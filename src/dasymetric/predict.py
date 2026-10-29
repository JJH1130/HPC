"""Stage 3: cell prediction + mass-preserving reallocation (design: docs/dasymetric_v1.md; maps: v2;
eras: docs/dasymetric_v3.md).

Each year is predicted with the model of its era (<version>/<era>/model/; without eras, <version>/model/).
For each year and each used county c (status in `use_status`):
  1. cell features (the era model's features) for all cells of c
  2. y_hat per cell, weight w = exp(y_hat) (predicted density, > 0); with `water_mask: true`, w = 0 on
     cells that are all water with no building that year (water_frac == 1 and BUI == 0; docs/dasymetric_v3_1.md)
  3. pop_cell = pop_c * w_cell / sum_{cells in c} w

Writes to <out-root>/<name>/<version>/:
  predictions/pop_{YEAR}.tif   cell population, float32, NoData = -9999 (unused counties + outside)
  qa/reallocation_qa.csv       per county-year: era, census pop, sum of cell pop, difference (--years: the other
                               years' rows of an earlier run are kept)
  maps/pop_{YEAR}.png          quick-look maps for maps.years (state boundaries from --counties-gpkg)
  maps/pop_{YEAR}_<prev>_vs_<version>.png   side by side with the `compare_with` version for maps.compare_years
Map years come from `maps:` in configs/model.yaml (default 1810, 1900, 2020 and 1810); the flags override it.

Checks (the job fails after writing everything if one fails): |sum pop_cell - pop_c| / pop_c < 1e-6
for every county-year, no negative or NaN cell values in used counties, and no people on masked cells.

CONUS (docs/conus_plan.md): with `block_rows`, features and the RF prediction run strip by strip (the RF uses
--n-jobs threads over its trees), only for cells of used counties (train and test counties alike); the weights
are kept (~1 GB per 10^8 cells) and scaled to the county totals in a second pass. Maps of windows above
MAP_MAX_CELLS show people per f x f cells. --measure N times the first N strips and writes nothing.
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import rasterio
from affine import Affine

import plots
from models import set_threads
from common import (NODATA_OUT, add_common_args, cell_features, county_selection, dist_built, era_of, load_config,
                    log, log_args, out_dir, read_zones, setup_logging, strips, used_mask, water_mask, write_tif)

MASS_TOL = 1e-6
MAP_MAX_CELLS = 20_000_000  # larger windows (CONUS: 214 M cells -> 1 km) are drawn as sums over f x f cells
MAP_DEFAULTS = {"years": [1810, 1900, 2020], "compare_years": [1810]}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(p)
    p.add_argument("--cutout-root", type=Path, required=True, help="cutout is <cutout-root>/<name>/")
    p.add_argument("--years", type=int, nargs="+", help="only these years (default: all config years)")
    p.add_argument("--map-years", type=int, nargs="*",
                   help="years to draw quick-look PNGs for (if predicted; default: maps.years in the config)")
    p.add_argument("--compare-years", type=int, nargs="*",
                   help="years to draw side by side with the compare_with version (default: maps.compare_years)")
    p.add_argument("--counties-gpkg", type=Path,
                   help="counties_2020.gpkg; dissolved by state as the map background (none: no background)")
    p.add_argument("--n-jobs", type=int, default=1, help="prediction threads (sbatch: SLURM_CPUS_ON_NODE)")
    p.add_argument("--measure", type=int, default=0, metavar="N",
                   help="trial: per year, predict only the first N strips with cells, log the time per cell and "
                        "the extrapolated time for the year, write nothing (needs block_rows)")
    return p.parse_args(argv)


def predict_year(cutout: Path, year: int, bundle: dict, cfg: dict, out: Path, measure: int = 0):
    """Predict + reallocate one year. Pass 1 predicts the weights strip by strip (`block_rows`; one strip = the
    whole window without it) for the cells of used counties only; pass 2 scales them to the county totals.
    measure > 0: stop after that many strips with cells, log the time per cell and the extrapolated total for
    the year, write nothing and return None."""
    zones, table, grid = read_zones(cutout, year)
    used = county_selection(table, zones, bundle["use_status"], year, cfg["unusable"])
    ids = used["zone_id"].to_numpy()
    parts = strips(zones.shape, cfg.get("block_rows"))
    whole = len(parts) == 1
    full = {}  # whole-window features (dist_built), computed once for the year
    if not whole and "dist_built" in bundle["features"]:  # timed on its own (whole-window distance transform)
        t = time.perf_counter()
        full["dist_built"] = dist_built(cutout, year, grid)
        log.info("    %d: dist_built on the whole window in %.1f s", year, time.perf_counter() - t)
    W, Z, M, MASKS = [], [], [], []  # per strip: weights, zone ids, water-masked flags, cell mask
    n_cells_all = int(used["n_cells"].sum())
    t0, done, n_pred = time.perf_counter(), 0, 0
    y_lo, y_hi = np.inf, -np.inf
    for k, rws in enumerate(parts):
        mask = used_mask(zones[rws], ids)
        MASKS.append(mask)
        if not mask.any():
            W.append(np.zeros(0)), Z.append(np.zeros(0, zones.dtype)), M.append(np.zeros(0, bool))
            continue
        t1 = time.perf_counter()
        X = cell_features(cutout, year, grid, mask, bundle["features"], None if whole else rws, full)
        t2 = time.perf_counter()
        y_hat = bundle["model"].predict(X)
        del X
        y_lo, y_hi = min(y_lo, float(y_hat.min())), max(y_hi, float(y_hat.max()))
        w = np.exp(y_hat)
        t3 = time.perf_counter()
        # v3.1: all-water cells without a building this year get weight 0 (docs/dasymetric_v3_1.md)
        if cfg.get("water_mask"):
            masked = water_mask(cutout, year, grid, mask, cfg.get("water_mask"), None if whole else rws)[0]
        else:
            masked = np.zeros(len(w), bool)
        w[masked] = 0.0
        W.append(w), Z.append(zones[rws][mask]), M.append(masked)
        done += 1
        n_pred += len(w)
        if not whole:
            el = time.perf_counter() - t0
            log.info("    %d strip %d/%d rows %d-%d: %d cells | features %.1f s, RF %.1f s | %d/%d cells, ETA %.0f min",
                     year, k + 1, len(parts), rws.start, rws.stop, len(w), t2 - t1, t3 - t2, n_pred, n_cells_all,
                     el / n_pred * (n_cells_all - n_pred) / 60)
        if measure and done >= measure:
            el = time.perf_counter() - t0
            log.info("MEASURE %d: %d strips, %d cells in %.1f s (%.0f cells/s; dist_built timed above) -> "
                     "%d cells of used counties this year: about %.1f min for pass 1; nothing written", year, done,
                     n_pred, el, n_pred / el, n_cells_all, el / n_pred * n_cells_all / 60)
            return None
    w = np.concatenate(W)
    z = np.concatenate(Z)
    masked = np.concatenate(M)
    del W, Z, M, full
    pop = np.zeros(int(max(zones.max(), ids.max())) + 1)
    pop[ids] = used["pop"].to_numpy()
    w_sum = np.bincount(z, weights=w, minlength=len(pop))
    empty = ~(w_sum[ids] > 0)
    if empty.any() and cfg["unusable"] == "skip":  # no unmasked cell: as in county_features, NoData
        log.warning("  %d: %d counties with no unmasked cell skipped (NoData):\n%s", year, int(empty.sum()),
                    used[empty].to_string())
        pop[ids[empty]] = 0.0
        used, ids = used[~empty], ids[~empty]
    elif empty.any():
        sys.exit(f"ERROR: {year}: counties with no unmasked cell (weights sum to 0):\n{used[empty].to_string()}")
    keep = w_sum[z] > 0
    cells = np.zeros(len(w))
    cells[keep] = pop[z[keep]] * w[keep] / w_sum[z[keep]]

    arr = np.full(zones.shape, NODATA_OUT, dtype="float32")
    i = 0
    for rws, mask in zip(parts, MASKS):  # pass 2: same cell order as pass 1
        n = int(mask.sum())
        view = arr[rws]
        view[mask] = np.where(keep[i:i + n], cells[i:i + n], NODATA_OUT)
        i += n
    del cells
    mask = used_mask(zones, ids)  # skipped counties stay NoData
    write_tif(out / "predictions" / f"pop_{year}.tif", arr, grid["transform"], grid["crs"], NODATA_OUT)

    z, masked = z[keep], masked[keep]
    stored = arr[mask].astype("float64")  # check what was written (float32), not the float64 values
    cell_sum = np.bincount(z, weights=stored, minlength=len(pop))[ids]
    qa = used[["zone_id", "GISJOIN", "state", "name", "status", "n_cells", "pop"]].copy()
    qa.insert(0, "era", bundle.get("era"))
    qa.insert(0, "year", year)
    qa["pop_cells"] = cell_sum
    qa["diff"] = qa["pop_cells"] - qa["pop"]
    qa["rel_diff"] = qa["diff"].abs() / qa["pop"]
    qa["n_masked"] = np.bincount(z[masked], minlength=len(pop))[used["zone_id"].to_numpy()]
    # bad: negative or NaN, or people on a masked cell
    n_bad = int((~np.isfinite(stored) | (stored < 0) | (masked & (stored != 0))).sum())
    log.info("  %d%s: %d counties, %d cells (%d masked) | y_hat %.3f..%.3f | pop %.0f -> cells %.0f | "
             "cell max %.1f | max rel diff %.2e | bad cells %d", year,
             f" ({bundle['era']})" if bundle.get("era") else "", len(used), int(mask.sum()), int(masked.sum()),
             y_lo, y_hi, qa["pop"].sum(), stored.sum(), stored.max(), qa["rel_diff"].max(), n_bad)
    log.info("  %d: %.1f min", year, (time.perf_counter() - t0) / 60)
    return qa, n_bad, (arr, mask, grid)


def coarsen(arr, mask, f: int):
    """People per f x f block of cells (sum over the valid cells) + mask of blocks with any valid cell."""
    if f == 1:
        return arr, mask
    h, w = arr.shape
    H, W = -(-h // f) * f, -(-w // f) * f
    a = np.zeros((H, W), dtype="float64")
    m = np.zeros((H, W), bool)
    a[:h, :w] = np.where(mask, arr, 0.0)
    m[:h, :w] = mask
    return (a.reshape(H // f, f, W // f, f).sum(axis=(1, 3)), m.reshape(H // f, f, W // f, f).any(axis=(1, 3)))


def draw_maps(year: int, arr, mask, grid, cfg: dict, out: Path, args, prev_dir: Path | None):
    # CONUS: draw people per f x f cells (the 250 m array is too big for matplotlib)
    f = max(1, math.ceil(math.sqrt(arr.size / MAP_MAX_CELLS)))
    arr, mask = coarsen(arr, mask, f)
    full_grid, t = grid, grid["transform"]
    grid = {**grid, "shape": arr.shape, "transform": Affine(t.a * f, 0, t.c, 0, t.e * f, t.f)}
    bounds = plots.map_bounds(mask, grid)
    states = plots.read_states(args.counties_gpkg, bounds, grid["crs"]) if args.counties_gpkg else None
    cell = f"{250 * f / 1000:g} km" if f > 1 else "250 m"  # one label for title and colour bar (fixed 2026-10-30)
    title = f"Population per {cell} cell, {year}"
    if year in args.map_years:
        plots.pop_maps(out / "maps" / f"pop_{year}.png", [(cfg["version"], arr, mask)], grid, states, bounds, title,
                       cell)
    if year in args.compare_years and prev_dir is not None:
        ppath = prev_dir / "predictions" / f"pop_{year}.tif"
        if not ppath.exists():
            log.warning("  no %s; side-by-side map for %d skipped", ppath, year)
            return
        with rasterio.open(ppath) as src:
            if (src.height, src.width) != full_grid["shape"] or src.transform != full_grid["transform"]:
                log.warning("  %s is not on this grid; side-by-side map skipped", ppath)
                return
            parr = src.read(1)
            pmask = parr != src.nodata
        parr, pmask = coarsen(parr, pmask, f)
        prev = cfg["compare_with"]
        plots.pop_maps(out / "maps" / f"pop_{year}_{prev}_vs_{cfg['version']}.png",
                       [(prev, parr, pmask), (cfg["version"], arr, mask)], grid, states, bounds, title, cell)


def main(argv=None):
    setup_logging()
    args = parse_args(argv)
    log_args(args)
    cfg = load_config(args.config)
    cutout = args.cutout_root / cfg["name"]
    out = out_dir(cfg, args.out_root)
    years = cfg["years"] if args.years is None else sorted(set(args.years))
    if not set(years) <= set(cfg["years"]):
        sys.exit(f"ERROR: --years {sorted(set(years) - set(cfg['years']))} not in the config years")
    if args.counties_gpkg and not args.counties_gpkg.exists():
        sys.exit(f"ERROR: --counties-gpkg {args.counties_gpkg} not found")
    prev_dir = args.out_root / cfg["name"] / cfg["compare_with"] if cfg.get("compare_with") else None
    maps = {**MAP_DEFAULTS, **(cfg.get("maps") or {})}
    if args.map_years is None:
        args.map_years = maps["years"]
    if args.compare_years is None:
        args.compare_years = maps["compare_years"]
    log.info("maps: %s | side by side with %s: %s", args.map_years, cfg.get("compare_with"), args.compare_years)

    bundles = {}
    for era in dict.fromkeys(era_of(cfg, y) for y in years):  # load each needed era model once, up front
        mpath = out_dir(cfg, args.out_root, era) / "model" / f"{cfg['model']}.joblib"
        if not mpath.exists():
            sys.exit(f"ERROR: {mpath} not found (run stage 2, train.py, first)")
        bundle = joblib.load(mpath)
        set_threads(bundle["model"], args.n_jobs)
        if bundle["features"] != cfg["eras"][era]["features"]:
            sys.exit(f"ERROR: {mpath} was trained on {bundle['features']}, the config says "
                     f"{cfg['eras'][era]['features']}; rerun stages 1-2")
        if str(bundle.get("water_mask", False)).lower() != str(cfg.get("water_mask", False)).lower():
            sys.exit(f"ERROR: {mpath} was trained with water_mask={bundle.get('water_mask', False)}, "
                     f"the config says {cfg.get('water_mask', False)}; rerun stages 1-2")
        bundles[era] = bundle
        log.info("model %s%s (%s) | features %s | use_status %s", bundle["name"], f" era {era}" if era else "",
                 mpath, bundle["features"], bundle["use_status"])
    log.info("%d years -> %s", len(years), out)

    if args.measure and not cfg.get("block_rows"):
        sys.exit("ERROR: --measure needs block_rows in the config")
    parts, bad_cells = [], 0
    for year in years:
        res = predict_year(cutout, year, bundles[era_of(cfg, year)], cfg, out, args.measure)
        if res is None:  # --measure
            continue
        qa, n_bad, (arr, mask, grid) = res
        parts.append(qa)
        bad_cells += n_bad
        if year in args.map_years or year in args.compare_years:
            draw_maps(year, arr, mask, grid, cfg, out, args, prev_dir)
        del arr, mask
    if args.measure:
        log.info("DONE (measure only)")
        return
    qa = pd.concat(parts, ignore_index=True)
    qpath = out / "qa" / "reallocation_qa.csv"
    qpath.parent.mkdir(parents=True, exist_ok=True)
    if args.years is not None and qpath.exists():  # --years (2020 added to v3_all): the other years' rows are kept
        old = pd.read_csv(qpath, float_precision="round_trip")  # kept rows written back unchanged
        old = old[~old["year"].isin(years)]
        log.info("--years: reallocation_qa.csv keeps %d rows of years %s", len(old), sorted(old["year"].unique()))
        qa = pd.concat([old, qa], ignore_index=True).sort_values(["year", "zone_id"], kind="stable")
    qa.to_csv(qpath, index=False)
    log.info("wrote %s", qpath)

    fail = qa[~(qa["rel_diff"] < MASS_TOL)]
    by_year = qa.assign(fail=~(qa["rel_diff"] < MASS_TOL)).groupby("year").agg(
        county_years=("GISJOIN", "size"), max_rel_diff=("rel_diff", "max"), fail=("fail", "sum"))
    log.info("mass check by year (tolerance %.0e):\n%s", MASS_TOL, by_year.to_string())
    log.info("mass check: %d county-years, max rel diff %.2e (tolerance %.0e), %d fail | bad cells %d",
             len(qa), qa["rel_diff"].max(), MASS_TOL, len(fail), bad_cells)
    if len(fail) or bad_cells:
        if len(fail):
            log.error("mass preservation failed:\n%s", fail.to_string())
        sys.exit("ERROR: reallocation checks failed (see above)")
    log.info("DONE")


if __name__ == "__main__":
    main()
