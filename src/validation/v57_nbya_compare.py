"""v5.7 with nby_age instead of nby (Stefan 2026-11-17 item 1; request 2026-11-18, docs/handoff/v57_nbya_request.md;
docs/conus_plan.md "v5.7 with nby_age instead of nby"). One change against v5.7: in every era nby (NobuiltYear, the same
in every year) -> nby_age (NobuiltYear x f_c(year), f_c = county BUPR_year / BUPR_2015 clipped to 0-1, 1 where
BUPR_2015 = 0; common.nby_age_setup). Versions on the same years, tracts, TEST counties and cells:
  v54       Dasy_CONUS_RF_v3_all        (v5.4, no filter)
  v56       Dasy_CONUS_RF_v3_u070       (v5.6 = v5.4 + the t070 filter; key "base" of nobuilt / plural_compare)
  v57       Dasy_CONUS_RF_v3_all_nby    (v5.7 = v5.4 + nby, no filter; the base)
  v57_nbya  Dasy_CONUS_RF_v3_all_nbya   (v5.7 with nby -> nby_age; the new version)
  v56_nbya  Dasy_CONUS_RF_v3_u070_nbya  (v5.6 + nby_age of the NobuiltYear test; reference column)

Three subcommands:
  config   the new config = v5.7's era of each year with nby -> nby_age (same position), every other setting as v5.7,
           the `nby_age:` block as conus_rf_v3_u070_nbya.yaml, compare_with v5.7, no exclude_counties; prints
           CONFIG OK or the differences (exit 1). Login node pre-check of sbatch/submit_conus.sh v57nbya.
  factors  after the features job, before train (the chain stops here on a difference): per year the new
           <era>/nby_age_factor.csv (results copy) against Dasy_CONUS_RF_v3_u070_nbya's: factors of the common
           counties equal (|diff| <= 1e-12; a different county set is logged, a different factor stops); the new
           county_features.csv against v5.7's: same counties, every column but nby / nby_age equal, nby_age = nby x
           factor (rtol 1e-6) -> v57_nbya_factor_check.csv; + the factor summary below. FACTORS OK or exit 1.
  compare  the comparison (after validate). Reporting rule (open_items): county metrics on ALL TEST counties; kept /
           excluded t070 only labelled beside them.
           - county, before allocation (v54_nby_compare.county_rows): test_all / test_kept_t070 / test_excluded_t070
             MdAPE, MAPE, R2 of log density; CV RMSE / R2 in columns named by the CV county set; ranks of nby and
             nby_age (permutation / mean |SHAP|)
           - tracts (plural_compare.tract_rows): all, kept / excluded t070, no_gap / gap (v5.6's gap counties), four
             observed density classes, + areal weighting; d_mdape = MdAPE - v5.7's
           - cells (--dasym-root + --cutout-root; nobuilt_compare.cell_sums): people on BUI = 0 cells and of those on
             NobuiltYear > 0 cells; city gap blocks (+ --ext-config + --data-root; nobuilt_compare.city_table, blocks
             inside v5.6's mask, a differing mask logged): Boston / Denver / Chicago, 1980 / 2010. Without the raster
             flags the CSVs of an earlier run in --out-dir are read again
           - factor summary per version and year: counties, f_c quantiles 10 / 50 / 90 %, mean, < 0.05 / < 0.10,
             clipped to 1, BUPR_2015 = 0, and the share of v5.7's undated records kept (sum nby x area x f_c / sum
             nby x area over the county-feature rows)
           - selection rule (fixed before the results): county CV RMSE only, on v5.7's CV county set (folds.csv equal,
             else stop); the user decides; tracts are not used for tuning -> v57_nbya_cv_rule.csv
           Checks, a difference stops the run before writing: v5.4 / v5.6 / v5.7 rows = v54_nby_comparison.csv (county,
           tract, cells, city_gap) and v54_nby_cells.csv / v54_nby_city_gaps.csv; v5.6 + nby_age rows =
           nobuilt_comparison.csv (tracts; county: its TEST = our test_kept_t070, CV, ranks of nby_age),
           nobuilt_cells.csv, nobuilt_city_gaps.csv.

Writes to --out-dir (results/validation/conus/nobuilt/; nobuilt_* / v54_nby_* are read only):
  v57_nbya_comparison.csv  as v54_nby_comparison.csv (+ nby_age ranks), d_mdape vs v5.7
  v57_nbya_cells.csv, v57_nbya_city_gaps.csv, v57_nbya_feature_ranks.csv, v57_nbya_factor_summary.csv,
  v57_nbya_factor_check.csv (factors), v57_nbya_cv_rule.csv
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
import nobuilt_compare as nc  # noqa: E402  (cells, city gap blocks)
import plural_compare as pc  # noqa: E402  (tract rows)
import v54_nby_compare as vc  # noqa: E402  (county rows on all TEST counties)

log = logging.getLogger("v57_nbya_compare")

YEARS = [1910, 1940, 1960, 1980, 2010]
VERSIONS = {"base": "Dasy_CONUS_RF_v3_u070", "v54": "Dasy_CONUS_RF_v3_all", "v57": "Dasy_CONUS_RF_v3_all_nby",
            "v57_nbya": "Dasy_CONUS_RF_v3_all_nbya", "v56_nbya": "Dasy_CONUS_RF_v3_u070_nbya"}
NEW, REF, OLD = "v57_nbya", "v57", "v56_nbya"
ORDER = ["v54", "v56", "v57", "v57_nbya", "v56_nbya", pc.AREAL]
RANK_FEATURES = ("nby", "nby_age")
CONFIGS = {"new": Path("configs/conus_rf_v3_all_nbya.yaml"), "v57": Path("configs/conus_rf_v3_all_nby.yaml"),
           "old": Path("configs/conus_rf_v3_u070_nbya.yaml")}
SAME_AS_V57 = ("study_area", "water_mask", "split", "exclude_counties", "use_status", "train_status", "unusable",
               "block_rows", "maps", "correlation_threshold", "model", "search", "permutation", "models")
FACTOR_TOL = 1e-12  # = common.FACTOR_TOL (predict's check)
FEATURE_RTOL = 1e-6  # county nby_age = f_c x county nby (mean of products vs product of the mean)
CV_NOTE = vc.CV_NOTE


def label(var: str) -> str:
    return vc.label(var)


def add_common(p):
    p.add_argument("--years", type=int, nargs="+", default=YEARS)
    p.add_argument("--name", default="conus")
    p.add_argument("--results-root", type=Path, default=Path("results"))
    p.add_argument("--out-dir", type=Path, default=Path("results/validation/conus/nobuilt"))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("config", help="new config = v5.7 with nby -> nby_age")
    for k, v in CONFIGS.items():
        c.add_argument(f"--{k}-config", type=Path, default=v)
    c.add_argument("--years", type=int, nargs="+", default=YEARS)
    f = sub.add_parser("factors", help="nby_age factors = the NobuiltYear test's; features = v5.7's with nby -> nby_age")
    add_common(f)
    m = sub.add_parser("compare", help="the comparison")
    add_common(m)
    m.add_argument("--city-years", type=int, nargs="+", default=nc.CITY_YEARS)
    m.add_argument("--exclusions", type=Path, default=Path("results/hisdac_uncertainty/excluded_counties_t070.csv"))
    m.add_argument("--split", type=Path, default=Path("configs/conus_split.csv"))
    m.add_argument("--mape-min", type=float, default=10)
    m.add_argument("--nobuilt-dir", type=Path, default=Path("results/validation/conus/nobuilt"),
                   help="nobuilt_* and v54_nby_* files (checked rows)")
    m.add_argument("--dasym-root", type=Path, help="<root>/<name>/<version>/predictions/pop_{YEAR}.tif (cells, city)")
    m.add_argument("--cutout-root", type=Path, help="<root>/<name>/layers/{BUI,NOBUILT}/ (cells)")
    m.add_argument("--ext-config", type=Path, help="configs/external_grids.yaml (city)")
    m.add_argument("--data-root", type=Path, help="$DATA_ROOT/raw/external (city: GHS-POP)")
    m.add_argument("--gap-csv", type=Path, default=nc.GAP_CSV, help="v5.6's gap blocks of the meeting maps")
    a = p.parse_args(argv)
    a.base = VERSIONS["base"]  # for nobuilt_compare.city_table / plural_compare.tract_rows
    return a


# ---------------------------------------------------------------- config

def config_problems(new: dict, v57: dict, old: dict, years) -> list[str]:
    """Differences of the new config from 'v5.7 with nby -> nby_age' (empty = OK)."""
    bad = []
    if new["version"] != VERSIONS[NEW]:
        bad.append(f"version {new['version']} != {VERSIONS[NEW]}")
    if new.get("compare_with") != v57["version"]:
        bad.append(f"compare_with {new.get('compare_with')} != {v57['version']}")
    if sorted(new["years"]) != sorted(years):
        bad.append(f"years {new['years']} != {sorted(years)}")
    if new.get("nby_age") != old.get("nby_age") or new.get("nby_age") is None:
        bad.append(f"nby_age block {new.get('nby_age')} != {old.get('nby_age')} (conus_rf_v3_u070_nbya.yaml)")
    if new.get("exclude_counties") is not None:
        bad.append("exclude_counties given (v5.7 has none)")
    for k in SAME_AS_V57:
        if new.get(k) != v57.get(k):
            bad.append(f"{k}: {new.get(k)} != v5.7 {v57.get(k)}")
    swap = lambda fs: ["nby_age" if f == "nby" else f for f in fs]  # noqa: E731
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
        if "nby" not in b["features"] or n["features"] != swap(b["features"]):
            bad.append(f"{e}: features {n['features']} != v5.7 {b['features']} with nby -> nby_age")
        if e in old["eras"] and n["features"] != old["eras"][e]["features"]:
            bad.append(f"{e}: features {n['features']} != v5.6 + nby_age {old['eras'][e]['features']}")
    fg = {g: swap(fs) for g, fs in (v57.get("feature_groups") or {}).items()}
    if new.get("feature_groups") != fg:
        bad.append(f"feature_groups {new.get('feature_groups')} != v5.7's with nby -> nby_age {fg}")
    return bad


def cmd_config(args) -> int:
    import common as dcommon
    cfg = {k: dcommon.load_config(getattr(args, f"{k}_config")) for k in CONFIGS}
    bad = config_problems(cfg["new"], cfg["v57"], cfg["old"], args.years)
    for b in bad:
        print(f"CONFIG DIFFERS: {b}")
    if bad:
        print(f"ERROR: {args.new_config} is not v5.7 with nby -> nby_age ({len(bad)} differences)")
        return 1
    print(f"CONFIG OK: {args.new_config} = {args.v57_config} eras {sorted(cfg['new']['eras'])} with nby -> nby_age, "
          f"nby_age block = {args.old_config}, every other setting as v5.7")
    return 0


# ---------------------------------------------------------------- factors

def era_dir(args, var: str, year: int) -> Path:
    return args.results_root / "dasymetric" / args.name / VERSIONS[var] / f"Y{year}"


def read_factors(args, var: str, year: int) -> pd.DataFrame | None:
    p = era_dir(args, var, year) / "nby_age_factor.csv"
    if not p.exists():
        return None
    t = pd.read_csv(p)
    return t[t["year"] == year]


def factor_check(args) -> pd.DataFrame:
    """New factors = the NobuiltYear test's (common counties); new county features = v5.7's with nby -> nby_age."""
    rows = []
    for y in args.years:
        new, old = read_factors(args, NEW, y), read_factors(args, OLD, y)
        for var, t in ((NEW, new), (OLD, old)):
            if t is None:
                sys.exit(f"ERROR: {y}: {era_dir(args, var, y) / 'nby_age_factor.csv'} not found")
        a, b = new.set_index("GISJOIN"), old.set_index("GISJOIN")
        common = a.index.intersection(b.index)
        if not len(common):
            sys.exit(f"ERROR: {y}: no common county in the nby_age factors of {VERSIONS[NEW]} and {VERSIONS[OLD]}")
        d = (a.loc[common, "factor"] - b.loc[common, "factor"]).abs()
        n_diff = int((d > FACTOR_TOL).sum())
        only_new, only_old = a.index.difference(b.index), b.index.difference(a.index)
        if len(only_new) or len(only_old):
            log.warning("  %d: county sets differ: %d only in the new factors %s, %d only in the old %s; the %d common "
                        "counties compared", y, len(only_new), list(only_new[:10]), len(only_old), list(only_old[:10]),
                        len(common))
        bcol = f"bupr_{y}"
        db = float((a.loc[common, bcol] - b.loc[common, bcol]).abs().max()) if bcol in a and bcol in b else np.nan
        r = {"year": y, "n_new": len(a), "n_old": len(b), "n_common": len(common), "only_new": len(only_new),
             "only_old": len(only_old), "max_abs_diff_factor": float(d.max()), "n_diff_factor": n_diff,
             "max_abs_diff_bupr": db}
        # county features: v5.7's columns, nby -> nby_age = nby x factor
        fn, fo = era_dir(args, NEW, y) / "county_features.csv", era_dir(args, REF, y) / "county_features.csv"
        for f in (fn, fo):
            if not f.exists():
                sys.exit(f"ERROR: {y}: {f} not found")
        cn, co = pd.read_csv(fn).set_index("GISJOIN"), pd.read_csv(fo).set_index("GISJOIN")
        if set(cn.index) != set(co.index):
            sys.exit(f"ERROR: {y}: county-feature rows of {VERSIONS[NEW]} and {VERSIONS[REF]} differ "
                     f"({len(set(cn.index) ^ set(co.index))} counties)")
        co = co.loc[cn.index]
        if "nby_age" not in cn or "nby" not in co or "nby" in cn:
            sys.exit(f"ERROR: {y}: expected nby_age (not nby) in {fn} and nby in {fo}")
        other = [c for c in co.columns if c != "nby"]
        if set(other) != set(c for c in cn.columns if c != "nby_age"):
            sys.exit(f"ERROR: {y}: county-feature columns differ: {sorted(set(other) ^ set(cn.columns) - {'nby_age'})}")
        for c in other:
            x, z = cn[c], co[c]
            if pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(z):
                same = np.isclose(x.to_numpy(float), z.to_numpy(float), rtol=1e-12, atol=0, equal_nan=True)
            else:
                same = (x.astype(str) == z.astype(str)).to_numpy()
            if not same.all():
                sys.exit(f"ERROR: {y}: county feature {c} differs from v5.7 for {int((~same).sum())} counties "
                         f"(one change expected: nby -> nby_age)")
        fac = a["factor"].reindex(cn.index)
        if fac.isna().any():
            sys.exit(f"ERROR: {y}: {int(fac.isna().sum())} feature counties without an nby_age factor")
        want = co["nby"].to_numpy(float) * fac.to_numpy(float)
        got = cn["nby_age"].to_numpy(float)
        ok = np.isclose(got, want, rtol=FEATURE_RTOL, atol=1e-12)
        rel = np.abs(got - want) / np.maximum(np.abs(want), 1e-300)
        r.update({"feature_rows": len(cn), "feature_cols_equal": len(other), "nby_age_max_rel_diff": float(rel.max()),
                  "nby_age_n_diff": int((~ok).sum())})
        r["status"] = "OK" if n_diff == 0 and ok.all() else "DIFFERS"
        rows.append(r)
        log.info("  %d: factors %d new / %d old / %d common, max |diff| %.3g, %d differ | features %d rows, %d columns "
                 "= v5.7, nby_age = nby x factor (max rel diff %.3g, %d differ) -> %s", y, len(a), len(b), len(common),
                 r["max_abs_diff_factor"], n_diff, len(cn), len(other), r["nby_age_max_rel_diff"], r["nby_age_n_diff"],
                 r["status"])
    return pd.DataFrame(rows)


def factor_summary(args, variants=(NEW, OLD)) -> pd.DataFrame:
    """Distribution of f_c per version and year (+ the share of v5.7's undated records kept by the factors)."""
    rows = []
    for var in variants:
        for y in args.years:
            t = read_factors(args, var, y)
            if t is None:
                log.info("  factor summary: no nby_age_factor.csv of %s %d", VERSIONS[var], y)
                continue
            f = t["factor"].to_numpy(float)
            q10, q50, q90 = np.quantile(f, [0.1, 0.5, 0.9])
            r = {"version": VERSIONS[var], "variant": var, "year": y, "counties": len(t), "factor_p10": q10,
                 "factor_median": q50, "factor_p90": q90, "factor_mean": float(f.mean()),
                 "n_lt_0_05": int((f < 0.05).sum()), "n_lt_0_10": int((f < 0.10).sum()),
                 "n_clipped_1": int((t["rule"] == "clipped_1").sum()),
                 "n_bupr_2015_zero": int((t["rule"] == "bupr_2015_zero").sum())}
            cf = era_dir(args, REF, y) / "county_features.csv"  # v5.7's county nby (the undated records it uses)
            if cf.exists():
                c = pd.read_csv(cf, usecols=["GISJOIN", "nby", "area_km2"]).merge(t[["GISJOIN", "factor"]],
                                                                                    on="GISJOIN", how="inner")
                w = c["nby"].to_numpy(float) * c["area_km2"].to_numpy(float)
                r["feature_counties"] = len(c)
                r["nby_kept_share"] = float((w * c["factor"]).sum() / w.sum()) if w.sum() > 0 else np.nan
            rows.append(r)
    return pd.DataFrame(rows)


def log_factor_summary(fs: pd.DataFrame):
    if len(fs):
        with pd.option_context("display.width", 220, "display.max_columns", 30):
            log.info("SUMMARY nby_age factor f_c per year (county quantiles; n_lt_* = counties below; nby_kept_share = "
                     "sum nby x area x f_c / sum nby x area over v5.7's county-feature rows):\n%s",
                     fs.drop(columns="version").round(4).to_string(index=False))


def cmd_factors(args) -> int:
    log.info("== nby_age factors of %s vs %s; county features vs %s", VERSIONS[NEW], VERSIONS[OLD], VERSIONS[REF])
    chk = factor_check(args)
    fs = factor_summary(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    chk.to_csv(args.out_dir / "v57_nbya_factor_check.csv", index=False)
    fs.to_csv(args.out_dir / "v57_nbya_factor_summary.csv", index=False)
    log_factor_summary(fs)
    if (chk["status"] != "OK").any():
        log.error("FACTORS DIFFER: %s", chk.loc[chk["status"] != "OK", "year"].tolist())
        return 1
    log.info("FACTORS OK: %d years, factors = %s on the common counties, county features = v5.7 with nby -> nby_age",
             len(chk), VERSIONS[OLD])
    return 0


# ---------------------------------------------------------------- checks against earlier tables

def _keyed(t: pd.DataFrame, keys) -> pd.DataFrame:
    t = t.copy()
    for k in keys:
        if k == "year":
            t[k] = t[k].astype(int)
        else:
            t[k] = t[k].astype(object).where(t[k].notna(), "").astype(str)
    return t


def check_rows(new: pd.DataFrame, path: Path, variants, keys, cols, what: str, years) -> int:
    """The rows of `variants` (labels) in `new` and in the earlier table `path` (same version names, the given years
    and, with a level key, the levels of that table) must be the same rows with the same `cols` (1e-9 relative);
    stops on a missing / extra row or a difference."""
    if not path.exists():
        sys.exit(f"ERROR: {what}: {path} not found (rows of {list(variants)} must be checked against it)")
    vs = [VERSIONS.get(v, v) for v in variants]
    old = pd.read_csv(path)
    old = old[old["version"].isin(vs) & old["year"].isin(years)]
    sub = new[new["version"].isin(vs) & new["year"].isin(years)]
    if "level" in keys:  # the levels this run has (cells / city only with the raster flags or an earlier run)
        lv = set(sub["level"]) & set(old["level"])
        if not lv:
            sys.exit(f"ERROR: {what}: no level of {sorted(set(sub['level']))} in {path}")
        sub, old = sub[sub["level"].isin(lv)], old[old["level"].isin(lv)]
        log.info("  %s: levels %s", what, sorted(lv))
    if not len(old):
        sys.exit(f"ERROR: {what}: no rows of {vs} in {path}")
    o, s = _keyed(old, keys), _keyed(sub, keys)
    if o.duplicated(keys).any() or s.duplicated(keys).any():
        sys.exit(f"ERROR: {what}: duplicated keys {keys}")
    m = s.merge(o[keys + [c for c in cols if c in o]], on=keys, how="outer", suffixes=("", "__old"), indicator=True)
    lost = m[m["_merge"] != "both"]
    if len(lost):
        sys.exit(f"ERROR: {what}: {len(lost)} rows only on one side of {path}: "
                 f"{lost[keys + ['_merge']].head(10).to_dict('records')}")
    used = []
    for c in cols:
        if c not in s or c + "__old" not in m:
            continue
        a = pd.to_numeric(m[c], errors="coerce").to_numpy(float)
        b = pd.to_numeric(m[c + "__old"], errors="coerce").to_numpy(float)
        bad = ~np.isclose(a, b, rtol=1e-9, atol=1e-12, equal_nan=True)
        if bad.any():
            sys.exit(f"ERROR: {what}: {c} differs from {path} for {m.loc[bad, keys].head(10).to_dict('records')}: "
                     f"{a[bad][:10].tolist()} vs {b[bad][:10].tolist()}")
        used.append(c)
    log.info("  MATCH %s: %d rows of %s (%s)", path, len(m), ", ".join(label(v) for v in variants), ", ".join(used))
    return len(m)


CMP_COLS = ["n", "counties", "mdape", "mape", "mape_n", "r2", "cv_counties", "cv_rmse_train_all", "cv_r2_train_all",
            "cv_rmse_train_kept_t070", "cv_r2_train_kept_t070", "nby_perm_rank", "nby_shap_rank", "nby_perm",
            "nby_shap", "share"]
CELL_COLS = ["cells", "cells_bui0", "cells_bui0_nb", "pop", "pop_bui0", "pop_bui0_nb", "pop_nb"]
CITY_KEYS = ["city", "year", "version", "set"]


def nobuilt_county_view(cmp: pd.DataFrame) -> pd.DataFrame:
    """County rows of v5.6 + nby_age in the form of nobuilt_comparison.csv: set test = its own TEST (test_kept_t070),
    CV from our test_all row, test_r2 = R2 of the kept TEST counties."""
    c = cmp[(cmp["level"] == "county") & (cmp["variant"] == OLD)]
    k = c[c["set"] == "test_kept_t070"].set_index("year")
    a = c[c["set"] == "test_all"].set_index("year")
    out = pd.DataFrame({"version": VERSIONS[OLD], "year": k.index, "level": "county", "set": "test", "city": "",
                        "n": k["n"].to_numpy(), "mdape": k["mdape"].to_numpy(), "mape": k["mape"].to_numpy(),
                        "test_r2": k["r2"].to_numpy()})
    for src, dst in (("cv_rmse_train_kept_t070", "cv_rmse"), ("cv_r2_train_kept_t070", "cv_r2"),
                     ("nby_age_perm_rank", "nby_age_perm_rank"), ("nby_age_shap_rank", "nby_age_shap_rank")):
        out[dst] = a[src].reindex(k.index).to_numpy() if src in a else np.nan
    return out


def check_all(args, cmp: pd.DataFrame, cells: pd.DataFrame, city: pd.DataFrame):
    nb = args.nobuilt_dir
    y = args.years
    log.info("== checks: v5.4 / v5.6 / v5.7 = v54_nby_*; v5.6 + nby_age = nobuilt_* (a difference stops the run)")
    prev = ["v54", "base", "v57", pc.AREAL]
    check_rows(cmp, nb / "v54_nby_comparison.csv", prev, ["version", "year", "level", "set", "city"], CMP_COLS,
               "comparison", y)
    tr = cmp[(cmp["level"] == "tract") & (cmp["variant"] == OLD)]
    check_rows(tr, nb / "nobuilt_comparison.csv", [OLD], ["version", "year", "level", "set", "city"],
               ["n", "counties", "mdape", "mape", "mape_n"], "tracts v5.6 + nby_age", y)
    cv = nobuilt_county_view(cmp)
    if len(cv):
        check_rows(cv, nb / "nobuilt_comparison.csv", [OLD], ["version", "year", "level", "set", "city"],
                   ["n", "mdape", "mape", "test_r2", "cv_rmse", "cv_r2", "nby_age_perm_rank", "nby_age_shap_rank"],
                   "county v5.6 + nby_age (its TEST = test_kept_t070)", y)
    if len(cells):
        check_rows(cells, nb / "v54_nby_cells.csv", ["v54", "base", "v57"], ["version", "year"], CELL_COLS, "cells", y)
        check_rows(cells, nb / "nobuilt_cells.csv", ["base", OLD], ["version", "year"], CELL_COLS,
                   "cells v5.6 + nby_age", y)
    if len(city):
        pop = [c for c in city.columns if c.startswith("pop_")]
        check_rows(city, nb / "v54_nby_city_gaps.csv", ["v54", "base", "v57"], CITY_KEYS,
                   ["n_blocks", *pop, "ratio", "mask_diff_cells"], "city gap blocks", y)
        check_rows(city, nb / "nobuilt_city_gaps.csv", ["base", OLD], CITY_KEYS, ["n_blocks", *pop, "ratio"],
                   "city gap blocks v5.6 + nby_age", y)


# ---------------------------------------------------------------- selection rule: county CV RMSE on v5.7's CV set

def cv_rule(args) -> pd.DataFrame:
    rows = []
    for y in args.years:
        dn, dr = era_dir(args, NEW, y), era_dir(args, REF, y)
        if not (dn / "metrics.json").exists():
            log.warning("  CV rule %d: no %s; skipped", y, dn / "metrics.json")
            continue
        fn, fr = dn / "folds.csv", dr / "folds.csv"
        for f in (fn, fr, dr / "metrics.json"):
            if not f.exists():
                sys.exit(f"ERROR: CV rule {y}: {f} not found")
        a = pd.read_csv(fn).sort_values("GISJOIN").reset_index(drop=True)
        b = pd.read_csv(fr).sort_values("GISJOIN").reset_index(drop=True)
        if not a[["GISJOIN", "fold"]].equals(b[["GISJOIN", "fold"]]):
            sys.exit(f"ERROR: CV rule {y}: CV counties / folds of {VERSIONS[NEW]} differ from {VERSIONS[REF]}; the CV "
                     f"RMSE is not comparable")
        mn, mr = json.loads((dn / "metrics.json").read_text()), json.loads((dr / "metrics.json").read_text())
        n, r = mn["cv_rmse_mean"], mr["cv_rmse_mean"]
        rows.append({"year": y, "cv_counties": len(a), "same_cv_set": True, "cv_rmse_v57": r, "cv_rmse_v57_nbya": n,
                     "d_cv_rmse": n - r, "rel_d_cv_rmse": (n - r) / r, "cv_r2_v57": mr.get("cv_r2_mean"),
                     "cv_r2_v57_nbya": mn.get("cv_r2_mean"), "lower": "v57_nbya" if n < r else "v57"})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- compare

def cells_part(args) -> pd.DataFrame:
    out = args.out_dir / "v57_nbya_cells.csv"
    if args.dasym_root and args.cutout_root:
        log.info("== cells: people on BUI = 0 cells and on NobuiltYear > 0 among them (nobuilt_cells.csv definition)")
        cells = nc.cells_table(args, VERSIONS)
        cells["variant"] = cells["variant"].map(label)
        return cells
    if out.exists():
        log.info("== cells: read again from %s", out)
        return pd.read_csv(out)
    log.warning("== cells: no rasters given and no %s; no cell rows", out)
    return pd.DataFrame()


def city_part(args) -> pd.DataFrame:
    out = args.out_dir / "v57_nbya_city_gaps.csv"
    if args.dasym_root and args.ext_config and args.data_root:
        log.info("== city gap blocks (rule of external_city_meeting.py, blocks inside v5.6's mask)")
        city = nc.city_table(args, VERSIONS, strict_mask=False)
        if len(city):
            city["variant"] = city["variant"].map(label)
        return city
    if out.exists():
        log.info("== city: read again from %s", out)
        return pd.read_csv(out)
    log.warning("== city: no rasters / config given and no %s; no city rows", out)
    return pd.DataFrame()


def cmd_compare(args) -> int:
    if not args.exclusions.exists():
        sys.exit(f"ERROR: {args.exclusions} not found (src/grid/uncertainty_filter.py)")
    excl = set(pd.read_csv(args.exclusions)["GISJOIN"])
    split_test = None
    if args.split.exists():
        sp = pd.read_csv(args.split)
        split_test = set(sp.loc[sp["part"] == "test", "GISJOIN"]) if "part" in sp else None
    log.info("versions %s | years %s | t070 exclusion set %d counties", {label(k): v for k, v in VERSIONS.items()},
             args.years, len(excl))
    log.info("reporting rule: county metrics on ALL TEST counties (test_all); kept / excluded t070 only labelled")
    log.info("selection rule (fixed before the results): county CV RMSE on v5.7's CV counties only; the user decides; "
             "tracts reported, not used for tuning")
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    cells = cells_part(args)
    city = city_part(args)
    rows = []
    for y in args.years:
        rows += vc.county_rows(args, y, VERSIONS, excl, split_test, rank_features=RANK_FEATURES)
        tr = pc.tract_rows(args, y, VERSIONS, excl)
        for r in tr:
            r["variant"] = label(r["variant"])
        rows += tr
    if len(cells):
        rows += nc.cell_rows(cells)
    if len(city):
        rows += nc.city_rows(city)
    cmp = pd.DataFrame(rows)
    if cmp.empty or not cmp["level"].isin(["tract", "county"]).any():
        sys.exit("ERROR: no tract / county result files found for any version / year")
    if "city" not in cmp:
        cmp["city"] = np.nan
    cmp.insert(cmp.columns.get_loc("set") + 1, "city", cmp.pop("city"))
    key = ["year", "level", "set", "city"]
    ref = cmp.loc[cmp["variant"] == REF, key + ["mdape"]].rename(columns={"mdape": "ref_mdape"})
    cmp = cmp.merge(ref, on=key, how="left")
    cmp.insert(cmp.columns.get_loc("mape_n") + 1, "d_mdape", cmp["mdape"] - cmp.pop("ref_mdape"))
    if not (cmp["variant"] == NEW).any():
        log.warning("no rows of %s yet (not run?): the table holds the other versions only", VERSIONS[NEW])

    check_all(args, cmp, cells, city)  # stops before anything is written
    ranks = bc.rank_table(args.results_root / "dasymetric" / args.name, {label(k): v for k, v in VERSIONS.items()},
                          args.years)
    fs = factor_summary(args)
    rule = cv_rule(args)
    cmp.to_csv(out / "v57_nbya_comparison.csv", index=False)
    if len(cells):
        cells.to_csv(out / "v57_nbya_cells.csv", index=False)
    if len(city):
        city.to_csv(out / "v57_nbya_city_gaps.csv", index=False)
    ranks.to_csv(out / "v57_nbya_feature_ranks.csv", index=False)
    fs.to_csv(out / "v57_nbya_factor_summary.csv", index=False)
    rule.to_csv(out / "v57_nbya_cv_rule.csv", index=False)

    def piv(t, values, index):
        tab = t.pivot_table(index=index, columns="variant", values=values, sort=False)
        return tab.reindex(columns=[c for c in ORDER if c in tab.columns])

    with pd.option_context("display.width", 220, "display.max_rows", 500, "display.max_columns", 30):
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
                          "cv_rmse_train_kept_t070", "cv_r2_train_kept_t070", "nby_perm_rank", "nby_shap_rank",
                          "nby_age_perm_rank", "nby_age_shap_rank") if k in ca]
        log.info("SUMMARY county CV (own train counties; columns name the CV set; v5.7 and v5.7 + nby_age share one CV "
                 "set) + ranks of nby / nby_age (1 = most important):\n%s", ca[cv].round(4).to_string(index=False))
        tr = cmp[cmp["level"] == "tract"]
        log.info("SUMMARY tract MdAPE (%%) by set, year and variant (areal_weighting = area-proportional):\n%s",
                 piv(tr, "mdape", ["set", "year"]).round(2).to_string())
        log.info("SUMMARY tract MAPE (%%, tracts >= %g people):\n%s", args.mape_min,
                 piv(tr, "mape", ["set", "year"]).round(2).to_string())
        ce = cmp[cmp["level"] == "cells"]
        if len(ce):
            log.info("SUMMARY people on cells (share_bui0 = on BUI = 0 cells / all; share_nb_of_bui0 = of those, on "
                     "NobuiltYear > 0 cells; share_bui0_nb = BUI = 0 and NobuiltYear > 0 / all):\n%s",
                     piv(ce, "share", ["set", "year"]).round(4).to_string())
        if len(city):
            ct = city.pivot_table(index=["city", "year", "set"], columns="variant", values=["n_blocks", "ratio"],
                                  sort=False)
            log.info("SUMMARY city gap blocks (blocks / version people / GHS-POP people; gap_v56 = v5.6's blocks for "
                     "every version):\n%s", ct.round(3).to_string())
        if len(ranks):
            rk = ranks[ranks["feature"].isin(RANK_FEATURES)]
            if len(rk):
                log.info("SUMMARY rank of nby / nby_age (permutation / SHAP):\n%s",
                         rk.pivot_table(index=["year", "feature"], columns="variant",
                                        values=["perm_rank", "shap_rank"]).to_string())
        log_factor_summary(fs)
        if len(rule):
            k = int((rule["lower"] == NEW).sum())
            log.info("SUMMARY selection rule: county CV RMSE on v5.7's CV counties (same folds checked):\n%s",
                     rule.round(4).to_string(index=False))
            log.info("RULE: v5.7 + nby_age has the lower county CV RMSE in %d of %d years (mean change %+.4f, %+.1f %%); "
                     "the user decides", k, len(rule), rule["d_cv_rmse"].mean(), 100 * rule["rel_d_cv_rmse"].mean())
    log.info("wrote %s", out)
    log.info("DONE")
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    return {"config": cmd_config, "factors": cmd_factors, "compare": cmd_compare}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
