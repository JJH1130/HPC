"""Cut a study-area window out of the HISDAC-US V2 rasters, plus per-year county zone grids.

Reads configs/study_area.yaml (rules: docs/cutout.md) and writes to <out-root>/<name>/:
  window.json                      the shared window (HISDAC grid offsets, transform, bounds)
  layers/{LAYER}/{YEAR}_{LAYER}.tif  yearly layers (BUI, BUPL, BUPR, BUA), int32, deflate
  layers/{LAYER}/<source name>.tif   single-file layers (FBUY, NobuiltYear)
  zones/zones_{YEAR}.tif           county id per cell (uint16, 0 = nodata), cell-center rasterize
  zones/zones_{YEAR}.csv           zone_id <-> GISJOIN, state, name, pop, status, area_km2
  cutout_qa.csv                    per year and county: cells assigned, cell area / county area

Steps:
  1. Pick counties whose `state` is in the config (or all) from each year's counties_{YEAR}.gpkg.
  2. One rectangle = union of the picked counties over ALL config years, snapped outward to
     the HISDAC grid (same origin, 250 m, ESRI:102039). Every year and layer shares it.
  3. Windowed reads of each HISDAC layer (never the whole CONUS array) -> int32 GeoTIFF.
     0 means "no building", so 0 is never nodata.
  4. zone_id = the county's GPKG feature id (1-based row number in counties_{YEAR}.gpkg).
     Counties not picked, and cells outside all counties, are 0.

Paths come from CLI flags (the sbatch script fills them from sbatch/cluster_env.sh).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio
import yaml
from rasterio.features import rasterize
from rasterio.windows import Window

INT32 = np.iinfo(np.int32)
ZONE_DTYPE = "uint16"
QA_COLS = ["year", "zone_id", "GISJOIN", "state", "name", "status", "area_km2",
           "n_cells", "cell_area_km2", "area_ratio"]

log = logging.getLogger("make_cutout")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, required=True, help="configs/study_area.yaml")
    p.add_argument("--hisdac-dir", type=Path, required=True, help="HISDAC_US_V2 root (read only)")
    p.add_argument("--census-dir", type=Path, required=True, help="folder with counties_{YEAR}.gpkg")
    p.add_argument("--out-root", type=Path, required=True, help="cutout goes to <out-root>/<name>/")
    p.add_argument("--years", type=int, nargs="+",
                   help="only write layers/zones for these years (the window still uses all config years)")
    return p.parse_args(argv)


# ---------------------------------------------------------------- config + inputs

def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    y = cfg["years"]
    cfg["years"] = list(range(y["start"], y["stop"] + 1, y["step"])) if isinstance(y, dict) else [int(v) for v in y]
    states = cfg["states"]
    cfg["all_states"] = isinstance(states, str) and states.lower() == "all"
    if not cfg["all_states"]:
        cfg["states"] = [states] if isinstance(states, str) else list(states)
    return cfg


def find_inputs(cfg: dict, hisdac_dir: Path, years) -> list[tuple[str, int | None, Path]]:
    """(layer, year or None, path) for every raster to cut; exits listing everything missing."""
    h, inputs, problems = cfg["hisdac"], [], []
    for layer in h["yearly_layers"]:
        for year in years:
            path = hisdac_dir / h["yearly_pattern"].format(LAYER=layer, YEAR=year)
            if path.exists():
                inputs.append((layer, year, path))
            else:
                problems.append(f"  missing: {path}")
    for layer, pattern in h.get("static_layers", {}).items():
        hits = sorted(hisdac_dir.glob(pattern))
        if len(hits) == 1:
            inputs.append((layer, None, hits[0]))
        else:
            problems.append(f"  {layer}: pattern {pattern!r} matched {len(hits)} files {[str(x) for x in hits]}")
    if problems:
        sys.exit(f"ERROR: HISDAC inputs under {hisdac_dir}:\n" + "\n".join(problems))
    return inputs


def check_grids(inputs) -> dict:
    """All rasters must share one grid; returns it (headers only, no pixels read)."""
    ref, bad = None, []
    for layer, year, path in inputs:
        with rasterio.open(path) as src:
            grid = {"transform": src.transform, "crs": src.crs, "width": src.width, "height": src.height,
                    "path": path}
            if ref is None:
                ref = grid
                log.info("reference grid: %s | %dx%d | cell %s x %s | origin (%s, %s) | %s",
                         path.name, src.width, src.height, src.transform.a, -src.transform.e,
                         src.transform.c, src.transform.f, src.crs.to_string() if src.crs else None)
            elif (not src.transform.almost_equals(ref["transform"]) or src.crs != ref["crs"]
                  or (src.width, src.height) != (ref["width"], ref["height"])):
                bad.append(f"  {path}: {src.width}x{src.height} {tuple(src.transform)[:6]} {src.crs}")
    if bad:
        sys.exit(f"ERROR: rasters not on the reference grid of {ref['path']}:\n" + "\n".join(bad))
    t = ref["transform"]
    if t.b != 0 or t.d != 0 or t.a != -t.e:
        sys.exit(f"ERROR: reference grid is rotated or has non-square cells: {t}")
    log.info("all %d rasters share the reference grid", len(inputs))
    return ref


def read_counties(census_dir: Path, year: int, cfg: dict, crs) -> gpd.GeoDataFrame:
    """Picked counties of one year, indexed by GPKG fid (= zone_id), in the raster CRS."""
    path = census_dir / f"counties_{year}.gpkg"
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (run census_prepare first)")
    where = None
    if not cfg["all_states"]:
        names = ", ".join("'" + s.lower().replace("'", "''") + "'" for s in cfg["states"])
        where = f"lower(trim(state)) IN ({names})"
    gdf = pyogrio.read_dataframe(path, where=where, fid_as_index=True)
    gdf.index.name = "zone_id"
    return gdf.to_crs(crs) if len(gdf) else gdf


# ---------------------------------------------------------------- window

def snapped_window(bounds, ref: dict) -> Window:
    """Smallest window on the reference grid that covers bounds (outward snap), clipped to it."""
    t = ref["transform"]
    cell = t.a
    minx, miny, maxx, maxy = bounds
    col0 = math.floor((minx - t.c) / cell)
    col1 = math.ceil((maxx - t.c) / cell)
    row0 = math.floor((t.f - maxy) / cell)
    row1 = math.ceil((t.f - miny) / cell)
    clipped = (max(col0, 0), max(row0, 0), min(col1, ref["width"]), min(row1, ref["height"]))
    if clipped != (col0, row0, col1, row1):
        log.warning("county bounds reach past the HISDAC extent; window clipped from cols %d-%d rows %d-%d",
                    col0, col1, row0, row1)
    col0, row0, col1, row1 = clipped
    if col1 <= col0 or row1 <= row0:
        sys.exit("ERROR: the picked counties don't overlap the HISDAC grid")
    return Window(col0, row0, col1 - col0, row1 - row0)


# ---------------------------------------------------------------- rasters

def to_int32(arr: np.ndarray, src_nodata, label: str):
    """Cast a layer to int32. 0 stays a value ("no building"); only the source's own nodata
    (or NaN) becomes nodata. Returns (array, nodata or None)."""
    nd = np.zeros(arr.shape, dtype=bool)
    if np.issubdtype(arr.dtype, np.floating):
        nd |= np.isnan(arr)
    keep_nd = src_nodata is not None and not (isinstance(src_nodata, float) and math.isnan(src_nodata))
    if keep_nd and src_nodata == 0:
        log.warning("  %s: source declares nodata=0; 0 means 'no building' here, so it is kept as a value",
                    label)
        keep_nd = False
    if keep_nd:
        nd |= arr == src_nodata
    valid = arr[~nd]
    if valid.size:
        if np.issubdtype(arr.dtype, np.floating) and not np.all(valid == np.round(valid)):
            sys.exit(f"ERROR: {label} has non-integer values; int32 would change them")
        if valid.min() < INT32.min or valid.max() > INT32.max:
            sys.exit(f"ERROR: {label} values {valid.min()}..{valid.max()} don't fit int32")
    out_nd = None
    if nd.any() or keep_nd:
        if keep_nd and float(src_nodata).is_integer() and INT32.min <= src_nodata <= INT32.max:
            out_nd = int(src_nodata)
        else:
            out_nd = -1
            if valid.size and (valid == -1).any():
                sys.exit(f"ERROR: {label} uses -1 as a value; pick another nodata")
    out = np.where(nd, out_nd if out_nd is not None else 0, arr).astype(np.int32)
    return out, out_nd, valid


def write_tif(path: Path, arr, transform, crs, nodata):
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    profile = dict(driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1, dtype=arr.dtype,
                   crs=crs, transform=transform, nodata=nodata, compress="deflate", predictor=2,
                   tiled=True, blockxsize=256, blockysize=256, BIGTIFF="IF_SAFER")
    with rasterio.open(part, "w", **profile) as dst:
        dst.write(arr, 1)
    os.replace(part, path)  # the final name only ever holds a complete file


def cut_layer(layer, year, path, window, out_dir, ref):
    label = f"{layer} {year}" if year else layer
    with rasterio.open(path) as src:
        arr = src.read(1, window=window)
        transform = src.window_transform(window)
        src_nodata, src_dtype = src.nodata, src.dtypes[0]
    out, out_nd, valid = to_int32(arr, src_nodata, label)
    name = f"{year}_{layer}.tif" if year else path.name
    out_path = out_dir / "layers" / layer / name
    write_tif(out_path, out, transform, ref["crs"], out_nd)
    log.info("  %-16s %s nodata=%s -> int32 nodata=%s | valid min %s max %s | zeros %d | nodata cells %d | %.1f MB",
             label, src_dtype, src_nodata, out_nd,
             valid.min() if valid.size else "-", valid.max() if valid.size else "-",
             int((valid == 0).sum()), int(out.size - valid.size),
             out_path.stat().st_size / 1e6)


def make_zones(year, cfg, args, window, ref, out_dir) -> pd.DataFrame:
    transform = rasterio.windows.transform(window, ref["transform"])
    counties = read_counties(args.census_dir, year, cfg, ref["crs"])
    if len(counties) and counties.index.max() > np.iinfo(ZONE_DTYPE).max:
        sys.exit(f"ERROR: {year} zone ids exceed {ZONE_DTYPE}")
    zones = rasterize(((geom, zid) for zid, geom in counties.geometry.items() if geom is not None),
                      out_shape=(int(window.height), int(window.width)), transform=transform,
                      fill=0, all_touched=False, dtype=ZONE_DTYPE)  # all_touched=False: cell center
    write_tif(out_dir / "zones" / f"zones_{year}.tif", zones, transform, ref["crs"], 0)
    table = counties.drop(columns="geometry").reset_index()
    table[["zone_id", "GISJOIN", "state", "name", "pop", "status", "area_km2"]].to_csv(
        out_dir / "zones" / f"zones_{year}.csv", index=False)

    ids, counts = np.unique(zones[zones > 0], return_counts=True)
    cell_km2 = ref["transform"].a ** 2 / 1e6
    qa = table.assign(year=year)
    qa["n_cells"] = qa["zone_id"].map(dict(zip(ids.tolist(), counts.tolist()))).fillna(0).astype(int)
    qa["cell_area_km2"] = qa["n_cells"] * cell_km2
    qa["area_ratio"] = qa["cell_area_km2"] / qa["area_km2"]
    zero = qa[qa["n_cells"] == 0]
    log.info("  zones %d: %d counties, %d cells assigned | area ratio min %.3f median %.3f max %.3f",
             year, len(qa), int(counts.sum()), qa["area_ratio"].min(), qa["area_ratio"].median(),
             qa["area_ratio"].max())
    if len(zero):
        log.warning("  zones %d: %d counties got 0 cells: %s", year, len(zero),
                    list(zip(zero["GISJOIN"], zero["name"], zero["area_km2"].round(2))))
    return qa[QA_COLS]


# ---------------------------------------------------------------- main

def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    out_dir = args.out_root / cfg["name"]
    years = cfg["years"] if args.years is None else sorted(set(args.years))
    if not set(years) <= set(cfg["years"]):
        sys.exit(f"ERROR: --years {sorted(set(years) - set(cfg['years']))} not in the config years")
    log.info("study area %r: states=%s | %d config years %d-%d | writing %d years -> %s",
             cfg["name"], "all" if cfg["all_states"] else cfg["states"], len(cfg["years"]),
             cfg["years"][0], cfg["years"][-1], len(years), out_dir)

    inputs = find_inputs(cfg, args.hisdac_dir, years)
    ref = check_grids(inputs)

    # window: union of picked counties over ALL config years
    bounds, seen_states = [], set()
    for year in cfg["years"]:
        c = read_counties(args.census_dir, year, cfg, ref["crs"])
        if c.empty:
            log.warning("%d: no counties picked", year)
            continue
        seen_states |= set(c["state"].str.strip().str.lower())
        bounds.append(c.total_bounds)
        log.info("%d: %d counties, bounds %s", year, len(c), np.round(c.total_bounds).tolist())
    if not bounds:
        sys.exit(f"ERROR: no county matches states {cfg['states']} in any year")
    if not cfg["all_states"]:
        unseen = [s for s in cfg["states"] if s.strip().lower() not in seen_states]
        if unseen:
            sys.exit(f"ERROR: states {unseen} never appear in the `state` column — check the spelling")
    b = np.array(bounds)
    union = (b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max())
    window = snapped_window(union, ref)
    transform = rasterio.windows.transform(window, ref["transform"])
    wb = rasterio.windows.bounds(window, ref["transform"])
    log.info("window: col_off %d row_off %d | %d x %d cells | bounds %s (counties %s)",
             window.col_off, window.row_off, window.width, window.height,
             [round(v) for v in wb], [round(v) for v in union])

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "window.json").write_text(json.dumps({
        "name": cfg["name"], "states": "all" if cfg["all_states"] else cfg["states"],
        "config_years": cfg["years"], "col_off": int(window.col_off), "row_off": int(window.row_off),
        "width": int(window.width), "height": int(window.height), "bounds": list(wb),
        "county_bounds": [float(v) for v in union], "transform": list(transform)[:6],
        "crs_wkt": ref["crs"].to_wkt(), "reference_raster": str(ref["path"]),
    }, indent=2))

    log.info("cutting %d rasters", len(inputs))
    for layer, year, path in inputs:
        cut_layer(layer, year, path, window, out_dir, ref)

    log.info("zone grids")
    qa = pd.concat([make_zones(y, cfg, args, window, ref, out_dir) for y in years], ignore_index=True)
    qa.to_csv(out_dir / "cutout_qa.csv", index=False)
    n_zero = int((qa["n_cells"] == 0).sum())
    summary = qa.groupby("year").agg(counties=("zone_id", "size"), zero_cell=("n_cells", lambda s: int((s == 0).sum())),
                                     ratio_min=("area_ratio", "min"), ratio_median=("area_ratio", "median"),
                                     ratio_max=("area_ratio", "max"))
    log.info("QA by year:\n%s", summary.round(3).to_string())
    if n_zero:
        log.warning("%d county-years have 0 cells (see cutout_qa.csv, n_cells == 0)", n_zero)
    log.info("wrote %s", out_dir)
    log.info("DONE")


if __name__ == "__main__":
    main()
