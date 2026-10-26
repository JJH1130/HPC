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
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

log = logging.getLogger("compare_models")

PARTS = ["all", "train", "test", "no_gap", "gap"]
DENS = ["dens_0_50", "dens_50_500", "dens_500_2000", "dens_2000_plus"]
SUMMARY = ["version", "model", "cv_rmse_mean", "cv_r2_mean", "test_r2", "tract_all_mdape", "tract_no_gap_mdape",
           "tract_dens_0_50_mdape", "tract_all_mae", "train_seconds"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--versions", nargs="+", required=True)
    p.add_argument("--name", default="conus")
    p.add_argument("--results-root", type=Path, default=Path("results"))
    p.add_argument("--out", type=Path, help="default <results-root>/validation/<name>/model_comparison.csv")
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


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    out = args.out or args.results_root / "validation" / args.name / "model_comparison.csv"
    rows = []
    for v in args.versions:
        vdir = args.results_root / "dasymetric" / args.name / v
        vpath = args.results_root / "validation" / args.name / v / "metrics_by_year.csv"
        met = pd.read_csv(vpath) if vpath.exists() else None
        if met is None:
            log.warning("%s: %s not found; tract columns empty", v, vpath)
        elif "no_gap" not in set(met["part"]):
            log.warning("%s: %s has no no_gap part (validated before 2026-10-27?)", v, vpath)
        for era, year in era_years(vdir).items():
            row = {"version": v, "year": year, "era": era, **model_row(vdir, era)}
            if met is not None:
                row.update(tract_row(met, year))
            rows.append(row)
    if not rows:
        sys.exit("ERROR: no version / year found")
    df = pd.DataFrame(rows).sort_values(["year", "version"], kind="stable")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        for year, g in df.groupby("year"):
            log.info("%d (MdAPE / MAE: tracts; no_gap = BUI gap counties left out):\n%s", year,
                     g[[c for c in SUMMARY if c in g]].round(4).to_string(index=False))
        log.info("chosen hyperparameters:\n%s", df[["year", "version", "best_params"]].to_string(index=False))
    log.info("wrote %s (%d rows)", out, len(df))
    log.info("DONE")


if __name__ == "__main__":
    main()
