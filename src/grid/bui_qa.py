"""BUI outlier check on a cutout (CONUS request 2026-10-27, docs/conus_plan.md "BUI outliers"): look only, no change.

The CONUS pilot cutout has single 250 m cells (62,500 m2) with BUI up to 5.4e9 (2010), far above any plausible
indoor floor area (a cell built over 20 times its land area holds ~1.25e6 m2 = ~1.35e7 sq ft). Per year this writes,
from the cutout layers read in strips of --block-rows rows:
  <out-dir>/bui_quantiles.csv  year, cells, cells with BUI > 0, quantiles of BUI over the BUI > 0 cells
                               (p50, p99, p99.9, p99.99, max) and the number of cells above each cap in --caps
  <out-dir>/bui_top.csv        the --top cells with the largest BUI: row, col, lon, lat, zone (2010 county), state,
                               county, BUI, BUPL, BUPR, bldg_size = BUI / BUPL, the median BUI of the 8 neighbours
                               and BUI / that median, county density (pop / area), the county's rank by population
and logs a summary: how many top cells fall in the most populous counties (metro cores) vs elsewhere, and how many
are isolated spikes (neighbour median far below the cell). With --hisdac-dir, README / metadata files under it are
listed and printed (BUI unit and definition) and the tags of one BUI raster are logged.
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
from rasterio.windows import Window

log = logging.getLogger("bui_qa")

QUANTILES = [0.5, 0.99, 0.999, 0.9999]
DOC_SUFFIXES = {".txt", ".md", ".xml", ".pdf", ".json", ".html", ".csv"}
DOC_NAMES = ("readme", "metadata", "codebook", "description", "about")
DOC_TEXT_SUFFIXES = {".txt", ".md", ".xml", ".json", ".html"}
DOC_MAX_BYTES = 200_000  # text files printed up to this size


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cutout", type=Path, required=True, help="the cutout folder, e.g. $HISDAC_SCRATCH/cutouts/conus")
    p.add_argument("--years", type=int, nargs="+", required=True)
    p.add_argument("--out-dir", type=Path, required=True, help="results/cutout/conus")
    p.add_argument("--caps", type=float, nargs="+", default=[1e7, 3e7, 1e8], help="cell counts above these BUI")
    p.add_argument("--top", type=int, default=50, help="largest cells listed per year")
    p.add_argument("--block-rows", type=int, default=512)
    p.add_argument("--metro-rank", type=int, default=50,
                   help="a top cell counts as metro when its county is among the N most populous of the year")
    p.add_argument("--hisdac-dir", type=Path, help="HISDAC_US_V2 root: list + print README / metadata files")
    return p.parse_args(argv)


def layer(cutout: Path, name: str, year: int) -> Path:
    path = cutout / "layers" / name / f"{year}_{name}.tif"
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (run grid_cutout first)")
    return path


def read_rows(src, rows: slice) -> np.ndarray:
    return src.read(1, window=Window(0, rows.start, src.width, rows.stop - rows.start)).astype("float64")


def neighbour_median(src, r: int, c: int) -> float:
    """Median BUI of the (up to 8) cells around (r, c)."""
    r0, c0 = max(r - 1, 0), max(c - 1, 0)
    r1, c1 = min(r + 2, src.height), min(c + 2, src.width)
    a = src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype("float64")
    keep = np.ones(a.shape, bool)
    keep[r - r0, c - c0] = False
    return float(np.median(a[keep]))


def year_qa(cutout: Path, year: int, args):
    zones_path = cutout / "zones" / f"zones_{year}.tif"
    table = pd.read_csv(cutout / "zones" / f"zones_{year}.csv")
    table["density"] = table["pop"] / table["area_km2"]
    table["pop_rank"] = table["pop"].rank(ascending=False, method="min")
    with rasterio.open(layer(cutout, "BUI", year)) as bui, rasterio.open(zones_path) as zsrc:
        if (bui.height, bui.width) != (zsrc.height, zsrc.width) or bui.transform != zsrc.transform:
            sys.exit(f"ERROR: BUI {year} is not on the zones grid")
        nd = bui.nodata
        pos, cand = [], []  # BUI > 0 values (float32); top candidates per strip (value, row, col)
        n_cells = n_nodata = 0
        caps = np.zeros(len(args.caps), dtype=np.int64)
        for r in range(0, bui.height, args.block_rows):
            rows = slice(r, min(r + args.block_rows, bui.height))
            a = read_rows(bui, rows)
            bad = ~np.isfinite(a) | ((a == nd) if nd is not None else False)
            n_nodata += int(bad.sum())
            a[bad] = 0.0
            n_cells += a.size
            v = a[a > 0]
            pos.append(v.astype("float32"))
            caps += np.array([(v > cap).sum() for cap in args.caps])
            flat = a.ravel()
            k = min(args.top, flat.size)
            idx = np.argpartition(flat, -k)[-k:]
            rr, cc = np.unravel_index(idx, a.shape)
            cand += list(zip(flat[idx], rr + r, cc))
        pos = np.concatenate(pos)
        q = np.quantile(pos, QUANTILES) if pos.size else [np.nan] * len(QUANTILES)
        stats = {"year": year, "cells": n_cells, "nodata_cells": n_nodata, "cells_bui_pos": int(pos.size),
                 **{f"p{100 * p:g}": float(x) for p, x in zip(QUANTILES, q)},
                 "max": float(pos.max()) if pos.size else np.nan,
                 **{f"n_gt_{cap:.0e}".replace("+0", ""): int(n) for cap, n in zip(args.caps, caps)}}
        top = sorted(cand, reverse=True)[:args.top]
        to_ll = Transformer.from_crs(bui.crs, "EPSG:4326", always_xy=True)
        out = []
        with rasterio.open(layer(cutout, "BUPL", year)) as pl, rasterio.open(layer(cutout, "BUPR", year)) as pr:
            for rank, (val, r, c) in enumerate(top, 1):
                x, y = bui.xy(int(r), int(c))
                lon, lat = to_ll.transform(x, y)
                win = Window(int(c), int(r), 1, 1)
                bupl = float(pl.read(1, window=win)[0, 0])
                bupr = float(pr.read(1, window=win)[0, 0])
                zid = int(zsrc.read(1, window=win)[0, 0])
                nb = neighbour_median(bui, int(r), int(c))
                out.append({"year": year, "rank": rank, "row": int(r), "col": int(c), "lon": round(lon, 5),
                            "lat": round(lat, 5), "zone_id": zid, "BUI": float(val), "BUPL": bupl, "BUPR": bupr,
                            "bldg_size": float(val) / bupl if bupl > 0 else np.nan, "nb_median_BUI": nb,
                            "ratio_to_nb": float(val) / nb if nb > 0 else np.inf})
    top = pd.DataFrame(out).merge(table[["zone_id", "GISJOIN", "state", "name", "pop", "density", "pop_rank"]],
                                  on="zone_id", how="left")
    log.info("%d: %d cells, %d with BUI > 0, %d nodata | %s | above caps %s", year, n_cells, pos.size, n_nodata,
             " ".join(f"{k} {stats[k]:.4g}" for k in stats if k.startswith("p") or k == "max"),
             {k: v for k, v in stats.items() if k.startswith("n_gt")})
    summarize(top, year, args)
    return stats, top


def summarize(top: pd.DataFrame, year: int, args):
    """Where the largest cells are: metro counties (top --metro-rank by population) or elsewhere; isolated or not."""
    metro = top["pop_rank"] <= args.metro_rank
    spike = top["ratio_to_nb"] > 100
    outside = top["zone_id"] == 0
    log.info("  %d top %d: %d in the %d most populous counties, %d elsewhere, %d outside any county | %d isolated "
             "(> 100 x the neighbour median) | %d counties, %d states | bldg_size median %.3g", year, len(top),
             int(metro.sum()), args.metro_rank, int((~metro & ~outside).sum()), int(outside.sum()), int(spike.sum()),
             top["GISJOIN"].nunique(), top["state"].nunique(), top["bldg_size"].median())
    by = (top.groupby(["state", "name"], dropna=False)
          .agg(cells=("BUI", "size"), max_BUI=("BUI", "max"), pop_rank=("pop_rank", "first"),
               density=("density", "first"), isolated=("ratio_to_nb", lambda s: int((s > 100).sum())))
          .sort_values("cells", ascending=False))
    log.info("  %d top cells by county:\n%s", year, by.round(1).to_string())


def show_docs(hisdac_dir: Path):
    """README / metadata files under the HISDAC folder (names and short text files printed), BUI raster tags."""
    if not hisdac_dir.is_dir():
        log.warning("--hisdac-dir %s is not a folder; docs skipped", hisdac_dir)
        return
    hits = sorted(p for p in hisdac_dir.rglob("*") if p.is_file() and not p.name.endswith(".aux.xml") and (
        p.suffix.lower() in DOC_SUFFIXES and (any(n in p.name.lower() for n in DOC_NAMES) or p.parent == hisdac_dir
                                              or "bui" in p.name.lower())))
    log.info("doc files under %s: %d", hisdac_dir, len(hits))
    for p in hits:
        log.info("  %s (%d bytes)", p, p.stat().st_size)
    for p in hits:
        if p.suffix.lower() in DOC_TEXT_SUFFIXES and p.stat().st_size <= DOC_MAX_BYTES:
            text = p.read_text(encoding="utf-8", errors="replace")
            log.info("==== %s ====\n%s\n==== end %s ====", p, text, p.name)
    for p in sorted((hisdac_dir / "BUI").glob("*BUI*.tif"))[:1]:
        with rasterio.open(p) as src:
            log.info("tags of %s: %s | band tags %s | units %s | descriptions %s | dtype %s nodata %s", p,
                     src.tags(), src.tags(1), src.units, src.descriptions, src.dtypes[0], src.nodata)
    for p in sorted((hisdac_dir / "BUI").glob("*.aux.xml"))[:1]:  # one sidecar (statistics / metadata)
        log.info("==== %s ====\n%s", p, p.read_text(encoding="utf-8", errors="replace")[:DOC_MAX_BYTES])


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    if args.hisdac_dir:
        show_docs(args.hisdac_dir)
    stats, tops = [], []
    for year in sorted(set(args.years)):
        s, t = year_qa(args.cutout, year, args)
        stats.append(s)
        tops.append(t)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    q = pd.DataFrame(stats)
    q.to_csv(args.out_dir / "bui_quantiles.csv", index=False)
    pd.concat(tops, ignore_index=True).to_csv(args.out_dir / "bui_top.csv", index=False)
    log.info("BUI quantiles over cells with BUI > 0:\n%s", q.to_string(index=False))
    log.info("wrote %s, %s", args.out_dir / "bui_quantiles.csv", args.out_dir / "bui_top.csv")
    log.info("DONE")


if __name__ == "__main__":
    main()
