"""PLURAL on v5.7 (Stefan 2026-11-17 item 2; request 2026-11-19, docs/handoff/v57_plural_density_request.md;
docs/conus_plan.md "PLURAL on v5.7"). The six PLURAL variants of the v5.6 test (docs/conus_plan.md "PLURAL grid test")
again, on v5.7 (Dasy_CONUS_RF_v3_all_nby: v5.4 + nby, no filter): every era = v5.7's era of the year + plural, the
plural block of conus_rf_v3_u070_<variant>.yaml, 1940 / 1980 / 2010 (the PLURAL grid's years). Versions:
  v57            Dasy_CONUS_RF_v3_all_nby             (v5.7, the base)
  v57_<variant>  Dasy_CONUS_RF_v3_all_nby_<variant>   (v5.7 + plural; plc, plcc, pq3, pq5, pe3, pe5)
  v56            Dasy_CONUS_RF_v3_u070                (v5.6; key "base" of plural_compare: tract sets, gap counties)
  v56_<variant>  Dasy_CONUS_RF_v3_u070_<variant>      (v5.6 + plural, reference columns from the earlier test)

Three subcommands:
  config    each new config = v5.7's era of each year + plural (appended), the plural block of the v5.6 test's config,
            every other setting as v5.7, feature_groups = v5.7's + PLURAL: [plural], compare_with v5.7, no
            exclude_counties; CONFIG OK or the differences (exit 1). Login-node pre-check of submit_conus.sh v57plural.
  features  after the six features jobs, before train (the chain stops on a difference): per variant and year the new
            county_features.csv (results copy) against v5.7's: same counties, every v5.7 column equal (rtol 1e-12),
            one column more (plural); plural = the v5.6 test's county plural on the common counties (rtol 1e-9; a
            different county set is logged); classed variants: plural_breaks.csv = the v5.6 test's (layer, breaks,
            classes, study cells, breaks and class shares; |diff| <= 1e-12) - the same cutout and the same study cells
            give the same breaks. -> plural_v57_features_check.csv. FEATURES OK or exit 1.
  compare   the comparison (after validate). Reporting rule (open_items): county metrics on ALL TEST counties; kept /
            excluded t070 only labelled beside them.
            - county, before allocation (v54_nby_compare.county_rows): test_all / test_kept_t070 / test_excluded_t070
              MdAPE, MAPE, R2 of log density; CV RMSE / R2 in columns named by the CV county set (v5.7 and its
              variants: train_all, one CV set; v5.6 and its variants: train_kept_t070); ranks of plural and nby
            - tracts (plural_compare.tract_rows): all, kept / excluded t070, no_gap / gap (v5.6's gap counties), four
              observed density classes, + areal weighting; d_mdape = MdAPE - v5.7's, d_mdape_own = MdAPE - the
              version's own base (v5.7 for v57_*, v5.6 for v56_*)
            - cells (--dasym-root + --cutout-root; nobuilt_compare.cell_sums): people on BUI = 0 cells and of those on
              NobuiltYear > 0 cells (Stefan: does plural move people onto or off cells without a dated record?).
              Without the raster flags the cells CSV of an earlier run in --out-dir is read again
            - ranks of plural / nby (permutation / mean |SHAP|) per version and year
            - selection rule (fixed 2026-11-19 before the results): per variant, the number of years with a county CV
              RMSE below v5.7's and the mean change (folds.csv equal to v5.7's, else stop); not by tracts (the "best
              classed variant" tract rule of the v5.6 test chose the county maps only and is not used here); the user
              decides -> plural_v57_cv_rule.csv
            Checks, a difference stops the run before writing: v5.6 / v5.7 / areal weighting rows = v54_nby_comparison.csv
            (county, tract, cells levels present) and v54_nby_cells.csv; v5.6 and v5.6 + plural rows =
            plural_comparison.csv (tracts; county: its TEST = our test_kept_t070, CV, plural ranks).

Writes to --out-dir (results/validation/conus/plural_grid_v57/; nothing of plural_grid/ or nobuilt/ is touched):
  plural_v57_comparison.csv      version, variant, year, level (county / tract / cells), set, city, n, counties, mdape,
                                 mape, mape_n, d_mdape, d_mdape_own, r2, CV columns, ranks, share (cells)
  plural_v57_cells.csv           as v54_nby_cells.csv, every version with a prediction on scratch
  plural_v57_feature_ranks.csv   version, variant, year, feature, permutation / mean |SHAP| value and rank
  plural_v57_cv_rule.csv         variant, year, CV counties, CV RMSE / R2 of v5.7 and the variant, change, lower,
                                 + per variant years_lower / mean_d_cv_rmse / mean_rel_d_cv_rmse
  plural_v57_features_check.csv  (features) one row per variant and year
No figure.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "dasymetric")]
import builtcell_compare as bc  # noqa: E402  (feature rank table)
import nobuilt_compare as nc  # noqa: E402  (cells)
import plural_compare as pc  # noqa: E402  (tract rows, variants)
import v54_nby_compare as vc  # noqa: E402  (county rows on all TEST counties)
import v57_nbya_compare as vn  # noqa: E402  (row checks against earlier tables)

log = logging.getLogger("v57_plural_compare")

YEARS = list(pc.YEARS)  # 1940 / 1980 / 2010
VARIANTS = list(pc.VARIANTS)  # plc, plcc, pq3, pq5, pe3, pe5
V57, V56 = "Dasy_CONUS_RF_v3_all_nby", "Dasy_CONUS_RF_v3_u070"
REF = "v57"
RANK_FEATURES = ("plural", "nby")
SAME_AS_V57 = ("study_area", "water_mask", "split", "exclude_counties", "use_status", "train_status", "unusable",
               "block_rows", "maps", "correlation_threshold", "model", "search", "permutation", "models")
FEATURE_RTOL = 1e-12  # v5.7's columns: the same cells, the same code
PLURAL_RTOL = 1e-9  # county plural vs the v5.6 test's (same cutout, same cells; strips summed in the same order)
BREAK_TOL = 1e-12


def versions(variants=VARIANTS) -> dict:
    """label -> version; "base" (= v5.6) first: plural_compare.tract_rows takes the tract sets from it."""
    out = {"base": V56, "v57": V57}
    out.update({f"v57_{v}": f"{V57}_{v}" for v in variants})
    out.update({f"v56_{v}": f"{V56}_{v}" for v in variants})
    return out


def label(var: str) -> str:
    return vc.label(var)  # base -> v56


def order(variants) -> list[str]:
    return ["v57", *[f"v57_{v}" for v in variants], "v56", *[f"v56_{v}" for v in variants], pc.AREAL]


CONFIG_PATTERN = {"new": "configs/conus_rf_v3_all_nby_{v}.yaml", "old": "configs/conus_rf_v3_u070_{v}.yaml"}


def config_path(kind: str, variant: str, pattern: str | None = None) -> Path:
    return Path((pattern or CONFIG_PATTERN[kind]).format(v=variant))


def add_common(p):
    p.add_argument("--variants", nargs="+", default=VARIANTS)
    p.add_argument("--years", type=int, nargs="+", default=YEARS)
    p.add_argument("--name", default="conus")
    p.add_argument("--results-root", type=Path, default=Path("results"))
    p.add_argument("--out-dir", type=Path, default=Path("results/validation/conus/plural_grid_v57"))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("config", help="new configs = v5.7 + plural")
    c.add_argument("--variants", nargs="+", default=VARIANTS)
    c.add_argument("--years", type=int, nargs="+", default=YEARS)
    c.add_argument("--v57-config", type=Path, default=Path("configs/conus_rf_v3_all_nby.yaml"))
    c.add_argument("--new-pattern", default=CONFIG_PATTERN["new"], help="new config path, {v} = variant")
    c.add_argument("--old-pattern", default=CONFIG_PATTERN["old"], help="v5.6 test config path, {v} = variant")
    f = sub.add_parser("features", help="county features = v5.7's + plural of the v5.6 test; breaks = the v5.6 test's")
    add_common(f)
    m = sub.add_parser("compare", help="the comparison")
    add_common(m)
    m.add_argument("--exclusions", type=Path, default=Path("results/hisdac_uncertainty/excluded_counties_t070.csv"))
    m.add_argument("--split", type=Path, default=Path("configs/conus_split.csv"))
    m.add_argument("--mape-min", type=float, default=10)
    m.add_argument("--nobuilt-dir", type=Path, default=Path("results/validation/conus/nobuilt"),
                   help="v54_nby_comparison.csv / v54_nby_cells.csv (v5.6 / v5.7 rows checked)")
    m.add_argument("--plural-dir", type=Path, default=Path("results/validation/conus/plural_grid"),
                   help="plural_comparison.csv of the v5.6 test (v5.6 + plural rows checked)")
    m.add_argument("--dasym-root", type=Path, help="<root>/<name>/<version>/predictions/pop_{YEAR}.tif (cells)")
    m.add_argument("--cutout-root", type=Path, help="<root>/<name>/layers/{BUI,NOBUILT}/ (cells)")
    a = p.parse_args(argv)
    a.base = V56  # for plural_compare.tract_rows
    return a


# ---------------------------------------------------------------- config

def config_problems(new: dict, v57: dict, old: dict, variant: str, years) -> list[str]:
    """Differences of one new config from 'v5.7 + plural with the v5.6 test's plural block' (empty = OK)."""
    bad = []
    want_v = f"{V57}_{variant}"
    if new["version"] != want_v:
        bad.append(f"version {new['version']} != {want_v}")
    if new.get("compare_with") != v57["version"]:
        bad.append(f"compare_with {new.get('compare_with')} != {v57['version']}")
    if sorted(new["years"]) != sorted(years):
        bad.append(f"years {new['years']} != {sorted(years)}")
    if new.get("plural") is None or new.get("plural") != old.get("plural"):
        bad.append(f"plural block {new.get('plural')} != {old.get('plural')} (conus_rf_v3_u070_{variant}.yaml)")
    if new.get("exclude_counties") is not None:
        bad.append("exclude_counties given (v5.7 has none)")
    for k in SAME_AS_V57:
        if new.get(k) != v57.get(k):
            bad.append(f"{k}: {new.get(k)} != v5.7 {v57.get(k)}")
    want = {f"Y{y}" for y in years}
    if set(new["eras"]) != want:
        bad.append(f"eras {sorted(new['eras'])} != {sorted(want)}")
    for e in sorted(set(new["eras"]) & want):
        n, b = new["eras"][e], v57["eras"].get(e)
        if b is None:
            bad.append(f"{e}: not in v5.7")
            continue
        if n["years"] != b["years"]:
            bad.append(f"{e}: years {n['years']} != v5.7 {b['years']}")
        if "plural" in b["features"] or n["features"] != b["features"] + ["plural"]:
            bad.append(f"{e}: features {n['features']} != v5.7 {b['features']} + plural")
    fg = {**(v57.get("feature_groups") or {}), "PLURAL": ["plural"]}
    if new.get("feature_groups") != fg:
        bad.append(f"feature_groups {new.get('feature_groups')} != v5.7's + PLURAL: [plural] {fg}")
    return bad


def cmd_config(args) -> int:
    import common as dcommon
    v57 = dcommon.load_config(args.v57_config)
    n_bad = 0
    for v in args.variants:
        new_p, old_p = config_path("new", v, args.new_pattern), config_path("old", v, args.old_pattern)
        bad = config_problems(dcommon.load_config(new_p), v57, dcommon.load_config(old_p), v, args.years)
        for b in bad:
            print(f"CONFIG DIFFERS {v}: {b}")
        n_bad += len(bad)
        if not bad:
            print(f"  {v}: {new_p} = v5.7 eras + plural, plural block = {old_p}")
    if n_bad:
        print(f"ERROR: {n_bad} differences from v5.7 + plural")
        return 1
    print(f"CONFIG OK: {len(args.variants)} configs = {args.v57_config} eras {['Y%d' % y for y in args.years]} + plural "
          f"({', '.join(args.variants)}), plural blocks = the v5.6 test's, every other setting as v5.7")
    return 0


# ---------------------------------------------------------------- features (+ breaks)

def era_dir(args, version: str, year: int) -> Path:
    return args.results_root / "dasymetric" / args.name / version / f"Y{year}"


def _num_equal(x: pd.Series, z: pd.Series, rtol: float) -> np.ndarray:
    if pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(z):
        return np.isclose(x.to_numpy(float), z.to_numpy(float), rtol=rtol, atol=0, equal_nan=True)
    return (x.astype(str) == z.astype(str)).to_numpy()


def breaks_check(args, variant: str, year: int) -> dict:
    """plural_breaks.csv of the new version = the v5.6 test's (classed variants; continuous: neither has one)."""
    fn = era_dir(args, f"{V57}_{variant}", year) / "plural_breaks.csv"
    fo = era_dir(args, f"{V56}_{variant}", year) / "plural_breaks.csv"
    if variant not in pc.CLASSED:
        for f in (fn, fo):
            if f.exists():
                sys.exit(f"ERROR: {year} {variant}: {f} exists for a continuous variant")
        return {"breaks": "continuous", "breaks_max_abs_diff": np.nan, "breaks_ok": True}
    for f in (fn, fo):
        if not f.exists():
            sys.exit(f"ERROR: {year} {variant}: {f} not found")
    a, b = pd.read_csv(fn), pd.read_csv(fo)
    a, b = a[a["year"] == year].reset_index(drop=True), b[b["year"] == year].reset_index(drop=True)
    if len(a) != 1 or len(b) != 1 or set(a.columns) != set(b.columns):
        sys.exit(f"ERROR: {year} {variant}: plural_breaks rows / columns differ ({len(a)} / {len(b)} rows, columns "
                 f"{sorted(set(a.columns) ^ set(b.columns))})")
    ok, dmax = True, 0.0
    for c in a.columns:
        x, z = a.at[0, c], b.at[0, c]
        if isinstance(x, str) or isinstance(z, str):
            same = str(x) == str(z)
        else:
            d = abs(float(x) - float(z))
            dmax = max(dmax, d) if c.startswith(("break_", "share_")) else dmax
            same = d <= BREAK_TOL
        if not same:
            log.error("  %d %s: plural_breaks %s = %s, the v5.6 test had %s", year, variant, c, x, z)
            ok = False
    return {"breaks": f"{a.at[0, 'breaks']} {int(a.at[0, 'classes'])}", "study_cells": int(a.at[0, "study_cells"]),
            "breaks_max_abs_diff": dmax, "breaks_ok": ok}


def feature_check(args) -> pd.DataFrame:
    rows = []
    for v in args.variants:
        for y in args.years:
            fn, f57, f56 = (era_dir(args, ver, y) / "county_features.csv"
                            for ver in (f"{V57}_{v}", V57, f"{V56}_{v}"))
            for f in (fn, f57, f56):
                if not f.exists():
                    sys.exit(f"ERROR: {y} {v}: {f} not found")
            cn, c7, c6 = (pd.read_csv(f).set_index("GISJOIN") for f in (fn, f57, f56))
            if set(cn.index) != set(c7.index):
                sys.exit(f"ERROR: {y} {v}: county-feature rows differ from v5.7 ({len(set(cn.index) ^ set(c7.index))} "
                         f"counties)")
            c7 = c7.loc[cn.index]
            if "plural" not in cn or "plural" in c7 or "plural" not in c6:
                sys.exit(f"ERROR: {y} {v}: expected plural in {fn} and {f56}, not in {f57}")
            if set(cn.columns) != set(c7.columns) | {"plural"}:
                sys.exit(f"ERROR: {y} {v}: county-feature columns are not v5.7's + plural: "
                         f"{sorted(set(cn.columns) ^ (set(c7.columns) | {'plural'}))}")
            for c in c7.columns:
                same = _num_equal(cn[c], c7[c], FEATURE_RTOL)
                if not same.all():
                    sys.exit(f"ERROR: {y} {v}: county feature {c} differs from v5.7 for {int((~same).sum())} counties "
                             f"(one change expected: + plural)")
            common = cn.index.intersection(c6.index)
            only_new, only_old = cn.index.difference(c6.index), c6.index.difference(cn.index)
            if len(only_new) or len(only_old):
                log.warning("  %d %s: county sets differ from the v5.6 test: %d only here %s, %d only there %s; the %d "
                            "common counties compared", y, v, len(only_new), list(only_new[:10]), len(only_old),
                            list(only_old[:10]), len(common))
            a, b = cn.loc[common, "plural"].to_numpy(float), c6.loc[common, "plural"].to_numpy(float)
            ok = np.isclose(a, b, rtol=PLURAL_RTOL, atol=1e-12)
            rel = np.abs(a - b) / np.maximum(np.abs(b), 1e-300)
            r = {"variant": v, "version": f"{V57}_{v}", "year": y, "feature_rows": len(cn),
                 "feature_cols_equal": len(c7.columns), "n_common_v56": len(common), "only_new": len(only_new),
                 "only_v56": len(only_old), "plural_max_rel_diff": float(rel.max()) if len(rel) else np.nan,
                 "plural_n_diff": int((~ok).sum())}
            r.update(breaks_check(args, v, y))
            r["status"] = "OK" if ok.all() and r["breaks_ok"] and len(common) else "DIFFERS"
            rows.append(r)
            log.info("  %d %-4s: %d counties, %d columns = v5.7 | plural = v5.6 test on %d common (max rel diff %.3g, "
                     "%d differ) | breaks %s (max |diff| %s) -> %s", y, v, len(cn), len(c7.columns), len(common),
                     r["plural_max_rel_diff"], r["plural_n_diff"], r["breaks"], r["breaks_max_abs_diff"], r["status"])
    return pd.DataFrame(rows)


def cmd_features(args) -> int:
    log.info("== county features of v5.7 + plural vs v5.7 (%s) and the v5.6 test's plural (%s_<variant>)", V57, V56)
    chk = feature_check(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    chk.to_csv(args.out_dir / "plural_v57_features_check.csv", index=False)
    bad = chk[chk["status"] != "OK"]
    if len(bad):
        log.error("FEATURES DIFFER: %s", bad[["variant", "year"]].to_dict("records"))
        return 1
    log.info("FEATURES OK: %d variants x %d years, county features = v5.7's + plural, plural and breaks = the v5.6 "
             "test's", len(args.variants), len(args.years))
    return 0


# ---------------------------------------------------------------- checks against earlier tables

def plural_county_view(cmp: pd.DataFrame, labels) -> pd.DataFrame:
    """County rows of v5.6 (+ plural) in the form of plural_comparison.csv: set test = its own TEST (test_kept_t070),
    CV from our test_all row, test_r2 = R2 of the kept TEST counties, plural ranks."""
    out = []
    for lab in labels:
        c = cmp[(cmp["level"] == "county") & (cmp["variant"] == lab)]
        k, a = c[c["set"] == "test_kept_t070"].set_index("year"), c[c["set"] == "test_all"].set_index("year")
        if not len(k):
            continue
        t = pd.DataFrame({"version": k["version"].to_numpy(), "year": k.index, "level": "county", "set": "test",
                          "n": k["n"].to_numpy(), "mdape": k["mdape"].to_numpy(), "mape": k["mape"].to_numpy(),
                          "mape_n": k["mape_n"].to_numpy(), "test_r2": k["r2"].to_numpy()})
        for src, dst in (("cv_rmse_train_kept_t070", "cv_rmse"), ("cv_r2_train_kept_t070", "cv_r2"),
                         ("plural_perm_rank", "plural_perm_rank"), ("plural_shap_rank", "plural_shap_rank")):
            t[dst] = a[src].reindex(k.index).to_numpy() if src in a else np.nan
        out.append(t)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def check_all(args, cmp: pd.DataFrame, cells: pd.DataFrame, vers: dict):
    y = args.years
    log.info("== checks: v5.6 / v5.7 / areal weighting = v54_nby_*; v5.6 (+ plural) = plural_comparison.csv (a "
             "difference stops the run)")
    vn.check_rows(cmp, args.nobuilt_dir / "v54_nby_comparison.csv", [V56, V57, pc.AREAL],
                  ["version", "year", "level", "set", "city"], vn.CMP_COLS, "comparison v5.6 / v5.7", y)
    old = [V56, *[vers[f"v56_{v}"] for v in args.variants]]
    tr = cmp[cmp["level"] == "tract"]
    vn.check_rows(tr, args.plural_dir / "plural_comparison.csv", old + [pc.AREAL], ["version", "year", "level", "set"],
                  ["n", "counties", "mdape", "mape", "mape_n"], "tracts v5.6 (+ plural)", y)
    cv = plural_county_view(cmp, ["v56", *[f"v56_{v}" for v in args.variants]])
    if len(cv):
        vn.check_rows(cv, args.plural_dir / "plural_comparison.csv", old, ["version", "year", "level", "set"],
                      ["n", "mdape", "mape", "mape_n", "test_r2", "cv_rmse", "cv_r2", "plural_perm_rank",
                       "plural_shap_rank"], "county v5.6 (+ plural) (its TEST = test_kept_t070)", y)
    if len(cells):
        vn.check_rows(cells, args.nobuilt_dir / "v54_nby_cells.csv", [V56, V57], ["version", "year"], vn.CELL_COLS,
                      "cells v5.6 / v5.7", y)


# ---------------------------------------------------------------- selection rule: county CV RMSE on v5.7's CV set

def cv_rule(args) -> pd.DataFrame:
    rows = []
    for v in args.variants:
        for y in args.years:
            dn, dr = era_dir(args, f"{V57}_{v}", y), era_dir(args, V57, y)
            if not (dn / "metrics.json").exists():
                log.warning("  CV rule %s %d: no %s; skipped", v, y, dn / "metrics.json")
                continue
            for f in (dn / "folds.csv", dr / "folds.csv", dr / "metrics.json"):
                if not f.exists():
                    sys.exit(f"ERROR: CV rule {v} {y}: {f} not found")
            a = pd.read_csv(dn / "folds.csv").sort_values("GISJOIN").reset_index(drop=True)
            b = pd.read_csv(dr / "folds.csv").sort_values("GISJOIN").reset_index(drop=True)
            if not a[["GISJOIN", "fold"]].equals(b[["GISJOIN", "fold"]]):
                sys.exit(f"ERROR: CV rule {v} {y}: CV counties / folds differ from {V57}; the CV RMSE is not comparable")
            mn, mr = json.loads((dn / "metrics.json").read_text()), json.loads((dr / "metrics.json").read_text())
            n, r = mn["cv_rmse_mean"], mr["cv_rmse_mean"]
            rows.append({"variant": f"v57_{v}", "version": f"{V57}_{v}", "year": y, "cv_counties": len(a),
                         "same_cv_set": True, "cv_rmse_v57": r, "cv_rmse_variant": n, "d_cv_rmse": n - r,
                         "rel_d_cv_rmse": (n - r) / r, "cv_r2_v57": mr.get("cv_r2_mean"),
                         "cv_r2_variant": mn.get("cv_r2_mean"), "lower": "variant" if n < r else "v57"})
    t = pd.DataFrame(rows)
    if len(t):
        g = t.groupby("variant")
        t["years"] = t["variant"].map(g["year"].nunique())
        t["years_lower"] = t["variant"].map(g["lower"].apply(lambda s: int((s == "variant").sum())))
        t["mean_d_cv_rmse"] = t["variant"].map(g["d_cv_rmse"].mean())
        t["mean_rel_d_cv_rmse"] = t["variant"].map(g["rel_d_cv_rmse"].mean())
    return t


# ---------------------------------------------------------------- compare

def cells_part(args, vers: dict) -> pd.DataFrame:
    out = args.out_dir / "plural_v57_cells.csv"
    if args.dasym_root and args.cutout_root:
        log.info("== cells: people on BUI = 0 cells and on NobuiltYear > 0 among them (nobuilt_cells.csv definition)")
        cells = nc.cells_table(args, vers)
        if len(cells):
            cells["variant"] = cells["variant"].map(label)
        return cells
    if out.exists():
        log.info("== cells: read again from %s", out)
        return pd.read_csv(out)
    log.warning("== cells: no rasters given and no %s; no cell rows", out)
    return pd.DataFrame()


def own_base(var: str) -> str:
    return "v57" if var.startswith("v57") else "v56" if var.startswith("v56") else ""


def cmd_compare(args) -> int:
    if not args.exclusions.exists():
        sys.exit(f"ERROR: {args.exclusions} not found (src/grid/uncertainty_filter.py)")
    excl = set(pd.read_csv(args.exclusions)["GISJOIN"])
    split_test = None
    if args.split.exists():
        sp = pd.read_csv(args.split)
        split_test = set(sp.loc[sp["part"] == "test", "GISJOIN"]) if "part" in sp else None
    vers = versions(args.variants)
    log.info("versions %s | years %s | t070 exclusion set %d counties", {label(k): v for k, v in vers.items()},
             args.years, len(excl))
    log.info("reporting rule: county metrics on ALL TEST counties (test_all); kept / excluded t070 only labelled")
    log.info("selection rule (fixed 2026-11-19 before the results): per variant the years with a county CV RMSE below "
             "v5.7's (same CV counties / folds) and the mean change; not by tracts; the user decides")
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    cells = cells_part(args, vers)
    rows = []
    for y in args.years:
        rows += vc.county_rows(args, y, vers, excl, split_test, rank_features=RANK_FEATURES)
        tr = pc.tract_rows(args, y, vers, excl)
        for r in tr:
            r["variant"] = label(r["variant"])
        rows += tr
    if len(cells):
        rows += nc.cell_rows(cells)
    cmp = pd.DataFrame(rows)
    if cmp.empty or not cmp["level"].isin(["tract", "county"]).any():
        sys.exit("ERROR: no tract / county result files found for any version / year")
    cmp["city"] = np.nan  # the column of v54_nby_comparison.csv (no city rows here)
    cmp.insert(cmp.columns.get_loc("set") + 1, "city", cmp.pop("city"))
    key = ["year", "level", "set"]
    base = cmp[["variant", *key, "mdape"]]
    ref = base[base["variant"] == REF].drop(columns="variant").rename(columns={"mdape": "ref_mdape"})
    own = base[base["variant"].isin(["v57", "v56"])].rename(columns={"variant": "own", "mdape": "own_mdape"})
    cmp["own"] = cmp["variant"].map(own_base)
    cmp = cmp.merge(ref, on=key, how="left").merge(own, on=["own", *key], how="left")
    cmp.insert(cmp.columns.get_loc("mape_n") + 1, "d_mdape", cmp["mdape"] - cmp.pop("ref_mdape"))
    cmp.insert(cmp.columns.get_loc("d_mdape") + 1, "d_mdape_own", cmp["mdape"] - cmp.pop("own_mdape"))
    cmp = cmp.drop(columns="own")
    new = [f"v57_{v}" for v in args.variants]
    if not cmp["variant"].isin(new).any():
        log.warning("no rows of v5.7 + plural yet (not run?): the table holds the other versions only")

    check_all(args, cmp, cells, vers)  # stops before anything is written
    ranks = bc.rank_table(args.results_root / "dasymetric" / args.name, {label(k): v for k, v in vers.items()},
                          args.years)
    rule = cv_rule(args)
    cmp.to_csv(out / "plural_v57_comparison.csv", index=False)
    if len(cells):
        cells.to_csv(out / "plural_v57_cells.csv", index=False)
    ranks.to_csv(out / "plural_v57_feature_ranks.csv", index=False)
    rule.to_csv(out / "plural_v57_cv_rule.csv", index=False)

    cols = order(args.variants)

    def piv(t, values, index):
        tab = t.pivot_table(index=index, columns="variant", values=values, sort=False)
        return tab.reindex(columns=[c for c in cols if c in tab.columns])

    with pd.option_context("display.width", 250, "display.max_rows", 500, "display.max_columns", 40):
        c = cmp[cmp["level"] == "county"]
        for s, what in (("test_all", "ALL TEST counties (main table; same set in every version)"),
                        ("test_kept_t070", "TEST counties KEPT by t070 (labelled, not the main number)"),
                        ("test_excluded_t070", "TEST counties EXCLUDED by t070 (labelled)")):
            cs = c[c["set"] == s]
            if len(cs):
                log.info("SUMMARY county %s, before allocation: R2 of log density / MdAPE (%%) / MAPE (%%):\n%s\n%s\n%s",
                         what, piv(cs, "r2", "year").round(3).to_string(), piv(cs, "mdape", "year").round(2).to_string(),
                         piv(cs, "mape", "year").round(2).to_string())
        ca = c[c["set"] == "test_all"]
        cv = [k for k in ("variant", "year", "cv_counties", "cv_rmse_train_all", "cv_r2_train_all",
                          "cv_rmse_train_kept_t070", "cv_r2_train_kept_t070", "plural_perm_rank", "plural_shap_rank",
                          "nby_perm_rank", "nby_shap_rank") if k in ca]
        log.info("SUMMARY county CV (own train counties; columns name the CV set: v5.7 and its variants share one, v5.6 "
                 "and its variants another) + ranks of plural / nby (1 = most important):\n%s",
                 ca[cv].round(4).to_string(index=False))
        tr = cmp[cmp["level"] == "tract"]
        log.info("SUMMARY tract MdAPE (%%) by set, year and variant (areal_weighting = area-proportional):\n%s",
                 piv(tr, "mdape", ["set", "year"]).round(2).to_string())
        log.info("SUMMARY tract MdAPE change vs the own base (v57_* - v5.7, v56_* - v5.6; points):\n%s",
                 piv(tr[tr["variant"] != pc.AREAL], "d_mdape_own", ["set", "year"]).round(2).to_string())
        log.info("SUMMARY tract MAPE (%%, tracts >= %g people):\n%s", args.mape_min,
                 piv(tr, "mape", ["set", "year"]).round(2).to_string())
        ce = cmp[cmp["level"] == "cells"]
        if len(ce):
            log.info("SUMMARY people on cells (share_bui0 = on BUI = 0 cells / all; share_nb_of_bui0 = of those, on "
                     "NobuiltYear > 0 cells; share_bui0_nb = BUI = 0 and NobuiltYear > 0 / all):\n%s",
                     piv(ce, "share", ["set", "year"]).round(4).to_string())
        if len(ranks):
            rk = ranks[ranks["feature"].isin(RANK_FEATURES)]
            if len(rk):
                log.info("SUMMARY rank of plural / nby (permutation / SHAP):\n%s",
                         rk.pivot_table(index=["feature", "year"], columns="variant",
                                        values=["perm_rank", "shap_rank"]).reindex(
                             columns=[c for c in cols if c in set(rk["variant"])], level=1).to_string())
        if len(rule):
            log.info("SUMMARY selection rule: county CV RMSE on v5.7's CV counties (same folds checked):\n%s",
                     rule.drop(columns=["version", "same_cv_set"]).round(4).to_string(index=False))
            s = rule.drop_duplicates("variant").set_index("variant")
            for v, r in s.iterrows():
                log.info("RULE: %s has the lower county CV RMSE in %d of %d years (mean change %+.4f, %+.1f %%)", v,
                         r["years_lower"], r["years"], r["mean_d_cv_rmse"], 100 * r["mean_rel_d_cv_rmse"])
            log.info("RULE: the user decides (tracts reported, not used for the choice)")
    log.info("wrote %s", out)
    log.info("DONE")
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    return {"config": cmd_config, "features": cmd_features, "compare": cmd_compare}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
