"""Where are the JRC no-data pixels (occurrence > 100, usually 255)? Diagnostic for the v3.1 water mask.

The JRC Data Users Guide does not define 255 in the occurrence layer, so this checks it on our data. Uses the
same tiles, grid and area weighting as src/grid/water_frac.py (settings: `water:` block of
configs/study_area.yaml) and writes to <cutout>/qa/:
  jrc_nodata_frac.tif        share of JRC no-data 30 m pixels per 250 m cell (float32, 0-1; NaN = no tile)
  jrc_nodata_by_county.csv   per year and county (all statuses): cells, no-data share, cells with any no-data,
                             no-data km2, of which more than --edge-km inside the study area, max distance (km)
                             of a no-data cell from the study-area edge (cells outside all counties that year)
  jrc_nodata_map.png         left: no-data share over the window; right: no-data cells inside the study counties,
                             split into "within --edge-km of the study-area edge" and "farther inside"
Nothing in the cutout layers is changed.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from pyproj import CRS
from rasterio.warp import transform_bounds
from scipy import ndimage

from make_cutout import load_config, write_tif
from water_frac import cell_shares, jrc_tiles

log = logging.getLogger("jrc_nodata_check")
CELL_KM = 0.25
# dataviz reference palette: sequential blue ramp, categorical slots 1-2, chart ink and surfaces
BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#1c5cab", "#104281", "#0d366b"]
EDGE_C, INNER_C = "#2a78d6", "#eb6834"
INK, INK2, STUDY_FILL, STATE_EDGE = "#0b0b0b", "#52514e", "#f0efec", "#b5b4ad"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, required=True, help="configs/study_area.yaml (its water: block)")
    p.add_argument("--cutout-root", type=Path, required=True, help="cutout is <cutout-root>/<name>/")
    p.add_argument("--counties-gpkg", type=Path, help="counties_2020.gpkg for state lines on the map")
    p.add_argument("--edge-km", type=float, default=1.0,
                   help="no-data cells farther than this from the study-area edge count as 'inside'")
    return p.parse_args(argv)


def edge_distance(inside: np.ndarray) -> np.ndarray:
    """km from each cell to the nearest cell outside the study counties; beyond the window counts as outside
    (the window is snapped to the county bounds, so there may be no outside cell at its border)."""
    return ndimage.distance_transform_edt(np.pad(inside, 1))[1:-1, 1:-1] * CELL_KM


def county_rows(cut: Path, year: int, nd: np.ndarray, edge_km: float):
    with rasterio.open(cut / "zones" / f"zones_{year}.tif") as src:
        zones = src.read(1)
    table = pd.read_csv(cut / "zones" / f"zones_{year}.csv")
    dist = edge_distance(zones > 0)
    has = np.nan_to_num(nd) > 0
    rows = []
    for _, t in table.iterrows():
        m = zones == t["zone_id"]
        v = np.nan_to_num(nd[m])
        inner = m & has & (dist > edge_km)
        rows.append({"year": year, "zone_id": t["zone_id"], "GISJOIN": t["GISJOIN"], "name": t["name"],
                     "status": t["status"], "cells": int(m.sum()), "nodata_share": float(v.mean()) if v.size else 0.0,
                     "cells_with_nodata": int((v > 0).sum()), "nodata_km2": float(v.sum() * CELL_KM ** 2),
                     "inner_nodata_km2": float(np.nan_to_num(nd[inner]).sum() * CELL_KM ** 2),
                     "max_dist_km": float(dist[m & has].max()) if (m & has).any() else 0.0})
    return rows, zones > 0, dist


def draw(path: Path, nd, zone_any, dist_any, transform, crs, gpkg, edge_km):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap, ListedColormap
    from matplotlib.patches import Patch

    H, W = nd.shape
    ext = [transform.c, transform.c + W * transform.a, transform.f + H * transform.e, transform.f]
    states = None
    if gpkg:
        import geopandas as gpd
        states = gpd.read_file(gpkg, columns=["state"])
        states = (states.to_crs(crs) if states.crs != crs else states).cx[ext[0]:ext[1], ext[2]:ext[3]]
        states = states.dissolve(by="state")
    fig, axes = plt.subplots(1, 2, figsize=(14, 14 * H / W / 2 + 1), dpi=150, layout="constrained")
    cmap = LinearSegmentedColormap.from_list("blues", BLUES)
    cmap.set_bad((0, 0, 0, 0))
    a0, a1 = axes
    a0.imshow(np.ma.masked_where(~zone_any, zone_any.astype("uint8")), cmap=ListedColormap([STUDY_FILL]),
              extent=ext, interpolation="nearest", zorder=1)  # study counties as land context
    im = a0.imshow(np.ma.masked_where(~(np.nan_to_num(nd) > 0), nd), cmap=cmap, vmin=0, vmax=1, extent=ext,
                   interpolation="nearest", zorder=2)
    a0.set_title("JRC no-data share per 250 m cell (whole window)", fontsize=10, color=INK)
    has = np.nan_to_num(nd) > 0
    cat = np.zeros(nd.shape, "uint8")
    cat[zone_any] = 1
    cat[zone_any & has & (dist_any <= edge_km)] = 2
    cat[zone_any & has & (dist_any > edge_km)] = 3
    a1.imshow(np.ma.masked_where(cat == 0, cat), cmap=ListedColormap([STUDY_FILL, EDGE_C, INNER_C]), vmin=1, vmax=3,
              extent=ext, interpolation="nearest", zorder=2)
    a1.set_title("JRC no-data inside the study counties (any year)", fontsize=10, color=INK)
    a1.legend(handles=[Patch(color=STUDY_FILL, label="study counties, no no-data"),
                       Patch(color=EDGE_C, label=f"no-data within {edge_km:g} km of the study-area edge"),
                       Patch(color=INNER_C, label=f"no-data more than {edge_km:g} km inside")],
              loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=1, fontsize=8, frameon=False, labelcolor=INK2)
    for ax in axes:
        if states is not None and len(states):
            states.boundary.plot(ax=ax, color=STATE_EDGE, lw=0.5, zorder=3)
        ax.contour(np.flipud(zone_any.astype(float)), levels=[0.5], colors=[INK2], linewidths=0.4,
                   extent=ext, zorder=4)
        ax.set_xlim(ext[0], ext[1])
        ax.set_ylim(ext[2], ext[3])
        ax.set_axis_off()
        km = max(k for k in (1, 2, 5, 10, 20, 50, 100, 200, 500) if k <= max((ext[1] - ext[0]) / 5e3, 1))
        x0, y0 = ext[0] + 0.04 * (ext[1] - ext[0]), ext[2] + 0.04 * (ext[3] - ext[2])
        ax.plot([x0, x0 + km * 1e3], [y0, y0], color=INK, lw=2, solid_capstyle="butt")
        ax.text(x0 + km * 5e2, y0 + 0.01 * (ext[3] - ext[2]), f"{km} km", ha="center", va="bottom", fontsize=8,
                color=INK)
    cb = fig.colorbar(im, ax=a0, shrink=0.6)
    cb.set_label("share of 30 m pixels with JRC value > 100", fontsize=9, color=INK2)
    cb.ax.tick_params(labelsize=8, colors=INK2)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    log.info("wrote %s", path)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    wcfg = cfg.get("water")
    if not wcfg:
        sys.exit(f"ERROR: no water: block in {args.config}")
    cut = args.cutout_root / cfg["name"]
    if not (cut / "window.json").exists():
        sys.exit(f"ERROR: {cut / 'window.json'} not found (run the cutout first)")
    win = json.loads((cut / "window.json").read_text())
    crs = CRS.from_wkt(win["crs_wkt"])
    transform = Affine(*win["transform"])
    H, W = int(win["height"]), int(win["width"])
    bounds_ll = transform_bounds(crs, "EPSG:4326", *win["bounds"], densify_pts=101)
    tiles, res = jrc_tiles(wcfg, bounds_ll)
    _, nd, stats = cell_shares(wcfg, tiles, res, None, transform, H, W, crs)
    log.info("window: %d JRC pixels, %d no-data (%.4f) | cells with any no-data %d of %d", stats["jrc_pixels"],
             stats["jrc_nodata_pixels"], stats["jrc_nodata_pixels"] / max(stats["jrc_pixels"], 1),
             int((np.nan_to_num(nd) > 0).sum()), H * W)
    write_tif(cut / "qa" / "jrc_nodata_frac.tif", nd, transform, crs, float("nan"))

    rows, zone_any, dist_any = [], np.zeros((H, W), bool), None
    for year in cfg["years"]:
        r, z, _ = county_rows(cut, year, nd, args.edge_km)
        rows += r
        zone_any |= z
    dist_any = edge_distance(zone_any)
    df = pd.DataFrame(rows)
    path = cut / "qa" / "jrc_nodata_by_county.csv"
    df.to_csv(path, index=False)
    log.info("wrote %s", path)
    by_year = df.groupby("year")[["cells", "cells_with_nodata", "nodata_km2", "inner_nodata_km2"]].sum()
    by_year["nodata_share"] = by_year["nodata_km2"] / (by_year["cells"] * CELL_KM ** 2)
    log.info("study counties by year (all statuses):\n%s", by_year.round(4).to_string())
    for year in sorted({cfg["years"][0], cfg["years"][-1]}):
        t = df[(df["year"] == year) & (df["cells_with_nodata"] > 0)].sort_values("nodata_km2", ascending=False)
        log.info("%d, counties with no-data (%d of %d):\n%s", year, len(t), int((df["year"] == year).sum()),
                 t.drop(columns=["year", "zone_id"]).round(4).to_string(index=False) if len(t) else "  none")
    inner = df.groupby("year")["inner_nodata_km2"].sum()
    log.info("verdict input: no-data more than %.1f km inside the study area: %s km2 (max over years %.3f)",
             args.edge_km, "none" if inner.max() == 0 else "present", inner.max())
    draw(cut / "qa" / "jrc_nodata_map.png", nd, zone_any, dist_any, transform, crs, args.counties_gpkg, args.edge_km)
    log.info("DONE")


if __name__ == "__main__":
    main()
