"""Static water-fraction layer for a study-area cutout (design: docs/dasymetric_v3_1.md).

Settings: the `water:` block of configs/study_area.yaml. Reads the existing cutout's window.json and writes
  <cutout>/layers/water_frac/water_frac.tif   share of permanent-water 30 m pixels per 250 m cell, float32 0-1,
                                              NaN where no JRC tile covers the cell
  <cutout>/qa/water_qa.csv                    QA (item, value)

Steps:
  1. JRC Global Surface Water occurrence tiles (EPSG:4326, 30 m): every file matching `jrc_glob` in `jrc_dir`
     whose bounds overlap the window is used (tile names are not hard-coded). Permanent water = occurrence
     >= `occurrence_min`. Values above 100 (JRC no data) count as not water and are reported.
  2. HydroLAKES polygons with Lake_type in `reservoir_types` (reservoirs) are set to not water (pixel centre
     inside the polygon). Only features intersecting the window are read.
  3. The 0/1 mask is averaged onto the HISDAC 250 m window grid, block by block: each 30 m pixel centre is
     assigned to the cell it falls in, weighted by cos(lat) (exact area weighting on the rotated grid), so
     memory stays small for any window size.

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


def cell_shares(wcfg: dict, tiles, res, lakes, transform, H: int, W: int, crs):
    """Per 250 m cell of the window: (water share, JRC no-data share, stats). Both shares are area-weighted
    over the covered 30 m pixels: each pixel centre goes to the cell it falls in, weighted by cos(lat).
    GDAL `average` is not used: on a grid rotated against lon/lat it also counts pixels outside the cell.
    Cells without any covered pixel are NaN in both. Water = occurrence >= occurrence_min and <= 100,
    minus pixels inside `lakes` (reservoirs); no data = occurrence > 100."""
    to_xy = Transformer.from_crs(4326, crs, always_xy=True)
    frac = np.full((H, W), np.nan, dtype="float32")
    nodata = np.full((H, W), np.nan, dtype="float32")
    stats = {"jrc_pixels": 0, "jrc_nodata_pixels": 0, "water_pixels": 0, "reservoir_pixels_removed": 0}
    blk = int(wcfg.get("block", 256))
    pad = 2 * max(res)
    n_blocks = math.ceil(H / blk) * math.ceil(W / blk)
    for k, (r0, c0) in enumerate((r, c) for r in range(0, H, blk) for c in range(0, W, blk)):
        h, w = min(blk, H - r0), min(blk, W - c0)
        btr = transform * Affine.translation(c0, r0)
        bb = rasterio.transform.array_bounds(h, w, btr)  # west, south, east, north
        bll = transform_bounds(crs, "EPSG:4326", bb[0], bb[1], bb[2], bb[3], densify_pts=21)
        bll = (bll[0] - pad, bll[1] - pad, bll[2] + pad, bll[3] + pad)
        occ, covered, str_ = source_block(tiles, res, bll)
        valid = covered & (occ <= 100)
        water = (valid & (occ >= wcfg["occurrence_min"])).astype("float32")
        if lakes is not None and len(lakes):
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
        for target, values in ((frac, water), (nodata, nd)):
            num = np.bincount(idx, weights=wt * values[ok], minlength=h * w)
            out = np.full(h * w, np.nan, dtype="float32")
            out[has] = num[has] / den[has]
            target[r0:r0 + h, c0:c0 + w] = out.reshape(h, w)
        if (k + 1) % 20 == 0 or k + 1 == n_blocks:
            log.info("  block %d/%d", k + 1, n_blocks)
    return frac, nodata, stats


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
    log.info("cutout %s | window %d x %d cells | occurrence >= %s = water | reservoir types %s", cut, W, H,
             wcfg["occurrence_min"], wcfg["reservoir_types"])
    tiles, res = jrc_tiles(wcfg, bounds_ll)
    lakes = reservoirs(wcfg, bounds_ll)

    frac, _, stats = cell_shares(wcfg, tiles, res, lakes, transform, H, W, crs)

    # QA
    zone_any = np.zeros((H, W), bool)
    for y in cfg["years"]:
        zp = cut / "zones" / f"zones_{y}.tif"
        if zp.exists():
            with rasterio.open(zp) as src:
                zone_any |= src.read(1) > 0
    v = frac[~np.isnan(frac)]
    fail = []
    if v.size and (v.min() < 0 or v.max() > 1 + 1e-6):
        fail.append(f"water_frac outside 0-1: {v.min()}..{v.max()}")
    unc = np.isnan(frac) & zone_any
    uncovered = int(unc.sum())
    if uncovered:  # name the 10-degree JRC tiles (west edge, north edge) that would cover those cells
        rr, cc = np.where(unc)
        lon, lat = to_ll.transform(transform.c + (cc + 0.5) * transform.a, transform.f + (rr + 0.5) * transform.e)
        names = sorted({f"{abs(int(math.floor(x / 10) * 10))}{'W' if x < 0 else 'E'}_"
                        f"{abs(int(math.ceil(y / 10) * 10))}{'N' if y > 0 else 'S'}" for x, y in zip(lon, lat)})
        fail.append(f"{uncovered} study-county cells have no JRC coverage; missing tiles {names} "
                    f"(occurrence_<tile>v1_4_2021.tif in {wcfg['jrc_dir']})")
    np.clip(frac, 0, 1, out=frac)
    zf = frac[zone_any & ~np.isnan(frac)]
    qa = {"window_cells": H * W, "window_nodata_cells": int(np.isnan(frac).sum()), "study_cells": int(zone_any.sum()),
          "study_uncovered_cells": uncovered, "min": float(v.min()) if v.size else np.nan,
          "max": float(v.max()) if v.size else np.nan, "study_mean": float(zf.mean()) if zf.size else np.nan,
          "study_share_gt0": float((zf > 0).mean()) if zf.size else np.nan,
          "study_share_eq1": float((zf >= 1).mean()) if zf.size else np.nan, **stats,
          "jrc_nodata_share": stats["jrc_nodata_pixels"] / max(stats["jrc_pixels"], 1)}
    log.info("water_frac %s..%s | study counties: %d cells, mean %.4f, share > 0 %.4f, share = 1 %.4f, uncovered %d | "
             "JRC no-data pixels %.4f of covered | water pixels %d, reservoir pixels removed %d", qa["min"], qa["max"],
             qa["study_cells"], qa["study_mean"], qa["study_share_gt0"], qa["study_share_eq1"], uncovered,
             qa["jrc_nodata_share"], stats["water_pixels"], stats["reservoir_pixels_removed"])
    inv = ~transform
    for pt in wcfg.get("qa_points") or []:
        x, y = to_xy.transform(pt["lon"], pt["lat"])
        half = pt.get("box_km", 5) * 500.0
        ca, ra = inv * (x - half, y + half)
        cb, rb = inv * (x + half, y - half)
        sl = frac[max(int(ra), 0):max(int(math.ceil(rb)), 0), max(int(ca), 0):max(int(math.ceil(cb)), 0)]
        s = sl[~np.isnan(sl)]
        r = {"cells": int(s.size), "mean": float(s.mean()) if s.size else np.nan,
             "max": float(s.max()) if s.size else np.nan, "share_eq0": float((s == 0).mean()) if s.size else np.nan}
        expect = pt.get("expect")
        # dry: the box (e.g. over a removed reservoir) is nearly all land; full_water: some all-water cell
        r["n_eq1"] = int((s >= 1).sum())
        ok = (r["mean"] <= 0.1) if expect == "dry" else (r["n_eq1"] > 0) if expect == "full_water" else True
        msg = (f"  QA point {pt['name']} ({pt['lon']}, {pt['lat']}, {pt.get('box_km', 5)} km box): {r['cells']} cells, "
               f"mean {r['mean']:.3f}, max {r['max']:.3f}, share = 0 {r['share_eq0']:.3f}, cells = 1 {r['n_eq1']} | "
               f"expect {expect}: "
               f"{'ok' if ok else 'NOT MET'}")
        (log.info if ok else log.warning)(msg)
        qa.update({f"{pt['name']}: {k}": val for k, val in r.items()})
        qa[f"{pt['name']}: expect {expect}"] = "ok" if ok else "not met"

    qpath = cut / "qa" / "water_qa.csv"
    qpath.parent.mkdir(parents=True, exist_ok=True)
    pd.Series(qa, name="value").to_csv(qpath, index_label="item")
    log.info("wrote %s", qpath)
    if fail:  # the layer is not written, so no later stage can use it
        sys.exit("ERROR: water_frac QA failed (layer not written):\n  " + "\n  ".join(fail))
    out_path = cut / "layers" / wcfg.get("out", "water_frac/water_frac.tif")
    write_tif(out_path, frac, transform, crs, float("nan"))
    log.info("wrote %s", out_path)
    log.info("DONE")


if __name__ == "__main__":
    main()
