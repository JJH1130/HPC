"""QA of the PLURAL layers in the cutout (PLURAL grid test, request 2026-10-30, docs/handoff/plural_grid_request.md;
docs/conus_plan.md "PLURAL grid test"). Looks only; changes nothing.

The source (Siqiao's 900 m grid, LAEA 45N 100W) has no nodata value: cells outside the US are 0, the same value as
the most urban cells. A 250 m cell near the coast or a border is warped (bilinear / cubic) from 900 m pixels some of
which lie outside the US, so the 0 fill can pull its value down. Measured per year and layer (config `plural_qa:`):

  out_w      the weight of outside pixels in a cell's value: the indicator "source pixel centre outside every county"
             (zones of that year sampled at the pixel centres, nearest) warped with the layer's own resampling. The
             warp is linear in the pixel values, so value = (1 - out_w) x (the value from the US pixels alone) when the
             outside pixels are 0; out_w = 0: no outside pixel used. Cubic weights can be negative.
  deficit    value / (1 - out_w) - value on cells with 0 < out_w < 0.99: how much the fill lowered the cell (the
             renormalized value is one possible fix; nearest at those cells is another; the user decides)
  edge       county cells within `edge_km` (5 km) of a cell outside every county (coast, Canada, Mexico, large lakes
             outside the county polygons); interior = the other county cells (out_w is 0 there: a 900 m warp reaches
             about 1.4 km). Value distributions of edge and interior side by side.
  source     share of the outside pixels that are exactly 0 (the fill), and of the inside pixels (urban zeros)
  points     the 900 m source pixel and the 250 m PLURAL / PLURALC cells at a few cities and remote places

Writes to <cutout>/qa/ (copied to results/cutout/<name>/ by sbatch/plural_qa.sh): plural_qa.csv (year, layer, part,
statistics), plural_points.csv (year, point, source value, layer values, out_w).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import yaml
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.warp import reproject
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_cutout  # noqa: E402  (config layers + input paths, as the cutout resolved them)

log = logging.getLogger("plural_qa")

CELL_KM = 0.25
QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]
TOUCHED = 1e-3  # out_w above this = an outside pixel took part in the cell's value
RENORM_MAX = 0.99  # deficit only where some US pixel weight is left


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, required=True, help="configs/conus_study_area.yaml")
    p.add_argument("--cutout-root", type=Path, required=True, help="cutout is <cutout-root>/<name>/")
    p.add_argument("--years", type=int, nargs="+", help="default: the years of the first QA layer")
    return p.parse_args(argv)


def stats(v: np.ndarray, w: np.ndarray) -> dict:
    """Value distribution + outside-weight summary of one set of cells (v values, w out_w)."""
    out = {"cells": int(v.size)}
    if not v.size:
        return out
    qs = np.quantile(v, QUANTILES)
    out.update({"mean": float(v.mean()), **{f"p{int(100 * q):02d}": float(x) for q, x in zip(QUANTILES, qs)},
                "share_zero": float((v <= 1e-6).mean()), "share_lt_0.1": float((v < 0.1).mean())})
    touched = w > TOUCHED
    ok = touched & (w < RENORM_MAX)
    deficit = v[ok] / (1 - w[ok]) - v[ok]
    out.update({"touched_share": float(touched.mean()), "touched_cells": int(touched.sum()),
                "out_w_mean_touched": float(w[touched].mean()) if touched.any() else 0.0,
                "out_w_ge_0.5": int((w >= 0.5).sum()),
                "deficit_mean": float(deficit.mean()) if deficit.size else 0.0,
                "deficit_p95": float(np.quantile(deficit, 0.95)) if deficit.size else 0.0,
                "deficit_max": float(deficit.max()) if deficit.size else 0.0})
    return out


def read_full(path: Path, dtype="float32"):
    with rasterio.open(path) as src:
        return src.read(1).astype(dtype), src.transform, src.crs, src.nodata


def outside_weight(zones, z_transform, z_crs, src_path: Path, resampling: str):
    """(out_w on the zones grid, source values, outside-pixel mask of the source). out_w = the indicator 'source
    pixel centre outside every county' warped onto the zones grid with `resampling`."""
    with rasterio.open(src_path) as src:
        sv = src.read(1)
        s_transform, s_crs = src.transform, src.crs
    zs = np.zeros(sv.shape, dtype="uint16")
    reproject(zones, zs, src_transform=z_transform, src_crs=z_crs, dst_transform=s_transform, dst_crs=s_crs,
              src_nodata=None, dst_nodata=None, resampling=Resampling.nearest)
    outside = zs == 0  # beyond the window, too: the init value 0
    ow = np.full(zones.shape, np.nan, dtype="float32")
    reproject(outside.astype("float32"), ow, src_transform=s_transform, src_crs=s_crs, dst_transform=z_transform,
              dst_crs=z_crs, src_nodata=None, dst_nodata=np.nan, resampling=Resampling[resampling])
    return ow, sv, outside, s_transform, s_crs


def point_rows(year, points, src_vals, s_transform, s_crs, layers: dict, out_ws: dict, z_transform, z_crs) -> list:
    rows = []
    to_src = Transformer.from_crs("EPSG:4326", s_crs, always_xy=True)
    to_win = Transformer.from_crs("EPSG:4326", z_crs, always_xy=True)
    for p in points:
        sx, sy = to_src.transform(p["lon"], p["lat"])
        sr, sc = rasterio.transform.rowcol(s_transform, sx, sy)
        wx, wy = to_win.transform(p["lon"], p["lat"])
        wr, wc = rasterio.transform.rowcol(z_transform, wx, wy)
        row = {"year": year, "point": p["name"], "lon": p["lon"], "lat": p["lat"],
               "source_900m": float(src_vals[sr, sc]) if 0 <= sr < src_vals.shape[0] and 0 <= sc < src_vals.shape[1]
               else np.nan}
        for name, arr in layers.items():
            inside = 0 <= wr < arr.shape[0] and 0 <= wc < arr.shape[1]
            row[name] = float(arr[wr, wc]) if inside else np.nan
            row[f"{name}_out_w"] = float(out_ws[name][wr, wc]) if inside else np.nan
        rows.append(row)
    return rows


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    raw = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    qcfg = raw.get("plural_qa")
    if not qcfg:
        sys.exit(f"ERROR: {args.config} has no plural_qa block")
    cfg = make_cutout.load_config(args.config)
    by_name = {lay["name"]: lay for lay in cfg["layers"]}
    missing = [n for n in qcfg["layers"] if n not in by_name]
    if missing:
        sys.exit(f"ERROR: plural_qa layers {missing} not in the config layers")
    lays = [by_name[n] for n in qcfg["layers"]]
    years = args.years or lays[0]["years"]
    edge_km = float(qcfg.get("edge_km", 5))
    cut = args.cutout_root / cfg["name"]
    qdir = cut / "qa"
    qdir.mkdir(parents=True, exist_ok=True)
    rows, prow = [], []
    for year in years:
        log.info("===== %d =====", year)
        zones, z_transform, z_crs, _ = read_full(cut / "zones" / f"zones_{year}.tif", "uint16")
        county = zones > 0
        d = ndimage.distance_transform_edt(np.pad(county, 1))[1:-1, 1:-1]  # cells to the nearest non-county cell (beyond the window too)
        edge = county & (d * CELL_KM <= edge_km)
        del d
        interior = county & ~edge
        log.info("  county cells %d | edge (<= %.0f km of a non-county cell) %d | interior %d", int(county.sum()),
                 edge_km, int(edge.sum()), int(interior.sum()))
        layers, out_ws = {}, {}
        for lay in lays:
            src = make_cutout.resolve(lay, year, Path("/"))
            if isinstance(src, str):
                sys.exit("ERROR: source raster:\n" + src)
            path = cut / "layers" / lay["name"] / f"{year}_{lay['name']}.tif"
            if not path.exists():
                sys.exit(f"ERROR: {path} not found (grid_cutout.sh --layers {lay['name']} first)")
            v = read_full(path)[0]
            if np.isnan(v[county]).any():
                log.warning("  %s %d: %d county cells are nodata", lay["name"], year, int(np.isnan(v[county]).sum()))
            ow, sv, outside, s_transform, s_crs = outside_weight(zones, z_transform, z_crs, src, lay["resampling"])
            if lay is lays[0]:  # the source is the same file for every layer of a year: log it once
                log.info("  source %s | %dx%d | %s | outside pixels %d: exactly 0 %.4f | inside pixels %d: exactly 0 "
                         "%.4f, value p05 / p50 / p95 %s", src.name, sv.shape[1], sv.shape[0], s_crs.to_string(),
                         int(outside.sum()), float((sv[outside] == 0).mean()), int((~outside).sum()),
                         float((sv[~outside] == 0).mean()), np.round(np.quantile(sv[~outside], [0.05, 0.5, 0.95]), 3).tolist())
                rows.append({"year": year, "layer": "source", "part": "outside_pixels", "cells": int(outside.sum()),
                             "share_zero": float((sv[outside] == 0).mean())})
                rows.append({"year": year, "layer": "source", "part": "inside_pixels", "cells": int((~outside).sum()),
                             "share_zero": float((sv[~outside] == 0).mean()), "mean": float(sv[~outside].mean())})
            for part, m in (("edge", edge), ("interior", interior), ("all", county)):
                ok = m & np.isfinite(v)
                r = {"year": year, "layer": lay["name"], "resampling": lay["resampling"], "part": part,
                     **stats(v[ok].astype("float64"), np.nan_to_num(ow[ok]).astype("float64"))}
                rows.append(r)
                log.info("  %-7s %-8s %9d cells | mean %.3f p05 %.3f p50 %.3f p95 %.3f | zero %.4f <0.1 %.4f | "
                         "outside pixels used in %.4f (%d cells, mean out_w %.3f, >= 0.5: %d) | deficit mean %.4f "
                         "p95 %.4f max %.3f", lay["name"], part, r["cells"], r.get("mean", np.nan),
                         r.get("p05", np.nan), r.get("p50", np.nan), r.get("p95", np.nan), r.get("share_zero", np.nan),
                         r.get("share_lt_0.1", np.nan), r.get("touched_share", np.nan), r.get("touched_cells", 0),
                         r.get("out_w_mean_touched", np.nan), r.get("out_w_ge_0.5", 0), r.get("deficit_mean", np.nan),
                         r.get("deficit_p95", np.nan), r.get("deficit_max", np.nan))
            layers[lay["name"]], out_ws[lay["name"]] = v, ow
        prow += point_rows(year, qcfg.get("points", []), sv, s_transform, s_crs, layers, out_ws, z_transform, z_crs)
        del layers, out_ws, zones, county, edge, interior
    qa = pd.DataFrame(rows)
    pts = pd.DataFrame(prow)
    qa.to_csv(qdir / "plural_qa.csv", index=False)
    pts.to_csv(qdir / "plural_points.csv", index=False)
    with pd.option_context("display.width", 220, "display.max_columns", 30):
        log.info("points (source = 900 m pixel; layers = the 250 m cell; out_w = weight of outside pixels):\n%s",
                 pts.round(3).to_string(index=False))
        e = qa[qa["part"].isin(["edge", "interior"])]
        log.info("edge vs interior:\n%s", e[["year", "layer", "part", "cells", "mean", "p05", "p50", "share_zero",
                                            "touched_share", "out_w_ge_0.5", "deficit_mean", "deficit_p95"]]
                 .round(4).to_string(index=False))
    log.info("wrote %s, %s", qdir / "plural_qa.csv", qdir / "plural_points.csv")
    log.info("DONE")


if __name__ == "__main__":
    main()
