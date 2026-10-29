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
With --years, both keep the rows of the other years from an earlier run.

2020 (request 2026-10-30, docs/conus_plan.md "2020"): the CSV ends in 2010, so every 2010 polygon takes the pop of the
NHGIS 2020 county (--census-dir counties_2020.gpkg) with the same GISJOIN, after the 2010 -> 2020 changes in
NHGIS_REMAP (new code of the same county: Shannon SD -> Oglala Lakota, 2015) and NHGIS_MERGED (a 2010 county merged into
another one before 2020: Bedford city -> Bedford County VA, 2013). Statuses as for the filled polygons above:
  ok                  same unit: NHGIS status ok / manual_fill, pop > 0, NHGIS 2020 area / 2010 polygon area within
                      --area-tol (trained + allocated)
  filled_nhgis_alloc  area ratio outside --area-tol, or the 2020 unit also holds a merged 2010 county (Bedford County:
                      its 2020 pop includes the former city, whose polygon is separate): allocation only
  no_value            no 2020 unit (the merged Bedford city: its cells are NoData; its people are in Bedford County)
  zero_pop            NHGIS pop 0
Connecticut's planning regions replaced its counties in 2022, after the 2020 census: NHGIS 2020 has the 8 counties
(checked in the log). Alaska, Hawaii and Puerto Rico are not in either file. Every decision is written to
<results-dir>/counties_{YEAR}_nhgis_match.csv (one row per 2010 polygon + one per NHGIS unit no polygon takes).

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

CSV_YEARS = list(range(1900, 2011, 10))  # Stefan's CSV
NHGIS_YEARS = [2020]  # after the CSV: NHGIS nominal counties matched to the 2010 polygons
YEARS = CSV_YEARS + NHGIS_YEARS
# 2010 -> 2020 changes of CONUS counties (Census Bureau, "Substantial Changes to Counties", 2010-2020):
NHGIS_REMAP = {2020: {"G4601130": "G4601020"}}  # Shannon County SD renamed Oglala Lakota (FIPS 46113 -> 46102), 2015
NHGIS_MERGED = {2020: {"G5105150": "G5100190"}}  # Bedford city VA merged into Bedford County (51515 -> 51019), 2013
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
    p.add_argument("--years", type=int, nargs="+", default=YEARS,
                   help="census years (1900-2010 from the CSV, 2020 from NHGIS)")
    return p.parse_args(argv)


def year_table(std: gpd.GeoDataFrame, year: int) -> gpd.GeoDataFrame:
    col = f"pop_{year}"
    if col not in std.columns:
        sys.exit(f"ERROR: {col} not in counties_std_2010.gpkg (years 1900-2010)")
    out = std[["GISJOIN", "fips", "state", "name", "area_km2", "geometry"]].copy()
    out["pop"] = pd.to_numeric(std[col], errors="coerce")
    out["status"] = np.where(out["pop"].isna(), "no_value", np.where(out["pop"] > 0, "ok", "zero_pop"))
    return out[COLS]


def nhgis_year_table(std: gpd.GeoDataFrame, year: int, census_dir: Path, area_tol=AREA_TOL):
    """A year after the CSV (2020): each 2010 polygon takes the NHGIS county of that year with the same GISJOIN
    (NHGIS_REMAP / NHGIS_MERGED for the known changes). Returns the year table + one record per polygon and per
    NHGIS unit left over (the match CSV)."""
    path = census_dir / f"counties_{year}.gpkg"
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (NHGIS nominal counties, sbatch/census_prepare.sh)")
    nom = pyogrio.read_dataframe(path, columns=["GISJOIN", "state", "name", "pop", "status", "area_km2"],
                                 read_geometry=False)
    if nom["GISJOIN"].duplicated().any():
        sys.exit(f"ERROR: duplicate GISJOIN in {path}")
    nom = nom.set_index("GISJOIN")
    remap, merged = NHGIS_REMAP.get(year, {}), NHGIS_MERGED.get(year, {})
    receivers = {}
    for gone, into in merged.items():
        receivers.setdefault(into, []).append(gone)
    ct = sorted(g for g in nom.index if g.startswith("G090"))
    log.info("%d: %s: %d NHGIS counties, pop %s | Connecticut units %d: %s", year, path, len(nom),
             f"{nom['pop'].sum():,.0f}", len(ct), ct)
    t = std[["GISJOIN", "fips", "state", "name", "area_km2", "geometry"]].copy()
    t["pop"] = np.nan
    t["status"] = "no_value"
    recs, used = [], set()
    for i in t.index:
        gj = t.at[i, "GISJOIN"]
        rec = {"year": year, "GISJOIN": gj, "state": t.at[i, "state"], "name": t.at[i, "name"], "rule": None,
               "source": None, "source_name": None, "nhgis_status": None, "pop": np.nan,
               "area_2010_km2": t.at[i, "area_km2"], "area_nhgis_km2": np.nan, "area_ratio": np.nan,
               "status": "no_value", "note": ""}
        if gj in merged:
            rec.update(rule="merged_into", source=merged[gj],
                       note=f"merged into {merged[gj]}: its people are counted there, its cells are NoData")
            recs.append(rec)
            continue
        code = remap.get(gj, gj)
        rec["rule"] = "remapped" if gj in remap else "same_code"
        if code not in nom.index:
            rec.update(rule="no_unit", note=f"no NHGIS {year} county {code}")
            recs.append(rec)
            continue
        r = nom.loc[code]
        used.add(code)
        rec.update(source=code, source_name=r["name"], nhgis_status=r["status"], pop=r["pop"],
                   area_nhgis_km2=r["area_km2"], area_ratio=r["area_km2"] / t.at[i, "area_km2"])
        if r["status"] in NHGIS_OK and r["pop"] > 0:
            same = area_tol[0] <= rec["area_ratio"] <= area_tol[1]
            rec["status"] = "ok" if same and gj not in receivers else "filled_nhgis_alloc"
            if gj in receivers:
                rec["note"] = f"also holds {receivers[gj]} (merged): allocation only"
            elif not same:
                rec["note"] = f"area ratio outside {area_tol[0]}-{area_tol[1]}: allocation only"
        elif r["status"] in NHGIS_OK and r["pop"] == 0:
            rec["status"] = "zero_pop"
        else:
            rec["note"] = f"NHGIS status {r['status']}, pop {r['pop']}"
        if rec["status"] != "no_value":
            t.at[i, "pop"] = float(r["pop"])
        t.at[i, "status"] = rec["status"]
        recs.append(rec)
    for code in sorted(set(nom.index) - used):  # NHGIS units no 2010 polygon takes (their people are not allocated)
        r = nom.loc[code]
        recs.append({"year": year, "GISJOIN": None, "state": r["state"], "name": None, "rule": "nhgis_unmatched",
                     "source": code, "source_name": r["name"], "nhgis_status": r["status"], "pop": r["pop"],
                     "status": None, "note": "no 2010 polygon"})
    m = pd.DataFrame(recs)
    log.info("%d: match rules %s | statuses %s", year, m["rule"].value_counts().to_dict(),
             m["status"].value_counts().to_dict())
    special = m[(m["rule"] != "same_code") | (m["status"] != "ok")]
    log.info("%d: polygons not matched 1:1 as ok, and NHGIS units left over:\n%s", year,
             special.to_string(index=False) if len(special) else "(none)")
    lost = m.loc[m["rule"] == "nhgis_unmatched", "pop"].sum()
    if lost > 0:
        log.warning("%d: %s people in NHGIS counties without a 2010 polygon are not allocated", year, f"{lost:,.0f}")
    log.info("%d: area ratio NHGIS / 2010 polygon of the matched counties: min %.4f, median %.4f, max %.4f", year,
             m["area_ratio"].min(), m["area_ratio"].median(), m["area_ratio"].max())
    return t[COLS], m


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


def keep_other_years(new: pd.DataFrame, path: Path, years):
    """Write new + the rows of the other years already in `path` (a --years run replaces only its own years)."""
    if path.exists():
        old = pd.read_csv(path, float_precision="round_trip")  # kept rows written back unchanged
        new = pd.concat([old[~old["year"].isin(years)], new], ignore_index=True).sort_values("year", kind="stable")
    new.to_csv(path, index=False)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    bad = sorted(set(args.years) - set(YEARS))
    if bad:
        sys.exit(f"ERROR: --years {bad}: census years are 1900-2010 (CSV) and {NHGIS_YEARS} (NHGIS)")
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
        if year in NHGIS_YEARS:
            t, match = nhgis_year_table(std, year, args.census_dir, tuple(args.area_tol))
            match.to_csv(args.results_dir / f"counties_{year}_nhgis_match.csv", index=False)
        else:
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
    log.info("summary:\n%s", summary.to_string(index=False))
    keep_other_years(summary, args.results_dir / "counties_conus_summary.csv", args.years)
    if filled:
        f = pd.DataFrame(filled)
        log.info("polygons without a CSV row (filled from NHGIS where possible):\n%s", f.to_string(index=False))
        keep_other_years(f, args.results_dir / "counties_conus_filled.csv", args.years)
    log.info("DONE")


if __name__ == "__main__":
    main()
