"""County MdAPE and a fixed tract set by year for one CONUS version (request 2026-10-30,
docs/handoff/validation_2020_uncertainty_request.md part A; docs/conus_plan.md "Metrics over time"). No retraining:
reads only the small result files that come back through git.

County level (A1), per year (era Y<year>) from <results-root>/dasymetric/<name>/<version>/Y<year>/:
  test_predictions.csv  model prediction of log density before the mass-preserving allocation (TEST counties)
  oof_predictions.csv   out-of-fold prediction of the same model settings (train counties, CV)
  county_features.csv   census pop and the area of the target (area_km2 = 0.0625 x unmasked cells with the water mask)
  metrics.json          the reported TEST R2 / pooled out-of-fold R2, to check the R2 recomputed here
Predicted county pop = exp(y_hat) x area_km2, observed = census pop (y = log(pop / area_km2)). Metrics: counties,
MdAPE, MAPE (all counties: county pop >= 10 everywhere), R2 of log density (= the reported TEST R2 / pooled OOF R2),
and the reported value next to it.

Fixed tract set (A2), from <results-root>/validation/<name>/<version>/tract_errors_{YEAR}.csv (tract_validate.py with
--split): evaluated tracts (flag ok) and the 2010 county (zone_gisjoin) their cells lie in. For each start year S
(--starts, default 1910 1920 1940 1960), the set is the counties with evaluated tracts in EVERY tract year from S on;
each year is scored on its own tracts inside those counties. The all-tracts set (each year's evaluated tracts) is
scored the same way, next to it. Metrics for the model and areal weighting (pop_baseline): tracts, counties, MdAPE
(observed > 0, as tract_validate.py), MAPE over tracts with observed pop >= 10 (--mape-min), observed pop.

Writes to <results-root>/validation/<name>/<version>/:
  county_metrics_by_year.csv   year, set (test / cv), counties, pop, MdAPE, MAPE, R2 and the reported R2
  fixed_tract_metrics.csv      set (all / from_<S>), year, method (model / baseline), tracts, counties, MdAPE, MAPE
  fixed_tract_counties.csv     set, GISJOIN, state, name: the counties of each fixed set
  mdape_over_time.png          MdAPE by year: all tracts, the fixed sets, county TEST; dashed = areal weighting
Paths come from CLI flags (sbatch/metrics_over_time.sh); runs locally as well (only tracked files).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("metrics_over_time")

STARTS = [1910, 1920, 1940, 1960]
MAPE_MIN = 10  # tracts with fewer observed people are left out of the MAPE (request 2026-10-30)
R2_TOL = 1e-9


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", default="Dasy_CONUS_RF_v3_all")
    p.add_argument("--name", default="conus")
    p.add_argument("--results-root", type=Path, default=Path("results"))
    p.add_argument("--starts", type=int, nargs="+", default=STARTS, help="start years of the fixed tract sets")
    p.add_argument("--mape-min", type=float, default=MAPE_MIN, help="MAPE only over observed pop >= this")
    return p.parse_args(argv)


def mdape(obs: np.ndarray, pred: np.ndarray) -> float:
    pos = obs > 0  # as tract_validate.mdape
    return float(np.median(np.abs(pred[pos] - obs[pos]) / obs[pos]) * 100) if pos.any() else np.nan


def mape(obs: np.ndarray, pred: np.ndarray, lo: float) -> float:
    keep = obs >= lo
    return float(np.mean(np.abs(pred[keep] - obs[keep]) / obs[keep]) * 100) if keep.any() else np.nan


def r2(obs: np.ndarray, pred: np.ndarray) -> float:
    ss = ((obs - obs.mean()) ** 2).sum()
    return float(1 - ((pred - obs) ** 2).sum() / ss) if ss > 0 else np.nan


# ---------------------------------------------------------------- A1: counties

def era_dirs(ddir: Path) -> dict[int, Path]:
    """year -> Y<year> folder (one era per year on CONUS)."""
    out = {}
    for d in sorted(ddir.glob("Y*")):
        m = re.fullmatch(r"Y(\d{4})", d.name)
        if m and d.is_dir():
            out[int(m.group(1))] = d
    return out


def county_rows(year: int, edir: Path, mape_min: float) -> list[dict]:
    need = [edir / f for f in ("county_features.csv", "test_predictions.csv", "oof_predictions.csv", "metrics.json")]
    missing = [str(f) for f in need if not f.exists()]
    if missing:
        log.warning("%d: county metrics skipped, missing %s", year, missing)
        return []
    cf = pd.read_csv(need[0])[["GISJOIN", "year", "pop", "area_km2", "y"]]
    met = json.loads(need[3].read_text())
    rows = []
    for name, path, col, reported in (("test", need[1], "y_hat", "test_r2"), ("cv", need[2], "oof", "oof_pooled_r2")):
        p = pd.read_csv(path)[["GISJOIN", "year", "y", col]].merge(cf, on=["GISJOIN", "year"], how="left",
                                                                   suffixes=("", "_features"))
        if p["pop"].isna().any():
            sys.exit(f"ERROR: {year} {name}: {int(p['pop'].isna().sum())} predicted counties not in county_features.csv")
        if not np.allclose(p["y"], p["y_features"], rtol=0, atol=1e-9):
            sys.exit(f"ERROR: {year} {name}: y of {path.name} differs from county_features.csv")
        obs = p["pop"].to_numpy()
        pred = np.exp(p[col].to_numpy()) * p["area_km2"].to_numpy()
        back = np.exp(p["y"].to_numpy()) * p["area_km2"].to_numpy()  # exp(y) x area must give the census pop back
        if not np.allclose(back, obs, rtol=1e-9):
            sys.exit(f"ERROR: {year} {name}: exp(y) x area_km2 != pop (area definition differs from the target)")
        r = r2(p["y"].to_numpy(), p[col].to_numpy())
        rep = met.get(reported)
        rows.append({"year": year, "set": name, "counties": len(p), "pop": float(obs.sum()),
                     "pop_pred": float(pred.sum()), "mdape": mdape(obs, pred), "mape": mape(obs, pred, mape_min),
                     "mape_n": int((obs >= mape_min).sum()), "r2_logdens": r, "reported_r2": rep,
                     "r2_same": bool(rep is not None and abs(r - rep) < R2_TOL)})
        log.info("  %d %-4s %4d counties | MdAPE %6.2f %% | MAPE %7.2f %% | R2 log density %.4f (reported %s: %s%s)",
                 year, name, len(p), rows[-1]["mdape"], rows[-1]["mape"], r, reported,
                 "n/a" if rep is None else f"{rep:.4f}", "" if rows[-1]["r2_same"] else " DIFFERS")
    return rows


# ---------------------------------------------------------------- A2: fixed tract set

def read_tracts(vdir: Path) -> dict[int, pd.DataFrame]:
    out = {}
    for f in sorted(vdir.glob("tract_errors_*.csv")):
        m = re.fullmatch(r"tract_errors_(\d{4})\.csv", f.name)
        if not m:
            continue
        t = pd.read_csv(f)
        if "zone_gisjoin" not in t:
            sys.exit(f"ERROR: {f} has no zone_gisjoin (run tract_validate.py with --split)")
        out[int(m.group(1))] = t[t["flag"] == "ok"].reset_index(drop=True)
    return out


def tract_rows(set_name: str, year: int, t: pd.DataFrame, mape_min: float) -> list[dict]:
    obs = t["pop_obs"].to_numpy(dtype=float)
    rows = []
    for method in ("model", "baseline"):
        pred = t[f"pop_{method}"].to_numpy(dtype=float)
        rows.append({"set": set_name, "year": year, "method": method, "tracts": len(t),
                     "counties": int(t["zone_gisjoin"].nunique()), "pop_obs": float(obs.sum()),
                     "mdape": mdape(obs, pred), "mape": mape(obs, pred, mape_min),
                     "mape_n": int((obs >= mape_min).sum())})
    return rows


def fixed_sets(tracts: dict, starts, mape_min: float, names: pd.DataFrame):
    years = sorted(tracts)
    counties = {y: set(t["zone_gisjoin"]) for y, t in tracts.items()}
    rows = [r for y in years for r in tract_rows("all", y, tracts[y], mape_min)]
    members = []
    for s in starts:
        ys = [y for y in years if y >= s]
        if not ys:
            log.warning("fixed set from %d: no tract year from %d on; skipped", s, s)
            continue
        common = set.intersection(*(counties[y] for y in ys))
        label = f"from_{s}"
        log.info("fixed set %s (%d years %d-%d): %d counties tracted in every year", label, len(ys), ys[0], ys[-1],
                 len(common))
        listed = names[names["GISJOIN"].isin(common)].sort_values("GISJOIN")
        log.info("  %s", "; ".join(f"{r.GISJOIN} {r.name}, {r.state}" for r in listed.itertuples()) if len(common) <= 60
                 else f"(more than 60; see fixed_tract_counties.csv) first: "
                      f"{'; '.join(f'{r.GISJOIN} {r.name}, {r.state}' for r in listed.head(20).itertuples())}")
        members.append(listed.assign(set=label)[["set", "GISJOIN", "state", "name"]])
        for y in ys:
            rows += tract_rows(label, y, tracts[y][tracts[y]["zone_gisjoin"].isin(common)], mape_min)
    return pd.DataFrame(rows), (pd.concat(members, ignore_index=True) if members else pd.DataFrame())


def county_names(ddir: Path) -> pd.DataFrame:
    frames = [pd.read_csv(f, usecols=["GISJOIN", "state", "name"]) for f in sorted(ddir.glob("Y*/county_features.csv"))]
    if not frames:
        return pd.DataFrame(columns=["GISJOIN", "state", "name"])
    return pd.concat(frames, ignore_index=True).drop_duplicates("GISJOIN", keep="last")


# ---------------------------------------------------------------- figure

def plot(tr: pd.DataFrame, cm: pd.DataFrame, path: Path, version: str):
    """MdAPE by year: solid = model, dashed = areal weighting, one colour per set (fixed order); county TEST MdAPE
    (model before allocation) as its own line. One y-axis (%)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dasymetric"))
    import plots  # noqa: E402  (palette + style of the pipeline figures)
    plt = plots.plt
    sets = list(dict.fromkeys(tr["set"]))
    fig, ax = plt.subplots(figsize=(9.5, 5.5), dpi=150, layout="constrained")
    for i, s in enumerate(sets):
        color = plots.SERIES[i % len(plots.SERIES)]
        d = tr[tr["set"] == s]
        label = "all tracts" if s == "all" else f"fixed set {s[5:]}+"
        n = d.loc[d["method"] == "model", "counties"]
        label += f" ({int(n.iloc[0])} counties)" if s != "all" and len(n) else ""
        for method, ls, mk in (("model", "-", "o"), ("baseline", "--", None)):
            m = d[d["method"] == method].sort_values("year")
            ax.plot(m["year"], m["mdape"], ls=ls, color=color, lw=2 if method == "model" else 1.2, marker=mk, ms=5,
                    label=label if method == "model" else None)
    test = cm[cm["set"] == "test"].sort_values("year")
    if len(test):
        # ink, not the next series slot: another scale (counties), and slot 6 is a second green next to slot 3
        ax.plot(test["year"], test["mdape"], ls="-", color=plots.INK, lw=2, marker="s", ms=5,
                label="counties, TEST (before allocation)")
    ax.plot([], [], ls="--", color=plots.MUTED, lw=1.2, label="dashed: areal weighting (same tracts)")
    years = sorted(set(tr["year"]) | set(test["year"]))
    ax.set_xticks(years, [str(y) for y in years])
    ax.set_ylim(bottom=0)
    ax.set_xlabel("census year", fontsize=9, color=plots.INK2)
    ax.set_ylabel("MdAPE (%)", fontsize=9, color=plots.INK2)
    ax.set_title(f"{version}: median absolute % error by year, tracts (all / fixed county sets) and counties",
                 fontsize=10, color=plots.INK)
    ax.grid(axis="y", color=plots.GRID, lw=0.6)
    plots._style(ax)
    ax.legend(fontsize=8, frameon=False, labelcolor=plots.INK2, loc="upper left", bbox_to_anchor=(1.01, 1))
    plots._save(fig, path)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    ddir = args.results_root / "dasymetric" / args.name / args.version
    vdir = args.results_root / "validation" / args.name / args.version
    if not ddir.is_dir() or not vdir.is_dir():
        sys.exit(f"ERROR: {ddir} or {vdir} not found")

    log.info("== A1 county metrics (model before allocation vs census)")
    cm = pd.DataFrame([r for y, e in era_dirs(ddir).items() for r in county_rows(y, e, args.mape_min)])
    if cm.empty:
        sys.exit(f"ERROR: no era with test / oof predictions under {ddir}")
    bad = cm[~cm["r2_same"]]
    if len(bad):
        log.warning("recomputed R2 differs from the reported one:\n%s", bad.to_string(index=False))
    else:
        log.info("recomputed R2 = reported TEST R2 / pooled OOF R2 in all %d rows", len(cm))
    cm.to_csv(vdir / "county_metrics_by_year.csv", index=False)
    log.info("county metrics:\n%s", cm.pivot(index="year", columns="set", values=["counties", "mdape", "mape",
                                                                                  "r2_logdens"]).round(3).to_string())

    log.info("== A2 tract sets")
    tracts = read_tracts(vdir)
    if not tracts:
        sys.exit(f"ERROR: no tract_errors_*.csv in {vdir}")
    log.info("tract years %s", sorted(tracts))
    tr, members = fixed_sets(tracts, args.starts, args.mape_min, county_names(ddir))
    mby = vdir / "metrics_by_year.csv"  # the all-tracts MdAPE must equal tract_validate.py's
    if mby.exists():
        ref = pd.read_csv(mby)
        ref = ref[(ref["part"] == "all") & (ref["subset"] == "all")].set_index(["year", "method"])["mdape"]
        a = tr[tr["set"] == "all"].set_index(["year", "method"])["mdape"]
        diff = (a - ref.reindex(a.index)).abs()
        log.info("all-tracts MdAPE vs metrics_by_year.csv: max |difference| %.2e over %d rows%s", diff.max(),
                 int(diff.notna().sum()), "" if diff.max() < 1e-9 else " (DIFFERS)")
    tr.to_csv(vdir / "fixed_tract_metrics.csv", index=False)
    members.to_csv(vdir / "fixed_tract_counties.csv", index=False)
    with pd.option_context("display.width", 200):
        log.info("tract MdAPE / MAPE (tracts >= %g people) by set and year:\n%s", args.mape_min,
                 tr.pivot_table(index=["set", "year"], columns="method", values=["tracts", "counties", "mdape", "mape"],
                                sort=False).round(2).to_string())
    plot(tr, cm, vdir / "mdape_over_time.png", args.version)
    log.info("wrote %s", vdir)
    log.info("DONE")


if __name__ == "__main__":
    main()
