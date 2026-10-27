"""QA of the NTL layer in a study-area cutout (design: docs/dasymetric_v3.md, "QA for NTL").

Reads <cutout-root>/<name>/layers/NTL/{YEAR}_NTL.tif, zones/zones_{YEAR}.tif and layers/BUI/{YEAR}_BUI.tif
for the NTL years in configs/study_area.yaml, and writes <cutout-root>/<name>/qa/ntl_qa.csv, one row per year:
  range       min, max, nodata cells and cells outside 0-63 in the whole window
  alignment   cells with DN >= --bright in a --box-km box around --lon/--lat (downtown Boston):
              count, centroid (ESRI:102039 m and lon/lat), shift (km) from the previous NTL year
  ntl ~ bui   Spearman rho over cells with zone > 0 (that year's zones)
  edges       (CONUS request 2026-10-28, docs/conus_plan.md "NTL test"; logged, never a failure) lights at the
              sea / border: lit (DN > 0) and bright cells outside every zone (sea, Canada, Mexico); zone cells
              with nodata; "glow" cells = zone cells without a building (BUI == 0) and DN >= --glow-dn, for edge
              cells (within --edge-km of a cell outside every zone: coast, border, large lakes) and interior
              cells (share, and mean DN on BUI == 0 cells). DMSP blooming or offshore light shows as an edge
              share well above the interior one. qa/ntl_glow_counties.csv: the --top counties per year with the
              most edge glow cells (with zones_{YEAR}.csv names).

Fails (after writing the CSVs) if a value is outside 0-63, or a year has no bright cell in the box (rule unchanged
since 2026-10-06; a change is on hold, docs/open_items.md). A centroid shift >= 1 km is logged as a warning (the
design expects well under 1 km).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from scipy import ndimage
from scipy.stats import spearmanr

from make_cutout import load_config

log = logging.getLogger("ntl_qa")
DN_MAX = 63
NAME_COLS = ("zone_id", "GISJOIN", "state", "name")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, required=True, help="configs/study_area.yaml")
    p.add_argument("--cutout-root", type=Path, required=True, help="cutout is <cutout-root>/<name>/")
    p.add_argument("--layer", default="NTL", help="config layer name of the night lights")
    p.add_argument("--lon", type=float, default=-71.06, help="box centre (downtown Boston)")
    p.add_argument("--lat", type=float, default=42.36)
    p.add_argument("--box-km", type=float, default=20.0, help="side of the square box")
    p.add_argument("--bright", type=int, default=60, help="DN threshold for the brightest cells")
    p.add_argument("--edge-km", type=float, default=5.0, help="zone cells this close to a non-zone cell = edge")
    p.add_argument("--glow-dn", type=int, default=30, help="DN of a 'glow' cell (lit, no building)")
    p.add_argument("--top", type=int, default=15, help="counties per year in ntl_glow_counties.csv")
    return p.parse_args(argv)


def read(path: Path):
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (cut the layer first)")
    with rasterio.open(path) as src:
        return src.read(1), src.nodata, src.transform, src.crs


def edge_stats(ntl, nd, zones, bui, cell_km: float, args):
    """Lights at the sea / border (module docstring, "edges"): (dict of counts, top counties by edge glow)."""
    zone = zones > 0
    out = {"outside_lit_cells": int((~zone & ~nd & (ntl > 0)).sum()),
           "outside_bright_cells": int((~zone & ~nd & (ntl >= args.bright)).sum()),
           "zone_nodata_cells": int((zone & nd).sum())}
    # km from each zone cell to the nearest cell outside every zone (0 outside); float32 keeps CONUS smaller
    dist = ndimage.distance_transform_edt(zone).astype("float32")
    dist *= cell_km
    edge = zone & (dist <= args.edge_km)
    del dist
    inner = zone & ~edge
    bui0 = ~nd & (bui == 0)
    glow = bui0 & (ntl >= args.glow_dn)
    for name, part in (("edge", edge), ("interior", inner)):
        n, g, b0 = int(part.sum()), int((glow & part).sum()), part & bui0
        out.update({f"{name}_cells": n, f"{name}_glow_cells": g, f"{name}_glow_share": g / n if n else np.nan,
                    f"{name}_mean_dn_bui0": float(ntl[b0].mean()) if b0.any() else np.nan})
    n_zone = int(zones.max()) + 1
    per = pd.DataFrame({"zone_id": np.arange(n_zone),
                        "edge_glow_cells": np.bincount(zones[glow & edge], minlength=n_zone),
                        "glow_cells": np.bincount(zones[glow & zone], minlength=n_zone),
                        "zone_cells": np.bincount(zones[zone], minlength=n_zone)})
    per = per[per["edge_glow_cells"] > 0].sort_values(["edge_glow_cells", "zone_id"], ascending=[False, True])
    return out, per.head(args.top).reset_index(drop=True)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    entries = [layer for layer in cfg["layers"] if layer["name"] == args.layer]
    if not entries or entries[0]["years"] is None:
        sys.exit(f"ERROR: no yearly layer {args.layer!r} in {args.config}")
    years = entries[0]["years"]
    cut = args.cutout_root / cfg["name"]
    log.info("cutout %s | %s years %s | box %.0f km around (%.2f, %.2f) | DN >= %d",
             cut, args.layer, years, args.box_km, args.lon, args.lat, args.bright)

    rows, tops, prev, fail = [], [], None, []
    for year in years:
        ntl, nd_val, t, crs = read(cut / "layers" / args.layer / f"{year}_{args.layer}.tif")
        zones, _, zt, _ = read(cut / "zones" / f"zones_{year}.tif")
        bui, _, bt, _ = read(cut / "layers" / "BUI" / f"{year}_BUI.tif")
        if ntl.shape != zones.shape or t != zt or bt != zt:
            sys.exit(f"ERROR: {year}: NTL, BUI and zones are not on the same grid")
        nd = ntl == nd_val if nd_val is not None else np.zeros(ntl.shape, bool)
        v = ntl[~nd]
        r = {"year": year, "n_cells": int(ntl.size), "nodata_cells": int(nd.sum()),
             "min": int(v.min()) if v.size else None, "max": int(v.max()) if v.size else None,
             "outside_0_63": int(((v < 0) | (v > DN_MAX)).sum()), "zero_share": float((v == 0).mean()) if v.size else None}

        cx, cy = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(args.lon, args.lat)
        half = args.box_km * 500.0
        # the box as row / column ranges (CONUS: no whole-window coordinate grids)
        xc, yc = t.c + (np.arange(ntl.shape[1]) + 0.5) * t.a, t.f + (np.arange(ntl.shape[0]) + 0.5) * t.e
        bc, br = np.flatnonzero(np.abs(xc - cx) <= half), np.flatnonzero(np.abs(yc - cy) <= half)
        box = (slice(br[0], br[-1] + 1) if br.size else slice(0, 0),
               slice(bc[0], bc[-1] + 1) if bc.size else slice(0, 0))
        bright = ~nd[box] & (ntl[box] >= args.bright)
        r["box_cells"] = int(br.size * bc.size)
        r["bright_cells"] = int(bright.sum())
        if bright.any():
            bi, bj = np.nonzero(bright)
            mx, my = float(xc[bc[0] + bj].mean()), float(yc[br[0] + bi].mean())
            lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(mx, my)
            r.update(centroid_x=mx, centroid_y=my, centroid_lon=lon, centroid_lat=lat)
            if prev is not None:
                r["shift_km_from"] = prev[0]
                r["shift_km"] = float(np.hypot(mx - prev[1], my - prev[2]) / 1e3)
            prev = (year, mx, my)
        else:
            fail.append(f"{year}: no cell with DN >= {args.bright} in the box")

        m = (zones > 0) & ~nd
        rho = spearmanr(ntl[m], bui[m]).statistic if m.any() else np.nan
        r.update(zone_cells=int(m.sum()), spearman_ntl_bui=float(rho))
        edges, top = edge_stats(ntl, nd, zones, bui, abs(t.a) / 1e3, args)
        r.update(edges)
        table = pd.read_csv(cut / "zones" / f"zones_{year}.csv", usecols=lambda c: c in NAME_COLS)
        top = top.merge(table, on="zone_id", how="left")
        tops.append(top.assign(year=year))
        if r["outside_0_63"]:
            fail.append(f"{year}: {r['outside_0_63']} cells outside 0-{DN_MAX}")
        if r.get("shift_km", 0) >= 1:
            log.warning("  %d: bright-cell centroid moved %.2f km from %d (expected well under 1 km)",
                        year, r["shift_km"], r["shift_km_from"])
        log.info("  %d: DN %s..%s | nodata %d | zero share %.3f | box: %d bright of %d cells, centroid "
                 "(%.4f, %.4f), shift %s km | Spearman ntl~bui %.3f over %d zone cells", year, r["min"], r["max"],
                 r["nodata_cells"], r["zero_share"], r["bright_cells"], r["box_cells"],
                 r.get("centroid_lon", np.nan), r.get("centroid_lat", np.nan),
                 f"{r['shift_km']:.3f}" if "shift_km" in r else "-", rho, r["zone_cells"])
        log.info("  %d edges: outside every zone %d lit / %d bright (DN >= %d) cells | zone cells with nodata %d | "
                 "glow (BUI 0, DN >= %d): edge (<= %g km) %d of %d cells (%.4f), interior %d of %d (%.4f) | mean DN "
                 "on BUI 0 cells: edge %.2f, interior %.2f", year, r["outside_lit_cells"], r["outside_bright_cells"],
                 args.bright, r["zone_nodata_cells"], args.glow_dn, args.edge_km, r["edge_glow_cells"],
                 r["edge_cells"], r["edge_glow_share"], r["interior_glow_cells"], r["interior_cells"],
                 r["interior_glow_share"], r["edge_mean_dn_bui0"], r["interior_mean_dn_bui0"])
        if len(top):
            with pd.option_context("display.width", 200, "display.max_columns", 20):
                log.info("  %d: counties with the most edge glow cells:\n%s", year, top.to_string(index=False))
        rows.append(r)

    qa = pd.DataFrame(rows)
    path = cut / "qa" / "ntl_qa.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    qa.to_csv(path, index=False)
    log.info("wrote %s", path)
    gpath = cut / "qa" / "ntl_glow_counties.csv"
    pd.concat(tops, ignore_index=True).to_csv(gpath, index=False)
    log.info("wrote %s", gpath)
    if fail:
        sys.exit("ERROR: NTL QA failed:\n  " + "\n  ".join(fail))
    log.info("DONE")


if __name__ == "__main__":
    main()
