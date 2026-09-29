"""Prepare NHGIS county population + boundaries (CONUS, 1810-2020) for the HISDAC work.

For each decennial year this writes counties_{YEAR}.gpkg (ESRI:102039, same CRS as
HISDAC) with columns GISJOIN, year, state, name, pop, status, area_km2, geometry,
plus qa_report.csv (one row per year) and dropped_rows.csv (every excluded row + reason).

Rules, applied in this order per year:
  1. CONUS only: Alaska, Hawaii, Puerto Rico removed (CSV and shapefile).
  2. "multi-county group" CSV rows removed; before removal their pop is compared with
     the state's county-row total and logged.
  3. Manual crosswalk (configs/nhgis_crosswalk.csv): CSV GISJOIN -> shapefile GISJOIN;
     several CSV rows landing on one boundary have their pop summed.
  4. Manual pop fills (configs/nhgis_manual_fills.csv) -> status manual_fill.
     1820 D.C. has no boundary: the 1830 G110* polygons are dissolved into one unit.
  5. Boundary without pop -> nodata_unenumerated (kept); pop == 0 -> nodata_zero (kept);
     pop without boundary -> dropped (dropped_rows.csv).

Paths come from CLI flags (the sbatch script fills them from sbatch/cluster_env.sh).
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely.geometry import MultiPolygon

TARGET_CRS = "ESRI:102039"  # USA Contiguous Albers Equal Area Conic (USGS) — HISDAC's CRS
YEARS = list(range(1810, 2021, 10))
NON_CONUS_PREFIXES = ("G020", "G150", "G720")  # Alaska, Hawaii, Puerto Rico
NON_CONUS_NAMES = re.compile(r"alaska|hawaii|puerto rico", re.IGNORECASE)
GROUP_PATTERN = "multi-county group"
# year -> (new GISJOIN, name, state, donor year, donor GISJOIN prefix): years whose
# NHGIS shapefile lacks a unit, rebuilt by dissolving the donor year's polygons.
BORROWED_BOUNDARIES = {1820: ("G1100010", "District of Columbia", "District Of Columbia", 1830, "G110")}
EXPECTED_TOTALS = {1810: 7_239_881}  # published U.S. totals, for the QA log
STATE_COLS = ("STATENAM", "STATE_NAME", "STATENAME", "STATE")
NAME_COLS = ("NHGISNAM", "NAMELSAD", "NAME")
OUT_COLS = ["GISJOIN", "year", "state", "name", "pop", "status", "area_km2", "geometry"]
DROP_COLS = ["year", "source", "GISJOIN", "state", "name", "pop", "reason", "detail"]

log = logging.getLogger("prepare_census")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pop-csv", type=Path, required=True, help="NHGIS time-series CSV (long layout)")
    p.add_argument("--shape-dir", type=Path, required=True, help="folder searched for US_county_{YEAR}*.shp")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--crosswalk", type=Path, required=True, help="year,csv_gisjoin,shp_gisjoin,note")
    p.add_argument("--manual-fills", type=Path, required=True, help="year,gisjoin,pop,source")
    p.add_argument("--years", type=int, nargs="+", default=YEARS, help="subset of years (default: all 22)")
    return p.parse_args(argv)


# ---------------------------------------------------------------- inputs

def read_population(path: Path) -> pd.DataFrame:
    try:
        raw = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False, na_values=[""])
    except UnicodeDecodeError:
        raw = pd.read_csv(path, dtype=str, encoding="latin-1", keep_default_na=False, na_values=[""])
    missing = {"GISJOIN", "YEAR", "STATE", "COUNTY", "NAME", "A00AA"} - set(raw.columns)
    if missing:
        sys.exit(f"ERROR: {path} is missing columns {sorted(missing)}; found {list(raw.columns)}")
    df = pd.DataFrame({
        "GISJOIN": raw["GISJOIN"].str.strip(),
        "year": pd.to_numeric(raw["YEAR"], errors="coerce"),
        "state": raw["STATE"],
        "county": raw["COUNTY"].fillna(""),
        "name": raw["NAME"].fillna(""),
        "pop": pd.to_numeric(raw["A00AA"], errors="coerce"),
    })
    log.info("population CSV: %d rows, years %s", len(df), sorted(df["year"].dropna().astype(int).unique().tolist()))
    return df


def find_shapefiles(shape_dir: Path, years) -> dict[int, Path]:
    found, problems = {}, []
    for year in years:
        hits = sorted(shape_dir.glob(f"**/US_county_{year}*.shp"))
        if len(hits) == 1:
            found[year] = hits[0]
        else:
            problems.append(f"  {year}: {len(hits)} matches {[str(h) for h in hits]}")
    if problems:
        sys.exit("ERROR: need exactly one US_county_{YEAR}*.shp per year under "
                 f"{shape_dir}:\n" + "\n".join(problems))
    return found


def _first_col(columns, candidates):
    return next((c for c in candidates if c in columns), None)


def read_boundary_attrs(path: Path) -> pd.DataFrame:
    """Attributes only (fast) — used to validate the crosswalk before the long loop."""
    df = pyogrio.read_dataframe(path, read_geometry=False)
    return _standardize_attrs(df, path)


def _standardize_attrs(df, path):
    if "GISJOIN" not in df.columns:
        sys.exit(f"ERROR: {path} has no GISJOIN column; found {list(df.columns)}")
    state_col, name_col = _first_col(df.columns, STATE_COLS), _first_col(df.columns, NAME_COLS)
    return pd.DataFrame({
        "GISJOIN": df["GISJOIN"].astype(str).str.strip(),
        "shp_state": df[state_col] if state_col else None,
        "shp_name": df[name_col] if name_col else None,
    })


def read_boundaries(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path, engine="pyogrio")
    if gdf.crs is None:
        sys.exit(f"ERROR: {path} has no CRS (.prj missing?)")
    out = gpd.GeoDataFrame(_standardize_attrs(gdf, path), geometry=gdf.geometry.values, crs=gdf.crs)
    log.info("  boundaries: %s (%d features, source CRS %s)", path.name, len(out), gdf.crs.name)
    out = out.to_crs(TARGET_CRS)
    dup = out["GISJOIN"].duplicated(keep=False)
    if dup.any():
        log.info("  %d features share %d GISJOINs -> dissolving by GISJOIN",
                 dup.sum(), out.loc[dup, "GISJOIN"].nunique())
        single = out[~dup]
        merged = [
            {"GISJOIN": g, "shp_state": part["shp_state"].iloc[0], "shp_name": part["shp_name"].iloc[0],
             "geometry": dissolve(part.geometry)}
            for g, part in out[dup].groupby("GISJOIN")
        ]
        out = pd.concat([single, gpd.GeoDataFrame(merged, crs=out.crs)], ignore_index=True)
    return out


def dissolve(geoms: gpd.GeoSeries):
    merged = geoms.make_valid().union_all()
    if merged.geom_type == "GeometryCollection":  # make_valid can leave stray lines/points
        polys = [p for g in merged.geoms for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon"]
        merged = MultiPolygon(polys)
    return merged


def read_config(path: Path, cols) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, comment="#").apply(lambda s: s.str.strip())
    missing = set(cols) - set(df.columns)
    if missing:
        sys.exit(f"ERROR: {path} is missing columns {sorted(missing)}")
    df["year"] = df["year"].astype(int)
    return df


def is_non_conus(gisjoin: pd.Series, state: pd.Series) -> pd.Series:
    return gisjoin.str.startswith(NON_CONUS_PREFIXES) | state.fillna("").str.contains(NON_CONUS_NAMES)


def validate_crosswalk(crosswalk: pd.DataFrame, pop: pd.DataFrame, shapefiles: dict[int, Path]):
    """Fail before the long loop if a crosswalk target isn't in that year's shapefile.
    Also logs same-state boundaries whose name shares the CSV unit's first word, so a
    hand-entered GISJOIN (e.g. Alexandria County, 1900) can be confirmed from the log."""
    bad = []
    for year, rows in crosswalk.groupby("year"):
        if year not in shapefiles:
            continue
        attrs = read_boundary_attrs(shapefiles[year])
        for r in rows.itertuples():
            src = pop[(pop["year"] == year) & (pop["GISJOIN"] == r.csv_gisjoin)]
            src_name = src["name"].iloc[0] if len(src) else "(not in CSV)"
            target = attrs[attrs["GISJOIN"] == r.shp_gisjoin]
            word = src_name.split()[0] if len(src) else ""
            cands = attrs[attrs["GISJOIN"].str[:4].eq(r.shp_gisjoin[:4])
                          & attrs["shp_name"].fillna("").str.contains(re.escape(word), case=False)] if word else attrs[:0]
            log.info("crosswalk %d: %s (%s) -> %s (%s) | same-state boundaries matching %r: %s",
                     year, r.csv_gisjoin, src_name, r.shp_gisjoin,
                     target["shp_name"].iloc[0] if len(target) else "NOT FOUND", word,
                     list(zip(cands["GISJOIN"], cands["shp_name"])))
            if not len(src):
                log.warning("crosswalk %d: CSV has no row %s — mapping has no effect", year, r.csv_gisjoin)
            if target.empty:
                bad.append(f"  {year}: {r.shp_gisjoin} not in {shapefiles[year].name}; "
                           f"candidates: {list(zip(cands['GISJOIN'], cands['shp_name']))}")
    if bad:
        sys.exit("ERROR: crosswalk targets missing from boundary files "
                 "(fix configs/nhgis_crosswalk.csv):\n" + "\n".join(bad))


# ---------------------------------------------------------------- one year

def drop_rows(df, year, source, reason, detail=""):
    out = pd.DataFrame({
        "year": year, "source": source, "GISJOIN": df["GISJOIN"].values,
        "state": df["state"].values if "state" in df else df["shp_state"].values,
        "name": df["name"].values if "name" in df else df["shp_name"].values,
        "pop": df["pop"].values if "pop" in df else float("nan"),
        "reason": reason, "detail": detail,
    })
    return out[DROP_COLS]


def process_year(year, pop_all, shapefiles, crosswalk, fills, out_dir):
    log.info("===== %d =====", year)
    dropped = []
    pop = pop_all[pop_all["year"] == year].copy()
    n_rows_raw = len(pop)

    # 1. CONUS only
    nc = is_non_conus(pop["GISJOIN"], pop["state"])
    if nc.any():
        dropped.append(drop_rows(pop[nc], year, "csv", "non_conus"))
        log.info("  CSV: dropped %d non-CONUS rows (pop %s)", nc.sum(), f"{pop.loc[nc, 'pop'].sum():,.0f}")
    pop = pop[~nc]
    n_rows_conus = len(pop)

    # 2. multi-county groups — log the comparison with the state's county rows, then drop
    grp = (pop["county"].str.contains(GROUP_PATTERN, case=False)
           | pop["name"].str.contains(GROUP_PATTERN, case=False))
    pop_group = 0.0
    for state, g in pop[grp].groupby("state"):
        county_sum = pop.loc[~grp & (pop["state"] == state), "pop"].sum()
        g_sum = g["pop"].sum()
        log.info("  multi-county group, %s: state county-row sum=%s; group rows sum=%s (equal=%s)",
                 state, f"{county_sum:,.0f}", f"{g_sum:,.0f}", county_sum == g_sum)
        details = []
        for r in g.itertuples():
            details.append(f"group pop={r.pop:,.0f}; state county-row sum={county_sum:,.0f}; "
                           f"equal={r.pop == county_sum}; all group rows sum={g_sum:,.0f}")
            log.info("    %s %s: %s", r.GISJOIN, r.name, details[-1])
        dropped.append(drop_rows(g, year, "csv", "multi_county_group", details))
        pop_group += g_sum
    pop = pop[~grp]

    # 3. crosswalk, then sum rows that share a boundary
    pop["src_gisjoin"] = pop["GISJOIN"]
    for r in crosswalk[crosswalk["year"] == year].itertuples():
        hit = pop["GISJOIN"] == r.csv_gisjoin
        pop.loc[hit, "GISJOIN"] = r.shp_gisjoin
        log.info("  crosswalk: %s -> %s (%d row(s), pop %s) %s", r.csv_gisjoin, r.shp_gisjoin,
                 hit.sum(), f"{pop.loc[hit, 'pop'].sum():,.0f}", r.note)

    bnd = read_boundaries(shapefiles[year])
    nc = is_non_conus(bnd["GISJOIN"], bnd["shp_state"])
    if nc.any():
        dropped.append(drop_rows(bnd[nc], year, "shp", "non_conus"))
        log.info("  shapefile: dropped %d non-CONUS features", nc.sum())
    bnd = bnd[~nc]

    if year in BORROWED_BOUNDARIES:
        gj, name, state, donor_year, prefix = BORROWED_BOUNDARIES[year]
        if bnd["GISJOIN"].str.startswith(prefix).any():
            log.info("  %s already has %s* boundaries — no borrowed unit needed", year, prefix)
        else:
            donor = read_boundaries(shapefiles[donor_year])  # main() adds the donor year
            parts = donor[donor["GISJOIN"].str.startswith(prefix)]
            log.info("  borrowed boundary %s: dissolved %d %d polygons %s", gj, len(parts), donor_year,
                     list(zip(parts["GISJOIN"], parts["shp_name"])))
            bnd = pd.concat([bnd, gpd.GeoDataFrame(
                [{"GISJOIN": gj, "shp_state": state, "shp_name": name, "geometry": dissolve(parts.geometry)}],
                crs=bnd.crs)], ignore_index=True)
            # CSV rows for this area have no boundary of their own: fold them into the new unit
            fold = pop["GISJOIN"].str.startswith(prefix) & (pop["GISJOIN"] != gj)
            if fold.any():
                log.info("  folded %d CSV rows into %s: %s", fold.sum(), gj,
                         list(zip(pop.loc[fold, "GISJOIN"], pop.loc[fold, "name"], pop.loc[fold, "pop"])))
                pop.loc[fold, "GISJOIN"] = gj

    pop["own_row"] = pop["GISJOIN"] == pop["src_gisjoin"]
    pop = pop.sort_values("own_row", ascending=False, kind="stable")  # target's own row names the unit
    merged_n = pop.groupby("GISJOIN").size()
    for gj in merged_n[merged_n > 1].index:
        rows = pop[pop["GISJOIN"] == gj]
        log.info("  summed %d CSV rows into %s: %s", len(rows), gj,
                 list(zip(rows["src_gisjoin"], rows["name"], rows["pop"])))
    by = pop.groupby("GISJOIN")
    agg = by.agg(state=("state", "first"), name=("name", "first"), own_row=("own_row", "any"))
    agg["pop"] = by["pop"].sum(min_count=1)
    agg = agg.reset_index()

    # 5a. pop without boundary -> dropped
    no_bnd = ~agg["GISJOIN"].isin(bnd["GISJOIN"])
    if no_bnd.any():
        dropped.append(drop_rows(agg[no_bnd], year, "csv", "no_boundary"))
        log.info("  %d CSV units have no boundary (pop %s) -> dropped: %s", no_bnd.sum(),
                 f"{agg.loc[no_bnd, 'pop'].sum():,.0f}", list(agg.loc[no_bnd, "name"]))
    pop_no_bnd = agg.loc[no_bnd, "pop"].sum()

    gdf = bnd.merge(agg[~no_bnd], on="GISJOIN", how="left")
    # a crosswalk target with no CSV row of its own takes its name from the shapefile
    use_shp = gdf["own_row"].ne(True) & gdf["shp_name"].notna()
    gdf["name"] = gdf["name"].mask(use_shp, gdf["shp_name"])
    gdf["state"] = gdf["state"].fillna(gdf["shp_state"])
    if year in BORROWED_BOUNDARIES:  # the rebuilt unit is named for the whole area, not a CSV row
        gj, name, state = BORROWED_BOUNDARIES[year][:3]
        gdf.loc[gdf["GISJOIN"] == gj, ["name", "state"]] = [name, state]
    gdf["status"] = "ok"

    # 4. manual fills
    for r in fills[fills["year"] == year].itertuples():
        hit = gdf["GISJOIN"] == r.gisjoin
        if not hit.any():
            sys.exit(f"ERROR: manual fill {year} {r.gisjoin} has no boundary in {shapefiles[year].name}")
        log.info("  manual fill %s (%s): pop %s -> %s [%s]", r.gisjoin, gdf.loc[hit, "name"].iloc[0],
                 gdf.loc[hit, "pop"].iloc[0], r.pop, r.source)
        gdf.loc[hit, "pop"] = float(r.pop)
        gdf.loc[hit, "status"] = "manual_fill"

    # 5b. statuses for kept boundaries
    auto = gdf["status"] == "ok"
    gdf.loc[auto & gdf["pop"].isna(), "status"] = "nodata_unenumerated"
    gdf.loc[auto & gdf["pop"].eq(0), "status"] = "nodata_zero"
    for status in ("nodata_unenumerated", "nodata_zero"):
        s = gdf[gdf["status"] == status]
        if len(s):
            log.info("  %s: %d units %s", status, len(s), list(zip(s["GISJOIN"], s["name"]))[:40])

    gdf["year"] = year
    gdf["pop"] = gdf["pop"].astype("float64")  # NaN = no data; float keeps GPKG writing simple
    gdf["area_km2"] = gdf.geometry.area / 1e6
    gdf = gdf[OUT_COLS].sort_values("GISJOIN").reset_index(drop=True)

    out_path = out_dir / f"counties_{year}.gpkg"
    out_path.unlink(missing_ok=True)
    gdf.to_file(out_path, layer="counties", driver="GPKG", engine="pyogrio", promote_to_multi=True)

    total = gdf["pop"].sum()
    counts = gdf["status"].value_counts()
    qa = {
        "year": year,
        "n_boundaries": len(bnd),
        "n_pop_rows": n_rows_raw,
        "n_pop_rows_conus": n_rows_conus,
        "n_boundary_without_pop": int(gdf["pop"].isna().sum()),
        "n_pop_without_boundary": int(no_bnd.sum()),
        "n_ok": int(counts.get("ok", 0)),
        "n_nodata_unenumerated": int(counts.get("nodata_unenumerated", 0)),
        "n_nodata_zero": int(counts.get("nodata_zero", 0)),
        "n_manual_fill": int(counts.get("manual_fill", 0)),
        "conus_pop_total": total,
        "pop_dropped_no_boundary": pop_no_bnd,
        "pop_dropped_pct": 100 * pop_no_bnd / (total + pop_no_bnd) if total + pop_no_bnd else 0.0,
        "pop_dropped_multi_county_group": pop_group,
        "expected_total": EXPECTED_TOTALS.get(year),
    }
    msg = (f"  wrote {out_path} ({len(gdf)} units, {out_path.stat().st_size / 1e6:.1f} MB) | "
           f"CONUS pop {total:,.0f} | dropped no-boundary {pop_no_bnd:,.0f} ({qa['pop_dropped_pct']:.3f}%)")
    if year in EXPECTED_TOTALS:
        exp = EXPECTED_TOTALS[year]
        msg += f" | expected ~{exp:,} (diff {total - exp:+,.0f}, {100 * (total - exp) / exp:+.3f}%)"
    log.info(msg)
    return qa, dropped


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    pop_all = read_population(args.pop_csv)
    crosswalk = read_config(args.crosswalk, ["year", "csv_gisjoin", "shp_gisjoin", "note"])
    fills = read_config(args.manual_fills, ["year", "gisjoin", "pop", "source"])
    shapefiles = find_shapefiles(args.shape_dir, sorted(set(args.years)))
    for year, path in shapefiles.items():
        log.info("shapefile %d: %s", year, path)
    for year in set(BORROWED_BOUNDARIES) & set(shapefiles):
        donor_year = BORROWED_BOUNDARIES[year][3]
        shapefiles.setdefault(donor_year, find_shapefiles(args.shape_dir, [donor_year])[donor_year])
    validate_crosswalk(crosswalk, pop_all, shapefiles)

    qa_rows, dropped = [], []
    for year in sorted(set(args.years)):
        qa, d = process_year(year, pop_all, shapefiles, crosswalk, fills, args.out_dir)
        qa_rows.append(qa)
        dropped.extend(d)

    qa_df = pd.DataFrame(qa_rows)
    qa_df.to_csv(args.out_dir / "qa_report.csv", index=False)
    drop_df = pd.concat(dropped, ignore_index=True) if dropped else pd.DataFrame(columns=DROP_COLS)
    drop_df.to_csv(args.out_dir / "dropped_rows.csv", index=False)
    log.info("QA report:\n%s", qa_df.to_string(index=False))
    log.info("dropped rows by reason:\n%s", drop_df.groupby(["reason", "source"]).size().to_string())
    log.info("wrote %s and %s", args.out_dir / "qa_report.csv", args.out_dir / "dropped_rows.csv")
    log.info("DONE")


if __name__ == "__main__":
    main()
