"""Diagnostic: compare the county CSV from Stefan Leyk (1900-2010 by 2010 FIPS) with the
nominal NHGIS counties written by prepare_census.py.

Steps:
  1. Read the CSV, drop Alaska (02) and Hawaii (15), build GISJOIN = "G" + 2-digit state
     + "0" + 3-digit county + "0" (NHGIS county code).
  2. Join to the NHGIS 2010 polygons (counties_2010.gpkg); report CSV rows without a
     polygon and polygons without a CSV row (std_vs_2010_unmatched.csv).
  3. For each year 1900-2010, match on GISJOIN to counties_{YEAR}.gpkg (nominal) and record
     pop_std, pop_nominal, area_year_km2, area_2010_km2, area_ratio. Classes:
       stable           pop_std == pop_nominal and 0.99 <= area_ratio <= 1.01
       boundary_change  any other matched row with both pops
       missing          NaN in the CSV, no nominal polygon, or nominal pop NaN (`detail` says which)
       no_2010_polygon  CSV row with a pop but no 2010 polygon, so no area ratio
  4. Writes to --results-dir: std_county_check.csv (one row per county-year),
     std_county_summary.csv and std_county_summary_MA.csv (counts and pop shares per
     year x class; class nominal_only = nominal counties no CSV row matches).
  5. Writes counties_std_2010.gpkg (2010 polygons + all CSV pop and CBSA columns) to --out-dir.

Existing census outputs are only read. Paths come from CLI flags (sbatch/std_county_check.sh).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

from prepare_census import gpkg_leftovers, local_tmp_dir, write_gpkg

YEARS = list(range(1900, 2011, 10))
DROP_STATES = ("02", "15")  # Alaska, Hawaii
MA_PREFIX = "G250"
AREA_TOL = 0.01
POP_COLS = {f"CENSUS{y}POP": f"pop_{y}" for y in YEARS} | {"POPESTIMATE2015": "pop_est2015"}
CBSA_COLS = {
    "CBSA Code": "cbsa_code",
    "Metropolitan Division Code": "metro_div_code",
    "CSA Code": "csa_code",
    "CBSA Title": "cbsa_title",
    "Metropolitan/Micropolitan Statistical Area": "cbsa_type",
    "Metropolitan Division Title": "metro_div_title",
    "CSA Title": "csa_title",
    "Central/Outlying County": "central_outlying",
}
CLASSES = ["stable", "boundary_change", "missing", "no_2010_polygon", "nominal_only"]

log = logging.getLogger("std_county_check")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--std-csv", type=Path, required=True, help="all_county_census_MSA_full.csv")
    p.add_argument("--census-dir", type=Path, required=True, help="folder with counties_{YEAR}.gpkg (read only)")
    p.add_argument("--out-dir", type=Path, required=True, help="where counties_std_2010.gpkg goes")
    p.add_argument("--results-dir", type=Path, required=True, help="small CSVs tracked in git")
    return p.parse_args(argv)


def read_std(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False, na_values=[""])
    missing = {"FIPS", "STNAME", "CTYNAME", *POP_COLS, *CBSA_COLS} - set(raw.columns)
    if missing:
        sys.exit(f"ERROR: {path} is missing columns {sorted(missing)}; found {list(raw.columns)}")
    fips = raw["FIPS"].str.strip().str.zfill(5)  # stored as a number: leading zero lost
    df = pd.DataFrame({
        "GISJOIN": "G" + fips.str[:2] + "0" + fips.str[2:] + "0",
        "fips": fips,
        "csv_state": raw["STNAME"],
        "csv_name": raw["CTYNAME"],
    })
    for src, dst in POP_COLS.items():
        df[dst] = pd.to_numeric(raw[src].str.replace(",", ""), errors="coerce").astype("float64")
    for src, dst in CBSA_COLS.items():
        df[dst] = raw[src]
    log.info("CSV: %d rows, %d states", len(df), df["csv_state"].nunique())
    dup = df["fips"].duplicated(keep=False)
    if dup.any():
        sys.exit(f"ERROR: duplicate FIPS in {path}: {sorted(df.loc[dup, 'fips'].unique())}")

    drop = df["fips"].str[:2].isin(DROP_STATES)
    log.info("dropped %d AK/HI rows (%s)", drop.sum(), df.loc[drop, "csv_state"].value_counts().to_dict())
    df = df[~drop].reset_index(drop=True)

    # NaN pattern: expected NaN only before a county's first value (county did not exist yet)
    pops = df[[f"pop_{y}" for y in YEARS]]
    started = pops.notna().cummax(axis=1)
    gaps = (started & pops.isna()).any(axis=1)
    log.info("counties with NaN in some year: %d; NaN after a first value (gaps): %d %s",
             int(pops.isna().any(axis=1).sum()), int(gaps.sum()),
             list(zip(df.loc[gaps, "fips"], df.loc[gaps, "csv_name"]))[:20])
    for y in YEARS:
        log.info("  %d: %d counties with pop, total %s", y, df[f"pop_{y}"].notna().sum(),
                 f"{df[f'pop_{y}'].sum():,.0f}")
    return df


def read_nominal(census_dir: Path, year: int, geometry=False):
    path = census_dir / f"counties_{year}.gpkg"
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (run sbatch/census_prepare.sh first)")
    if geometry:
        return gpd.read_file(path, layer="counties", engine="pyogrio")
    return pyogrio.read_dataframe(path, layer="counties", read_geometry=False)


def check_2010(std: pd.DataFrame, poly: pd.DataFrame) -> pd.DataFrame:
    csv_only = std[~std["GISJOIN"].isin(poly["GISJOIN"])]
    poly_only = poly[~poly["GISJOIN"].isin(std["GISJOIN"])]
    log.info("2010 join: %d CSV rows, %d polygons, %d matched", len(std), len(poly),
             std["GISJOIN"].isin(poly["GISJOIN"]).sum())
    log.info("CSV rows without a 2010 polygon (%d): %s", len(csv_only),
             list(zip(csv_only["GISJOIN"], csv_only["csv_state"], csv_only["csv_name"])))
    log.info("2010 polygons without a CSV row (%d): %s", len(poly_only),
             list(zip(poly_only["GISJOIN"], poly_only["state"], poly_only["name"], poly_only["pop"])))
    return pd.concat([
        pd.DataFrame({"side": "csv_only", "GISJOIN": csv_only["GISJOIN"], "state": csv_only["csv_state"],
                      "name": csv_only["csv_name"], "pop_2010": csv_only["pop_2010"]}),
        pd.DataFrame({"side": "polygon_only", "GISJOIN": poly_only["GISJOIN"], "state": poly_only["state"],
                      "name": poly_only["name"], "pop_2010": poly_only["pop"]}),
    ], ignore_index=True)


def check_year(year, std, area_2010, census_dir):
    nom = read_nominal(census_dir, year)[["GISJOIN", "pop", "status", "area_km2"]]
    nom = nom.rename(columns={"pop": "pop_nominal", "status": "nominal_status", "area_km2": "area_year_km2"})
    d = std[["GISJOIN", "fips", "csv_state", "csv_name", f"pop_{year}"]].rename(
        columns={f"pop_{year}": "pop_std", "csv_state": "state", "csv_name": "name"})
    d = d.merge(nom, on="GISJOIN", how="left", indicator=True)
    d = d.merge(area_2010, on="GISJOIN", how="left")
    d.insert(4, "year", year)
    d["area_ratio"] = d["area_year_km2"] / d["area_2010_km2"]
    d["pop_diff"] = d["pop_std"] - d["pop_nominal"]
    d["pop_equal"] = d["pop_std"].eq(d["pop_nominal"])
    d["area_equal"] = d["area_ratio"].between(1 - AREA_TOL, 1 + AREA_TOL)

    no_match = d["_merge"].eq("left_only")
    d["detail"] = ""
    d.loc[d["pop_nominal"].isna(), "detail"] = "nominal_pop_nan"
    d.loc[no_match, "detail"] = "no_nominal_match"
    d.loc[d["pop_std"].isna(), "detail"] = "csv_nan"
    d["class"] = "boundary_change"
    d.loc[d["pop_equal"] & d["area_equal"], "class"] = "stable"
    d.loc[d["area_2010_km2"].isna(), "class"] = "no_2010_polygon"
    d.loc[d["detail"].ne(""), "class"] = "missing"
    d = d.drop(columns="_merge")

    nominal_only = nom[~nom["GISJOIN"].isin(std["GISJOIN"])]
    counts = d["class"].value_counts().to_dict()
    log.info("%d: %s | nominal counties without CSV row: %d (pop %s)", year, counts, len(nominal_only),
             f"{nominal_only['pop_nominal'].sum():,.0f}")
    if len(nominal_only):
        log.info("  nominal only: %s", list(nominal_only["GISJOIN"])[:40])
    ex = d[d["class"].eq("boundary_change")].assign(a=lambda x: x["pop_diff"].abs()).nlargest(5, "a")
    for r in ex.itertuples():
        log.info("  largest pop diff: %s %s, %s: std %s vs nominal %s, area ratio %.3f", r.GISJOIN, r.name,
                 r.state, f"{r.pop_std:,.0f}", f"{r.pop_nominal:,.0f}", r.area_ratio)
    return d, nominal_only.assign(year=year)


def summarize(rows: pd.DataFrame, nominal_only: pd.DataFrame) -> pd.DataFrame:
    """Counts and pop shares per year x class. pop_std_share is over the CSV total for the
    year; pop_nominal_share is over the nominal total (so it includes nominal_only)."""
    g = rows.groupby(["year", "class"]).agg(n=("GISJOIN", "size"), pop_std=("pop_std", "sum"),
                                            pop_nominal=("pop_nominal", "sum")).reset_index()
    no = nominal_only.groupby("year").agg(n=("GISJOIN", "size"), pop_nominal=("pop_nominal", "sum")).reset_index()
    no["class"], no["pop_std"] = "nominal_only", 0.0
    s = pd.concat([g, no], ignore_index=True)
    full = pd.MultiIndex.from_product([sorted(rows["year"].unique()), CLASSES], names=["year", "class"])
    s = s.set_index(["year", "class"]).reindex(full).reset_index()
    s[["n", "pop_std", "pop_nominal"]] = s[["n", "pop_std", "pop_nominal"]].fillna(0)
    s["n"] = s["n"].astype(int)
    by_year = s.groupby("year")
    s["n_share"] = s["n"] / by_year["n"].transform("sum")
    s["pop_std_share"] = s["pop_std"] / by_year["pop_std"].transform("sum")
    s["pop_nominal_share"] = s["pop_nominal"] / by_year["pop_nominal"].transform("sum")
    return s


def write_std_gpkg(poly: gpd.GeoDataFrame, std: pd.DataFrame, out_dir: Path):
    out = poly[["GISJOIN", "state", "name", "area_km2", "geometry"]].merge(std, on="GISJOIN", how="left")
    cols = ["GISJOIN", "fips", "state", "name", "csv_state", "csv_name", "area_km2",
            *POP_COLS.values(), *CBSA_COLS.values(), "geometry"]
    out = gpd.GeoDataFrame(out[cols], geometry="geometry", crs=poly.crs).sort_values("GISJOIN")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "counties_std_2010.gpkg"
    for f in gpkg_leftovers(path)[1:]:  # side files from a failed earlier run
        f.unlink(missing_ok=True)
    tmp = local_tmp_dir()
    tmp.mkdir(parents=True, exist_ok=True)
    write_gpkg(out.reset_index(drop=True), path, tmp)
    log.info("wrote %s (%d polygons, %d without CSV row, %.1f MB)", path, len(out),
             out["fips"].isna().sum(), path.stat().st_size / 1e6)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    args.results_dir.mkdir(parents=True, exist_ok=True)

    std = read_std(args.std_csv)
    poly = read_nominal(args.census_dir, 2010, geometry=True)
    unmatched = check_2010(std, poly)
    unmatched.to_csv(args.results_dir / "std_vs_2010_unmatched.csv", index=False)
    area_2010 = poly[["GISJOIN", "area_km2"]].rename(columns={"area_km2": "area_2010_km2"})

    rows, nominal_only = [], []
    for year in YEARS:
        r, n = check_year(year, std, area_2010, args.census_dir)
        rows.append(r)
        nominal_only.append(n)
    rows = pd.concat(rows, ignore_index=True)
    nominal_only = pd.concat(nominal_only, ignore_index=True)
    rows.to_csv(args.results_dir / "std_county_check.csv", index=False)

    summary = summarize(rows, nominal_only)
    summary.to_csv(args.results_dir / "std_county_summary.csv", index=False)
    is_ma = rows["GISJOIN"].str.startswith(MA_PREFIX)
    summary_ma = summarize(rows[is_ma], nominal_only[nominal_only["GISJOIN"].str.startswith(MA_PREFIX)])
    summary_ma.to_csv(args.results_dir / "std_county_summary_MA.csv", index=False)
    with pd.option_context("display.width", 200, "display.max_rows", 200, "display.float_format", "{:,.4f}".format):
        log.info("summary (CONUS):\n%s", summary.to_string(index=False))
        log.info("summary (Massachusetts):\n%s", summary_ma.to_string(index=False))

    write_std_gpkg(poly, std, args.out_dir)
    log.info("DONE")


if __name__ == "__main__":
    main()
