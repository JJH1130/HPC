"""Zoomed cell-population maps of a few counties, several dasymetric versions side by side (CONUS request
2026-10-27, docs/conus_plan.md "v3 and v4"): do the PLURAL-1 distances move people inside a rural county towards
the empty land on the side of the nearest metro?

One PNG per county, <out-dir>/county_<GISJOIN>_<YEAR>.png, one column per --versions entry (+ a first column):
  row 1  BUI (log, grey) with the direction and distance to the nearest PLURAL place of >= --metro-pop people;
         then people per 250 m cell for each version (shared log scale)
  row 2  tract error of each version (% of observed, results/validation/<name>/<version>/tract_errors_{YEAR}.csv)
  row 3  cell difference of each later version minus the first one (people per cell, diverging)
County boundaries (zones of the cutout's census input, --counties-gpkg) and 2010 tract boundaries are drawn on
every panel. The window is the county's bounding box + --margin-km.

Inputs: the cutout (zones, BUI), <dasym-root>/<name>/<version>/predictions/pop_{YEAR}.tif, the tract errors, the
tracts and the PLURAL places of the study-area config (place_dist block). Looks only; writes PNGs + a small CSV
(<out-dir>/county_maps.csv: per county and version, cells, people, share of the county's people on cells with
BUI = 0, mean distance to the metro weighted by people).
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import yaml
from matplotlib.colors import LinearSegmentedColormap, LogNorm, TwoSlopeNorm
from rasterio.windows import Window

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dasymetric"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "grid"))
import plots  # noqa: E402  (palette and plot helpers of the dasymetric step)
from place_dist import place_points, place_table  # noqa: E402

log = logging.getLogger("county_maps")
CELL_KM2 = 0.0625


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--study-config", type=Path, required=True, help="configs/conus_study_area.yaml")
    p.add_argument("--counties", nargs="+", required=True, help="GISJOIN of the counties to draw")
    p.add_argument("--versions", nargs="+", required=True, help="first = reference of the difference panels")
    p.add_argument("--year", type=int, default=2010)
    p.add_argument("--dasym-root", type=Path, required=True)
    p.add_argument("--cutout-root", type=Path, required=True)
    p.add_argument("--counties-gpkg", type=Path, required=True, help="the census input counties_{YEAR}.gpkg")
    p.add_argument("--tract-dir", type=Path, required=True, help="folder with tracts_{YEAR}.gpkg")
    p.add_argument("--validation-root", type=Path, default=Path("results/validation"))
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--margin-km", type=float, default=5.0)
    p.add_argument("--metro-pop", type=float, default=250_000)
    return p.parse_args(argv)


def read_win(path: Path, bounds, grid=None):
    """(array float64, valid mask, window transform) of the raster inside bounds."""
    with rasterio.open(path) as src:
        if grid is not None and (src.transform != grid[0] or src.shape != grid[1]):
            sys.exit(f"ERROR: {path} is not on the zones grid")
        t = src.transform  # north-up grid: the window from the affine directly (outward to whole cells)
        c0, c1 = math.floor((bounds[0] - t.c) / t.a), math.ceil((bounds[2] - t.c) / t.a)
        r0, r1 = math.floor((bounds[3] - t.f) / t.e), math.ceil((bounds[1] - t.f) / t.e)
        win = Window(c0, r0, c1 - c0, r1 - r0)
        arr = src.read(1, window=win, boundless=True, fill_value=src.nodata if src.nodata is not None else 0)
        arr = arr.astype("float64")
        valid = np.isfinite(arr) if src.nodata is None else (arr != src.nodata) & np.isfinite(arr)
        return arr, valid, src.window_transform(win)


def metros(study_cfg: Path, year: int, min_pop: float, crs) -> pd.DataFrame:
    """PLURAL places with >= min_pop people in the PLURAL year of `year` (x, y in the cutout CRS)."""
    cfg = yaml.safe_load(study_cfg.read_text(encoding="utf-8"))
    pcfg = cfg["place_dist"]
    py = int((pcfg.get("year_map") or {}).get(year, year))
    table = place_table(pcfg, [py])
    pts = place_points(pcfg, [py], crs)
    big = table[table[py] >= min_pop].join(pts, how="inner")
    log.info("metros: %d PLURAL places with >= %d people in %d", len(big), min_pop, py)
    return big


def draw_county(gj, args, cutout, counties, tracts, places, errors, crs):
    year = args.year
    c = counties[counties["GISJOIN"] == gj]
    if c.empty:
        log.warning("%s not in %s; skipped", gj, args.counties_gpkg)
        return []
    name = f"{c['name'].iloc[0]}, {c['state'].iloc[0]}"
    x0, y0, x1, y1 = c.total_bounds
    m = args.margin_km * 1000
    bounds = (x0 - m, y0 - m, x1 + m, y1 + m)
    with rasterio.open(cutout / "zones" / f"zones_{year}.tif") as z:
        grid = (z.transform, z.shape)
    zones, _, wt = read_win(cutout / "zones" / f"zones_{year}.tif", bounds, grid)
    bui, _, _ = read_win(cutout / "layers" / "BUI" / f"{year}_BUI.tif", bounds, grid)
    zid = int(c["zone_id"].iloc[0])
    inside = zones == zid
    pops = {}
    for v in args.versions:
        arr, valid, _ = read_win(args.dasym_root / cutout.name / v / "predictions" / f"pop_{year}.tif", bounds, grid)
        pops[v] = np.where(valid, arr, np.nan)
    h, w = zones.shape
    extent = [wt.c, wt.c + w * wt.a, wt.f + h * wt.e, wt.f]

    cx, cy = c.geometry.iloc[0].representative_point().coords[0]
    d = np.hypot(places["x"] - cx, places["y"] - cy)
    near = places.loc[d.idxmin()]
    near_km = float(d.min()) / 1000
    rows_c, cols_c = np.indices(zones.shape)
    X, Y = wt.c + (cols_c + 0.5) * wt.a, wt.f + (rows_c + 0.5) * wt.e
    dist_km = np.hypot(X - near["x"], Y - near["y"]) / 1000

    summary = []
    for v, arr in pops.items():
        a = np.where(inside & np.isfinite(arr), arr, 0.0)
        tot = a.sum()
        summary.append({"GISJOIN": gj, "county": name, "version": v, "cells": int(inside.sum()), "pop": tot,
                        "share_on_bui0": a[bui == 0].sum() / tot if tot else np.nan,
                        "metro": near["place_name"], "metro_km_from_county": near_km,
                        "pop_weighted_metro_km": (a * dist_km).sum() / tot if tot else np.nan})
        log.info("  %s %-18s pop %.0f | on BUI = 0 cells %.1f %% | people-weighted km to %s %.1f", gj, v, tot,
                 100 * summary[-1]["share_on_bui0"], near["place_name"], summary[-1]["pop_weighted_metro_km"])

    plt = plots.plt
    n = len(args.versions) + 1
    aspect = (bounds[3] - bounds[1]) / (bounds[2] - bounds[0])
    fig, axes = plt.subplots(3, n, figsize=(4.2 * n, 3 * 4.2 * aspect + 1.5), dpi=150, layout="constrained")
    blues = LinearSegmentedColormap.from_list("blues", plots.BLUES)
    blues.set_bad((0, 0, 0, 0))
    div = LinearSegmentedColormap.from_list("div", plots.DIVERGING)
    tb = tracts.cx[bounds[0]:bounds[2], bounds[1]:bounds[3]]
    cb_ = counties.cx[bounds[0]:bounds[2], bounds[1]:bounds[3]]

    def frame(ax, title):
        tb.boundary.plot(ax=ax, color=plots.AXIS, lw=0.3, zorder=4)
        cb_.boundary.plot(ax=ax, color=plots.MUTED, lw=0.6, zorder=5)
        c.boundary.plot(ax=ax, color=plots.INK, lw=1.2, zorder=6)
        ax.set_xlim(bounds[0], bounds[2])
        ax.set_ylim(bounds[1], bounds[3])
        ax.set_axis_off()
        ax.set_title(title, fontsize=9, color=plots.INK)

    ax = axes[0, 0]
    b = np.ma.masked_where(bui <= 0, bui)
    ax.imshow(b, cmap="Greys", norm=LogNorm(vmin=max(float(b.min()) if b.count() else 1, 1),
                                            vmax=max(float(b.max()) if b.count() else 10, 10)),
              extent=extent, interpolation="nearest", zorder=2)
    ang = np.arctan2(near["y"] - cy, near["x"] - cx)
    L = 0.35 * min(bounds[2] - bounds[0], bounds[3] - bounds[1])
    ax.annotate("", xy=(cx + L * np.cos(ang), cy + L * np.sin(ang)), xytext=(cx, cy), zorder=7,
                arrowprops=dict(arrowstyle="->", color=plots.SERIES[1], lw=2))
    ax.text(cx + 1.05 * L * np.cos(ang), cy + 1.05 * L * np.sin(ang), f"{near['place_name']}\n{near_km:.0f} km",
            fontsize=8, color=plots.SERIES[1], ha="center", va="center", zorder=7)
    frame(ax, f"{name}: BUI {year} (log)")

    vals = np.concatenate([a[inside & np.isfinite(a) & (a > 0)] for a in pops.values()])
    vmin = max(float(np.percentile(vals, 1)) if vals.size else 1e-3, 1e-3)
    norm = LogNorm(vmin=vmin, vmax=max(float(vals.max()) if vals.size else 1, vmin * 10), clip=True)
    for i, (v, arr) in enumerate(pops.items(), 1):
        ax = axes[0, i]
        im = ax.imshow(np.ma.masked_where(~(np.isfinite(arr) & (arr > 0)), arr), cmap=blues, norm=norm,
                       extent=extent, interpolation="nearest", zorder=2)
        s = summary[i - 1]
        frame(ax, f"{v}: people per cell\non BUI = 0 cells {100 * s['share_on_bui0']:.1f} %, "
                  f"mean km to {near['place_name']} {s['pop_weighted_metro_km']:.0f}")
    cb = fig.colorbar(im, ax=axes[0, 1:].tolist(), shrink=0.8)
    cb.set_label("people per 250 m cell (log)", fontsize=8, color=plots.INK2)
    cb.ax.tick_params(which="both", labelsize=7, colors=plots.INK2)

    for ax in axes[1:, 0]:
        ax.set_axis_off()
    for i, v in enumerate(args.versions, 1):  # row 2: tract error under each version
        ax = axes[1, i]
        e = errors.get(v)
        if e is not None:
            te = tb.merge(e, on="GISJOIN", how="inner")
            te.plot(ax=ax, column=te["pct_err"].clip(-100, 100), cmap=div, zorder=2,
                    norm=TwoSlopeNorm(vmin=-100, vcenter=0, vmax=100))
        frame(ax, f"{v}: tract error, % of observed")
    sm = plt.cm.ScalarMappable(cmap=div, norm=TwoSlopeNorm(vmin=-100, vcenter=0, vmax=100))
    cbe = fig.colorbar(sm, ax=axes[1, 1:].tolist(), shrink=0.8)
    cbe.set_label("tract error, % (clipped at ±100)", fontsize=8, color=plots.INK2)
    cbe.ax.tick_params(labelsize=7, colors=plots.INK2)

    ref = args.versions[0]  # row 3: each later version minus the first, under that version
    diffs = {v: pops[v] - pops[ref] for v in args.versions[1:]}
    lim = max([float(np.nanpercentile(np.abs(dv[inside]), 99)) for dv in diffs.values()
               if np.isfinite(dv[inside]).any()] + [1e-3])
    dnorm = TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim)
    axes[2, 1].set_axis_off()
    for i, v in enumerate(args.versions[1:], 2):
        ax = axes[2, i]
        ax.imshow(np.ma.masked_where(~(inside & np.isfinite(diffs[v])), diffs[v]), cmap=div, norm=dnorm,
                  extent=extent, interpolation="nearest", zorder=2)
        frame(ax, f"{v} minus {ref}, people per cell")
    if diffs:
        sm = plt.cm.ScalarMappable(cmap=div, norm=dnorm)
        cbd = fig.colorbar(sm, ax=axes[2, 2:].tolist(), shrink=0.8)
        cbd.set_label("difference, people per cell", fontsize=8, color=plots.INK2)
        cbd.ax.tick_params(labelsize=7, colors=plots.INK2)
    plots._save(fig, args.out_dir / f"county_{gj}_{year}.png")
    return summary


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    study = yaml.safe_load(args.study_config.read_text(encoding="utf-8"))
    cutout = args.cutout_root / study["name"]
    year = args.year
    with rasterio.open(cutout / "zones" / f"zones_{year}.tif") as z:
        crs = z.crs
    counties = gpd.read_file(args.counties_gpkg, engine="pyogrio", fid_as_index=True)
    counties.index.name = "zone_id"
    counties = counties.reset_index().to_crs(crs)
    want = set(args.counties)
    tracts = gpd.read_file(args.tract_dir / f"tracts_{year}.gpkg", engine="pyogrio", columns=["GISJOIN"]).to_crs(crs)
    sel = counties[counties["GISJOIN"].isin(want)]
    if len(sel) < len(want):
        log.warning("counties not found: %s", sorted(want - set(sel["GISJOIN"])))
    x0, y0, x1, y1 = sel.total_bounds
    pad = 200_000
    tracts = tracts.cx[x0 - pad:x1 + pad, y0 - pad:y1 + pad]
    places = metros(args.study_config, year, args.metro_pop, crs)
    errors = {}
    for v in args.versions:
        path = args.validation_root / study["name"] / v / f"tract_errors_{year}.csv"
        if not path.exists():
            log.warning("no %s: %s tract error panel left empty", path, v)
            continue
        e = pd.read_csv(path, usecols=["GISJOIN", "flag", "pop_obs", "pop_model"])
        e = e[(e["flag"] == "ok") & (e["pop_obs"] > 0)]
        errors[v] = e.assign(pct_err=100 * (e["pop_model"] - e["pop_obs"]) / e["pop_obs"])[["GISJOIN", "pct_err"]]
    rows = []
    for gj in args.counties:
        rows += draw_county(gj, args, cutout, counties, tracts, places, errors, crs)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(rows)
    out.to_csv(args.out_dir / "county_maps.csv", index=False)
    log.info("summary:\n%s", out.round(3).to_string(index=False))
    log.info("DONE")


if __name__ == "__main__":
    main()
