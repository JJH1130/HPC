"""PLURAL at county level only (request 2026-11-19, docs/handoff/plural_countymean_request.md; docs/conus_plan.md
"PLURAL at county level only"). PLURAL on v5.7 improved county CV but worsened tracts in 1980 / 2010 (rural most).
Hypothesis: plural separates counties (good for the county prediction) but its cell values blur the allocation inside a
county. Test without retraining: the trained models of pq5 / plc predict with every cell's plural replaced by its
county's plural (the county-feature value the model was trained on; predict.py `plural: {cell_value: county_mean}` +
`model_from`). Versions:
  v57         Dasy_CONUS_RF_v3_all_nby          v5.7 (the base)
  v57_pq5     Dasy_CONUS_RF_v3_all_nby_pq5      v5.7 + plural, 5 quantile classes (cell values)
  v57_pq5cm   Dasy_CONUS_RF_v3_all_nby_pq5cm    pq5's models, county plural at prediction
  v57_plc     Dasy_CONUS_RF_v3_all_nby_plc      v5.7 + plural, continuous bilinear (cell values)
  v57_plccm   Dasy_CONUS_RF_v3_all_nby_plccm    plc's models, county plural at prediction
  (base = v5.6, Dasy_CONUS_RF_v3_u070: tract sets and gap counties, as before; its rows are not in the table)

Subcommands:
  config    each cm config = its PLURAL config + model_from <PLURAL version>, compare_with <PLURAL version>, plural
            cell_value county_mean, version <PLURAL version>cm; nothing else differs. CONFIG OK or exit 1 (login node).
  snapshot  login node, before submitting: sha256 of each PLURAL version's era model, county_features.csv and
            plural_breaks.csv on scratch -> logs/conus_pluralcm_models.json (the compare checks the cm runs against it)
  variance  diagnosis job, no model: over the study cells (the unmasked cells of v5.7's counties, = the cells averaged
            into the county features) the variance of plural (bilinear value, pq5 class), bui, nby, bldg_size split into
            between counties / within counties (within share = sum over counties of the within-county sum of squares /
            the total sum of squares); two passes in strips. Check first: the county means of the pass = the county
            features of v5.7 (bui, nby, bldg_size), plc (plural) and pq5 (plural classes with pq5's breaks), rtol 1e-9,
            else stop -> pluralcm_variance_split.csv (+ VARIANCE lines)
  compare   after the two predict / validate chains and the variance job:
            - model check: <cm>/<era>/model_from.json (predict.py: the loaded model gave the PLURAL version's TEST
              predictions; hashes) = the snapshot = the model file on scratch now; else stop
            - county (v54_nby_compare.county_rows): v5.7 / pq5 / plc on ALL TEST counties; a cm version gets its PLURAL
              version's county rows (same model + same county features: same county TEST / CV numbers; column
              county_from)
            - tracts (plural_compare.tract_rows): all, kept / excluded t070, no_gap / gap (v5.6's gap counties), four
              observed density classes, areal weighting; d_mdape = - v5.7, d_mdape_orig = cm - its PLURAL version
            - cells (nobuilt_compare.cell_sums): people on BUI = 0 cells, of those on NobuiltYear > 0 cells
            - built contrast: per county, mean weight (people / km2 after allocation) of built cells (BUI > 0) / of
              BUI = 0 cells, and of BUI = 0 cells split into NobuiltYear > 0 / = 0 (water-masked cells left out);
              county median and 10 / 90 % per version and year (+ the group densities)
            - interpretation rule (fixed 2026-11-19 before the results, logged first; RULE lines)
            Checks, a difference stops the run before writing: v5.7 / pq5 / plc / areal weighting rows =
            plural_grid_v57/plural_v57_comparison.csv (county, tract, cells), their cell rows = plural_v57_cells.csv,
            people in the contrast pass = people in the cell pass.
Writes results/validation/conus/plural_grid_v57/countymean/: pluralcm_{comparison, cells, built_contrast, rule,
model_check, variance_split}.csv. No figure.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "dasymetric")]
import nobuilt_compare as nc  # noqa: E402  (cells)
import plural_compare as pc  # noqa: E402  (tract rows)
import v54_nby_compare as vc  # noqa: E402  (county rows on all TEST counties)
import v57_nbya_compare as vn  # noqa: E402  (row checks against earlier tables)

log = logging.getLogger("plural_countymean")

YEARS = [1940, 1980, 2010]
V57, V56 = "Dasy_CONUS_RF_v3_all_nby", "Dasy_CONUS_RF_v3_u070"
PAIRS = ["pq5", "plc"]  # PLURAL variant -> <variant>cm
OUT = Path("results/validation/conus/plural_grid_v57/countymean")
PREV = Path("results/validation/conus/plural_grid_v57")
SNAPSHOT = Path("logs/conus_pluralcm_models.json")
RANK_FEATURES = ("plural", "nby")
CHECK_COLS = vn.CMP_COLS + ["plural_perm_rank", "plural_shap_rank", "plural_perm", "plural_shap"]
FEATURE_RTOL = 1e-9  # county means of the variance pass = county_features.csv
POP_RTOL = 1e-9  # people of the contrast pass = people of the cell pass
CELL_KM2 = 0.0625
TOL_PP = 0.5  # interpretation rule: "at the level of" = within 0.5 points of tract MdAPE
GAP_MIN_PP = 1.0  # judged only where the PLURAL version differs from v5.7 by more than this
RULE_TEXT = (
    "interpretation rule (fixed 2026-11-19 before the results): per PLURAL version P (pq5, plc) and its county-mean "
    "version Pcm, tract MdAPE of all tracts per year, judged where |P - v5.7| > %.1f pp: cell_level = |Pcm - v5.7| <= "
    "%.1f pp (the cell values of plural cause the tract loss); county_level = |Pcm - P| <= %.1f pp (the changed county "
    "prediction itself causes it); beyond_v57 = Pcm past v5.7 by more than %.1f pp; further = Pcm further from v5.7 "
    "than P by more than %.1f pp; partial = in between (recovered = (P - Pcm) / (P - v5.7)); not_judged where |P - "
    "v5.7| <= %.1f pp. Other tract sets: same numbers, not judged. A cause check, not a selection; the user decides"
    % (GAP_MIN_PP, TOL_PP, TOL_PP, TOL_PP, TOL_PP, GAP_MIN_PP))
VAR_FEATURES = ["plural_plc", "plural_pq5", "bui", "nby", "bldg_size"]
GROUPS = ("built", "bui0_nb", "bui0_norec")  # BUI > 0 | BUI = 0 and NobuiltYear > 0 | BUI = 0 and NobuiltYear = 0


def versions(pairs=PAIRS, base: bool = True) -> dict:
    """label -> version; "base" (= v5.6) first: plural_compare.tract_rows takes the tract sets from it."""
    out = {"base": V56} if base else {}
    out["v57"] = V57
    for v in pairs:
        out[f"v57_{v}"] = f"{V57}_{v}"
        out[f"v57_{v}cm"] = f"{V57}_{v}cm"
    return out


def order(pairs) -> list[str]:
    return ["v57", *[x for v in pairs for x in (f"v57_{v}", f"v57_{v}cm")], pc.AREAL]


def config_path(variant: str, cm: bool, pattern: str | None = None) -> Path:
    if pattern:
        return Path(pattern.format(v=variant))
    return Path(f"configs/conus_rf_v3_all_nby_{variant}{'cm' if cm else ''}.yaml")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def add_common(p):
    p.add_argument("--pairs", nargs="+", default=PAIRS, help="PLURAL variants with a <variant>cm version")
    p.add_argument("--years", type=int, nargs="+", default=YEARS)
    p.add_argument("--name", default="conus")
    p.add_argument("--results-root", type=Path, default=Path("results"))
    p.add_argument("--out-dir", type=Path, default=OUT)
    p.add_argument("--block-rows", type=int, default=512)
    p.add_argument("--water-mask", default="yearly", help="v5.7's water_mask (the cells of its county features)")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("config", help="cm configs = the PLURAL configs + county_mean / model_from")
    c.add_argument("--pairs", nargs="+", default=PAIRS)
    c.add_argument("--cm-pattern", help="cm config path, {v} = variant (default configs/conus_rf_v3_all_nby_{v}cm.yaml)")
    s = sub.add_parser("snapshot", help="hashes of the PLURAL versions' models / county features (login node)")
    add_common(s)
    s.add_argument("--dasym-root", type=Path, required=True)
    s.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    v = sub.add_parser("variance", help="between / within county variance of plural, bui, nby, bldg_size")
    add_common(v)
    v.add_argument("--cutout-root", type=Path, required=True)
    m = sub.add_parser("compare", help="the comparison")
    add_common(m)
    m.add_argument("--exclusions", type=Path, default=Path("results/hisdac_uncertainty/excluded_counties_t070.csv"))
    m.add_argument("--split", type=Path, default=Path("configs/conus_split.csv"))
    m.add_argument("--mape-min", type=float, default=10)
    m.add_argument("--prev-dir", type=Path, default=PREV, help="plural_v57_comparison.csv / plural_v57_cells.csv")
    m.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    m.add_argument("--dasym-root", type=Path, help="<root>/<name>/<version>/predictions/pop_{YEAR}.tif + models")
    m.add_argument("--cutout-root", type=Path, help="<root>/<name>/layers/ + zones/ (cells, built contrast)")
    a = p.parse_args(argv)
    a.base = V56  # for plural_compare.tract_rows
    return a


# ---------------------------------------------------------------- config

def config_problems(cm: dict, orig: dict, variant: str) -> list[str]:
    """Differences of a cm config from 'its PLURAL config + county_mean / model_from' (empty = OK)."""
    bad = []
    want = {"version": f"{orig['version']}cm", "model_from": orig["version"], "compare_with": orig["version"]}
    for k, w in want.items():
        if cm.get(k) != w:
            bad.append(f"{k} {cm.get(k)} != {w}")
    if orig.get("model_from"):
        bad.append(f"the PLURAL config has model_from {orig['model_from']}")
    if (orig.get("plural") or {}).get("cell_value") is not None:
        bad.append(f"the PLURAL config has cell_value {orig['plural']['cell_value']}")
    wp = {**(orig.get("plural") or {}), "cell_value": "county_mean"}
    if cm.get("plural") != wp:
        bad.append(f"plural block {cm.get('plural')} != {wp}")
    for k in sorted((set(cm) | set(orig)) - set(want) - {"plural"}):
        if cm.get(k) != orig.get(k):
            bad.append(f"{k}: {cm.get(k)} != {variant}'s {orig.get(k)}")
    return bad


def cmd_config(args) -> int:
    import common as dcommon
    n_bad = 0
    for v in args.pairs:
        cp, op = config_path(v, True, args.cm_pattern), config_path(v, False)
        bad = config_problems(dcommon.load_config(cp), dcommon.load_config(op), v)
        for b in bad:
            print(f"CONFIG DIFFERS {v}cm: {b}")
        n_bad += len(bad)
        if not bad:
            print(f"  {v}cm: {cp} = {op} + model_from / compare_with {V57}_{v}, plural cell_value county_mean")
    if n_bad:
        print(f"ERROR: {n_bad} differences")
        return 1
    print(f"CONFIG OK: {len(args.pairs)} cm configs = their PLURAL configs + plural cell_value county_mean + model_from "
          f"({', '.join(v + 'cm' for v in args.pairs)}); no features / train jobs")
    return 0


# ---------------------------------------------------------------- snapshot (login node)

def source_files(dasym_root: Path, name: str, variant: str, year: int) -> dict:
    e = dasym_root / name / f"{V57}_{variant}" / f"Y{year}"
    f = {"model": e / "model" / "rf.joblib", "county_features": e / "features" / "county_features.csv"}
    if variant in pc.CLASSED:
        f["plural_breaks"] = e / "features" / "plural_breaks.csv"
    return f


def cmd_snapshot(args) -> int:
    snap = {"created": dt.datetime.now().isoformat(timespec="seconds"), "dasym_root": str(args.dasym_root),
            "versions": {}}
    miss = []
    for v in args.pairs:
        for y in args.years:
            files = source_files(args.dasym_root, args.name, v, y)
            ent = {}
            for k, p in files.items():
                if not p.exists():
                    miss.append(str(p))
                    continue
                ent[k] = {"path": str(p), "sha256": sha256(p)}
                print(f"  {v} {y} {k}: {ent[k]['sha256']}  {p}")
            snap["versions"].setdefault(f"{V57}_{v}", {})[f"Y{y}"] = ent
    if miss:
        for m in miss:
            print(f"MISSING {m}")
        print("ERROR: snapshot incomplete")
        return 1
    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
    args.snapshot.write_text(json.dumps(snap, indent=2))
    n = sum(len(e) for d in snap["versions"].values() for e in d.values())
    print(f"SNAPSHOT OK: {n} files of {len(args.pairs)} PLURAL versions x {len(args.years)} years -> {args.snapshot}")
    return 0


# ---------------------------------------------------------------- variance split (no model)

def era_dir(args, version: str, year: int) -> Path:
    return args.results_root / "dasymetric" / args.name / version / f"Y{year}"


def read_cf(args, version: str, year: int) -> pd.DataFrame:
    p = era_dir(args, version, year) / "county_features.csv"
    if not p.exists():
        sys.exit(f"ERROR: {p} not found")
    t = pd.read_csv(p, float_precision="round_trip")
    return t[t["year"] == year].set_index("zone_id")


def strip_values(cutout: Path, year: int, grid: dict, zones: np.ndarray, ids, rws, whole: bool, inner, water):
    """Zone ids + the five cell values of the unmasked study cells of one strip (None if the strip has none)."""
    import common as dc
    mask = dc.used_mask(zones[rws], ids)
    if not mask.any():
        return None
    rows = None if whole else rws
    keep = ~dc.water_mask(cutout, year, grid, mask, water, rows)[0]
    bui = dc.read_layer(cutout, "BUI", year, grid, mask, rows)
    bupl = dc.read_layer(cutout, "BUPL", year, grid, mask, rows)
    pl = dc.read_layer(cutout, "PLURAL", year, grid, mask, rows)
    vals = {"plural_plc": pl, "plural_pq5": dc.plural_classes(pl, inner),
            "bui": bui, "nby": dc.read_layer(cutout, dc.NOBUILT_LAYER, None, grid, mask, rows),
            "bldg_size": np.divide(bui, bupl, out=np.zeros_like(bupl), where=bupl > 0)}
    return zones[rws][mask][keep], {k: v[keep] for k, v in vals.items()}


def variance_year(args, year: int) -> tuple[list[dict], list[dict]]:
    import common as dc
    cutout = args.cutout_root / args.name
    zones, table, grid = dc.read_zones(cutout, year)
    c57 = read_cf(args, V57, year)
    cpl, cpq = read_cf(args, f"{V57}_plc", year), read_cf(args, f"{V57}_pq5", year)
    for t, v in ((cpl, "plc"), (cpq, "pq5")):
        if set(t.index) != set(c57.index):
            sys.exit(f"ERROR: {year}: counties of {v} differ from v5.7 ({len(set(t.index) ^ set(c57.index))})")
    gis = table.set_index("zone_id")["GISJOIN"].reindex(c57.index)
    if (gis.to_numpy() != c57["GISJOIN"].to_numpy()).any():
        sys.exit(f"ERROR: {year}: zone ids of v5.7's county features differ from the cutout's zone table")
    bp = era_dir(args, f"{V57}_pq5", year) / "plural_breaks.csv"
    if not bp.exists():
        sys.exit(f"ERROR: {bp} not found")
    b = pd.read_csv(bp)
    b = b[b["year"] == year].iloc[0]
    inner = np.array([b[f"break_{i}"] for i in range(1, int(b["classes"]))], float)
    ids = c57.index.to_numpy()
    nz = int(max(zones.max(), ids.max())) + 1
    parts = dc.strips(zones.shape, args.block_rows)
    whole = len(parts) == 1
    n = np.zeros(nz)
    s = {f: np.zeros(nz) for f in VAR_FEATURES}
    for rws in parts:  # pass 1: county sums
        r = strip_values(cutout, year, grid, zones, ids, rws, whole, inner, args.water_mask)
        if r is None:
            continue
        z, vals = r
        n += np.bincount(z, minlength=nz)
        for f in VAR_FEATURES:
            s[f] += np.bincount(z, weights=vals[f], minlength=nz)
    if (n[ids] == 0).any():
        sys.exit(f"ERROR: {year}: {int((n[ids] == 0).sum())} counties of v5.7's features have no unmasked cell")
    mean = {f: np.divide(s[f], n, out=np.zeros(nz), where=n > 0) for f in VAR_FEATURES}
    ref = {"bui": c57["bui"], "nby": c57["nby"], "bldg_size": c57["bldg_size"], "plural_plc": cpl["plural"],
           "plural_pq5": cpq["plural"]}
    chk = []
    for f, col in ref.items():
        got = mean[f][col.index.to_numpy()]
        ok = np.isclose(got, col.to_numpy(float), rtol=FEATURE_RTOL, atol=1e-12)
        rel = np.abs(got - col.to_numpy(float)) / np.maximum(np.abs(col.to_numpy(float)), 1e-300)
        chk.append({"year": year, "feature": f, "counties": len(col), "n_differ": int((~ok).sum()),
                    "max_rel_diff": float(rel.max())})
        if not ok.all():
            sys.exit(f"ERROR: VARIANCE CHECK {year} {f}: county means differ from the county features for "
                     f"{int((~ok).sum())} counties (max rel diff {rel.max():.3g}); not the cells of the model")
    log.info("  %d: county means of the pass = county features (v5.7 bui / nby / bldg_size, plc plural, pq5 plural "
             "classes; %d counties, rtol %.0e)", year, len(ids), FEATURE_RTOL)
    N = n.sum()
    gm = {f: s[f].sum() / N for f in VAR_FEATURES}
    within = {f: np.zeros(nz) for f in VAR_FEATURES}
    total = dict.fromkeys(VAR_FEATURES, 0.0)
    for rws in parts:  # pass 2: sums of squares around the county mean and the grand mean
        r = strip_values(cutout, year, grid, zones, ids, rws, whole, inner, args.water_mask)
        if r is None:
            continue
        z, vals = r
        for f in VAR_FEATURES:
            within[f] += np.bincount(z, weights=(vals[f] - mean[f][z]) ** 2, minlength=nz)
            total[f] += float(((vals[f] - gm[f]) ** 2).sum())
    rows = []
    for f in VAR_FEATURES:
        w = float(within[f].sum())
        t = total[f]
        rows.append({"year": year, "feature": f, "cells": int(N), "counties": len(ids), "mean": gm[f],
                     "total_ss": t, "within_ss": w, "between_ss": t - w, "total_var": t / N,
                     "within_share": w / t if t > 0 else np.nan, "between_share": 1 - w / t if t > 0 else np.nan,
                     "counties_constant": int((within[f][ids] == 0).sum())})
        log.info("VARIANCE %d %-10s: %d cells, %d counties | within-county share of the variance %.4f, between %.4f "
                 "| counties with one value %d", year, f, N, len(ids), rows[-1]["within_share"],
                 rows[-1]["between_share"], rows[-1]["counties_constant"])
    return rows, chk


def cmd_variance(args) -> int:
    log.info("== variance split over the study cells (unmasked cells of v5.7's counties): within share = sum over "
             "counties of the within-county sum of squares / total sum of squares")
    rows, chk = [], []
    for y in args.years:
        r, c = variance_year(args, y)
        rows += r
        chk += c
    args.out_dir.mkdir(parents=True, exist_ok=True)
    t = pd.DataFrame(rows)
    t.to_csv(args.out_dir / "pluralcm_variance_split.csv", index=False)
    log.info("SUMMARY within-county share of the cell variance (1 = all inside counties, 0 = all between):\n%s",
             t.pivot_table(index="feature", columns="year", values="within_share", sort=False).round(4).to_string())
    log.info("VARIANCE OK: %d years x %d features, county means = county features -> %s", len(args.years),
             len(VAR_FEATURES), args.out_dir / "pluralcm_variance_split.csv")
    log.info("DONE")
    return 0


# ---------------------------------------------------------------- built contrast (predictions)

def _dens(pp: np.ndarray, nn: np.ndarray) -> np.ndarray:
    """Mean weight (people / km2) of a group of cells per county; NaN without a cell."""
    return np.divide(pp, nn * CELL_KM2, out=np.full(len(pp), np.nan), where=nn > 0)


def contrast_year(args, year: int, vers: dict) -> tuple[list[dict], dict]:
    """Per version: per-county mean weight (people / km2) of built / BUI = 0 (NobuiltYear > 0 / = 0) cells, summarised
    over counties; + people over all predicted cells (checked against the cell pass)."""
    import rasterio
    import common as dc
    from rasterio.windows import Window
    cutout = args.cutout_root / args.name
    zones, table, grid = dc.read_zones(cutout, year)
    nz = int(zones.max()) + 1
    labs = [lab for lab, v in vers.items()
            if (args.dasym_root / args.name / v / "predictions" / f"pop_{year}.tif").exists()]
    for lab in vers:
        if lab not in labs:
            log.warning("  contrast %d %s: no prediction on scratch; left out", year, vers[lab])
    if not labs:
        return [], {}
    srcs = {lab: rasterio.open(args.dasym_root / args.name / vers[lab] / "predictions" / f"pop_{year}.tif")
            for lab in labs}
    try:
        for lab, s in srcs.items():
            if (s.height, s.width) != grid["shape"] or s.transform != grid["transform"]:
                sys.exit(f"ERROR: {s.name} is not on the zones grid")
        n = {lab: {g: np.zeros(nz) for g in GROUPS} for lab in labs}
        p = {lab: {g: np.zeros(nz) for g in GROUPS} for lab in labs}
        tot = dict.fromkeys(labs, 0.0)
        parts = dc.strips(zones.shape, args.block_rows)
        whole = len(parts) == 1
        for rws in parts:
            w = Window(0, rws.start, grid["shape"][1], rws.stop - rws.start)
            arr = {lab: s.read(1, window=w).astype("float64") for lab, s in srcs.items()}
            ok = {lab: (a != srcs[lab].nodata) & np.isfinite(a) for lab, a in arr.items()}
            mask = ok[labs[0]]
            for lab in labs[1:]:
                if (ok[lab] != mask).any():
                    sys.exit(f"ERROR: {year}: predicted cells of {vers[lab]} differ from {vers[labs[0]]} (rows "
                             f"{rws.start}-{rws.stop})")
            if not mask.any():
                continue
            rows = None if whole else rws
            keep = ~dc.water_mask(cutout, year, grid, mask, args.water_mask, rows)[0]
            bui = dc.read_layer(cutout, "BUI", year, grid, mask, rows)[keep]
            nby = dc.read_layer(cutout, dc.NOBUILT_LAYER, None, grid, mask, rows)[keep]
            z = zones[rws][mask][keep]
            grp = np.where(bui > 0, 0, np.where(nby > 0, 1, 2))
            for lab in labs:
                v = arr[lab][mask]
                tot[lab] += float(v.sum())
                v = v[keep]
                for gi, g in enumerate(GROUPS):
                    sel = grp == gi
                    n[lab][g] += np.bincount(z[sel], minlength=nz)
                    p[lab][g] += np.bincount(z[sel], weights=v[sel], minlength=nz)
    finally:
        for s in srcs.values():
            s.close()
    rows = []
    for lab in labs:
        cnt = n[lab]["built"] + n[lab]["bui0_nb"] + n[lab]["bui0_norec"]
        zid = np.flatnonzero(cnt > 0)
        d = {g: _dens(p[lab][g][zid], n[lab][g][zid]) for g in GROUPS}
        d["bui0"] = _dens(p[lab]["bui0_nb"][zid] + p[lab]["bui0_norec"][zid],
                         n[lab]["bui0_nb"][zid] + n[lab]["bui0_norec"][zid])
        meas = {f"dens_{g}": d[g] for g in ("built", "bui0", "bui0_nb", "bui0_norec")}
        for g in ("bui0", "bui0_nb", "bui0_norec"):
            meas[f"built_vs_{g}"] = np.divide(d["built"], d[g], out=np.full(len(zid), np.nan),
                                              where=np.isfinite(d["built"]) & np.isfinite(d[g]) & (d[g] > 0))
        res = {}
        for m, x in meas.items():
            x = x[np.isfinite(x)]
            q = np.quantile(x, [0.1, 0.5, 0.9]) if len(x) else [np.nan] * 3
            res[m] = {"version": vers[lab], "variant": lab, "year": year, "measure": m, "counties": len(x),
                      "p10": q[0], "median": q[1], "p90": q[2],
                      "share_lt1": float((x < 1).mean()) if m.startswith("built_vs") and len(x) else np.nan}
        rows += list(res.values())
        a, b, c = res["built_vs_bui0"], res["built_vs_bui0_nb"], res["built_vs_bui0_norec"]
        log.info("  contrast %d %-10s: %d counties | built / BUI = 0 weight, county median %.2f (10-90 %% %.2f-%.2f) | "
                 "built / (BUI = 0, NobuiltYear > 0) %.2f | built / (BUI = 0, no record) %.2f", year, lab, len(zid),
                 a["median"], a["p10"], a["p90"], b["median"], c["median"])
    return rows, {(vers[lab], year): tot[lab] for lab in labs}


def contrast_part(args, vers: dict, cells: pd.DataFrame) -> pd.DataFrame:
    out = args.out_dir / "pluralcm_built_contrast.csv"
    if not (args.dasym_root and args.cutout_root):
        if out.exists():
            log.info("== built contrast: read again from %s", out)
            return pd.read_csv(out)
        log.warning("== built contrast: no rasters given and no %s; no contrast rows", out)
        return pd.DataFrame()
    log.info("== built contrast: per county mean weight (people / km2) of built / BUI = 0 cells (water-masked cells "
             "left out), county median + 10 / 90 %%")
    rows, tots = [], {}
    for y in args.years:
        r, t = contrast_year(args, y, vers)
        rows += r
        tots.update(t)
    if len(cells):  # the same people as the cell pass (nobuilt_compare.cell_sums)
        for (v, y), t in tots.items():
            c = cells[(cells["version"] == v) & (cells["year"] == y)]
            if len(c) != 1 or not np.isclose(t, float(c["pop"].iloc[0]), rtol=POP_RTOL, atol=0):
                sys.exit(f"ERROR: {y} {v}: people of the contrast pass {t} != the cell pass {c['pop'].tolist()}")
        log.info("  MATCH contrast people = cell people (%d version-years)", len(tots))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- model check

def model_checks(args) -> pd.DataFrame:
    snap = json.loads(args.snapshot.read_text()) if args.snapshot.exists() else None
    if snap is None:
        log.warning("no snapshot %s: the cm hashes are checked against the scratch files only", args.snapshot)
    rows = []
    for v in args.pairs:
        orig, cm = f"{V57}_{v}", f"{V57}_{v}cm"
        for y in args.years:
            j = era_dir(args, cm, y) / "model_from.json"
            r = {"variant": f"v57_{v}cm", "version": cm, "model_from": orig, "year": y}
            if not j.exists():
                rows.append({**r, "status": "missing"})
                continue
            info = json.loads(j.read_text())
            r.update({k: info.get(k) for k in ("era", "test_rows", "test_max_abs_diff", "test_check", "model_sha256",
                                               "county_features_sha256", "plural_breaks_sha256")})
            bad = []
            if info.get("model_from") != orig or info.get("version") != cm:
                bad.append(f"model_from.json is for {info.get('version')} <- {info.get('model_from')}")
            if info.get("test_check") != "OK":
                bad.append(f"TEST check {info.get('test_check')}")
            ent = ((snap or {}).get("versions", {}).get(orig, {}).get(f"Y{y}")) if snap else None
            if snap is not None:
                if not ent:
                    bad.append("not in the snapshot")
                else:
                    for k, col in (("model", "model_sha256"), ("county_features", "county_features_sha256"),
                                   ("plural_breaks", "plural_breaks_sha256")):
                        if k in ent and ent[k]["sha256"] != info.get(col):
                            bad.append(f"{k} sha256 differs from the snapshot")
            r["snapshot"] = bool(ent)
            if args.dasym_root:
                src = source_files(args.dasym_root, args.name, v, y)
                now = sha256(src["model"]) if src["model"].exists() else None
                r["model_sha256_now"] = now
                if now != info.get("model_sha256"):
                    bad.append(f"model file on scratch now {now} != {info.get('model_sha256')}")
            r["status"] = "OK" if not bad else "; ".join(bad)
            rows.append(r)
    t = pd.DataFrame(rows)
    for r in t.itertuples():
        (log.info if r.status in ("OK", "missing") else log.error)(
            "  MODEL %s %d <- %s: %s%s", r.version, r.year, r.model_from, r.status,
            "" if r.status == "missing" else f" (TEST rows {r.test_rows}, max |diff| {r.test_max_abs_diff:.3g})")
    return t


# ---------------------------------------------------------------- interpretation rule

def rule_table(cmp: pd.DataFrame, pairs) -> pd.DataFrame:
    tr = cmp[cmp["level"] == "tract"].set_index(["variant", "year", "set"])["mdape"]
    rows = []
    for v in pairs:
        p, c = f"v57_{v}", f"v57_{v}cm"
        for (lab, y, s), cm_val in tr.items():
            if lab != c or ("v57", y, s) not in tr or (p, y, s) not in tr:
                continue
            b, o = tr[("v57", y, s)], tr[(p, y, s)]
            gap = o - b
            rec = (o - cm_val) / gap if gap != 0 else np.nan
            if abs(gap) <= GAP_MIN_PP:
                out = "not_judged"
            elif abs(cm_val - b) <= TOL_PP:
                out = "cell_level"
            elif abs(cm_val - o) <= TOL_PP:
                out = "county_level"
            elif (cm_val - b) * np.sign(-gap) > TOL_PP:
                out = "beyond_v57"
            elif (cm_val - o) * np.sign(gap) > TOL_PP:
                out = "further"
            else:
                out = "partial"
            rows.append({"pair": v, "plural_version": f"{V57}_{v}", "cm_version": f"{V57}_{v}cm", "year": y, "set": s,
                         "mdape_v57": b, "mdape_plural": o, "mdape_cm": cm_val, "gap_plural_v57": gap,
                         "d_cm_v57": cm_val - b, "d_cm_plural": cm_val - o, "recovered": rec, "outcome": out,
                         "judged": s == "all"})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- compare

def cells_part(args, vers: dict) -> pd.DataFrame:
    out = args.out_dir / "pluralcm_cells.csv"
    if args.dasym_root and args.cutout_root:
        log.info("== cells: people on BUI = 0 cells and on NobuiltYear > 0 among them (nobuilt_cells.csv definition)")
        return nc.cells_table(args, vers)
    if out.exists():
        log.info("== cells: read again from %s", out)
        return pd.read_csv(out)
    log.warning("== cells: no rasters given and no %s; no cell rows", out)
    return pd.DataFrame()


def cmd_compare(args) -> int:
    log.info("RULE: " + RULE_TEXT)
    if not args.exclusions.exists():
        sys.exit(f"ERROR: {args.exclusions} not found (src/grid/uncertainty_filter.py)")
    excl = set(pd.read_csv(args.exclusions)["GISJOIN"])
    split_test = None
    if args.split.exists():
        sp = pd.read_csv(args.split)
        split_test = set(sp.loc[sp["part"] == "test", "GISJOIN"]) if "part" in sp else None
    vers = versions(args.pairs)
    own = {k: v for k, v in vers.items() if k != "base"}
    log.info("versions %s | years %s | t070 exclusion set %d counties", own, args.years, len(excl))
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    log.info("== model check: the cm runs used the PLURAL versions' models (predict.py TEST check, snapshot, scratch)")
    mchk = model_checks(args)
    bad = mchk[~mchk["status"].isin(["OK", "missing"])]
    if len(bad):
        sys.exit(f"ERROR: model check failed: {bad[['version', 'year', 'status']].to_dict('records')}")
    ok_cm = {(r.version, r.year) for r in mchk.itertuples() if r.status == "OK"}

    cells = cells_part(args, own)
    rows = []
    plain = {k: v for k, v in own.items() if not k.endswith("cm")}
    for y in args.years:
        cr = vc.county_rows(args, y, plain, excl, split_test, rank_features=RANK_FEATURES)
        for v in args.pairs:  # same model + same county features = the PLURAL version's county numbers
            cm = f"{V57}_{v}cm"
            if (cm, y) in ok_cm:
                cr += [{**r, "version": cm, "variant": f"v57_{v}cm", "county_from": r["version"]}
                       for r in cr if r["variant"] == f"v57_{v}"]
        rows += cr
        tr = [r for r in pc.tract_rows(args, y, vers, excl) if r["variant"] != "base"]
        for v in args.pairs:
            cm = f"{V57}_{v}cm"
            if any(r["version"] == cm for r in tr) and (cm, y) not in ok_cm:
                sys.exit(f"ERROR: {y}: tract rows of {cm} without a model check (model_from.json)")
        rows += tr
    if len(cells):
        rows += nc.cell_rows(cells)
    cmp = pd.DataFrame(rows)
    if cmp.empty or not cmp["level"].isin(["tract", "county"]).any():
        sys.exit("ERROR: no tract / county result files found for any version / year")
    cmp["city"] = np.nan  # the column of plural_v57_comparison.csv (no city rows)
    cmp.insert(cmp.columns.get_loc("set") + 1, "city", cmp.pop("city"))
    key = ["year", "level", "set"]
    ref = cmp.loc[cmp["variant"] == "v57", [*key, "mdape"]].rename(columns={"mdape": "ref_mdape"})
    cmp = cmp.merge(ref, on=key, how="left")
    cmp.insert(cmp.columns.get_loc("mape_n") + 1, "d_mdape", cmp["mdape"] - cmp.pop("ref_mdape"))
    orig = cmp[["variant", *key, "mdape"]].rename(columns={"variant": "orig", "mdape": "orig_mdape"})
    cmp["orig"] = np.where(cmp["variant"].str.endswith("cm"), cmp["variant"].str[:-2], "")
    cmp = cmp.merge(orig, on=["orig", *key], how="left")
    cmp.insert(cmp.columns.get_loc("d_mdape") + 1, "d_mdape_orig", cmp["mdape"] - cmp.pop("orig_mdape"))
    cmp = cmp.drop(columns="orig")
    if not cmp["variant"].str.endswith("cm").any():
        log.warning("no rows of the cm versions yet (not run?): the table holds v5.7 / pq5 / plc only")

    log.info("== checks: v5.7 / pq5 / plc / areal weighting = plural_v57_* (a difference stops the run)")
    plural = [f"{V57}_{v}" for v in args.pairs]
    vn.check_rows(cmp, args.prev_dir / "plural_v57_comparison.csv", [V57, *plural, pc.AREAL],
                  ["version", "year", "level", "set", "city"], CHECK_COLS, "comparison v5.7 / PLURAL", args.years)
    if len(cells):
        vn.check_rows(cells, args.prev_dir / "plural_v57_cells.csv", [V57, *plural], ["version", "year"], vn.CELL_COLS,
                      "cells v5.7 / PLURAL", args.years)
    contrast = contrast_part(args, own, cells)
    rule = rule_table(cmp, args.pairs)

    cmp.to_csv(out / "pluralcm_comparison.csv", index=False)
    if len(cells):
        cells.to_csv(out / "pluralcm_cells.csv", index=False)
    if len(contrast):
        contrast.to_csv(out / "pluralcm_built_contrast.csv", index=False)
    rule.to_csv(out / "pluralcm_rule.csv", index=False)
    mchk.to_csv(out / "pluralcm_model_check.csv", index=False)

    cols = order(args.pairs)

    def piv(t, values, index):
        tab = t.pivot_table(index=index, columns="variant", values=values, sort=False)
        return tab.reindex(columns=[c for c in cols if c in tab.columns])

    with pd.option_context("display.width", 250, "display.max_rows", 500, "display.max_columns", 40):
        c = cmp[(cmp["level"] == "county") & (cmp["set"] == "test_all")]
        if len(c):
            log.info("SUMMARY county, ALL TEST counties, before allocation (cm = its PLURAL version by construction): "
                     "R2 / MdAPE (%%):\n%s\n%s", piv(c, "r2", "year").round(3).to_string(),
                     piv(c, "mdape", "year").round(2).to_string())
        tr = cmp[cmp["level"] == "tract"]
        log.info("SUMMARY tract MdAPE (%%) by set, year and version (areal_weighting = area-proportional):\n%s",
                 piv(tr, "mdape", ["set", "year"]).round(2).to_string())
        log.info("SUMMARY tract MdAPE change vs v5.7 (points):\n%s",
                 piv(tr[tr["variant"] != pc.AREAL], "d_mdape", ["set", "year"]).round(2).to_string())
        ce = cmp[cmp["level"] == "cells"]
        if len(ce):
            log.info("SUMMARY people on cells (share_bui0 = on BUI = 0 cells / all; share_nb_of_bui0 = of those, on "
                     "NobuiltYear > 0 cells; share_bui0_nb = BUI = 0 and NobuiltYear > 0 / all):\n%s",
                     piv(ce, "share", ["set", "year"]).round(4).to_string())
        if len(contrast):
            log.info("SUMMARY built contrast, county median (10 / 90 %%) of mean weight ratios built / BUI = 0 cells:\n%s",
                     contrast[contrast["measure"].str.startswith("built_vs")].pivot_table(
                         index=["measure", "year"], columns="variant", values="median", sort=False).reindex(
                         columns=[c for c in cols if c in set(contrast["variant"])]).round(2).to_string())
        vpath = out / "pluralcm_variance_split.csv"
        if vpath.exists():
            vs = pd.read_csv(vpath)
            log.info("SUMMARY within-county share of the cell variance (variance job):\n%s",
                     vs.pivot_table(index="feature", columns="year", values="within_share", sort=False)
                     .round(4).to_string())
        else:
            log.warning("no %s (variance job not run?)", vpath)
        if len(rule):
            log.info("SUMMARY interpretation table (tract MdAPE, points):\n%s",
                     rule.drop(columns=["plural_version", "cm_version"]).round(3).to_string(index=False))
            for r in rule[rule["judged"]].itertuples():
                log.info("RULE: %s %d all tracts: v5.7 %.2f | %s %.2f | %scm %.2f -> %s (recovered %.2f)", r.pair,
                         r.year, r.mdape_v57, r.pair, r.mdape_plural, r.pair, r.mdape_cm, r.outcome, r.recovered)
            log.info("RULE: a cause check, not a selection; the user decides")
    log.info("wrote %s", out)
    log.info("DONE")
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    return {"config": cmd_config, "snapshot": cmd_snapshot, "variance": cmd_variance,
            "compare": cmd_compare}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
