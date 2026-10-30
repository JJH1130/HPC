"""PLURAL grid test: v5.6 (Dasy_CONUS_RF_v3_u070) vs v5.6 + plural (continuous / classed) on the same tracts and
counties (request 2026-10-30, docs/handoff/plural_grid_request.md part 4; docs/conus_plan.md "PLURAL grid test").
Reads only small result files that come back through git; runs locally as well.

Tract level, per year, from tract_errors_{YEAR}.csv of each version (flag ok; only tracts evaluated in every version,
the difference is logged): MdAPE and MAPE (tracts with >= --mape-min people) for the sets
  all, kept_t070 / excluded_t070 (the tract's 2010 county in the exclusion set or not), no_gap / gap (BUI gap
  counties, column gap), dens_0_50 ... dens_2000_plus (observed people per km2 of the tract's cells, as
  tract_validate.py)
and the areal-weighting baseline (pop_baseline of v5.6) as its own version row.
County level (set test): TEST counties of each version (test_predictions.csv; the same set in every version, checked),
predicted pop = exp(y_hat) x area_km2 of the target (before allocation) vs census pop: MdAPE, MAPE; with the CV
RMSE / R2 and TEST RMSE / R2 of metrics.json, and the rank + value of plural by permutation importance and mean |SHAP|
(compare_models.rank_row; empty for v5.6).

Best classed variant (rule fixed 2026-10-30 before any result): the lowest mean over the years of tract MdAPE (set
all) among the classed variants; it is drawn next to v5.6 and the bilinear continuous one in the county maps
(sbatch/plural_compare.sh). Written to <out-dir>/plural_best.txt.

Writes to --out-dir (results/validation/conus/plural_grid/):
  plural_comparison.csv  version, variant, year, level, set, n, counties, mdape, mape, mape_n, d_mdape (vs v5.6, same
                         year / level / set), cv_rmse, cv_r2, test_rmse, test_r2, plural_perm_rank, plural_perm,
                         plural_shap_rank, plural_shap, n_features
  plural_comparison.png  tract MdAPE (all tracts) per variant, one panel per year, v5.6 as a dashed line
  plural_best.txt        the chosen classed variant (one line)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_models import rank_row  # noqa: E402
from metrics_over_time import mape, mdape  # noqa: E402

log = logging.getLogger("plural_compare")

YEARS = [1940, 1980, 2010]
BASE = "Dasy_CONUS_RF_v3_u070"
VARIANTS = ["plc", "plcc", "pq3", "pq5", "pe3", "pe5"]  # version = <base>_<variant>
CLASSED = ["pq3", "pq5", "pe3", "pe5"]
AREAL = "areal_weighting"
DENSITY_CLASSES = [(0, 50), (50, 500), (500, 2000), (2000, None)]  # as tract_validate.DENSITY_CLASSES
CELL_KM2 = 0.0625


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default=BASE, help="v5.6")
    p.add_argument("--variants", nargs="+", default=VARIANTS, help="suffixes: version = <base>_<variant>")
    p.add_argument("--years", type=int, nargs="+", default=YEARS)
    p.add_argument("--name", default="conus")
    p.add_argument("--results-root", type=Path, default=Path("results"))
    p.add_argument("--exclusions", type=Path, default=Path("results/hisdac_uncertainty/excluded_counties_t070.csv"))
    p.add_argument("--mape-min", type=float, default=10)
    p.add_argument("--out-dir", type=Path, default=Path("results/validation/conus/plural_grid"))
    return p.parse_args(argv)


def dens_label(lo, hi) -> str:
    return f"dens_{lo}_{'plus' if hi is None else hi}"


# ---------------------------------------------------------------- tract level

def tract_rows(args, year: int, versions: dict, excl: set) -> list[dict]:
    vroot = args.results_root / "validation" / args.name
    te = {}
    for var, v in versions.items():
        path = vroot / v / f"tract_errors_{year}.csv"
        if not path.exists():
            log.warning("%d %s: %s missing; no tract rows", year, v, path)
            continue
        t = pd.read_csv(path)
        te[var] = t[t["flag"] == "ok"].set_index("GISJOIN")
    if "base" not in te:
        log.warning("%d: no tract errors of %s; no tract rows this year", year, args.base)
        return []
    common = set.intersection(*(set(t.index) for t in te.values()))
    for var, t in te.items():
        if len(t) != len(common):
            log.warning("%d %s: %d evaluated tracts, %d evaluated in every version (only those are scored)", year,
                        versions[var], len(t), len(common))
    ids = sorted(common)
    rows = []
    base = te["base"].loc[ids]
    dens = (base["pop_obs"] / (base["n_cells"] * CELL_KM2)).to_numpy()
    sets = {"all": np.ones(len(ids), bool)}
    inside = base["zone_gisjoin"].isin(excl).to_numpy()
    sets.update({"kept_t070": ~inside, "excluded_t070": inside})
    if "gap" in base:
        g = (base["gap"].astype(str).str.lower() == "true").to_numpy()
        sets.update({"no_gap": ~g, "gap": g})
    for lo, hi in DENSITY_CLASSES:
        sets[dens_label(lo, hi)] = (dens >= lo) & (dens < (np.inf if hi is None else hi))
    cols = [(var, versions[var], "pop_model", te[var].loc[ids]) for var in te] + [(AREAL, AREAL, "pop_baseline", base)]
    for var, v, col, t in cols:
        for s, m in sets.items():
            obs, est = t["pop_obs"].to_numpy(float)[m], t[col].to_numpy(float)[m]
            rows.append({"version": v, "variant": var, "year": year, "level": "tract", "set": s, "n": int(m.sum()),
                         "counties": int(base["zone_gisjoin"][m].nunique()), "mdape": mdape(obs, est),
                         "mape": mape(obs, est, args.mape_min), "mape_n": int((obs >= args.mape_min).sum())})
    return rows


# ---------------------------------------------------------------- county level

def county_rows(args, year: int, versions: dict) -> list[dict]:
    root = args.results_root / "dasymetric" / args.name
    rows, test_sets = [], {}
    for var, v in versions.items():
        d = root / v / f"Y{year}"
        need = [d / "test_predictions.csv", d / "county_features.csv", d / "metrics.json"]
        missing = [str(f) for f in need if not f.exists()]
        if missing:
            log.warning("%d %s: missing %s; no county row", year, v, missing)
            continue
        tp, cf = pd.read_csv(need[0]), pd.read_csv(need[1])
        met = json.loads(need[2].read_text())
        test_sets[var] = set(tp["GISJOIN"])
        p = tp[["GISJOIN", "y_hat"]].merge(cf[["GISJOIN", "pop", "area_km2"]], on="GISJOIN", how="left")
        if p["pop"].isna().any():
            sys.exit(f"ERROR: {year} {v}: {int(p['pop'].isna().sum())} TEST counties not in county_features.csv")
        obs = p["pop"].to_numpy(float)
        est = np.exp(p["y_hat"].to_numpy(float)) * p["area_km2"].to_numpy(float)
        r = {"version": v, "variant": var, "year": year, "level": "county", "set": "test", "n": len(p),
             "counties": len(p), "mdape": mdape(obs, est), "mape": mape(obs, est, args.mape_min),
             "mape_n": int((obs >= args.mape_min).sum()), "cv_rmse": met.get("cv_rmse_mean"),
             "cv_r2": met.get("cv_r2_mean"), "test_rmse": met.get("test_rmse"), "test_r2": met.get("test_r2")}
        if var != "base":
            r.update(rank_row(d, ["plural"]))
        rows.append(r)
    if "base" in test_sets:
        for var, s in test_sets.items():
            if s != test_sets["base"]:
                sys.exit(f"ERROR: {year} {versions[var]}: TEST counties differ from {args.base} "
                         f"({len(s ^ test_sets['base'])} counties); same split + exclusions expected")
    return rows


# ---------------------------------------------------------------- choice + figure

def best_classed(cmp: pd.DataFrame, variants, years) -> str | None:
    t = cmp[(cmp["level"] == "tract") & (cmp["set"] == "all") & cmp["variant"].isin(CLASSED)
            & cmp["variant"].isin(variants)]
    full = t.groupby("variant")["year"].nunique() == len(years)
    means = t.groupby("variant")["mdape"].mean()[full[full].index]
    return None if means.empty else str(means.idxmin())


def plot(cmp: pd.DataFrame, variants, years, path: Path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dasymetric"))
    import plots  # noqa: E402  (palette + style of the pipeline figures)
    plt = plots.plt
    t = cmp[(cmp["level"] == "tract") & (cmp["set"] == "all")]
    order = [v for v in variants if v in set(t["variant"])]
    fig, axes = plt.subplots(1, len(years), figsize=(4.2 * len(years), 4.2), dpi=150, layout="constrained",
                             sharey=True, squeeze=False)
    for ax, y in zip(axes[0], years):
        d = t[t["year"] == y].set_index("variant")
        if "base" in d.index:
            b = float(d.loc["base", "mdape"])
            ax.axhline(b, color=plots.INK2, lw=1.2, ls="--", zorder=1)
            ax.text(len(order) - 0.5, b, f"v5.6 {b:.1f} %", fontsize=8, color=plots.INK2, ha="right", va="bottom")
        if AREAL in d.index:
            a = float(d.loc[AREAL, "mdape"])
            ax.axhline(a, color=plots.MUTED, lw=1, ls=":", zorder=1)
            ax.text(len(order) - 0.5, a, f"areal weighting {a:.1f} %", fontsize=8, color=plots.MUTED, ha="right",
                    va="bottom")
        xs = [i for i, v in enumerate(order) if v in d.index]
        vals = [float(d.loc[v, "mdape"]) for v in order if v in d.index]
        ax.scatter(xs, vals, s=48, color=plots.SERIES[0], zorder=3, edgecolor="white", linewidth=1.5)
        for x, v in zip(xs, vals):
            if order[x] != "base":  # v5.6 is labeled on its line
                ax.text(x, v, f" {v:.1f}", fontsize=7, color=plots.INK2, va="center")
        ax.set_xticks(range(len(order)), ["v5.6" if v == "base" else v for v in order])
        ax.set_xlim(-0.6, len(order) - 0.4)
        ax.set_title(str(y), fontsize=10, color=plots.INK)
        ax.grid(axis="y", color=plots.GRID, lw=0.6)
        plots._style(ax)
    axes[0][0].set_ylabel("tract MdAPE, all tracts (%)", fontsize=9, color=plots.INK2)
    fig.suptitle("v5.6 + PLURAL grid: continuous (plc bilinear, plcc cubic) and classes (q = quantile, e = equal "
                 "breaks; 3 / 5)", fontsize=9, color=plots.INK2)
    plots._save(fig, path)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    if not args.exclusions.exists():
        sys.exit(f"ERROR: {args.exclusions} not found (src/grid/uncertainty_filter.py)")
    excl = set(pd.read_csv(args.exclusions)["GISJOIN"])
    log.info("exclusion set %s: %d counties", args.exclusions, len(excl))
    versions = {"base": args.base, **{v: f"{args.base}_{v}" for v in args.variants}}
    log.info("RULE (fixed before the results, 2026-10-30): best classed variant = lowest mean over %s of tract MdAPE "
             "(all tracts) among %s", args.years, [v for v in args.variants if v in CLASSED])
    rows = []
    for y in args.years:
        rows += tract_rows(args, y, versions, excl)
        rows += county_rows(args, y, versions)
    cmp = pd.DataFrame(rows)
    if cmp.empty:
        sys.exit("ERROR: no result files found for any version / year")
    key = ["year", "level", "set"]
    base = cmp.loc[cmp["variant"] == "base", key + ["mdape"]].rename(columns={"mdape": "base_mdape"})
    cmp = cmp.merge(base, on=key, how="left")
    cmp.insert(cmp.columns.get_loc("mape_n") + 1, "d_mdape", cmp["mdape"] - cmp.pop("base_mdape"))
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    cmp.to_csv(out / "plural_comparison.csv", index=False)
    with pd.option_context("display.width", 220, "display.max_rows", 500, "display.max_columns", 30):
        tr = cmp[cmp["level"] == "tract"]
        log.info("tract MdAPE (%%) by set, year and variant:\n%s",
                 tr.pivot_table(index=["set", "year"], columns="variant", values="mdape", sort=False).round(2).to_string())
        log.info("tract MAPE (%%, tracts >= %g people):\n%s", args.mape_min,
                 tr.pivot_table(index=["set", "year"], columns="variant", values="mape", sort=False).round(2).to_string())
        c = cmp[cmp["level"] == "county"]
        cols = [k for k in ("variant", "year", "n", "mdape", "mape", "cv_rmse", "cv_r2", "test_rmse", "test_r2",
                            "plural_perm_rank", "plural_perm", "plural_shap_rank", "plural_shap", "n_features") if k in c]
        log.info("TEST counties (before allocation) + CV / TEST + rank of plural (1 = most important):\n%s",
                 c[cols].round(4).to_string(index=False))
    best = best_classed(cmp, args.variants, args.years)
    (out / "plural_best.txt").write_text((best and versions[best] or "") + "\n")
    if best:
        m = cmp[(cmp["level"] == "tract") & (cmp["set"] == "all")].groupby("variant")["mdape"].mean()
        log.info("RULE RESULT: best classed variant %s (%s): mean tract MdAPE %.2f %% | v5.6 %.2f %% | plc %s | the "
                 "user decides", best, versions[best], m[best], m.get("base", np.nan),
                 f"{m['plc']:.2f} %" if "plc" in m else "-")
    else:
        log.warning("RULE RESULT: none (no classed variant has all years %s)", args.years)
    plot(cmp, ["base"] + list(args.variants), args.years, out / "plural_comparison.png")
    log.info("wrote %s", out)
    log.info("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
