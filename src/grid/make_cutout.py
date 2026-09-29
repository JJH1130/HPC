"""Cut a study-area window out of the HISDAC-US V2 rasters, plus per-year county zone grids.

Reads configs/study_area.yaml (rules: docs/cutout.md) and writes to <out-root>/<name>/:
  window.json                      the shared window (HISDAC grid offsets, transform, bounds)
  layers/...                       every layer listed under `layers:` in the config
                                   (default {name}/{YEAR}_{name}.tif), int32 or float32, deflate
  zones/zones_{YEAR}.tif           county id per cell (uint16, 0 = nodata), cell-center rasterize
  zones/zones_{YEAR}.csv           zone_id <-> GISJOIN, state, name, pop, status, area_km2
  cutout_qa.csv                    per year and county: cells assigned, cell area / county area

Steps:
  1. Pick counties whose `state` is in the config (or all) from each year's counties_{YEAR}.gpkg.
  2. One rectangle = union of the picked counties over ALL config years, snapped outward to
     the HISDAC grid (same origin, 250 m, ESRI:102039). Every year and layer shares it.
  3. Layers are listed only in the config. Rasters on the HISDAC grid: windowed read (never
     the whole CONUS array); 0 means "no building", so 0 is never nodata. Rasters on other
     grids (DEM, NTL, ...): GDAL warp onto the window with the layer's `resampling`.
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
from pyproj import CRS
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.warp import reproject
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

RESAMPLING = {"none", "nearest", "bilinear", "cubic", "average", "sum", "mode", "min", "max", "med"}
DTYPES = {"int32", "float32"}


def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["years"] = parse_years(cfg["years"])
    states = cfg["states"]
    cfg["all_states"] = isinstance(states, str) and states.lower() == "all"
    if not cfg["all_states"]:
        cfg["states"] = [states] if isinstance(states, str) else list(states)
    cfg["layers"] = expand_layers(cfg)
    return cfg


def parse_years(y):
    if isinstance(y, dict):
        return list(range(y["start"], y["stop"] + 1, y.get("step", 1)))
    return sorted(int(v) for v in y)


def expand_layers(cfg: dict) -> list[dict]:
    """One dict per output layer (a `classes` entry becomes one layer per class)."""
    out, errors = [], []
    for entry in cfg["layers"]:
        name = entry.get("name", "?")
        res, dtype = entry.get("resampling"), entry.get("dtype", "int32")
        if res not in RESAMPLING:
            errors.append(f"  {name}: resampling {res!r} not in {sorted(RESAMPLING)}")
        if dtype not in DTYPES:
            errors.append(f"  {name}: dtype {dtype!r} not in {sorted(DTYPES)}")
        y = entry.get("years", "all")
        static = y is None or y == "none"
        if static:
            years = None
        elif y == "all":
            years = cfg["years"]
        else:
            years = [v for v in parse_years(y) if v in cfg["years"]]
            if not years:
                log.warning("layer %s: none of its years %s are study years; skipped", name, y)
                continue
        default_out = "{name}/{FILENAME}" if static else "{name}/{YEAR}_{name}.tif"
        for cls in entry.get("classes", [None]):
            out.append({"label": f"{name}_{cls}" if cls else name, "name": name, "class": cls,
                        "path": entry["path"], "years": years, "resampling": res, "dtype": dtype,
                        "out": entry.get("out", default_out), "aligned": {}})
    labels = [layer["label"] for layer in out]
    dup = sorted({x for x in labels if labels.count(x) > 1})
    if dup:
        errors.append(f"  duplicate layer names: {dup}")
    if errors:
        sys.exit("ERROR: config layers:\n" + "\n".join(errors))
    return out


def fill(pattern: str, layer: dict, year) -> str:
    return pattern.format(name=layer["name"], CLASS=layer["class"] or "", YEAR=year or "",
                          FILENAME="{FILENAME}")


def resolve(layer: dict, year, hisdac_dir: Path):
    """Path of one input file, or an error string that shows what the folder does contain."""
    rel = fill(layer["path"], layer, year)
    is_abs = Path(rel).is_absolute()
    if any(ch in rel for ch in "*?["):
        base = Path(Path(rel).anchor) if is_abs else hisdac_dir
        pattern = str(Path(rel).relative_to(base)) if is_abs else rel
        hits = sorted(base.glob(pattern.replace("\\", "/")))
        if len(hits) == 1:
            return hits[0]
        return f"  {layer['label']} {year or ''}: {rel!r} matched {len(hits)} files {[str(h) for h in hits[:5]]}"
    path = Path(rel) if is_abs else hisdac_dir / rel
    if path.exists():
        return path
    folder = path.parent
    listing = sorted(p.name for p in folder.iterdir())[:8] if folder.is_dir() else "(folder missing)"
    return f"  {layer['label']} {year or ''}: missing {path} | folder contains {listing}"


def find_inputs(cfg: dict, hisdac_dir: Path, years) -> list[tuple[dict, int | None, Path]]:
    """(layer, year or None, path) for every raster to cut. Each yearly layer's FIRST year is
    checked even when --years skips it, so a file-naming mismatch stops any run at the start."""
    inputs, problems = [], []
    for layer in cfg["layers"]:
        if layer["years"] is None:
            wanted, check = [None], [None]
        else:
            wanted = [y for y in layer["years"] if y in years]
            check = sorted(set(wanted) | {layer["years"][0]})
        for year in check:
            hit = resolve(layer, year, hisdac_dir)
            if isinstance(hit, str):
                problems.append(hit)
            elif year in wanted:
                inputs.append((layer, year, hit))
        span = "single file" if layer["years"] is None else f"years {layer['years'][0]}-{layer['years'][-1]}"
        log.info("layer %-14s %-22s resampling %-8s %s | files to write: %d",
                 layer["label"], span, layer["resampling"], layer["dtype"], len(wanted))
    if problems:
        sys.exit(f"ERROR: input rasters (relative paths are under {hisdac_dir}):\n" + "\n".join(problems))
    return inputs


def reference_grid(cfg: dict, hisdac_dir: Path) -> dict:
    ref_layer = next((layer for layer in cfg["layers"] if layer["label"] == cfg["grid_reference"]), None)
    if ref_layer is None:
        sys.exit(f"ERROR: grid_reference {cfg['grid_reference']!r} is not a layer name")
    path = resolve(ref_layer, ref_layer["years"][0] if ref_layer["years"] else None, hisdac_dir)
    if isinstance(path, str):
        sys.exit("ERROR: grid reference file:\n" + path)
    with rasterio.open(path) as src:
        t = src.transform
        grid = {"transform": t, "crs": src.crs, "width": src.width, "height": src.height, "path": path}
    if t.b != 0 or t.d != 0 or t.a != -t.e:
        sys.exit(f"ERROR: reference grid is rotated or has non-square cells: {t}")
    log.info("reference grid: %s | %dx%d | cell %s | origin (%s, %s) | %s", path.name, grid["width"],
             grid["height"], t.a, t.c, t.f, grid["crs"].to_string() if grid["crs"] else None)
    return grid


def on_grid(src, ref: dict) -> bool:
    """Same CRS, same cell size, origin offset by whole cells -> no resampling needed."""
    if src.crs is None or not CRS.from_user_input(src.crs).equals(CRS.from_user_input(ref["crs"])):
        return False
    t, r = src.transform, ref["transform"]
    if (t.b, t.d) != (0, 0) or not math.isclose(t.a, r.a) or not math.isclose(t.e, r.e):
        return False
    dx, dy = (t.c - r.c) / r.a, (t.f - r.f) / r.e
    return math.isclose(dx, round(dx), abs_tol=1e-6) and math.isclose(dy, round(dy), abs_tol=1e-6)


def check_grids(inputs, ref: dict):
    """resampling: none layers must sit on the reference grid (headers only, no pixels read)."""
    bad, n_warp = [], 0
    for layer, year, path in inputs:
        with rasterio.open(path) as src:
            aligned = on_grid(src, ref)
            layer["aligned"][year] = aligned
            n_warp += not aligned
            if layer["resampling"] == "none" and not aligned:
                bad.append(f"  {layer['label']} {year or ''}: {path} | cell {src.transform.a} "
                           f"origin ({src.transform.c}, {src.transform.f}) {src.crs}")
    if bad:
        sys.exit("ERROR: these rasters are not on the HISDAC grid but have resampling: none "
                 "(set a resampling method in the config):\n" + "\n".join(bad))
    log.info("%d rasters on the HISDAC grid (window read), %d to warp onto it", len(inputs) - n_warp, n_warp)


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

def read_layer(layer, year, path, win_transform, shape, ref, label):
    """Values on the cutout grid + nodata mask + the nodata value to carry over.
    On-grid: direct window read; 0 stays a value ("no building") even if the source calls it
    nodata. Off-grid: GDAL warp with the layer's resampling; the source's nodata is honored."""
    with rasterio.open(path) as src:
        src_nodata = src.nodata
        if src_nodata is not None and math.isnan(src_nodata):
            src_nodata = None  # NaN is caught by the isnan mask
        if layer["aligned"][year]:
            col = round((win_transform.c - src.transform.c) / src.transform.a)
            row = round((win_transform.f - src.transform.f) / src.transform.e)
            if col < 0 or row < 0 or col + shape[1] > src.width or row + shape[0] > src.height:
                sys.exit(f"ERROR: {label}: {path} does not cover the cutout window")
            arr = src.read(1, window=Window(col, row, shape[1], shape[0]))
            nd = np.isnan(arr) if np.issubdtype(arr.dtype, np.floating) else np.zeros(arr.shape, bool)
            if src_nodata == 0:
                log.warning("  %s: source declares nodata=0; 0 means 'no building', kept as a value", label)
                src_nodata = None
            elif src_nodata is not None:
                nd |= arr == src_nodata
            return arr, nd, src_nodata, "window read"
        arr = np.full(shape, np.nan, dtype="float64")
        reproject(source=rasterio.band(src, 1), destination=arr, src_nodata=src.nodata,
                  dst_transform=win_transform, dst_crs=ref["crs"], dst_nodata=np.nan,
                  resampling=Resampling[layer["resampling"]])
        return arr, np.isnan(arr), src_nodata, f"warped ({layer['resampling']})"


def convert(arr, nd, src_nodata, layer, warped, label):
    """Cast to the layer's dtype. Returns (array, nodata or None, valid values)."""
    valid = arr[~nd]
    if layer["dtype"] == "float32":
        out_nd = float(src_nodata) if src_nodata is not None else float("nan")
        return np.where(nd, out_nd, arr).astype("float32"), out_nd, valid
    if np.issubdtype(arr.dtype, np.floating):
        if warped:  # resampled values need not be whole numbers; int32 layers are rounded
            arr, valid = np.rint(arr), np.rint(valid)
        elif valid.size and not np.all(valid == np.round(valid)):
            sys.exit(f"ERROR: {label} has non-integer values; set dtype: float32 for this layer")
    if valid.size and (valid.min() < INT32.min or valid.max() > INT32.max):
        sys.exit(f"ERROR: {label} values {valid.min()}..{valid.max()} don't fit int32")
    out_nd = None
    if nd.any() or src_nodata is not None:
        ok = src_nodata is not None and float(src_nodata).is_integer() and INT32.min <= src_nodata <= INT32.max
        out_nd = int(src_nodata) if ok else -1
        if valid.size and (valid == out_nd).any():
            sys.exit(f"ERROR: {label} uses {out_nd} both as a value and as nodata")
    out = np.where(nd, out_nd if out_nd is not None else 0, arr).astype(np.int32)
    return out, out_nd, valid


def write_tif(path: Path, arr, transform, crs, nodata):
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    predictor = 3 if np.issubdtype(arr.dtype, np.floating) else 2
    profile = dict(driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1, dtype=arr.dtype,
                   crs=crs, transform=transform, nodata=nodata, compress="deflate", predictor=predictor,
                   tiled=True, blockxsize=256, blockysize=256, BIGTIFF="IF_SAFER")
    with rasterio.open(part, "w", **profile) as dst:
        dst.write(arr, 1)
    os.replace(part, path)  # the final name only ever holds a complete file


def cut_layer(layer, year, path, win_transform, shape, out_dir, ref):
    label = f"{layer['label']} {year}" if year else layer["label"]
    arr, nd, src_nodata, how = read_layer(layer, year, path, win_transform, shape, ref, label)
    out, out_nd, valid = convert(arr, nd, src_nodata, layer, not layer["aligned"][year], label)
    rel = fill(layer["out"], layer, year).replace("{FILENAME}", path.name)
    out_path = out_dir / "layers" / rel
    write_tif(out_path, out, win_transform, ref["crs"], out_nd)
    log.info("  %-18s %s, %s -> %s nodata=%s | min %s max %s | zeros %d | nodata cells %d | %.1f MB",
             label, arr.dtype, how, layer["dtype"], out_nd,
             valid.min() if valid.size else "-", valid.max() if valid.size else "-",
             int((valid == 0).sum()), int(nd.sum()), out_path.stat().st_size / 1e6)


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
    ref = reference_grid(cfg, args.hisdac_dir)
    check_grids(inputs, ref)

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
    shape = (int(window.height), int(window.width))
    for layer, year, path in inputs:
        cut_layer(layer, year, path, transform, shape, out_dir, ref)

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
