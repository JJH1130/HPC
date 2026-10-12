"""Prepare NHGIS census tract population + boundaries (CONUS, 1910-2020) for validating the
dasymetric outputs (Ch1). Same pattern as prepare_census.py; county outputs are only read.

Inputs (extract nhgis0002):
  1910-1960  source tables  {csv-dir}/*_ds{NN}_{YEAR}_tract.csv (+ _codebook.txt). The
             population column of each table is taken from the codebook (one variable, or
             the one labelled "Total") unless configs/nhgis_tract_tables.csv says otherwise.
  1970-2020  time series    --ts-csv (AV0 Total Population, AV0AA, nominal, time varies by row)
  boundaries               {shape-dir}/*_us_tract_{YEAR}.zip (read from the zip)

Rules per year:
  1. Stack every population table -> (GISJOIN, pop, dataset, table); empty pops dropped.
  2. Same GISJOIN in several tables: equal values -> keep one. Different values: if
     (max - min) / max <= 5 % -> status "ok", pop from the highest-priority table
     ("conflict_resolved" in issues.csv); else status "conflict", pop empty. Priority per
     year = order of rows in the table config, then dataset number.
  3. CONUS only: state code 02, 15, 72 dropped (table and polygon side).
  4. Join to the year's polygons (ESRI:102039) on GISJOIN; polygon without pop -> status
     "no_pop"; pop without polygon -> issues.csv ("pop_only").
  5. county_gisjoin = GISJOIN[:8], checked against counties_{YEAR}.gpkg (code exists, and the
     tract's representative point lies in that county); area_km2.

Outputs: tracts_{YEAR}.gpkg (layer "tracts") in --out-dir; table_inventory.csv, issues.csv,
qa_by_year[_MA].csv, coverage_by_county[_MA].csv in --results-dir.
Rules and QA: docs/tract_preprocessing.md. Paths come from CLI flags (sbatch/tract_prepare.sh).
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

from prepare_census import TARGET_CRS, dissolve, gpkg_leftovers, local_tmp_dir, write_gpkg

YEARS = list(range(1910, 2021, 10))
TS_FIRST_YEAR = 1970
TS_TABLE, TS_COL = "AV0", "AV0AA"
NON_CONUS_STATES = ("02", "15", "72")  # Alaska, Hawaii, Puerto Rico (state code = GISJOIN[1:3])
MA_PREFIX = "G250"
OUT_COLS = ["GISJOIN", "county_gisjoin", "pop", "status", "source_tables", "area_km2", "geometry"]
ISSUE_COLS = ["year", "GISJOIN", "issue", "pop", "source_tables", "detail"]
INV_COLS = ["year", "dataset", "file", "table", "nhgis_code", "title", "universe", "n_vars",
            "variables", "pop_columns", "rule", "priority"]
RESOLVE_TOL = 0.05  # max relative difference between tables still taken as one value

TABLE_RE = re.compile(r"^\s*Table\s+\d+:\s+(?P<v>.+?)\s*$")
UNIV_RE = re.compile(r"^\s*Universe:\s+(?P<v>.+?)\s*$")
SRC_RE = re.compile(r"^\s*Source code:\s+(?P<v>\S+)")
NHGIS_RE = re.compile(r"^\s*NHGIS code:\s+(?P<v>\S+)")
VAR_RE = re.compile(r"^\s+(?P<var>[A-Z0-9]+\d{3}):\s+(?P<label>.+?)\s*$")

log = logging.getLogger("prepare_tracts")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv-dir", type=Path, required=True, help="folder with *_ds{NN}_{YEAR}_tract.csv + codebooks")
    p.add_argument("--ts-csv", type=Path, required=True, help="NHGIS tract time series CSV (AV0, nominal)")
    p.add_argument("--shape-dir", type=Path, required=True, help="folder with *_us_tract_{YEAR}.zip")
    p.add_argument("--census-dir", type=Path, required=True, help="folder with counties_{YEAR}.gpkg (read only)")
    p.add_argument("--table-config", type=Path, required=True, help="dataset,table,pop_columns,note")
    p.add_argument("--out-dir", type=Path, required=True, help="where tracts_{YEAR}.gpkg go")
    p.add_argument("--results-dir", type=Path, required=True, help="small CSVs tracked in git")
    p.add_argument("--years", type=int, nargs="+", default=YEARS, help="subset of years (default: all 12)")
    return p.parse_args(argv)


# ---------------------------------------------------------------- inputs

def read_nhgis_csv(path: Path, needed) -> pd.DataFrame:
    try:
        raw = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False, na_values=[""])
    except UnicodeDecodeError:
        raw = pd.read_csv(path, dtype=str, encoding="latin-1", keep_default_na=False, na_values=[""])
    missing = set(needed) - set(raw.columns)
    if missing:
        sys.exit(f"ERROR: {path} is missing columns {sorted(missing)}; found {list(raw.columns)}")
    raw["GISJOIN"] = raw["GISJOIN"].fillna("").str.strip()
    bad = raw["GISJOIN"].str.contains(" ") | raw["GISJOIN"].eq("")  # optional descriptive header row
    if bad.any():
        log.info("  %s: dropped %d rows without a GISJOIN (descriptive header?)", path.name, bad.sum())
        raw = raw[~bad]
    return raw


def parse_codebook(path: Path) -> list[dict]:
    """Tables in the codebook's Data Dictionary: title, universe, source code, NHGIS code, variables."""
    tables, cur, in_dict = [], None, False
    for line in path.read_text(encoding="latin-1").splitlines():
        if line.strip() == "Data Dictionary":
            in_dict = True
            continue
        if not in_dict:
            continue
        if line.strip().startswith("Citation and Use"):
            break
        m = TABLE_RE.match(line)
        if m:
            cur = {"title": m["v"], "universe": "", "table": "", "nhgis_code": "", "variables": []}
            tables.append(cur)
            continue
        if cur is None:
            continue
        for key, rx in (("universe", UNIV_RE), ("table", SRC_RE), ("nhgis_code", NHGIS_RE)):
            m = rx.match(line)
            if m:
                cur[key] = m["v"]
                break
        else:
            m = VAR_RE.match(line)
            if m:
                cur["variables"].append((m["var"], m["label"]))
    for t in tables:
        t["table"] = t["table"] or t["nhgis_code"]
    return tables


def read_table_config(path: Path) -> dict[tuple[str, str], str]:
    """(dataset, table) -> pop_columns ("" = automatic choice), in file order (= priority)."""
    df = pd.read_csv(path, dtype=str, comment="#").fillna("").apply(lambda s: s.str.strip())
    missing = {"dataset", "table", "pop_columns", "note"} - set(df.columns)
    if missing:
        sys.exit(f"ERROR: {path} is missing columns {sorted(missing)}")
    return {(r.dataset, r.table): r.pop_columns for r in df.itertuples()}


def choose_columns(dataset, table, variables, header, config) -> tuple[list[str], str]:
    if config.get((dataset, table)):
        cols, rule = config[(dataset, table)].split(), "config"
    elif len(variables) == 1:
        cols, rule = [variables[0][0]], "single_variable"
    else:
        totals = [v for v, label in variables if label.strip().lower() == "total"]
        cols, rule = (totals, "total_label") if len(totals) == 1 else ([], "UNRESOLVED")
    if cols and any(c not in header for c in cols):
        rule = "MISSING_COLUMN"
    return cols, rule


def build_inventory(csv_dir: Path, config, results_dir: Path) -> pd.DataFrame:
    """One row per 1910-1960 table (all source years, so problems show before the long loop).
    Written before checking, so a stopped job still leaves the inventory to read."""
    rows, problems = [], []
    for year in [y for y in YEARS if y < TS_FIRST_YEAR]:
        files = sorted(csv_dir.glob(f"*_ds*_{year}_tract.csv"))
        if not files:
            problems.append(f"  {year}: no *_ds*_{year}_tract.csv in {csv_dir}")
        for f in files:
            dataset = re.search(r"_(ds\d+)_", f.name)[1]
            cb = f.with_name(f.stem + "_codebook.txt")
            if not cb.exists():
                problems.append(f"  {f.name}: codebook {cb.name} not found")
                continue
            header = set(pd.read_csv(f, nrows=0, encoding="utf-8-sig").columns)
            tables = parse_codebook(cb)
            if not tables:
                problems.append(f"  {cb.name}: no tables found in the Data Dictionary")
            for t in tables:
                cols, rule = choose_columns(dataset, t["table"], t["variables"], header, config)
                rows.append({
                    "year": year, "dataset": dataset, "file": f.name, "table": t["table"],
                    "nhgis_code": t["nhgis_code"], "title": t["title"], "universe": t["universe"],
                    "n_vars": len(t["variables"]),
                    "variables": "; ".join(f"{v}={label}" for v, label in t["variables"]),
                    "pop_columns": " ".join(cols), "rule": rule,
                })
    inv = pd.DataFrame(rows, columns=INV_COLS)
    # priority within a year (1 = preferred): config row order, then dataset number, then codebook order
    cfg_order = {key: i for i, key in enumerate(config)}
    keys = pd.DataFrame({
        "year": inv["year"],
        "cfg": [cfg_order.get(k, len(cfg_order)) for k in zip(inv["dataset"], inv["table"])],
        "ds": inv["dataset"].str[2:].astype(int),
        "pos": range(len(inv)),
    })
    inv["priority"] = keys.sort_values(["year", "cfg", "ds", "pos"]).groupby("year").cumcount() + 1
    inv.to_csv(results_dir / "table_inventory.csv", index=False)
    log.info("table inventory (%d tables):\n%s", len(inv),
             inv[["year", "dataset", "table", "title", "n_vars", "pop_columns", "rule", "priority"]]
             .to_string(index=False))
    used = set(zip(inv["dataset"], inv["table"]))
    for key in set(config) - used:
        log.warning("config row %s matches no table", key)
    bad = inv[inv["rule"].isin(["UNRESOLVED", "MISSING_COLUMN"])]
    problems += [f"  {r.year} {r.dataset} {r.table} ({r.title}): {r.rule}; variables: {r.variables}"
                 for r in bad.itertuples()]
    if problems:
        sys.exit("ERROR: fix these (add rows to the table config; see results/tract/table_inventory.csv):\n"
                 + "\n".join(problems))
    return inv


def read_ts(path: Path) -> pd.DataFrame:
    raw = read_nhgis_csv(path, ["GISJOIN", "YEAR", TS_COL])
    ts = pd.DataFrame({
        "GISJOIN": raw["GISJOIN"],
        "year": pd.to_numeric(raw["YEAR"], errors="coerce"),
        "pop": pd.to_numeric(raw[TS_COL], errors="coerce"),
        "dataset": "ts", "table": TS_TABLE,
    })
    log.info("time series: %d rows, years %s", len(ts), sorted(ts["year"].dropna().astype(int).unique().tolist()))
    return ts


def find_shape_zip(shape_dir: Path, year: int) -> tuple[Path, str]:
    hits = sorted(shape_dir.glob(f"*_us_tract_{year}.zip"))
    if len(hits) != 1:
        sys.exit(f"ERROR: need exactly one *_us_tract_{year}.zip under {shape_dir}; found {[h.name for h in hits]}")
    with zipfile.ZipFile(hits[0]) as zf:
        shps = [n for n in zf.namelist() if n.lower().endswith(".shp")]
    if len(shps) != 1:
        sys.exit(f"ERROR: {hits[0].name} must hold exactly one .shp; found {shps}")
    return hits[0], shps[0]


def read_tracts(zip_path: Path, inner: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(f"/vsizip/{zip_path}/{inner}", engine="pyogrio")
    if "GISJOIN" not in gdf.columns:
        sys.exit(f"ERROR: {zip_path.name}/{inner} has no GISJOIN column; found {list(gdf.columns)}")
    if gdf.crs is None:
        sys.exit(f"ERROR: {zip_path.name}/{inner} has no CRS (.prj missing?)")
    log.info("  boundaries: %s/%s (%d features, source CRS %s)", zip_path.name, inner, len(gdf), gdf.crs.name)
    out = gpd.GeoDataFrame({"GISJOIN": gdf["GISJOIN"].astype(str).str.strip()},
                           geometry=gdf.geometry.values, crs=gdf.crs).to_crs(TARGET_CRS)
    dup = out["GISJOIN"].duplicated(keep=False)
    if dup.any():
        log.info("  %d features share %d GISJOINs -> dissolving by GISJOIN", dup.sum(), out.loc[dup, "GISJOIN"].nunique())
        merged = [{"GISJOIN": g, "geometry": dissolve(part.geometry)} for g, part in out[dup].groupby("GISJOIN")]
        out = pd.concat([out[~dup], gpd.GeoDataFrame(merged, crs=out.crs)], ignore_index=True)
    return out


def is_non_conus(gisjoin: pd.Series) -> pd.Series:
    return gisjoin.str[1:3].isin(NON_CONUS_STATES)


# ---------------------------------------------------------------- one year

def stack_year(year, inv, csv_dir, ts) -> pd.DataFrame:
    """Rule 1: all population tables of the year -> GISJOIN, pop, dataset, table."""
    if year >= TS_FIRST_YEAR:
        return ts.loc[ts["year"] == year, ["GISJOIN", "pop", "dataset", "table"]].assign(priority=1)
    parts = []
    for fname, g in inv[inv["year"] == year].groupby("file"):
        cols = sorted({c for pc in g["pop_columns"] for c in pc.split()})
        raw = read_nhgis_csv(csv_dir / fname, ["GISJOIN", *cols])
        for r in g.itertuples():
            vals = raw[r.pop_columns.split()].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)
            parts.append(pd.DataFrame({"GISJOIN": raw["GISJOIN"].values, "pop": vals.values,
                                       "dataset": r.dataset, "table": r.table, "priority": r.priority}))
            log.info("  %s %s %s (%s): %d rows, %d with pop, total %s", fname, r.dataset, r.table,
                     r.pop_columns, len(raw), vals.notna().sum(), f"{vals.sum():,.0f}")
    return pd.concat(parts, ignore_index=True)


def combine(year, stack) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rule 2: one row per GISJOIN. Values that differ by <= RESOLVE_TOL take the
    highest-priority table's value; larger differences -> conflict, pop empty."""
    empty = stack["pop"].isna()
    if empty.any():
        log.info("  dropped %d table rows with an empty pop", empty.sum())
    stack = stack[~empty].sort_values("priority", kind="stable")
    stack["src"] = stack["table"].where(stack["dataset"] == "ts", stack["dataset"] + ":" + stack["table"])
    by = stack.groupby("GISJOIN")
    agg = by.agg(n=("pop", "size"), pop_min=("pop", "min"), pop_max=("pop", "max"), pop_first=("pop", "first"),
                 source_tables=("src", lambda s: ";".join(sorted(set(s))))).reset_index()
    differ = agg["pop_min"] != agg["pop_max"]
    rel = (agg["pop_max"] - agg["pop_min"]) / agg["pop_max"]  # pops >= 0, so max > 0 when they differ
    agg["resolved"] = differ & (rel <= RESOLVE_TOL)
    conflict = differ & ~agg["resolved"]
    agg["status"] = "ok"
    agg.loc[conflict, "status"] = "conflict"
    agg["pop"] = agg["pop_first"].where(~conflict)
    log.info("  %d table rows -> %d GISJOINs; %d in several tables with equal values (kept one); "
             "%d differ by <= %.0f%% (highest-priority value kept); %d conflicts (pop empty)",
             len(stack), len(agg), int(((agg["n"] > 1) & ~differ).sum()), int(agg["resolved"].sum()),
             100 * RESOLVE_TOL, int(conflict.sum()))
    rows = stack[stack["GISJOIN"].isin(agg.loc[differ, "GISJOIN"])]
    detail = {g: "; ".join(f"{s}={p:,.0f}" for s, p in zip(part["src"], part["pop"]))
              for g, part in rows.groupby("GISJOIN")}
    d = agg[differ]
    issues = pd.DataFrame({"year": year, "GISJOIN": d["GISJOIN"].values,
                           "issue": d["status"].map({"ok": "conflict_resolved", "conflict": "conflict"}).values,
                           "pop": d["pop"].values, "source_tables": d["source_tables"].values,
                           "detail": [f"{detail[g]} (max diff {r:.1%})" for g, r in zip(d["GISJOIN"], rel[differ])]})
    for r in issues.head(20).itertuples():
        log.info("    %s %s: pop %s | %s", r.issue, r.GISJOIN, r.pop, r.detail)
    return agg[["GISJOIN", "pop", "status", "source_tables", "resolved"]], issues


def check_counties(year, tracts, counties) -> pd.DataFrame:
    """Rule 5 checks: county code exists that year; tract point lies in that county."""
    not_found = ~tracts["county_gisjoin"].isin(counties["GISJOIN"])
    pts = gpd.GeoDataFrame({"GISJOIN": tracts["GISJOIN"].values, "county_gisjoin": tracts["county_gisjoin"].values},
                           geometry=tracts.geometry.representative_point().values, crs=tracts.crs)
    hit = gpd.sjoin(pts, counties[["GISJOIN", "geometry"]].rename(columns={"GISJOIN": "pt_county"}).to_crs(tracts.crs),
                    how="left", predicate="within")
    hit = hit[~hit.index.duplicated()].reindex(pts.index)  # a point on a shared edge can fall in two counties
    mismatch = ~not_found.values & hit["pt_county"].ne(hit["county_gisjoin"]).values
    issues = pd.concat([
        pd.DataFrame({"year": year, "GISJOIN": tracts.loc[not_found, "GISJOIN"].values, "issue": "county_not_found",
                      "detail": ("no county " + tracts.loc[not_found, "county_gisjoin"]
                                 + f" in counties_{year}.gpkg").values}),
        pd.DataFrame({"year": year, "GISJOIN": hit.loc[mismatch, "GISJOIN"].values, "issue": "county_mismatch",
                      "detail": ("point in " + hit.loc[mismatch, "pt_county"].fillna("no county")).values}),
    ], ignore_index=True)
    issues = issues.merge(tracts[["GISJOIN", "pop", "source_tables"]], on="GISJOIN", how="left")
    log.info("  county check: %d codes not in counties_%d.gpkg, %d tract points in another county or none",
             not_found.sum(), year, mismatch.sum())
    for r in issues.head(20).itertuples():
        log.info("    %s %s: %s", r.issue, r.GISJOIN, r.detail)
    return issues


def summarize(year, n_tables, agg, tracts, issues) -> dict:
    count = lambda kind: int((issues["issue"] == kind).sum())
    pop_only = issues[issues["issue"] == "pop_only"]
    return {
        "year": year, "n_tables": n_tables, "n_tracts": len(tracts),
        "n_with_pop": int(tracts["pop"].notna().sum()), "total_pop": float(tracts["pop"].sum()),
        "n_conflict": int((agg["status"] == "conflict").sum()), "n_conflict_resolved": int(agg["resolved"].sum()),
        "n_unmatched_pop": len(pop_only), "pop_unmatched": float(pop_only["pop"].sum()),
        "n_unmatched_poly": count("no_pop"),
        "n_county_not_found": count("county_not_found"), "n_county_mismatch": count("county_mismatch"),
    }


def coverage(year, tracts, counties) -> pd.DataFrame:
    cov = tracts.groupby("county_gisjoin").agg(
        n_tracts=("GISJOIN", "size"), n_tracts_pop=("pop", "count"),
        n_conflict=("status", lambda s: int((s == "conflict").sum())), tract_pop=("pop", "sum")).reset_index()
    cov = cov.merge(counties[["GISJOIN", "state", "name", "pop"]]
                    .rename(columns={"GISJOIN": "county_gisjoin", "pop": "county_pop"}), on="county_gisjoin", how="left")
    cov["coverage"] = cov["tract_pop"] / cov["county_pop"]
    cov.insert(0, "year", year)
    return cov[["year", "county_gisjoin", "state", "name", "county_pop", "tract_pop", "coverage",
                "n_tracts", "n_tracts_pop", "n_conflict"]]


def process_year(year, inv, ts, args, tmp_dir):
    log.info("===== %d =====", year)
    stack = stack_year(year, inv, args.csv_dir, ts)
    n_tables = stack.groupby(["dataset", "table"]).ngroups
    agg, issues_conflict = combine(year, stack)

    # 3. CONUS only
    nc = is_non_conus(agg["GISJOIN"])
    if nc.any():
        log.info("  tables: dropped %d non-CONUS tracts (pop %s)", nc.sum(), f"{agg.loc[nc, 'pop'].sum():,.0f}")
    agg = agg[~nc]
    issues_conflict = issues_conflict[issues_conflict["GISJOIN"].isin(agg["GISJOIN"])]

    zip_path, inner = find_shape_zip(args.shape_dir, year)
    tracts = read_tracts(zip_path, inner)
    nc = is_non_conus(tracts["GISJOIN"])
    if nc.any():
        log.info("  boundaries: dropped %d non-CONUS features", nc.sum())
    tracts = tracts[~nc]

    # 4. join
    tracts = tracts.merge(agg, on="GISJOIN", how="left")
    tracts["status"] = tracts["status"].fillna("no_pop")
    tracts["source_tables"] = tracts["source_tables"].fillna("")
    pop_only = agg[~agg["GISJOIN"].isin(tracts["GISJOIN"])]
    no_pop = tracts[tracts["status"] == "no_pop"]
    log.info("  join: %d polygons, %d with pop; %d table tracts without polygon (pop %s); %d polygons without pop",
             len(tracts), tracts["pop"].notna().sum(), len(pop_only), f"{pop_only['pop'].sum():,.0f}", len(no_pop))
    issues = [issues_conflict,
              pd.DataFrame({"year": year, "GISJOIN": pop_only["GISJOIN"].values, "issue": "pop_only",
                            "pop": pop_only["pop"].values, "source_tables": pop_only["source_tables"].values,
                            "detail": pop_only["status"].values}),
              pd.DataFrame({"year": year, "GISJOIN": no_pop["GISJOIN"].values, "issue": "no_pop",
                            "pop": float("nan"), "source_tables": "", "detail": ""})]

    # 5. county + area
    tracts["county_gisjoin"] = tracts["GISJOIN"].str[:8]
    counties = gpd.read_file(args.census_dir / f"counties_{year}.gpkg", engine="pyogrio",
                             columns=["GISJOIN", "state", "name", "pop"])
    issues.append(check_counties(year, tracts, counties))
    tracts["pop"] = tracts["pop"].astype("float64")
    tracts["area_km2"] = tracts.geometry.area / 1e6
    tracts = tracts[OUT_COLS].sort_values("GISJOIN").reset_index(drop=True)

    out_path = args.out_dir / f"tracts_{year}.gpkg"
    write_gpkg(tracts, out_path, tmp_dir, layer="tracts")
    log.info("  wrote %s (%d tracts, %.1f MB) | tract pop %s", out_path, len(tracts),
             out_path.stat().st_size / 1e6, f"{tracts['pop'].sum():,.0f}")

    issues = pd.concat(issues, ignore_index=True)[ISSUE_COLS]
    cov = coverage(year, tracts, counties)
    ma = lambda df, col="GISJOIN": df[df[col].str.startswith(MA_PREFIX)]
    qa = summarize(year, n_tables, agg, tracts, issues)
    qa_ma = summarize(year, n_tables, ma(agg), ma(tracts), ma(issues))
    log.info("  QA: %s", qa)
    log.info("  QA Massachusetts: %s", qa_ma)
    return qa, qa_ma, cov, issues


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    bad_years = sorted(set(args.years) - set(YEARS))
    if bad_years:
        sys.exit(f"ERROR: years must be in {YEARS}; got {bad_years}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.results_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = local_tmp_dir()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    log.info("GPKGs are written in %s, then copied to %s", tmp_dir, args.out_dir)
    stale = [f for y in set(args.years) for f in gpkg_leftovers(args.out_dir / f"tracts_{y}.gpkg") if f.exists()]
    for f in stale:
        f.unlink()
    if stale:
        log.info("removed %d files from an earlier run: %s", len(stale), sorted(f.name for f in stale))

    inv = build_inventory(args.csv_dir, read_table_config(args.table_config), args.results_dir)
    for year in sorted(set(args.years)):  # fail before the long loop
        find_shape_zip(args.shape_dir, year)
        if not (args.census_dir / f"counties_{year}.gpkg").exists():
            sys.exit(f"ERROR: {args.census_dir / f'counties_{year}.gpkg'} not found (run census_prepare first)")
    ts = read_ts(args.ts_csv) if max(args.years) >= TS_FIRST_YEAR else None

    qa_rows, qa_ma_rows, covs, issues = [], [], [], []
    for year in sorted(set(args.years)):
        qa, qa_ma, cov, iss = process_year(year, inv, ts, args, tmp_dir)
        qa_rows.append(qa)
        qa_ma_rows.append(qa_ma)
        covs.append(cov)
        issues.append(iss)

    res = args.results_dir
    qa_df = pd.DataFrame(qa_rows)
    qa_df.to_csv(res / "qa_by_year.csv", index=False)
    pd.DataFrame(qa_ma_rows).to_csv(res / "qa_by_year_MA.csv", index=False)
    cov_df = pd.concat(covs, ignore_index=True)
    cov_df.to_csv(res / "coverage_by_county.csv", index=False)
    cov_df[cov_df["county_gisjoin"].str.startswith(MA_PREFIX)].to_csv(res / "coverage_by_county_MA.csv", index=False)
    iss_df = pd.concat(issues, ignore_index=True)
    iss_df.to_csv(res / "issues.csv", index=False)
    log.info("QA by year:\n%s", qa_df.to_string(index=False))
    log.info("issues by year and kind:\n%s", iss_df.groupby(["year", "issue"]).size().to_string())
    log.info("counties with coverage > 1.001: %d", int((cov_df["coverage"] > 1.001).sum()))
    log.info("wrote results to %s", res)
    log.info("DONE")


if __name__ == "__main__":
    main()
