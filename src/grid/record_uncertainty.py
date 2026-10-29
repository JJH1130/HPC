"""HISDAC record uncertainty per cell and county (request 2026-10-30, docs/handoff/validation_2020_uncertainty_request.md
part C, and docs/handoff/record_uncertainty_fallback_request.md; docs/conus_plan.md "HISDAC record uncertainty").
Diagnosis only: nothing is trained, excluded or imputed.

Inputs (paths from CLI flags, sbatch/record_uncertainty.sh):
  --contemp     BUPR_contemp.tif: all ZTRAX property records, with or without a built year (~2016). Optional: it is
                not in the Dataverse BUPR.tar (v2, checked 2026-10-30); when it is missing, the ratios that need it are
                left out and the run goes on with NobuiltYear alone
  --hisdac-dir  BUPR/{YEAR}_BUPR.tif (records with a built year <= YEAR) and FBUY/NobuiltYear.tif
  --cutout      zones/zones_{ZONE_YEAR}.tif + .csv: the 2010 county polygons on the HISDAC grid (CONUS cutout)
  --features    <version>/Y<year>/county_features.csv (results/dasymetric/...): the used counties, pop and bui per year
  --split       configs/conus_split.csv (train / test county)

C2 grid and cell checks: each raster is compared with the zone grid (CRS, transform, size); a raster on another grid is
read through a WarpedVRT onto the zone grid with nearest resampling (logged; an integer shift is then exact). A first
pass over NobuiltYear decides from its values whether it is a count (values > 1 present) or a 0/1 flag. With contemp,
per cell with any record: d = contemp - BUPR_<ref-year> vs NobuiltYear (d == NobuiltYear means the two A ratios agree
in that cell), and the two A ratios per cell.
C3 county ratios (sums over the county's cells, 2010 polygons); the column names say which definition:
  ratio_A_contemp = (contemp - BUPR_<ref-year>) / contemp, negative -> 0 (counted); needs contemp
  ratio_A_nby     = NobuiltYear / (BUPR_<ref-year> + NobuiltYear): the same share from contemp = records with a year +
                    records without one; <ref-year> 2015 is the series year nearest the ZTRAX collection (~2016).
                    ratio_A_nby_<alt-ref-year> (2020) beside it, the difference logged; needs a NobuiltYear count
  ratio_B_<year>  = NobuiltYear / (BUPR_year + NobuiltYear), an upper bound per census year; needs a NobuiltYear count
  Both A ratios -> a_compare.csv (county level; cell level in cell_check.csv).
  No contemp and a 0/1 NobuiltYear: no ratio can be computed; that fact and the value distribution are written and
  the run ends there (exit 0).
C4 BUI gap counties (floor area per person < --gap-share x the year's median, as tract_validate.py) vs each A ratio:
overlap per threshold, ratio distribution of gap / other counties, by state.
C5 thresholds 0.1-0.9 for every ratio that could be computed: counties kept (ratio <= threshold), their share of the
year's pop, train / test counties kept (split), gap counties kept, by state; A ratios with the pop of every census
year, ratio_B_<year> for its own year.

Writes to --out-dir (results/hisdac_uncertainty/):
  grid_check.csv                   raster, CRS / grid equal to the zones or aligned, nodata, value range
  cell_check.csv                   item, value: inputs found, NobuiltYear count or flag, cell checks, outcome
  nobuilt_values.csv               NobuiltYear value -> cells (0 .. 99, 100 = 100 and more), all cells / study cells
  county_record_uncertainty.csv    one row per 2010 county: sums, ratios, pop and gap flag per year, split part
  a_compare.csv, a_compare_thresholds.csv                                ratio_A_contemp vs ratio_A_nby (both needed)
  gap_overlap.csv, gap_ratio_distribution.csv, gap_by_state.csv          C4 (column measure)
  threshold_table.csv, threshold_by_state.csv, threshold_counties.png    C5 (column measure: A_contemp, A_nby, B)
"""
from __future__ import annotations

import argparse
import logging
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
A_MEASURES = (("A_contemp", "ratio_A_contemp"), ("A_nby", "ratio_A_nby"))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--contemp", type=Path, default=None, help="BUPR_contemp.tif (optional: left out when missing)")
    p.add_argument("--hisdac-dir", type=Path, required=True, help="HISDAC-US V2 folder (BUPR/, FBUY/)")
    p.add_argument("--cutout", type=Path, required=True, help="CONUS cutout folder (zones/)")
    p.add_argument("--zone-year", type=int, default=2010, help="zones_{YEAR}: the 2010 county polygons")
    p.add_argument("--features", type=Path, required=True,
                   help="results/dasymetric/conus/<version>: Y<year>/county_features.csv (pop, bui, used counties)")
    p.add_argument("--split", type=Path, required=True, help="configs/conus_split.csv")
    p.add_argument("--years", type=int, nargs="+", default=YEARS, help="census years for B_year and the pop shares")
    p.add_argument("--ref-year", type=int, default=2015, help="BUPR year of the A ratios (nearest the ZTRAX ~2016)")
    p.add_argument("--alt-ref-year", type=int, default=2020, help="ratio_A_nby also with this BUPR year (logged)")
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


def strips(H: int, block_rows: int):
    for r0 in range(0, H, block_rows):
        yield slice(r0, min(r0 + block_rows, H))


def read_zones(zsrc, rows: slice, nz: int, path: Path) -> np.ndarray:
    z = zsrc.read(1, window=Window(0, rows.start, zsrc.width, rows.stop - rows.start)).astype(np.int64)
    if z.max() >= nz:
        sys.exit(f"ERROR: {path}: zone id {int(z.max())} not in its table (max {nz - 1})")
    return z


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


# ---------------------------------------------------------------- C2: NobuiltYear first, then the strips

def nobuilt_scan(args, grid: dict, zones_path: Path, nz: int, path: Path):
    """Value distribution of NobuiltYear (own reader, so the main pass counts its nodata once): count or 0/1 flag."""
    lay = Layer("NobuiltYear", path, grid)
    hist_all = np.zeros(NB_MAX + 1, dtype=np.int64)
    hist_study = np.zeros(NB_MAX + 1, dtype=np.int64)
    frac = 0
    zsrc = rasterio.open(zones_path)
    for rows in strips(grid["shape"][0], args.block_rows):
        study = read_zones(zsrc, rows, nz, zones_path) > 0
        nb = lay.read(rows)
        frac += int(((nb > 0) & (nb != np.round(nb))).sum())
        nbi = np.clip(nb, 0, NB_MAX).astype(np.int64)
        hist_all += np.bincount(nbi.ravel(), minlength=NB_MAX + 1)
        hist_study += np.bincount(nbi[study], minlength=NB_MAX + 1)
    zsrc.close()
    is_count = bool(lay.vmax > 1)
    info = {"nobuilt_max": lay.vmax, "nobuilt_is_count": is_count, "nobuilt_values_gt1_cells": int(hist_all[2:].sum()),
            "nobuilt_fractional_cells": frac}
    log.info("NobuiltYear: max %s -> %s; cells with a value > 1: %d", lay.vmax,
             "a COUNT of records without a built year" if is_count else "a 0/1 FLAG", info["nobuilt_values_gt1_cells"])
    log.info("NobuiltYear values (study cells), first 12 bins: %s | 100+: %d",
             dict(zip(range(12), hist_study[:12].tolist())), int(hist_study[NB_MAX]))
    return lay, info, hist_all, hist_study


def accumulate(args, grid: dict, zones_path: Path, nz: int, layers: dict, bupr_years):
    """Per-county sums (bincount over zone ids < nz) + whole-window cell checks, strip by strip. layers: nobuilt,
    bupr_<year> for bupr_years (incl. the ref years) and contemp when it exists."""
    has_c = "contemp" in layers
    sums = {}
    cell = {"window_cells": 0, "study_cells": 0, "record_cells": 0, "ref_gt0": 0, "nobuilt_gt0": 0,
            "nobuilt_only_cells": 0, "nobuilt_sum": 0.0, "ref_sum": 0.0, "study_record_cells": 0}
    if has_c:
        cell.update({"contemp_gt0": 0, "d_eq_nobuilt": 0, "d_gt_nobuilt": 0, "d_lt_nobuilt": 0, "d_negative": 0,
                     "d_negative_sum": 0.0, "d_sum": 0.0, "contemp_sum": 0.0, "contemp0_ref_gt0": 0,
                     "study_d_eq_nobuilt": 0, "study_d_negative": 0, "cells_both_a": 0, "cells_a_absdiff_sum": 0.0,
                     "cells_a_within_005": 0})
    zsrc = rasterio.open(zones_path)
    H = grid["shape"][0]
    for k, rows in enumerate(strips(H, args.block_rows)):
        z = read_zones(zsrc, rows, nz, zones_path)
        b = {y: layers[f"bupr_{y}"].read(rows) for y in bupr_years}
        ref = b[args.ref_year]
        nb = layers["nobuilt"].read(rows)
        c = layers["contemp"].read(rows) if has_c else np.zeros_like(nb)
        rec = (c > 0) | (ref > 0) | (nb > 0)
        study = z > 0
        cell["window_cells"] += z.size
        cell["study_cells"] += int(study.sum())
        cell["record_cells"] += int(rec.sum())
        cell["ref_gt0"] += int((ref > 0).sum())
        cell["nobuilt_gt0"] += int((nb > 0).sum())
        cell["nobuilt_only_cells"] += int(((nb > 0) & (ref == 0)).sum())
        cell["nobuilt_sum"] += float(nb.sum())
        cell["ref_sum"] += float(ref.sum())
        cell["study_record_cells"] += int((rec & study).sum())
        if has_c:
            d = c - ref
            cell["contemp_gt0"] += int((c > 0).sum())
            cell["d_eq_nobuilt"] += int((rec & (d == nb)).sum())
            cell["d_gt_nobuilt"] += int((rec & (d > nb)).sum())
            cell["d_lt_nobuilt"] += int((rec & (d < nb)).sum())
            cell["d_negative"] += int((rec & (d < 0)).sum())
            cell["d_negative_sum"] += float(d[d < 0].sum())
            cell["d_sum"] += float(d.sum())
            cell["contemp_sum"] += float(c.sum())
            cell["contemp0_ref_gt0"] += int(((c == 0) & (ref > 0)).sum())
            cell["study_d_eq_nobuilt"] += int((rec & study & (d == nb)).sum())
            cell["study_d_negative"] += int((rec & study & (d < 0)).sum())
            both = (c > 0) & (ref + nb > 0)  # both A ratios defined in the cell
            with np.errstate(divide="ignore", invalid="ignore"):
                diff = np.abs(np.clip(d / c, 0, None) - nb / (ref + nb))[both]
            cell["cells_both_a"] += int(both.sum())
            cell["cells_a_absdiff_sum"] += float(diff.sum())
            cell["cells_a_within_005"] += int((diff <= 0.05).sum())

        zz = z[study]

        def add(key, values):
            if key not in sums:
                sums[key] = np.zeros(nz)
            sums[key] += np.bincount(zz, weights=values[study], minlength=nz)

        add("n_cells", np.ones_like(nb))
        if has_c:
            add("contemp", c)
            add("neg_cells", (rec & (d < 0)).astype("float64"))
        add("nobuilt", nb)
        for y in bupr_years:
            add(f"bupr_{y}", b[y])
        if (k + 1) % 4 == 0 or rows.stop == H:
            log.info("  rows %d-%d of %d", rows.start, rows.stop, H)
    zsrc.close()
    if has_c:
        cell["cells_a_absdiff_mean"] = cell["cells_a_absdiff_sum"] / max(cell["cells_both_a"], 1)
    return sums, cell


# ---------------------------------------------------------------- C3 comparisons, C4 + C5

def nby_alt_log(df: pd.DataFrame, ref: int, alt: int, thresholds):
    """ratio_A_nby with BUPR_<ref> vs BUPR_<alt> (log only; both columns are in the county table)."""
    a, b = df["ratio_A_nby"], df[f"ratio_A_nby_{alt}"]
    diff = (a - b).dropna()
    log.info("ratio_A_nby %d vs %d (%d counties with both): difference (%d - %d) quantiles %s, max %.3f, "
             "counties with |difference| > 0.05: %d, > 0.10: %d", ref, alt, len(diff), ref, alt,
             diff.quantile([0.1, 0.5, 0.9]).round(4).to_dict(), float(diff.abs().max()) if len(diff) else np.nan,
             int((diff.abs() > 0.05).sum()), int((diff.abs() > 0.10).sum()))
    log.info("  counties above each threshold, %d / %d: %s", ref, alt,
             {t: (int((a > t).sum()), int((b > t).sum())) for t in thresholds})


def a_compare(df: pd.DataFrame, ref: str, thresholds, out: Path):
    """ratio_A_contemp vs ratio_A_nby per county (both defined)."""
    u = df.dropna(subset=["ratio_A_contemp", "ratio_A_nby"])
    a, b = u["ratio_A_contemp"], u["ratio_A_nby"]
    diff = a - b
    s = {"counties_both": len(u), "counties_contemp_only": int(df["ratio_A_contemp"].notna().sum() - len(u)),
         "counties_nby_only": int(df["ratio_A_nby"].notna().sum() - len(u)),
         "diff_median": diff.median(), "diff_mean": diff.mean(), "absdiff_median": diff.abs().median(),
         "absdiff_q90": diff.abs().quantile(0.9), "absdiff_max": diff.abs().max(),
         "within_001": int((diff.abs() <= 0.01).sum()), "within_005": int((diff.abs() <= 0.05).sum()),
         "pearson": a.corr(b), "spearman": a.corr(b, method="spearman")}
    pd.Series(s, name="value").to_csv(out / "a_compare.csv", index_label="item")
    rows = [{"threshold": t, "both_above": int(((a > t) & (b > t)).sum()),
             "contemp_only_above": int(((a > t) & ~(b > t)).sum()), "nby_only_above": int((~(a > t) & (b > t)).sum()),
             "neither": int((~(a > t) & ~(b > t)).sum())} for t in thresholds]
    tt = pd.DataFrame(rows)
    tt.to_csv(out / "a_compare_thresholds.csv", index=False)
    log.info("ratio_A_contemp vs ratio_A_nby (county level):\n%s\n%s", pd.Series(s).round(4).to_string(),
             tt.to_string(index=False))
    if len(u):
        far = u.assign(diff=diff).reindex(diff.abs().sort_values(ascending=False).index).head(20)
        log.info("  largest differences:\n%s", far[["GISJOIN", "state", "name", "contemp", ref, "nobuilt", "ratio_A_contemp",
                                                    "ratio_A_nby", "diff"]].round(3).to_string(index=False))


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
            rows.append({"measure": measure, "ratio": ratio, "year": year, "threshold": t,
                         **({"state": g} if state else {}),
                         "counties_total": len(d), "counties_kept": int(keep.sum()),
                         "counties_share": keep.mean() if len(d) else np.nan,
                         "pop_kept": float(k["pop_y"].sum()), "pop_share": float(k["pop_y"].sum() / tot_pop)
                         if tot_pop else np.nan,
                         "train_total": int((d["part"] == "train").sum()), "train_kept": int((k["part"] == "train").sum()),
                         "test_total": int((d["part"] == "test").sum()), "test_kept": int((k["part"] == "test").sum()),
                         "gap_total": int(d["gap_y"].sum()), "gap_kept": int(k["gap_y"].sum()),
                         "undefined": int(d[ratio].isna().sum())})
    return rows


def gap_compare(df: pd.DataFrame, measure: str, ratio: str, year: int, cy: dict, thresholds):
    """Gap counties of `year` vs one A ratio -> (overlap, distribution, by state) frames with a measure column."""
    u = df.merge(cy[year][["GISJOIN", "gap", "floor_per_person"]], on="GISJOIN", how="inner")
    gap = u["gap"].astype(bool)
    r = u[ratio]
    rows = []
    for t in thresholds:
        hi = r > t
        rows.append({"measure": measure, "ratio": ratio, "year": year, "threshold": t, "gap_counties": int(gap.sum()),
                     "ratio_above": int(hi.sum()), "both": int((gap & hi).sum()), "gap_only": int((gap & ~hi).sum()),
                     "ratio_only": int((~gap & hi).sum()), "neither": int((~gap & ~hi).sum()),
                     "share_of_gap_above": float((gap & hi).sum() / gap.sum()) if gap.any() else np.nan,
                     "share_of_other_above": float((~gap & hi).sum() / (~gap).sum()) if (~gap).any() else np.nan})
    ov = pd.DataFrame(rows)
    q = [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]
    sels = (("gap", gap), ("other", ~gap), ("all", gap | ~gap))
    dist = pd.DataFrame({name: r[sel].quantile(q).to_numpy() for name, sel in sels}, index=[f"q{int(100 * v)}" for v in q])
    dist.loc["mean"] = [r[sel].mean() for _, sel in sels]
    dist.loc["n"] = [int(sel.sum()) for _, sel in sels]
    dist.loc["undefined"] = [int(r[sel].isna().sum()) for _, sel in sels]
    rho = r.corr(u["floor_per_person"], method="spearman")
    dist.loc["spearman_ratio_vs_floor_per_person_all"] = [np.nan, np.nan, rho]
    dist.insert(0, "measure", measure)
    st = u.groupby("state").agg(counties=("GISJOIN", "size"), gap=("gap", "sum"), ratio_median=(ratio, "median"),
                                ratio_mean=(ratio, "mean"), ratio_above_05=(ratio, lambda s: int((s > 0.5).sum())))
    st["gap_and_ratio_above_05"] = u[gap & (r > 0.5)].groupby("state").size().reindex(st.index).fillna(0).astype(int)
    st = st.sort_values(["gap", "ratio_median"], ascending=False)
    st.insert(0, "measure", measure)
    log.info("C4 %d %s: gap counties vs %s > threshold:\n%s", year, measure, ratio, ov.drop(columns=["measure", "ratio"])
             .round(3).to_string(index=False))
    log.info("C4 %d %s: distribution, gap vs other counties (Spearman vs floor area per person %.3f):\n%s", year,
             measure, rho, dist.drop(columns="measure").round(3).to_string())
    log.info("C4 %d %s: by state (most gap counties first):\n%s", year, measure,
             st.drop(columns="measure").head(25).round(3).to_string())
    return ov, dist, st


def plot_thresholds(tt: pd.DataFrame, path: Path, b_years):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dasymetric"))
    import plots  # noqa: E402  (palette + style of the pipeline figures)
    plt = plots.plt
    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 4.8), dpi=150, layout="constrained")
    lines = [("A_contemp", 2010, "A from contemp, 2010 counties"), ("A_nby", 2010, "A from NobuiltYear, 2010 counties")]
    lines += [("B", y, f"B_{y} (upper bound)") for y in b_years]
    i = 0
    for m, y, label in lines:
        d = tt[(tt["measure"] == m) & (tt["year"] == y)].sort_values("threshold")
        if d.empty:
            continue
        color = plots.SERIES[i % len(plots.SERIES)]
        i += 1
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

def write_cell_check(cell: dict, out: Path):
    pd.Series(cell, name="value").to_csv(out / "cell_check.csv", index_label="item")


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
    zt = pd.read_csv(zcsv)
    nz = int(zt["zone_id"].max()) + 1
    has_c = args.contemp is not None and args.contemp.exists()
    if not has_c:
        log.warning("BUPR_contemp not found (%s): ratio_A_contemp and the A comparison are left out; "
                    "the A ratio comes from NobuiltYear (ratio_A_nby)", args.contemp)

    log.info("== C2: NobuiltYear values")
    nb_path = args.hisdac_dir / "FBUY" / "NobuiltYear.tif"
    nb_scan, nb_info, hist_all, hist_study = nobuilt_scan(args, grid, zpath, nz, nb_path)
    is_count = nb_info["nobuilt_is_count"]
    pd.DataFrame({"value": np.arange(NB_MAX + 1), "cells_all": hist_all, "cells_study": hist_study}).to_csv(
        out / "nobuilt_values.csv", index=False)
    cell = {"contemp_available": has_c, **nb_info}
    if not has_c and not is_count:
        cell["outcome"] = "no ratio: BUPR_contemp missing and NobuiltYear a 0/1 flag"
        pd.DataFrame([nb_scan.summary()]).to_csv(out / "grid_check.csv", index=False)
        write_cell_check(cell, out)
        log.warning("NobuiltYear is a 0/1 flag (not a count) and BUPR_contemp is missing: neither ratio_A_nby nor "
                    "ratio_B can be computed. Written: the NobuiltYear value distribution (nobuilt_values.csv), "
                    "grid_check.csv, cell_check.csv. Not a failure.")
        log.info("DONE (NobuiltYear value distribution only)")
        return 0

    years = sorted(y for y in set(args.years) if hisdac_path(args.hisdac_dir, "BUPR", y).exists())
    if sorted(set(args.years)) != years:
        log.warning("BUPR years without a file (left out): %s", sorted(set(args.years) - set(years)))
    alt = args.alt_ref_year if is_count and hisdac_path(args.hisdac_dir, "BUPR", args.alt_ref_year).exists() else None
    if is_count and alt is None:
        log.warning("BUPR_%d not found: ratio_A_nby_%d left out", args.alt_ref_year, args.alt_ref_year)
    bupr_years = sorted(set(years) | {args.ref_year} | ({alt} if alt else set()))
    layers = {"nobuilt": Layer("NobuiltYear", nb_path, grid)}
    if has_c:
        layers["contemp"] = Layer("BUPR_contemp", args.contemp, grid)
    layers.update({f"bupr_{y}": Layer(f"BUPR_{y}", hisdac_path(args.hisdac_dir, "BUPR", y), grid) for y in bupr_years})

    log.info("== C2 / C3: strips of %d rows", args.block_rows)
    sums, cc = accumulate(args, grid, zpath, nz, layers, bupr_years)
    cell.update(cc)
    gc = pd.DataFrame([lay.summary() for lay in layers.values()])
    gc.to_csv(out / "grid_check.csv", index=False)
    log.info("grid check:\n%s", gc.drop(columns=["path"]).to_string(index=False))
    rc = max(cell["record_cells"], 1)
    for k in ("d_eq_nobuilt", "d_gt_nobuilt", "d_lt_nobuilt", "d_negative", "nobuilt_only_cells"):
        if k in cell:
            cell[f"{k}_share_of_record_cells"] = cell[k] / rc
    cell["outcome"] = "ratios: " + ", ".join(
        (["A_contemp"] if has_c else []) + (["A_nby", "B"] if is_count else []))
    write_cell_check(cell, out)
    log.info("cell check%s:\n%s", f" (d = contemp - BUPR_{args.ref_year}, over cells with any record)" if has_c else "",
             pd.Series(cell).to_string())

    # C3 county table
    split = pd.read_csv(args.split)
    cy = county_years(args.features, sorted(set(args.years) | {args.gap_year}), args.gap_share)
    df = zt[["zone_id", "GISJOIN", "state", "name"]].copy()
    idx = df["zone_id"].to_numpy()
    for key, v in sums.items():
        df[key] = v[idx]
    df["part"] = df["GISJOIN"].map(dict(zip(split["GISJOIN"], split["part"])))
    ref = f"bupr_{args.ref_year}"
    measures = []
    if has_c:
        df["ratio_A_contemp_raw"] = np.where(df["contemp"] > 0, (df["contemp"] - df[ref]) /
                                             df["contemp"].where(df["contemp"] > 0), np.nan)
        df["ratio_A_contemp_negative"] = df["ratio_A_contemp_raw"] < 0
        df["ratio_A_contemp"] = df["ratio_A_contemp_raw"].clip(lower=0)
        measures.append(A_MEASURES[0])
        log.info("C3 ratio_A_contemp: %d counties with contemp = 0 (undefined), %d negative (set to 0), quantiles %s",
                 int(df["ratio_A_contemp_raw"].isna().sum()), int(df["ratio_A_contemp_negative"].sum()),
                 df["ratio_A_contemp"].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(3).to_dict())
        if df["ratio_A_contemp_negative"].any():
            log.info("  counties with contemp < BUPR_%d (first 30):\n%s", args.ref_year,
                     df[df["ratio_A_contemp_negative"]].sort_values("ratio_A_contemp_raw").head(30)[
                         ["GISJOIN", "state", "name", "contemp", ref, "ratio_A_contemp_raw"]].to_string(index=False))
    if is_count:
        def share(y):
            den = df[f"bupr_{y}"] + df["nobuilt"]
            return df["nobuilt"] / den.where(den > 0)
        df["ratio_A_nby"] = share(args.ref_year)
        if alt:
            df[f"ratio_A_nby_{alt}"] = share(alt)
        for y in years:
            df[f"ratio_B_{y}"] = share(y)
        measures.append(A_MEASURES[1])
        log.info("C3 ratio_A_nby (NobuiltYear / (BUPR_%d + NobuiltYear)): %d undefined (no record), quantiles %s",
                 args.ref_year, int(df["ratio_A_nby"].isna().sum()),
                 df["ratio_A_nby"].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(3).to_dict())
        log.info("C3 ratio_B_year median by year: %s", {y: round(float(df[f"ratio_B_{y}"].median()), 3) for y in years})
        if alt:
            nby_alt_log(df, args.ref_year, alt, args.thresholds)
    for y, t in cy.items():
        df[f"pop_{y}"] = df["GISJOIN"].map(dict(zip(t["GISJOIN"], t["pop"])))
        df[f"gap_{y}"] = df["GISJOIN"].map(dict(zip(t["GISJOIN"], t["gap"])))
    df.to_csv(out / "county_record_uncertainty.csv", index=False)
    log.info("C3: %d counties -> county_record_uncertainty.csv", len(df))
    if has_c and is_count:
        a_compare(df, ref, args.thresholds, out)

    log.info("== C4 gap counties vs the A ratios")
    if args.gap_year in cy:
        parts = [gap_compare(df, m, r, args.gap_year, cy, args.thresholds) for m, r in measures]
        pd.concat([p[0] for p in parts]).to_csv(out / "gap_overlap.csv", index=False)
        pd.concat([p[1] for p in parts]).to_csv(out / "gap_ratio_distribution.csv", index_label="stat")
        pd.concat([p[2] for p in parts]).to_csv(out / "gap_by_state.csv")
    else:
        log.warning("C4: no county features for %d; gap comparison skipped", args.gap_year)

    log.info("== C5 thresholds")
    tt, ts = [], []
    for y in sorted(cy):
        for m, r in measures:
            tt += threshold_rows(df, m, r, y, cy, args.thresholds, False)
            ts += threshold_rows(df, m, r, y, cy, args.thresholds, True)
        if is_count and y in years:
            tt += threshold_rows(df, "B", f"ratio_B_{y}", y, cy, args.thresholds, False)
            ts += threshold_rows(df, "B", f"ratio_B_{y}", y, cy, args.thresholds, True)
    tt, ts = pd.DataFrame(tt), pd.DataFrame(ts)
    tt.to_csv(out / "threshold_table.csv", index=False)
    ts.to_csv(out / "threshold_by_state.csv", index=False)
    if len(tt):
        with pd.option_context("display.width", 200):
            for m, g in tt.groupby("measure"):
                sel = g[g["year"].isin([1920, 1960, 2010, 2020])] if m == "B" else g[g["year"] == 2010]
                log.info("C5 %s:\n%s", m, sel[["year", "threshold", "counties_kept", "counties_total", "pop_share",
                                               "train_kept", "test_kept", "gap_kept", "undefined"]].round(3)
                         .to_string(index=False))
        plot_thresholds(tt, out / "threshold_counties.png",
                        [y for y in (1920, 1960, 2010, 2020) if y in cy] if is_count else [])
    log.info("wrote %s", out)
    log.info("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
