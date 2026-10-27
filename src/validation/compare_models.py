"""Model family comparison table (CONUS, docs/conus_plan.md "Model family"; request 2026-10-27).

Reads, per version, the small result files that come back through git:
  <results-root>/dasymetric/<name>/<version>/cv_summary.csv          era -> years (one year per era on CONUS)
  <results-root>/dasymetric/<name>/<version>/<era>/metrics.json      CV and TEST scores, model, chosen settings
  <results-root>/dasymetric/<name>/<version>/<era>/best_params.json  (versions before 2026-10-27: no best_params in
  <results-root>/dasymetric/<name>/<version>/<era>/cv_results.csv     metrics.json; candidates = rows of cv_results)
  <results-root>/validation/<name>/<version>/metrics_by_year.csv     tract metrics (tract_validate.py)
and writes --out (one row per version and year): CV RMSE mean / sd, CV R2, TEST RMSE / R2, tract MdAPE / MAE / R2 of
log pop for the parts all / train / test / no_gap / gap, MdAPE per density class (part all), the areal-weighting
MdAPE, the number of gap counties and tracts, the chosen hyperparameters and the train time; logs a summary per year.
Also, when the files are there: tract_counties (counties with evaluated tracts, from tract_errors_{YEAR}.csv) and the
mass check per year (mass_county_years, mass_max_rel_diff, mass_fail from reallocation_qa.csv).

One version over all years (Dasy_CONUS_RF_v3_all, docs/conus_plan.md "All census years"):
  --out .../summary_by_year.csv --plot .../mdape_by_year.png --repro-with Dasy_CONUS_RF_v3_n60
--plot draws tract MdAPE by year (model, model without gap counties, areal weighting) above the number of counties
with tracts; --repro-with logs one line per year shared with that version: chosen hyperparameters, CV RMSE and tract
MdAPE the same or not (column repro_<version>: same / differs: ...).

Feature test (Dasy_CONUS_RF_v3_ntl vs v3_all, docs/conus_plan.md "NTL test"):
  --versions Dasy_CONUS_RF_v3_all Dasy_CONUS_RF_v3_ntl --years 2000 2010 --rank-features ntl
    --out .../ntl_comparison.csv
--years keeps those years only; --rank-features adds, per feature, its rank among the era's features by
permutation importance (feature_importance.csv) and by mean |SHAP| (shap_importance.csv), 1 = first, with the
values and the number of features (empty where the version has no such feature), and logs them.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("compare_models")

PARTS = ["all", "train", "test", "no_gap", "gap"]
DENS = ["dens_0_50", "dens_50_500", "dens_500_2000", "dens_2000_plus"]
SUMMARY = ["version", "model", "cv_rmse_mean", "cv_r2_mean", "test_r2", "tract_all_n", "tract_counties",
           "tract_all_mdape", "tract_test_mdape", "tract_no_gap_mdape", "tract_dens_0_50_mdape", "baseline_all_mdape",
           "gap_counties", "mass_fail", "train_seconds"]
MASS_TOL = 1e-6  # as src/dasymetric/predict.py


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--versions", nargs="+", required=True)
    p.add_argument("--name", default="conus")
    p.add_argument("--results-root", type=Path, default=Path("results"))
    p.add_argument("--out", type=Path, help="default <results-root>/validation/<name>/model_comparison.csv")
    p.add_argument("--plot", type=Path, help="PNG: tract MdAPE and counties with tracts by year (first version)")
    p.add_argument("--repro-with", metavar="VERSION",
                   help="compare the shared years with this version (same seed, features, folds -> same results)")
    p.add_argument("--years", nargs="+", type=int, help="only these years (default: every era of each version)")
    p.add_argument("--rank-features", nargs="+", default=[], metavar="FEATURE",
                   help="add the permutation / SHAP rank of these features (e.g. ntl)")
    return p.parse_args(argv)


def era_years(vdir: Path) -> dict:
    """era -> year from cv_summary.csv (years 'a-b'; only one-year eras)."""
    path = vdir / "cv_summary.csv"
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (train.py writes it; the train job copies it to results/)")
    out = {}
    for r in pd.read_csv(path).itertuples():
        lo, hi = (int(v) for v in str(r.years).split("-"))
        if lo != hi:
            log.warning("%s: era %s covers %s; skipped (one year per era expected)", vdir.name, r.era, r.years)
            continue
        out[r.era] = lo
    return out


def model_row(vdir: Path, era: str) -> dict:
    edir = vdir / era
    m = json.loads((edir / "metrics.json").read_text())
    best = m.get("best_params")
    if best is None and (edir / "best_params.json").exists():
        best = json.loads((edir / "best_params.json").read_text())
    n_cand = m.get("n_candidates")
    if n_cand is None and (edir / "cv_results.csv").exists():
        n_cand = len(pd.read_csv(edir / "cv_results.csv"))
    return {"model": m.get("model"), "n_candidates": n_cand, "n_train_rows": m.get("n_rows"),
            "cv_rmse_mean": m.get("cv_rmse_mean"), "cv_rmse_sd": m.get("cv_rmse_sd"),
            "cv_r2_mean": m.get("cv_r2_mean"), "cv_r2_sd": m.get("cv_r2_sd"),
            "test_rmse": m.get("test_rmse"), "test_r2": m.get("test_r2"),
            "best_params": json.dumps(best, sort_keys=True) if best is not None else None,
            "search_seconds": m.get("search_seconds"), "train_seconds": m.get("train_seconds")}


def rank_row(edir: Path, features) -> dict:
    """Rank (1 = first) and value of each feature by permutation importance and by mean |SHAP| in the era."""
    out = {}
    for kind, fname, col in (("perm", "feature_importance.csv", "permutation_mean"),
                             ("shap", "shap_importance.csv", "mean_abs_shap")):
        path = edir / fname
        if not path.exists():
            log.warning("%s not found; %s ranks empty", path, kind)
            continue
        imp = pd.read_csv(path).sort_values(col, ascending=False, kind="stable").reset_index(drop=True)
        out["n_features"] = len(imp)
        for f in features:
            hit = imp.index[imp["feature"] == f]
            out[f"{f}_{kind}_rank"] = int(hit[0]) + 1 if len(hit) else None
            out[f"{f}_{kind}"] = float(imp.loc[hit[0], col]) if len(hit) else None
    return out


def tract_row(met: pd.DataFrame, year: int) -> dict:
    out = {}
    y = met[met["year"] == year]
    mod = y[y["method"] == "model"].set_index(["part", "subset"])
    for part in PARTS:
        if (part, "all") in mod.index:
            r = mod.loc[(part, "all")]
            out.update({f"tract_{part}_n": int(r["n"]), f"tract_{part}_mdape": r["mdape"],
                        f"tract_{part}_mae": r["mae"], f"tract_{part}_r2_log": r["r2_log"]})
    for d in DENS:
        if ("all", d) in mod.index:
            out[f"tract_{d}_mdape"] = mod.loc[("all", d), "mdape"]
    base = y[(y["method"] == "baseline") & (y["part"] == "all") & (y["subset"] == "all")]
    if len(base):
        out["baseline_all_mdape"] = float(base["mdape"].iloc[0])
    for col in ("gap_counties", "gap_tracts"):
        if col in y and y[col].notna().any():
            out[col] = int(y[col].dropna().iloc[0])
    return out


def extra_rows(valdir: Path, year: int, mass) -> dict:
    """tract_counties from tract_errors_{year}.csv, the mass check from reallocation_qa.csv (when present)."""
    out = {}
    te = valdir / f"tract_errors_{year}.csv"
    if te.exists():
        t = pd.read_csv(te, usecols=["flag", "zone_gisjoin"])
        out["tract_counties"] = int(t.loc[t["flag"] == "ok", "zone_gisjoin"].nunique())
    if mass is not None:
        q = mass[mass["year"] == year]
        if len(q):
            out.update(mass_county_years=len(q), mass_max_rel_diff=float(q["rel_diff"].max()),
                       mass_fail=int((~(q["rel_diff"] < MASS_TOL)).sum()))
    return out


def version_rows(args, v: str) -> list[dict]:
    vdir = args.results_root / "dasymetric" / args.name / v
    valdir = args.results_root / "validation" / args.name / v
    vpath = valdir / "metrics_by_year.csv"
    met = pd.read_csv(vpath) if vpath.exists() else None
    if met is None:
        log.warning("%s: %s not found; tract columns empty", v, vpath)
    elif "no_gap" not in set(met["part"]):
        log.warning("%s: %s has no no_gap part (validated before 2026-10-27?)", v, vpath)
    mpath = vdir / "reallocation_qa.csv"
    mass = pd.read_csv(mpath, usecols=["year", "rel_diff"]) if mpath.exists() else None
    rows = []
    for era, year in era_years(vdir).items():
        if args.years and year not in args.years:
            continue
        row = {"version": v, "year": year, "era": era, **model_row(vdir, era)}
        if args.rank_features:
            row.update(rank_row(vdir / era, args.rank_features))
        if met is not None:
            row.update(tract_row(met, year))
        row.update(extra_rows(valdir, year, mass))
        rows.append(row)
    return rows


def repro(df: pd.DataFrame, ref: pd.DataFrame, ref_name: str) -> pd.DataFrame:
    """One line per shared year: hyperparameters, CV RMSE, tract MdAPE the same as ref_name's or not."""
    col = f"repro_{ref_name}"
    df[col] = None
    r = ref.set_index("year")
    for i, row in df.iterrows():
        if row["year"] not in r.index:
            continue
        o = r.loc[row["year"]]
        a, b = row.get("tract_all_mdape", np.nan), o.get("tract_all_mdape", np.nan)
        checks = {"hyperparameters": row["best_params"] == o["best_params"],
                  "CV RMSE": bool(np.isclose(row["cv_rmse_mean"], o["cv_rmse_mean"], rtol=0, atol=1e-9)),
                  "tract MdAPE": bool(np.isclose(a, b, rtol=0, atol=1e-9))}
        diff = [k for k, ok in checks.items() if not ok]
        df.at[i, col] = "same" if not diff else "differs: " + ", ".join(diff)
        log.info("repro %d vs %s: hyperparameters %s (%s vs %s) | CV RMSE %.6f vs %.6f %s | tract MdAPE %.3f vs "
                 "%.3f %s -> %s", row["year"], ref_name, "same" if checks["hyperparameters"] else "DIFFER",
                 row["best_params"], o["best_params"], row["cv_rmse_mean"], o["cv_rmse_mean"],
                 "same" if checks["CV RMSE"] else "DIFFERS", a, b, "same" if checks["tract MdAPE"] else "DIFFERS",
                 "SAME" if not diff else "DIFFERENT (" + ", ".join(diff) + ")")
    return df


def plot_years(df: pd.DataFrame, path: Path):
    """Tract MdAPE by year (model, model without gap counties, areal weighting) above counties with tracts.
    Two panels, not two y-scales on one axis."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    d = df[df["version"] == df["version"].iloc[0]].sort_values("year")
    fig, (a, b) = plt.subplots(2, 1, figsize=(8, 6.5), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    lines = [("tract_all_mdape", "model, all tracts", "#2a78d6", "-", "o"),
             ("tract_no_gap_mdape", "model, without BUI gap counties", "#1baf7a", "--", "s"),
             ("baseline_all_mdape", "areal weighting", "#eb6834", "-", "^")]
    for colname, label, color, ls, mk in lines:
        if colname in d and d[colname].notna().any():
            a.plot(d["year"], d[colname], ls, color=color, lw=2, marker=mk, ms=6, label=label)
    a.set_ylabel("tract MdAPE (%)")
    a.set_ylim(bottom=0)
    a.legend(frameon=False, fontsize=9)
    a.set_title(f"{d['version'].iloc[0]}: tract validation by year", fontsize=11)
    n = d["tract_counties"] if "tract_counties" in d else pd.Series(np.nan, index=d.index)
    b.bar(d["year"], n.fillna(0), width=6, color="#2a78d6")
    for x, v in zip(d["year"], n):
        b.annotate("no tracts" if pd.isna(v) else f"{int(v)}", (x, 0 if pd.isna(v) else v), ha="center",
                   va="bottom", fontsize=8, color="#444444", xytext=(0, 2), textcoords="offset points")
    b.set_ylabel("counties with tracts")
    b.set_xticks(d["year"])
    b.set_xlabel("census year")
    for ax in (a, b):
        ax.grid(axis="y", color="#dddddd", lw=0.6)
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    log.info("wrote %s", path)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    out = args.out or args.results_root / "validation" / args.name / "model_comparison.csv"
    rows = [r for v in args.versions for r in version_rows(args, v)]
    if not rows:
        sys.exit("ERROR: no version / year found")
    df = pd.DataFrame(rows).sort_values(["year", "version"], kind="stable")
    if args.repro_with:
        df = repro(df, pd.DataFrame(version_rows(args, args.repro_with)), args.repro_with)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        for year, g in df.groupby("year"):
            log.info("%d (MdAPE / MAE: tracts; no_gap = BUI gap counties left out):\n%s", year,
                     g[[c for c in SUMMARY if c in g]].round(4).to_string(index=False))
        log.info("chosen hyperparameters:\n%s", df[["year", "version", "best_params"]].to_string(index=False))
        for f in args.rank_features:
            cols = [c for c in (f"{f}_perm_rank", f"{f}_perm", f"{f}_shap_rank", f"{f}_shap", "n_features") if c in df]
            log.info("rank of %s (1 = most important; permutation = RMSE increase when shuffled, shap = mean |SHAP|):"
                     "\n%s", f, df[["year", "version"] + cols].to_string(index=False))
    if "mass_fail" in df:
        bad = df.loc[df["mass_fail"] > 0, "year"].tolist()
        log.info("mass check (reallocation_qa.csv, tolerance %.0e): %d county-years fail; years with a failure: %s",
                 MASS_TOL, int(df["mass_fail"].fillna(0).sum()), bad or "none")
    if args.plot:
        plot_years(df, args.plot)
    log.info("wrote %s (%d rows)", out, len(df))
    log.info("DONE")


if __name__ == "__main__":
    main()
