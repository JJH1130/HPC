"""County population input for the CONUS runs (docs/conus_plan.md): Stefan's county CSV on 2010 county polygons.

Reads counties_std_2010.gpkg (written by std_county_check.py: NHGIS 2010 polygons + the CSV's pop_{YEAR} columns,
joined by 2010 FIPS) and writes, per requested census year, <out-dir>/counties_{YEAR}.gpkg with the columns
make_cutout.py and the dasymetric steps read:
  GISJOIN, fips, state, name, pop, status, area_km2, geometry
All years share the same polygons in the same row order (sorted by GISJOIN), so a county has the same zone_id
(GPKG feature id) in every year. status:
  ok        pop > 0 (used for training and allocation)
  no_value  no CSV value for that year (NaN, or a 2010 polygon without a CSV row: Miami-Dade, Broomfield,
            Shannon SD, Bedford city); not used, its cells are NoData (known input errors, docs/conus_plan.md)
  zero_pop  CSV value 0; not used (y = log(0) is undefined), its cells are NoData
Also writes <results-dir>/counties_conus_summary.csv (counties, pop and area per year and status).

Paths come from CLI flags (sbatch/census_conus.sh).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from prepare_census import gpkg_leftovers, local_tmp_dir, write_gpkg

YEARS = list(range(1900, 2011, 10))
COLS = ["GISJOIN", "fips", "state", "name", "pop", "status", "area_km2", "geometry"]

log = logging.getLogger("conus_counties")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--std-gpkg", type=Path, required=True, help="counties_std_2010.gpkg (std_county_check.py)")
    p.add_argument("--out-dir", type=Path, required=True, help="counties_{YEAR}.gpkg go here")
    p.add_argument("--results-dir", type=Path, required=True, help="summary CSV (tracked in git)")
    p.add_argument("--years", type=int, nargs="+", default=YEARS, help="census years (1900-2010)")
    return p.parse_args(argv)


def year_table(std: gpd.GeoDataFrame, year: int) -> gpd.GeoDataFrame:
    col = f"pop_{year}"
    if col not in std.columns:
        sys.exit(f"ERROR: {col} not in counties_std_2010.gpkg (years 1900-2010)")
    out = std[["GISJOIN", "fips", "state", "name", "area_km2", "geometry"]].copy()
    out["pop"] = pd.to_numeric(std[col], errors="coerce")
    out["status"] = np.where(out["pop"].isna(), "no_value", np.where(out["pop"] > 0, "ok", "zero_pop"))
    return out[COLS]


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    bad = sorted(set(args.years) - set(YEARS))
    if bad:
        sys.exit(f"ERROR: --years {bad}: the CSV has census years 1900-2010 only")
    if not args.std_gpkg.exists():
        sys.exit(f"ERROR: {args.std_gpkg} not found (run sbatch/std_county_check.sh first)")
    std = gpd.read_file(args.std_gpkg, engine="pyogrio").sort_values("GISJOIN").reset_index(drop=True)
    if std["GISJOIN"].duplicated().any():
        sys.exit(f"ERROR: duplicate GISJOIN in {args.std_gpkg}")
    log.info("%s: %d polygons, %d without a CSV row, CRS %s", args.std_gpkg, len(std), int(std["fips"].isna().sum()),
             std.crs.to_string() if std.crs else None)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.results_dir.mkdir(parents=True, exist_ok=True)
    tmp = local_tmp_dir()
    tmp.mkdir(parents=True, exist_ok=True)
    rows = []
    for year in sorted(args.years):
        t = year_table(std, year)
        path = args.out_dir / f"counties_{year}.gpkg"
        for f in gpkg_leftovers(path)[1:]:  # side files from a failed earlier run
            f.unlink(missing_ok=True)
        write_gpkg(t, path, tmp)
        s = t.groupby("status").agg(counties=("GISJOIN", "size"), pop=("pop", "sum"), area_km2=("area_km2", "sum"))
        for status, r in s.iterrows():
            rows.append({"year": year, "status": status, "counties": int(r["counties"]), "pop": float(r["pop"]),
                         "area_km2": float(r["area_km2"]), "area_share": float(r["area_km2"] / t["area_km2"].sum())})
        log.info("%d: %s | pop (ok) %s | wrote %s", year, s["counties"].to_dict(),
                 f"{t.loc[t['status'] == 'ok', 'pop'].sum():,.0f}", path)
        nv = t[t["status"] != "ok"]
        if len(nv):
            log.info("  not ok (first 30): %s", list(zip(nv["GISJOIN"], nv["state"], nv["name"], nv["status"]))[:30])
    summary = pd.DataFrame(rows)
    summary.to_csv(args.results_dir / "counties_conus_summary.csv", index=False)
    log.info("summary:\n%s", summary.to_string(index=False))
    log.info("DONE")


if __name__ == "__main__":
    main()
