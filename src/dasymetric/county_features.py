"""Stage 1: county features + target from the study-area cutout (design: docs/dasymetric_v1.md).

Writes <out-root>/<name>/<version>/features/county_features.csv, one row per county-year:
  year, zone_id, GISJOIN, state, name, status, n_cells, <features>, pop, area_km2, y

Only counties whose status is in `use_status` (configs/model.yaml) are kept. County feature =
mean of the cell feature over all cells of the county (zone == county, including 0 cells).
Target y = log(pop / area_km2), area from the census polygons.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from common import (add_common_args, cell_features, county_selection, load_config, log, log_args,
                    out_dir, read_zones, setup_logging)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(p)
    p.add_argument("--cutout-root", type=Path, required=True, help="cutout is <cutout-root>/<name>/")
    return p.parse_args(argv)


def year_rows(cutout: Path, year: int, cfg: dict) -> tuple[pd.DataFrame, int]:
    zones, table, grid = read_zones(cutout, year)
    used = county_selection(table, zones, cfg["use_status"], year)
    mask = np.isin(zones, used["zone_id"].to_numpy())
    feats = cell_features(cutout, year, grid, mask, cfg["features"])
    z = zones[mask]
    n = np.bincount(z)
    rows = used[["zone_id", "GISJOIN", "state", "name", "status", "n_cells"]].copy()
    rows.insert(0, "year", year)
    zid = rows["zone_id"].to_numpy()
    for f in cfg["features"]:
        rows[f] = np.bincount(z, weights=feats[f].to_numpy())[zid] / n[zid]
    rows["pop"] = used["pop"].to_numpy()
    rows["area_km2"] = used["area_km2"].to_numpy()
    rows["y"] = np.log(rows["pop"] / rows["area_km2"])
    log.info("  %d: %d counties in the table, %d used, %d cells", year, len(table), len(rows), int(mask.sum()))
    return rows, len(table)


def main(argv=None):
    setup_logging()
    args = parse_args(argv)
    log_args(args)
    cfg = load_config(args.config)
    cutout = args.cutout_root / cfg["name"]
    out = out_dir(cfg, args.out_root)
    log.info("study %r %s | %d years %d-%d | features %s | use_status %s -> %s", cfg["name"], cfg["version"],
             len(cfg["years"]), cfg["years"][0], cfg["years"][-1], cfg["features"], cfg["use_status"], out)

    parts, n_all = [], 0
    for year in cfg["years"]:
        rows, n_table = year_rows(cutout, year, cfg)
        parts.append(rows)
        n_all += n_table
    df = pd.concat(parts, ignore_index=True)
    if not np.isfinite(df[cfg["features"] + ["y"]].to_numpy()).all():
        sys.exit("ERROR: non-finite county features or target")

    log.info("county-years: %d before status filtering (expected 314 for massachusetts), %d training rows "
             "| %d counties (GISJOIN) | %d years", n_all, len(df), df["GISJOIN"].nunique(), df["year"].nunique())
    log.info("feature summary:\n%s", df[cfg["features"] + ["y"]].describe().T.round(3).to_string())
    path = out / "features" / "county_features.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    log.info("wrote %s", path)
    log.info("DONE")


if __name__ == "__main__":
    main()
