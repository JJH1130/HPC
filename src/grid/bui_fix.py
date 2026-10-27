"""Replace BUI record errors in a cutout (docs/conus_plan.md "BUI outliers", Treatment; decided 2026-10-27).

A cell with BUI > bui_cap.max (sq ft; 3e7 = about 45 x the land area of a 250 m cell) is a record error. Its BUI is
replaced by the median BUI of its 3 x 3 neighbours, the cell itself left out. Only neighbours inside the window, with
valid data and not above the cap themselves, are used; if none is left the cell gets 0. Neighbours are always the
original values, so the result does not depend on the order of the cells: each --block-rows strip is read with one
halo row above and below and gives the same cells as the whole window. BUPL, BUPR, Land_Use and the raw HISDAC files
are not changed.

Config (study area yaml):  bui_cap: {max: 3.0e7, replace: neighbour_median}.  Without it the cutout is never changed
(only --check works).

In place on <cutout-root>/<name>/: the first run moves layers/BUI/{YEAR}_BUI.tif to layers/BUI_raw/{YEAR}_BUI.tif;
every run reads BUI_raw and writes layers/BUI/{YEAR}_BUI.tif again (a rerun gives the same file); with --years only
those years are touched and bui_fix_summary.csv keeps the other years' rows. Re-cutting BUI with
make_cutout.py --layers BUI overwrites layers/BUI/: run this again afterwards.

QA (--qa-dir): bui_fix_summary.csv (one row per year: cells above the cap, replaced by 0, max before / after, BUI sum
before / after) and bui_fixed_{YEAR}.csv (every replaced cell: row, col, lon, lat, zone / county, BUI before / after,
neighbours in the window / used / above the cap, BUPL); the largest cells are logged.

--check counts only and writes nothing in the cutout (files bui_check_summary.csv, bui_check_{YEAR}.csv). With
--hisdac-dir and --window-json it reads the raw HISDAC BUI over that window (e.g. Massachusetts, whose scratch cutout
may be purged) instead of the cutout.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import CRS, Transformer
from rasterio.windows import Window

from make_cutout import load_config, resolve

log = logging.getLogger("bui_fix")

REPLACE = ("neighbour_median",)
REC_COLS = ["row", "col", "BUI_before", "BUI_after", "nb_in_window", "nb_used", "nb_over_cap"]
TOP_LOGGED = 15


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, required=True, help="study area yaml (bui_cap block)")
    p.add_argument("--cutout-root", type=Path, required=True, help="the cutout is <cutout-root>/<name>")
    p.add_argument("--qa-dir", type=Path, required=True, help="results/cutout/<name>")
    p.add_argument("--years", type=int, nargs="+", help="default: the config years")
    p.add_argument("--block-rows", type=int, default=512)
    p.add_argument("--check", action="store_true", help="count only; the cutout is not changed")
    p.add_argument("--cap", type=float, help="--check without a bui_cap block: the cap to count (default 3e7)")
    p.add_argument("--hisdac-dir", type=Path, help="--check: read the raw HISDAC BUI (needs --window-json)")
    p.add_argument("--window-json", type=Path, help="--check: window of the raw read (a cutout's window.json)")
    return p.parse_args(argv)


def cap_config(cfg: dict, args) -> float:
    block = cfg.get("bui_cap")
    if block:
        if block.get("replace", "neighbour_median") not in REPLACE:
            sys.exit(f"ERROR: bui_cap.replace {block.get('replace')!r} not in {REPLACE}")
        cap = float(block["max"])
        if args.cap is not None and args.cap != cap:
            sys.exit(f"ERROR: --cap {args.cap} differs from bui_cap.max {cap} in {args.config}")
        return cap
    if not args.check:
        sys.exit(f"ERROR: {args.config} has no bui_cap block; the cutout is not changed (use --check to count)")
    return float(args.cap if args.cap is not None else 3e7)


def fix_strip(src, base: Window, start: int, stop: int, cap: float):
    """Rows start:stop of `base` (window of src) with every cell above the cap replaced. Reads one halo row above and
    below. Returns (strip as float64, records of the replaced cells, stats of the original strip)."""
    H = int(base.height)
    lo, hi = max(start - 1, 0), min(stop + 1, H)
    a = src.read(1, window=Window(base.col_off, base.row_off + lo, base.width, hi - lo)).astype("float64")
    valid = np.isfinite(a)
    if src.nodata is not None:
        valid &= a != src.nodata
    over = valid & (a > cap)
    core = slice(start - lo, stop - lo)
    out = a[core].copy()
    recs = []
    for r, c in zip(*np.nonzero(over[core])):
        r += start - lo  # row in a
        r0, r1, c0, c1 = max(r - 1, 0), min(r + 2, a.shape[0]), max(c - 1, 0), min(c + 2, a.shape[1])
        nb, use = a[r0:r1, c0:c1], valid[r0:r1, c0:c1] & ~over[r0:r1, c0:c1]
        new = float(np.median(nb[use])) if use.any() else 0.0
        out[r - (start - lo), c] = new
        recs.append({"row": int(lo + r), "col": int(c), "BUI_before": float(a[r, c]), "BUI_after": new,
                     "nb_in_window": int(nb.size - 1), "nb_used": int(use.sum()),
                     "nb_over_cap": int(over[r0:r1, c0:c1].sum() - 1)})
    v = a[core][valid[core]]
    return out, recs, {"n": int(v.size), "pos": int((v > 0).sum()), "sum": float(v.sum()),
                       "max": float(v.max()) if v.size else -np.inf, "max_out": float(out[valid[core]].max())
                       if v.size else -np.inf}


def values_at(path: Path, rows, cols) -> list:
    with rasterio.open(path) as s:
        return [s.read(1, window=Window(int(c), int(r), 1, 1))[0, 0].item() for r, c in zip(rows, cols)]


def describe(recs: pd.DataFrame, src, base: Window, cutout: Path | None, year: int) -> pd.DataFrame:
    """lon / lat, zone and county, BUPL of the replaced cells (zone and BUPL only when the cutout has them)."""
    if recs.empty:
        return recs
    t = src.window_transform(base)
    x, y = t * (recs["col"].to_numpy() + 0.5, recs["row"].to_numpy() + 0.5)
    lon, lat = Transformer.from_crs(CRS.from_user_input(src.crs), "EPSG:4326", always_xy=True).transform(x, y)
    recs = recs.assign(lon=np.round(lon, 5), lat=np.round(lat, 5))
    if cutout is None:
        return recs
    for path, col in ((cutout / "layers" / "BUPL" / f"{year}_BUPL.tif", "BUPL"),
                      (cutout / "zones" / f"zones_{year}.tif", "zone_id")):
        if path.exists():
            recs[col] = values_at(path, recs["row"], recs["col"])
    table = cutout / "zones" / f"zones_{year}.csv"
    if "zone_id" in recs and table.exists():
        z = pd.read_csv(table, usecols=["zone_id", "GISJOIN", "state", "name", "pop"])
        recs = recs.merge(z, on="zone_id", how="left")
    return recs


def year_fix(year: int, cap: float, args, cfg: dict, cutout: Path):
    """One year: (summary row, records). Writes the capped layer unless --check."""
    raw, cur = cutout / "layers" / "BUI_raw" / f"{year}_BUI.tif", cutout / "layers" / "BUI" / f"{year}_BUI.tif"
    if args.check and args.hisdac_dir:
        layer = next(entry for entry in cfg["layers"] if entry["name"] == "BUI")
        path = resolve(layer, year, args.hisdac_dir)
        if isinstance(path, str):
            log.warning("%d: no raw BUI (%s); skipped", year, path.strip())
            return None, None
        w = json.loads(args.window_json.read_text())
        base = Window(w["col_off"], w["row_off"], w["width"], w["height"])
        source, zones_from = path, None
    else:
        if not args.check and not raw.exists():
            if not cur.exists():
                sys.exit(f"ERROR: {cur} not found (run grid_cutout first)")
            raw.parent.mkdir(parents=True, exist_ok=True)
            os.replace(cur, raw)  # the original cutout layer, kept for reruns and comparison
            log.info("%d: moved %s -> %s", year, cur, raw)
        source = raw if raw.exists() else cur
        if not source.exists():
            sys.exit(f"ERROR: {source} not found (run grid_cutout first)")
        base, zones_from = None, cutout
    with rasterio.open(source) as src:
        base = base or Window(0, 0, src.width, src.height)
        dst, part = None, None
        if not args.check:
            profile = {**src.profile, "driver": "GTiff", "compress": "deflate", "tiled": True, "blockxsize": 256,
                       "blockysize": 256, "BIGTIFF": "IF_SAFER",
                       "predictor": 3 if np.issubdtype(np.dtype(src.dtypes[0]), np.floating) else 2}
            cur.parent.mkdir(parents=True, exist_ok=True)
            part = cur.with_name(cur.name + ".part")
            dst = rasterio.open(part, "w", **profile)
        recs, n_valid, n_pos, total = [], 0, 0, 0.0
        max_before, max_after = -np.inf, -np.inf
        try:
            for start in range(0, int(base.height), args.block_rows):
                stop = min(start + args.block_rows, int(base.height))
                out, r, st = fix_strip(src, base, start, stop, cap)
                recs += r
                n_valid, n_pos, total = n_valid + st["n"], n_pos + st["pos"], total + st["sum"]
                max_before, max_after = max(max_before, st["max"]), max(max_after, st["max_out"])
                if dst is not None:
                    if np.issubdtype(np.dtype(src.dtypes[0]), np.integer):
                        out = np.rint(out)
                    dst.write(out.astype(src.dtypes[0]), 1, window=Window(0, start, int(base.width), stop - start))
        finally:
            if dst is not None:
                dst.close()
        if part is not None:
            os.replace(part, cur)  # the final name only ever holds a complete file
        df = describe(pd.DataFrame(recs, columns=REC_COLS), src, base, zones_from, year)
    before = float(df["BUI_before"].sum()) if len(df) else 0.0
    after = float(df["BUI_after"].sum()) if len(df) else 0.0
    row = {"year": year, "applied": not args.check, "cap": cap, "source": str(source), "cells_valid": n_valid,
           "cells_bui_pos": n_pos, "n_over_cap": len(df), "n_set_to_0": int((df["BUI_after"] == 0).sum()) if len(df) else 0,
           "max_before": max_before if n_valid else np.nan, "max_after": max_after if n_valid else np.nan,
           "sum_over_cap_before": before, "sum_over_cap_after": after, "bui_total_before": total,
           "bui_total_after": total - before + after,
           "share_of_total_removed": (before - after) / total if total > 0 else 0.0}
    log.info("%d: %d cells above %.3g of %d valid (%d with BUI > 0) | %d set to 0 | max %.4g -> %.4g | BUI total "
             "%.4g -> %.4g (%.3f %% removed)%s", year, row["n_over_cap"], cap, n_valid, n_pos, row["n_set_to_0"],
             row["max_before"], row["max_after"], total, row["bui_total_after"], 100 * row["share_of_total_removed"],
             "" if not args.check else " | check only, nothing written")
    if len(df):
        cols = [c for c in ["row", "col", "lon", "lat", "state", "name", "BUI_before", "BUI_after", "nb_used",
                            "nb_over_cap", "BUPL"] if c in df]
        log.info("  %d largest:\n%s", year, df.sort_values("BUI_before", ascending=False)[cols].head(TOP_LOGGED)
                 .to_string(index=False))
    return row, df.assign(year=year)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    if args.hisdac_dir and not (args.check and args.window_json):
        sys.exit("ERROR: --hisdac-dir needs --check and --window-json (the raw HISDAC files are never changed)")
    cfg = load_config(args.config)
    cap = cap_config(cfg, args)
    cutout = args.cutout_root / cfg["name"]
    years = cfg["years"] if args.years is None else sorted(set(args.years))
    log.info("study area %r | cap %.3g | %s | years %s | cutout %s", cfg["name"], cap,
             "check only" if args.check else "replace by the neighbour median (in place)", years,
             args.hisdac_dir if args.check and args.hisdac_dir else cutout)
    prefix = "bui_check" if args.check else "bui_fixed"
    args.qa_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for year in years:
        row, df = year_fix(year, cap, args, cfg, cutout)
        if row is None:
            continue
        rows.append(row)
        if len(df) or not args.check:
            df.sort_values("BUI_before", ascending=False).to_csv(args.qa_dir / f"{prefix}_{year}.csv", index=False)
    summary = pd.DataFrame(rows)
    path = args.qa_dir / ("bui_check_summary.csv" if args.check else "bui_fix_summary.csv")
    if args.years is not None and path.exists():  # --years: the other years' rows of an earlier run are kept
        old = pd.read_csv(path)
        summary = pd.concat([old[~old["year"].isin(years)], summary], ignore_index=True).sort_values("year")
    summary.to_csv(path, index=False)
    log.info("summary:\n%s", summary.drop(columns=["source"]).to_string(index=False))
    log.info("years with cells above the cap: %s", summary.loc[summary["n_over_cap"] > 0, "year"].tolist())
    log.info("wrote %s", path)
    log.info("DONE")


if __name__ == "__main__":
    main()
