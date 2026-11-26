"""Strata: keep v5.7's people per county x area type x cell group and change only the order of the cells inside each
stratum with another model's cell people (request docs/handoff/strata_request.md; docs/conus_plan.md "Strata (PLURAL
area type x cell group)"; background "Cap transfer: result": v5.7's split between the cell groups is about right, the
remaining tract error is WHICH cells inside a group get people). No change to v5.7 itself.

  config  (login node, seconds) the four new versions (Dasy_CONUS_RF_v3_all_nby_{ntl,ntlv,pq5ntl,pq5ntlv}) = v5.7's
          era Y2010 + their additions, every other setting = v5.7's, the plural block = pq5's, the layers in the
          study area for 2010, the `strata:` block's score versions -> CONFIG OK, or CONFIG DIFFERS + exit 1.
  run     (one job) one strip pass per year (the calibration year 2010 first): breaks, strata, allocations,
          selection, report -> --out-dir. `--check` = the inputs only (the new versions' maps may be missing: they
          are made by the same chain).

Definitions (`strata:` block of configs/external_grids.yaml; rules fixed 2026-11-26 before any result):
  cells       mask = v5.7 pop_Y.tif not nodata, in a used county (cap_allocation.year_pass); cell group built (BUI_Y >
              0) / undated (BUI_Y = 0, NobuiltYear > 0) / no_record (missed_cells / cap_allocation).
  area type   from PLURAL_Y (cutout layer, bilinear; 0 urban ... 1 rural): urban PLURAL <= t1, peri_urban t1 < PLURAL
              <= t2, rural PLURAL > t2, PLURAL nodata -> none (never swapped, counted). t1 / t2 fixed ONCE from the
              calibration year and used for every year (PLURAL is computed per year from that year's places, so the
              same breaks give era-specific classes): over the calibration year's mask cells with a GHS-SMOD class
              (scheme A of rural_boxes.smod per 250 m cell = the SMOD 1 km cell its centre falls in: urban 30,
              peri_urban 21-23, rural 11-13; water 10 / nodata left out) and a PLURAL value, t1 = the smallest PLURAL
              value with share(PLURAL <= t1) >= the SMOD urban cell share, t2 the same with the urban + peri_urban
              share (numpy quantile, inverted_cdf). GHS-SMOD enters only these two numbers: no GHS cell value (and no
              GHS-POP) is used anywhere else.
  strata      3 types x 3 groups = 9 per year (+ the type none, kept at v5.7).
  allocation  cap = v5.7's own people per (county, stratum). Inside a stratum of a county: cell = cap x score_i /
              sum(score), score = a model's cell people (its pop_Y.tif; nodata on a mask cell -> 0). A county stratum
              with people and score sum 0 keeps v5.7 (counted). With score v57 everywhere the result = v5.7 (cells
              rtol 1e-9, tract sums = pop_model of v5.7's tract_errors_Y.csv), else stop; every allocation keeps the
              county x stratum sums (rtol 1e-9) and the county sums = census (rtol 1e-6, as v5.7), else stop.
  selection   per year and stratum: only that stratum's score swapped (all others v57), tract MdAPE on the tracts of
              TRAIN counties (part of configs/conus_split.csv; must equal the part column of the tract file); the
              lowest-MdAPE score is chosen if it beats v57 by more than min_gain_pp (0.1 pp), else v57 (a tie between
              scores -> the first in the config). TEST tracts never enter the choice. Then one combined allocation
              with every stratum's chosen score.
  report      on the TEST-county tracts: v5.7 (file), combined, and each single full model (its own cells on v5.7's
              mask) -> MdAPE / MAPE (tracts >= mape_min people) / R2 of log(pop + 1) / RMSE / MAE by part: all,
              dens_*, kept / excluded t070, no_gap / gap, the fixed 1980 county class, tract area type (the type of
              most of its cells; a tie -> the more urban type). No further selection.

Writes to --out-dir (results/validation/conus/strata/):
  breaks.csv          t1 / t2 with the SMOD target and the reached PLURAL shares, SMOD class shares, confusion matrix
                      PLURAL type x SMOD class (cells) + agreement, area type shares per year
  strata_cells.csv    year x area type x group: cells, counties with cells, v5.7 people and share
  stratum_scores.csv  year x stratum x score: TRAIN / TEST MdAPE of the single swap and d vs v57, county strata kept
                      at v5.7 (score sum 0), chosen flag
  chosen.csv          year x stratum: chosen score, v57 / best TRAIN MdAPE, gain
  test_metrics.csv    year x method x part (TEST-county tracts), d_* vs v5.7
  strata_mdape.png    TEST MdAPE per method and year; TEST d_mdape of each stratum's best single swap
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
import cap_allocation as ca  # noqa: E402
import degurba_boxes as db  # noqa: E402
import external_city_density as ecd  # noqa: E402
import external_city_maps as ecm  # noqa: E402
import external_city_meeting as ecmt  # noqa: E402
import missed_cells as mcm  # noqa: E402
import tract_validate as tv  # noqa: E402
from external_compare import load_config, resolve  # noqa: E402
from metrics_over_time import mape  # noqa: E402

log = logging.getLogger("strata")
OUT = Path("results/validation/conus/strata")
AREA_TYPES = ("urban", "peri_urban", "rural")
TYPE_NAMES = (*AREA_TYPES, "none")                       # index 3 = PLURAL nodata
NONE = 3
NTY = len(TYPE_NAMES)
GROUPS = ca.GROUPS                                       # built / undated / no_record
NT = len(GROUPS)
NS = NTY * NT                                            # stratum = type x NT + group
# scheme A class index (db.A_CLASSES: rural, peri_urban, urban, excluded) -> area type index (-1 = left out)
SMOD_TYPE = np.array([AREA_TYPES.index(c) for c in db.CLASSES] + [-1], np.int64)
REF = "v5.7"
GAIN_TOL = 1e-9                                          # float tolerance of the min_gain_pp rule
CONFIG_FREE = ("version", "years", "eras", "compare_with", "feature_groups", "plural")   # may differ from v5.7


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["config", "run"])
    p.add_argument("--config", type=Path, default=Path("configs/external_grids.yaml"))
    p.add_argument("--data-root", type=Path, help="$DATA_ROOT/raw/external (GHS-SMOD)")
    p.add_argument("--dasym-root", type=Path, help="<root>/<name>/<version>/predictions/pop_{YEAR}.tif")
    p.add_argument("--cutout-root", type=Path, help="<root>/<name>/{zones,layers}")
    p.add_argument("--census-dir", type=Path, help="(not read; kept for the common sbatch arguments)")
    p.add_argument("--tract-dir", type=Path, help="tracts_{YEAR}.gpkg")
    p.add_argument("--hisdac-dir", type=Path, default=None, help="HISDAC-US V2 folder: FBUY/NobuiltYear.tif")
    p.add_argument("--out-dir", type=Path, default=OUT)
    p.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_ON_NODE", "1")))
    p.add_argument("--block-rows", type=int, default=None, help="override the model config's block_rows (tests)")
    p.add_argument("--check", action="store_true", help="run: list the inputs only; exit 1 if one is missing")
    return p.parse_args(argv)


def st_config(cfg: dict) -> dict:
    st = cfg.get("strata")
    if not st:
        sys.exit("ERROR: no strata block in the config")
    for k in ("model_config", "base", "base_label", "years", "calib_year", "plural_layer", "scores", "new_versions",
              "plural_from", "tract_errors", "split", "exclusions", "county_class", "min_gain_pp", "mape_min"):
        if k not in st:
            sys.exit(f"ERROR: strata.{k} missing")
    st["years"] = sorted(int(y) for y in st["years"])
    st["calib_year"] = int(st["calib_year"])
    if st["calib_year"] not in st["years"]:
        sys.exit("ERROR: strata.calib_year must be one of its years")
    st["scores"] = {int(y): dict(v or {}) for y, v in st["scores"].items()}
    if set(st["scores"]) != set(st["years"]):
        sys.exit(f"ERROR: strata.scores years {sorted(st['scores'])} != strata.years {st['years']}")
    for y, sc in st["scores"].items():
        if st["base_label"] in sc:
            sys.exit(f"ERROR: strata.scores {y}: {st['base_label']} is the base, always a candidate, not listed")
    for k, spec in st["new_versions"].items():
        if not isinstance(spec, dict) or "config" not in spec or not spec.get("add"):
            sys.exit(f"ERROR: strata.new_versions.{k} needs config and add")
    st["min_gain_pp"] = float(st["min_gain_pp"])
    return st


# ---------------------------------------------------------------- config check (new versions)

def check_new_configs(st: dict) -> list[str]:
    """Problems of the new versions' configs against v5.7 (empty list = CONFIG OK)."""
    import yaml

    import common

    def load(p):
        return yaml.safe_load(Path(p).read_text(encoding="utf-8"))

    base = load(st["model_config"])
    pq = load(st["plural_from"])
    out = []
    if base.get("version") != st["base"]:
        out.append(f"{st['model_config']}: version {base.get('version')} != strata.base {st['base']}")
    bera = (base.get("eras") or {}).get("Y2010")
    if not bera:
        return out + [f"{st['model_config']}: no era Y2010"]
    study = load(common.resolve_repo_path(base["study_area"], Path(st["model_config"])))
    layers = {d["name"]: d for d in study.get("layers", [])}
    for label, spec in st["new_versions"].items():
        p = spec["config"]
        m = load(p)
        add = list(spec["add"])
        want = f"{st['base']}_{label}"
        if m.get("version") != want:
            out.append(f"{p}: version {m.get('version')} != {want}")
        if st["scores"].get(2010, {}).get(label) != want:
            out.append(f"strata.scores 2010 {label}: {st['scores'].get(2010, {}).get(label)} != {want}")
        if m.get("years") != [2010]:
            out.append(f"{p}: years {m.get('years')} != [2010]")
        era = {"Y2010": {"years": [2010], "features": list(bera["features"]) + add}}
        if m.get("eras") != era:
            out.append(f"{p}: eras {m.get('eras')} != v5.7's Y2010 + {add}: {era}")
        if m.get("compare_with") != st["base"]:
            out.append(f"{p}: compare_with {m.get('compare_with')} != {st['base']}")
        if "plural" in add:
            if m.get("plural") != pq.get("plural"):
                out.append(f"{p}: plural block {m.get('plural')} != {st['plural_from']}'s {pq.get('plural')}")
        elif "plural" in m:
            out.append(f"{p}: a plural block without the feature plural")
        fg, bg = m.get("feature_groups") or {}, base.get("feature_groups") or {}
        extra = {k: v for k, v in fg.items() if k not in bg}
        if any(fg.get(k) != v for k, v in bg.items()) or sorted(sum(extra.values(), [])) != sorted(add):
            out.append(f"{p}: feature_groups != v5.7's + groups of exactly {add}: {fg}")
        for k in sorted((set(base) | set(m)) - set(CONFIG_FREE)):
            if base.get(k) != m.get(k):
                out.append(f"{p}: {k} {m.get(k)!r} != v5.7's {base.get(k)!r}")
        for f in add:
            lay = st["plural_layer"] if f == "plural" else common.LAYER_FEATURES.get(f)
            if f == "plural" and m.get("plural"):
                lay = m["plural"].get("layer")
            yrs = (layers.get(lay) or {}).get("years")
            if lay is None or lay not in layers or not (isinstance(yrs, list) and 2010 in yrs):
                out.append(f"{p}: feature {f}: layer {lay} with 2010 not in the study area {base['study_area']}")
        try:
            common.load_config(Path(p))
        except SystemExit as e:
            out.append(f"{p}: common.load_config: {e}")
    lay = layers.get(st["plural_layer"]) or {}
    if not (isinstance(lay.get("years"), list) and set(st["years"]) <= set(lay["years"])):
        out.append(f"study area: layer {st['plural_layer']} lacks years {st['years']}")
    return out


# ---------------------------------------------------------------- breaks and strata

def quantile_breaks(plural: np.ndarray, smod_type: np.ndarray) -> dict:
    """t1 / t2 by quantile matching on cell counts over the cells with a SMOD type (>= 0) and a PLURAL value."""
    ok = np.isfinite(plural) & (smod_type >= 0)
    if not ok.any():
        sys.exit("ERROR: breaks: no cell with a SMOD class and a PLURAL value")
    p, s = plural[ok].astype(np.float64), smod_type[ok]
    su, sup = float(np.mean(s == 0)), float(np.mean(s <= 1))
    if su <= 0 or sup >= 1:
        sys.exit(f"ERROR: breaks: SMOD urban share {su} / urban + peri_urban share {sup}: no break in (0, 1)")
    t1 = float(np.quantile(p, su, method="inverted_cdf"))
    t2 = float(np.quantile(p, sup, method="inverted_cdf"))
    return {"t1": t1, "t2": t2, "smod_urban": su, "smod_urban_peri": sup, "n": int(ok.sum()),
            "reached_t1": float(np.mean(p <= t1)), "reached_t2": float(np.mean(p <= t2))}


def area_types(plural: np.ndarray, t1: float, t2: float) -> np.ndarray:
    t = np.full(len(plural), NONE, np.int8)
    fin = np.isfinite(plural)
    t[fin & (plural <= t1)] = 0
    t[fin & (plural > t1) & (plural <= t2)] = 1
    t[fin & (plural > t2)] = 2
    return t


def confusion(ptype: np.ndarray, smod_type: np.ndarray) -> np.ndarray:
    """(3, 3) cells: rows PLURAL type, columns SMOD type, over cells with both."""
    ok = (ptype < NONE) & (smod_type >= 0)
    return np.bincount(ptype[ok].astype(np.int64) * 3 + smod_type[ok], minlength=9).reshape(3, 3)


def swap_cells(k: np.ndarray, v: np.ndarray, s: np.ndarray) -> tuple[np.ndarray, int]:
    """New values of the cells of one or more strata: cap (v's sum per key) x s / sum(s) per key; a key with people
    and score sum 0 keeps v. Returns (values, number of such keys)."""
    L = int(k.max()) + 1 if len(k) else 0
    cap = np.bincount(k, weights=v, minlength=L)
    ssum = np.bincount(k, weights=s, minlength=L)
    zero = ssum <= 0
    new = np.where(zero[k], v, cap[k] * s / np.where(zero, 1.0, ssum)[k])
    return new, int((zero & (cap > 0)).sum())


def choose(train_mdape: dict, base: str, min_gain: float) -> tuple[str, str, float]:
    """(chosen, best, gain): the lowest TRAIN MdAPE among the non-base scores (a tie -> the first); chosen if it beats
    the base by more than min_gain (pp; float tolerance 1e-9, so 20.0 - 19.9 is not more than 0.1), else the base."""
    others = [s for s in train_mdape if s != base and np.isfinite(train_mdape[s])]
    if not others:
        return base, base, 0.0
    best = min(others, key=lambda s: train_mdape[s])               # min keeps the first of equal values
    gain = float(train_mdape[base] - train_mdape[best])
    return (best if gain > min_gain + GAIN_TOL else base), best, gain


# ---------------------------------------------------------------- one strip

def strata_strip(task):
    try:
        return _strata_strip(*task)
    except BaseException as e:   # sys.exit in a pool worker would hang the pool
        raise RuntimeError(f"strip {task[0]}-{task[1]}: {type(e).__name__}: {e}") from None


def _strata_strip(r0: int, r1: int, ctx: dict) -> dict:
    """cap_allocation._transfer_strip's cells (mask, county, group, v57, tract id, PLURAL) + the score maps' cells and,
    in the calibration year, the SMOD area type of each cell."""
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
    tid = ca._SHARED["tid"][r0:r1]
    info["tract_cells_outside_mask"] = int(((tid > 0) & ~m).sum())
    pl, pvalid = mcm.read_rows(ctx["plural"], r0, r1, gt, W)
    info["plural_nodata_in_mask"] = int((m & ~pvalid).sum())
    cells = {"ci": ci[m].astype(np.int32), "grp": ctype[m].astype(np.int8), "v57": v57[m].astype(np.float32),
             "tid": tid[m].astype(np.int32), "plural": np.where(pvalid, pl, np.nan)[m].astype(np.float32)}
    for k, path in ctx["scores"].items():
        a, valid = mcm.read_rows(path, r0, r1, gt, W)
        info[f"{k}_mask_cells_without_value"] = int((m & ~valid).sum())
        info[f"{k}_people_outside_mask"] = float(a[valid & ~m].sum())
        cells[f"s_{k}"] = np.where(m & valid, a, 0.0)[m].astype(np.float32)
    if ctx.get("smod") is not None:
        codes = db.smod_on_cells(ctx["smod"], st, (h, W), crs)
        for code, cnt in db.check_codes(codes[m], ctx["smod_codes"], f"strip {r0}-{r1}").items():
            info[f"smod_code_{code}"] = cnt
        cells["smod"] = SMOD_TYPE[db.scheme_a(codes, ctx["scheme_a"])][m].astype(np.int8)
    return {"rows": (r0, r1), "acc": acc, "info": info, "cells": cells}


# ---------------------------------------------------------------- tracts

def metric_row(year, method, part, obs, est, nc, zone, mape_min) -> dict:
    r = tv.metrics(obs, est, nc * tv.CELL_KM2)
    return {"year": year, "method": method, "part": part, "n": int(len(obs)), "counties": int(pd.unique(zone).size),
            **r, "mape": mape(obs, est, mape_min), "mape_n": int((obs >= mape_min).sum())}


def mdape(obs, est) -> float:
    return tv.metrics(obs, est, np.ones(len(obs)))["mdape"]


def tract_types(tid: np.ndarray, types: np.ndarray, nt: int, tpos: np.ndarray) -> np.ndarray:
    """Area type name per evaluated tract: the type of most of its cells (tie -> the more urban); none without."""
    cnt = np.bincount(tid.astype(np.int64) * NTY + types, minlength=nt * NTY).reshape(nt, NTY)[tpos, :3]
    out = np.array(AREA_TYPES, object)[cnt.argmax(axis=1)]
    return np.where(cnt.sum(axis=1) > 0, out, "none")


# ---------------------------------------------------------------- figure

def draw(path: Path, tm: pd.DataFrame, ss: pd.DataFrame, years: list):
    plots = ecm._plots()
    plt = plots.plt
    fig = plt.figure(figsize=(4.4 * len(years), 8.0), dpi=150, layout="constrained")
    axes = fig.subplots(2, len(years), squeeze=False)
    for j, y in enumerate(years):
        ax = axes[0, j]
        d = tm[(tm["year"] == y) & (tm["part"] == "all")]
        ref = d[d["method"] == REF]
        if ref.empty or not ref["n"].iloc[0]:
            ax.text(0.5, 0.5, f"{y}: no TEST tracts", transform=ax.transAxes, ha="center", fontsize=9)
            ax.set_axis_off()
        else:
            ms = list(d["method"])
            cols = [plots.MUTED if m == REF else (plots.SERIES[0] if m == "combined" else plots.SERIES[1]) for m in ms]
            ax.bar(range(len(ms)), d["mdape"], color=cols, width=0.65)
            ax.axhline(ref["mdape"].iloc[0], color=plots.MUTED, lw=1, ls="--")
            lo = float(np.nanmin(d["mdape"]))
            ax.set_ylim(max(0.0, lo - 5), float(np.nanmax(d["mdape"])) + 2)
            ax.set_xticks(range(len(ms)), [m.replace("full_", "full ") for m in ms], fontsize=7, rotation=30,
                          ha="right")
            ax.set_title(f"{y}: TEST tracts {int(ref['n'].iloc[0])} ({int(ref['counties'].iloc[0])} counties)",
                         fontsize=9, color=plots.INK)
        ax = axes[1, j]
        e = ss[(ss["year"] == y) & (ss["best"])]
        short = {"peri_urban": "peri", "no_record": "no rec", "undated": "undat"}
        lab = [f"{short.get(t, t)} {short.get(g, g)}" for t, g in zip(e["area_type"], e["group"])]
        col = [plots.SERIES[0] if c else plots.GRID for c in e["chosen"]]
        ax.bar(range(len(e)), e["test_d_mdape"], color=col, width=0.65)
        ax.axhline(0, color=plots.MUTED, lw=0.8)
        ax.set_xticks(range(len(e)), [f"{lb}\n{s}" for lb, s in zip(lab, e["score"])], fontsize=6.5, rotation=45,
                      ha="right")
        ax.set_title(f"{y}: best single-stratum swap (TRAIN), TEST d MdAPE\ncoloured = chosen (gain > rule)",
                     fontsize=8.5, color=plots.INK)
        for a in axes[:, j]:
            a.spines[["top", "right"]].set_visible(False)
            a.grid(axis="y", color=plots.GRID, lw=0.6)
            a.set_axisbelow(True)
            a.tick_params(labelsize=7.5, colors=plots.INK)
    axes[0, 0].set_ylabel("tract MdAPE, % (TEST-county tracts)", fontsize=8, color=plots.INK)
    axes[1, 0].set_ylabel("d MdAPE vs v5.7, pp (TEST)", fontsize=8, color=plots.INK)
    fig.suptitle("Strata (PLURAL area type x cell group): v5.7's people per county stratum, cells ordered by another "
                 "model\nv5.7 = dashed line; combined = every stratum's chosen score (chosen on TRAIN-county tracts)",
                 fontsize=9.5, color=plots.INK)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    log.info("  wrote %s", path)


# ---------------------------------------------------------------- run

def year_inputs(args, st, rb, model, year: int, check: bool) -> tuple[dict, dict, list]:
    import common
    cut = args.cutout_root / model["name"]
    maps = args.dasym_root / model["name"]
    p = {"zones": cut / "zones" / f"zones_{year}.tif", "zones_csv": cut / "zones" / f"zones_{year}.csv",
         "bui": common.layer_path(cut, "BUI", year), "v57": maps / st["base"] / "predictions" / f"pop_{year}.tif",
         "plural": common.layer_path(cut, st["plural_layer"], year), "tracts": args.tract_dir / f"tracts_{year}.gpkg",
         "tract_errors": ca.ypath(st["tract_errors"], year)}
    miss = [f"{year} {k} {v}" for k, v in p.items() if not Path(v).exists()]
    scores = {k: maps / v / "predictions" / f"pop_{year}.tif" for k, v in st["scores"][year].items()}
    new = {f"{st['base']}_{k}" for k in st["new_versions"]}
    for k, v in scores.items():
        made_here = st["scores"][year][k] in new
        if not v.exists():
            if check and made_here:
                log.info("  input %d score %-8s %s  (made by this chain)", year, k, v)
            else:
                miss.append(f"{year} score {k} {v}")
        else:
            log.info("  input %d score %-8s %s", year, k, v)
    if year == st["calib_year"]:
        path, note = resolve(args.data_root, rb["smod"], year)
        p["smod"] = path
        if path is None:
            miss.append(f"GHS-SMOD {year}: {note}")
    for k, v in p.items():
        log.info("  input %d %-13s %s%s", year, k, v, "" if v is not None and Path(v).exists() else "  MISSING")
    return p, scores, miss


def run(args, cfg, st, rb):
    t_start = time.time()
    for k in ("data_root", "dasym_root", "cutout_root", "tract_dir"):
        if getattr(args, k) is None:
            sys.exit(f"ERROR: run needs --{k.replace('_', '-')}")
    model = mcm.model_settings(Path(st["model_config"]))
    if model["version"] != st["base"]:
        sys.exit(f"ERROR: {st['model_config']} is {model['version']}, strata.base is {st['base']}")
    args.name = model["name"]
    cal = st["calib_year"]
    order = [cal] + [y for y in st["years"] if y != cal]
    ins, maps, miss = {}, {}, []
    for y in order:
        ins[y], maps[y], m = year_inputs(args, st, rb, model, y, args.check)
        miss += m
    tracked = {k: Path(st[k]) for k in ("split", "exclusions", "county_class")}
    for k, v in tracked.items():
        log.info("  input %-13s %s%s", k, v, "" if v.exists() else "  MISSING")
        if not v.exists():
            miss.append(f"{k} {v}")
    nb, how = ecd.nobuilt_path(args)
    log.info("  input NobuiltYear source: %s (%s)", nb, how)
    if nb is None:
        miss.append(f"NobuiltYear: {how}")
    probs = check_new_configs(st)
    for p in probs:
        log.error("CONFIG DIFFERS %s", p)
    if probs:
        miss.append(f"{len(probs)} config problems")
    block_rows = int(args.block_rows or model.get("block_rows") or 0)
    if not block_rows:
        sys.exit("ERROR: no block_rows")
    if miss:
        sys.exit(f"ERROR: {len(miss)} inputs missing: {miss}")
    if args.check:
        log.info("CHECK OK: inputs for %s (breaks from %d), scores %s, block_rows %d", order, cal,
                 {y: list(v) for y, v in maps.items()}, block_rows)
        return 0
    base = st["base_label"]
    log.info("RULE area type: PLURAL <= t1 urban, t1 < PLURAL <= t2 peri_urban, PLURAL > t2 rural, nodata none (kept "
             "at v5.7); t1 / t2 once from %d: smallest PLURAL value with share(PLURAL <= t) >= the GHS-SMOD %d urban "
             "(urban + peri_urban) cell share over the mask cells with a SMOD class (scheme A per cell) and a PLURAL "
             "value; used for every year. GHS-SMOD enters only t1 / t2; no GHS cell value is used anywhere else", cal,
             cal)
    log.info("RULE allocation: v5.7's people per county x area type x cell group; inside a stratum cap x score / "
             "sum(score), score = a model's cell people; a county stratum with score sum 0 keeps v5.7")
    log.info("RULE selection: per year and stratum one swap (others %s), MdAPE on TRAIN-county tracts (%s); the best "
             "score if it beats %s by more than %.2f pp, else %s; combined = every chosen score; reported on TEST-"
             "county tracts only; TEST tracts never enter the choice", base, st["split"], base, st["min_gain_pp"],
             base)
    cls_t = pd.read_csv(tracked["county_class"])
    cclass = dict(zip(cls_t["GISJOIN"], cls_t["county_class"]))
    split = pd.read_csv(tracked["split"])
    spart = dict(zip(split["GISJOIN"], split["part"]))
    excl = set(pd.read_csv(tracked["exclusions"])["GISJOIN"])
    mape_min = float(st["mape_min"])
    br_rows, sc_rows, ss_rows, ch_rows, tm_rows = [], [], [], [], []
    brk = None
    for y in order:
        ty = time.time()
        log.info("===== %d%s =====", y, " (calibration year of the breaks)" if y == cal else "")
        p = ins[y]
        extra = {"nobuilt": nb, "products": {}, "scores": maps[y], "smod": p.get("smod"),
                 "smod_codes": rb["smod"]["codes"], "scheme_a": rb["smod"]["scheme_a"]}
        yp = ca.year_pass(args, model, p, y, extra, block_rows, strata_strip)
        ct, c, tr, n = yp["ct"], yp["c"], yp["tr"], yp["n"]
        plural = c["plural"].astype(np.float64)
        if y == cal:
            brk = quantile_breaks(plural, c["smod"].astype(np.int64))
            log.info("BREAKS t1 = %.6f, t2 = %.6f from %d cells: SMOD urban share %.4f (PLURAL <= t1: %.4f), urban + "
                     "peri_urban %.4f (PLURAL <= t2: %.4f)", brk["t1"], brk["t2"], brk["n"], brk["smod_urban"],
                     brk["reached_t1"], brk["smod_urban_peri"], brk["reached_t2"])
            if not brk["t1"] < brk["t2"]:
                log.warning("  t1 = t2: peri_urban is empty")
            for nm, tgt, rch in (("t1", "smod_urban", "reached_t1"), ("t2", "smod_urban_peri", "reached_t2")):
                br_rows.append({"section": "break", "year": y, "name": nm, "value": brk[nm], "share": brk[tgt],
                                "reached_share": brk[rch], "cells": brk["n"]})
            sm = c["smod"].astype(np.int64)
            for i, nm in enumerate(AREA_TYPES):
                k = int(((sm == i) & np.isfinite(plural)).sum())
                br_rows.append({"section": "smod_share", "year": y, "smod_class": nm, "cells": k,
                                "share": k / brk["n"]})
            br_rows.append({"section": "smod_share", "year": y, "smod_class": "left_out (water / nodata / no PLURAL)",
                            "cells": int(len(sm) - brk["n"])})
            ptype = area_types(plural, brk["t1"], brk["t2"])
            cm = confusion(ptype, sm)
            for i, a in enumerate(AREA_TYPES):
                for j, b in enumerate(AREA_TYPES):
                    br_rows.append({"section": "confusion", "year": y, "plural_class": a, "smod_class": b,
                                    "cells": int(cm[i, j]), "share": cm[i, j] / cm.sum()})
            agree = float(np.trace(cm) / cm.sum())
            br_rows.append({"section": "agreement", "year": y, "value": agree, "cells": int(cm.sum())})
            log.info("  confusion PLURAL type (rows) x SMOD class (columns), cells:\n%s\n  agreement %.4f",
                     pd.DataFrame(cm, index=AREA_TYPES, columns=AREA_TYPES).to_string(), agree)
            del c["smod"], sm
        types = area_types(plural, brk["t1"], brk["t2"])
        del plural
        stratum = types.astype(np.int64) * NT + c["grp"]
        ci = c["ci"].astype(np.int64)
        key = ci * NS + stratum
        v = c["v57"].astype(np.float64)
        tc = np.bincount(types, minlength=NTY)
        for i, nm in enumerate(TYPE_NAMES):
            br_rows.append({"section": "type_share", "year": y, "plural_class": nm, "cells": int(tc[i]),
                            "share": tc[i] / tc.sum()})
        log.info("  area type cells %d: %s", y, dict(zip(TYPE_NAMES, tc.tolist())))
        scnt = np.bincount(stratum, minlength=NS)
        sppl = np.bincount(stratum, weights=v, minlength=NS)
        kc = np.bincount(key, minlength=n * NS).reshape(n, NS)
        for s in range(NS):
            sc_rows.append({"year": y, "area_type": TYPE_NAMES[s // NT], "group": GROUPS[s % NT], "cells": int(scnt[s]),
                            "counties": int((kc[:, s] > 0).sum()), "people_v57": float(sppl[s]),
                            "people_share": float(sppl[s] / sppl.sum())})
        # tracts: TRAIN / TEST county label of the split
        tp_ = tr["zone_gisjoin"].map(spart).fillna("none").to_numpy()
        if "part" in tr:
            bad = (tr["part"].isin(["train", "test"]).to_numpy() & (tr["part"].to_numpy() != tp_))
            if bad.any():
                sys.exit(f"ERROR: {y}: {int(bad.sum())} tracts whose part differs from {st['split']}")
        trn, tst = tp_ == "train", tp_ == "test"
        obs, ncell = tr["pop_obs"].to_numpy(float), tr["n_cells"].to_numpy(float)
        log.info("  tracts %d: TRAIN counties %d tracts (%d counties), TEST counties %d tracts (%d counties), other %d",
                 y, int(trn.sum()), tr["zone_gisjoin"][trn].nunique(), int(tst.sum()), tr["zone_gisjoin"][tst].nunique(),
                 int((~trn & ~tst).sum()))
        tid, nt, tpos = c["tid"], yp["nt"], yp["tpos"]

        def tsum(x):
            return np.bincount(tid, weights=x, minlength=nt)[tpos]

        # base = score v57 everywhere
        allv, nz = swap_cells(key, v, v)
        if not np.allclose(allv, v, rtol=1e-9, atol=1e-9):
            sys.exit(f"ERROR: {y}: score v57 everywhere != v5.7 cells")
        base_ts = tsum(allv)
        want = tr["pop_model"].to_numpy(float)
        if not np.allclose(base_ts, want, rtol=1e-9, atol=1e-6):
            i = int(np.flatnonzero(~np.isclose(base_ts, want, rtol=1e-9, atol=1e-6))[0])
            sys.exit(f"ERROR: {y}: tract {tr['GISJOIN'].iloc[i]}: score v57 {base_ts[i]}, v5.7 file {want[i]}")
        log.info("  MATCH %d: score v57 everywhere = v5.7 cells and %d tract sums of %s", y, len(tr),
                 p["tract_errors"].name)
        P = ct[f"census_pop_{y}"].to_numpy(float)
        del allv
        sel = {s: np.flatnonzero(stratum == s) for s in range(NTY * NT - NT)}   # the 9 strata (type none left out)
        b_tr, b_te = mdape(obs[trn], base_ts[trn]), mdape(obs[tst], base_ts[tst])
        cands = list(maps[y])
        new_cells: dict = {}
        for s, ix in sel.items():
            at, gr = TYPE_NAMES[s // NT], GROUPS[s % NT]
            res = {base: (b_tr, b_te, 0)}
            for k in cands:
                sc = c[f"s_{k}"][ix].astype(np.float64)
                new, nz = swap_cells(key[ix], v[ix], sc)
                kk = key[ix]
                L = int(kk.max()) + 1 if len(kk) else 0
                if not np.allclose(np.bincount(kk, weights=new, minlength=L), np.bincount(kk, weights=v[ix],
                                                                                          minlength=L),
                                   rtol=1e-9, atol=1e-6):
                    sys.exit(f"ERROR: {y} {at} {gr} {k}: county stratum sums changed")
                ts = base_ts + np.bincount(tid[ix], weights=new - v[ix], minlength=nt)[tpos]
                res[k] = (mdape(obs[trn], ts[trn]), mdape(obs[tst], ts[tst]), nz)
                new_cells[(s, k)] = new
            chosen, best, gain = choose({k: r[0] for k, r in res.items()}, base, st["min_gain_pp"])
            for k, (a, b, nz) in res.items():
                ss_rows.append({"year": y, "area_type": at, "group": gr, "score": k, "cells": len(ix),
                                "train_mdape": a, "train_d_mdape": a - b_tr, "test_mdape": b, "test_d_mdape": b - b_te,
                                "county_strata_kept_v57": nz, "best": k == best, "chosen": k == chosen})
            ch_rows.append({"year": y, "area_type": at, "group": gr, "cells": len(ix), "chosen": chosen,
                            "train_mdape_v57": b_tr, "best_score": best, "best_train_mdape": res[best][0],
                            "gain_pp": gain, "min_gain_pp": st["min_gain_pp"]})
            log.info("  %-10s %-9s %9d cells: TRAIN MdAPE %s -> chosen %s (gain %.3f pp)", at, gr, len(ix),
                     {k: round(r[0], 3) for k, r in res.items()}, chosen, gain)
            for k in cands:
                if k != chosen:
                    new_cells.pop((s, k), None)
        # combined
        comb = v.copy()
        for (s, k), new in new_cells.items():
            comb[sel[s]] = new
        del new_cells
        if not np.allclose(np.bincount(key, weights=comb, minlength=n * NS), np.bincount(key, weights=v,
                                                                                         minlength=n * NS),
                           rtol=1e-9, atol=1e-6):
            sys.exit(f"ERROR: {y}: combined: county stratum sums changed")
        cs = np.bincount(ci, weights=comb, minlength=n)
        d = np.abs(cs - P) / np.where(P > 0, P, 1)
        if not (d < 1e-6).all():
            sys.exit(f"ERROR: {y}: combined: county sums != census in {int((d >= 1e-6).sum())} counties")
        log.info("  combined %d: county x stratum sums = v5.7, county sums = census (max %.1e)", y, float(d.max()))
        ests = {REF: tr["pop_model"].to_numpy(float), "combined": tsum(comb)}
        for k in cands:
            ests[f"full_{k}"] = tsum(c[f"s_{k}"].astype(np.float64))
        # TEST parts
        tt = tr[tst].reset_index(drop=True)
        parts = {k: m for k, m in ca.tract_parts(tt, excl, cclass).items() if k not in ("train", "test")}
        ttype = tract_types(tid, types, nt, tpos)[tst]
        for a in (*AREA_TYPES, "none"):
            if a != "none" or (ttype == "none").any():
                parts[f"type_{a}"] = ttype == a
        o, nc_, z = obs[tst], ncell[tst], tt["zone_gisjoin"].to_numpy()
        rows = []
        for meth, est in ests.items():
            e = est[tst]
            for part, m in parts.items():
                rows.append(metric_row(y, meth, part, o[m], e[m], nc_[m], z[m], mape_min))
        r = pd.DataFrame(rows)
        ref = r[r["method"] == REF].set_index("part")
        for k in ("mdape", "mape", "r2_log"):
            r[f"d_{k}"] = r[k].to_numpy() - ref.loc[r["part"], k].to_numpy()
        tm_rows.append(r)
        log.info("  TEST MdAPE %d (all): %s", y, r[r["part"] == "all"].set_index("method")["mdape"].round(3).to_dict())
        del c, yp, comb, key, stratum, types, v
        log.info("  %d done (%.0f s)", y, time.time() - ty)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    cols = ["section", "year", "name", "plural_class", "smod_class", "cells", "share", "reached_share", "value"]
    brt = pd.DataFrame(br_rows).reindex(columns=cols)
    sct, sst, cht = pd.DataFrame(sc_rows), pd.DataFrame(ss_rows), pd.DataFrame(ch_rows)
    tm = pd.concat(tm_rows, ignore_index=True)
    brt.to_csv(out / "breaks.csv", index=False)
    sct.to_csv(out / "strata_cells.csv", index=False)
    sst.to_csv(out / "stratum_scores.csv", index=False)
    cht.to_csv(out / "chosen.csv", index=False)
    tm.to_csv(out / "test_metrics.csv", index=False)
    draw(out / "strata_mdape.png", tm, sst, st["years"])
    with pd.option_context("display.width", 250, "display.max_rows", 500, "display.max_columns", 40):
        log.info("SUMMARY breaks:\n%s", brt[brt["section"].isin(["break", "agreement"])].dropna(axis=1, how="all")
                 .to_string(index=False))
        log.info("SUMMARY area type shares by year:\n%s", brt[brt["section"] == "type_share"].pivot_table(
            index="plural_class", columns="year", values="share", sort=False).round(4).to_string())
        log.info("SUMMARY strata cells / v5.7 people share:\n%s", sct.pivot_table(
            index=["area_type", "group"], columns="year", values=["cells", "people_share"], sort=False).to_string())
        log.info("SUMMARY chosen:\n%s", cht.round(3).to_string(index=False))
        log.info("SUMMARY stratum scores (TRAIN / TEST d_mdape):\n%s", sst.pivot_table(
            index=["year", "area_type", "group"], columns="score", values=["train_d_mdape", "test_d_mdape"],
            sort=False).round(3).to_string())
        log.info("SUMMARY TEST MdAPE by year, method and part:\n%s", tm.pivot_table(
            index=["year", "method"], columns="part", values="mdape", sort=False).round(2).to_string())
    log.info("wrote %s (5 tables + 1 PNG), %.0f s", out, time.time() - t_start)
    log.info("DONE")
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    st = st_config(cfg)
    if args.mode == "config":
        probs = check_new_configs(st)
        for p in probs:
            log.error("CONFIG DIFFERS %s", p)
        if probs:
            return 1
        log.info("CONFIG OK: %s = v5.7's era Y2010 + %s; other settings = v5.7's; plural block = %s's",
                 [f"{st['base']}_{k}" for k in st["new_versions"]],
                 {k: v["add"] for k, v in st["new_versions"].items()}, st["plural_from"])
        return 0
    return run(args, cfg, st, db.rb_config(cfg))


if __name__ == "__main__":
    sys.exit(main())
