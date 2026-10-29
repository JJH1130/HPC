"""Uncertainty-filter sensitivity: v5.4 (no filter) vs the filtered versions on the same county sets (request
2026-10-30, docs/handoff/uncertainty_filter_request.md part 3; docs/conus_plan.md "Uncertainty filter"). Reads only
small result files that come back through git; runs locally as well.

Exclusion sets: results/hisdac_uncertainty/excluded_counties_t{090,070,050}.csv (src/grid/uncertainty_filter.py), one
fixed set of 2010 counties per threshold, nested (a smaller t excludes more).

County level, per year (before allocation, as metrics_over_time.py: predicted pop = exp(y_hat) x area_km2 of the
target, observed = census pop; MdAPE, MAPE over counties with pop >= --mape-min, R2 of log density):
  common_test   (a) TEST counties of v5.4 (test_predictions.csv) not excluded at the strictest threshold: every model
                scored them as TEST counties
  imputed_test  (b) TEST counties excluded at the loosest threshold: no model trained on them (v5.4: TEST; filtered
                models: excluded_predictions.csv, part test)
  own_excluded  each filtered model's own excluded counties (train and test part; sets differ: not for comparison)
Tract level (c), from tract_errors_{YEAR}.csv of each version (flag ok; not used for the choice): all, gap / no_gap
(BUI gap counties, column gap), and for every threshold kept_t<..> / excluded_t<..> (zone_gisjoin in that set); the
areal-weighting baseline (pop_baseline of v5.4) as its own row.

Choice (rule fixed 2026-10-30 before any result, request part 3): per model the mean over the years of
(MdAPE common_test + MdAPE imputed_test) / 2; the lowest wins; models within --tie percentage points of it count as
equal and the one keeping more counties wins (no filter > 0.9 > 0.7 > 0.5). Needs every year for every model. The
result is logged as one line; the decision is the user's.

Writes to --out-dir (results/validation/conus/uncertainty_filter/):
  filter_comparison.csv   version, threshold, year, level, set, n, counties, MdAPE, MAPE, R2 (county sets)
  filter_selection.csv    per model: mean (a), mean (b), score, within the tie, chosen
  filter_comparison.png   threshold vs MdAPE of (a) and (b), one line per year
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics_over_time import mape, mdape, r2  # noqa: E402

log = logging.getLogger("filter_compare")

YEARS = [1920, 1960, 2010, 2020]
FILTERED = ["0.9:Dasy_CONUS_RF_v3_u090", "0.7:Dasy_CONUS_RF_v3_u070", "0.5:Dasy_CONUS_RF_v3_u050"]
NONE = "none"


def label(t: float) -> str:
    return f"t{int(round(100 * t)):03d}"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="Dasy_CONUS_RF_v3_all", help="the no-filter version (v5.4)")
    p.add_argument("--filtered", nargs="+", default=FILTERED, help="threshold:version pairs")
    p.add_argument("--years", type=int, nargs="+", default=YEARS)
    p.add_argument("--name", default="conus")
    p.add_argument("--results-root", type=Path, default=Path("results"))
    p.add_argument("--exclusions", type=Path, default=Path("results/hisdac_uncertainty"))
    p.add_argument("--mape-min", type=float, default=10)
    p.add_argument("--tie", type=float, default=1.0, help="percentage points counted as equal")
    p.add_argument("--out-dir", type=Path, default=Path("results/validation/conus/uncertainty_filter"))
    return p.parse_args(argv)


# ---------------------------------------------------------------- county level

def county_metrics(pred: pd.DataFrame, cf: pd.DataFrame, mape_min: float, what: str) -> dict:
    p = pred[["GISJOIN", "y", "y_hat"]].merge(cf[["GISJOIN", "pop", "area_km2", "y"]], on="GISJOIN", how="left",
                                              suffixes=("", "_features"))
    if p["pop"].isna().any():
        sys.exit(f"ERROR: {what}: {int(p['pop'].isna().sum())} counties not in county_features.csv")
    if not np.allclose(p["y"], p["y_features"], rtol=0, atol=1e-9):
        sys.exit(f"ERROR: {what}: y differs from county_features.csv")
    obs = p["pop"].to_numpy()
    est = np.exp(p["y_hat"].to_numpy()) * p["area_km2"].to_numpy()
    return {"n": len(p), "counties": len(p), "pop_obs": float(obs.sum()), "mdape": mdape(obs, est),
            "mape": mape(obs, est, mape_min), "mape_n": int((obs >= mape_min).sum()),
            "r2_logdens": r2(p["y"].to_numpy(), p["y_hat"].to_numpy()) if len(p) > 1 else np.nan}


def pick(df: pd.DataFrame, ids: set, what: str) -> pd.DataFrame:
    got = df[df["GISJOIN"].isin(ids)]
    if set(got["GISJOIN"]) != ids:
        sys.exit(f"ERROR: {what}: {len(ids - set(got['GISJOIN']))} of {len(ids)} counties missing, e.g. "
                 f"{sorted(ids - set(got['GISJOIN']))[:10]}")
    return got


def county_rows(args, year: int, models: list, excl: dict) -> list[dict]:
    root = args.results_root / "dasymetric" / args.name
    strict, loose = min(excl), max(excl)
    base_dir = root / args.base / f"Y{year}"
    if not (base_dir / "test_predictions.csv").exists() or not (base_dir / "county_features.csv").exists():
        log.warning("%d: %s has no test_predictions.csv / county_features.csv; no county sets for this year", year,
                    base_dir)
        return []
    base_test = pd.read_csv(base_dir / "test_predictions.csv")
    test_ids = set(base_test["GISJOIN"])
    sets = {"common_test": test_ids - excl[strict], "imputed_test": test_ids & excl[loose]}
    log.info("%d: TEST counties of %s %d | (a) common_test = not excluded at t = %.1f: %d | (b) imputed_test = "
             "excluded at t = %.1f: %d", year, args.base, len(test_ids), strict, len(sets["common_test"]), loose,
             len(sets["imputed_test"]))
    base_cf = pd.read_csv(base_dir / "county_features.csv")
    rows = []
    for t, v in models:
        d = root / v / f"Y{year}"
        need = [d / "county_features.csv", d / "test_predictions.csv"] + ([] if t == NONE else [d / "excluded_predictions.csv"])
        missing = [str(f) for f in need if not f.exists()]
        if missing:
            log.warning("%d %s: missing %s; left out", year, v, missing)
            continue
        cf = pd.read_csv(need[0])
        same = cf[["GISJOIN", "y"]].merge(base_cf[["GISJOIN", "y"]], on="GISJOIN", suffixes=("", "_base"))
        if len(same) != len(base_cf) or not np.allclose(same["y"], same["y_base"], rtol=0, atol=1e-9):
            log.warning("%d %s: county targets differ from %s (%d of %d matched)", year, v, args.base, len(same),
                        len(base_cf))
        test = pd.read_csv(need[1])
        if t == NONE:
            preds = {"common_test": test, "imputed_test": test}
        else:
            ex = pd.read_csv(need[2])
            leak = set(test["GISJOIN"]) & excl[t]
            if leak:
                sys.exit(f"ERROR: {year} {v}: excluded counties in its TEST predictions: {sorted(leak)[:10]}")
            preds = {"common_test": test, "imputed_test": ex[ex["part"] == "test"], "own_excluded": ex}
        for s, df in preds.items():
            ids = sets.get(s, set(df["GISJOIN"]))
            m = county_metrics(pick(df, ids, f"{year} {v} {s}"), cf, args.mape_min, f"{year} {v} {s}")
            rows.append({"version": v, "threshold": t, "year": year, "level": "county", "set": s, **m})
            log.info("  %d %-24s t=%-4s %-12s %4d counties | MdAPE %6.2f %% | MAPE %7.2f %% | R2 %.3f", year, v, t, s,
                     m["n"], m["mdape"], m["mape"], m["r2_logdens"])
    return rows


# ---------------------------------------------------------------- tract level

def tract_rows(args, year: int, models: list, excl: dict) -> list[dict]:
    vroot = args.results_root / "validation" / args.name
    rows = []
    for t, v in [*models, (NONE, "areal_weighting")]:
        path = vroot / (args.base if v == "areal_weighting" else v) / f"tract_errors_{year}.csv"
        if not path.exists():
            log.warning("%d %s: %s missing; no tract rows", year, v, path)
            continue
        te = pd.read_csv(path)
        te = te[te["flag"] == "ok"]
        col = "pop_baseline" if v == "areal_weighting" else "pop_model"
        parts = {"all": np.ones(len(te), bool)}
        if "gap" in te:
            g = te["gap"].astype(str).str.lower() == "true"
            parts.update({"gap": g.to_numpy(), "no_gap": (~g).to_numpy()})
        for tt, ids in excl.items():
            inside = te["zone_gisjoin"].isin(ids).to_numpy()
            parts.update({f"kept_{label(tt)}": ~inside, f"excluded_{label(tt)}": inside})
        for s, m in parts.items():
            sub = te[m]
            obs, est = sub["pop_obs"].to_numpy(float), sub[col].to_numpy(float)
            rows.append({"version": v, "threshold": t, "year": year, "level": "tract", "set": s, "n": len(sub),
                         "counties": int(sub["zone_gisjoin"].nunique()), "pop_obs": float(obs.sum()),
                         "mdape": mdape(obs, est), "mape": mape(obs, est, args.mape_min),
                         "mape_n": int((obs >= args.mape_min).sum()), "r2_logdens": np.nan})
    return rows


# ---------------------------------------------------------------- choice + figure

def choose(cmp: pd.DataFrame, models: list, years, tie: float) -> pd.DataFrame:
    c = cmp[(cmp["level"] == "county") & cmp["set"].isin(["common_test", "imputed_test"])]
    rows = []
    for t, v in models:
        d = c[c["version"] == v].pivot_table(index="year", columns="set", values="mdape")
        full = set(years) <= set(d.index) and {"common_test", "imputed_test"} <= set(d.columns)
        a = float(d["common_test"].mean()) if "common_test" in d else np.nan
        b = float(d["imputed_test"].mean()) if "imputed_test" in d else np.nan
        rows.append({"version": v, "threshold": t, "years": len(d), "complete": full, "mean_common_test": a,
                     "mean_imputed_test": b, "score": (a + b) / 2 if full else np.nan,
                     "keep_order": np.inf if t == NONE else float(t)})
    s = pd.DataFrame(rows)
    ok = s["complete"]
    s["within_tie"] = False
    s["chosen"] = False
    if ok.any():
        best = s.loc[ok, "score"].min()
        s.loc[ok, "within_tie"] = s.loc[ok, "score"] <= best + tie
        win = s[s["within_tie"]].sort_values("keep_order", ascending=False).index[0]
        s.loc[win, "chosen"] = True
    return s.drop(columns="keep_order")


def plot(cmp: pd.DataFrame, models: list, years, path: Path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dasymetric"))
    import plots  # noqa: E402  (palette + style of the pipeline figures)
    plt = plots.plt
    order = [t for t, _ in models]
    xs = {t: i for i, t in enumerate(order)}
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), dpi=150, layout="constrained", sharey=True)
    for ax, (s, title) in zip(axes, (("common_test", "(a) common TEST counties"),
                                     ("imputed_test", "(b) TEST counties excluded at t = 0.9 (imputed)"))):
        for i, y in enumerate(years):
            d = cmp[(cmp["level"] == "county") & (cmp["set"] == s) & (cmp["year"] == y)]
            d = d.assign(x=d["threshold"].map(xs)).dropna(subset=["x"]).sort_values("x")
            if d.empty:
                continue
            ax.plot(d["x"], d["mdape"], color=plots.SERIES[i % len(plots.SERIES)], lw=2, marker="o", ms=6,
                    label=str(y))
        ax.set_xticks(range(len(order)), ["no filter" if t == NONE else f"t = {t}" for t in order])
        ax.set_title(title, fontsize=10, color=plots.INK)
        ax.set_xlabel("county filter (ratio_A_nby >= t + fixed rules excluded)", fontsize=9, color=plots.INK2)
        ax.grid(axis="y", color=plots.GRID, lw=0.6)
        plots._style(ax)
    axes[0].set_ylabel("county MdAPE before allocation (%)", fontsize=9, color=plots.INK2)
    axes[0].set_ylim(bottom=0)
    axes[1].legend(fontsize=8, frameon=False, labelcolor=plots.INK2, title="year", title_fontsize=8)
    plots._save(fig, path)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    filtered = []
    for item in args.filtered:
        t, v = item.split(":", 1)
        filtered.append((float(t), v))
    filtered.sort(key=lambda p: -p[0])  # loosest first
    excl = {}
    for t, _ in filtered:
        f = args.exclusions / f"excluded_counties_{label(t)}.csv"
        if not f.exists():
            sys.exit(f"ERROR: {f} not found (src/grid/uncertainty_filter.py)")
        excl[t] = set(pd.read_csv(f)["GISJOIN"])
        log.info("t = %.1f: %d excluded counties (%s)", t, len(excl[t]), f)
    ts = sorted(excl, reverse=True)
    if not all(excl[a] <= excl[b] for a, b in zip(ts, ts[1:])):
        log.warning("exclusion sets are not nested")
    log.info("RULE (fixed before the results, request 2026-10-30): mean over %s of (MdAPE (a) common_test + MdAPE (b) "
             "imputed_test) / 2; lowest wins; within %.1f pp the model keeping more counties wins "
             "(no filter > larger t); the final choice is the user's", args.years, args.tie)
    models = [(NONE, args.base), *filtered]
    rows = []
    for y in args.years:
        rows += county_rows(args, y, models, excl)
        rows += tract_rows(args, y, models, excl)
    cmp = pd.DataFrame(rows)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    cmp.to_csv(out / "filter_comparison.csv", index=False)
    sel = choose(cmp, models, args.years, args.tie)
    sel.to_csv(out / "filter_selection.csv", index=False)
    with pd.option_context("display.width", 220, "display.max_rows", 500):
        c = cmp[cmp["level"] == "county"].pivot_table(index=["set", "year"], columns="threshold", values="mdape",
                                                      sort=False)
        log.info("county MdAPE (%%) by set, year and threshold:\n%s", c.round(2).to_string())
        t = cmp[(cmp["level"] == "tract") & cmp["set"].isin(["all", "gap", "no_gap", "kept_t050", "excluded_t050",
                                                             "kept_t090", "excluded_t090"])]
        log.info("tract MdAPE (%%), not used for the choice:\n%s",
                 t.pivot_table(index=["set", "year"], columns="version", values="mdape", sort=False).round(2).to_string())
        log.info("selection:\n%s", sel.round(3).to_string(index=False))
    if sel["chosen"].any():
        w = sel[sel["chosen"]].iloc[0]
        log.info("RULE RESULT: %s (threshold %s): score %.2f %% (mean (a) %.2f, (b) %.2f); within %.1f pp: %s -> the "
                 "user decides", w["version"], w["threshold"], w["score"], w["mean_common_test"],
                 w["mean_imputed_test"], args.tie, sel.loc[sel["within_tie"], "version"].tolist())
    else:
        log.warning("RULE RESULT: none (no model has all years %s)", args.years)
    if len(cmp):
        plot(cmp, models, args.years, out / "filter_comparison.png")
    log.info("wrote %s", out)
    log.info("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
