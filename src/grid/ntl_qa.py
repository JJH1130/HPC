"""QA of the night-light layers in a study-area cutout (design: docs/dasymetric_v3.md, "QA for NTL").

Reads <cutout-root>/<name>/layers/<LAYER>/{YEAR}_<LAYER>.tif, zones/zones_{YEAR}.tif and layers/BUI/{YEAR}_BUI.tif
for the years of each --layer in the study-area config, and writes <cutout-root>/<name>/qa/<layer>_qa.csv (ntl_qa.csv
for NTL), one row per year:
  range       min, max, nodata cells in the whole window; DN layers (NTL): cells outside 0-63; radiance layers
              (NTLV, VIIRS-like, docs/conus_plan.md "VIIRS-like NTL test"): negative cells
  alignment   bright cells in a --box-km box around --lon/--lat (downtown Boston): count, centroid (ESRI:102039 m
              and lon/lat), shift (km) from the previous year. Bright = DN >= --bright for DN layers; for radiance
              layers (no fixed scale) >= the --bright-pct percentile of the lit zone cells of that year (logged)
  ntl ~ bui   Spearman rho over cells with zone > 0 (that year's zones)
  edges       (CONUS request 2026-10-28, docs/conus_plan.md "NTL test"; logged, never a failure) lights at the
              sea / border: lit (> 0) and bright cells outside every zone (sea, Canada, Mexico); zone cells
              with nodata; for edge cells (within --edge-km of a cell outside every zone: coast, border, large lakes)
              and interior cells: "glow" cells = zone cells without a building (BUI == 0) and value >= the glow
              threshold (DN layers --glow-dn, radiance layers --glow-rad), their share, the share of lit cells among
              the BUI == 0 cells (lit_bui0_share), the mean value on BUI == 0 cells, and that mean over the mean on
              cells with buildings (bui0_to_built, scale-free: how much light lies on empty land). Blooming or
              offshore light shows as an edge share well above the interior one. qa/<layer>_glow_counties.csv: the
              --top counties per year with the most edge glow cells (with zones_{YEAR}.csv names).
With several --layer (e.g. NTL NTLV), qa/ntl_edges_compare.csv puts the edge / interior lines of every layer and
year side by side (also logged).

Fails (after writing the CSVs) if a DN layer has a value outside 0-63 or a year without a bright cell in the box
(rule unchanged since 2026-10-06; a change is on hold, docs/open_items.md), or a radiance layer has a negative value.
For a radiance layer, no bright cell in the box is only a warning (no rule history). A centroid shift >= 1 km is
logged as a warning (the design expects well under 1 km).
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
DN_LAYERS = {"NTL"}  # Harmonized DMSP DN 0-63; every other layer is read as radiance (VIIRS-like, nW/cm2/sr)
NAME_COLS = ("zone_id", "GISJOIN", "state", "name")
EDGE_COLS = ["glow_threshold", "outside_lit_cells", "zone_nodata_cells", "edge_glow_share", "interior_glow_share",
             "edge_lit_bui0_share", "interior_lit_bui0_share", "edge_bui0_to_built", "interior_bui0_to_built"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, required=True, help="configs/study_area.yaml")
    p.add_argument("--cutout-root", type=Path, required=True, help="cutout is <cutout-root>/<name>/")
    p.add_argument("--layer", nargs="+", default=["NTL"], help="config layer names of the night lights")
    p.add_argument("--lon", type=float, default=-71.06, help="box centre (downtown Boston)")
    p.add_argument("--lat", type=float, default=42.36)
    p.add_argument("--box-km", type=float, default=20.0, help="side of the square box")
    p.add_argument("--bright", type=int, default=60, help="DN threshold for the brightest cells (DN layers)")
    p.add_argument("--bright-pct", type=float, default=99.0,
                   help="radiance layers: bright = this percentile of the lit zone cells of the year")
    p.add_argument("--edge-km", type=float, default=5.0, help="zone cells this close to a non-zone cell = edge")
    p.add_argument("--glow-dn", type=int, default=30, help="DN of a 'glow' cell (lit, no building), DN layers")
    p.add_argument("--glow-rad", type=float, default=10.0,
                   help="radiance (nW/cm2/sr) of a 'glow' cell, radiance layers (no calibration to DN 30; logged only)")
    p.add_argument("--top", type=int, default=15, help="counties per year in <layer>_glow_counties.csv")
    return p.parse_args(argv)


def read(path: Path):
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (cut the layer first)")
    with rasterio.open(path) as src:
        return src.read(1), src.nodata, src.transform, src.crs


def nodata_mask(arr, nd_val):
    nd = ~np.isfinite(arr) if np.issubdtype(arr.dtype, np.floating) else np.zeros(arr.shape, bool)
    if nd_val is not None and np.isfinite(nd_val):
        nd |= arr == nd_val
    return nd


def edge_masks(zones, cell_km: float, edge_km: float):
    """(zone, edge, interior) cell masks: edge = zone cells within edge_km of a cell outside every zone."""
    zone = zones > 0
    # km from each zone cell to the nearest cell outside every zone (0 outside); float32 keeps CONUS smaller
    dist = ndimage.distance_transform_edt(zone).astype("float32")
    dist *= cell_km
    edge = zone & (dist <= edge_km)
    del dist
    return zone, edge, zone & ~edge


def edge_stats(val, nd, zones, masks, bui, bright: float, glow_thr: float, top: int):
    """Lights at the sea / border (module docstring, "edges"): (dict of counts, top counties by edge glow)."""
    zone, edge, inner = masks
    out = {"glow_threshold": glow_thr, "outside_lit_cells": int((~zone & ~nd & (val > 0)).sum()),
           "outside_bright_cells": int((~zone & ~nd & (val >= bright)).sum()),
           "zone_nodata_cells": int((zone & nd).sum())}
    bui0, built = ~nd & (bui == 0), ~nd & (bui > 0)
    glow = bui0 & (val >= glow_thr)
    for name, part in (("edge", edge), ("interior", inner)):
        n, g, b0, b1 = int(part.sum()), int((glow & part).sum()), part & bui0, part & built
        m0 = float(val[b0].mean()) if b0.any() else np.nan
        m1 = float(val[b1].mean()) if b1.any() else np.nan
        out.update({f"{name}_cells": n, f"{name}_glow_cells": g, f"{name}_glow_share": g / n if n else np.nan,
                    f"{name}_lit_bui0_share": float((val[b0] > 0).mean()) if b0.any() else np.nan,
                    f"{name}_mean_dn_bui0": m0, f"{name}_bui0_to_built": m0 / m1 if m1 else np.nan})
    n_zone = int(zones.max()) + 1
    per = pd.DataFrame({"zone_id": np.arange(n_zone),
                        "edge_glow_cells": np.bincount(zones[glow & edge], minlength=n_zone),
                        "glow_cells": np.bincount(zones[glow & zone], minlength=n_zone),
                        "zone_cells": np.bincount(zones[zone], minlength=n_zone)})
    per = per[per["edge_glow_cells"] > 0].sort_values(["edge_glow_cells", "zone_id"], ascending=[False, True])
    return out, per.head(top).reset_index(drop=True)


def box_slices(t, shape, cx, cy, half):
    """Cell centre coordinates and the box as row / column ranges (CONUS: no whole-window coordinate grids)."""
    xc, yc = t.c + (np.arange(shape[1]) + 0.5) * t.a, t.f + (np.arange(shape[0]) + 0.5) * t.e
    bc, br = np.flatnonzero(np.abs(xc - cx) <= half), np.flatnonzero(np.abs(yc - cy) <= half)
    box = (slice(br[0], br[-1] + 1) if br.size else slice(0, 0),
           slice(bc[0], bc[-1] + 1) if bc.size else slice(0, 0))
    return xc, yc, bc, br, box


def layer_year(name, year, val, nd_val, t, crs, zones, bui, masks, prev, args):
    """One QA row of one layer and year + its top counties + failures / warnings."""
    dn = name in DN_LAYERS
    nd = nodata_mask(val, nd_val)
    v = val[~nd]
    fail = []
    r = {"year": year, "layer": name, "scale": "dn" if dn else "radiance", "n_cells": int(val.size),
         "nodata_cells": int(nd.sum()), "zero_share": float((v == 0).mean()) if v.size else None}
    if dn:
        r.update(min=int(v.min()) if v.size else None, max=int(v.max()) if v.size else None,
                 outside_0_63=int(((v < 0) | (v > DN_MAX)).sum()))
        if r["outside_0_63"]:
            fail.append(f"{name} {year}: {r['outside_0_63']} cells outside 0-{DN_MAX}")
        bright, glow_thr = float(args.bright), float(args.glow_dn)
        rule = f"DN >= {args.bright}"
    else:
        r.update(min=float(v.min()) if v.size else None, max=float(v.max()) if v.size else None,
                 negative=int((v < 0).sum()))
        if r["negative"]:
            fail.append(f"{name} {year}: {r['negative']} negative cells")
        lit = val[(zones > 0) & ~nd & (val > 0)]
        bright = float(np.percentile(lit, args.bright_pct)) if lit.size else np.inf
        glow_thr = args.glow_rad
        rule = f">= {bright:.4g} (p{args.bright_pct:g} of the lit zone cells; radiance, no DN rule)"
    r["bright_threshold"] = bright

    cx, cy = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(args.lon, args.lat)
    xc, yc, bc, br, box = box_slices(t, val.shape, cx, cy, args.box_km * 500.0)
    hit = ~nd[box] & (val[box] >= bright)
    r["box_cells"] = int(br.size * bc.size)
    r["bright_cells"] = int(hit.sum())
    if hit.any():
        bi, bj = np.nonzero(hit)
        mx, my = float(xc[bc[0] + bj].mean()), float(yc[br[0] + bi].mean())
        lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(mx, my)
        r.update(centroid_x=mx, centroid_y=my, centroid_lon=lon, centroid_lat=lat)
        if prev is not None:
            r["shift_km_from"] = prev[0]
            r["shift_km"] = float(np.hypot(mx - prev[1], my - prev[2]) / 1e3)
            if r["shift_km"] >= 1:
                log.warning("  %s %d: bright-cell centroid moved %.2f km from %d (expected well under 1 km)",
                            name, year, r["shift_km"], prev[0])
    elif dn:
        fail.append(f"{name} {year}: no cell with DN >= {args.bright} in the box")
    else:
        log.warning("  %s %d: no bright cell (%s) in the box (radiance: warning only)", name, year, rule)

    m = (zones > 0) & ~nd
    rho = spearmanr(val[m], bui[m]).statistic if m.any() else np.nan
    r.update(zone_cells=int(m.sum()), spearman_ntl_bui=float(rho))
    edges, top = edge_stats(val, nd, zones, masks, bui, bright, glow_thr, args.top)
    r.update(edges)
    log.info("  %s %d: %s..%s | nodata %d | zero share %.3f | box: bright %s: %d of %d cells, centroid "
             "(%.4f, %.4f), shift %s km | Spearman ntl~bui %.3f over %d zone cells", name, year, r["min"], r["max"],
             r["nodata_cells"], r["zero_share"], rule, r["bright_cells"], r["box_cells"],
             r.get("centroid_lon", np.nan), r.get("centroid_lat", np.nan),
             f"{r['shift_km']:.3f}" if "shift_km" in r else "-", rho, r["zone_cells"])
    log.info("  %s %d edges: outside every zone %d lit / %d bright cells | zone cells with nodata %d | glow (BUI 0, "
             ">= %g): edge (<= %g km) %d of %d cells (%.4f), interior %d of %d (%.4f) | lit share of BUI 0 cells: "
             "edge %.4f, interior %.4f | mean on BUI 0 cells: edge %.3f, interior %.3f (x %.3f, x %.3f of the mean "
             "on built cells)", name, year, r["outside_lit_cells"], r["outside_bright_cells"], r["zone_nodata_cells"],
             glow_thr, args.edge_km, r["edge_glow_cells"], r["edge_cells"], r["edge_glow_share"],
             r["interior_glow_cells"], r["interior_cells"], r["interior_glow_share"], r["edge_lit_bui0_share"],
             r["interior_lit_bui0_share"], r["edge_mean_dn_bui0"], r["interior_mean_dn_bui0"],
             r["edge_bui0_to_built"], r["interior_bui0_to_built"])
    return r, top, fail, ((year, r["centroid_x"], r["centroid_y"]) if hit.any() else prev)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    years_of = {}
    for name in args.layer:
        entries = [layer for layer in cfg["layers"] if layer["name"] == name]
        if not entries or entries[0]["years"] is None:
            sys.exit(f"ERROR: no yearly layer {name!r} in {args.config}")
        years_of[name] = entries[0]["years"]
    cut = args.cutout_root / cfg["name"]
    log.info("cutout %s | layers %s | box %g km around (%.2f, %.2f) | DN layers %s: DN >= %d, others: >= p%g of the "
             "lit zone cells", cut, years_of, args.box_km, args.lon, args.lat, sorted(DN_LAYERS), args.bright,
             args.bright_pct)

    rows = {n: [] for n in args.layer}
    tops = {n: [] for n in args.layer}
    prev = {n: None for n in args.layer}
    fail = []
    for year in sorted({y for ys in years_of.values() for y in ys}):
        zones, _, zt, _ = read(cut / "zones" / f"zones_{year}.tif")
        bui, _, bt, _ = read(cut / "layers" / "BUI" / f"{year}_BUI.tif")
        if bt != zt or bui.shape != zones.shape:
            sys.exit(f"ERROR: {year}: BUI and zones are not on the same grid")
        masks = edge_masks(zones, abs(zt.a) / 1e3, args.edge_km)  # once per year, shared by the layers
        table = pd.read_csv(cut / "zones" / f"zones_{year}.csv", usecols=lambda c: c in NAME_COLS)
        for name in args.layer:
            if year not in years_of[name]:
                continue
            val, nd_val, t, crs = read(cut / "layers" / name / f"{year}_{name}.tif")
            if val.shape != zones.shape or t != zt:
                sys.exit(f"ERROR: {year}: {name} and zones are not on the same grid")
            r, top, f, prev[name] = layer_year(name, year, val, nd_val, t, crs, zones, bui, masks, prev[name], args)
            del val
            fail += f
            top = top.merge(table, on="zone_id", how="left")
            tops[name].append(top.assign(year=year))
            if len(top):
                with pd.option_context("display.width", 200, "display.max_columns", 20):
                    log.info("  %s %d: counties with the most edge glow cells:\n%s", name, year,
                             top.to_string(index=False))
            rows[name].append(r)
        del zones, bui, masks

    qdir = cut / "qa"
    qdir.mkdir(parents=True, exist_ok=True)
    for name in args.layer:
        for kind, data in (("qa", pd.DataFrame(rows[name])), ("glow_counties", pd.concat(tops[name], ignore_index=True))):
            path = qdir / f"{name.lower()}_{kind}.csv"
            data.to_csv(path, index=False)
            log.info("wrote %s", path)
    if len(args.layer) > 1:
        side = pd.concat([pd.DataFrame(rows[n]) for n in args.layer], ignore_index=True)
        side = side[["year", "layer"] + EDGE_COLS].sort_values(["year", "layer"], kind="stable")
        path = qdir / "ntl_edges_compare.csv"
        side.to_csv(path, index=False)
        with pd.option_context("display.width", 250, "display.max_columns", 20):
            log.info("edges side by side (glow = BUI 0 and >= glow_threshold; lit_bui0_share = lit share of BUI 0 "
                     "cells; bui0_to_built = mean on BUI 0 cells / mean on built cells):\n%s",
                     side.round(4).to_string(index=False))
        log.info("wrote %s", path)
    if fail:
        sys.exit("ERROR: NTL QA failed:\n  " + "\n  ".join(fail))
    log.info("DONE")


if __name__ == "__main__":
    main()
