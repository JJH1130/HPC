"""Distance-to-place layers from PLURAL-1 place populations for a study-area cutout (design: docs/dasymetric_v4_1.md).

Settings: the `place_dist:` block of configs/study_area.yaml. Reads the existing cutout's window.json and writes,
for every study year from `first_year` on, one layer per size class:
  <cutout>/layers/PLACEDIST/<name>/{YEAR}_<name>.tif   float32 km from each cell centre to the nearest place of
                                                        that class in that year (all CONUS places, not only the
                                                        window), e.g. PLACEDIST/d_250k/2020_d_250k.tif
  <cutout>/qa/place_dist_qa.csv                        QA (item, value)
  <cutout>/qa/place_dist_fills.csv                     gap fills per state and PLURAL year

Steps:
  1. Place population: the PLURAL CSV (`csv`; placeid, state_name, `pop_col` per PLURAL year; 0 = no record that
     year). Locations: the yearly PLURAL point shapefiles (`shp`, {YEAR} filled with each PLURAL year), merged to
     one point per placeid (the latest year it appears in), reprojected from the shapefile CRS (`shp_crs` if the
     file has none) to the cutout CRS.
  2. Gap fill (`fill_gaps: true`): a place with 0 in PLURAL year Y and > 0 in both neighbouring PLURAL years (the
     years before and after Y in `plural_years`; for 2010 these are 2000 and 2018) gets the mean of the two
     neighbours' original values. The first and last PLURAL years are never filled; two zeros in a row are not
     filled. Mainly New England towns missing in single decades (docs/dasymetric_v4_1.md).
  3. Size classes (`classes`: name -> [min, max), max null = no upper bound) from that population.
  4. Study year -> PLURAL year: the same year if it is a PLURAL year, else `year_map` (2020 -> 2018).
  5. Per class, nearest-place distance from every cell centre (scipy cKDTree on the cutout's projected
     coordinates, `block` rows at a time), in km.

Fails if a class has no place in a year, a PLURAL year's CSV column or shapefile is missing, or a value is not
finite. QA points (`qa_points`: lon, lat, layer, min_km and/or max_km, optional year) are logged per year; a point
outside its range is a warning, not an error.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import rasterio
from affine import Affine
from pyproj import CRS, Transformer
from scipy.spatial import cKDTree

from make_cutout import load_config, write_tif

log = logging.getLogger("place_dist")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, required=True, help="configs/study_area.yaml (its place_dist: block)")
    p.add_argument("--cutout-root", type=Path, required=True, help="cutout is <cutout-root>/<name>/")
    p.add_argument("--years", type=int, nargs="+", help="only these study years (default: all from first_year)")
    return p.parse_args(argv)


def crs_label(crs) -> str:
    """Short name of a pyproj or rasterio CRS for the log (a rasterio CRS has no .name)."""
    c = CRS.from_user_input(crs)
    return c.to_string() if c.to_epsg() else c.name


def norm_id(values) -> pd.Series:
    """placeid as text; numeric ids lose a trailing '.0' and leading zeros so CSV and shapefile ids match."""
    s = pd.Series(values).astype(str).str.strip()
    num = s.str.fullmatch(r"\d+(\.0+)?")
    s[num] = s[num].map(lambda v: str(int(float(v))))
    return s


def read_csv_any(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, low_memory=False)
    except UnicodeDecodeError:  # place names with accents in a latin-1 file
        return pd.read_csv(path, low_memory=False, encoding="latin-1")


def place_table(pcfg: dict, plural_years) -> pd.DataFrame:
    """placeid (index), place_name, state_name, one population column per PLURAL year (int, NaN -> 0)."""
    path = Path(pcfg["csv"])
    if not path.is_file():
        sys.exit(f"ERROR: place_dist.csv {path} not found")
    df = read_csv_any(path)
    cols = {c.lower(): c for c in df.columns}
    need = {"placeid", "place_name", "state_name"} | {pcfg["pop_col"].format(YEAR=y).lower() for y in plural_years}
    missing = sorted(need - set(cols))
    if missing:
        sys.exit(f"ERROR: {path}: missing columns {missing}; has {list(df.columns)[:40]}")
    out = pd.DataFrame({"placeid": norm_id(df[cols["placeid"]]), "place_name": df[cols["place_name"]],
                        "state_name": df[cols["state_name"]]})
    for y in plural_years:
        out[y] = pd.to_numeric(df[cols[pcfg["pop_col"].format(YEAR=y).lower()]], errors="coerce").fillna(0)
    dup = out["placeid"].duplicated()
    if dup.any():
        log.warning("CSV: %d duplicate placeid rows dropped (first kept), e.g. %s", int(dup.sum()),
                    out.loc[dup, "placeid"].head(5).tolist())
        out = out[~dup]
    log.info("CSV %s: %d places, PLURAL years %s", path, len(out), plural_years)
    return out.set_index("placeid")


def place_points(pcfg: dict, plural_years, crs) -> pd.DataFrame:
    """placeid (index) -> x, y in the cutout CRS, from the yearly shapefiles (latest year wins)."""
    to_xy = None
    pts = {}
    shift = []  # distance (m) between a place's points in different years, to spot moved or mis-keyed points
    for y in plural_years:
        path = Path(pcfg["shp"].format(YEAR=y))
        if not path.is_file():
            sys.exit(f"ERROR: place_dist.shp for {y}: {path} not found; folder has "
                     f"{sorted(p.name for p in path.parent.glob('*.shp'))[:20]}")
        info = pyogrio.read_info(path)
        field = next((f for f in info["fields"] if f.lower() == "placeid"), None)
        if field is None:
            sys.exit(f"ERROR: {path} has no placeid field; fields {list(info['fields'])}")
        gdf = pyogrio.read_dataframe(path, columns=[field])
        src_crs = gdf.crs if gdf.crs is not None else pcfg.get("shp_crs")
        if src_crs is None:
            sys.exit(f"ERROR: {path} has no CRS and place_dist.shp_crs is not set")
        t = Transformer.from_crs(CRS.from_user_input(src_crs), CRS.from_user_input(crs), always_xy=True)
        if to_xy is None:
            to_xy = t
            log.info("shapefile CRS %s -> cutout CRS %s", crs_label(src_crs), crs_label(crs))
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
        x, yy = t.transform(gdf.geometry.x.to_numpy(), gdf.geometry.y.to_numpy())
        ids = norm_id(gdf[field]).to_numpy()
        n_new = 0
        for pid, px, py in zip(ids, x, yy):
            if pid in pts:
                shift.append(float(np.hypot(px - pts[pid][0], py - pts[pid][1])))
            else:
                n_new += 1
            pts[pid] = (px, py)
        log.info("  %d: %s: %d points (%d placeids not seen in earlier years)", y, path.name, len(gdf), n_new)
    out = pd.DataFrame.from_dict(pts, orient="index", columns=["x", "y"])
    s = np.array(shift)
    if s.size:
        log.info("points: %d placeids; position change between years: median %.1f m, p99 %.1f m, max %.1f km, "
                 "%d > 1 km", len(out), np.median(s), np.percentile(s, 99), s.max() / 1000, int((s > 1000).sum()))
    return out


def fill_gaps(pop: pd.DataFrame, plural_years):
    """(filled population, bool frame of filled cells): 0 in an inner PLURAL year with > 0 in both neighbouring
    PLURAL years -> mean of the neighbours' original values (step 2)."""
    out = pop[plural_years].astype(float).copy()
    filled = pd.DataFrame(False, index=pop.index, columns=plural_years)
    for i in range(1, len(plural_years) - 1):
        prev, y, nxt = plural_years[i - 1], plural_years[i], plural_years[i + 1]
        hit = (pop[y] <= 0) & (pop[prev] > 0) & (pop[nxt] > 0)
        out.loc[hit, y] = (pop.loc[hit, prev] + pop.loc[hit, nxt]) / 2.0
        filled[y] = hit
    return out, filled


def class_counts(pop: pd.Series, classes: dict) -> dict:
    return {name: int(((pop >= lo) & (pop < hi)).sum()) for name, (lo, hi) in classes.items()}


def parse_classes(pcfg: dict) -> dict:
    """name -> (min, max) with max = inf for null."""
    out = {}
    for name, (lo, hi) in pcfg["classes"].items():
        out[str(name)] = (float(lo), float("inf") if hi is None else float(hi))
    return out


def nearest_km(px, py, transform: Affine, H: int, W: int, block: int, workers: int) -> np.ndarray:
    """Distance (km) from every cell centre of the H x W grid to the nearest of the points (px, py)."""
    tree = cKDTree(np.column_stack([px, py]))
    out = np.empty((H, W), dtype="float32")
    cols = np.arange(W) + 0.5
    for r0 in range(0, H, block):
        rows = np.arange(r0, min(r0 + block, H)) + 0.5
        C, R = np.meshgrid(cols, rows)
        X = transform.c + C * transform.a + R * transform.b
        Y = transform.f + C * transform.d + R * transform.e
        d, _ = tree.query(np.column_stack([X.ravel(), Y.ravel()]), k=1, workers=workers)
        out[r0:r0 + len(rows)] = (d / 1000.0).reshape(len(rows), W)
    return out


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    pcfg = cfg.get("place_dist")
    if not pcfg:
        sys.exit(f"ERROR: no place_dist: block in {args.config}")
    cut = args.cutout_root / cfg["name"]
    wpath = cut / "window.json"
    if not wpath.exists():
        sys.exit(f"ERROR: {wpath} not found (run the cutout first)")
    win = json.loads(wpath.read_text())
    crs = CRS.from_wkt(win["crs_wkt"])
    transform = Affine(*win["transform"])
    H, W = int(win["height"]), int(win["width"])

    plural_years = sorted(int(y) for y in pcfg["plural_years"])
    year_map = {int(k): int(v) for k, v in (pcfg.get("year_map") or {}).items()}
    years = [y for y in cfg["years"] if y >= int(pcfg["first_year"])]
    if args.years:
        years = [y for y in years if y in args.years]
    match = {y: (y if y in plural_years else year_map.get(y)) for y in years}
    bad = [y for y, p in match.items() if p not in plural_years]
    if bad:
        sys.exit(f"ERROR: study years {bad} have no PLURAL year (plural_years {plural_years}, year_map {year_map})")
    classes = parse_classes(pcfg)
    workers = int(os.environ.get("SLURM_CPUS_ON_NODE", "1"))
    log.info("cutout %s | window %d x %d cells | study years %s -> PLURAL %s | classes %s | fill_gaps %s | "
             "%d query workers", cut, W, H, years, [match[y] for y in years],
             {k: (int(lo), None if hi == float("inf") else int(hi)) for k, (lo, hi) in classes.items()},
             pcfg.get("fill_gaps", True), workers)

    pop_raw = place_table(pcfg, plural_years)
    pts = place_points(pcfg, plural_years, crs)
    qa = {"window_cells": H * W, "places_csv": len(pop_raw), "places_with_point": len(pts)}

    # step 2: gap fill
    if pcfg.get("fill_gaps", True):
        pop, filled = fill_gaps(pop_raw, plural_years)
    else:
        pop, filled = pop_raw[plural_years].astype(float), pd.DataFrame(False, index=pop_raw.index,
                                                                         columns=plural_years)
    by_state = filled.groupby(pop_raw["state_name"]).sum()
    by_state = by_state[(by_state > 0).any(axis=1)]
    fpath = cut / "qa" / "place_dist_fills.csv"
    fpath.parent.mkdir(parents=True, exist_ok=True)
    by_state.to_csv(fpath, index_label="state_name")
    log.info("gap fill: %d place-years filled in total; per PLURAL year %s", int(filled.values.sum()),
             {y: int(filled[y].sum()) for y in plural_years})
    if len(by_state):
        log.info("gap fills per state (states with any fill; also in %s):\n%s", fpath.name,
                 by_state.sort_values(plural_years[1:-1], ascending=False).to_string())
    big = pcfg.get("check_state", "Massachusetts")
    st = pop_raw["state_name"].astype(str).str.lower() == str(big).lower()
    lo = min(lo for lo, _ in classes.values())
    before = {y: int((pop_raw.loc[st, y] >= lo).sum()) for y in plural_years}
    after = {y: int((pop.loc[st, y] >= lo).sum()) for y in plural_years}
    log.info("%s places >= %d before fill: %s", big, lo, before)
    log.info("%s places >= %d after fill:  %s", big, lo, after)
    for y in plural_years:
        qa[f"{big} places >= {int(lo)} {y} before fill"] = before[y]
        qa[f"{big} places >= {int(lo)} {y} after fill"] = after[y]
        qa[f"filled place-years {y}"] = int(filled[y].sum())
    us = {y: (int((pop_raw[y] >= lo).sum()), int((pop[y] >= lo).sum())) for y in plural_years}
    log.info("all places >= %d (before -> after fill): %s", lo, {y: f"{a} -> {b}" for y, (a, b) in us.items()})
    fl = filled.any(axis=1) & st
    if fl.any():
        rows = pop.loc[fl, plural_years].astype(int)
        rows.insert(0, "place", pop_raw.loc[rows.index, "place_name"])
        log.info("%s places with a fill (population after fill):\n%s", big, rows.to_string())

    # steps 3-5 per study year
    inv = ~transform
    to_xy = Transformer.from_crs(4326, crs, always_xy=True)
    qpts = []
    for p in pcfg.get("qa_points") or []:
        x, y = to_xy.transform(p["lon"], p["lat"])
        c, r = inv * (x, y)
        if 0 <= r < H and 0 <= c < W:
            qpts.append((p, int(r), int(c)))
        else:
            log.warning("QA point %s is outside the window; skipped", p["name"])
    out_pat = pcfg.get("out", "PLACEDIST/{CLASS}/{YEAR}_{CLASS}.tif")
    blk = int(pcfg.get("block", 128))
    zones_any = np.zeros((H, W), bool)  # study cells (zone > 0 in any year), for the log summary
    for y in cfg["years"]:
        zp = cut / "zones" / f"zones_{y}.tif"
        if zp.exists():
            with rasterio.open(zp) as src:
                zones_any |= src.read(1) > 0
    for year in years:
        py = match[year]
        p = pop[py]
        have = p.index.intersection(pts.index)
        nopt = p[(p >= lo) & ~p.index.isin(pts.index)]
        if len(nopt):
            log.warning("%d (PLURAL %d): %d places >= %d have no point and are left out (e.g. %s)", year, py,
                        len(nopt), int(lo), pop_raw.loc[nopt.index[:5], "place_name"].tolist())
        qa[f"{year} places >= {int(lo)} without point"] = len(nopt)
        pv = p.loc[have]
        counts = class_counts(pv, classes)
        log.info("%d (PLURAL %d): places per class %s", year, py, counts)
        for name, (clo, chi) in classes.items():
            sel = pv[(pv >= clo) & (pv < chi)].index
            if not len(sel):
                sys.exit(f"ERROR: {year} (PLURAL {py}): no place in class {name}")
            d = nearest_km(pts.loc[sel, "x"].to_numpy(), pts.loc[sel, "y"].to_numpy(), transform, H, W, blk, workers)
            if not np.isfinite(d).all():
                sys.exit(f"ERROR: {year} {name}: non-finite distance")
            s = d[zones_any] if zones_any.any() else d
            qa[f"{year} {name}: places"] = len(sel)
            qa[f"{year} {name}: study min km"] = float(s.min())
            qa[f"{year} {name}: study mean km"] = float(s.mean())
            qa[f"{year} {name}: study max km"] = float(s.max())
            log.info("  %d %s: %d places | study cells km min %.1f mean %.1f max %.1f", year, name, len(sel),
                     s.min(), s.mean(), s.max())
            for q, r, c in qpts:
                if q["layer"] != name or (q.get("year") is not None and int(q["year"]) != year):
                    continue
                v = float(d[r, c])
                ok = v >= float(q.get("min_km", -np.inf)) and v <= float(q.get("max_km", np.inf))
                (log.info if ok else log.warning)("  QA point %s %d %s = %.2f km (expect %s..%s km): %s", q["name"],
                                                  year, name, v, q.get("min_km", "-"), q.get("max_km", "-"),
                                                  "ok" if ok else "NOT MET")
                qa[f"QA {q['name']} {year} {name} km"] = v
                qa[f"QA {q['name']} {year} {name}"] = "ok" if ok else "not met"
            write_tif(cut / "layers" / out_pat.format(CLASS=name, YEAR=year), d, transform, crs, None)
        log.info("wrote %d layers for %d", len(classes), year)

    qpath = cut / "qa" / "place_dist_qa.csv"
    pd.Series(qa, name="value").to_csv(qpath, index_label="item")
    log.info("wrote %s and %s", qpath, fpath)
    log.info("DONE")


if __name__ == "__main__":
    main()
