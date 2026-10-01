"""Stage 3: cell prediction + mass-preserving reallocation (design: docs/dasymetric_v1.md).

For each year and each used county c (status in `use_status`):
  1. cell features for all cells of c
  2. y_hat per cell, weight w = exp(y_hat) (predicted density, > 0)
  3. pop_cell = pop_c * w_cell / sum_{cells in c} w

Writes to <out-root>/<name>/<version>/:
  predictions/pop_{YEAR}.tif   cell population, float32, NoData = -9999 (unused counties + outside)
  qa/reallocation_qa.csv       per county-year: census pop, sum of cell pop, difference
  maps/pop_{YEAR}.png          quick-look maps for --map-years

Checks (the job fails after writing everything if one fails): |sum pop_cell - pop_c| / pop_c < 1e-6
for every county-year, and no negative or NaN cell values in used counties.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from common import (NODATA_OUT, add_common_args, cell_features, county_selection, load_config, log,
                    log_args, out_dir, read_zones, setup_logging, write_tif)

MASS_TOL = 1e-6
# Sequential blue ramp, light -> dark (dataviz reference palette, steps 100-700).
BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#1c5cab", "#104281", "#0d366b"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(p)
    p.add_argument("--cutout-root", type=Path, required=True, help="cutout is <cutout-root>/<name>/")
    p.add_argument("--years", type=int, nargs="+", help="only these years (default: all config years)")
    p.add_argument("--map-years", type=int, nargs="*", default=[1810, 1900, 2020],
                   help="years to draw quick-look PNGs for (if predicted)")
    p.add_argument("--n-jobs", type=int, default=1, help="prediction threads (sbatch: SLURM_CPUS_ON_NODE)")
    return p.parse_args(argv)


def predict_year(cutout: Path, year: int, bundle: dict, cfg: dict, out: Path):
    zones, table, grid = read_zones(cutout, year)
    used = county_selection(table, zones, bundle["use_status"], year)
    mask = np.isin(zones, used["zone_id"].to_numpy())
    X = cell_features(cutout, year, grid, mask, bundle["features"])
    y_hat = bundle["model"].predict(X)
    w = np.exp(y_hat)
    z = zones[mask]
    pop = np.zeros(int(zones.max()) + 1)
    pop[used["zone_id"].to_numpy()] = used["pop"].to_numpy()
    w_sum = np.bincount(z, weights=w, minlength=len(pop))
    cells = pop[z] * w / w_sum[z]

    arr = np.full(zones.shape, NODATA_OUT, dtype="float32")
    arr[mask] = cells
    write_tif(out / "predictions" / f"pop_{year}.tif", arr, grid["transform"], grid["crs"], NODATA_OUT)

    stored = arr[mask].astype("float64")  # check what was written (float32), not the float64 values
    cell_sum = np.bincount(z, weights=stored, minlength=len(pop))[used["zone_id"].to_numpy()]
    qa = used[["zone_id", "GISJOIN", "state", "name", "status", "n_cells", "pop"]].copy()
    qa.insert(0, "year", year)
    qa["pop_cells"] = cell_sum
    qa["diff"] = qa["pop_cells"] - qa["pop"]
    qa["rel_diff"] = qa["diff"].abs() / qa["pop"]
    n_bad = int((~np.isfinite(stored) | (stored < 0)).sum())
    log.info("  %d: %d counties, %d cells | y_hat %.3f..%.3f | pop %.0f -> cells %.0f | cell max %.1f | "
             "max rel diff %.2e | bad cells %d", year, len(used), int(mask.sum()), y_hat.min(), y_hat.max(),
             qa["pop"].sum(), stored.sum(), stored.max(), qa["rel_diff"].max(), n_bad)
    return qa, n_bad, (arr, mask, grid)


def quick_look(path: Path, year: int, arr, mask, grid):
    """PNG of one year's cell population, log color scale, cropped to the used counties."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap, LogNorm

    rows, cols = np.where(mask)
    r0, r1, c0, c1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
    sub = np.ma.masked_where(~mask[r0:r1, c0:c1], arr[r0:r1, c0:c1])
    vals = arr[mask]
    norm = LogNorm(vmin=max(float(np.percentile(vals, 1)), 1e-3), vmax=float(vals.max()), clip=True)
    cmap = LinearSegmentedColormap.from_list("blues", BLUES)
    cmap.set_bad("#ffffff")
    t = grid["transform"]
    extent = [(t.c + c0 * t.a) / 1e3, (t.c + c1 * t.a) / 1e3, (t.f + r1 * t.e) / 1e3, (t.f + r0 * t.e) / 1e3]
    fig, ax = plt.subplots(figsize=(8, 8 * (r1 - r0) / max(c1 - c0, 1) + 1), dpi=150, facecolor="white")
    im = ax.imshow(sub, cmap=cmap, norm=norm, extent=extent, interpolation="nearest")
    ax.set_title(f"Population per 250 m cell, {year} (total {vals.sum():,.0f})", fontsize=11, color="#222222")
    ax.set_xlabel("x (km, ESRI:102039)", fontsize=9, color="#555555")
    ax.set_ylabel("y (km)", fontsize=9, color="#555555")
    ax.tick_params(labelsize=8, colors="#555555")
    for s in ax.spines.values():
        s.set_color("#cccccc")
    cb = fig.colorbar(im, ax=ax, shrink=0.7)
    cb.set_label("people per cell (log scale)", fontsize=9, color="#555555")
    cb.ax.tick_params(labelsize=8, colors="#555555")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    log.info("  map %s", path)


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

    mpath = out / "model" / f"{cfg['model']}.joblib"
    if not mpath.exists():
        sys.exit(f"ERROR: {mpath} not found (run stage 2, train.py, first)")
    bundle = joblib.load(mpath)
    if hasattr(bundle["model"], "n_jobs"):
        bundle["model"].n_jobs = args.n_jobs
    log.info("model %s (%s) | features %s | use_status %s | %d years -> %s", bundle["name"], mpath,
             bundle["features"], bundle["use_status"], len(years), out)

    parts, bad_cells = [], 0
    for year in years:
        qa, n_bad, (arr, mask, grid) = predict_year(cutout, year, bundle, cfg, out)
        parts.append(qa)
        bad_cells += n_bad
        if year in args.map_years:
            quick_look(out / "maps" / f"pop_{year}.png", year, arr, mask, grid)
    qa = pd.concat(parts, ignore_index=True)
    qpath = out / "qa" / "reallocation_qa.csv"
    qpath.parent.mkdir(parents=True, exist_ok=True)
    qa.to_csv(qpath, index=False)
    log.info("wrote %s", qpath)

    fail = qa[~(qa["rel_diff"] < MASS_TOL)]
    log.info("mass check: %d county-years, max rel diff %.2e (tolerance %.0e), %d fail | bad cells %d",
             len(qa), qa["rel_diff"].max(), MASS_TOL, len(fail), bad_cells)
    if len(fail) or bad_cells:
        if len(fail):
            log.error("mass preservation failed:\n%s", fail.to_string())
        sys.exit("ERROR: reallocation checks failed (see above)")
    log.info("DONE")


if __name__ == "__main__":
    main()
