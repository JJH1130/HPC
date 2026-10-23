"""Water-fraction layer(s) for a study-area cutout (design: docs/dasymetric_v3_1.md; yearly GDW version:
docs/dasymetric_v4.md).

Settings: the `water:` block of configs/study_area.yaml. Reads the existing cutout's window.json and writes
  reservoir_source: hydrolakes (default, v3.1) -> one static layer
    <cutout>/layers/water_frac/water_frac.tif         share of permanent-water 30 m pixels per 250 m cell,
                                                      float32 0-1, NaN where no JRC tile covers the cell
  reservoir_source: gdw (v4) -> one layer per study year
    <cutout>/layers/water_frac/{YEAR}_water_frac.tif  same, but a Global Dam Watch reservoir counts as water
                                                      only from its completion year (rule in step 2b)
  <cutout>/qa/water_qa.csv                            QA (item, value)

Steps:
  1. JRC Global Surface Water occurrence tiles (EPSG:4326, 30 m): every file matching `jrc_glob` in `jrc_dir`
     whose bounds overlap the window is used (tile names are not hard-coded). Permanent water = occurrence
     >= `occurrence_min`. Values above 100 (JRC no data, 255) count as water if `nodata_as_water` is true
     (checked with src/grid/jrc_nodata_check.py: in Massachusetts they lie only on the open sea), else as
     not water; their share is reported either way.
  2. HydroLAKES polygons with Lake_type in `reservoir_types` (reservoirs) are set to not water (pixel centre
     inside the polygon). Only features intersecting the window are read.
  2b. (reservoir_source: gdw) Global Dam Watch reservoir polygons (`gdw` block) get an effective year:
     LAKE_CTRL in `lake_ctrl_water` (a natural lake raised by a dam) -> not a reservoir, JRC decides in every
     year; QUALITY <= `quality_max` and YEAR_DAM > 0 -> YEAR_DAM; otherwise (no year, or quality 4-5) -> never
     water (as HydroLAKES in v3.1). In census year Y a reservoir pixel is water only if its year <= Y.
  3. The 0/1 mask is averaged onto the HISDAC 250 m window grid, block by block: each 30 m pixel centre is
     assigned to the cell it falls in, weighted by cos(lat) (exact area weighting on the rotated grid), so
     memory stays small for any window size. Blocks run in SLURM_CPUS_ON_NODE processes (same result as one).
     `only_zone_blocks: true` (CONUS) computes only blocks holding a study cell (zone > 0 in any year); the
     others stay NaN. --years (gdw) writes only those years' layers.

Fails if a cell of the study counties (zone > 0 in any year) has no JRC coverage, or a value is outside 0-1.
The QA points (`qa_points`) are reported: `expect: dry` = box mean <= 0.1 (e.g. a removed reservoir),
`expect: full_water` = at least one cell with water_frac = 1 in the box (cells the v3.1 water mask can drop
where BUI = 0). A point whose expectation fails is a warning, not an error.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import rasterio
from affine import Affine
from pyproj import CRS, Transformer
from rasterio.features import rasterize
from rasterio.warp import transform_bounds
from rasterio.windows import Window

from make_cutout import load_config, write_tif

log = logging.getLogger("water_frac")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, required=True, help="configs/study_area.yaml (its water: block)")
    p.add_argument("--cutout-root", type=Path, required=True, help="cutout is <cutout-root>/<name>/")
    p.add_argument("--years", type=int, nargs="+",
                   help="gdw only: write only these study years' layers (default: all study years)")
    return p.parse_args(argv)


def jrc_tiles(wcfg: dict, bounds_ll):
    """(path, bounds, res) of the JRC tiles overlapping bounds_ll (lon/lat), all on one lon/lat grid."""
    folder = Path(wcfg["jrc_dir"])
    files = sorted(folder.glob(wcfg["jrc_glob"]))
    if not files:
        sys.exit(f"ERROR: no file matches {wcfg['jrc_glob']!r} in {folder}")
    hits, res = [], None
    for f in files:
        with rasterio.open(f) as src:
            b = src.bounds
            if b.right <= bounds_ll[0] or b.left >= bounds_ll[2] or b.top <= bounds_ll[1] or b.bottom >= bounds_ll[3]:
                continue
            if not CRS.from_user_input(src.crs).equals(CRS.from_epsg(4326)):
                sys.exit(f"ERROR: {f} is not EPSG:4326 ({src.crs})")
            r = (src.transform.a, -src.transform.e)
            if res is not None and not np.allclose(r, res):
                sys.exit(f"ERROR: {f} has pixel size {r}, other tiles {res}")
            res = r
            hits.append((f, b))
    log.info("JRC: %d files in %s, %d overlap the window (lon %.3f..%.3f, lat %.3f..%.3f): %s", len(files), folder,
             len(hits), bounds_ll[0], bounds_ll[2], bounds_ll[1], bounds_ll[3], [h[0].name for h in hits])
    if not hits:
        sys.exit("ERROR: no JRC tile overlaps the window")
    return hits, res


def reservoirs(wcfg: dict, bounds_ll):
    path = Path(wcfg["hydrolakes"])
    if not path.exists():
        sys.exit(f"ERROR: {path} not found")
    types = [int(t) for t in wcfg["reservoir_types"]]
    gdf = pyogrio.read_dataframe(path, bbox=tuple(bounds_ll), columns=["Hylak_id", "Lake_name", "Lake_type"],
                                 where=f"Lake_type IN ({', '.join(map(str, types))})")
    if gdf.crs is not None and not CRS.from_user_input(gdf.crs).equals(CRS.from_epsg(4326)):
        gdf = gdf.to_crs(4326)
    log.info("HydroLAKES: %d polygons with Lake_type in %s intersect the window (%s)", len(gdf), types,
             ", ".join(sorted(n for n in gdf["Lake_name"].dropna().unique()[:10])) or "-")
    return gdf


NEVER = 9999  # effective year of a GDW reservoir that never counts as water (no year, or low quality)


def reservoirs_gdw(wcfg: dict, bounds_ll):
    """GDW reservoir polygons intersecting the window, with `eff_year` (step 2b). Natural lakes raised by a dam
    (LAKE_CTRL listed in lake_ctrl_water) are dropped: they stay water whenever JRC says so."""
    g = wcfg.get("gdw") or {}
    path = Path(g.get("path", ""))
    if not path.is_file():
        sys.exit(f"ERROR: water.gdw.path {path} not found (Global Dam Watch reservoirs shapefile)")
    gdf = pyogrio.read_dataframe(path, bbox=tuple(bounds_ll),
                                 columns=["GDW_ID", "RES_NAME", "DAM_NAME", "YEAR_DAM", "QUALITY", "LAKE_CTRL"])
    if gdf.crs is not None and not CRS.from_user_input(gdf.crs).equals(CRS.from_epsg(4326)):
        gdf = gdf.to_crs(4326)
    qmax = int(g.get("quality_max", 3))
    ctrl = {str(v).lower() for v in g.get("lake_ctrl_water", ["Yes", "Maybe"])}
    q = pd.to_numeric(gdf["QUALITY"].astype(str).str.extract(r"^\s*(\d)")[0], errors="coerce")
    yr = pd.to_numeric(gdf["YEAR_DAM"], errors="coerce")
    is_ctrl = gdf["LAKE_CTRL"].astype(str).str.strip().str.lower().isin(ctrl)
    dated = (q <= qmax) & (yr > 0)
    gdf["eff_year"] = np.where(dated, yr, NEVER).astype(int)
    log.info("GDW: %d reservoir polygons intersect the window | %d natural lakes raised by a dam (LAKE_CTRL in %s) "
             "kept to JRC | %d dated (quality <= %d) | %d never water (no year or quality > %d)", len(gdf),
             int(is_ctrl.sum()), sorted(ctrl), int((dated & ~is_ctrl).sum()), qmax, int((~dated & ~is_ctrl).sum()), qmax)
    gdf = gdf[~is_ctrl]
    big = gdf.assign(name=gdf["RES_NAME"].fillna(gdf["DAM_NAME"])).sort_values("eff_year")
    named = [f"{n} ({y if y != NEVER else 'never'})" for n, y in zip(big["name"].fillna("?"), big["eff_year"])][:15]
    log.info("GDW reservoirs (first 15 by year): %s", ", ".join(named) or "-")
    return gdf


def source_block(tiles, res, bounds_ll):
    """Occurrence mosaic (uint8, 255 = not covered) on the shared JRC grid over bounds_ll, + its transform."""
    rx, ry = res
    x0 = min(t[1].left for t in tiles)  # grid origin shared by all tiles
    y0 = max(t[1].top for t in tiles)
    c0 = math.floor((bounds_ll[0] - x0) / rx)
    c1 = math.ceil((bounds_ll[2] - x0) / rx)
    r0 = math.floor((y0 - bounds_ll[3]) / ry)
    r1 = math.ceil((y0 - bounds_ll[1]) / ry)
    tr = Affine(rx, 0, x0 + c0 * rx, 0, -ry, y0 - r0 * ry)
    occ = np.full((r1 - r0, c1 - c0), 255, dtype="uint8")
    covered = np.zeros(occ.shape, bool)
    for path, b in tiles:
        # this tile's pixel range inside the block (all tiles share the grid, so offsets are whole pixels)
        tc0, tr0 = round((b.left - x0) / rx), round((y0 - b.top) / ry)
        tw, th = round((b.right - b.left) / rx), round((b.top - b.bottom) / ry)
        cs0, cs1 = max(c0, tc0), min(c1, tc0 + tw)
        rs0, rs1 = max(r0, tr0), min(r1, tr0 + th)
        if cs0 >= cs1 or rs0 >= rs1:
            continue
        with rasterio.open(path) as src:
            arr = src.read(1, window=Window(cs0 - tc0, rs0 - tr0, cs1 - cs0, rs1 - rs0))
        occ[rs0 - r0:rs1 - r0, cs0 - c0:cs1 - c0] = arr
        covered[rs0 - r0:rs1 - r0, cs0 - c0:cs1 - c0] = True
    return occ, covered, tr


_JOB = {}  # block job settings; set in the main process or, with workers, in each worker (pool initializer)


def _init(job: dict):
    _JOB.clear()
    _JOB.update(job)


def cell_shares(wcfg: dict, tiles, res, lakes, transform, H: int, W: int, crs, res_years=None, years=None,
                need=None, workers: int = 1):
    """Per 250 m cell of the window: (water share, JRC no-data share, stats). Both shares are area-weighted
    over the covered 30 m pixels: each pixel centre goes to the cell it falls in, weighted by cos(lat).
    GDAL `average` is not used: on a grid rotated against lon/lat it also counts pixels outside the cell.
    Cells without any covered pixel are NaN in both. Water = occurrence >= occurrence_min and <= 100,
    (plus no data = occurrence > 100 if wcfg nodata_as_water), minus pixels inside `lakes` (reservoirs).
    With `res_years` (GDW polygons with eff_year) and `years`, the water share is returned as {year: array}:
    a reservoir pixel is water in year Y only if its eff_year <= Y (step 2b); `lakes` is then not used.
    `need` (bool H x W, optional): blocks without any True cell are skipped and stay NaN (CONUS:
    only_zone_blocks). `workers` > 1 computes the blocks in that many processes; the result is the same."""
    yearly = res_years is not None
    if yearly:
        frac = {y: np.full((H, W), np.nan, dtype="float32") for y in years}
    else:
        frac = np.full((H, W), np.nan, dtype="float32")
    nodata = np.full((H, W), np.nan, dtype="float32")
    stats = {"jrc_pixels": 0, "jrc_nodata_pixels": 0, "water_pixels": 0, "reservoir_pixels_removed": 0}
    if yearly:
        stats.update({f"reservoir_pixels_water_{y}": 0 for y in years})
    blk = int(wcfg.get("block", 256))
    blocks = [(r, c, min(blk, H - r), min(blk, W - c)) for r in range(0, H, blk) for c in range(0, W, blk)]
    n_all = len(blocks)
    if need is not None:
        blocks = [b for b in blocks if need[b[0]:b[0] + b[2], b[1]:b[1] + b[3]].any()]
    log.info("  %d of %d blocks of %d x %d cells to compute (%s), %d worker process(es)", len(blocks), n_all, blk, blk,
             "blocks with study cells" if need is not None else "all", workers)
    job = {"wcfg": wcfg, "tiles": tiles, "res": res, "lakes": lakes, "transform": transform, "crs": crs,
           "res_years": res_years, "years": years}
    if workers > 1:
        import multiprocessing as mp
        pool = mp.get_context("spawn").Pool(workers, initializer=_init, initargs=(job,))
        results = pool.imap_unordered(_block, blocks, chunksize=1)
    else:
        _init(job)
        pool, results = None, map(_block, blocks)
    try:
        for k, (r0, c0, h, w, outs, nd_out, st) in enumerate(results):
            for key, v in outs.items():
                (frac[key] if yearly else frac)[r0:r0 + h, c0:c0 + w] = v
            nodata[r0:r0 + h, c0:c0 + w] = nd_out
            for key, v in st.items():
                stats[key] += v
            if (k + 1) % 20 == 0 or k + 1 == len(blocks):
                log.info("  block %d/%d", k + 1, len(blocks))
    finally:
        if pool is not None:
            pool.close()
            pool.join()
    return frac, nodata, stats


def _block(b):
    """One block of cells: ({year or None: water share}, no-data share, stats). Settings come from _JOB."""
    r0, c0, h, w = b
    j = _JOB
    wcfg, tiles, res, lakes, transform, crs = j["wcfg"], j["tiles"], j["res"], j["lakes"], j["transform"], j["crs"]
    res_years, years = j["res_years"], j["years"]
    yearly = res_years is not None
    to_xy = Transformer.from_crs(4326, crs, always_xy=True)
    pad = 2 * max(res)
    stats = {"jrc_pixels": 0, "jrc_nodata_pixels": 0, "water_pixels": 0, "reservoir_pixels_removed": 0}
    if yearly:
        stats.update({f"reservoir_pixels_water_{y}": 0 for y in years})
    btr = transform * Affine.translation(c0, r0)
    bb = rasterio.transform.array_bounds(h, w, btr)  # west, south, east, north
    bll = transform_bounds(crs, "EPSG:4326", bb[0], bb[1], bb[2], bb[3], densify_pts=21)
    bll = (bll[0] - pad, bll[1] - pad, bll[2] + pad, bll[3] + pad)
    occ, covered, str_ = source_block(tiles, res, bll)
    valid = covered & (occ <= 100)
    wet = valid & (occ >= wcfg["occurrence_min"])
    if wcfg.get("nodata_as_water"):
        wet |= covered & (occ > 100)
    water = wet.astype("float32")
    layers = None  # yearly: {year: water array}
    if yearly:
        ry = np.zeros(occ.shape, dtype="int16")  # 0 = not a GDW reservoir
        sub = res_years.cx[bll[0]:bll[2], bll[1]:bll[3]]
        if len(sub):
            ry = rasterize(((g, int(y)) for g, y in zip(sub.geometry, sub["eff_year"])), out_shape=occ.shape,
                           transform=str_, fill=0, dtype="int16")
        inres = ry > 0
        stats["reservoir_pixels_removed"] += int((wet & inres & (ry == NEVER)).sum())
        layers = {}
        for y in years:
            wy = wet & (~inres | (ry <= y))
            stats[f"reservoir_pixels_water_{y}"] += int((wet & inres & (ry <= y)).sum())
            layers[y] = wy  # bool: 22 float32 copies of a block would need ~4x the memory
        water = layers[years[-1]].astype("float32")
    elif lakes is not None and len(lakes):
        sub = lakes.cx[bll[0]:bll[2], bll[1]:bll[3]]
        if len(sub):
            inres = rasterize(((g, 1) for g in sub.geometry), out_shape=occ.shape, transform=str_, fill=0,
                              dtype="uint8").astype(bool)
            stats["reservoir_pixels_removed"] += int((water.astype(bool) & inres).sum())
            water[inres] = 0
    nd = (covered & (occ > 100)).astype("float32")
    stats["jrc_pixels"] += int(covered.sum())
    stats["jrc_nodata_pixels"] += int(nd.sum())
    stats["water_pixels"] += int(water.sum())
    lon = str_.c + (np.arange(occ.shape[1]) + 0.5) * str_.a
    lat = str_.f + (np.arange(occ.shape[0]) + 0.5) * str_.e
    LON, LAT = np.meshgrid(lon, lat)
    X, Y = to_xy.transform(LON, LAT)
    col = np.floor((X - btr.c) / btr.a).astype(np.int64)
    row = np.floor((Y - btr.f) / btr.e).astype(np.int64)
    ok = covered & (row >= 0) & (row < h) & (col >= 0) & (col < w)
    idx = row[ok] * w + col[ok]
    wt = np.cos(np.radians(LAT[ok]))
    den = np.bincount(idx, weights=wt, minlength=h * w)
    has = den > 0  # cells without any covered pixel stay NaN

    def share(values):
        num = np.bincount(idx, weights=wt * values[ok], minlength=h * w)
        out = np.full(h * w, np.nan, dtype="float32")
        out[has] = num[has] / den[has]
        return out.reshape(h, w)

    outs = {y: share(layers[y]) for y in years} if yearly else {None: share(water)}
    return r0, c0, h, w, outs, share(nd), stats


def nodata_by_county(cut: Path, zone_last, ndshare, frac, top: int = 20):
    """Per county of the last zone grid: mean JRC no-data share of its cells, cells with share > 0.5, and the share of
    cells with water_frac = 1 (last layer). Writes qa/water_jrc_nodata_by_county.csv (counties with any no data,
    largest mean first) and logs the top `top`: is JRC no data (counted as water) on land inside counties?"""
    year, z = zone_last
    table = pd.read_csv(cut / "zones" / f"zones_{year}.csv")
    nz = max(int(z.max()), int(table["zone_id"].max())) + 1
    inz = z > 0
    zi = z[inz]
    nd = np.nan_to_num(ndshare[inz])
    cells = np.bincount(zi, minlength=nz)
    out = table[["zone_id", "GISJOIN", "state", "name"]].copy()
    ids = out["zone_id"].to_numpy()
    out["cells"] = cells[ids]
    with np.errstate(invalid="ignore", divide="ignore"):
        out["nodata_mean"] = np.bincount(zi, weights=nd, minlength=nz)[ids] / cells[ids]
        out["water_eq1_share"] = np.bincount(zi, weights=(np.nan_to_num(frac[inz]) >= 1), minlength=nz)[ids] / cells[ids]
    out["cells_nodata_gt50"] = np.bincount(zi, weights=nd > 0.5, minlength=nz)[ids].astype(int)
    out = out[out["nodata_mean"] > 0].sort_values("nodata_mean", ascending=False)
    path = cut / "qa" / "water_jrc_nodata_by_county.csv"
    out.to_csv(path, index=False)
    log.info("JRC no data by county (zones %d): %d counties with any; top %d by mean share (also %s):\n%s", year,
             len(out), top, path.name, out.head(top).round(5).to_string(index=False))


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    wcfg = cfg.get("water")
    if not wcfg:
        sys.exit(f"ERROR: no water: block in {args.config}")
    cut = args.cutout_root / cfg["name"]
    wpath = cut / "window.json"
    if not wpath.exists():
        sys.exit(f"ERROR: {wpath} not found (run the cutout first)")
    win = json.loads(wpath.read_text())
    crs = CRS.from_wkt(win["crs_wkt"])
    transform = Affine(*win["transform"])
    H, W = int(win["height"]), int(win["width"])
    to_xy = Transformer.from_crs(4326, crs, always_xy=True)
    to_ll = Transformer.from_crs(crs, 4326, always_xy=True)
    bounds_ll = transform_bounds(crs, "EPSG:4326", *win["bounds"], densify_pts=101)
    source = str(wcfg.get("reservoir_source", "hydrolakes")).lower()
    if source not in ("hydrolakes", "gdw"):
        sys.exit(f"ERROR: water.reservoir_source must be hydrolakes or gdw, not {source!r}")
    years = list(cfg["years"])
    if args.years:
        if source != "gdw":
            sys.exit("ERROR: --years only applies to the yearly layers (reservoir_source: gdw)")
        bad = sorted(set(args.years) - set(years))
        if bad:
            sys.exit(f"ERROR: --years {bad} not in the config years")
        years = sorted(set(args.years))
    workers = int(os.environ.get("SLURM_CPUS_ON_NODE", "1"))
    log.info("cutout %s | window %d x %d cells | occurrence >= %s = water | JRC no data = %s | reservoirs: %s",
             cut, W, H, wcfg["occurrence_min"], "water" if wcfg.get("nodata_as_water") else "not water",
             f"HydroLAKES Lake_type {wcfg['reservoir_types']} never water" if source == "hydrolakes"
             else f"GDW, water from completion year (yearly layers {years})")
    # study cells (zone > 0 in any year): QA, and with only_zone_blocks the only blocks computed (CONUS)
    zone_any = np.zeros((H, W), bool)
    zone_last = None  # (year, zones) of the last study year with a zone grid: per-county JRC no-data QA
    for y in cfg["years"]:
        zp = cut / "zones" / f"zones_{y}.tif"
        if zp.exists():
            with rasterio.open(zp) as src:
                z = src.read(1)
            zone_any |= z > 0
            zone_last = (y, z)
    need = zone_any if wcfg.get("only_zone_blocks") else None
    if need is not None and not need.any():
        sys.exit(f"ERROR: only_zone_blocks: no zones_{{YEAR}}.tif with study cells in {cut / 'zones'}")
    tiles, res = jrc_tiles(wcfg, bounds_ll)
    if source == "gdw":
        gdw = reservoirs_gdw(wcfg, bounds_ll)
        layers, ndshare, stats = cell_shares(wcfg, tiles, res, None, transform, H, W, crs, res_years=gdw, years=years,
                                       need=need, workers=workers)
    else:
        lakes = reservoirs(wcfg, bounds_ll)
        frac, ndshare, stats = cell_shares(wcfg, tiles, res, lakes, transform, H, W, crs, need=need, workers=workers)
        layers = {None: frac}

    # QA (summary on the last layer; masked-cell shares per year for the yearly layers)
    last = list(layers)[-1]
    frac = layers[last]
    v = frac[~np.isnan(frac)]
    fail = []
    for key, arr in layers.items():
        a = arr[~np.isnan(arr)]
        if a.size and (a.min() < 0 or a.max() > 1 + 1e-6):
            fail.append(f"water_frac {key or ''} outside 0-1: {a.min()}..{a.max()}")
    unc = np.isnan(frac) & zone_any
    uncovered = int(unc.sum())
    if uncovered:  # name the 10-degree JRC tiles (west edge, north edge) that would cover those cells
        rr, cc = np.where(unc)
        lon, lat = to_ll.transform(transform.c + (cc + 0.5) * transform.a, transform.f + (rr + 0.5) * transform.e)
        names = sorted({f"{abs(int(math.floor(x / 10) * 10))}{'W' if x < 0 else 'E'}_"
                        f"{abs(int(math.ceil(y / 10) * 10))}{'N' if y > 0 else 'S'}" for x, y in zip(lon, lat)})
        fail.append(f"{uncovered} study-county cells have no JRC coverage; missing tiles {names} "
                    f"(occurrence_<tile>v1_4_2021.tif in {wcfg['jrc_dir']})")
    for arr in layers.values():
        np.clip(arr, 0, 1, out=arr)
    zf = frac[zone_any & ~np.isnan(frac)]
    qa = {"reservoir_source": source, "window_cells": H * W, "window_nodata_cells": int(np.isnan(frac).sum()),
          "study_cells": int(zone_any.sum()), "study_uncovered_cells": uncovered,
          "min": float(v.min()) if v.size else np.nan, "max": float(v.max()) if v.size else np.nan,
          "study_mean": float(zf.mean()) if zf.size else np.nan,
          "study_share_gt0": float((zf > 0).mean()) if zf.size else np.nan,
          "study_share_eq1": float((zf >= 1).mean()) if zf.size else np.nan, **stats,
          # JRC no data inside the study counties (counted as water if nodata_as_water): mean share per cell and
          # cells that are mostly no data; checked on the open sea only so far (Massachusetts)
          "study_jrc_nodata_mean": float(np.nanmean(ndshare[zone_any])) if zone_any.any() else np.nan,
          "study_cells_jrc_nodata_gt50": int((np.nan_to_num(ndshare[zone_any]) > 0.5).sum()),
          "jrc_nodata_share": stats["jrc_nodata_pixels"] / max(stats["jrc_pixels"], 1)}
    if source == "gdw":
        for y, arr in layers.items():
            s = arr[zone_any & ~np.isnan(arr)]
            qa[f"study_share_eq1_{y}"] = float((s >= 1).mean()) if s.size else np.nan
            log.info("  %d: study cells with water_frac = 1: %.4f | reservoir water pixels %d", y,
                     qa[f"study_share_eq1_{y}"], stats[f"reservoir_pixels_water_{y}"])
    log.info("water_frac (%s) %s..%s | study counties: %d cells, mean %.4f, share > 0 %.4f, share = 1 %.4f, "
             "uncovered %d | JRC no-data pixels %.4f of covered | water pixels %d, reservoir pixels never water %d",
             last or "static", qa["min"], qa["max"], qa["study_cells"], qa["study_mean"], qa["study_share_gt0"],
             qa["study_share_eq1"], uncovered, qa["jrc_nodata_share"], stats["water_pixels"],
             stats["reservoir_pixels_removed"])
    log.info("JRC no data in study cells: mean share %.5f | cells with share > 0.5: %d (counted as %s)",
             qa["study_jrc_nodata_mean"], qa["study_cells_jrc_nodata_gt50"],
             "water" if wcfg.get("nodata_as_water") else "not water")
    inv = ~transform
    for pt in wcfg.get("qa_points") or []:
        py = pt.get("year")
        if source == "gdw":
            if py is not None and int(py) not in layers:
                log.warning("  QA point %s: year %s is not among the layers written; skipped", pt["name"], py)
                continue
            arr = layers[int(py)] if py is not None else frac
        else:
            arr = frac
        label = f"{pt['name']}" + (f" {py}" if py is not None else "")  # unique QA keys in both modes
        x, y = to_xy.transform(pt["lon"], pt["lat"])
        half = pt.get("box_km", 5) * 500.0
        ca, ra = inv * (x - half, y + half)
        cb, rb = inv * (x + half, y - half)
        sl = arr[max(int(ra), 0):max(int(math.ceil(rb)), 0), max(int(ca), 0):max(int(math.ceil(cb)), 0)]
        s = sl[~np.isnan(sl)]
        r = {"cells": int(s.size), "mean": float(s.mean()) if s.size else np.nan,
             "max": float(s.max()) if s.size else np.nan, "share_eq0": float((s == 0).mean()) if s.size else np.nan}
        expect = pt.get("expect")
        # dry: the box (e.g. over a reservoir before its dam) is nearly all land; full_water: some all-water cell
        r["n_eq1"] = int((s >= 1).sum())
        ok = (r["mean"] <= 0.1) if expect == "dry" else (r["n_eq1"] > 0) if expect == "full_water" else True
        msg = (f"  QA point {label} ({pt['lon']}, {pt['lat']}, {pt.get('box_km', 5)} km box): {r['cells']} cells, "
               f"mean {r['mean']:.3f}, max {r['max']:.3f}, share = 0 {r['share_eq0']:.3f}, cells = 1 {r['n_eq1']} | "
               f"expect {expect}: {'ok' if ok else 'NOT MET'}")
        (log.info if ok else log.warning)(msg)
        qa.update({f"{label}: {k}": val for k, val in r.items()})
        qa[f"{label}: expect {expect}"] = "ok" if ok else "not met"

    qpath = cut / "qa" / "water_qa.csv"
    qpath.parent.mkdir(parents=True, exist_ok=True)
    pd.Series(qa, name="value").to_csv(qpath, index_label="item")
    log.info("wrote %s", qpath)
    if zone_last is not None:
        nodata_by_county(cut, zone_last, ndshare, frac)
    if fail:  # the layer is not written, so no later stage can use it
        sys.exit("ERROR: water_frac QA failed (layer not written):\n  " + "\n  ".join(fail))
    if source == "gdw":
        pattern = wcfg.get("yearly_out", "water_frac/{YEAR}_water_frac.tif")
        for y, arr in layers.items():
            out_path = cut / "layers" / pattern.format(YEAR=y)
            write_tif(out_path, arr, transform, crs, float("nan"))
        log.info("wrote %d yearly layers %s", len(layers), cut / "layers" / pattern)
    else:
        out_path = cut / "layers" / wcfg.get("out", "water_frac/water_frac.tif")
        write_tif(out_path, frac, transform, crs, float("nan"))
        log.info("wrote %s", out_path)
    log.info("DONE")


if __name__ == "__main__":
    main()
