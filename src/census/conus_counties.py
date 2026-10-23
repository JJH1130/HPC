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
  filled_nhgis  2010 polygon without any CSV row (Miami-Dade, Shannon SD, Broomfield, Bedford city): pop taken from
            that year's NHGIS nominal county (--census-dir counties_{YEAR}.gpkg from prepare_census.py) with the same
            GISJOIN, or an older code in ALIASES (Miami-Dade = Dade County G1200250); NHGIS status ok or manual_fill
            and pop > 0 only, else no_value. NHGIS area / 2010 polygon area within --area-tol (default 0.95-1.05):
            the same unit, used for allocation AND training (train rows of configs/conus_split.csv)
  filled_nhgis_alloc  as filled_nhgis, but the area ratio is outside that range: allocation only (not in
            train_status), since the NHGIS count belongs to a differently drawn unit
Also writes <results-dir>/counties_conus_summary.csv (counties, pop and area per year and status) and
<results-dir>/counties_conus_filled.csv (filled county-years: source GISJOIN, pop, NHGIS area / 2010 polygon area).

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
import pyogrio

from prepare_census import gpkg_leftovers, local_tmp_dir, write_gpkg

YEARS = list(range(1900, 2011, 10))
COLS = ["GISJOIN", "fips", "state", "name", "pop", "status", "area_km2", "geometry"]
# 2010 GISJOIN -> older NHGIS codes of the same county, tried after the 2010 code (Dade County before 1997)
ALIASES = {"G1200860": ["G1200250"]}
NHGIS_OK = {"ok", "manual_fill"}
AREA_TOL = (0.95, 1.05)  # NHGIS area / 2010 polygon area for filled_nhgis (trainable); outside: filled_nhgis_alloc

log = logging.getLogger("conus_counties")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--std-gpkg", type=Path, required=True, help="counties_std_2010.gpkg (std_county_check.py)")
    p.add_argument("--census-dir", type=Path, required=True,
                   help="NHGIS nominal counties_{YEAR}.gpkg (prepare_census.py), read only: fills polygons without a CSV row")
    p.add_argument("--out-dir", type=Path, required=True, help="counties_{YEAR}.gpkg go here")
    p.add_argument("--area-tol", type=float, nargs=2, default=AREA_TOL, metavar=("MIN", "MAX"),
                   help="NHGIS / 2010 area ratio range for status filled_nhgis (trainable); outside: filled_nhgis_alloc")
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


def fill_from_nhgis(t: gpd.GeoDataFrame, year: int, census_dir: Path, area_tol=AREA_TOL) -> list[dict]:
    """Polygons without a CSV row (fips missing) get the NHGIS nominal county pop of the same GISJOIN (or an
    ALIASES code); status filled_nhgis (area ratio within area_tol) or filled_nhgis_alloc. Returns one record per polygon for the log and the filled CSV."""
    todo = t.index[t["fips"].isna()]
    if not len(todo):
        return []
    path = census_dir / f"counties_{year}.gpkg"
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (NHGIS nominal counties, sbatch/census_prepare.sh)")
    nom = pyogrio.read_dataframe(path, columns=["GISJOIN", "name", "pop", "status", "area_km2"], read_geometry=False)
    nom = nom.set_index("GISJOIN")
    recs = []
    for i in todo:
        gj = t.at[i, "GISJOIN"]
        rec = {"year": year, "GISJOIN": gj, "state": t.at[i, "state"], "name": t.at[i, "name"], "source": None,
               "source_name": None, "nhgis_status": None, "pop": np.nan, "area_2010_km2": t.at[i, "area_km2"],
               "area_nhgis_km2": np.nan, "area_ratio": np.nan, "filled": False, "status": "no_value"}
        for code in [gj] + ALIASES.get(gj, []):
            if code in nom.index:
                r = nom.loc[code]
                rec.update(source=code, source_name=r["name"], nhgis_status=r["status"], pop=r["pop"],
                           area_nhgis_km2=r["area_km2"], area_ratio=r["area_km2"] / t.at[i, "area_km2"])
                break
        if rec["source"] and rec["nhgis_status"] in NHGIS_OK and rec["pop"] > 0:
            same = area_tol[0] <= rec["area_ratio"] <= area_tol[1]
            t.at[i, "pop"] = float(rec["pop"])
            t.at[i, "status"] = rec["status"] = "filled_nhgis" if same else "filled_nhgis_alloc"
            rec["filled"] = True
        log.info("  %d %s %s: %s", year, gj, rec["name"],
                 f"filled from NHGIS {rec['source']} ({rec['source_name']}): pop {rec['pop']:,.0f}, area NHGIS / 2010 "
                 f"{rec['area_ratio']:.3f} -> {rec['status']} ("
                 f"{'within' if rec['status'] == 'filled_nhgis' else 'outside'} {area_tol[0]}-{area_tol[1]}: "
                 f"{'training + allocation' if rec['status'] == 'filled_nhgis' else 'allocation only'})"
                 if rec["filled"] else
                 f"not filled (NHGIS {rec['source'] or 'no county'}, status {rec['nhgis_status']}, pop {rec['pop']}): no_value")
        recs.append(rec)
    return recs


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
    rows, filled = [], []
    for year in sorted(args.years):
        t = year_table(std, year)
        filled += fill_from_nhgis(t, year, args.census_dir, tuple(args.area_tol))
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
    if filled:
        f = pd.DataFrame(filled)
        f.to_csv(args.results_dir / "counties_conus_filled.csv", index=False)
        log.info("polygons without a CSV row (filled from NHGIS where possible):\n%s", f.to_string(index=False))
    log.info("DONE")


if __name__ == "__main__":
    main()
