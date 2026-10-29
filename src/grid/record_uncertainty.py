"""HISDAC record uncertainty per cell and county (request 2026-10-30, docs/handoff/validation_2020_uncertainty_request.md
part C; docs/conus_plan.md "HISDAC record uncertainty"). Diagnosis only: nothing is trained, excluded or imputed.

Inputs (paths from CLI flags, sbatch/record_uncertainty.sh):
  --contemp     BUPR_contemp.tif: all ZTRAX property records, with or without a built year (~2016; downloaded by
                sbatch/hisdac_extra_download.sh into $DATA_ROOT/raw/hisdac_extra/)
  --hisdac-dir  BUPR/{YEAR}_BUPR.tif (records with a built year <= YEAR) and FBUY/NobuiltYear.tif
  --cutout      zones/zones_{ZONE_YEAR}.tif + .csv: the 2010 county polygons on the HISDAC grid (CONUS cutout)
  --features    <version>/Y<year>/county_features.csv (results/dasymetric/...): the used counties, pop and bui per year
  --split       configs/conus_split.csv (train / test county)

C2 grid and cell checks: each raster is compared with the zone grid (CRS, transform, size); a raster on another grid is
read through a WarpedVRT onto the zone grid with nearest resampling (logged; an integer shift is then exact). The
NobuiltYear value distribution decides whether it is a count (values > 1 present) or a 0/1 flag. Per cell, over cells
with any record: d = contemp - BUPR_<ref-year>, compared with NobuiltYear (d == NobuiltYear, d > it, d < it, d < 0).
C3 county ratios (sums over the county's cells, 2010 polygons):
  A      = (contemp - BUPR_<ref-year>) / contemp, fixed over the years; negative -> 0 (counted: a_negative)
  B_year = NobuiltYear / (BUPR_year + NobuiltYear), an upper bound per census year (only if NobuiltYear is a count)
C4 BUI gap counties (floor area per person < --gap-share x the year's median, as tract_validate.py) vs A: overlap per
threshold, A distribution of gap / other counties, by state.
C5 thresholds 0.1-0.9: counties kept (ratio <= threshold), their share of the year's pop, train / test counties kept
(split), gap counties kept, by state; for A (pop of every census year) and for B_year.

Writes to --out-dir (results/hisdac_uncertainty/):
  grid_check.csv                   raster, CRS / grid equal to the zones or aligned, nodata, value range
  cell_check.csv                   item, value: NobuiltYear count or flag, cell comparison of d with NobuiltYear
  nobuilt_values.csv               NobuiltYear value -> cells (0 .. 99, 100 = 100 and more), all cells / study cells
  county_record_uncertainty.csv    one row per 2010 county: sums, A, B_year, pop and gap flag per year, split part
  gap_overlap.csv, gap_ratio_distribution.csv, gap_by_state.csv          C4
  threshold_table.csv, threshold_by_state.csv, threshold_counties.png    C5
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window

log = logging.getLogger("record_uncertainty")

YEARS = list(range(1900, 2021, 10))
THRESHOLDS = [round(0.1 * k, 1) for k in range(1, 10)]
NB_MAX = 100  # NobuiltYear histogram: 0 .. 99 one bin each, 100 = 100 and more


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--contemp", type=Path, required=True, help="BUPR_contemp.tif")
    p.add_argument("--hisdac-dir", type=Path, required=True, help="HISDAC-US V2 folder (BUPR/, FBUY/)")
    p.add_argument("--cutout", type=Path, required=True, help="CONUS cutout folder (zones/)")
    p.add_argument("--zone-year", type=int, default=2010, help="zones_{YEAR}: the 2010 county polygons")
    p.add_argument("--features", type=Path, required=True,
                   help="results/dasymetric/conus/<version>: Y<year>/county_features.csv (pop, bui, used counties)")
    p.add_argument("--split", type=Path, required=True, help="configs/conus_split.csv")
    p.add_argument("--years", type=int, nargs="+", default=YEARS, help="census years for B_year and the pop shares")
    p.add_argument("--ref-year", type=int, default=2015, help="BUPR year compared with contemp (ratio A)")
    p.add_argument("--gap-share", type=float, default=0.05)
    p.add_argument("--gap-year", type=int, default=2010, help="year of the gap set compared with A (C4)")
    p.add_argument("--thresholds", type=float, nargs="+", default=THRESHOLDS)
    p.add_argument("--block-rows", type=int, default=1024)
    p.add_argument("--out-dir", type=Path, required=True)
    return p.parse_args(argv)


# ---------------------------------------------------------------- rasters on the zone grid

class Layer:
    """A raster read in row strips on the zone grid: directly when it is on that grid, else through a WarpedVRT
    (nearest). Nodata cells read as 0 (no record) and are counted."""

    def __init__(self, label: str, path: Path, grid: dict):
        if not path.exists():
            sys.exit(f"ERROR: {label}: {path} not found")
        self.label, self.path = label, path
        self.src = rasterio.open(path)
        same_crs = self.src.crs is not None and self.src.crs == grid["crs"]
        same = same_crs and self.src.transform == grid["transform"] and self.src.shape == grid["shape"]
        self.reader = self.src
        if not same:
            self.reader = WarpedVRT(self.src, crs=grid["crs"], transform=grid["transform"], width=grid["shape"][1],
                                    height=grid["shape"][0], resampling=Resampling.nearest)
        self.nodata = self.src.nodata
        self.n_nodata = 0
        self.vmin, self.vmax = np.inf, -np.inf
        self.info = {"raster": label, "path": str(path), "crs": self.src.crs.to_string() if self.src.crs else None,
                     "width": self.src.width, "height": self.src.height, "transform": tuple(self.src.transform)[:6],
                     "dtype": self.src.dtypes[0], "nodata": self.nodata, "same_crs_as_zones": bool(same_crs),
                     "on_zone_grid": bool(same), "read_as": "direct" if same else "WarpedVRT nearest onto the zones"}
        (log.info if same else log.warning)("%-14s %s | %dx%d %s | %s", label, path, self.src.width, self.src.height,
                                            self.info["crs"], self.info["read_as"])

    def read(self, rows: slice) -> np.ndarray:
        w = Window(0, rows.start, self.reader.width, rows.stop - rows.start)
        a = self.reader.read(1, window=w).astype("float64")
        bad = ~np.isfinite(a)
        if self.nodata is not None:
            bad |= a == self.nodata
        self.n_nodata += int(bad.sum())
        a[bad] = 0.0
        if a.size:
            self.vmin, self.vmax = min(self.vmin, float(a.min())), max(self.vmax, float(a.max()))
        return a

    def summary(self) -> dict:
        return {**self.info, "nodata_cells_read_as_0": self.n_nodata, "min": self.vmin, "max": self.vmax}


def hisdac_path(hisdac: Path, layer: str, year: int) -> Path:
    return hisdac / layer / f"{year}_{layer}.tif"


# ---------------------------------------------------------------- inputs from results

def county_years(features: Path, years, gap_share: float) -> dict:
    """year -> table of the used counties (GISJOIN, pop, gap flag) from Y<year>/county_features.csv."""
    out = {}
    for y in years:
        f = features / f"Y{y}" / "county_features.csv"
        if not f.exists():
            log.warning("%d: %s not found; no pop / gap for this year", y, f)
            continue
        df = pd.read_csv(f)
        df = df[df["pop"] > 0]
        cells = df["n_cells"] - (df["n_masked"] if "n_masked" in df else 0)
        floor = df["bui"] * cells / df["pop"]  # as tract_validate.gap_counties
        med = float(floor.median())
        out[y] = pd.DataFrame({"GISJOIN": df["GISJOIN"], "pop": df["pop"], "gap": floor < gap_share * med,
                               "floor_per_person": floor})
        log.info("%d: %d used counties, pop %s, gap counties (< %.0f %% of the median %.0f sq ft per person): %d",
                 y, len(df), f"{df['pop'].sum():,.0f}", 100 * gap_share, med, int(out[y]["gap"].sum()))
    return out


# ---------------------------------------------------------------- C2 + C3: strips

def accumulate(args, grid: dict, zones_path: Path, nz: int, layers: dict, years):
    """Per-county sums (bincount over zone ids < nz) + whole-window cell checks, strip by strip."""
    H = grid["shape"][0]
    sums = {}
    cell = {"window_cells": 0, "study_cells": 0, "record_cells": 0, "contemp_gt0": 0, "ref_gt0": 0, "nobuilt_gt0": 0,
            "d_eq_nobuilt": 0, "d_gt_nobuilt": 0, "d_lt_nobuilt": 0, "d_negative": 0, "d_negative_sum": 0.0,
            "d_sum": 0.0, "nobuilt_sum": 0.0, "contemp_sum": 0.0, "ref_sum": 0.0, "contemp0_ref_gt0": 0,
            "study_record_cells": 0, "study_d_eq_nobuilt": 0, "study_d_negative": 0}
    hist_all = np.zeros(NB_MAX + 1, dtype=np.int64)
    hist_study = np.zeros(NB_MAX + 1, dtype=np.int64)
    nb_frac = 0
    zsrc = rasterio.open(zones_path)
    for k, r0 in enumerate(range(0, H, args.block_rows)):
        rows = slice(r0, min(r0 + args.block_rows, H))
        z = zsrc.read(1, window=Window(0, rows.start, zsrc.width, rows.stop - rows.start)).astype(np.int64)
        if z.max() >= nz:
            sys.exit(f"ERROR: {zones_path}: zone id {int(z.max())} not in its table (max {nz - 1})")
        c = layers["contemp"].read(rows)
        ref = layers["ref"].read(rows)
        nb = layers["nobuilt"].read(rows)
        nb_frac += int(((nb > 0) & (nb != np.round(nb))).sum())
        d = c - ref
        rec = (c > 0) | (ref > 0) | (nb > 0)
        study = z > 0
        cell["window_cells"] += z.size
        cell["study_cells"] += int(study.sum())
        cell["record_cells"] += int(rec.sum())
        cell["contemp_gt0"] += int((c > 0).sum())
        cell["ref_gt0"] += int((ref > 0).sum())
        cell["nobuilt_gt0"] += int((nb > 0).sum())
        cell["d_eq_nobuilt"] += int((rec & (d == nb)).sum())
        cell["d_gt_nobuilt"] += int((rec & (d > nb)).sum())
        cell["d_lt_nobuilt"] += int((rec & (d < nb)).sum())
        cell["d_negative"] += int((rec & (d < 0)).sum())
        cell["d_negative_sum"] += float(d[d < 0].sum())
        cell["d_sum"] += float(d.sum())
        cell["nobuilt_sum"] += float(nb.sum())
        cell["contemp_sum"] += float(c.sum())
        cell["ref_sum"] += float(ref.sum())
        cell["contemp0_ref_gt0"] += int(((c == 0) & (ref > 0)).sum())
        cell["study_record_cells"] += int((rec & study).sum())
        cell["study_d_eq_nobuilt"] += int((rec & study & (d == nb)).sum())
        cell["study_d_negative"] += int((rec & study & (d < 0)).sum())
        nbi = np.clip(nb, 0, NB_MAX).astype(np.int64)
        hist_all += np.bincount(nbi.ravel(), minlength=NB_MAX + 1)
        hist_study += np.bincount(nbi[study], minlength=NB_MAX + 1)

        zz = z[study]

        def add(key, values):
            if key not in sums:
                sums[key] = np.zeros(nz)
            sums[key] += np.bincount(zz, weights=values[study], minlength=nz)

        add("n_cells", np.ones_like(c))
        add("contemp", c)
        add(f"bupr_{args.ref_year}", ref)
        add("nobuilt", nb)
        add("neg_cells", (rec & (d < 0)).astype("float64"))
        for y in years:
            add(f"bupr_{y}", layers[f"bupr_{y}"].read(rows))
        if (k + 1) % 4 == 0 or rows.stop == H:
            log.info("  rows %d-%d of %d", rows.start, rows.stop, H)
    zsrc.close()
    cell["nobuilt_fractional_cells"] = nb_frac
    return sums, cell, hist_all, hist_study


# ---------------------------------------------------------------- C4 + C5

def threshold_rows(df: pd.DataFrame, measure: str, ratio: str, year: int, cy: dict, thresholds, state: bool):
    """Counties used in `year` (cy[year]) kept at each threshold (ratio <= t; undefined ratio = no record at all:
    kept, counted in `undefined`)."""
    if year not in cy:
        return []
    u = df.merge(cy[year].rename(columns={"pop": "pop_y", "gap": "gap_y"})[["GISJOIN", "pop_y", "gap_y"]],
                 on="GISJOIN", how="inner")
    groups = [("all", u)] if not state else list(u.groupby("state"))
    rows = []
    for g, d in groups:
        tot_pop = d["pop_y"].sum()
        for t in thresholds:
            keep = ~(d[ratio] > t)  # NaN (no record) is kept
            k = d[keep]
            rows.append({"measure": measure, "year": year, "threshold": t, **({"state": g} if state else {}),
                         "counties_total": len(d), "counties_kept": int(keep.sum()),
                         "counties_share": keep.mean() if len(d) else np.nan,
                         "pop_kept": float(k["pop_y"].sum()), "pop_share": float(k["pop_y"].sum() / tot_pop)
                         if tot_pop else np.nan,
                         "train_total": int((d["part"] == "train").sum()), "train_kept": int((k["part"] == "train").sum()),
                         "test_total": int((d["part"] == "test").sum()), "test_kept": int((k["part"] == "test").sum()),
                         "gap_total": int(d["gap_y"].sum()), "gap_kept": int(k["gap_y"].sum()),
                         "undefined": int(d[ratio].isna().sum())})
    return rows


def gap_compare(df: pd.DataFrame, year: int, cy: dict, thresholds, out: Path):
    if year not in cy:
        log.warning("C4: no county features for %d; gap comparison skipped", year)
        return
    u = df.merge(cy[year][["GISJOIN", "gap", "floor_per_person"]], on="GISJOIN", how="inner")
    gap = u["gap"].astype(bool)
    rows = []
    for t in thresholds:
        hi = u["a"] > t
        rows.append({"year": year, "threshold": t, "gap_counties": int(gap.sum()), "a_above": int(hi.sum()),
                     "both": int((gap & hi).sum()), "gap_only": int((gap & ~hi).sum()),
                     "a_only": int((~gap & hi).sum()), "neither": int((~gap & ~hi).sum()),
                     "share_of_gap_above": float((gap & hi).sum() / gap.sum()) if gap.any() else np.nan,
                     "share_of_other_above": float((~gap & hi).sum() / (~gap).sum()) if (~gap).any() else np.nan})
    ov = pd.DataFrame(rows)
    ov.to_csv(out / "gap_overlap.csv", index=False)
    q = [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]
    dist = pd.DataFrame({name: u.loc[sel, "a"].quantile(q).to_numpy() for name, sel in
                         (("gap", gap), ("other", ~gap), ("all", gap | ~gap))}, index=[f"q{int(100 * v)}" for v in q])
    dist.loc["mean"] = [u.loc[sel, "a"].mean() for sel in (gap, ~gap, gap | ~gap)]
    dist.loc["n"] = [int(sel.sum()) for sel in (gap, ~gap, gap | ~gap)]
    dist.loc["undefined_a"] = [int(u.loc[sel, "a"].isna().sum()) for sel in (gap, ~gap, gap | ~gap)]
    rho = u[["a", "floor_per_person"]].corr(method="spearman").iloc[0, 1]
    dist.loc["spearman_a_vs_floor_per_person_all"] = [np.nan, np.nan, rho]
    dist.to_csv(out / "gap_ratio_distribution.csv", index_label="stat")
    st = u.groupby("state").agg(counties=("GISJOIN", "size"), gap=("gap", "sum"), a_median=("a", "median"),
                                a_mean=("a", "mean"), a_above_05=("a", lambda s: int((s > 0.5).sum())))
    st["gap_and_a_above_05"] = u[gap & (u["a"] > 0.5)].groupby("state").size().reindex(st.index).fillna(0).astype(int)
    st = st.sort_values(["gap", "a_median"], ascending=False)
    st.to_csv(out / "gap_by_state.csv")
    log.info("C4 %d: gap counties vs A (A > threshold):\n%s", year, ov.round(3).to_string(index=False))
    log.info("C4 %d: A distribution, gap vs other counties (Spearman A vs floor area per person %.3f):\n%s", year, rho,
             dist.round(3).to_string())
    log.info("C4 %d: by state (most gap counties first):\n%s", year, st.head(25).round(3).to_string())


def plot_thresholds(tt: pd.DataFrame, path: Path, b_years):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dasymetric"))
    import plots  # noqa: E402  (palette + style of the pipeline figures)
    plt = plots.plt
    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 4.8), dpi=150, layout="constrained")
    lines = [("A", 2010, "A (fixed), 2010 counties")] + [("B", y, f"B_{y} (upper bound)") for y in b_years]
    for i, (m, y, label) in enumerate(lines):
        d = tt[(tt["measure"] == m) & (tt["year"] == y)].sort_values("threshold")
        if d.empty:
            continue
        color = plots.SERIES[i % len(plots.SERIES)]
        a.plot(d["threshold"], d["counties_kept"], color=color, lw=2, marker="o", ms=5, label=label)
        b.plot(d["threshold"], 100 * d["pop_share"], color=color, lw=2, marker="o", ms=5, label=label)
    a.set_ylabel("counties kept (ratio <= threshold)", fontsize=9, color=plots.INK2)
    b.set_ylabel("population kept (% of the year's used counties)", fontsize=9, color=plots.INK2)
    for ax in (a, b):
        ax.set_xlabel("threshold on the share of records without a built year", fontsize=9, color=plots.INK2)
        ax.grid(axis="y", color=plots.GRID, lw=0.6)
        ax.set_ylim(bottom=0)
        plots._style(ax)
    a.set_title("Counties left at each threshold", fontsize=10, color=plots.INK)
    b.set_title("Population left at each threshold", fontsize=10, color=plots.INK)
    b.legend(fontsize=8, frameon=False, labelcolor=plots.INK2, loc="lower right")
    plots._save(fig, path)


# ---------------------------------------------------------------- main

def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    zpath, zcsv = args.cutout / "zones" / f"zones_{args.zone_year}.tif", args.cutout / "zones" / f"zones_{args.zone_year}.csv"
    for f in (zpath, zcsv, args.split):
        if not f.exists():
            sys.exit(f"ERROR: {f} not found")
    with rasterio.open(zpath) as z:
        grid = {"crs": z.crs, "transform": z.transform, "shape": z.shape}
    log.info("zone grid %s: %dx%d %s", zpath, grid["shape"][1], grid["shape"][0], grid["crs"].to_string())
    years = sorted(y for y in set(args.years) if hisdac_path(args.hisdac_dir, "BUPR", y).exists())
    if sorted(set(args.years)) != years:
        log.warning("BUPR years without a file (left out): %s", sorted(set(args.years) - set(years)))
    layers = {"contemp": Layer("BUPR_contemp", args.contemp, grid),
              "ref": Layer(f"BUPR_{args.ref_year}", hisdac_path(args.hisdac_dir, "BUPR", args.ref_year), grid),
              "nobuilt": Layer("NobuiltYear", args.hisdac_dir / "FBUY" / "NobuiltYear.tif", grid)}
    layers.update({f"bupr_{y}": Layer(f"BUPR_{y}", hisdac_path(args.hisdac_dir, "BUPR", y), grid) for y in years})

    zt = pd.read_csv(zcsv)
    log.info("== C2 / C3: strips of %d rows", args.block_rows)
    sums, cell, hist_all, hist_study = accumulate(args, grid, zpath, int(zt["zone_id"].max()) + 1, layers, years)
    gc = pd.DataFrame([lay.summary() for lay in layers.values()])
    gc.to_csv(out / "grid_check.csv", index=False)
    log.info("grid check:\n%s", gc.drop(columns=["path"]).to_string(index=False))

    is_count = bool(layers["nobuilt"].vmax > 1)
    cell.update({"nobuilt_max": layers["nobuilt"].vmax, "nobuilt_is_count": is_count,
                 "nobuilt_values_gt1_cells": int(hist_all[2:].sum())})
    rc = max(cell["record_cells"], 1)
    for k in ("d_eq_nobuilt", "d_gt_nobuilt", "d_lt_nobuilt", "d_negative"):
        cell[f"{k}_share_of_record_cells"] = cell[k] / rc
    pd.Series(cell, name="value").to_csv(out / "cell_check.csv", index_label="item")
    log.info("NobuiltYear: max %s -> %s; cells with a value > 1: %d", layers["nobuilt"].vmax,
             "a COUNT of records without a built year" if is_count else "a 0/1 FLAG (B_year not computed)",
             cell["nobuilt_values_gt1_cells"])
    log.info("cell check (d = contemp - BUPR_%d, over cells with any record):\n%s", args.ref_year,
             pd.Series(cell).to_string())
    pd.DataFrame({"value": np.arange(NB_MAX + 1), "cells_all": hist_all, "cells_study": hist_study}).to_csv(
        out / "nobuilt_values.csv", index=False)
    log.info("NobuiltYear values (study cells), first 12 bins: %s | 100+: %d",
             dict(zip(range(12), hist_study[:12].tolist())), int(hist_study[NB_MAX]))

    # C3 county table
    split = pd.read_csv(args.split)
    cy = county_years(args.features, sorted(set(args.years) | {args.gap_year}), args.gap_share)
    df = zt[["zone_id", "GISJOIN", "state", "name"]].copy()
    idx = df["zone_id"].to_numpy()
    for key, v in sums.items():
        df[key] = v[idx]
    df["part"] = df["GISJOIN"].map(dict(zip(split["GISJOIN"], split["part"])))
    ref = f"bupr_{args.ref_year}"
    df["a_raw"] = np.where(df["contemp"] > 0, (df["contemp"] - df[ref]) / df["contemp"].where(df["contemp"] > 0), np.nan)
    df["a_negative"] = df["a_raw"] < 0
    df["a"] = df["a_raw"].clip(lower=0)
    for y in years:
        den = df[f"bupr_{y}"] + df["nobuilt"]
        df[f"b_{y}"] = (df["nobuilt"] / den.where(den > 0)) if is_count else np.nan
    for y, t in cy.items():
        df[f"pop_{y}"] = df["GISJOIN"].map(dict(zip(t["GISJOIN"], t["pop"])))
        df[f"gap_{y}"] = df["GISJOIN"].map(dict(zip(t["GISJOIN"], t["gap"])))
    df.to_csv(out / "county_record_uncertainty.csv", index=False)
    log.info("C3: %d counties | A: %d with contemp = 0 (undefined), %d negative (set to 0), quantiles %s", len(df),
             int(df["a_raw"].isna().sum()), int(df["a_negative"].sum()),
             df["a"].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(3).to_dict())
    if df["a_negative"].any():
        log.info("  counties with contemp < BUPR_%d (first 30):\n%s", args.ref_year,
                 df[df["a_negative"]].sort_values("a_raw").head(30)[["GISJOIN", "state", "name", "contemp", ref,
                                                                     "a_raw"]].to_string(index=False))
    if is_count:
        log.info("C3: B_year median by year: %s", {y: round(float(df[f"b_{y}"].median()), 3) for y in years})

    log.info("== C4 gap counties vs A")
    gap_compare(df, args.gap_year, cy, args.thresholds, out)

    log.info("== C5 thresholds")
    tt, ts = [], []
    for y in sorted(cy):
        tt += threshold_rows(df, "A", "a", y, cy, args.thresholds, False)
        ts += threshold_rows(df, "A", "a", y, cy, args.thresholds, True)
        if is_count and y in years:
            tt += threshold_rows(df, "B", f"b_{y}", y, cy, args.thresholds, False)
            ts += threshold_rows(df, "B", f"b_{y}", y, cy, args.thresholds, True)
    tt, ts = pd.DataFrame(tt), pd.DataFrame(ts)
    tt.to_csv(out / "threshold_table.csv", index=False)
    ts.to_csv(out / "threshold_by_state.csv", index=False)
    with pd.option_context("display.width", 200):
        for m, g in tt.groupby("measure"):
            sel = g[g["year"].isin([1920, 1960, 2010, 2020])] if m == "B" else g[g["year"] == 2010]
            log.info("C5 %s:\n%s", m, sel[["year", "threshold", "counties_kept", "counties_total", "pop_share",
                                           "train_kept", "test_kept", "gap_kept", "undefined"]].round(3)
                     .to_string(index=False))
    if len(tt):
        plot_thresholds(tt, out / "threshold_counties.png", [y for y in (1920, 1960, 2010, 2020) if y in cy] if is_count else [])
    log.info("wrote %s", out)
    log.info("DONE")


if __name__ == "__main__":
    main()
