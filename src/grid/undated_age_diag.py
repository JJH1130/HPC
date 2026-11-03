"""Are the HISDAC records without a built year older buildings? (request 2026-11-04, docs/handoff/v54_nby_request.md part
3; docs/conus_plan.md "v5.4 + NobuiltYear (no filter)"). Diagnosis only: no model, nothing goes into a feature or a
config. Background: nby_age (NobuiltYear x the county's BUPR_year / BUPR_2015) did worse than nby, so the assumption
"undated records have the same age distribution as the dated records of the county" may be wrong.

Cell level (--hisdac-dir + --cutout; rasters read in row strips on the zone grid, record_uncertainty.Layer: a raster on
another grid through a WarpedVRT, nearest; nodata = 0): over the study cells (2010 county zone > 0) with a building
(BUPR_<ref> > 0 or NobuiltYear > 0), the HISDAC FBUY (first built-up year, FBUY/FBUY.tif; 0 / nodata = none) of
  nb_gt0        NobuiltYear > 0 (any)
  nb_eq0        NobuiltYear = 0 (so BUPR_<ref> > 0)
  nb_gt0_dated  NobuiltYear > 0 and BUPR_<ref> > 0 (the cells of nb_gt0 that also have dated records)
  nb_only       NobuiltYear > 0 and BUPR_<ref> = 0 (no dated record: FBUY mostly none; counted apart)
items: cells, cells with an FBUY year (fbuy_cells) and without (fbuy_none), FBUY quantiles q05 ... q95 + mean over the
cells with a year (exact, from a histogram of whole years), share of those cells by decade (share_1800s ... share_2010s,
share_before_1800), share with FBUY <= --early-year (1940).
County level (--county-table = county_record_uncertainty.csv, tracked): Spearman (average ranks of ties) between
ratio_A_nby (NobuiltYear / (BUPR_<ref> + NobuiltYear)) and the early share of the dated records BUPR_<early> /
BUPR_<ref>, over counties with BUPR_<ref> > 0 (all, and those with NobuiltYear > 0); the median early share per
ratio_A_nby band. Without the raster flags the cell rows of an earlier run in the output are kept.

Writes --out-dir/undated_age_diag.csv (level, group, item, value) + log.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("undated_age_diag")

QUANTILES = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]
YMAX = 2100  # histogram of whole FBUY years 0 .. YMAX
GROUPS = ("nb_gt0", "nb_eq0", "nb_gt0_dated", "nb_only")
BANDS = [0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]
OUT = "undated_age_diag.csv"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hisdac-dir", type=Path, help="HISDAC-US V2 folder (FBUY/FBUY.tif, FBUY/NobuiltYear.tif, BUPR/)")
    p.add_argument("--cutout", type=Path, help="CONUS cutout folder (zones/zones_<zone-year>.tif + .csv)")
    p.add_argument("--zone-year", type=int, default=2010)
    p.add_argument("--ref-year", type=int, default=2015, help="BUPR year of 'has dated records' and of ratio_A_nby")
    p.add_argument("--early-year", type=int, default=1940)
    p.add_argument("--county-table", type=Path,
                   default=Path("results/hisdac_uncertainty/county_record_uncertainty.csv"))
    p.add_argument("--block-rows", type=int, default=1024)
    p.add_argument("--out-dir", type=Path, default=Path("results/hisdac_uncertainty"))
    return p.parse_args(argv)


# ---------------------------------------------------------------- cells

def hist_quantile(h: np.ndarray, q: float) -> float:
    """Lower q-quantile of integer values with counts h (value = index): the smallest v with cum(v) >= q x n."""
    c = np.cumsum(h)
    return float(np.searchsorted(c, q * c[-1], side="left")) if c[-1] else np.nan


def hist_rows(group: str, n_cells: int, h: np.ndarray, early: int) -> list[dict]:
    """Rows of one group from its FBUY histogram (index 0 = none)."""
    yrs = h.copy()
    yrs[0] = 0
    n = int(yrs.sum())
    rows = [("cells", n_cells), ("fbuy_cells", n), ("fbuy_none", int(h[0]))]
    for q in QUANTILES:
        rows.append((f"q{int(round(q * 100)):02d}", hist_quantile(yrs, q)))
    v = np.arange(len(yrs))
    rows.append(("mean", float((v * yrs).sum() / n) if n else np.nan))
    rows.append(("share_before_1800", float(yrs[1:1800].sum() / n) if n else np.nan))
    for d0 in range(1800, 2020, 10):
        rows.append((f"share_{d0}s", float(yrs[d0:d0 + 10].sum() / n) if n else np.nan))
    rows.append((f"share_le_{early}", float(yrs[1:early + 1].sum() / n) if n else np.nan))
    return [{"level": "cell", "group": group, "item": k, "value": val} for k, val in rows]


def cell_part(args) -> list[dict]:
    import rasterio
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from record_uncertainty import Layer, read_zones, strips
    zpath = args.cutout / "zones" / f"zones_{args.zone_year}.tif"
    zcsv = args.cutout / "zones" / f"zones_{args.zone_year}.csv"
    for f in (zpath, zcsv):
        if not f.exists():
            sys.exit(f"ERROR: {f} not found")
    with rasterio.open(zpath) as z:
        grid = {"crs": z.crs, "transform": z.transform, "shape": z.shape}
    nz = int(pd.read_csv(zcsv)["zone_id"].max()) + 1
    lay = {"fbuy": Layer("FBUY", args.hisdac_dir / "FBUY" / "FBUY.tif", grid),
           "nb": Layer("NobuiltYear", args.hisdac_dir / "FBUY" / "NobuiltYear.tif", grid),
           "ref": Layer(f"BUPR_{args.ref_year}", args.hisdac_dir / "BUPR" / f"{args.ref_year}_BUPR.tif", grid)}
    hist = {g: np.zeros(YMAX + 1, dtype=np.int64) for g in GROUPS}
    ncell = dict.fromkeys(GROUPS, 0)
    built = 0
    bad_year = 0
    zsrc = rasterio.open(zpath)
    H = grid["shape"][0]
    for k, rows in enumerate(strips(H, args.block_rows)):
        study = read_zones(zsrc, rows, nz, zpath) > 0
        fb, nb, ref = lay["fbuy"].read(rows), lay["nb"].read(rows), lay["ref"].read(rows)
        b = study & ((ref > 0) | (nb > 0))
        built += int(b.sum())
        fy = np.rint(fb).astype(np.int64)
        odd = (fy < 0) | (fy > YMAX)
        bad_year += int((odd & b).sum())
        fy = np.where(odd, 0, fy)
        masks = {"nb_gt0": b & (nb > 0), "nb_eq0": b & (nb <= 0), "nb_gt0_dated": b & (nb > 0) & (ref > 0),
                 "nb_only": b & (nb > 0) & (ref <= 0)}
        for g, m in masks.items():
            ncell[g] += int(m.sum())
            hist[g] += np.bincount(fy[m], minlength=YMAX + 1)
        if (k + 1) % 4 == 0 or rows.stop == H:
            log.info("  rows %d-%d of %d", rows.start, rows.stop, H)
    zsrc.close()
    for name, ly in lay.items():
        log.info("  %s: %s", name, ly.summary())
    if bad_year:
        log.warning("%d built cells with an FBUY value outside 0 .. %d (counted as none)", bad_year, YMAX)
    out = [{"level": "cell", "group": "built", "item": "cells", "value": built},
           {"level": "cell", "group": "built", "item": "fbuy_out_of_range", "value": bad_year}]
    for g in GROUPS:
        out += hist_rows(g, ncell[g], hist[g], args.early_year)
    return out


# ---------------------------------------------------------------- counties

def spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return np.nan
    ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


def county_part(args) -> list[dict]:
    t = pd.read_csv(args.county_table)
    ref, early = f"bupr_{args.ref_year}", f"bupr_{args.early_year}"
    for c in (ref, early, "nobuilt", "ratio_A_nby"):
        if c not in t:
            sys.exit(f"ERROR: {args.county_table} has no column {c}")
    d = t[t[ref] > 0].copy()
    d["early_share"] = d[early] / d[ref]
    d = d[np.isfinite(d["ratio_A_nby"])]
    rows = []
    for g, m in (("ref_gt0", np.ones(len(d), bool)), ("ref_gt0_nb_gt0", (d["nobuilt"] > 0).to_numpy())):
        s = d[m]
        rho = spearman(s["ratio_A_nby"].to_numpy(), s["early_share"].to_numpy())
        rows += [{"level": "county", "group": g, "item": "counties", "value": len(s)},
                 {"level": "county", "group": g, "item": f"spearman_ratio_A_nby_vs_{early}_share", "value": rho}]
        log.info("county %s: %d counties, Spearman(ratio_A_nby, %s / %s) = %.4f", g, len(s), early, ref, rho)
    labels = [f"ratio_A_nby_{lo:g}_{hi:g}" for lo, hi in zip(BANDS[:-1], BANDS[1:])]  # first band includes 0
    band = pd.cut(d["ratio_A_nby"], BANDS, include_lowest=True, labels=labels)
    for name, s in d.groupby(band, observed=False):
        rows += [{"level": "county", "group": name, "item": "counties", "value": len(s)},
                 {"level": "county", "group": name, "item": f"median_{early}_share",
                  "value": float(s["early_share"].median()) if len(s) else np.nan}]
    return rows


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    if not args.county_table.exists():
        sys.exit(f"ERROR: {args.county_table} not found (src/grid/record_uncertainty.py)")
    out = args.out_dir / OUT
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.hisdac_dir and args.cutout:
        log.info("== cells: FBUY of built cells with / without undated records (strips of %d rows)", args.block_rows)
        rows = cell_part(args)
    elif out.exists():
        log.info("== cells: kept from %s (no --hisdac-dir / --cutout)", out)
        old = pd.read_csv(out)
        rows = old[old["level"] == "cell"].to_dict("records")
    else:
        log.warning("== cells: no rasters given and no %s; county rows only", out)
        rows = []
    log.info("== counties: ratio_A_nby vs the early share of the dated records")
    rows += county_part(args)
    t = pd.DataFrame(rows)
    t.to_csv(out, index=False)
    c = t[t["level"] == "cell"]
    with pd.option_context("display.width", 200, "display.max_rows", 200):
        if len(c):
            log.info("SUMMARY FBUY of built cells (study cells with BUPR_%d > 0 or NobuiltYear > 0) by group:\n%s",
                     args.ref_year, c.pivot_table(index="item", columns="group", values="value", sort=False)
                     .reindex(columns=[g for g in GROUPS if g in set(c["group"])]).to_string())
        log.info("SUMMARY counties:\n%s", t[t["level"] == "county"].to_string(index=False))
    log.info("wrote %s", out)
    log.info("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
