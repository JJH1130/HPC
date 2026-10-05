"""QA of the NTL layer in a study-area cutout (design: docs/dasymetric_v3.md, "QA for NTL").

Reads <cutout-root>/<name>/layers/NTL/{YEAR}_NTL.tif, zones/zones_{YEAR}.tif and layers/BUI/{YEAR}_BUI.tif
for the NTL years in configs/study_area.yaml, and writes <cutout-root>/<name>/qa/ntl_qa.csv, one row per year:
  range       min, max, nodata cells and cells outside 0-63 in the whole window
  alignment   cells with DN >= --bright in a --box-km box around --lon/--lat (downtown Boston):
              count, centroid (ESRI:102039 m and lon/lat), shift (km) from the previous NTL year
  ntl ~ bui   Spearman rho over cells with zone > 0 (that year's zones)

Fails (after writing the CSV) if a value is outside 0-63, or a year has no bright cell in the box.
A centroid shift >= 1 km is logged as a warning (the design expects well under 1 km).
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
from scipy.stats import spearmanr

from make_cutout import load_config

log = logging.getLogger("ntl_qa")
DN_MAX = 63


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, required=True, help="configs/study_area.yaml")
    p.add_argument("--cutout-root", type=Path, required=True, help="cutout is <cutout-root>/<name>/")
    p.add_argument("--layer", default="NTL", help="config layer name of the night lights")
    p.add_argument("--lon", type=float, default=-71.06, help="box centre (downtown Boston)")
    p.add_argument("--lat", type=float, default=42.36)
    p.add_argument("--box-km", type=float, default=20.0, help="side of the square box")
    p.add_argument("--bright", type=int, default=60, help="DN threshold for the brightest cells")
    return p.parse_args(argv)


def read(path: Path):
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (cut the layer first)")
    with rasterio.open(path) as src:
        return src.read(1), src.nodata, src.transform, src.crs


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

    rows, prev, fail = [], None, []
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
        rr, cc = np.mgrid[0:ntl.shape[0], 0:ntl.shape[1]]
        x, y = t.c + (cc + 0.5) * t.a, t.f + (rr + 0.5) * t.e
        bright = (np.abs(x - cx) <= half) & (np.abs(y - cy) <= half) & ~nd & (ntl >= args.bright)
        r["box_cells"] = int(((np.abs(x - cx) <= half) & (np.abs(y - cy) <= half)).sum())
        r["bright_cells"] = int(bright.sum())
        if bright.any():
            mx, my = float(x[bright].mean()), float(y[bright].mean())
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
        rows.append(r)

    qa = pd.DataFrame(rows)
    path = cut / "qa" / "ntl_qa.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    qa.to_csv(path, index=False)
    log.info("wrote %s", path)
    if fail:
        sys.exit("ERROR: NTL QA failed:\n  " + "\n  ".join(fail))
    log.info("DONE")


if __name__ == "__main__":
    main()
