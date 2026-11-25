"""1980 missed cells: GHS-POP / GHS-BUILT on cells that HISDAC calls unbuilt (BUI_1980 = 0), per county and area type,
what v5.7 puts there, and whether PLURAL / remoteness picks them (request docs/handoff/missed_cells_1980_request.md;
Stefan 2026-11-25, docs/open_items.md next steps 1 + 2; docs/conus_plan.md "1980 missed cells"). Diagnosis only: no
model, training or prediction change; one year, CONUS, the 2010 counties v5.7 predicts (its use_status).

No threshold on GHS-POP: the people GHS-POP puts on unbuilt cells are a continuous mass; the only classes are DEGURBA's
(GHS-SMOD of the year).

  run      (one job) every row strip of block_rows rows of the model config (in column tiles of tile_cols cells for
           the product moves) -> county_missed_1980.csv, by_class_1980.csv, plural_capture_1980.csv, capture_1980.png,
           county_gap_1980.png in --out-dir. `--check` = list the inputs only (exit 1 if one is missing).

Cells (the `missed_cells:` block of configs/external_grids.yaml):
  mask       cells with a v5.7 prediction (pop_{YEAR}.tif not nodata: used counties, after the water mask). GHS people
             outside it are summed apart and logged: cells of a used county outside the mask (water / masked),
             cells of a county not used, cells outside every county (sea, outside CONUS).
  products   GHS-POP (people) and GHS-BUILT-S (built-up surface, m2) of the year moved to our 250 m cells with
             external_city_maps.to_grid (k x k sub-points, population / surface kept), as the DEGURBA boxes.
  groups     built = BUI > 0; unbuilt = BUI = 0, split into undated (NobuiltYear > 0) / no_record (= 0); a BUI nodata
             cell counts as unbuilt, as in degurba_boxes (count logged). NobuiltYear source = degurba_boxes'.
  cell class GHS-SMOD of the year per cell centre (degurba_boxes.smod_on_cells), the most frequent code of each 1 km
             block (4 x 4 cells from the grid origin; a tie -> the more urban code) = scheme A of the DEGURBA boxes:
             urban 30 / peri_urban 21-23 / rural 11-13 / excluded (water 10, nodata); a cell takes its block's class.
  county     DEGURBA level 1 (2021 manual) on GHS-POP of the year: >= 50 % of the county's GHS people (mask cells) on
  class      urban centre cells -> city; else >= 50 % on rural cells -> rural; else town_suburb; no GHS people ->
             no_ghs.
  maps       GHS-POP, v5.7 (main), v5.7 + PLURAL pq5, v5.4; versions read on the v5.7 mask cells (their people
             outside it, and mask cells without their value, logged).

Tables:
  county_missed_1980.csv  one row per county: census people, county class, cells per group, per map the county
             people and its unbuilt / undated / no_record shares (of the map's own county people), gap = GHS - v5.7
             unbuilt share, GHS / census, GHS on the county's cells outside the mask, GHS-BUILT surface and its shares
             on unbuilt / undated / no_record cells, overlap of v5.7 with GHS-POP on the county's unbuilt cells
             (degurba_boxes.overlap_metrics: sum min of the shares / of the people, even-spread baseline, Spearman).
  by_class_1980.csv       county class x cell class (+ all), cells pooled (not a mean of counties): the same sums,
             shares and overlaps; on the cell-class `all` rows the county gap distribution (median, 10 / 90 %).
  plural_capture_1980.csv unbuilt cells ranked by a score inside each county (the allocation is a within-county
             problem): share of the GHS people on unbuilt cells held by the top k % of the cells (by count, k x n_c
             cells per county; ties share the boundary evenly = the expected value of a random tie order), summed over
             the counties of a subset; one CONUS-wide ranking as a reference line. Scores: ghs (GHS itself = upper
             bound), plural_inv (1 - PLURAL, less remote first), v57, pq5 (cell people), nobuilt (NobuiltYear),
             neg_d_* (- distance, if the cutout has the year's PLACEDIST layers), random (= k). Spearman over the
             unbuilt cells of the subset and the median of the per-county Spearman (cells with a score only).
Checks (a difference stops the run before writing): v5.7 county sums = census (|d| / pop < 1e-6); per DEGURBA box
(the 11 boxes of rural_boxes) the year's built / undated / no_record people of GHS-POP, v5.7 and pq5 on the cells of
its full blocks = degurba_boxes' cell_type_shares.csv (scheme A, class all); the GHS score's capture >= every other
score's at every k; random = k.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
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
from external_compare import load_config, resolve  # noqa: E402

log = logging.getLogger("missed_cells")
OUT = Path("results/validation/conus/missed_cells_1980")
BOX_CHECK = db.EXT / "degurba_boxes_v57" / "cell_type_shares.csv"
F = 4                                                   # 1 km block = 4 x 4 cells
CELL_CLASSES = ("rural", "peri_urban", "urban", "excluded")   # index = degurba_boxes.scheme_a
GROUPS = ("built", "undated", "no_record")              # index = external_city_density.cell_types
COUNTY_CLASSES = ("city", "town_suburb", "rural")
NC, NT = len(CELL_CLASSES), len(GROUPS)
CELL_MAPS = ("v57", "pq5")                              # maps kept per unbuilt cell (overlap, capture scores)
EPS = 1e-9


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["run"])
    p.add_argument("--config", type=Path, default=Path("configs/external_grids.yaml"))
    p.add_argument("--data-root", type=Path, required=True, help="$DATA_ROOT/raw/external")
    p.add_argument("--dasym-root", type=Path, required=True, help="<root>/<name>/<version>/predictions/pop_{YEAR}.tif")
    p.add_argument("--cutout-root", type=Path, required=True, help="<root>/<name>/{zones,layers}")
    p.add_argument("--census-dir", type=Path, required=True, help="counties_2010.gpkg (county map)")
    p.add_argument("--hisdac-dir", type=Path, default=None, help="HISDAC-US V2 folder: FBUY/NobuiltYear.tif")
    p.add_argument("--out-dir", type=Path, default=OUT)
    p.add_argument("--box-check", type=Path, default=BOX_CHECK, help="degurba_boxes cell_type_shares.csv")
    p.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_ON_NODE", "1")))
    p.add_argument("--block-rows", type=int, default=None, help="override the model config's block_rows (tests)")
    p.add_argument("--check", action="store_true", help="list the inputs only; exit 1 if one is missing")
    return p.parse_args(argv)


# ---------------------------------------------------------------- config and inputs

def mc_config(cfg: dict) -> dict:
    mc = cfg.get("missed_cells")
    if not mc:
        sys.exit("ERROR: no missed_cells block in the config")
    for k in ("year", "model_config", "maps", "mask_map", "ghs_built", "plural_layer", "placedist_layer", "ks",
              "tile_cols", "county_rule"):
        if k not in mc:
            sys.exit(f"ERROR: missed_cells.{k} missing")
    if mc["mask_map"] not in mc["maps"]:
        sys.exit("ERROR: missed_cells.mask_map is not one of missed_cells.maps")
    ks = [float(k) for k in mc["ks"]]
    if sorted(ks) != ks or not all(0 < k <= 1 for k in ks):
        sys.exit(f"ERROR: missed_cells.ks must rise within (0, 1]: {ks}")
    mc["ks"] = ks
    return mc


def inputs(args, cfg, mc, rb, model):
    """Paths of every input (exits listing the missing ones). Returns a dict."""
    import common
    year = int(mc["year"])
    cut = args.cutout_root / model["name"]
    p = {"zones": cut / "zones" / f"zones_{year}.tif", "zones_csv": cut / "zones" / f"zones_{year}.csv",
         "bui": common.layer_path(cut, "BUI", year), "plural": common.layer_path(cut, mc["plural_layer"], year),
         "counties": args.census_dir / "counties_2010.gpkg", "box_check": args.box_check}
    for k, v in mc["maps"].items():
        p[f"map_{k}"] = args.dasym_root / model["name"] / v / "predictions" / f"pop_{year}.tif"
    miss = [f"{k} {v}" for k, v in p.items() if not Path(v).exists()]
    for k, spec in (("ghs_pop", cfg["products"]["ghs_pop"]), ("ghs_built", mc["ghs_built"]), ("smod", rb["smod"])):
        path, note = resolve(args.data_root, spec, year)
        p[k] = path
        if path is None:
            miss.append(f"{k} {year}: {note}")
    nb, how = ecd.nobuilt_path(args)
    p["nobuilt"], p["nobuilt_how"] = nb, how
    if nb is None:
        miss.append(f"NobuiltYear: {how}")
    p["placedist"] = {}
    for d in common.PLACE_DIST:
        f = common.layer_path(cut, f"{mc['placedist_layer']}/{d}", year)
        if f.exists():
            p["placedist"][d] = f
    for k, v in p.items():
        if k not in ("placedist", "nobuilt_how"):
            log.info("  input %-10s %s%s", k, v, "" if v is not None and Path(v).exists() else "  MISSING")
    log.info("  input NobuiltYear source: %s", how)
    if p["placedist"] and len(p["placedist"]) != len(common.PLACE_DIST):
        miss.append(f"PLACEDIST {year}: only {sorted(p['placedist'])} of {common.PLACE_DIST}")
    log.info("  remoteness: %s", f"PLACEDIST {year} layers {sorted(p['placedist'])} + PLURAL" if p["placedist"] else
             f"no {mc['placedist_layer']} layers for {year} in the cutout: PLURAL only (no new layer made)")
    if miss:
        sys.exit(f"ERROR: {len(miss)} inputs missing: {miss}")
    return p


def model_settings(path: Path) -> dict:
    """The model config's settings used here (name of its study area, block_rows, statuses); not the full
    common.load_config (no eras / models needed)."""
    import yaml

    import common
    m = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    study = yaml.safe_load(common.resolve_repo_path(m["study_area"], Path(path)).read_text(encoding="utf-8"))
    return {"name": study["name"], "version": m["version"], "block_rows": m.get("block_rows"),
            "use_status": m["use_status"], "train_status": m["train_status"],
            "unusable": str(m.get("unusable", "stop")).lower()}


def counties(p: dict, model: dict, year: int) -> tuple[pd.DataFrame, np.ndarray]:
    """(used counties in zone order, lookup zone id -> county index or -1)."""
    import common
    with rasterio.open(p["zones"]) as src:
        zones = src.read(1)
    table = pd.read_csv(p["zones_csv"])
    used = common.county_selection(table, zones, model["use_status"], year, model.get("unusable", "stop"))
    used = used.sort_values("zone_id").reset_index(drop=True)
    lut = np.full(max(int(zones.max()), int(table["zone_id"].max())) + 1, -1, np.int64)
    lut[used["zone_id"].to_numpy()] = np.arange(len(used))
    used["train"] = used["status"].isin(model["train_status"])
    return used, lut


# ---------------------------------------------------------------- one strip

def read_rows(path, r0: int, r1: int, grid_t, width: int):
    """(float64 values, valid flags) of rows r0:r1 of a raster on our grid."""
    with rasterio.open(path) as src:
        if src.transform != grid_t or src.width != width:
            raise RuntimeError(f"{path} is not on the grid of the mask map")
        nd = src.nodata
        a = src.read(1, window=Window(0, r0, width, r1 - r0)).astype("float64")
    valid = np.isfinite(a) if nd is None else (a != nd) & np.isfinite(a)
    return a, valid


def product_rows(path, r0: int, r1: int, grid_t, crs, width: int, tile_cols: int, subpixel_m: float):
    """A product moved to the cells of rows r0:r1 (to_grid per column tile; a cell's value does not depend on the
    tile: every sub-point is binned by its own position)."""
    out = np.zeros((r1 - r0, width))
    for c0 in range(0, width, tile_cols):
        cw = min(tile_cols, width - c0)
        tt = win_transform(Window(c0, r0, cw, r1 - r0), grid_t)
        out[:, c0:c0 + cw] = ecm.to_grid(path, tt, (r1 - r0, cw), crs, subpixel_m)[0]
    return out


def cell_classes(smod_path, st, shape, crs, rb) -> tuple[np.ndarray, dict]:
    """Scheme A class index per cell (its 1 km block's), and the SMOD codes found."""
    h, w = shape
    codes = db.smod_on_cells(smod_path, st, shape, crs)
    found = db.check_codes(codes, rb["smod"]["codes"], "strip")
    ph, pw = -h % F, -w % F
    pad = np.pad(codes, ((0, ph), (0, pw)), constant_values=db.NODATA)
    cls = db.scheme_a(db.block_majority(pad, F), rb["smod"]["scheme_a"])
    return np.repeat(np.repeat(cls, F, 0), F, 1)[:h, :w], found


def strip_work(task):
    try:
        return _strip_work(*task)
    except BaseException as e:   # sys.exit in a pool worker would hang the pool
        raise RuntimeError(f"strip {task[0]}-{task[1]}: {type(e).__name__}: {e}") from None


def _strip_work(r0: int, r1: int, ctx: dict) -> dict:
    gt, crs, W, n = ctx["grid_t"], ctx["crs"], ctx["width"], ctx["n_counties"]
    h = r1 - r0
    st = win_transform(Window(0, r0, W, h), gt)
    maps = {}
    vm, mask = read_rows(ctx["maps"][ctx["mask_map"]], r0, r1, gt, W)
    with rasterio.open(ctx["zones"]) as src:
        zones = src.read(1, window=Window(0, r0, W, h)).astype(np.int64)
    ci = ctx["lut"][zones]
    info = {"mask_cells_no_county": int((mask & (ci < 0)).sum())}
    m = mask & (ci >= 0)
    maps[ctx["mask_map"]] = np.where(mask, vm, 0.0)
    for k, path in ctx["maps"].items():
        if k == ctx["mask_map"]:
            continue
        a, valid = read_rows(path, r0, r1, gt, W)
        info[f"{k}_people_outside_mask"] = float(a[valid & ~mask].sum())
        info[f"{k}_mask_cells_without_value"] = int((mask & ~valid).sum())
        maps[k] = np.where(mask & valid, a, 0.0)
    bui, bvalid = read_rows(ctx["bui"], r0, r1, gt, W)
    info["bui_nodata_in_mask"] = int((m & ~bvalid).sum())
    bui = np.where(bvalid, bui, -1.0)
    nb = ecmt.read_on_box(ctx["nobuilt"], st, (h, W), crs)
    ctype = ecd.cell_types(bui, nb)
    cls, found = cell_classes(ctx["smod"], st, (h, W), crs, ctx["rb"])
    ghs = product_rows(ctx["ghs_pop"], r0, r1, gt, crs, W, ctx["tile_cols"], ctx["subpixel_m"])
    bs = product_rows(ctx["ghs_built"], r0, r1, gt, crs, W, ctx["tile_cols"], ctx["subpixel_m"])
    # per county x cell class x group
    idx = (ci * (NC * NT) + cls * NT + ctype)[m]
    L = n * NC * NT
    acc = {"cells": np.bincount(idx, minlength=L).astype(np.int64),
           "ghs": np.bincount(idx, weights=ghs[m], minlength=L), "bs": np.bincount(idx, weights=bs[m], minlength=L)}
    for k, a in maps.items():
        acc[k] = np.bincount(idx, weights=a[m], minlength=L)
    off = ~mask
    used_off = off & (ci >= 0)
    info.update(ghs_outside_mask_used=float(ghs[used_off].sum()), ghs_unused_county=float(ghs[off & (zones > 0) &
                                                                                                (ci < 0)].sum()),
                ghs_no_county=float(ghs[off & (zones == 0)].sum()), bs_outside_mask=float(bs[off].sum()),
                ghs_mask=float(ghs[m].sum()))
    ghs_off_county = np.bincount(ci[used_off], weights=ghs[used_off], minlength=n)
    # unbuilt cells
    u = m & (ctype > 0)
    ub = {"ci": ci[u].astype(np.int32), "cls": cls[u].astype(np.int8), "ctype": ctype[u].astype(np.int8),
          "ghs": ghs[u], "nobuilt": nb[u].astype(np.float32)}   # GHS kept float64 (ranks, sums)
    for k, a in maps.items():
        if k in CELL_MAPS:                                 # per cell only what overlap / capture use (memory)
            ub[k] = a[u].astype(np.float32)                # the predictions are float32 rasters: exact
    pl, pvalid = read_rows(ctx["plural"], r0, r1, gt, W)
    ub["plural"] = np.where(pvalid, pl, np.nan)[u].astype(np.float32)
    for d, path in ctx["placedist"].items():
        a, valid = read_rows(path, r0, r1, gt, W)
        ub[d] = np.where(valid, a, np.nan)[u].astype(np.float32)
    # pieces of the DEGURBA boxes in this strip (the cells degurba_boxes reads for its cell types)
    pieces = []
    for key, br, bc, size in ctx["boxes"]:
        a0, a1 = max(br, r0), min(br + size, r1)
        c0, c1 = max(bc, 0), min(bc + size, W)
        if a0 >= a1 or c0 >= c1:
            continue
        s = (slice(a0 - r0, a1 - r0), slice(c0, c1))
        pieces.append((key, a0 - br, a1 - br, c0 - bc, c1 - bc,
                       {"mask": mask[s].copy(), "ghs": ghs[s].copy(), "ctype": ctype[s].copy(),
                        **{k: maps[k][s].copy() for k in ctx["box_maps"]}}))
    return {"rows": (r0, r1), "acc": acc, "info": info, "ghs_off_county": ghs_off_county, "ub": ub,
            "pieces": pieces, "codes": found}


def run_strips(ctx: dict, rows: list, workers: int):
    """Strip results in row order (a pool of `workers` processes, or in this process)."""
    tasks = [(r.start, r.stop, ctx) for r in rows]
    if workers <= 1:
        yield from map(strip_work, tasks)
        return
    import multiprocessing as mp
    with mp.get_context("fork").Pool(workers) as pool:
        yield from pool.imap(strip_work, tasks)


# ---------------------------------------------------------------- numbers

def runs(group: np.ndarray, key: np.ndarray, n_groups: int):
    """Cells sorted by (group, key ascending): order, run starts / lengths / groups (a run = equal group and key),
    the position of each run inside its group and the group sizes."""
    order = np.lexsort((key, group))
    g, v = group[order], key[order]
    n = len(g)
    new = np.ones(n, bool)
    new[1:] = (g[1:] != g[:-1]) | (v[1:] != v[:-1])
    start = np.flatnonzero(new)
    length = np.diff(np.append(start, n))
    rg = g[start]
    gstart = np.searchsorted(g, np.arange(n_groups))
    return order, start, length, rg, start - gstart[rg], np.bincount(group, minlength=n_groups)


def capture(group: np.ndarray, score: np.ndarray, target: np.ndarray, ks, n_groups: int) -> np.ndarray:
    """(n_groups, len(ks)): target held by the top k x n_g cells of each group by score (NaN score = last); a tie
    run at the boundary contributes the fraction of its cells inside (= the expected value of a random order)."""
    s = np.where(np.isfinite(score), score, -np.inf).astype(np.float64)
    order, start, length, rg, pos, ng = runs(group, -s, n_groups)
    rt = np.add.reduceat(target.astype(np.float64)[order], start) if len(order) else np.zeros(0)
    out = np.zeros((n_groups, len(ks)))
    for j, k in enumerate(ks):
        frac = np.clip((k * ng[rg] - pos) / length, 0.0, 1.0)
        out[:, j] = np.bincount(rg, weights=rt * frac, minlength=n_groups)
    return out


def ranks_within(group: np.ndarray, x: np.ndarray, n_groups: int) -> np.ndarray:
    """Average ranks (1 = lowest) of x inside each group, minus the group's mean rank (n_g + 1) / 2."""
    order, start, length, rg, pos, ng = runs(group, x, n_groups)
    avg = pos + (length + 1) / 2.0 - (ng[rg] + 1) / 2.0
    r = np.empty(len(x))
    r[order] = np.repeat(avg, length)
    return r


def spearman_groups(group: np.ndarray, x: np.ndarray, y: np.ndarray, n_groups: int) -> np.ndarray:
    """Spearman of x and y inside each group (NaN with < 3 cells or a constant side)."""
    rx, ry = ranks_within(group, x, n_groups), ranks_within(group, y, n_groups)
    n = np.bincount(group, minlength=n_groups)
    sxy = np.bincount(group, weights=rx * ry, minlength=n_groups)
    sxx = np.bincount(group, weights=rx * rx, minlength=n_groups)
    syy = np.bincount(group, weights=ry * ry, minlength=n_groups)
    with np.errstate(invalid="ignore", divide="ignore"):
        rho = sxy / np.sqrt(sxx * syy)
    return np.where((n >= 3) & (sxx > 0) & (syy > 0), rho, np.nan)


def county_class(urban_share: np.ndarray, rural_share: np.ndarray, total: np.ndarray, rule: dict) -> np.ndarray:
    """DEGURBA level 1 on the GHS people shares: city / rural / town_suburb, no_ghs without GHS people."""
    return np.where(total <= 0, "no_ghs", np.where(urban_share >= rule["city_urban_share"], "city",
                                                   np.where(rural_share >= rule["rural_share"], "rural",
                                                            "town_suburb")))


def share(part, total):
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(total > 0, part / np.where(total > 0, total, 1), np.nan)


def county_table(used: pd.DataFrame, acc: dict, ghs_off: np.ndarray, map_keys: list, rule: dict, year: int):
    n = len(used)
    A = {k: v.reshape(n, NC, NT) for k, v in acc.items()}
    t = used[["GISJOIN", "state", "name", "status", "train"]].copy()
    t[f"census_pop_{year}"] = used["pop"].to_numpy(float)
    g = A["ghs"].sum(axis=2)
    gt = g.sum(axis=1)
    t["ghs_share_urban_centre"] = share(g[:, 2], gt)
    t["ghs_share_rural"] = share(g[:, 0], gt)
    t["county_class"] = county_class(t["ghs_share_urban_centre"].to_numpy(), t["ghs_share_rural"].to_numpy(), gt,
                                     rule)
    for i, grp in enumerate(GROUPS):
        t[f"n_cells_{grp}"] = A["cells"][:, :, i].sum(axis=1)
    for k in ["ghs", *map_keys]:
        by = A[k].sum(axis=1)
        tot = by.sum(axis=1)
        t[f"pop_{k}"] = tot
        t[f"unbuilt_share_{k}"] = share(by[:, 1] + by[:, 2], tot)
        t[f"undated_share_{k}"] = share(by[:, 1], tot)
        t[f"no_record_share_{k}"] = share(by[:, 2], tot)
    t["gap"] = t["unbuilt_share_ghs"] - t["unbuilt_share_v57"]
    t["ghs_over_census"] = share(t["pop_ghs"].to_numpy(), t[f"census_pop_{year}"].to_numpy())
    t["ghs_pop_outside_mask"] = ghs_off
    b = A["bs"].sum(axis=1)
    bt = b.sum(axis=1)
    t["built_surface_m2"] = bt
    t["bs_unbuilt_share"] = share(b[:, 1] + b[:, 2], bt)
    t["bs_undated_share"] = share(b[:, 1], bt)
    t["bs_no_record_share"] = share(b[:, 2], bt)
    return t


def overlap_by_county(ub: dict, n: int) -> pd.DataFrame:
    """degurba_boxes.overlap_metrics of v5.7 (a) and GHS-POP (b) over each county's unbuilt cells."""
    order = np.argsort(ub["ci"], kind="stable")
    c = ub["ci"][order]
    bounds = np.searchsorted(c, np.arange(n + 1))
    x, y = ub["v57"][order].astype(np.float64), ub["ghs"][order].astype(np.float64)
    rows = []
    for i in range(n):
        a, b = bounds[i], bounds[i + 1]
        if b == a:
            rows.append({"n_unbuilt_cells": 0})
            continue
        o = db.overlap_metrics(x[a:b], y[a:b])
        rows.append({"n_unbuilt_cells": o["n_cells"], "ov_dist": o["overlap_dist"], "ov_amount": o["overlap_amount"],
                     "ov_random": o["overlap_random"], "ov_spearman": o["spearman_all_cells"]})
    return pd.DataFrame(rows)


def by_class_table(ct: pd.DataFrame, acc: dict, ub: dict, map_keys: list) -> pd.DataFrame:
    """County class x cell class (+ all), cells pooled."""
    n = len(ct)
    A = {k: v.reshape(n, NC, NT) for k, v in acc.items()}
    cc = ct["county_class"].to_numpy()
    ucc = cc[ub["ci"]]
    classes = [c for c in (*COUNTY_CLASSES, "no_ghs") if (cc == c).any()] + ["all"]
    rows = []
    for c in classes:
        sel_c = np.ones(n, bool) if c == "all" else cc == c
        usel_c = np.ones(len(ucc), bool) if c == "all" else ucc == c
        for j, cl in enumerate([*CELL_CLASSES, "all"]):
            cls_idx = slice(None) if cl == "all" else [j]
            r = {"county_class": c, "cell_class": cl, "n_counties": int(sel_c.sum())}
            for i, grp in enumerate(GROUPS):
                r[f"n_cells_{grp}"] = int(A["cells"][sel_c][:, cls_idx, i].sum())
            for k in ["ghs", *map_keys, "bs"]:
                by = A[k][sel_c][:, cls_idx, :].sum(axis=(0, 1))
                tot = by.sum()
                pre = "bs" if k == "bs" else k
                r[f"{'built_surface_m2' if k == 'bs' else 'pop_' + k}"] = float(tot)
                r[f"{pre}_unbuilt_share" if k == "bs" else f"unbuilt_share_{k}"] = float(share(by[1] + by[2], tot))
                r[f"{pre}_undated_share" if k == "bs" else f"undated_share_{k}"] = float(share(by[1], tot))
                r[f"{pre}_no_record_share" if k == "bs" else f"no_record_share_{k}"] = float(share(by[2], tot))
            um = usel_c if cl == "all" else usel_c & (ub["cls"] == j)
            for k in ("v57", "pq5"):
                if k not in ub:
                    continue
                o = db.overlap_metrics(ub[k][um].astype(np.float64), ub["ghs"][um].astype(np.float64))
                r.update({f"ov_{k}_dist": o["overlap_dist"], f"ov_{k}_amount": o["overlap_amount"],
                          f"ov_{k}_random": o["overlap_random"], f"ov_{k}_spearman": o["spearman_all_cells"]})
            if cl == "all":
                gp = ct.loc[sel_c, "gap"].dropna()
                r.update(gap_median=gp.median(), gap_p10=gp.quantile(0.1), gap_p90=gp.quantile(0.9),
                         n_counties_gap=len(gp))
            rows.append(r)
    return pd.DataFrame(rows)


def scores(ub: dict, placedist: list) -> dict:
    s = {"ghs": ub["ghs"], "plural_inv": 1.0 - ub["plural"].astype(np.float64), "v57": ub["v57"]}
    if "pq5" in ub:
        s["pq5"] = ub["pq5"]
    s["nobuilt"] = ub["nobuilt"]
    for d in placedist:
        s[f"neg_{d}"] = -ub[d].astype(np.float64)
    return s


def capture_table(ct: pd.DataFrame, ub: dict, sc: dict, ks: list) -> pd.DataFrame:
    """Capture rows (within-county ranking per subset, CONUS-wide ranking for all) + Spearman rows."""
    n = len(ct)
    cc = ct["county_class"].to_numpy()
    ci = ub["ci"].astype(np.int64)
    G = np.bincount(ci, weights=ub["ghs"].astype(np.float64), minlength=n)
    ncell = np.bincount(ci, minlength=n)
    subsets = {"all": np.ones(n, bool), **{c: cc == c for c in COUNTY_CLASSES}}
    rows = []
    zero = np.zeros(len(ci), np.int64)
    for name, s in sc.items():
        nan = ~np.isfinite(s)
        cap = capture(ci, s, ub["ghs"], ks, n)
        conus = capture(zero, s, ub["ghs"], ks, 1)[0]
        ok = ~nan
        rho_c = spearman_groups(ci[ok], s[ok].astype(np.float64), ub["ghs"][ok].astype(np.float64), n)
        for sub, sel in subsets.items():
            usel = sel[ci]
            base = {"subset": sub, "score": name, "n_counties": int((sel & (ncell > 0)).sum()),
                    "n_cells": int(usel.sum()), "n_cells_no_score": int((usel & nan).sum()),
                    "ghs_unbuilt_pop": float(G[sel].sum())}
            for j, k in enumerate(ks):
                rows.append({**base, "ranking": "within_county", "metric": "capture", "k": k,
                             "value": float(cap[sel, j].sum() / G[sel].sum()) if G[sel].sum() > 0 else np.nan})
            m = usel & ok
            rho = spearman_groups(np.zeros(int(m.sum()), np.int64), s[m].astype(np.float64),
                                  ub["ghs"][m].astype(np.float64), 1)[0]
            rows.append({**base, "ranking": "pooled_cells", "metric": "spearman", "k": np.nan, "value": float(rho)})
            r = rho_c[sel]
            rows.append({**base, "ranking": "within_county", "metric": "spearman_county_median", "k": np.nan,
                         "value": float(np.nanmedian(r)) if np.isfinite(r).any() else np.nan,
                         "n_counties_rho": int(np.isfinite(r).sum())})
        Gt = float(G.sum())
        for j, k in enumerate(ks):
            rows.append({"subset": "all", "score": name, "ranking": "conus", "metric": "capture", "k": k,
                         "value": float(conus[j] / Gt) if Gt > 0 else np.nan, "n_cells": len(ci),
                         "n_cells_no_score": int(nan.sum()), "ghs_unbuilt_pop": Gt})
    for sub, sel in subsets.items():
        for rk in ("within_county", "conus") if sub == "all" else ("within_county",):
            for k in ks:
                rows.append({"subset": sub, "score": "random", "ranking": rk, "metric": "capture", "k": k, "value": k,
                             "n_counties": int((sel & (ncell > 0)).sum()), "ghs_unbuilt_pop": float(G[sel].sum())})
    cols = ["subset", "ranking", "score", "metric", "k", "value", "n_counties", "n_counties_rho", "n_cells",
            "n_cells_no_score", "ghs_unbuilt_pop"]
    t = pd.DataFrame(rows)
    return t[[c for c in cols if c in t]]


def check_capture(t: pd.DataFrame):
    c = t[t["metric"] == "capture"]
    for (sub, rk), g in c.groupby(["subset", "ranking"]):
        up = g[g["score"] == "ghs"].set_index("k")["value"]
        for sname, s in g[g["score"] != "ghs"].groupby("score"):
            v = s.set_index("k")["value"]
            bad = v[v > up.loc[v.index] + EPS]
            if len(bad):
                sys.exit(f"ERROR: capture of {sname} above the GHS upper bound ({sub}, {rk}): {bad.to_dict()}")
        r = g[g["score"] == "random"]
        if not np.allclose(r["value"], r["k"]):
            sys.exit("ERROR: random capture != k")
    log.info("  capture: the GHS score >= every other score at every k (%d subset x ranking), random = k",
             c.groupby(["subset", "ranking"]).ngroups)


def check_census(ct: pd.DataFrame, year: int):
    d = (ct["pop_v57"] - ct[f"census_pop_{year}"]).abs() / ct[f"census_pop_{year}"]
    bad = ct[~(d < 1e-6)]
    if len(bad):
        sys.exit(f"ERROR: v5.7 county sums != census {year} in {len(bad)} counties:\n"
                 f"{bad[['GISJOIN', 'pop_v57', f'census_pop_{year}']].head(20).to_string()}")
    log.info("  v5.7 county sums = census %d: %d counties, max |d| / pop %.2e", year, len(ct), float(d.max()))


def check_boxes(boxes: dict, path: Path, year: int, cols: dict):
    """Per box: people of the maps per group on the cells of its full blocks = cell_type_shares.csv (A, all)."""
    ct = pd.read_csv(path)
    ct = ct[(ct["year"] == year) & (ct["scheme"] == "A") & (ct["class"] == "all")]
    n = 0
    for key, b in boxes.items():
        full = ecm.block_sums(b["mask"].astype(np.int64), F) == F * F
        sel = np.kron(full, np.ones((F, F))).astype(bool)
        for t, tname in enumerate(ecd.CELL_TYPES):
            row = ct[(ct["box"] == key) & (ct["cell_type"] == tname)]
            if len(row) != 1:
                sys.exit(f"ERROR: {path}: no single row for {key} {year} {tname}")
            m = sel & (b["ctype"] == t)
            if int(m.sum()) != int(row["n_cells"].iloc[0]):
                sys.exit(f"ERROR: box {key} {tname}: {int(m.sum())} cells here, {int(row['n_cells'].iloc[0])} in "
                         f"{path}")
            for k, col in cols.items():
                here, there = float(b[k][m].sum()), float(row[col].iloc[0])
                if not np.isclose(here, there, rtol=1e-9, atol=1e-6):
                    sys.exit(f"ERROR: box {key} {tname} {k}: {here} here, {there} in {path} ({col})")
                n += 1
    log.info("  MATCH %s: %d box sums (%d boxes x built / undated / no_record x %s)", path, n, len(boxes),
             list(cols))


# ---------------------------------------------------------------- figures

def draw_capture(path: Path, t: pd.DataFrame, year: int):
    plots = ecm._plots()
    plt = plots.plt
    c = t[(t["metric"] == "capture") & (t["ranking"] == "within_county")]
    names = [s for s in c["score"].unique() if s != "random"]
    subs = ["all", *COUNTY_CLASSES]
    fig = plt.figure(figsize=(16.0, 4.6), dpi=150, layout="constrained")
    axes = fig.subplots(1, len(subs), sharey=True)
    for ax, sub in zip(axes, subs):
        d = c[c["subset"] == sub]
        if d.empty or not d["n_counties"].fillna(0).max():
            ax.text(0.5, 0.5, f"no {sub.replace('_', ' / ')} counties", transform=ax.transAxes, ha="center",
                    fontsize=9, color=plots.MUTED)
            ax.set_axis_off()
            continue
        ax.plot([0, 100], [0, 100], color=plots.MUTED, lw=1.0, ls="--", label="random (= k)")
        for i, s in enumerate(names):
            r = d[d["score"] == s].sort_values("k")
            ax.plot([0, *(100 * r["k"])], [0, *(100 * r["value"])], color=plots.SERIES[i % len(plots.SERIES)],
                    lw=2.0, marker="o", ms=4, ls=":" if s == "ghs" else "-",
                    label="GHS-POP itself (upper bound)" if s == "ghs" else s)
        n = d["n_counties"].iloc[0]
        ax.set_title(f"{sub.replace('_', ' / ')} counties ({int(n)})", fontsize=9, color=plots.INK)
        ax.set_xlim(0, 52)
        ax.set_ylim(0, 100)
        ax.set_xlabel("top k % of the county's unbuilt cells (by score)", fontsize=8, color=plots.INK)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(color=plots.GRID, lw=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(labelsize=7.5, colors=plots.INK)
    axes[0].set_ylabel("% of GHS-POP people on unbuilt cells held", fontsize=8, color=plots.INK)
    h, lab = axes[0].get_legend_handles_labels()
    fig.legend(h, lab, loc="outside lower center", ncol=len(lab), fontsize=8, frameon=False)
    fig.suptitle(f"{year}: do the scores pick the unbuilt (BUI = 0) cells where GHS-POP puts people? Ranking inside "
                 "each county, county classes by DEGURBA level 1 (GHS-POP, GHS-SMOD)", fontsize=9.5, color=plots.INK)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    log.info("  wrote %s", path)


def draw_gap(path: Path, ct: pd.DataFrame, gpkg: Path, year: int):
    import geopandas as gpd
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
    plots = ecm._plots()
    plt = plots.plt
    g = gpd.read_file(gpkg)[["GISJOIN", "geometry"]].merge(ct[["GISJOIN", "gap"]], on="GISJOIN", how="left")
    lim = float(np.nanquantile(np.abs(ct["gap"]), 0.98)) or 0.01
    cmap = LinearSegmentedColormap.from_list("gap", [plots.DIVERGING[0], "#ffffff", plots.DIVERGING[2]])
    fig = plt.figure(figsize=(12.0, 7.4), dpi=150, layout="constrained")
    ax = fig.subplots()
    g[g["gap"].isna()].plot(ax=ax, color="#d9d8d2", lw=0)
    g[g["gap"].notna()].plot(ax=ax, column="gap", cmap=cmap, norm=TwoSlopeNorm(0.0, -lim, lim), lw=0.05,
                             edgecolor="#bdbcb6")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=TwoSlopeNorm(0.0, -lim, lim))
    cb = fig.colorbar(sm, ax=ax, shrink=0.6, extend="both")
    cb.set_label("GHS-POP unbuilt share - v5.7 unbuilt share (of the county's people)", fontsize=8)
    ax.set_axis_off()
    ax.set_title(f"{year}: share of a county's people on unbuilt (BUI = 0) cells, GHS-POP minus v5.7\n(red = GHS-POP "
                 f"puts more there; colour range +/- {lim:.2f} = 98th percentile of |gap|; grey = no v5.7 "
                 "prediction)", fontsize=9, color=plots.INK)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    log.info("  wrote %s", path)


# ---------------------------------------------------------------- run

def run(args, cfg, mc, rb):
    import common
    year = int(mc["year"])
    model = model_settings(Path(mc["model_config"]))
    if model["version"] != mc["maps"][mc["mask_map"]]:
        sys.exit(f"ERROR: {mc['model_config']} is {model['version']}, the mask map is {mc['maps'][mc['mask_map']]}")
    rb["boxes"] = rb.get("boxes") or {}
    args.name = model["name"]                     # cutout / prediction folder name (NobuiltYear lookup reads it)
    p = inputs(args, cfg, mc, rb, model)
    block_rows = int(args.block_rows or model.get("block_rows") or 0)
    if not block_rows or block_rows % F:
        sys.exit(f"ERROR: block_rows {block_rows}: needs a multiple of {F} (whole 1 km blocks per strip)")
    if args.check:
        log.info("CHECK OK: inputs for %d (%d maps, %s), block_rows %d", year, len(mc["maps"]), list(mc["maps"]),
                 block_rows)
        return 0
    if not rb["boxes"]:
        sys.exit(f"ERROR: {args.config}: rural_boxes.boxes is empty (DEGURBA boxes not chosen)")
    log.info("RULE no threshold on GHS-POP: GHS people on unbuilt cells taken as a continuous mass; classes only from "
             "GHS-SMOD %d (block majority, scheme A: urban %s / peri_urban %s / rural %s; water / nodata excluded)",
             year, *(rb["smod"]["scheme_a"][k] for k in ("urban", "peri_urban", "rural")))
    rule = mc["county_rule"]
    log.info("RULE county class (DEGURBA level 1, 2021 manual) on GHS-POP %d of the mask cells: share on urban centre "
             "cells (30) >= %.2f -> city; else share on rural cells (11-13) >= %.2f -> rural; else town_suburb; no "
             "GHS people -> no_ghs", year, rule["city_urban_share"], rule["rural_share"])
    log.info("RULE groups: built = BUI_%d > 0; unbuilt = BUI = 0 (BUI nodata counted unbuilt, as degurba_boxes): "
             "undated = NobuiltYear > 0, no_record = 0", year)
    used, lut = counties(p, model, year)
    with rasterio.open(p[f"map_{mc['mask_map']}"]) as src:
        grid_t, crs, (H, W) = src.transform, src.crs, src.shape
    with rasterio.open(p["zones"]) as src:
        if src.transform != grid_t or src.shape != (H, W):
            sys.exit("ERROR: zones are not on the grid of the mask map")
    boxes = db.all_boxes(cfg, rb)
    box_wins = {k: ecm.box_window(grid_t, b["x"], b["y"], rb["box_km"]) for k, b in boxes.items()}
    tags = {rb["version"]: ecmt.tag(rb["version_label"]),
            **{v: ecmt.tag(lab) for v, lab in rb.get("extra_versions", {}).items()}}
    box_cols = {"ghs": "pop_ghs_pop", **{k: f"pop_{tags[v]}" for k, v in mc["maps"].items() if v in tags}}
    ctx = {"grid_t": grid_t, "crs": crs, "width": W, "n_counties": len(used), "lut": lut, "zones": p["zones"],
           "maps": {k: p[f"map_{k}"] for k in mc["maps"]}, "mask_map": mc["mask_map"], "bui": p["bui"],
           "nobuilt": p["nobuilt"], "smod": p["smod"], "rb": rb, "ghs_pop": p["ghs_pop"], "ghs_built": p["ghs_built"],
           "plural": p["plural"], "placedist": p["placedist"], "tile_cols": int(mc["tile_cols"]),
           "subpixel_m": cfg["city_maps"]["subpixel_m"],
           "boxes": [(k, int(w.row_off), int(w.col_off), int(w.width)) for k, w in box_wins.items()],
           "box_maps": [k for k in box_cols if k != "ghs"]}
    rows = common.strips((H, W), block_rows)
    log.info("grid %d x %d, %d strips of %d rows, column tiles of %d cells, %d workers, %d counties, %d boxes", H, W,
             len(rows), block_rows, mc["tile_cols"], args.workers, len(used), len(boxes))
    map_keys = list(mc["maps"])
    acc, info, ghs_off, ubl, codes = None, {}, np.zeros(len(used)), [], {}
    bx = {k: {"mask": np.zeros((w.height, w.width), bool), "ghs": np.zeros((w.height, w.width)),
              "ctype": np.full((w.height, w.width), -1, np.int64),
              **{m: np.zeros((w.height, w.width)) for m in ctx["box_maps"]}} for k, w in box_wins.items()}
    for res in run_strips(ctx, rows, args.workers):
        acc = res["acc"] if acc is None else {k: acc[k] + v for k, v in res["acc"].items()}
        for k, v in res["info"].items():
            info[k] = info.get(k, 0) + v
        ghs_off += res["ghs_off_county"]
        ubl.append(res["ub"])
        for c, v in res["codes"].items():
            codes[c] = codes.get(c, 0) + v
        for key, a0, a1, c0, c1, arrs in res["pieces"]:
            for k, a in arrs.items():
                bx[key][k][a0:a1, c0:c1] = a
        log.info("  strip rows %d-%d done", *res["rows"])
    ub = {k: np.concatenate([u[k] for u in ubl]) for k in ubl[0]}
    del ubl
    log.info("SMOD %d codes on the cells: %s", year, codes)
    log.info("mask / outside (logged, not in the tables): %s", {k: round(v, 3) if isinstance(v, float) else v
                                                                  for k, v in info.items()})
    log.info("  GHS people: %.0f on the mask cells; outside the mask %.0f on cells of used counties (water / masked), "
             "%.0f on cells of counties not used, %.0f on cells outside every county (sea, outside CONUS)",
             info["ghs_mask"], info["ghs_outside_mask_used"], info["ghs_unused_county"], info["ghs_no_county"])
    log.info("  unbuilt cells %d (undated %d, no_record %d); PLURAL missing on %d of them", len(ub["ci"]),
             int((ub["ctype"] == 1).sum()), int((ub["ctype"] == 2).sum()), int(np.isnan(ub["plural"]).sum()))
    ct = county_table(used, acc, ghs_off, map_keys, rule, year)
    ct = pd.concat([ct.reset_index(drop=True), overlap_by_county(ub, len(ct))], axis=1)
    log.info("checks (a difference stops the run before writing):")
    check_census(ct, year)
    check_boxes(bx, args.box_check, year, box_cols)
    sc = scores(ub, list(p["placedist"]))
    cap = capture_table(ct, ub, sc, mc["ks"])
    check_capture(cap)
    bc = by_class_table(ct, acc, ub, map_keys)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    ct.to_csv(out / f"county_missed_{year}.csv", index=False)
    bc.to_csv(out / f"by_class_{year}.csv", index=False)
    cap.to_csv(out / f"plural_capture_{year}.csv", index=False)
    draw_capture(out / f"capture_{year}.png", cap, year)
    draw_gap(out / f"county_gap_{year}.png", ct, p["counties"], year)
    with pd.option_context("display.width", 250, "display.max_rows", 300, "display.max_columns", 40):
        log.info("SUMMARY counties per class: %s", ct["county_class"].value_counts().to_dict())
        a = bc[bc["cell_class"] == "all"]
        log.info("SUMMARY unbuilt shares by county class (cells pooled) and county gap = GHS - v5.7:\n%s",
                 a[["county_class", "n_counties", *(f"unbuilt_share_{k}" for k in ["ghs", *map_keys]),
                    "bs_unbuilt_share", "ov_v57_dist", "ov_v57_random", "gap_median", "gap_p10", "gap_p90"]]
                 .round(4).to_string(index=False))
        log.info("SUMMARY county class x cell class (city counties' rural / peri_urban rows = metro fringe):\n%s",
                 bc[["county_class", "cell_class", "n_cells_undated", "n_cells_no_record", "pop_ghs",
                     *(f"unbuilt_share_{k}" for k in ["ghs", *map_keys]), "bs_unbuilt_share", "ov_v57_dist",
                     "ov_v57_random"]].round(4).to_string(index=False))
        c = cap[(cap["metric"] == "capture") & cap["k"].isin([0.05, 0.10, 0.20])]
        w = c.pivot_table(index=["subset", "ranking", "score"], columns="k", values="value").reset_index()
        log.info("SUMMARY capture (share of GHS people on unbuilt cells in the top k %% of cells):\n%s",
                 w.round(4).to_string(index=False))
        s = cap[cap["metric"] != "capture"].pivot_table(index=["subset", "score"], columns="metric",
                                                         values="value").reset_index()
        log.info("SUMMARY Spearman with GHS-POP on unbuilt cells (pooled cells / county median):\n%s",
                 s.round(4).to_string(index=False))
    log.info("wrote %s (3 CSV + 2 PNG)", out)
    log.info("DONE")
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    mc = mc_config(cfg)
    rb = db.rb_config(cfg)
    return run(args, cfg, mc, rb)


if __name__ == "__main__":
    sys.exit(main())
