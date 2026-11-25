"""Cap allocation 1980: fix each county's people on the built / undated / no_record cells first (a cap per group), then
spread each cap over the group's cells by a cell score (request docs/handoff/cap_allocation_1980_request.md;
docs/conus_plan.md "Cap allocation 1980"; background "1980 missed cells: result"). One year, CONUS, the 2010 counties
v5.7 predicts; no new dasymetric training (one small county cap model); scored on the 1980 tracts.

  run      (one job) every row strip of block_rows rows (as missed_cells.py: GHS-POP moved per column tile, groups,
           SMOD classes), the mask cells kept (~30 bytes each), then caps x scores, tract sums, group capture ->
           --out-dir. `--check` = list the inputs only (exit 1 if one is missing).
  transfer (one job) learn the county group shares from GHS in 2010 and apply them to 1940 - 2010 with each year's
           features, scored on each year's tracts (`cap_transfer:` block; section "transfer" below; request
           docs/handoff/cap_transfer_request.md) -> results/validation/conus/cap_transfer/. `--check` as above.

Definitions (= missed_cells.py; `cap_allocation:` block of configs/external_grids.yaml, cells from its `missed_cells:`):
  cells      mask = v5.7 pop_1980.tif not nodata, in a used county; groups built (BUI > 0) / undated (BUI = 0,
             NobuiltYear > 0) / no_record (BUI = 0, NobuiltYear = 0); county class = DEGURBA level 1 of missed_cells.
             The county table here must equal county_missed_1980.csv (people, shares, classes), else stop.
  allocation county c, group g, cap s_cg (the three sum to 1), P_c = census 1980:
             cell i = P_c * s_cg * score_i / sum_{j in c, g} score_j. A group without cells gets 0 and the other caps
             are scaled up (counties logged); a group whose scores sum to 0 is spread evenly over its cells (logged).
             County sums must equal P_c (rtol 1e-9), else stop.
  caps       v57             the group shares v5.7 gives (= county_missed_1980.csv v57 shares, checked)
             ghs             the GHS-POP 1980 group shares (reference upper bound, not available before 1980)
             model           two random forests (y1 = log(s_undated / s_built), y2 = log(s_no_record / s_built) of
                             GHS-POP, a 0 share -> eps, fixed before the results), fixed settings, no tuning; features
                             = the v5.7 county features 1980 + plural (county mean of the plc variant) + the county's
                             cell shares per group (HISDAC); nothing derived from GHS (no DEGURBA county class: it is
                             built on the county's own GHS-POP and there is no GHS before 1975; it only splits the
                             result tables; a GHS-derived feature name stops the run); out of fold: a train county
                             is predicted by the model fit on the other four folds of configs/conus_split.csv, every
                             other county by the model fit on all train counties; shares back by softmax (a group
                             without cells -> 0)
             model_noplural  the same without plural
  scores     v57 (v5.7 cell people), pq5 (v5.7 + PLURAL pq5), mixed (built / undated v57, no_record pq5), even,
             plural_inv (1 - PLURAL on the unbuilt groups, v57 on built; PLURAL nodata -> 0, logged)
  check      cap v57 + score v57 = v5.7: every cell = v5.7 x P_c / (v5.7 county sum) (rtol 1e-9) and within 1e-6 of
             v5.7 itself (the county sums differ from the census by < 1e-8, missed_cells log); its tract sums = the
             pop_model of v5.7's tract_errors_1980.csv (x the same county factor, rtol 1e-9); else stop.

Tracts (tract_validate.py: read_tracts, tract_ids, metrics; the evaluated tracts = flag ok of v5.7's
tract_errors_1980.csv, n_cells checked): per combination and part MdAPE / MAPE (tracts >= mape_min people) / R2 of
log(pop + 1), RMSE, MAE; parts all, train / test, dens_* (observed density, as tract_validate), kept_t070 /
excluded_t070, no_gap / gap (column gap of v5.7's file = v5.6's gap counties), city / town_suburb / rural (county class);
d_* = combination - v5.7 (the file). Reported numbers only: no selection rule (selection by county CV, the user decides).

Writes to --out-dir (results/validation/conus/cap_allocation_1980/):
  cap_model_1980.csv     cap model per variant: OOF (train counties) and TEST RMSE of y1 / y2, share MAE per group (also
                         of the v57 cap vs GHS), permutation importance (OOF folds, RMSE increase)
  caps_1980.csv          county x cap: cells and cap per group (+ the model's y1 / y2 and where it came from)
  group_shares_1980.csv  combination x county class: pooled group shares and the county gap median (GHS - combination)
  tract_metrics_1980.csv combination x part
  tract_pop_1980.csv.gz  one row per evaluated tract: v5.7 (file), observed, and every combination
  group_capture_1980.csv within-county capture of the GHS people on undated / no_record cells by score, k = ks
  tract_mdape_1980.png   tract MdAPE per combination (all + county classes), v5.7 as a line
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import Window
from rasterio.windows import transform as win_transform

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "dasymetric"))
import degurba_boxes as db  # noqa: E402
import external_city_density as ecd  # noqa: E402
import external_city_maps as ecm  # noqa: E402
import external_city_meeting as ecmt  # noqa: E402
import missed_cells as mcm  # noqa: E402
import tract_validate as tv  # noqa: E402
from external_compare import load_config, resolve  # noqa: E402
from metrics_over_time import mape  # noqa: E402

log = logging.getLogger("cap_allocation")
OUT = Path("results/validation/conus/cap_allocation_1980")
OUT_T = Path("results/validation/conus/cap_transfer")
GROUPS = mcm.GROUPS                                      # built / undated / no_record
NC, NT = mcm.NC, mcm.NT
CAPS = ("v57", "ghs", "model", "model_noplural")
SCORES = ("v57", "pq5", "mixed", "even", "plural_inv")
CLASSES = mcm.COUNTY_CLASSES
GHS_DERIVED = ("ghs", "county_class", "class_", "smod", "degurba", "bs_", "built_surface", "gap", "unbuilt_share",
               "undated_share", "no_record_share")       # name prefixes refused as cap model features
REF = "v5.7"                                             # the v5.7 file's tract numbers
_SHARED: dict = {}                                       # tract ids of the grid, inherited by the forked workers


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["run", "transfer"])
    p.add_argument("--config", type=Path, default=Path("configs/external_grids.yaml"))
    p.add_argument("--data-root", type=Path, required=True, help="$DATA_ROOT/raw/external")
    p.add_argument("--dasym-root", type=Path, required=True, help="<root>/<name>/<version>/predictions/pop_{YEAR}.tif")
    p.add_argument("--cutout-root", type=Path, required=True, help="<root>/<name>/{zones,layers}")
    p.add_argument("--census-dir", type=Path, required=True, help="counties_2010.gpkg")
    p.add_argument("--tract-dir", type=Path, required=True, help="tracts_{YEAR}.gpkg")
    p.add_argument("--hisdac-dir", type=Path, default=None, help="HISDAC-US V2 folder: FBUY/NobuiltYear.tif")
    p.add_argument("--out-dir", type=Path, default=None, help=f"default {OUT} (run) / {OUT_T} (transfer)")
    p.add_argument("--box-check", type=Path, default=mcm.BOX_CHECK, help="(missed_cells input list; not used here)")
    p.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_ON_NODE", "1")))
    p.add_argument("--block-rows", type=int, default=None, help="override the model config's block_rows (tests)")
    p.add_argument("--check", action="store_true", help="list the inputs only; exit 1 if one is missing")
    return p.parse_args(argv)


# ---------------------------------------------------------------- config and inputs

def ca_config(cfg: dict) -> dict:
    ca = cfg.get("cap_allocation")
    if not ca:
        sys.exit("ERROR: no cap_allocation block in the config")
    for k in ("missed_table", "tract_errors", "county_features", "plural_features", "split", "exclusions",
              "features", "eps", "rf", "perm_repeats", "caps", "scores", "ks", "mape_min"):
        if k not in ca:
            sys.exit(f"ERROR: cap_allocation.{k} missing")
    if not set(ca["caps"]) <= set(CAPS) or "v57" not in ca["caps"]:
        sys.exit(f"ERROR: cap_allocation.caps must be among {CAPS} and hold v57: {ca['caps']}")
    if not set(ca["scores"]) <= set(SCORES) or "v57" not in ca["scores"]:
        sys.exit(f"ERROR: cap_allocation.scores must be among {SCORES} and hold v57: {ca['scores']}")
    ca["ks"] = [float(k) for k in ca["ks"]]
    return ca


def inputs(args, cfg, mc, ca, rb, model) -> dict:
    p = mcm.inputs(args, cfg, mc, rb, model)            # the missed_cells inputs (exits on a missing one)
    year = int(mc["year"])
    extra = {"tracts": args.tract_dir / f"tracts_{year}.gpkg",
             **{k: Path(ca[k]) for k in ("missed_table", "tract_errors", "county_features", "plural_features", "split",
                                         "exclusions")}}
    for k, v in extra.items():
        log.info("  input %-15s %s%s", k, v, "" if v.exists() else "  MISSING")
    miss = [f"{k} {v}" for k, v in extra.items() if not v.exists()]
    if miss:
        sys.exit(f"ERROR: {len(miss)} inputs missing: {miss}")
    return {**p, **extra}


# ---------------------------------------------------------------- one strip

def strip_work(task):
    try:
        return _strip_work(*task)
    except BaseException as e:   # sys.exit in a pool worker would hang the pool
        raise RuntimeError(f"strip {task[0]}-{task[1]}: {type(e).__name__}: {e}") from None


def _strip_work(r0: int, r1: int, ctx: dict) -> dict:
    """missed_cells._strip_work's reads (no GHS-BUILT, no boxes), every mask cell kept."""
    gt, crs, W, n = ctx["grid_t"], ctx["crs"], ctx["width"], ctx["n_counties"]
    h = r1 - r0
    st = win_transform(Window(0, r0, W, h), gt)
    vm, mask = mcm.read_rows(ctx["v57"], r0, r1, gt, W)
    with rasterio.open(ctx["zones"]) as src:
        zones = src.read(1, window=Window(0, r0, W, h)).astype(np.int64)
    ci = ctx["lut"][zones]
    m = mask & (ci >= 0)
    info = {"mask_cells_no_county": int((mask & (ci < 0)).sum())}
    v57 = np.where(mask, vm, 0.0)
    a, valid = mcm.read_rows(ctx["pq5"], r0, r1, gt, W)
    info["pq5_mask_cells_without_value"] = int((mask & ~valid).sum())
    pq5 = np.where(mask & valid, a, 0.0)
    bui, bvalid = mcm.read_rows(ctx["bui"], r0, r1, gt, W)
    info["bui_nodata_in_mask"] = int((m & ~bvalid).sum())
    bui = np.where(bvalid, bui, -1.0)
    nb = ecmt.read_on_box(ctx["nobuilt"], st, (h, W), crs)
    ctype = ecd.cell_types(bui, nb)
    cls, _ = mcm.cell_classes(ctx["smod"], st, (h, W), crs, ctx["rb"])
    ghs = mcm.product_rows(ctx["ghs_pop"], r0, r1, gt, crs, W, ctx["tile_cols"], ctx["subpixel_m"])
    idx = (ci * (NC * NT) + cls * NT + ctype)[m]
    L = n * NC * NT
    acc = {"cells": np.bincount(idx, minlength=L).astype(np.int64), "bs": np.zeros(L),
           "ghs": np.bincount(idx, weights=ghs[m], minlength=L),
           "v57": np.bincount(idx, weights=v57[m], minlength=L), "pq5": np.bincount(idx, weights=pq5[m], minlength=L)}
    pl, pvalid = mcm.read_rows(ctx["plural"], r0, r1, gt, W)
    tid = _SHARED["tid"][r0:r1]
    info["tract_cells_outside_mask"] = int(((tid > 0) & ~m).sum())
    cells = {"ci": ci[m].astype(np.int32), "grp": ctype[m].astype(np.int8), "v57": v57[m].astype(np.float32),
             "pq5": pq5[m].astype(np.float32), "plural": np.where(pvalid, pl, np.nan)[m].astype(np.float32),
             "ghs": ghs[m], "nobuilt": nb[m].astype(np.float32), "tid": tid[m].astype(np.int32)}
    return {"rows": (r0, r1), "acc": acc, "info": info, "cells": cells}


def run_strips(ctx: dict, rows: list, workers: int, fn=None):
    fn = fn or strip_work
    tasks = [(r.start, r.stop, ctx) for r in rows]
    if workers <= 1:
        yield from map(fn, tasks)
        return
    import multiprocessing as mp
    with mp.get_context("fork").Pool(workers) as pool:
        yield from pool.imap(fn, tasks)


# ---------------------------------------------------------------- caps

def group_sums(acc: dict, key: str, n: int) -> np.ndarray:
    """(n, 3) per county and group (summed over the cell classes)."""
    return acc[key].reshape(n, NC, NT).sum(axis=1)


def row_shares(a: np.ndarray) -> np.ndarray:
    t = a.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(t > 0, a / np.where(t > 0, t, 1), np.nan)


def log_ratios(s: np.ndarray, eps: float) -> np.ndarray:
    """(n, 2): y1 = log(s_undated / s_built), y2 = log(s_no_record / s_built), a 0 share -> eps."""
    c = np.maximum(s, eps)
    return np.log(c[:, 1:] / c[:, :1])


def softmax_shares(y: np.ndarray, has: np.ndarray) -> np.ndarray:
    """(n, 3) shares from (n, 2) log ratios against built; a group without cells (has False) -> 0, sum 1."""
    z = np.column_stack([np.zeros(len(y)), y])
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z) * has
    t = e.sum(axis=1, keepdims=True)
    return np.where(t > 0, e / np.where(t > 0, t, 1), np.nan)


def fit_rf(X, y, rf: dict, n_jobs: int):
    from sklearn.ensemble import RandomForestRegressor
    return RandomForestRegressor(**rf, n_jobs=n_jobs).fit(X, y)


def oof_predict(X: np.ndarray, Y: np.ndarray, fold: np.ndarray, fit_rows: np.ndarray, rf: dict, n_jobs: int,
                perm_repeats: int = 0, seed: int = 42):
    """Out-of-fold predictions of the two targets. A row with fold >= 0 (a train county) is predicted by the models fit
    on the fit_rows of the other folds; every other row (TEST, outside the split) by the models fit on all fit_rows
    with fold >= 0. fit_rows = rows with a target. Returns (pred (n, 2), how (n,), permutation importance (2, f): the
    RMSE increase on each held-out fold's fit rows, weighted by their count; NaN without perm_repeats)."""
    from sklearn.inspection import permutation_importance
    n, f = X.shape
    pred = np.full((n, Y.shape[1]), np.nan)
    how = np.where(fold >= 0, "oof", "all_train").astype(object)
    imp, wsum = np.zeros((Y.shape[1], f)), 0
    for k in sorted(set(fold[fold >= 0].tolist())):
        tr, te = fit_rows & (fold >= 0) & (fold != k), fold == k
        if not tr.any():
            sys.exit(f"ERROR: cap model: no rows to fit for fold {k}")
        ev = te & fit_rows
        for j in range(Y.shape[1]):
            m = fit_rf(X[tr], Y[tr, j], rf, n_jobs)
            pred[te, j] = m.predict(X[te])
            if perm_repeats and ev.any():
                pi = permutation_importance(m, X[ev], Y[ev, j], scoring="neg_root_mean_squared_error",
                                            n_repeats=perm_repeats, random_state=seed)  # the forest threads
                imp[j] += pi.importances_mean * ev.sum()
        wsum += int(ev.sum())
    rest = fold < 0
    if rest.any():
        tr = fit_rows & (fold >= 0)
        for j in range(Y.shape[1]):
            pred[rest, j] = fit_rf(X[tr], Y[tr, j], rf, n_jobs).predict(X[rest])
    return pred, how, (imp / wsum if perm_repeats and wsum else np.full((Y.shape[1], f), np.nan))


def ghs_derived(cols) -> list:
    """Columns made from GHS (POP / SMOD / BUILT) or the county class built on them: never cap model features (the
    target's own information; no GHS before 1975)."""
    return [c for c in cols if any(str(c).lower().startswith(p) for p in GHS_DERIVED)]


def county_design(ct: pd.DataFrame, cf: pd.DataFrame, pf: pd.DataFrame | None, feats: list,
                  cnt: np.ndarray) -> pd.DataFrame:
    """Feature table in the order of ct: county features, plural (not with pf = None: transfer), cell shares per
    group (HISDAC). No GHS-derived column (the DEGURBA county class only splits the result tables)."""
    bad = ghs_derived(feats)
    if bad:
        sys.exit(f"ERROR: cap model features derived from GHS: {bad}")
    key = ct[["GISJOIN"]]
    a = key.merge(cf[["GISJOIN", *feats]], on="GISJOIN", how="left")
    X = a[feats].copy()
    if pf is not None:
        X["plural"] = key.merge(pf[["GISJOIN", "plural"]], on="GISJOIN", how="left")["plural"].to_numpy()
    tot = cnt.sum(axis=1)
    for i, g in enumerate(GROUPS):
        X[f"cells_{g}"] = np.where(tot > 0, cnt[:, i] / np.where(tot > 0, tot, 1), 0.0)
    assert not ghs_derived(X.columns), ghs_derived(X.columns)
    bad = X.columns[X.isna().any()].tolist()
    if bad:
        miss = ct.loc[X.isna().any(axis=1).to_numpy(), "GISJOIN"].head(10).tolist()
        sys.exit(f"ERROR: cap model features missing / NaN in {bad} (counties e.g. {miss})")
    return X


def cap_model(ct, X: pd.DataFrame, s_ghs, cnt, fold, part, ca, n_jobs):
    """Model caps (model, model_noplural) and the rows of cap_model_1980.csv."""
    eps = float(ca["eps"])
    has = cnt > 0
    target = np.isfinite(s_ghs).all(axis=1)
    Y = np.where(target[:, None], log_ratios(np.nan_to_num(s_ghs), eps), np.nan)
    caps, extra, rows = {}, {}, []
    sets = {"oof_train": (fold >= 0) & target, "test": (part == "test") & target}
    for variant, cols in (("model", list(X.columns)), ("model_noplural", [c for c in X.columns if c != "plural"])):
        t0 = time.time()
        pred, how, imp = oof_predict(X[cols].to_numpy(float), Y, fold, target, ca["rf"], n_jobs,
                                     int(ca["perm_repeats"]), int(ca["rf"].get("random_state", 42)))
        s = softmax_shares(pred, has)
        caps[variant], extra[variant] = s, (pred, how)
        for sname, sel in sets.items():
            for j, tname in enumerate(("y1", "y2")):
                rows.append({"variant": variant, "set": sname, "metric": "rmse", "target": tname, "n": int(sel.sum()),
                             "value": float(np.sqrt(np.mean((pred[sel, j] - Y[sel, j]) ** 2)))})
            for i, g in enumerate(GROUPS):
                rows.append({"variant": variant, "set": sname, "metric": "share_mae", "target": g, "n": int(sel.sum()),
                             "value": float(np.mean(np.abs(s[sel, i] - s_ghs[sel, i])))})
        for j, tname in enumerate(("y1", "y2")):
            for fi, c in enumerate(cols):
                rows.append({"variant": variant, "set": "oof_train", "metric": "perm_rmse_increase", "target": tname,
                             "feature": c, "n": int(sets["oof_train"].sum()), "value": float(imp[j, fi])})
        log.info("  cap model %s: %d features, %.0f s; OOF RMSE y1 %.3f y2 %.3f (%d train counties), TEST y1 %.3f "
                 "y2 %.3f (%d)", variant, len(cols), time.time() - t0,
                 *(r["value"] for r in rows if r["variant"] == variant and r["set"] == "oof_train"
                   and r["metric"] == "rmse"), int(sets["oof_train"].sum()),
                 *(r["value"] for r in rows if r["variant"] == variant and r["set"] == "test" and r["metric"] == "rmse"),
                 int(sets["test"].sum()))
    return caps, extra, rows, sets, Y


# ---------------------------------------------------------------- allocation

def cell_scores(c: dict, name: str) -> np.ndarray:
    grp = c["grp"]
    if name == "v57":
        return c["v57"].astype(np.float64)
    if name == "pq5":
        return c["pq5"].astype(np.float64)
    if name == "mixed":
        return np.where(grp == 2, c["pq5"], c["v57"]).astype(np.float64)
    if name == "even":
        return np.ones(len(grp))
    if name == "plural_inv":
        pi = 1.0 - c["plural"].astype(np.float64)
        return np.where(grp == 0, c["v57"].astype(np.float64), np.clip(np.nan_to_num(pi, nan=0.0), 0.0, None))
    if name == "pq5_unbuilt":                              # transfer: built v57, undated / no_record pq5
        return np.where(grp == 0, c["v57"], c["pq5"]).astype(np.float64)
    raise ValueError(name)


def allocate(ci: np.ndarray, grp: np.ndarray, P: np.ndarray, S: np.ndarray, score: np.ndarray, n: int):
    """cell = P_c x s_cg x score_i / sum_{c,g} score. Returns (cells, info)."""
    key = ci.astype(np.int64) * NT + grp
    cnt = np.bincount(key, minlength=n * NT).reshape(n, NT)
    S = np.nan_to_num(np.asarray(S, float))
    dropped = ((cnt == 0) & (S > 0)).any(axis=1)
    S = np.where(cnt > 0, S, 0.0)
    rs = S.sum(axis=1)
    if ((rs <= 0) & (cnt.sum(axis=1) > 0) & (P > 0)).any():
        bad = np.flatnonzero((rs <= 0) & (cnt.sum(axis=1) > 0) & (P > 0))
        sys.exit(f"ERROR: allocation: {len(bad)} counties with people and cells but no cap on any group with cells")
    S = S / np.where(rs > 0, rs, 1)[:, None]
    ssum = np.bincount(key, weights=score, minlength=n * NT)
    zero = (ssum <= 0) & (cnt.ravel() > 0)
    w = np.where(zero[key], 1.0 / np.maximum(cnt.ravel()[key], 1), score / np.where(zero, 1.0, ssum)[key])
    cells = P[ci] * S.ravel()[key] * w
    info = {"counties_renormalized": int(dropped.sum()), "groups_even_zero_score": int(zero.sum()),
            "counties_even_zero_score": int(zero.reshape(n, NT).any(axis=1).sum())}
    return cells, info


def check_county_sums(ci, cells, P, n, what):
    s = np.bincount(ci, weights=cells, minlength=n)
    d = np.abs(s - P) / np.where(P > 0, P, 1)
    if not (d < 1e-9).all():
        sys.exit(f"ERROR: {what}: county sums != census in {int((d >= 1e-9).sum())} counties (max {d.max():.2e})")
    return float(d.max())


# ---------------------------------------------------------------- tracts

def tract_parts(tr: pd.DataFrame, excl: set, cclass: dict) -> dict:
    dens = (tr["pop_obs"] / (tr["n_cells"] * tv.CELL_KM2)).to_numpy()
    parts = {"all": np.ones(len(tr), bool)}
    for p in ("train", "test"):
        parts[p] = (tr["part"] == p).to_numpy()
    for lo, hi in tv.DENSITY_CLASSES:
        parts[tv.density_label(lo, hi)] = (dens >= lo) & (dens < (np.inf if hi is None else hi))
    inside = tr["zone_gisjoin"].isin(excl).to_numpy()
    parts.update({"kept_t070": ~inside, "excluded_t070": inside})
    if "gap" in tr:
        g = (tr["gap"].astype(str).str.lower() == "true").to_numpy()
        parts.update({"no_gap": ~g, "gap": g})
    cc = tr["zone_gisjoin"].map(cclass).to_numpy()
    for c in CLASSES:
        parts[c] = cc == c
    return parts


def tract_rows(name: str, cap: str, score: str, tr: pd.DataFrame, est: np.ndarray, parts: dict, mape_min: float):
    obs, nc = tr["pop_obs"].to_numpy(float), tr["n_cells"].to_numpy(float)
    rows = []
    for part, m in parts.items():
        r = tv.metrics(obs[m], est[m], nc[m] * tv.CELL_KM2)
        rows.append({"combination": name, "cap": cap, "score": score, "part": part, "n": int(m.sum()),
                     "counties": int(tr["zone_gisjoin"][m].nunique()), **r,
                     "mape": mape(obs[m], est[m], mape_min), "mape_n": int((obs[m] >= mape_min).sum())})
    return rows


# ---------------------------------------------------------------- group capture

def group_capture(c: dict, ct: pd.DataFrame, ks: list) -> pd.DataFrame:
    """Within-county capture of the GHS people on the undated / no_record cells by score (missed_cells.capture)."""
    n = len(ct)
    cc = ct["county_class"].to_numpy()
    subsets = {"all": np.ones(n, bool), **{k: cc == k for k in CLASSES}}
    rows = []
    for gi, g in ((1, "undated"), (2, "no_record")):
        sel = c["grp"] == gi
        ci = c["ci"][sel].astype(np.int64)
        ghs = c["ghs"][sel]
        G = np.bincount(ci, weights=ghs, minlength=n)
        ncell = np.bincount(ci, minlength=n)
        sc = {"ghs": ghs, "v57": c["v57"][sel].astype(np.float64), "pq5": c["pq5"][sel].astype(np.float64),
              "plural_inv": 1.0 - c["plural"][sel].astype(np.float64)}
        if g == "undated":
            sc["nobuilt"] = c["nobuilt"][sel].astype(np.float64)
        sc["even"] = np.zeros(len(ci))                     # one tie run per county = the expected value = k
        for name, s in sc.items():
            cap = mcm.capture(ci, s, ghs, ks, n)
            for sub, m in subsets.items():
                for j, k in enumerate(ks):
                    rows.append({"group": g, "subset": sub, "ranking": "within_county", "metric": "capture",
                                 "score": name, "k": k, "value": float(cap[m, j].sum() / G[m].sum())
                                 if G[m].sum() > 0 else np.nan, "n_counties": int((m & (ncell > 0)).sum()),
                                 "n_cells": int(m[ci].sum()), "n_cells_no_score": int((m[ci] & ~np.isfinite(s)).sum()),
                                 "ghs_pop": float(G[m].sum())})
    t = pd.DataFrame(rows)
    for g, d in t.groupby("group"):
        mcm.check_capture(d)
        e = d[d["score"] == "even"].dropna(subset=["value"])
        if not np.allclose(e["value"], e["k"]):
            sys.exit(f"ERROR: group capture {g}: even != k")
    return t


# ---------------------------------------------------------------- tables

def pooled_shares(name, cap, score, G: np.ndarray, ghs_G: np.ndarray, cc: np.ndarray) -> list[dict]:
    """G (n, 3) people per county and group of a combination; pooled shares per county class + county gap median."""
    rows = []
    for sub in ("all", *CLASSES):
        m = np.ones(len(cc), bool) if sub == "all" else cc == sub
        tot = G[m].sum()
        r = {"combination": name, "cap": cap, "score": score, "county_class": sub, "n_counties": int(m.sum()),
             "pop": float(tot)}
        for i, g in enumerate(GROUPS):
            r[f"share_{g}"] = float(G[m, i].sum() / tot) if tot > 0 else np.nan
        r["share_unbuilt"] = r["share_undated"] + r["share_no_record"]
        u = row_shares(G[m])[:, 1:].sum(axis=1)
        ug = row_shares(ghs_G[m])[:, 1:].sum(axis=1)
        gap = ug - u
        r["gap_median"] = float(np.nanmedian(gap)) if np.isfinite(gap).any() else np.nan
        rows.append(r)
    return rows


def check_missed(ct: pd.DataFrame, path: Path, year: int):
    old = pd.read_csv(path)
    if list(old["GISJOIN"]) != list(ct["GISJOIN"]):
        sys.exit(f"ERROR: {path}: other counties / order than here")
    for c in ("county_class", "n_cells_built", "n_cells_undated", "n_cells_no_record"):
        if not (old[c].astype(str).to_numpy() == ct[c].astype(str).to_numpy()).all():
            sys.exit(f"ERROR: {path}: column {c} differs from here")
    cols = [f"census_pop_{year}", "ghs_share_urban_centre", "ghs_share_rural"] + [
        f"{a}_{k}" for k in ("ghs", "v57", "pq5") for a in ("pop", "unbuilt_share", "undated_share", "no_record_share")]
    for c in cols:
        a, b = ct[c].to_numpy(float), old[c].to_numpy(float)
        if not np.allclose(a, b, rtol=1e-9, atol=1e-9, equal_nan=True):
            i = int(np.flatnonzero(~np.isclose(a, b, rtol=1e-9, atol=1e-9, equal_nan=True))[0])
            sys.exit(f"ERROR: {path}: {c} of {ct['GISJOIN'].iloc[i]}: {a[i]} here, {b[i]} there")
    log.info("  MATCH %s: %d counties x %d columns (classes, cells, people and group shares of GHS / v5.7 / pq5)", path,
             len(ct), len(cols) + 4)


# ---------------------------------------------------------------- figure

def draw(path: Path, tm: pd.DataFrame, caps: list, scores: list, year: int):
    plots = ecm._plots()
    plt = plots.plt
    panels = ["all", *CLASSES]
    fig = plt.figure(figsize=(16.0, 4.8), dpi=150, layout="constrained")
    axes = fig.subplots(1, len(panels), sharey=True)
    for ax, part in zip(axes, panels):
        d = tm[tm["part"] == part]
        ref = d[d["combination"] == REF]
        if ref.empty or not ref["n"].iloc[0]:
            ax.text(0.5, 0.5, f"no tracts in {part.replace('_', ' / ')} counties", transform=ax.transAxes,
                    ha="center", fontsize=9, color=plots.MUTED)
            ax.set_axis_off()
            continue
        ax.axhline(ref["mdape"].iloc[0], color=plots.MUTED, lw=1.2, ls="--", label="v5.7")
        for i, cap in enumerate(caps):
            r = d[d["cap"] == cap].set_index("score").reindex(scores)
            x = np.arange(len(scores)) + (i - (len(caps) - 1) / 2) * 0.16
            ax.plot(x, r["mdape"], ls="none", marker="o", ms=6, color=plots.SERIES[i % len(plots.SERIES)],
                    label=f"cap {cap}")
        ax.set_xticks(range(len(scores)), [s.replace("_", " ") for s in scores], fontsize=7.5)
        ax.set_title(f"{part.replace('_', ' / ')}: {int(ref['n'].iloc[0])} tracts, {int(ref['counties'].iloc[0])} "
                     "counties", fontsize=9, color=plots.INK)
        ax.set_xlabel("score inside the cap", fontsize=8, color=plots.INK)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color=plots.GRID, lw=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(labelsize=7.5, colors=plots.INK)
    axes[0].set_ylabel("tract MdAPE, %", fontsize=8, color=plots.INK)
    h, lab = axes[0].get_legend_handles_labels()
    fig.legend(h, lab, loc="outside lower center", ncol=len(lab), fontsize=8, frameon=False)
    fig.suptitle(f"{year} tracts: county caps per cell group (built / undated / no record) x score inside the cap; "
                 "county classes by DEGURBA level 1", fontsize=9.5, color=plots.INK)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    log.info("  wrote %s", path)


# ---------------------------------------------------------------- run

def run(args, cfg, mc, ca, rb):
    import common
    t_start = time.time()
    year = int(mc["year"])
    model = mcm.model_settings(Path(mc["model_config"]))
    if model["version"] != mc["maps"][mc["mask_map"]]:
        sys.exit(f"ERROR: {mc['model_config']} is {model['version']}, the mask map is {mc['maps'][mc['mask_map']]}")
    if "pq5" not in mc["maps"]:
        sys.exit("ERROR: missed_cells.maps has no pq5")
    args.name = model["name"]
    p = inputs(args, cfg, mc, ca, rb, model)
    block_rows = int(args.block_rows or model.get("block_rows") or 0)
    if not block_rows or block_rows % mcm.F:
        sys.exit(f"ERROR: block_rows {block_rows}: needs a multiple of {mcm.F}")
    if args.check:
        log.info("CHECK OK: inputs for %d, caps %s x scores %s, block_rows %d", year, ca["caps"], ca["scores"],
                 block_rows)
        return 0
    eps = float(ca["eps"])
    log.info("RULE allocation: cell = P_c x cap_cg x score_i / sum of the scores of county c, group g (P_c = census "
             "%d); a group without cells -> cap 0, the others scaled up; scores summing to 0 -> even; groups as "
             "missed_cells (built BUI > 0 / undated NobuiltYear > 0 / no_record)", year)
    log.info("RULE cap model: y1 = log(s_undated / s_built), y2 = log(s_no_record / s_built) of GHS-POP %d, a 0 share "
             "-> eps = %g (fixed before the results); random forests %s (fixed, no tuning); out of fold on the folds "
             "of %s", year, eps, ca["rf"], ca["split"])
    log.info("RULE tracts: reported only, no selection rule (selection by county CV; the user decides)")
    rule = mc["county_rule"]
    used, lut = mcm.counties(p, model, year)
    n = len(used)
    with rasterio.open(p[f"map_{mc['mask_map']}"]) as src:
        grid_t, crs, (H, W) = src.transform, src.crs, src.shape
    grid = {"transform": grid_t, "crs": crs, "shape": (H, W)}
    with rasterio.open(p["zones"]) as src:
        if src.transform != grid_t or src.shape != (H, W):
            sys.exit("ERROR: zones are not on the grid of the mask map")
    # tracts on the grid (tract_validate's rasterization), checked against v5.7's file
    t0 = time.time()
    tracts = tv.read_tracts(p["tracts"], grid, "")
    tid = tv.tract_ids(tracts, grid)
    _SHARED["tid"] = tid
    te = pd.read_csv(p["tract_errors"])
    tr = te[te["flag"] == "ok"].reset_index(drop=True)
    pos = pd.Series(np.arange(1, len(tracts) + 1), index=tracts["GISJOIN"].to_numpy())
    if not tr["GISJOIN"].isin(pos.index).all():
        sys.exit(f"ERROR: {p['tract_errors']}: evaluated tracts missing from {p['tracts']}")
    tpos = pos.loc[tr["GISJOIN"]].to_numpy()
    ncell_t = np.bincount(tid.ravel(), minlength=len(tracts) + 1)
    if not (ncell_t[tpos] == tr["n_cells"].to_numpy()).all():
        sys.exit(f"ERROR: tract cells here != n_cells of {p['tract_errors']}")
    log.info("tracts %d: %d in %s, %d evaluated (flag ok) in %d counties; cells per tract = the file (%.0f s)", year,
             len(tracts), p["tracts"].name, len(tr), tr["zone_gisjoin"].nunique(), time.time() - t0)
    ctx = {"grid_t": grid_t, "crs": crs, "width": W, "n_counties": n, "lut": lut, "zones": p["zones"],
           "v57": p[f"map_{mc['mask_map']}"], "pq5": p["map_pq5"], "bui": p["bui"], "nobuilt": p["nobuilt"],
           "smod": p["smod"], "rb": rb, "ghs_pop": p["ghs_pop"], "plural": p["plural"],
           "tile_cols": int(mc["tile_cols"]), "subpixel_m": cfg["city_maps"]["subpixel_m"]}
    rows = common.strips((H, W), block_rows)
    log.info("grid %d x %d, %d strips of %d rows, %d workers, %d counties", H, W, len(rows), block_rows, args.workers, n)
    acc, info, cl = None, {}, []
    for res in run_strips(ctx, rows, args.workers):
        acc = res["acc"] if acc is None else {k: acc[k] + v for k, v in res["acc"].items()}
        for k, v in res["info"].items():
            info[k] = info.get(k, 0) + v
        cl.append(res["cells"])
        log.info("  strip rows %d-%d done", *res["rows"])
    c = {k: np.concatenate([u[k] for u in cl]) for k in cl[0]}
    del cl
    _SHARED.clear()
    del tid
    log.info("cells kept %d (built %d, undated %d, no_record %d); %s", len(c["ci"]), *(int((c["grp"] == i).sum())
                                                                                      for i in range(3)), info)
    ct = mcm.county_table(used, acc, np.zeros(n), ["v57", "pq5"], rule, year)
    log.info("checks (a difference stops the run before writing):")
    mcm.check_census(ct, year)
    check_missed(ct, p["missed_table"], year)
    P = ct[f"census_pop_{year}"].to_numpy(float)
    cnt = group_sums(acc, "cells", n).astype(np.int64)
    s_v57 = row_shares(group_sums(acc, "v57", n))
    s_ghs = row_shares(group_sums(acc, "ghs", n))
    cc = ct["county_class"].to_numpy()
    # split + caps
    split = pd.read_csv(p["split"])
    sp = ct[["GISJOIN"]].merge(split[["GISJOIN", "part", "fold"]], on="GISJOIN", how="left")
    fold = sp["fold"].fillna(-1).astype(int).to_numpy()
    part = sp["part"].fillna("none").to_numpy()
    fold = np.where(part == "train", fold, -1)
    log.info("split %s: counties %s; train folds %s", p["split"], pd.Series(part).value_counts().to_dict(),
             pd.Series(fold[fold >= 0]).value_counts().sort_index().to_dict())
    cf, pf = pd.read_csv(p["county_features"]), pd.read_csv(p["plural_features"])
    cf, pf = cf[cf["year"] == year], pf[pf["year"] == year]
    X = county_design(ct, cf, pf, list(ca["features"]), cnt)
    log.info("cap model features (%d): %s; counties with a group without cells: %d", X.shape[1], list(X.columns),
             int((cnt == 0).any(axis=1).sum()))
    caps = {"v57": s_v57}
    no_ghs = ~np.isfinite(s_ghs).all(axis=1)
    caps["ghs"] = np.where(no_ghs[:, None], s_v57, s_ghs)
    log.info("  cap ghs: %d counties without GHS people take the v57 cap", int(no_ghs.sum()))
    model_caps, extra, cm_rows, sets, Y = cap_model(ct, X, s_ghs, cnt, fold, part, ca, args.workers)
    caps.update(model_caps)
    for sname, sel in sets.items():
        for i, g in enumerate(GROUPS):
            cm_rows.append({"variant": "v57", "set": sname, "metric": "share_mae", "target": g, "n": int(sel.sum()),
                            "value": float(np.mean(np.abs(s_v57[sel, i] - s_ghs[sel, i])))})
    caps = {k: v for k, v in caps.items() if k in ca["caps"]}
    # caps table
    crow = []
    for cap, s in caps.items():
        d = ct[["GISJOIN", "state", "name", "county_class"]].copy()
        d["part"], d["fold"], d["cap"] = part, fold, cap
        for i, g in enumerate(GROUPS):
            d[f"n_cells_{g}"] = cnt[:, i]
        for i, g in enumerate(GROUPS):
            d[f"share_{g}"] = s[:, i]
        if cap in extra:
            d["y1"], d["y2"], d["pred_from"] = extra[cap][0][:, 0], extra[cap][0][:, 1], extra[cap][1]
        elif cap == "ghs":
            d["y1"], d["y2"] = Y[:, 0], Y[:, 1]
        crow.append(d)
    caps_t = pd.concat(crow, ignore_index=True)
    # allocations
    ci = c["ci"].astype(np.int64)
    key = ci * NT + c["grp"]
    T = np.bincount(ci, weights=c["v57"].astype(np.float64), minlength=n)
    fac = np.where(T > 0, P / np.where(T > 0, T, 1), 0.0)
    nt = int(c["tid"].max()) + 1 if len(c["tid"]) else 1
    nt = max(nt, len(tracts) + 1)
    cidx = ct.reset_index().set_index("GISJOIN")["index"]
    tzone = cidx.reindex(tr["zone_gisjoin"]).to_numpy()
    if np.isnan(tzone.astype(float)).any():
        sys.exit("ERROR: evaluated tracts in counties not used here")
    tzone = tzone.astype(np.int64)
    excl = set(pd.read_csv(p["exclusions"])["GISJOIN"])
    parts = tract_parts(tr, excl, dict(zip(ct["GISJOIN"], cc)))
    for k in ("all", *CLASSES):
        log.info("  tract part %-12s %6d tracts in %4d counties", k, int(parts[k].sum()),
                 tr["zone_gisjoin"][parts[k]].nunique())
    tm = tract_rows(REF, REF, REF, tr, tr["pop_model"].to_numpy(float), parts, float(ca["mape_min"]))
    tpop = tr[["GISJOIN", "zone_gisjoin", "part", *(["gap"] if "gap" in tr else []), "n_cells", "pop_obs"]].copy()
    tpop["county_class"] = cc[tzone]
    tpop[REF] = tr["pop_model"].to_numpy(float)
    ghs_G = group_sums(acc, "ghs", n)
    gs = pooled_shares("GHS-POP", "ghs_pop", "ghs_pop", ghs_G, ghs_G, cc)
    gs += pooled_shares(REF, REF, REF, group_sums(acc, "v57", n), ghs_G, cc)
    alloc_info = []
    log.info("combinations %d caps x %d scores:", len(caps), len(ca["scores"]))
    for cap, S in caps.items():
        for score in ca["scores"]:
            name = f"{cap}+{score}"
            sc = cell_scores(c, score)
            cells, ainfo = allocate(ci, c["grp"], P, S, sc, n)
            dmax = check_county_sums(ci, cells, P, n, name)
            if cap == "v57" and score == "v57":
                v = c["v57"].astype(np.float64)
                if not np.allclose(cells, v * fac[ci], rtol=1e-9, atol=1e-9):
                    sys.exit("ERROR: cap v57 + score v57 != v5.7 x P_c / v5.7 county sum")
                if not np.allclose(cells, v, rtol=1e-6, atol=1e-6):
                    sys.exit("ERROR: cap v57 + score v57 != v5.7 (rtol 1e-6)")
                rel = float(np.max(np.abs(cells - v) / np.maximum(v, 1e-12), initial=0.0))
                log.info("  MATCH cap v57 + score v57 = v5.7 cells x P_c / county sum (rtol 1e-9); max relative "
                         "difference to v5.7 itself %.2e", rel)
            ts = np.bincount(c["tid"], weights=cells, minlength=nt)[tpos]
            if cap == "v57" and score == "v57":
                want = tr["pop_model"].to_numpy(float) * fac[tzone]
                if not np.allclose(ts, want, rtol=1e-9, atol=1e-6):
                    i = int(np.flatnonzero(~np.isclose(ts, want, rtol=1e-9, atol=1e-6))[0])
                    sys.exit(f"ERROR: tract {tr['GISJOIN'].iloc[i]}: cap v57 + score v57 {ts[i]}, v5.7 file "
                             f"{tr['pop_model'].iloc[i]} x {fac[tzone[i]]}")
                d = np.abs(ts - tr["pop_model"].to_numpy(float)) / np.maximum(tr["pop_model"].to_numpy(float), 1e-12)
                log.info("  MATCH %s: %d tract sums of cap v57 + score v57 = pop_model x the county factor (rtol "
                         "1e-9); max relative difference to pop_model %.2e", p["tract_errors"], len(tr), float(d.max()))
            tpop[name] = ts
            tm += tract_rows(name, cap, score, tr, ts, parts, float(ca["mape_min"]))
            G = np.bincount(key, weights=cells, minlength=n * NT).reshape(n, NT)
            gs += pooled_shares(name, cap, score, G, ghs_G, cc)
            alloc_info.append({"combination": name, **ainfo, "county_sum_max_rel": dmax})
            log.info("  %-26s county sums = census (max %.1e); %s", name, dmax, ainfo)
    tm = pd.DataFrame(tm)
    ref = tm[tm["combination"] == REF].set_index("part")
    for k in ("mdape", "mape", "r2_log"):
        tm[f"d_{k}"] = tm[k].to_numpy() - ref.loc[tm["part"], k].to_numpy()
    gc = group_capture(c, ct, ca["ks"])
    log.info("  group capture: the GHS score >= every other score, even = k (undated / no_record x 4 subsets)")
    # write
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(cm_rows).to_csv(out / f"cap_model_{year}.csv", index=False)
    caps_t.to_csv(out / f"caps_{year}.csv", index=False)
    gst = pd.DataFrame(gs)
    gst.to_csv(out / f"group_shares_{year}.csv", index=False)
    tm.to_csv(out / f"tract_metrics_{year}.csv", index=False)
    tpop.to_csv(out / f"tract_pop_{year}.csv.gz", index=False, float_format="%.4f")
    gc.to_csv(out / f"group_capture_{year}.csv", index=False)
    draw(out / f"tract_mdape_{year}.png", tm, list(caps), list(ca["scores"]), year)
    with pd.option_context("display.width", 250, "display.max_rows", 400, "display.max_columns", 40):
        cmt = pd.DataFrame(cm_rows)
        a = cmt[cmt["metric"] != "perm_rmse_increase"]
        log.info("SUMMARY cap model (county CV; share MAE vs GHS-POP):\n%s",
                 a.pivot_table(index=["variant", "set"], columns=["metric", "target"], values="value").round(4)
                 .to_string())
        imp = cmt[cmt["metric"] == "perm_rmse_increase"]
        log.info("SUMMARY cap model permutation importance (OOF, RMSE increase):\n%s",
                 imp.pivot_table(index="feature", columns=["variant", "target"], values="value", sort=False)
                 .round(4).to_string())
        log.info("SUMMARY pooled group shares by county class (score does not change them):\n%s",
                 gst[gst["score"].isin([REF, "ghs_pop", "v57"])][["combination", "county_class", "n_counties",
                                                                   "share_built", "share_undated", "share_no_record",
                                                                   "share_unbuilt", "gap_median"]]
                 .round(4).to_string(index=False))
        piv = tm.pivot_table(index="combination", columns="part", values="mdape", sort=False)
        log.info("SUMMARY tract MdAPE %% by part:\n%s", piv.round(2).to_string())
        log.info("SUMMARY tract n / counties by part:\n%s",
                 tm[tm["combination"] == REF][["part", "n", "counties"]].to_string(index=False))
        piv = tm.pivot_table(index="combination", columns="part", values="d_mdape", sort=False)
        log.info("SUMMARY tract d_mdape (combination - v5.7) by part:\n%s", piv.round(2).to_string())
        g = gc[gc["subset"] == "all"].pivot_table(index=["group", "score"], columns="k", values="value")
        log.info("SUMMARY group capture (all counties, share of GHS people of the group in the top k %% of its "
                 "cells):\n%s", g.round(4).to_string())
    log.info("wrote %s (6 tables + 1 PNG), %.0f s", out, time.time() - t_start)
    log.info("DONE")
    return 0


# ================================================================ transfer
# Learn "county features -> group shares" where GHS is close to its sources (GHS-POP 2010 people: GPWv4.11 = the 2010
# census; GHS-BUILT-S residential surface of the epoch next to the 2014 Landsat observation), apply it to earlier years
# with that year's features, score on that year's tracts (request docs/handoff/cap_transfer_request.md;
# docs/conus_plan.md "Cap transfer (learn 2010, apply 1940-1980)"). The `run` mode above (1980) is unchanged.
#
#   transfer  (one job) per year (the learn year first) every row strip: v5.7 cells of the year (mask, people), groups
#             (BUI_year, NobuiltYear), PLURAL / pq5 (plural_years only), tract ids; in the learn year also GHS-POP and
#             GHS-BUILT-S total / non-residential moved to our cells (as missed_cells). Then caps per method x scores
#             inside the groups, tract sums, checks -> --out-dir. `--check` = list the inputs only.
#
# Targets (learn year, HISDAC groups of the learn year): P = GHS-POP group shares, B = residential built-up surface
#   (total - NRES, a negative cell -> 0, logged; total alone if NRES is missing, logged) group shares. Two forests per
#   target (y1 / y2 log ratios, eps, the fixed settings of cap_allocation: no tuning), features = the v5.7 county
#   features common to the model config's eras of every year (+ the year's cell shares per group); no PLURAL, nothing
#   from GHS. Learn year: out of fold (folds of the split) for train counties, the all-train model for the rest; other
#   years: the all-train model on that year's features.
# Methods: v57 (own shares; identity check), P_transfer / B_transfer (softmax of the model), P_scaled / B_scaled (undated
#   share x f_c(year) = clip(bupr_year / bupr_ref, 0, 1), 1 where bupr_ref = 0 (county_record_uncertainty.csv, the
#   nby_age definition); the removed share to built / no_record in proportion to theirs), learn year only P_direct /
#   B_direct (the target shares themselves; a county without target -> v57, logged).
# Scores inside a group: v57 (all groups), plural_inv (unbuilt 1 - PLURAL), mixed (no_record pq5), pq5_unbuilt
#   (undated / no_record pq5); without PLURAL grid / pq5 for the year (not in plural_years): v57 only.

METHODS = ("v57", "P_transfer", "P_scaled", "B_transfer", "B_scaled", "P_direct", "B_direct")
LEARN_ONLY = ("P_direct", "B_direct")
T_SCORES = ("v57", "plural_inv", "mixed", "pq5_unbuilt")
TARGETS = ("P", "B")
CIRCULAR = "circular (GHS-POP 2010 uses the 2010 census)"


def tr_config(cfg: dict) -> dict:
    t = cfg.get("cap_transfer")
    if not t:
        sys.exit("ERROR: no cap_transfer block in the config")
    for k in ("learn_year", "years", "plural_years", "ghs_pop_year", "built_epoch", "ghs_built", "ghs_built_nres",
              "tract_errors", "county_features", "county_class", "bupr", "bupr_ref", "split", "exclusions", "eps",
              "rf", "perm_repeats", "methods", "scores", "mape_min"):
        if k not in t:
            sys.exit(f"ERROR: cap_transfer.{k} missing")
    t["years"] = sorted(int(y) for y in t["years"])
    t["plural_years"] = sorted(int(y) for y in t["plural_years"])
    t["learn_year"] = int(t["learn_year"])
    if t["learn_year"] not in t["years"]:
        sys.exit("ERROR: cap_transfer.learn_year must be one of its years")
    if not set(t["plural_years"]) <= set(t["years"]):
        sys.exit("ERROR: cap_transfer.plural_years must be among its years")
    if not set(t["methods"]) <= set(METHODS) or "v57" not in t["methods"]:
        sys.exit(f"ERROR: cap_transfer.methods must be among {METHODS} and hold v57: {t['methods']}")
    if not set(t["scores"]) <= set(T_SCORES) or "v57" not in t["scores"]:
        sys.exit(f"ERROR: cap_transfer.scores must be among {T_SCORES} and hold v57: {t['scores']}")
    return t


def ypath(template, year: int) -> Path:
    return Path(str(template).replace("{YEAR}", str(year)))


def common_features(model_config, years: list, cfs: dict) -> tuple[list, list]:
    """(features of the model config's era Y<year> of every year that are columns of every year's county features, in
    the order of the first year's list; the dropped ones). A GHS-derived name stops."""
    import yaml
    m = yaml.safe_load(Path(model_config).read_text(encoding="utf-8"))
    eras = m.get("eras") or {}
    lists = {}
    for y in years:
        e = eras.get(f"Y{y}")
        if not e or "features" not in e:
            sys.exit(f"ERROR: {model_config}: no era Y{y} with a features list")
        lists[y] = list(e["features"])
    keep = [f for f in lists[years[0]] if all(f in lists[y] and f in cfs[y].columns for y in years)]
    dropped = sorted(set().union(*map(set, lists.values())) - set(keep))
    bad = ghs_derived(keep)
    if bad:
        sys.exit(f"ERROR: cap model features derived from GHS: {bad}")
    if not keep:
        sys.exit("ERROR: no county feature common to every year")
    return keep, dropped


def f_factor(gj: pd.Series, bupr: pd.DataFrame, year: int, ref: int) -> tuple[np.ndarray, np.ndarray]:
    """(f_c, rule) per county in the order of gj: clip(bupr_year / bupr_ref, 0, 1), 1 where bupr_ref = 0 (nby_age)."""
    cols = [f"bupr_{year}", f"bupr_{ref}"]
    if not {"GISJOIN", *cols} <= set(bupr.columns) or bupr["GISJOIN"].duplicated().any():
        sys.exit(f"ERROR: bupr table: needs one row per GISJOIN with {cols}")
    t = gj.to_frame("GISJOIN").merge(bupr[["GISJOIN", *cols]], on="GISJOIN", how="left")
    if t[cols].isna().any().any():
        miss = t.loc[t[cols].isna().any(axis=1), "GISJOIN"].tolist()
        sys.exit(f"ERROR: bupr table: {len(miss)} counties of {year} missing: {miss[:20]}")
    b, r = t[cols[0]].to_numpy(float), t[cols[1]].to_numpy(float)
    zero = r <= 0
    ratio = np.divide(b, r, out=np.full(len(b), np.nan), where=~zero)
    f = np.where(zero, 1.0, np.clip(np.nan_to_num(ratio), 0.0, 1.0))
    return f, np.where(zero, "ref_zero", np.where(ratio > 1, "clipped_1", "ratio"))


def scale_undated(S: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, int]:
    """Undated share x f; the removed share goes to built / no_record in proportion to their shares (the sum stays 1).
    A county whose built + no_record shares are 0 keeps its shares (counted). NaN rows stay NaN."""
    S = np.asarray(S, float)
    out = S.copy()
    u = S[:, 1]
    rest = S[:, 0] + S[:, 2]
    d = u * (1.0 - f)
    ok = np.isfinite(u) & (rest > 0)
    out[ok, 1] = u[ok] * f[ok]
    out[ok, 0] = S[ok, 0] + d[ok] * S[ok, 0] / rest[ok]
    out[ok, 2] = S[ok, 2] + d[ok] * S[ok, 2] / rest[ok]
    return out, int((np.isfinite(u) & (rest <= 0) & (d > 0)).sum())


def year_inputs(args, cfg, mc, tc, model, year: int, learn: bool) -> tuple[dict, list]:
    import common
    cut = args.cutout_root / model["name"]
    maps = args.dasym_root / model["name"]
    p = {"zones": cut / "zones" / f"zones_{year}.tif", "zones_csv": cut / "zones" / f"zones_{year}.csv",
         "bui": common.layer_path(cut, "BUI", year), "v57": maps / mc["maps"]["v57"] / "predictions" / f"pop_{year}.tif",
         "tracts": args.tract_dir / f"tracts_{year}.gpkg", "tract_errors": ypath(tc["tract_errors"], year),
         "county_features": ypath(tc["county_features"], year)}
    if year in tc["plural_years"]:
        p["pq5"] = maps / mc["maps"]["pq5"] / "predictions" / f"pop_{year}.tif"
        p["plural"] = common.layer_path(cut, mc["plural_layer"], year)
    miss = [f"{year} {k} {v}" for k, v in p.items() if not Path(v).exists()]
    if learn:
        for k, spec, y in (("ghs_pop", cfg["products"]["ghs_pop"], int(tc["ghs_pop_year"])),
                           ("bt", tc["ghs_built"], int(tc["built_epoch"]))):
            path, note = resolve(args.data_root, spec, y)
            p[k] = path
            if path is None:
                miss.append(f"{k} {y}: {note}")
        path, note = resolve(args.data_root, tc["ghs_built_nres"], int(tc["built_epoch"]))
        p["bn"] = path
        if path is None:
            log.warning("  %d: GHS-BUILT-S NRES %d not found (%s): target B uses the TOTAL built-up surface", year,
                        tc["built_epoch"], note)
    for k, v in p.items():
        log.info("  input %d %-15s %s%s", year, k, v, "" if v is not None and Path(v).exists() else "  MISSING")
    return p, miss


def transfer_strip(task):
    try:
        return _transfer_strip(*task)
    except BaseException as e:   # sys.exit in a pool worker would hang the pool
        raise RuntimeError(f"strip {task[0]}-{task[1]}: {type(e).__name__}: {e}") from None


def _transfer_strip(r0: int, r1: int, ctx: dict) -> dict:
    gt, crs, W, n = ctx["grid_t"], ctx["crs"], ctx["width"], ctx["n_counties"]
    h = r1 - r0
    st = win_transform(Window(0, r0, W, h), gt)
    vm, mask = mcm.read_rows(ctx["v57"], r0, r1, gt, W)
    with rasterio.open(ctx["zones"]) as src:
        zones = src.read(1, window=Window(0, r0, W, h)).astype(np.int64)
    ci = ctx["lut"][zones]
    m = mask & (ci >= 0)
    info = {"mask_cells_no_county": int((mask & (ci < 0)).sum())}
    v57 = np.where(mask, vm, 0.0)
    bui, bvalid = mcm.read_rows(ctx["bui"], r0, r1, gt, W)
    info["bui_nodata_in_mask"] = int((m & ~bvalid).sum())
    bui = np.where(bvalid, bui, -1.0)
    nb = ecmt.read_on_box(ctx["nobuilt"], st, (h, W), crs)
    ctype = ecd.cell_types(bui, nb)
    key = (ci * NT + ctype)[m]
    L = n * NT
    acc = {"cells": np.bincount(key, minlength=L).astype(np.int64), "v57": np.bincount(key, weights=v57[m], minlength=L)}
    tid = _SHARED["tid"][r0:r1]
    info["tract_cells_outside_mask"] = int(((tid > 0) & ~m).sum())
    cells = {"ci": ci[m].astype(np.int32), "grp": ctype[m].astype(np.int8), "v57": v57[m].astype(np.float32),
             "tid": tid[m].astype(np.int32)}
    if ctx.get("pq5") is not None:
        a, valid = mcm.read_rows(ctx["pq5"], r0, r1, gt, W)
        info["pq5_mask_cells_without_value"] = int((mask & ~valid).sum())
        cells["pq5"] = np.where(mask & valid, a, 0.0)[m].astype(np.float32)
    if ctx.get("plural") is not None:
        pl, pvalid = mcm.read_rows(ctx["plural"], r0, r1, gt, W)
        info["plural_nodata_in_mask"] = int((m & ~pvalid).sum())
        cells["plural"] = np.where(pvalid, pl, np.nan)[m].astype(np.float32)
    prods = {}
    for k, path in ctx["products"].items():
        a = mcm.product_rows(path, r0, r1, gt, crs, W, ctx["tile_cols"], ctx["subpixel_m"])
        prods[k] = a
        acc[k] = np.bincount(key, weights=a[m], minlength=L)
        info[f"{k}_mask"] = float(a[m].sum())
        info[f"{k}_outside_mask"] = float(a[~m].sum())
    if "bt" in prods:
        res = prods["bt"] - prods["bn"] if "bn" in prods else prods["bt"]
        neg = m & (res < 0)
        info["bres_negative_cells"] = int(neg.sum())
        info["bres_negative_m2"] = float(res[neg].sum())
        acc["bres"] = np.bincount(key, weights=np.maximum(res, 0.0)[m], minlength=L)
    return {"rows": (r0, r1), "acc": acc, "info": info, "cells": cells}


def year_pass(args, model, p: dict, year: int, ctx_extra: dict, block_rows: int) -> dict:
    """One year's strips: used counties, county x group sums, cells, evaluated tracts."""
    import common
    used, lut = mcm.counties(p, model, year)
    n = len(used)
    with rasterio.open(p["v57"]) as src:
        grid_t, crs, (H, W) = src.transform, src.crs, src.shape
    grid = {"transform": grid_t, "crs": crs, "shape": (H, W)}
    with rasterio.open(p["zones"]) as src:
        if src.transform != grid_t or src.shape != (H, W):
            sys.exit(f"ERROR: {year}: zones are not on the grid of the v5.7 map")
    t0 = time.time()
    tracts = tv.read_tracts(p["tracts"], grid, "")
    tid = tv.tract_ids(tracts, grid)
    _SHARED["tid"] = tid
    te = pd.read_csv(p["tract_errors"])
    tr = te[te["flag"] == "ok"].reset_index(drop=True)
    pos = pd.Series(np.arange(1, len(tracts) + 1), index=tracts["GISJOIN"].to_numpy())
    if not tr["GISJOIN"].isin(pos.index).all():
        sys.exit(f"ERROR: {p['tract_errors']}: evaluated tracts missing from {p['tracts']}")
    tpos = pos.loc[tr["GISJOIN"]].to_numpy()
    ncell_t = np.bincount(tid.ravel(), minlength=len(tracts) + 1)
    if not (ncell_t[tpos] == tr["n_cells"].to_numpy()).all():
        sys.exit(f"ERROR: tract cells here != n_cells of {p['tract_errors']}")
    log.info("  tracts %d: %d in %s, %d evaluated (flag ok) in %d counties; cells per tract = the file (%.0f s)", year,
             len(tracts), p["tracts"].name, len(tr), tr["zone_gisjoin"].nunique(), time.time() - t0)
    ctx = {"grid_t": grid_t, "crs": crs, "width": W, "n_counties": n, "lut": lut, "zones": p["zones"], "v57": p["v57"],
           "bui": p["bui"], "pq5": p.get("pq5"), "plural": p.get("plural"), **ctx_extra}
    rows = common.strips((H, W), block_rows)
    log.info("  grid %d x %d, %d strips of %d rows, %d workers, %d counties, products %s", H, W, len(rows), block_rows,
             args.workers, n, list(ctx["products"]))
    acc, info, cl = None, {}, []
    for res in run_strips(ctx, rows, args.workers, transfer_strip):
        acc = res["acc"] if acc is None else {k: acc[k] + v for k, v in res["acc"].items()}
        for k, v in res["info"].items():
            info[k] = info.get(k, 0) + v
        cl.append(res["cells"])
    c = {k: np.concatenate([u[k] for u in cl]) for k in cl[0]}
    del cl
    _SHARED.clear()
    del tid
    log.info("  cells kept %d (built %d, undated %d, no_record %d); %s", len(c["ci"]),
             *(int((c["grp"] == i).sum()) for i in range(3)),
             {k: round(v, 3) if isinstance(v, float) else v for k, v in info.items()})
    A = {k: v.reshape(n, NT) for k, v in acc.items()}
    ct = used[["GISJOIN", "state", "name", "status", "train"]].reset_index(drop=True).copy()
    ct[f"census_pop_{year}"] = used["pop"].to_numpy(float)
    ct["pop_v57"] = A["v57"].sum(axis=1)
    mcm.check_census(ct, year)
    return {"ct": ct, "A": A, "c": c, "tr": tr, "tpos": tpos, "nt": len(tracts) + 1, "n": n}


def pooled_by_class(year, method, G: np.ndarray, cc: np.ndarray, what: str = "allocated") -> list[dict]:
    rows = []
    for sub in ("all", *CLASSES):
        m = np.ones(len(cc), bool) if sub == "all" else cc == sub
        tot = G[m].sum()
        r = {"year": year, "method": method, "basis": what, "county_class": sub, "n_counties": int(m.sum()),
             "total": float(tot)}
        for i, g in enumerate(GROUPS):
            r[f"share_{g}"] = float(G[m, i].sum() / tot) if tot > 0 else np.nan
        r["share_unbuilt"] = r["share_undated"] + r["share_no_record"]
        rows.append(r)
    return rows


def draw_transfer(path: Path, tm: pd.DataFrame, methods: list, scores: list, years: list, learn: int):
    plots = ecm._plots()
    plt = plots.plt
    fig = plt.figure(figsize=(4.2 * len(years), 4.9), dpi=150, layout="constrained")
    axes = np.atleast_1d(fig.subplots(1, len(years), sharey=True))
    for ax, y in zip(axes, years):
        d = tm[(tm["year"] == y) & (tm["part"] == "all")]
        ref = d[d["method"] == REF]
        if ref.empty or not ref["n"].iloc[0]:
            ax.text(0.5, 0.5, f"{y}: no tracts", transform=ax.transAxes, ha="center", fontsize=9, color=plots.MUTED)
            ax.set_axis_off()
            continue
        ms = [m for m in methods if (d["method"] == m).any()]
        ax.axhline(ref["mdape"].iloc[0], color=plots.MUTED, lw=1.2, ls="--", label="v5.7")
        sc = [s for s in scores if (d["score"] == s).any()]
        for i, s in enumerate(sc):
            r = d[d["score"] == s].set_index("method").reindex(ms)
            x = np.arange(len(ms)) + (i - (len(sc) - 1) / 2) * 0.16
            ax.plot(x, r["mdape"], ls="none", marker="o", ms=6, color=plots.SERIES[i % len(plots.SERIES)],
                    label=f"score {s.replace('_', ' ')}")
        ax.set_xticks(range(len(ms)), [m.replace("_", " ") for m in ms], fontsize=7, rotation=30, ha="right")
        note = "learn year; P methods circular" if y == learn else ("no PLURAL grid: score v57 only" if len(sc) == 1
                                                                    else "")
        ax.set_title(f"{y}: {int(ref['n'].iloc[0])} tracts, {int(ref['counties'].iloc[0])} counties"
                     + (f"\n{note}" if note else ""), fontsize=9, color=plots.INK)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color=plots.GRID, lw=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(labelsize=7.5, colors=plots.INK)
    axes[0].set_ylabel("tract MdAPE, % (all evaluated tracts)", fontsize=8, color=plots.INK)
    h, lab = [], []
    for ax in axes:
        for hh, ll in zip(*ax.get_legend_handles_labels()):
            if ll not in lab:
                h.append(hh)
                lab.append(ll)
    fig.legend(h, lab, loc="outside lower center", ncol=len(lab), fontsize=8, frameon=False)
    fig.suptitle(f"County group shares (built / undated / no record) learned in {learn} (P = GHS-POP, B = GHS-BUILT-S\n"
                 "residential) and applied with each year's features; v5.7 = dashed line", fontsize=9.5,
                 color=plots.INK)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    log.info("  wrote %s", path)


def run_transfer(args, cfg, mc, tc):
    t_start = time.time()
    model = mcm.model_settings(Path(mc["model_config"]))
    if model["version"] != mc["maps"]["v57"]:
        sys.exit(f"ERROR: {mc['model_config']} is {model['version']}, the v57 map is {mc['maps']['v57']}")
    if "pq5" not in mc["maps"]:
        sys.exit("ERROR: missed_cells.maps has no pq5")
    args.name = model["name"]
    learn = tc["learn_year"]
    order = [learn] + [y for y in tc["years"] if y != learn]
    ins, miss = {}, []
    for y in order:
        ins[y], m = year_inputs(args, cfg, mc, tc, model, y, y == learn)
        miss += m
    tracked = {k: Path(tc[k]) for k in ("county_class", "bupr", "split", "exclusions")}
    for k, v in tracked.items():
        log.info("  input %-15s %s%s", k, v, "" if v.exists() else "  MISSING")
        if not v.exists():
            miss.append(f"{k} {v}")
    nb, how = ecd.nobuilt_path(args)
    log.info("  input NobuiltYear source: %s (%s)", nb, how)
    if nb is None:
        miss.append(f"NobuiltYear: {how}")
    block_rows = int(args.block_rows or model.get("block_rows") or 0)
    if not block_rows:
        sys.exit("ERROR: no block_rows")
    if miss:
        sys.exit(f"ERROR: {len(miss)} inputs missing: {miss}")
    cfs = {}
    for y in order:
        f = pd.read_csv(ins[y]["county_features"])
        cfs[y] = f[f["year"] == y] if "year" in f else f
    feats, dropped = common_features(mc["model_config"], order, cfs)
    log.info("FEATURES common to the eras of %s and their county features (%d): %s; not common: %s", order,
             len(feats), feats, dropped or "none")
    if args.check:
        log.info("CHECK OK: inputs for %s (learn %d, PLURAL / pq5 in %s), methods %s x scores %s, block_rows %d",
                 order, learn, tc["plural_years"], tc["methods"], tc["scores"], block_rows)
        return 0
    eps, rf = float(tc["eps"]), dict(tc["rf"])
    ref_year = int(tc["bupr_ref"])
    log.info("RULE targets (learn year %d, HISDAC groups of %d): P = GHS-POP %s group shares; B = GHS-BUILT-S %s "
             "residential surface (total - NRES, negative cells -> 0) group shares", learn, learn, tc["ghs_pop_year"],
             tc["built_epoch"])
    log.info("RULE cap models: y1 = log(s_undated / s_built), y2 = log(s_no_record / s_built), a 0 share -> eps = %g; "
             "random forests %s (fixed, no tuning); features = the common county features + the year's cell shares "
             "per group, no PLURAL, nothing from GHS; learn year out of fold on %s, other years the all-train models",
             eps, rf, tc["split"])
    log.info("RULE scaled: undated share x f_c(year), f_c = clip(bupr_year / bupr_%d, 0, 1), 1 where bupr_%d = 0; the "
             "removed share to built / no_record in proportion to their shares", ref_year, ref_year)
    log.info("RULE allocation as cap_allocation run (P_c = census of the year); tracts: reported only, no selection "
             "rule; county classes = the fixed DEGURBA level 1 labels of %s (1980 GHS) for every year",
             tc["county_class"])
    cls_t = pd.read_csv(tracked["county_class"])
    cclass = dict(zip(cls_t["GISJOIN"], cls_t["county_class"]))
    bupr = pd.read_csv(tracked["bupr"])
    split = pd.read_csv(tracked["split"])
    excl = set(pd.read_csv(tracked["exclusions"])["GISJOIN"])
    mape_min = float(tc["mape_min"])
    products = {}
    cm_rows, cap_rows, gs_rows, tm_rows, fc_rows, tps = [], [], [], [], [], []
    models = {}
    for y in order:
        ty = time.time()
        log.info("===== %d%s =====", y, " (learn year)" if y == learn else "")
        p = ins[y]
        if y == learn:
            products = {"ghs": p["ghs_pop"], "bt": p["bt"], **({"bn": p["bn"]} if p.get("bn") else {})}
        extra = {"nobuilt": nb, "products": products if y == learn else {}, "tile_cols": int(mc["tile_cols"]),
                 "subpixel_m": cfg["city_maps"]["subpixel_m"]}
        yp = year_pass(args, model, p, y, extra, block_rows)
        ct, A, c, tr, n = yp["ct"], yp["A"], yp["c"], yp["tr"], yp["n"]
        cnt = A["cells"]
        has = cnt > 0
        s_v57 = row_shares(A["v57"])
        cc = ct["GISJOIN"].map(cclass).fillna("none").to_numpy()
        log.info("  county classes (fixed 1980 labels): %s", pd.Series(cc).value_counts().to_dict())
        sp = ct[["GISJOIN"]].merge(split[["GISJOIN", "part", "fold"]], on="GISJOIN", how="left")
        part = sp["part"].fillna("none").to_numpy()
        fold = np.where(part == "train", sp["fold"].fillna(-1).astype(int).to_numpy(), -1)
        X = county_design(ct, cfs[y], None, feats, cnt)
        Xn = X.to_numpy(float)
        f, frule = f_factor(ct["GISJOIN"], bupr, y, ref_year)
        q = np.quantile(f, [0.1, 0.5, 0.9])
        fc_rows.append({"year": y, "n_counties": n, "f_p10": q[0], "f_median": q[1], "f_p90": q[2],
                        "f_min": float(f.min()), "f_max": float(f.max()), "n_clipped_1": int((frule == "clipped_1").sum()),
                        "n_ref_zero": int((frule == "ref_zero").sum())})
        log.info("  f_c %d: p10 / median / p90 %.3f / %.3f / %.3f; clipped to 1 %d, bupr_%d = 0 %d", y, *q,
                 fc_rows[-1]["n_clipped_1"], ref_year, fc_rows[-1]["n_ref_zero"])
        shares, preds = {"v57": s_v57}, {}
        if y == learn:
            targets = {"P": row_shares(A["ghs"]), "B": row_shares(A["bres"])}
            sets = {"oof_train": fold >= 0, "test": part == "test"}
            for tname, s_t in targets.items():
                fit = np.isfinite(s_t).all(axis=1)
                Yt = np.where(fit[:, None], log_ratios(np.nan_to_num(s_t), eps), np.nan)
                t0 = time.time()
                pred, how, imp = oof_predict(Xn, Yt, fold, fit, rf, args.workers, int(tc["perm_repeats"]),
                                             int(rf.get("random_state", 42)))
                trn = fit & (fold >= 0)
                models[tname] = [fit_rf(Xn[trn], Yt[trn, j], rf, args.workers) for j in range(2)]
                rest = fold < 0
                if rest.any():
                    full = np.column_stack([mdl.predict(Xn[rest]) for mdl in models[tname]])
                    log.info("  target %s: rest rows of oof_predict vs the kept all-train models: max |d| %.2e", tname,
                             float(np.nanmax(np.abs(full - pred[rest]))))
                    pred[rest] = full
                s_hat = softmax_shares(pred, has)
                preds[tname] = (pred, how)
                for sname, sel0 in sets.items():
                    sel = sel0 & fit
                    for j, yn in enumerate(("y1", "y2")):
                        cm_rows.append({"target": tname, "set": sname, "metric": "rmse", "group": yn,
                                        "n": int(sel.sum()), "value": float(np.sqrt(np.mean((pred[sel, j] - Yt[sel, j])
                                                                                            ** 2)))})
                    for i, g in enumerate(GROUPS):
                        cm_rows.append({"target": tname, "set": sname, "metric": "share_mae", "group": g,
                                        "n": int(sel.sum()), "value": float(np.mean(np.abs(s_hat[sel, i] -
                                                                                           s_t[sel, i])))})
                        cm_rows.append({"target": tname, "set": sname, "metric": "share_mae_v57", "group": g,
                                        "n": int(sel.sum()), "value": float(np.mean(np.abs(s_v57[sel, i] -
                                                                                           s_t[sel, i])))})
                for j, yn in enumerate(("y1", "y2")):
                    for fi, col in enumerate(X.columns):
                        cm_rows.append({"target": tname, "set": "oof_train", "metric": "perm_rmse_increase",
                                        "group": yn, "feature": col, "n": int((sets["oof_train"] & fit).sum()),
                                        "value": float(imp[j, fi])})
                log.info("  cap model %s: %d counties with a target (%d train), %.0f s", tname, int(fit.sum()),
                         int(trn.sum()), time.time() - t0)
                direct = np.where(fit[:, None], s_t, s_v57)
                shares[f"{tname}_direct"] = direct
                log.info("  %s_direct: %d counties without a target take the v57 shares", tname, int((~fit).sum()))
            gs_rows += pooled_by_class(y, f"GHS-POP {tc['ghs_pop_year']}", A["ghs"], cc, "product")
            gs_rows += pooled_by_class(y, f"GHS-BUILT-S res {tc['built_epoch']}", A["bres"], cc, "product")
        else:
            for tname in TARGETS:
                pred = np.column_stack([mdl.predict(Xn) for mdl in models[tname]])
                preds[tname] = (pred, np.full(n, f"model_{learn}", object))
        for tname in TARGETS:
            st = softmax_shares(preds[tname][0], has)
            shares[f"{tname}_transfer"] = st
            ss, kept = scale_undated(st, f)
            shares[f"{tname}_scaled"] = ss
            log.info("  %s_scaled: %d counties keep the transfer shares (built + no_record share 0)", tname, kept)
        methods = [m for m in tc["methods"] if m in shares and (m not in LEARN_ONLY or y == learn)]
        for mth in methods:
            d = ct[["GISJOIN", "state", "name"]].copy()
            d.insert(0, "year", y)
            d["county_class_1980"], d["part"], d["fold"], d["method"], d["f_c"] = cc, part, fold, mth, f
            for i, g in enumerate(GROUPS):
                d[f"n_cells_{g}"] = cnt[:, i]
            for i, g in enumerate(GROUPS):
                d[f"share_{g}"] = shares[mth][:, i]
            t = mth.split("_")[0]
            if t in preds and mth.endswith(("_transfer", "_scaled")):
                d["y1"], d["y2"], d["pred_from"] = preds[t][0][:, 0], preds[t][0][:, 1], preds[t][1]
            cap_rows.append(d)
        # allocations
        P = ct[f"census_pop_{y}"].to_numpy(float)
        ci = c["ci"].astype(np.int64)
        key = ci * NT + c["grp"]
        T = np.bincount(ci, weights=c["v57"].astype(np.float64), minlength=n)
        fac = np.where(T > 0, P / np.where(T > 0, T, 1), 0.0)
        cidx = ct.reset_index().set_index("GISJOIN")["index"]
        tzone = cidx.reindex(tr["zone_gisjoin"]).to_numpy()
        if np.isnan(tzone.astype(float)).any():
            sys.exit(f"ERROR: {y}: evaluated tracts in counties not used here")
        tzone = tzone.astype(np.int64)
        parts = tract_parts(tr, excl, cclass)
        for k in ("all", *CLASSES):
            log.info("  tract part %-12s %6d tracts in %4d counties", k, int(parts[k].sum()),
                     tr["zone_gisjoin"][parts[k]].nunique())
        plural_ok = y in tc["plural_years"]
        scores = list(tc["scores"]) if plural_ok else ["v57"]
        note = {"plural_grid": "yes" if plural_ok else "no PLURAL grid"}
        tm_y = [{**r, "year": y, "circular": "", **note}
                for r in tract_rows(REF, REF, REF, tr, tr["pop_model"].to_numpy(float), parts, mape_min)]
        tp = tr[["GISJOIN", "zone_gisjoin", "part", "gap", "n_cells", "pop_obs"]].copy()
        tp.insert(0, "year", y)
        tp["county_class_1980"] = cc[tzone]
        tp[REF] = tr["pop_model"].to_numpy(float)
        tsum = {}
        for mth in methods:
            for score in scores:
                name = f"{mth}+{score}"
                cells, ainfo = allocate(ci, c["grp"], P, shares[mth], cell_scores(c, score), n)
                dmax = check_county_sums(ci, cells, P, n, f"{y} {name}")
                if mth == "v57" and score == "v57":
                    v = c["v57"].astype(np.float64)
                    if not np.allclose(cells, v * fac[ci], rtol=1e-9, atol=1e-9):
                        sys.exit(f"ERROR: {y}: method v57 + score v57 != v5.7 x P_c / v5.7 county sum")
                    if not np.allclose(cells, v, rtol=1e-6, atol=1e-6):
                        sys.exit(f"ERROR: {y}: method v57 + score v57 != v5.7 (rtol 1e-6)")
                ts = np.bincount(c["tid"], weights=cells, minlength=yp["nt"])[yp["tpos"]]
                if mth == "v57" and score == "v57":
                    want = tr["pop_model"].to_numpy(float) * fac[tzone]
                    if not np.allclose(ts, want, rtol=1e-9, atol=1e-6):
                        i = int(np.flatnonzero(~np.isclose(ts, want, rtol=1e-9, atol=1e-6))[0])
                        sys.exit(f"ERROR: {y}: tract {tr['GISJOIN'].iloc[i]}: method v57 + score v57 {ts[i]}, v5.7 "
                                 f"file {tr['pop_model'].iloc[i]} x {fac[tzone[i]]}")
                    log.info("  MATCH %d: v57 + v57 = v5.7 cells x P_c / county sum and %d tract sums of %s", y,
                             len(tr), p["tract_errors"].name)
                if score == "v57":
                    G = np.bincount(key, weights=cells, minlength=n * NT).reshape(n, NT)
                    gs_rows += pooled_by_class(y, mth, G, cc)
                tsum[name] = ts
                circ = CIRCULAR if (y == learn and mth.startswith("P_")) else ""
                tm_y += [{**r, "year": y, "circular": circ, **note}
                         for r in tract_rows(name, mth, score, tr, ts, parts, mape_min)]
                log.info("  %-24s county sums = census (max %.1e); %s", name, dmax, ainfo)
        tps.append(pd.concat([tp, pd.DataFrame(tsum)], axis=1))
        tm_y = pd.DataFrame(tm_y).rename(columns={"cap": "method"})
        ref = tm_y[tm_y["combination"] == REF].set_index("part")
        for k in ("mdape", "mape", "r2_log"):
            tm_y[f"d_{k}"] = tm_y[k].to_numpy() - ref.loc[tm_y["part"], k].to_numpy()
        tm_rows.append(tm_y)
        del c, yp
        log.info("  %d done (%.0f s)", y, time.time() - ty)
    tm = pd.concat(tm_rows, ignore_index=True)
    first = ["year", "combination", "method", "score", "part", "n", "counties", "circular", "plural_grid"]
    tm = tm[first + [k for k in tm.columns if k not in first]]
    gst = pd.DataFrame(gs_rows)
    cmt = pd.DataFrame(cm_rows)
    fct = pd.DataFrame(fc_rows).sort_values("year")
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    cmt.to_csv(out / "cap_model.csv", index=False)
    pd.concat(cap_rows, ignore_index=True).to_csv(out / "caps.csv", index=False)
    gst.to_csv(out / "group_shares.csv", index=False)
    fct.to_csv(out / "fc_summary.csv", index=False)
    tm.to_csv(out / "tract_metrics.csv", index=False)
    pd.concat(tps, ignore_index=True).to_csv(out / "tract_pop.csv.gz", index=False, float_format="%.4f")
    draw_transfer(out / "tract_mdape.png", tm, list(tc["methods"]), list(tc["scores"]), tc["years"], learn)
    with pd.option_context("display.width", 250, "display.max_rows", 500, "display.max_columns", 40):
        a = cmt[cmt["metric"] != "perm_rmse_increase"]
        log.info("SUMMARY cap models (learn year %d county CV):\n%s", learn,
                 a.pivot_table(index=["target", "set"], columns=["metric", "group"], values="value").round(4)
                 .to_string())
        imp = cmt[cmt["metric"] == "perm_rmse_increase"]
        log.info("SUMMARY permutation importance (OOF, RMSE increase):\n%s",
                 imp.pivot_table(index="feature", columns=["target", "group"], values="value", sort=False).round(4)
                 .to_string())
        log.info("SUMMARY f_c by year:\n%s", fct.round(4).to_string(index=False))
        g = gst[gst["county_class"] == "all"]
        log.info("SUMMARY pooled group shares (all counties) by year and method:\n%s",
                 g[["year", "method", "basis", "share_built", "share_undated", "share_no_record"]].round(4)
                 .to_string(index=False))
        log.info("SUMMARY pooled group shares by county class (fixed 1980 labels):\n%s",
                 gst.pivot_table(index=["county_class", "method"], columns="year", values="share_unbuilt", sort=False)
                 .round(4).to_string())
        for k in ("mdape", "d_mdape"):
            piv = tm[tm["part"].isin(["all", "dens_0_50", *CLASSES, "gap", "excluded_t070"])].pivot_table(
                index=["year", "combination"], columns="part", values=k, sort=False)
            log.info("SUMMARY tract %s by year, combination and part:\n%s", k, piv.round(2).to_string())
        log.info("SUMMARY tract n / counties by year and part:\n%s",
                 tm[tm["combination"] == REF].pivot_table(index="part", columns="year", values=["n", "counties"],
                                                          sort=False).to_string())
    log.info("wrote %s (6 tables + 1 PNG), %.0f s", out, time.time() - t_start)
    log.info("DONE")
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    mc = mcm.mc_config(cfg)
    if args.mode == "transfer":
        args.out_dir = args.out_dir or OUT_T
        return run_transfer(args, cfg, mc, tr_config(cfg))
    ca = ca_config(cfg)
    rb = db.rb_config(cfg)
    rb["boxes"] = rb.get("boxes") or {}
    args.out_dir = args.out_dir or OUT
    return run(args, cfg, mc, ca, rb)


if __name__ == "__main__":
    sys.exit(main())
