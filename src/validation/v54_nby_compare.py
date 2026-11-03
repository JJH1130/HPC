"""v5.4 + NobuiltYear without the county filter (request 2026-11-04, docs/handoff/v54_nby_request.md; docs/conus_plan.md
"v5.4 + NobuiltYear (no filter)"): four versions on the same years, tracts, TEST counties and cells
  v54      Dasy_CONUS_RF_v3_all       (v5.4, no filter)
  v54_nby  Dasy_CONUS_RF_v3_all_nby   (v5.4 + nby, no filter)
  v56      Dasy_CONUS_RF_v3_u070      (v5.6 = v5.4 + the t070 filter: 1,020 counties out of search, fit and TEST)
  v56_nby  Dasy_CONUS_RF_v3_u070_nby  (v5.6 + nby)
Question: does nby make the filter unnecessary? No selection rule (the user decides); tracts are not used for tuning.

Reporting rule (open_items, 2026-11-04): county metrics on ALL TEST counties (kept + excluded by the filter); kept-only
numbers only next to them, labelled.

County level, per year, before allocation (as metrics_over_time.py): predicted pop = exp(y_hat) x area_km2 of the
target (county_features.csv), observed = census pop; MdAPE, MAPE (county pop >= --mape-min), R2 of log density.
  test_all            every TEST county of the split = test_predictions.csv + (filter versions) the TEST part of
                      excluded_predictions.csv (the fitted model's prediction for the excluded counties); the same set
                      in every version (checked) -> the main table
  test_kept_t070 / test_excluded_t070   the same rows split by the t070 exclusion set (labelled)
  The R2 of the set the model reported as its own TEST (test_all without a filter, test_kept_t070 with it) is checked
  against metrics.json test_r2 (logged; DIFFERS on a mismatch).
  CV RMSE / R2 (metrics.json, mean over folds) only in columns named by their CV county set: cv_*_train_all (no filter)
  and cv_*_train_kept_t070 (filter: the excluded counties are not in its CV), + cv_counties. Not comparable between
  filter and no filter, and not a selection criterion (column cv_note, log).
Tract level, as plural_compare.tract_rows (tract_errors_{YEAR}.csv, flag ok, tracts evaluated in every version; sets
from v5.6's file: all, kept / excluded t070, no_gap / gap (gap counties of v5.6, tract_validate.py --gap-version), the
four observed density classes) + areal weighting. d_mdape = MdAPE - v5.4's (same year / level / set).
Cells (--dasym-root + --cutout-root): people on BUI = 0 cells, and of those on NobuiltYear > 0 cells
(nobuilt_compare.cell_sums, the definition of nobuilt_cells.csv); the v5.6 / v5.6 + nby rows must equal
<nobuilt-dir>/nobuilt_cells.csv, else stop.
City gap blocks (+ --ext-config + --data-root): nobuilt_compare.city_table (rule of external_city_meeting.py, Boston /
Denver / Chicago, 1980 / 2010, blocks inside v5.6's mask; v5.6's own = city_maps_meeting/gap_blocks.csv); the v5.6 /
v5.6 + nby rows must equal <nobuilt-dir>/nobuilt_city_gaps.csv, else stop. A v5.4 version whose cells with a prediction
differ from v5.6's is logged (column mask_diff_cells), not stopped.
Ranks of nby (permutation / mean |SHAP|), as builtcell_compare.rank_table.
Without the raster flags the cells / city CSVs of an earlier run in --out-dir are read again (runs locally).

Writes to --out-dir (results/validation/conus/nobuilt/; the nobuilt_* files are not touched):
  v54_nby_comparison.csv     version, variant, year, level (county / tract / cells / city_gap), set, city, n,
                             counties, mdape, mape, mape_n, r2, d_mdape (vs v5.4), r2_reported(_same), cv_counties,
                             cv_rmse_train_all, cv_r2_train_all, cv_rmse_train_kept_t070, cv_r2_train_kept_t070,
                             cv_note, nby ranks, share (cells: the named share; city_gap: version / GHS-POP people)
  v54_nby_cells.csv          as nobuilt_cells.csv, four versions
  v54_nby_city_gaps.csv      as nobuilt_city_gaps.csv, four versions (+ mask_diff_cells)
  v54_nby_feature_ranks.csv  version, variant, year, feature, permutation / mean |SHAP| value and rank
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
import builtcell_compare as bc  # noqa: E402  (feature rank table)
import nobuilt_compare as nc  # noqa: E402  (cells, city gap blocks)
import plural_compare as pc  # noqa: E402  (tract rows)
from compare_models import rank_row  # noqa: E402
from metrics_over_time import mape, mdape, r2  # noqa: E402

log = logging.getLogger("v54_nby_compare")

YEARS = [1910, 1940, 1960, 1980, 2010]
# label -> version; "base" is the key nobuilt_compare / plural_compare use for v5.6 (masks, gap blocks, tract sets)
VERSIONS = {"base": "Dasy_CONUS_RF_v3_u070", "v56_nby": "Dasy_CONUS_RF_v3_u070_nby",
            "v54": "Dasy_CONUS_RF_v3_all", "v54_nby": "Dasy_CONUS_RF_v3_all_nby"}
LABEL = {"base": "v56"}  # output label of the base key
REF = "v54"  # d_mdape against v5.4 (one change: + nby)
ORDER = ["v54", "v54_nby", "v56", "v56_nby", pc.AREAL]
CHECKED = ("base", "v56_nby")  # rows that must equal the NobuiltYear test's files
CV_NOTE = ("CV on each version's own train counties (filter versions: excluded counties not in CV); not comparable "
           "between filter and no filter; not a selection criterion")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--years", type=int, nargs="+", default=YEARS)
    p.add_argument("--city-years", type=int, nargs="+", default=nc.CITY_YEARS)
    p.add_argument("--name", default="conus")
    p.add_argument("--results-root", type=Path, default=Path("results"))
    p.add_argument("--exclusions", type=Path, default=Path("results/hisdac_uncertainty/excluded_counties_t070.csv"))
    p.add_argument("--split", type=Path, default=Path("configs/conus_split.csv"))
    p.add_argument("--mape-min", type=float, default=10)
    p.add_argument("--out-dir", type=Path, default=Path("results/validation/conus/nobuilt"))
    p.add_argument("--nobuilt-dir", type=Path, default=Path("results/validation/conus/nobuilt"),
                   help="nobuilt_cells.csv / nobuilt_city_gaps.csv of the NobuiltYear test (v5.6 rows checked)")
    p.add_argument("--dasym-root", type=Path, help="<root>/<name>/<version>/predictions/pop_{YEAR}.tif (cells, city)")
    p.add_argument("--cutout-root", type=Path, help="<root>/<name>/layers/{BUI,NOBUILT}/ (cells)")
    p.add_argument("--ext-config", type=Path, help="configs/external_grids.yaml (city)")
    p.add_argument("--data-root", type=Path, help="$DATA_ROOT/raw/external (city: GHS-POP)")
    p.add_argument("--gap-csv", type=Path, default=nc.GAP_CSV, help="v5.6's gap blocks of the meeting maps")
    a = p.parse_args(argv)
    a.base = VERSIONS["base"]  # for nobuilt_compare.city_table
    return a


def label(var: str) -> str:
    return LABEL.get(var, var)


# ---------------------------------------------------------------- county level: all TEST counties

def test_predictions(d: Path) -> tuple[pd.DataFrame, bool]:
    """(GISJOIN, y, y_hat of every TEST county of the split, filtered?) for one era folder."""
    tp = pd.read_csv(d / "test_predictions.csv")[["GISJOIN", "y", "y_hat"]]
    ex_path = d / "excluded_predictions.csv"
    if not ex_path.exists():
        return tp, False
    ex = pd.read_csv(ex_path)
    ex = ex.loc[ex["part"] == "test", ["GISJOIN", "y", "y_hat"]]
    both = set(tp["GISJOIN"]) & set(ex["GISJOIN"])
    if both:
        sys.exit(f"ERROR: {d}: {len(both)} counties both in test_predictions.csv and excluded_predictions.csv")
    return pd.concat([tp, ex], ignore_index=True), True


def county_rows(args, year: int, versions: dict, excl: set, split_test: set | None) -> list[dict]:
    root = args.results_root / "dasymetric" / args.name
    rows, sets = [], {}
    for var, v in versions.items():
        d = root / v / f"Y{year}"
        need = [d / "test_predictions.csv", d / "county_features.csv", d / "metrics.json", d / "oof_predictions.csv"]
        missing = [str(f) for f in need if not f.exists()]
        if missing:
            log.warning("%d %s: missing %s; no county rows", year, v, missing)
            continue
        tp, filtered = test_predictions(d)
        cf = pd.read_csv(need[1])[["GISJOIN", "pop", "area_km2", "y"]]
        met = json.loads(need[2].read_text())
        cv_n = len(pd.read_csv(need[3], usecols=["GISJOIN"]))
        p = tp.merge(cf, on="GISJOIN", how="left", suffixes=("", "_features"))
        if p["pop"].isna().any():
            sys.exit(f"ERROR: {year} {v}: {int(p['pop'].isna().sum())} TEST counties not in county_features.csv")
        if not np.allclose(p["y"], p["y_features"], rtol=0, atol=1e-9):
            sys.exit(f"ERROR: {year} {v}: y of the TEST predictions differs from county_features.csv")
        sets[var] = set(p["GISJOIN"])
        inside = p["GISJOIN"].isin(excl).to_numpy()
        own = "test_kept_t070" if filtered else "test_all"  # the model's own reported TEST set
        cvset = "train_kept_t070" if filtered else "train_all"
        for s, m in (("test_all", np.ones(len(p), bool)), ("test_kept_t070", ~inside),
                     ("test_excluded_t070", inside)):
            obs = p["pop"].to_numpy(float)[m]
            est = np.exp(p["y_hat"].to_numpy(float)[m]) * p["area_km2"].to_numpy(float)[m]
            rr = r2(p["y"].to_numpy(float)[m], p["y_hat"].to_numpy(float)[m]) if m.sum() > 1 else np.nan
            r = {"version": v, "variant": label(var), "year": year, "level": "county", "set": s, "n": int(m.sum()),
                 "counties": int(m.sum()), "mdape": mdape(obs, est), "mape": mape(obs, est, args.mape_min),
                 "mape_n": int((obs >= args.mape_min).sum()), "r2": rr, "filtered": filtered}
            if s == own:
                rep = met.get("test_r2")
                r["r2_reported"] = rep
                r["r2_reported_same"] = bool(rep is not None and abs(rr - rep) < 1e-9)
                if not r["r2_reported_same"]:
                    log.warning("%d %s %s: R2 %.6f vs metrics.json test_r2 %s DIFFERS", year, v, s, rr, rep)
            if s == "test_all":
                r.update({"cv_counties": cv_n, f"cv_rmse_{cvset}": met.get("cv_rmse_mean"),
                          f"cv_r2_{cvset}": met.get("cv_r2_mean"), "cv_note": CV_NOTE})
                rk = rank_row(d, ["nby"])
                if rk.get("nby_perm_rank") is not None or rk.get("nby_shap_rank") is not None:
                    r.update(rk)
            rows.append(r)
    if sets:
        first = next(iter(sets))
        for var, s in sets.items():
            if s != sets[first]:
                sys.exit(f"ERROR: {year}: all TEST counties of {versions[var]} differ from {versions[first]} "
                         f"({len(s ^ sets[first])} counties); same split expected")
        if split_test is not None and sets[first] - split_test:
            sys.exit(f"ERROR: {year}: {len(sets[first] - split_test)} TEST counties not test in {args.split}")
        log.info("  %d: %d TEST counties in every version (%d in the t070 exclusion set)", year, len(sets[first]),
                 len(sets[first] & excl))
    return rows


# ---------------------------------------------------------------- cells / city with the NobuiltYear test's checks

def checked(new: pd.DataFrame, path: Path, keys: list, cols: list, what: str):
    """The v5.6 / v5.6 + nby rows of `new` must equal the NobuiltYear test's file (stops on a difference)."""
    if not path.exists():
        log.warning("%s: %s not found; v5.6 / v5.6 + nby rows not checked", what, path)
        return
    sub = new[new["version"].isin([VERSIONS[k] for k in CHECKED])]
    import external_city_meeting as ecmt
    n = ecmt.check_previous(sub, [path], keys, cols)
    if n != len(sub):
        sys.exit(f"ERROR: {what}: {len(sub)} v5.6 / v5.6 + nby rows, {n} of them in {path}")


def cells_part(args) -> pd.DataFrame:
    out = args.out_dir / "v54_nby_cells.csv"
    if args.dasym_root and args.cutout_root:
        log.info("== cells: people on BUI = 0 cells and on NobuiltYear > 0 among them (nobuilt_cells.csv definition)")
        cells = nc.cells_table(args, VERSIONS)
        cells["variant"] = cells["variant"].map(label)
        checked(cells, args.nobuilt_dir / "nobuilt_cells.csv", ["version", "year"],
                ["cells", "cells_bui0", "cells_bui0_nb", "pop", "pop_bui0", "pop_bui0_nb", "pop_nb"], "cells")
        cells.to_csv(out, index=False)
        return cells
    if out.exists():
        log.info("== cells: read again from %s", out)
        return pd.read_csv(out)
    log.warning("== cells: no rasters given and no %s; no cell rows", out)
    return pd.DataFrame()


def city_part(args) -> pd.DataFrame:
    out = args.out_dir / "v54_nby_city_gaps.csv"
    if args.dasym_root and args.ext_config and args.data_root:
        log.info("== city gap blocks (rule of external_city_meeting.py, blocks inside v5.6's mask)")
        city = nc.city_table(args, VERSIONS, strict_mask=False)
        if len(city):
            city["variant"] = city["variant"].map(label)
            pop = [c for c in city.columns if c.startswith("pop_") and c != "pop_version"]
            checked(city, args.nobuilt_dir / "nobuilt_city_gaps.csv", ["city", "year", "version", "set"],
                    ["n_blocks", "pop_version", *pop, "ratio"], "city gap blocks")
        city.to_csv(out, index=False)
        return city
    if out.exists():
        log.info("== city: read again from %s", out)
        return pd.read_csv(out)
    log.warning("== city: no rasters / config given and no %s; no city rows", out)
    return pd.DataFrame()


# ---------------------------------------------------------------- main

def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    if not args.exclusions.exists():
        sys.exit(f"ERROR: {args.exclusions} not found (src/grid/uncertainty_filter.py)")
    excl = set(pd.read_csv(args.exclusions)["GISJOIN"])
    split_test = None
    if args.split.exists():
        sp = pd.read_csv(args.split)
        split_test = set(sp.loc[sp["part"] == "test", "GISJOIN"]) if "part" in sp else None
    log.info("versions %s | years %s | t070 exclusion set %d counties | no selection rule (the user decides)",
             {label(k): v for k, v in VERSIONS.items()}, args.years, len(excl))
    log.info("reporting rule: county metrics on ALL TEST counties (test_all); kept / excluded t070 only labelled")
    log.info("CV: %s", CV_NOTE)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    cells = cells_part(args)
    city = city_part(args)

    rows = []
    for y in args.years:
        rows += county_rows(args, y, VERSIONS, excl, split_test)
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
    cmp.to_csv(out / "v54_nby_comparison.csv", index=False)
    ranks = bc.rank_table(args.results_root / "dasymetric" / args.name,
                          {label(k): v for k, v in VERSIONS.items()}, args.years)
    ranks.to_csv(out / "v54_nby_feature_ranks.csv", index=False)

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
                          "cv_rmse_train_kept_t070", "cv_r2_train_kept_t070", "nby_perm_rank", "nby_shap_rank")
              if k in ca]
        log.info("SUMMARY county CV (own train counties; columns name the CV set; NOT comparable between filter and no "
                 "filter, not a selection criterion) + rank of nby (1 = most important):\n%s",
                 ca[cv].round(4).to_string(index=False))
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
        if len(ranks) and "nby" in set(ranks["feature"]):
            log.info("SUMMARY rank of nby (permutation / SHAP):\n%s",
                     ranks[ranks["feature"] == "nby"].pivot_table(index="year", columns="variant",
                                                                  values=["perm_rank", "shap_rank"]).to_string())
    log.info("wrote %s", out)
    log.info("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
