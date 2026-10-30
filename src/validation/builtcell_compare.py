"""Built-cell aggregation test: v5.6 (Dasy_CONUS_RF_v3_u070) vs v5.6 with built-cell county means + built_local
(window k = 3 / 5 / 9: Dasy_CONUS_RF_v3_u070_bc3 / _bc5 / _bc9) on the same tracts and counties (request 2026-10-31,
docs/handoff/builtcell_aggregation_request.md; docs/conus_plan.md "Built-cell aggregation test"). Reads only small
result files that come back through git; runs locally as well.

Tract and county rows as src/validation/plural_compare.py (same functions): tract MdAPE / MAPE (>= --mape-min people)
for all, kept / excluded t070, no_gap / gap (v5.6's gap column), the observed density classes, areal weighting; TEST
counties (the same set in every version, checked) before allocation: MdAPE, MAPE, with CV RMSE / R2 and TEST RMSE / R2
of metrics.json and the rank of built_local by permutation importance and mean |SHAP|.
Cell rows (level cells), from aggregation_diag.py run per version into <diag-root>/<variant>/ (variant base = v5.6),
column share: pop_on_empty (allocated people on BUI = 0 cells / all), built_oor_<feature> (people on built cells below
or above the min-max range of that feature's training county values / people on built cells), built_inside_all
(people on built cells with every feature inside).

Window choice (rule fixed 2026-10-31 before any result): the k with the lowest mean county CV RMSE (metrics.json
cv_rmse_mean) over the years; any k within --tol (0.005) of that mean -> the smallest such k. Tracts are not used for
the choice (their rows are reported for all three). Written to <out-dir>/builtcell_choice.txt (the version), logged as
RULE RESULT.

Writes to --out-dir (results/validation/conus/builtcell/):
  builtcell_comparison.csv     version, variant, year, level (tract / county / cells), set, n, counties, mdape, mape,
                               mape_n, d_mdape (vs v5.6), cv_rmse, cv_r2, test_rmse, test_r2, built_local ranks, share
  builtcell_feature_ranks.csv  version, variant, year, feature, permutation / mean |SHAP| value and rank
  builtcell_comparison.png     tract MdAPE (all tracts) per variant, one panel per year, v5.6 as a dashed line
  builtcell_choice.txt         the chosen version (one line)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plural_compare as pc  # noqa: E402  (tract / county rows, figure)

log = logging.getLogger("builtcell_compare")

YEARS = [1960, 2010]
BASE = "Dasy_CONUS_RF_v3_u070"
VARIANTS = ["bc3", "bc5", "bc9"]  # version = <base>_<variant>; k = the number after bc
TOL = 0.005


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default=BASE, help="v5.6")
    p.add_argument("--variants", nargs="+", default=VARIANTS, help="suffixes bc<k>: version = <base>_<variant>")
    p.add_argument("--years", type=int, nargs="+", default=YEARS)
    p.add_argument("--name", default="conus")
    p.add_argument("--results-root", type=Path, default=Path("results"))
    p.add_argument("--exclusions", type=Path, default=Path("results/hisdac_uncertainty/excluded_counties_t070.csv"))
    p.add_argument("--mape-min", type=float, default=10)
    p.add_argument("--tol", type=float, default=TOL, help="CV RMSE tie: within this, the smaller window")
    p.add_argument("--out-dir", type=Path, default=Path("results/validation/conus/builtcell"))
    p.add_argument("--diag-root", type=Path, help="aggregation_diag outputs per variant (default <out-dir>/diag)")
    return p.parse_args(argv)


def window(var: str) -> int:
    return int(var[2:])


def cell_rows(diag_root: Path, versions: dict, years) -> list[dict]:
    rows = []
    for var, v in versions.items():
        path = diag_root / var / "extrapolation.csv"
        if not path.exists():
            log.warning("%s: %s missing; no cell rows", v, path)
            continue
        e = pd.read_csv(path)
        e = e[(e["range"] == "minmax") & e["year"].isin(years)]
        for y, d in e.groupby("year"):
            base = {"version": v, "variant": var, "year": int(y), "level": "cells"}
            a = d[d["feature"] == "all_features"].set_index("subset")
            rows.append({**base, "set": "pop_on_empty", "share": float(a.at["empty", "pop_share_of_total"])})
            rows.append({**base, "set": "built_inside_all", "share": float(a.at["built", "pop_share_inside"])})
            for r in d[(d["feature"] != "all_features") & (d["subset"] == "built")].itertuples():
                rows.append({**base, "set": f"built_oor_{r.feature}", "share": r.pop_share_below + r.pop_share_above})
    return rows


def rank_table(root: Path, versions: dict, years) -> pd.DataFrame:
    out = []
    for var, v in versions.items():
        for y in years:
            d = root / v / f"Y{y}"
            parts = []
            for kind, fname, col in (("perm", "feature_importance.csv", "permutation_mean"),
                                     ("shap", "shap_importance.csv", "mean_abs_shap")):
                if (d / fname).exists():
                    t = pd.read_csv(d / fname)[["feature", col]].rename(columns={col: kind})
                    t[f"{kind}_rank"] = t[kind].rank(ascending=False, method="first").astype(int)
                    parts.append(t.set_index("feature"))
            if parts:
                t = pd.concat(parts, axis=1).reset_index()
                t.insert(0, "year", y)
                t.insert(0, "variant", var)
                t.insert(0, "version", v)
                out.append(t)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def choose(cmp: pd.DataFrame, variants, years, tol: float):
    """(chosen variant or None, mean CV RMSE per variant over the years; only variants with every year)."""
    c = cmp[(cmp["level"] == "county") & cmp["variant"].isin(variants)].dropna(subset=["cv_rmse"])
    full = c.groupby("variant")["year"].nunique() == len(years)
    means = c.groupby("variant")["cv_rmse"].mean()[full[full].index]
    if means.empty:
        return None, means
    near = [v for v in means.index if means[v] <= means.min() + tol]
    return min(near, key=window), means


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    if not args.exclusions.exists():
        sys.exit(f"ERROR: {args.exclusions} not found (src/grid/uncertainty_filter.py)")
    excl = set(pd.read_csv(args.exclusions)["GISJOIN"])
    versions = {"base": args.base, **{v: f"{args.base}_{v}" for v in args.variants}}
    log.info("RULE (fixed before the results, 2026-10-31): window k = lowest mean county CV RMSE over %s among %s; "
             "within %.3f of it the smallest k; tracts not used", args.years, args.variants, args.tol)
    rows = []
    for y in args.years:
        rows += pc.tract_rows(args, y, versions, excl)
        rows += pc.county_rows(args, y, versions, rank_features=("built_local",))
    rows += cell_rows(args.diag_root or args.out_dir / "diag", versions, args.years)
    cmp = pd.DataFrame(rows)
    if cmp.empty or not (cmp["level"] != "cells").any():
        sys.exit("ERROR: no tract / county result files found for any version / year")
    key = ["year", "level", "set"]
    base = cmp.loc[cmp["variant"] == "base", key + ["mdape"]].rename(columns={"mdape": "base_mdape"})
    cmp = cmp.merge(base, on=key, how="left")
    cmp.insert(cmp.columns.get_loc("mape_n") + 1, "d_mdape", cmp["mdape"] - cmp.pop("base_mdape"))
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    cmp.to_csv(out / "builtcell_comparison.csv", index=False)
    ranks = rank_table(args.results_root / "dasymetric" / args.name, versions, args.years)
    ranks.to_csv(out / "builtcell_feature_ranks.csv", index=False)
    with pd.option_context("display.width", 220, "display.max_rows", 500, "display.max_columns", 30):
        tr = cmp[cmp["level"] == "tract"]
        log.info("tract MdAPE (%%) by set, year and variant:\n%s",
                 tr.pivot_table(index=["set", "year"], columns="variant", values="mdape", sort=False).round(2).to_string())
        log.info("tract MAPE (%%, tracts >= %g people):\n%s", args.mape_min,
                 tr.pivot_table(index=["set", "year"], columns="variant", values="mape", sort=False).round(2).to_string())
        c = cmp[cmp["level"] == "county"]
        cols = [k for k in ("variant", "year", "n", "mdape", "mape", "cv_rmse", "cv_r2", "test_rmse", "test_r2",
                            "built_local_perm_rank", "built_local_shap_rank", "n_features") if k in c]
        log.info("TEST counties (before allocation) + CV / TEST + rank of built_local (1 = most important):\n%s",
                 c[cols].round(4).to_string(index=False))
        ce = cmp[cmp["level"] == "cells"]
        if len(ce):
            log.info("population shares on cells (pop_on_empty = on BUI = 0 cells; built_oor_<f> = built-cell people "
                     "outside the training range of f):\n%s",
                     ce.pivot_table(index=["set", "year"], columns="variant", values="share", sort=False).round(4).to_string())
        if len(ranks):
            log.info("feature ranks (permutation / SHAP):\n%s",
                     ranks.pivot_table(index=["year", "feature"], columns="variant", values=["perm_rank", "shap_rank"],
                                       sort=False).to_string())
    best, means = choose(cmp, args.variants, args.years, args.tol)
    (out / "builtcell_choice.txt").write_text((best and versions[best] or "") + "\n")
    if best:
        t = cmp[(cmp["level"] == "tract") & (cmp["set"] == "all")].groupby("variant")["mdape"].mean()
        cv = cmp[cmp["level"] == "county"].groupby("variant")["cv_rmse"].mean()
        log.info("RULE RESULT: k = %d (%s): mean CV RMSE %.4f | %s | v5.6 %.4f | mean tract MdAPE (not used for the "
                 "choice) %s, v5.6 %.2f %% | the user decides", window(best), versions[best], means[best],
                 ", ".join(f"{v} {means[v]:.4f}" for v in means.index), cv.get("base", np.nan),
                 ", ".join(f"{v} {t[v]:.2f} %" for v in args.variants if v in t), t.get("base", np.nan))
    else:
        log.warning("RULE RESULT: none (no variant has a CV RMSE in every year %s)", args.years)
    pc.plot(cmp, ["base"] + list(args.variants), args.years, out / "builtcell_comparison.png",
            "v5.6 + built-cell county means + built_local (bc<k> = k x k window): tract MdAPE, all tracts")
    log.info("wrote %s", out)
    log.info("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
