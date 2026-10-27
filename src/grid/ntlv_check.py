"""Check the downloaded VIIRS-like night-light rasters before they are cut (docs/conus_plan.md "VIIRS-like NTL test";
data: Chen et al. 2021, docs/data_sources.md).

For each year of the config layer (--layer, default NTLV) the one input file the cutout would read (same path rule
as src/grid/make_cutout.py) is opened and logged:
  header      CRS, cell size (degrees and arc-seconds), size, dtype, nodata tag, bounds
  coverage    the cutout window (window.json of <cutout-root>/<name>/, ESRI:102039) as a lon/lat box: inside the
              raster bounds or not
  values      over the lon/lat box only (windowed read, never the global raster): nodata / NaN, negative, zero and
              lit (> 0) cells; min, max and the 50 / 90 / 99 / 99.9 % quantiles of the lit cells
  points      the value at fixed sea, lake, dark-land and city-centre points: shows how the sea mask is stored
              (nodata, NaN or 0) and that cities are bright
and one row per year goes to --out (CSV). Fails (after writing the CSV) if the CRS is not geographic, the box is not
covered, a value is negative, or no cell is lit. Looks only; writes no raster.
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
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

from make_cutout import load_config, resolve

log = logging.getLogger("ntlv_check")
# lon, lat; expected: sea / lake = masked or 0, dark = 0 or dim, city = bright
POINTS = [("Atlantic, off New Jersey", -72.0, 38.5, "sea"), ("Gulf of Mexico", -90.0, 27.0, "sea"),
          ("Pacific, off N California", -125.5, 40.5, "sea"), ("Lake Michigan centre", -87.0, 43.5, "lake"),
          ("Great Salt Lake", -112.5, 41.1, "lake"), ("Nevada, Great Basin", -116.6, 39.3, "dark"),
          ("Chicago Loop", -87.63, 41.88, "city"), ("Midtown Manhattan", -73.98, 40.75, "city"),
          ("Las Vegas Strip", -115.17, 36.11, "city"), ("Boston downtown", -71.06, 42.36, "city")]
QUANTS = (50, 90, 99, 99.9)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, required=True, help="configs/conus_study_area.yaml")
    p.add_argument("--cutout-root", type=Path, required=True, help="window.json of <cutout-root>/<name>/")
    p.add_argument("--layer", default="NTLV")
    p.add_argument("--out", type=Path, required=True, help="CSV, one row per year")
    return p.parse_args(argv)


def lonlat_box(cut: Path):
    w = json.loads((cut / "window.json").read_text())
    return transform_bounds(rasterio.crs.CRS.from_wkt(w["crs_wkt"]), "EPSG:4326", *w["bounds"], densify_pts=101)


def check_file(path: Path, year, box) -> tuple[dict, list[str]]:
    fail = []
    with rasterio.open(path) as src:
        t, crs = src.transform, src.crs
        r = {"year": year, "file": str(path), "crs": crs.to_string() if crs else None, "width": src.width,
             "height": src.height, "dtype": src.dtypes[0], "nodata": src.nodata, "cell_deg": t.a,
             "cell_arcsec": t.a * 3600, "west": src.bounds.left, "south": src.bounds.bottom,
             "east": src.bounds.right, "north": src.bounds.top}
        if crs is None or not crs.is_geographic:
            fail.append(f"{year}: CRS {r['crs']} is not geographic (lon/lat) as the paper says (WGS84)")
        b = src.bounds
        r["covers_window"] = bool(b.left <= box[0] and b.bottom <= box[1] and b.right >= box[2] and b.top >= box[3])
        if not r["covers_window"]:
            fail.append(f"{year}: raster bounds {tuple(b)} do not cover the cutout window {box}")
        win = from_bounds(*box, transform=t).round_offsets().round_lengths()
        arr = src.read(1, window=win, boundless=True, fill_value=src.nodata if src.nodata is not None else np.nan)
        arr = arr.astype("float64")
        nd = ~np.isfinite(arr)
        if src.nodata is not None and np.isfinite(src.nodata):
            nd |= arr == src.nodata
        v = arr[~nd]
        lit = v[v > 0]
        r.update(box_cells=int(arr.size), box_nodata=int(nd.sum()), box_negative=int((v < 0).sum()),
                 box_zero=int((v == 0).sum()), box_lit=int(lit.size),
                 min=float(v.min()) if v.size else np.nan, max=float(v.max()) if v.size else np.nan)
        r.update({f"lit_p{q:g}": float(np.percentile(lit, q)) if lit.size else np.nan for q in QUANTS})
        if r["box_negative"]:
            fail.append(f"{year}: {r['box_negative']} negative cells (min {r['min']}) in the window box")
        if not lit.size:
            fail.append(f"{year}: no lit cell in the window box")
        for name, lon, lat, kind in POINTS:
            row, col = src.index(lon, lat)
            if 0 <= row < src.height and 0 <= col < src.width:
                val = float(src.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
                masked = not np.isfinite(val) or (src.nodata is not None and val == src.nodata)
                text = "nodata" if masked else f"{val:g}"
            else:
                text = "outside"
            r[f"pt_{name}"] = text
            log.info("    %-26s (%8.3f, %6.3f) %-4s -> %s", name, lon, lat, kind, text)
    return r, fail


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
    layer = entries[0]
    box = lonlat_box(args.cutout_root / cfg["name"])
    log.info("layer %s: %s | years %s | resampling %s, %s | window as lon/lat box %s", args.layer, layer["path"],
             layer["years"], layer["resampling"], layer["dtype"], tuple(round(x, 3) for x in box))
    rows, fail = [], []
    for year in layer["years"]:
        path = resolve(layer, year, Path("/"))
        if isinstance(path, str):
            fail.append(path.strip())
            continue
        log.info("  %d: %s (%.1f MB)", year, path, path.stat().st_size / 1e6)
        r, f = check_file(path, year, box)
        fail += f
        log.info("  %d: %s | cell %.6f deg = %.2f arc-sec | %dx%d %s nodata=%s | bounds W %.3f S %.3f E %.3f N %.3f | "
                 "covers the window: %s", year, r["crs"], r["cell_deg"], r["cell_arcsec"], r["width"], r["height"],
                 r["dtype"], r["nodata"], r["west"], r["south"], r["east"], r["north"], r["covers_window"])
        log.info("  %d: window box %d cells: nodata %d (%.1f %%), negative %d, zero %d (%.1f %%), lit %d (%.1f %%) | "
                 "min %g max %g | lit quantiles %s", year, r["box_cells"], r["box_nodata"],
                 100 * r["box_nodata"] / r["box_cells"], r["box_negative"], r["box_zero"],
                 100 * r["box_zero"] / r["box_cells"], r["box_lit"], 100 * r["box_lit"] / r["box_cells"], r["min"],
                 r["max"], ", ".join(f"p{q:g} {r[f'lit_p{q:g}']:.3g}" for q in QUANTS))
        rows.append(r)
    if rows:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(args.out, index=False)
        log.info("wrote %s", args.out)
    if fail:
        sys.exit("ERROR: VIIRS-like check failed:\n  " + "\n  ".join(fail))
    log.info("DONE")


if __name__ == "__main__":
    main()
