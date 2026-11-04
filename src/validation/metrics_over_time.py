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
With --compare-with VERSION [VERSION ...] (v5.6 next to v5.4, docs/conus_plan.md "v5.6 all years"; v5.7 next to v5.4
and v5.6, "v5.7 all years"), those versions' county TEST and tract sets (the same --starts, computed the same way from
their own files) are drawn in the figure (model only, same colour per set; dotted, then dash-dot); their CSVs are not
written here.

All TEST counties (reporting rule of 2026-11-04, docs/open_items.md): set `test` is the model's own TEST set
(test_predictions.csv; with a county filter only the kept TEST counties), set `test_all` every TEST county of the split
= test_predictions.csv + the TEST part of excluded_predictions.csv (the fitted model's prediction for the counties the
filter left out; the same as `test` without a filter), the main county number and the county line of the figure. With
--exclusions excluded_counties_t070.csv the test_all rows are also split into test_kept_t070 / test_excluded_t070
(labelled, next to it). --check-against v54_nby_comparison.csv: the county rows (test_all / kept / excluded: MdAPE,
MAPE, R2) and the all-tracts MdAPE of every version and year also in that table must be the same (1e-9), else stop
before writing (check_against, also used by compare_models.py).
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
    p.add_argument("--compare-with", metavar="VERSION", nargs="+", default=[],
                   help="draw these versions as dotted / dash-dot lines (e.g. v5.4 v5.6)")
    p.add_argument("--exclusions", type=Path, metavar="CSV",
                   help="excluded_counties_t070.csv: split the all-TEST county rows into kept / excluded (labelled)")
    p.add_argument("--check-against", type=Path, metavar="CSV",
                   help="v54_nby_comparison.csv: shared county / all-tracts numbers must be the same, else stop")
    return p.parse_args(argv)


def exclusion_set(path: Path | None):
    """(label, GISJOIN set) of excluded_counties_<label>.csv, or None."""
    if path is None:
        return None
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (src/grid/uncertainty_filter.py)")
    return path.stem.replace("excluded_counties_", ""), set(pd.read_csv(path)["GISJOIN"])


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


PRED_COLS = ["GISJOIN", "year", "y", "y_hat"]


def all_test_predictions(edir: Path) -> tuple[pd.DataFrame, bool]:
    """(GISJOIN, year, y, y_hat of every TEST county of the split, filtered?): test_predictions.csv + the TEST part of
    excluded_predictions.csv (written by train.py with exclude_counties; none without a filter)."""
    tp = pd.read_csv(edir / "test_predictions.csv")[PRED_COLS]
    ex_path = edir / "excluded_predictions.csv"
    if not ex_path.exists():
        return tp, False
    ex = pd.read_csv(ex_path)
    ex = ex.loc[ex["part"] == "test", PRED_COLS]
    both = set(tp["GISJOIN"]) & set(ex["GISJOIN"])
    if both:
        sys.exit(f"ERROR: {edir}: {len(both)} counties both in test_predictions.csv and excluded_predictions.csv")
    return pd.concat([tp, ex], ignore_index=True), True


def _score(year: int, name: str, p: pd.DataFrame, cf: pd.DataFrame, col: str, mape_min: float, rep, reported: str,
           what: str) -> dict:
    p = p.merge(cf, on=["GISJOIN", "year"], how="left", suffixes=("", "_features"))
    if p["pop"].isna().any():
        sys.exit(f"ERROR: {year} {name}: {int(p['pop'].isna().sum())} predicted counties not in county_features.csv")
    if not np.allclose(p["y"], p["y_features"], rtol=0, atol=1e-9):
        sys.exit(f"ERROR: {year} {name}: y of {what} differs from county_features.csv")
    obs = p["pop"].to_numpy()
    pred = np.exp(p[col].to_numpy()) * p["area_km2"].to_numpy()
    back = np.exp(p["y"].to_numpy()) * p["area_km2"].to_numpy()  # exp(y) x area must give the census pop back
    if not np.allclose(back, obs, rtol=1e-9):
        sys.exit(f"ERROR: {year} {name}: exp(y) x area_km2 != pop (area definition differs from the target)")
    r = r2(p["y"].to_numpy(), p[col].to_numpy()) if len(p) > 1 else np.nan
    row = {"year": year, "set": name, "counties": len(p), "pop": float(obs.sum()), "pop_pred": float(pred.sum()),
           "mdape": mdape(obs, pred), "mape": mape(obs, pred, mape_min), "mape_n": int((obs >= mape_min).sum()),
           "r2_logdens": r, "reported_r2": rep,
           "r2_same": None if rep is None and not reported else bool(rep is not None and abs(r - rep) < R2_TOL)}
    log.info("  %d %-20s %4d counties | MdAPE %6.2f %% | MAPE %7.2f %% | R2 log density %.4f%s", year, name, len(p),
             row["mdape"], row["mape"], r, "" if not reported else
             f" (reported {reported}: {'n/a' if rep is None else f'{rep:.4f}'}{'' if row['r2_same'] else ' DIFFERS'})")
    return row


def county_rows(year: int, edir: Path, mape_min: float, excl=None) -> list[dict]:
    """Rows test (own TEST set), cv (out of fold), test_all (every TEST county of the split) and, with `excl` =
    (label, GISJOIN set), test_kept_<label> / test_excluded_<label> (the test_all rows split)."""
    need = [edir / f for f in ("county_features.csv", "test_predictions.csv", "oof_predictions.csv", "metrics.json")]
    missing = [str(f) for f in need if not f.exists()]
    if missing:
        log.warning("%d: county metrics skipped, missing %s", year, missing)
        return []
    cf = pd.read_csv(need[0])[["GISJOIN", "year", "pop", "area_km2", "y"]]
    met = json.loads(need[3].read_text())
    rows = []
    for name, path, col, reported in (("test", need[1], "y_hat", "test_r2"), ("cv", need[2], "oof", "oof_pooled_r2")):
        p = pd.read_csv(path)[["GISJOIN", "year", "y", col]]
        rows.append(_score(year, name, p, cf, col, mape_min, met.get(reported), reported, path.name))
    ta, filtered = all_test_predictions(edir)
    # without a filter test_all = the reported TEST set (its R2 checked); with one there is no reported value
    sets = [("test_all", np.ones(len(ta), bool), None if filtered else "test_r2")]
    if excl is not None:
        inside = ta["GISJOIN"].isin(excl[1]).to_numpy()
        sets += [(f"test_kept_{excl[0]}", ~inside, None), (f"test_excluded_{excl[0]}", inside, None)]
    for name, m, reported in sets:
        r = _score(year, name, ta[m], cf, "y_hat", mape_min, met.get(reported) if reported else None, reported or "",
                   "test / excluded predictions")
        rows.append({**r, "filtered": filtered})
    for r in rows:
        r.setdefault("filtered", filtered)
    return rows


def check_against(path: Path, version: str, county: pd.DataFrame | None, tract: pd.DataFrame | None) -> int:
    """The numbers of `version` that are also in `path` (v54_nby_comparison.csv: level county set test_all /
    test_kept_t070 / test_excluded_t070 -> mdape, mape, r2; level tract set all -> mdape) must be the same (1e-9
    relative); stops on a difference. county: year, set, mdape, mape, r2; tract: year, mdape (all tracts). Returns the
    number of rows compared (0 = the version is not in the table)."""
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (--check-against)")
    ref = pd.read_csv(path)
    ref = ref[ref["version"] == version]
    n = 0
    for level, new, keys, cols in (("county", county, ["year", "set"], ["mdape", "mape", "r2"]),
                                   ("tract", tract, ["year"], ["mdape"])):
        if new is None or not len(new):
            continue
        old = ref[ref["level"] == level]
        if level == "tract":
            old = old[old["set"] == "all"]
        m = new[keys + cols].merge(old[keys + cols], on=keys, suffixes=("", "__ref"))
        for c in cols:
            a, b = m[c].to_numpy(float), m[c + "__ref"].to_numpy(float)
            bad = ~np.isclose(a, b, rtol=1e-9, atol=1e-12, equal_nan=True)
            if bad.any():
                sys.exit(f"ERROR: {version} {level} {c} differs from {path} for {m.loc[bad, keys].to_dict('records')}: "
                         f"{a[bad].tolist()} vs {b[bad].tolist()}")
        n += len(m)
        log.info("  MATCH %s %s %s: %d rows (%s; years %s)", path.name, version, level, len(m), ", ".join(cols),
                 sorted(set(m["year"])))
    return n


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

OTHER_LS = [":", "-.", (0, (1, 3))]  # compared versions, in --compare-with order


def county_line(cm: pd.DataFrame) -> pd.DataFrame:
    """The county rows of the figure: all TEST counties (test_all; `test` for tables written before it existed)."""
    s = "test_all" if (cm["set"] == "test_all").any() else "test"
    return cm[cm["set"] == s].sort_values("year")


def plot(tr: pd.DataFrame, cm: pd.DataFrame, path: Path, version: str, others=()):
    """MdAPE by year: solid = model, dashed = areal weighting, one colour per set (fixed order); county MdAPE on all
    TEST counties (model before allocation) as its own line. One y-axis (%). others = [(version, tract sets, county
    metrics)] of compared versions: their model lines dotted / dash-dot, same colours."""
    others = list(others)
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
        for k, other in enumerate(others):
            o = other[1]
            o = o[(o["set"] == s) & (o["method"] == "model")].sort_values("year")
            ax.plot(o["year"], o["mdape"], ls=OTHER_LS[k % len(OTHER_LS)], color=color, lw=1.6)
    test = county_line(cm)
    if len(test):
        # ink, not the next series slot: another scale (counties), and slot 6 is a second green next to slot 3
        ax.plot(test["year"], test["mdape"], ls="-", color=plots.INK, lw=2, marker="s", ms=5,
                label="counties, all TEST (before allocation)")
    for k, other in enumerate(others):
        ot = county_line(other[2])
        ax.plot(ot["year"], ot["mdape"], ls=OTHER_LS[k % len(OTHER_LS)], color=plots.INK, lw=1.6)
    ax.plot([], [], ls="--", color=plots.MUTED, lw=1.2, label="dashed: areal weighting (same tracts)")
    for k, other in enumerate(others):
        name = {":": "dotted", "-.": "dash-dot"}.get(OTHER_LS[k % len(OTHER_LS)], "fine dots")
        ax.plot([], [], ls=OTHER_LS[k % len(OTHER_LS)], color=plots.MUTED, lw=1.6, label=f"{name}: {other[0]} (model)")
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

    excl = exclusion_set(args.exclusions)
    log.info("== A1 county metrics (model before allocation vs census; main = test_all, every TEST county of the split)")
    cm = pd.DataFrame([r for y, e in era_dirs(ddir).items() for r in county_rows(y, e, args.mape_min, excl)])
    if cm.empty:
        sys.exit(f"ERROR: no era with test / oof predictions under {ddir}")
    bad = cm[cm["r2_same"] == False]  # noqa: E712  (None = no reported value for that set)
    if len(bad):
        log.warning("recomputed R2 differs from the reported one:\n%s", bad.to_string(index=False))
    else:
        log.info("recomputed R2 = reported TEST R2 / pooled OOF R2 in all %d rows with a reported value",
                 int(cm["r2_same"].notna().sum()))
    log.info("county metrics:\n%s", cm.pivot(index="year", columns="set", values=["counties", "mdape", "mape",
                                                                                  "r2_logdens"]).round(3).to_string())

    log.info("== A2 tract sets")
    tracts = read_tracts(vdir)
    if not tracts:
        sys.exit(f"ERROR: no tract_errors_*.csv in {vdir}")
    log.info("tract years %s", sorted(tracts))
    tr, members = fixed_sets(tracts, args.starts, args.mape_min, county_names(ddir))
    others = []
    for v in args.compare_with:
        oddir = args.results_root / "dasymetric" / args.name / v
        ovdir = args.results_root / "validation" / args.name / v
        ocm = pd.DataFrame([r for y, e in era_dirs(oddir).items() for r in county_rows(y, e, args.mape_min, excl)])
        otr = fixed_sets(read_tracts(ovdir), args.starts, args.mape_min, county_names(oddir))[0]
        others.append((v, otr, ocm))
    if args.check_against:  # before anything is written
        log.info("check against %s:", args.check_against)
        for v, t, c in [(args.version, tr, cm)] + others:
            cc = c[c["set"].str.startswith("test_")].rename(columns={"r2_logdens": "r2"})
            tt = t[(t["set"] == "all") & (t["method"] == "model")]
            if check_against(args.check_against, v, cc, tt) == 0:
                log.info("  %s: not in %s, nothing compared", v, args.check_against.name)
    cm.to_csv(vdir / "county_metrics_by_year.csv", index=False)
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
    for v, otr, ocm in others:
        with pd.option_context("display.width", 200):
            a = tr[tr["method"] == "model"].pivot_table(index="year", columns="set", values="mdape", sort=False)
            b = otr[otr["method"] == "model"].pivot_table(index="year", columns="set", values="mdape", sort=False)
            log.info("tract MdAPE (%%), %s minus %s (negative = %s better):\n%s", args.version, v, args.version,
                     (a - b).round(2).to_string())
            ct = pd.DataFrame({k: county_line(cm).set_index("year")[k] - county_line(ocm).set_index("year")[k]
                               for k in ("mdape", "mape", "r2_logdens")})
            log.info("county TEST MdAPE (%%), %s minus %s (all TEST counties; MAPE %%, R2 of log density):\n%s",
                     args.version, v, ct.round(3).to_string())
    plot(tr, cm, vdir / "mdape_over_time.png", args.version, others)
    log.info("wrote %s", vdir)
    log.info("DONE")


if __name__ == "__main__":
    main()
