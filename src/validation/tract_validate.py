"""Validate the Massachusetts dasymetric predictions against NHGIS census tracts
(design: docs/validation_tract.md).

Per year:
  1. Massachusetts tracts (status ok, pop not empty) rasterized onto the cutout grid (cell centre).
  2. Model: tract pop = sum of predicted cells. Baseline: county pop spread evenly over the
     county's cells with a prediction > 0 (= the model's cells minus the water mask).
  3. Only tracts whose cells all lie in one used county are evaluated (others flagged).
  4. RMSE, MAE, median absolute % error, R2 on log(pop + 1), and R2 on log(density + 1)
     (density = tract pop / area of its cells) for model and baseline, for all / non-small
     (>= 4 cells) / small tracts.
  5. Totals QA: county pop = sum of cells; for fully tracted county-years, observed tracts,
     predicted cells inside tracts and baseline cells inside tracts all sum to the county pop.
     Stops (after writing everything) if the predicted or baseline sums fail.

Writes to <results-root>/<name>/<version>/: tract_errors_{YEAR}.csv, metrics_by_year.csv,
qa_totals.csv, tract_validation_{YEAR}.png. Paths come from CLI flags (sbatch/validate_tract.sh).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dasymetric"))
import plots  # noqa: E402  (palette and plot helpers of the dasymetric step)

YEARS = [1910, 1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020]  # 1920: no MA tracts
MAP_YEARS = [1940, 1970, 2020]
MA_PREFIX = "G250"
SMALL_CELLS = 4
CELL_KM2 = 0.25 * 0.25  # area of one 250 m cell
TOTAL_TOL = 0.001  # 0.1 %
FULL_COVERAGE = (0.999, 1.001)
FATAL_CHECKS = ("tracts_model", "tracts_baseline")
TRACT_COLS = ["GISJOIN", "county_gisjoin", "status", "flag", "n_cells", "small", "pop_obs", "pop_model",
              "pop_baseline", "lon", "lat"]
QA_COLS = ["year", "county_gisjoin", "name", "check", "coverage", "expected", "value", "rel_diff", "flag"]

log = logging.getLogger("tract_validate")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", required=True, help="dasymetric version, e.g. v3_1")
    p.add_argument("--name", default="massachusetts", help="study area name")
    p.add_argument("--dasym-root", type=Path, required=True, help="predictions in <root>/<name>/<version>/")
    p.add_argument("--cutout-root", type=Path, required=True, help="zones in <root>/<name>/zones/")
    p.add_argument("--tract-dir", type=Path, required=True, help="folder with tracts_{YEAR}.gpkg")
    p.add_argument("--coverage-csv", type=Path, required=True, help="results/tract/coverage_by_county_MA.csv")
    p.add_argument("--results-root", type=Path, required=True, help="outputs in <root>/<name>/<version>/")
    p.add_argument("--years", type=int, nargs="+", default=YEARS)
    p.add_argument("--map-years", type=int, nargs="*", default=MAP_YEARS)
    return p.parse_args(argv)


# ---------------------------------------------------------------- inputs

def read_grid(cutout: Path, year: int):
    tif, csv = cutout / "zones" / f"zones_{year}.tif", cutout / "zones" / f"zones_{year}.csv"
    with rasterio.open(tif) as src:
        zones = src.read(1)
        grid = {"transform": src.transform, "crs": src.crs, "shape": zones.shape}
    return zones, pd.read_csv(csv), grid


def read_pred(path: Path, grid: dict):
    with rasterio.open(path) as src:
        if (src.height, src.width) != grid["shape"] or src.transform != grid["transform"]:
            sys.exit(f"ERROR: {path} is not on the zones grid")
        arr = src.read(1).astype("float64")
        valid = arr != src.nodata
    return arr, valid


def read_tracts(path: Path, grid: dict) -> gpd.GeoDataFrame:
    t = gpd.read_file(path, engine="pyogrio", columns=["GISJOIN", "county_gisjoin", "pop", "status"])
    t = t[t["GISJOIN"].str.startswith(MA_PREFIX)].reset_index(drop=True)
    return t.to_crs(grid["crs"].to_wkt())


# ---------------------------------------------------------------- metrics + QA

def r2(obs: np.ndarray, pred: np.ndarray) -> float:
    ss_tot = ((obs - obs.mean()) ** 2).sum()
    return float(1 - ((pred - obs) ** 2).sum() / ss_tot) if ss_tot > 0 else np.nan


def mdape(obs: np.ndarray, pred: np.ndarray) -> float:
    pos = obs > 0
    return float(np.median(np.abs(pred[pos] - obs[pos]) / obs[pos]) * 100) if pos.any() else np.nan


def metrics(obs: np.ndarray, pred: np.ndarray, area: np.ndarray) -> dict:
    """Tract pop metrics + R2 on log density (people/km2 over the tract's cells; area > 0 for evaluated
    tracts). Density uses the same area for obs and pred, so a % error on density equals the one on pop."""
    if len(obs) == 0:
        return {k: np.nan for k in ("rmse", "mae", "mdape", "r2_log", "r2_logdens")}
    err = pred - obs
    ldo, ldp = np.log1p(obs / area), np.log1p(pred / area)
    return {
        "rmse": float(np.sqrt((err ** 2).mean())),
        "mae": float(np.abs(err).mean()),
        "mdape": mdape(obs, pred),
        "r2_log": r2(np.log1p(obs), np.log1p(pred)),
        "r2_logdens": r2(ldo, ldp),
    }


def qa_row(year, gj, name, check, coverage, expected, value):
    rel = abs(value - expected) / expected if expected else (0.0 if value == expected else np.inf)
    return {"year": year, "county_gisjoin": gj, "name": name, "check": check, "coverage": coverage,
            "expected": expected, "value": value, "rel_diff": rel, "flag": bool(rel > TOTAL_TOL)}


# ---------------------------------------------------------------- one year

def validate_year(year, args, pred_dir, cutout, realloc, coverage):
    log.info("===== %d =====", year)
    zones, ztable, grid = read_grid(cutout, year)
    pred, valid = read_pred(pred_dir / "predictions" / f"pop_{year}.tif", grid)
    rq = realloc[realloc["year"] == year]
    nz = int(max(zones.max(), rq["zone_id"].max())) + 1
    zid = np.where(valid, zones, 0)
    if (valid & (zones == 0)).any():
        sys.exit(f"ERROR: {year}: predicted cells outside the county zones")

    # county totals + water mask, and the baseline
    model_cells = np.where(valid, pred, 0.0)
    elig = valid & (pred > 0)
    county_sum = np.bincount(zid.ravel(), weights=model_cells.ravel(), minlength=nz)
    n_zero = np.bincount(zid[valid & (pred == 0)], minlength=nz)
    n_elig = np.bincount(zid[elig], minlength=nz)
    county_pop = np.zeros(nz)
    county_pop[rq["zone_id"].to_numpy()] = rq["pop"].to_numpy()
    base_cells = np.zeros(zones.shape)
    base_cells[elig] = county_pop[zid[elig]] / n_elig[zid[elig]]
    qa = []
    for r in rq.itertuples():
        qa.append(qa_row(year, r.GISJOIN, r.name, "county_cells", np.nan, r.pop, county_sum[r.zone_id]))
        qa.append(qa_row(year, r.GISJOIN, r.name, "masked_cells", np.nan, r.n_masked, n_zero[r.zone_id]))

    # tracts -> cells (cell centre inside the tract)
    t = read_tracts(args.tract_dir / f"tracts_{year}.gpkg", grid)
    tid = rasterize(zip(t.geometry, range(1, len(t) + 1)), out_shape=grid["shape"], transform=grid["transform"],
                    fill=0, all_touched=False, dtype="int32")
    n = len(t) + 1
    in_t = tid > 0
    t["n_cells"] = np.bincount(tid[in_t], minlength=n)[1:]
    t["pop_model"] = np.bincount(tid[in_t], weights=model_cells[in_t], minlength=n)[1:]
    t["pop_baseline"] = np.bincount(tid[in_t], weights=base_cells[in_t], minlength=n)[1:]
    n_invalid = np.bincount(tid[in_t & ~valid], minlength=n)[1:]
    pairs = np.unique(np.stack([tid[in_t & valid], zid[in_t & valid]]), axis=1)
    n_zones = np.bincount(pairs[0], minlength=n)[1:]
    t["flag"] = "ok"
    t.loc[n_zones > 1, "flag"] = "multi_county"
    t.loc[n_invalid > 0, "flag"] = "outside_model"
    t.loc[t["n_cells"] == 0, "flag"] = "no_cells"
    t.loc[(t["status"] != "ok") | t["pop"].isna(), "flag"] = "not_ok"
    t["small"] = t["n_cells"] < SMALL_CELLS
    t["pop_obs"] = t["pop"]
    pts = t.geometry.representative_point().to_crs("EPSG:4326")  # where to look a tract up
    t["lon"], t["lat"] = pts.x.round(5), pts.y.round(5)
    log.info("  %d MA tracts | flags %s", len(t), t["flag"].value_counts().to_dict())
    out = args.out / f"tract_errors_{year}.csv"
    t[TRACT_COLS].sort_values("GISJOIN").to_csv(out, index=False)

    # metrics
    ev = t[t["flag"] == "ok"]
    ma_total = rq.loc[rq["GISJOIN"].str.startswith(MA_PREFIX), "pop"].sum()
    rows = []
    for subset, sel in (("all", ev), ("non_small", ev[~ev["small"]]), ("small", ev[ev["small"]])):
        obs = sel["pop_obs"].to_numpy()
        for method in ("model", "baseline"):
            m = metrics(obs, sel[f"pop_{method}"].to_numpy(), sel["n_cells"].to_numpy() * CELL_KM2)
            rows.append({"year": year, "method": method, "subset": subset, "n": len(sel),
                         "pop_share": obs.sum() / ma_total if ma_total else np.nan, **m})
    for r in rows:
        if r["subset"] == "all":
            log.info("  %-8s n=%d share=%.3f rmse=%.0f mae=%.0f mdape=%.1f%% r2_log=%.3f | r2 log density=%.3f",
                     r["method"], r["n"], r["pop_share"], r["rmse"], r["mae"], r["mdape"], r["r2_log"],
                     r["r2_logdens"])

    # totals QA over tracted counties
    zone_of = dict(zip(ztable["GISJOIN"], ztable["zone_id"]))
    names = dict(zip(rq["GISJOIN"], rq["name"]))
    for c in coverage[coverage["year"] == year].itertuples():
        gj, cov = c.county_gisjoin, c.coverage
        if not (FULL_COVERAGE[0] <= cov <= FULL_COVERAGE[1]):
            qa.append({**qa_row(year, gj, c.name, "partial_coverage", cov, np.nan, cov), "rel_diff": np.nan,
                       "flag": False})
            continue
        z = zone_of.get(gj)
        if z is None or gj not in names:
            log.warning("  %s fully tracted but not a used county in %d; skipped", gj, year)
            continue
        cells = (zid == z) & in_t
        pop_c = county_pop[z]
        qa.append(qa_row(year, gj, names[gj], "tracts_obs", cov, pop_c,
                         t.loc[t["county_gisjoin"] == gj, "pop_obs"].sum()))
        qa.append(qa_row(year, gj, names[gj], "tracts_model", cov, pop_c, model_cells[cells].sum()))
        qa.append(qa_row(year, gj, names[gj], "tracts_baseline", cov, pop_c, base_cells[cells].sum()))

    if year in args.map_years:
        draw(args.out / f"tract_validation_{year}.png", t, year, args.version)
    return rows, qa


# ---------------------------------------------------------------- figure

def draw(path: Path, t: gpd.GeoDataFrame, year: int, version: str):
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
    plt = plots.plt
    ev = t[t["flag"] == "ok"].copy()
    ev["pct_err"] = np.where(ev["pop_obs"] > 0, 100 * (ev["pop_model"] - ev["pop_obs"]) / ev["pop_obs"], np.nan)
    fig, (ax_map, ax_sc) = plt.subplots(1, 2, figsize=(14, 6.5), dpi=150, layout="constrained",
                                        gridspec_kw={"width_ratios": [1.25, 1]})
    t[t["flag"] != "ok"].plot(ax=ax_map, color=plots.GRID, edgecolor="white", lw=0.2)
    cmap = LinearSegmentedColormap.from_list("div", plots.DIVERGING)
    ev.plot(ax=ax_map, column=ev["pct_err"].clip(-100, 100), cmap=cmap,
            norm=TwoSlopeNorm(vmin=-100, vcenter=0, vmax=100), edgecolor="white", lw=0.2, missing_kwds={"color": plots.GRID})
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=TwoSlopeNorm(vmin=-100, vcenter=0, vmax=100))
    cb = fig.colorbar(sm, ax=ax_map, shrink=0.7)
    cb.set_label("model error, % of observed (clipped at ±100)", fontsize=9, color=plots.INK2)
    cb.ax.tick_params(labelsize=8, colors=plots.INK2)
    ax_map.set_axis_off()
    ax_map.set_title(f"Tract error, {version}, {year}\n{len(ev)} tracts evaluated; grey = not evaluated",
                     fontsize=10, color=plots.INK)

    pos = ev[ev["pop_obs"] > 0]
    lo = max(1.0, float(pos[["pop_obs", "pop_model", "pop_baseline"]].min().min()) if len(pos) else 1.0)
    hi = float(pos[["pop_obs", "pop_model", "pop_baseline"]].max().max()) if len(pos) else 10.0
    for i, (method, label) in enumerate((("baseline", "areal weighting"), ("model", version))):
        ax_sc.scatter(pos["pop_obs"], pos[f"pop_{method}"].clip(lower=lo), s=10, alpha=0.6, lw=0,
                      color=plots.SERIES[1 - i], label=label)
    ax_sc.plot([lo, hi], [lo, hi], color=plots.MUTED, lw=1, ls="--", label="1:1")
    ax_sc.set_xscale("log")
    ax_sc.set_yscale("log")
    ax_sc.set_xlabel("observed tract population", fontsize=9, color=plots.INK2)
    ax_sc.set_ylabel("predicted tract population", fontsize=9, color=plots.INK2)
    ax_sc.set_title(f"Observed vs predicted, {year} (tracts with observed > 0)", fontsize=10, color=plots.INK)
    ax_sc.grid(color=plots.GRID, lw=0.6)
    plots._style(ax_sc)
    ax_sc.legend(fontsize=8, frameon=False, labelcolor=plots.INK2, loc="upper left")
    plots._save(fig, path)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    pred_dir = args.dasym_root / args.name / args.version
    cutout = args.cutout_root / args.name
    args.out = args.results_root / args.name / args.version
    args.out.mkdir(parents=True, exist_ok=True)
    years = sorted(set(args.years))
    missing = [p for y in years for p in (pred_dir / "predictions" / f"pop_{y}.tif",
                                          cutout / "zones" / f"zones_{y}.tif", cutout / "zones" / f"zones_{y}.csv",
                                          args.tract_dir / f"tracts_{y}.gpkg") if not p.exists()]
    rq_path = pred_dir / "qa" / "reallocation_qa.csv"
    missing += [p for p in (rq_path, args.coverage_csv) if not p.exists()]
    if missing:
        sys.exit("ERROR: inputs not found:\n" + "\n".join(f"  {p}" for p in missing))
    realloc = pd.read_csv(rq_path)
    if "n_masked" not in realloc.columns:  # versions before v3.1 have no water mask
        log.info("no water mask: %s has no n_masked column; expecting 0 cells with prediction 0", rq_path)
        realloc["n_masked"] = 0
    coverage = pd.read_csv(args.coverage_csv)

    rows, qa = [], []
    for year in years:
        r, q = validate_year(year, args, pred_dir, cutout, realloc, coverage)
        rows += r
        qa += q
    met = pd.DataFrame(rows)
    met.to_csv(args.out / "metrics_by_year.csv", index=False)
    qa_df = pd.DataFrame(qa, columns=QA_COLS)
    qa_df.to_csv(args.out / "qa_totals.csv", index=False)
    log.info("metrics (all tracts):\n%s", met[met["subset"] == "all"].to_string(index=False))
    flagged = qa_df[qa_df["flag"]]
    log.info("totals QA: %d rows, %d flagged (> %.1f%%); by check:\n%s", len(qa_df), len(flagged), 100 * TOTAL_TOL,
             qa_df.groupby("check")["flag"].agg(["size", "sum"]).to_string())
    if len(flagged):
        log.warning("flagged totals:\n%s", flagged.to_string(index=False))
    fatal = flagged[flagged["check"].isin(FATAL_CHECKS)]
    if len(fatal):
        sys.exit(f"ERROR: {len(fatal)} fully tracted county-years where predicted/baseline pop inside tracts "
                 "differs from the county pop by > 0.1% (see qa_totals.csv)")
    log.info("wrote %s", args.out)
    log.info("DONE")


if __name__ == "__main__":
    main()
