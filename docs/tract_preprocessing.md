# NHGIS Tract Preprocessing (Chapter 1 validation)

Rules for turning NHGIS census tract population and boundary files (extract nhgis0002,
1910–2020) into one tract layer per decade, used to validate the dasymetric outputs at a
finer scale than counties. Same pattern as the county step (`docs/census_preprocessing.md`);
the county outputs are only read, never changed.

Code: `src/census/prepare_tracts.py`; job: `sbatch/tract_prepare.sh`; steps:
`docs/runbooks/Preparing_Tracts.md`. Source: `docs/data_sources.md` (NHGIS, extract nhgis0002).

Last updated: 2026-10-13

## Inputs

All under `/projects/jaju1407/data/raw/nhgis/`.

| Item | Path | Notes |
|---|---|---|
| Source tables, 1910–1960 | `nhgis0002_csv/nhgis0002_ds{NN}_{YEAR}_tract.csv` + `..._codebook.txt` | 24 datasets (ds39–ds92). Coverage in 1910–1950 is city-specific. 1910: ds39 NT1 + ds40 NT22, NT49; 1960 ds92 has NTSUP2, NBT1, NBT4 (27 tables in all, job 33886550) |
| Time series, 1970–2020 | `nhgis0002_csv/nhgis0002_ts_nominal_tract.csv` | AV0 Total Population (`AV0AA`), nominal, time varies by row |
| Boundaries | `nhgis0002_shape/nhgis0002_shapefile_tl{2008,2010,2020}_us_tract_{YEAR}.zip` | 1910–2000 on 2008 TIGER/Line+, 2010 on 2010, 2020 on 2020. Read straight from the zip |
| Counties (read only) | `/projects/jaju1407/data/processed/census/counties_{YEAR}.gpkg` | Output of the county step |
| Table choices | `configs/nhgis_tract_tables.csv` | `dataset,table,pop_columns,note`; only needed when the automatic choice fails or is wrong |

### Which column is the population

The program reads each source dataset's codebook (Data Dictionary section) and lists every
table with its variables in `results/tract/table_inventory.csv`. Per table, the population
column is chosen in this order:

1. `configs/nhgis_tract_tables.csv` row for (`dataset`, `table`) → those columns
   (space-separated; several are summed).
2. The table has exactly one variable → that variable (`rule = single_variable`).
3. Exactly one variable labelled "Total" → that variable (`rule = total_label`).
4. Otherwise `rule = UNRESOLVED`: the job writes the inventory and stops. Add a config row.

A chosen column that is missing from the CSV header also stops the job (`MISSING_COLUMN`).
1970–2020 always use `AV0AA` (table `AV0`).

## Rules per year

1. **Stack** every population table of the year into rows (GISJOIN, pop, dataset, table).
   Rows with an empty pop are dropped (logged).
2. **Duplicates across tables:** the same GISJOIN in several tables with equal values →
   one row kept. Different values → `status = conflict`, `pop` left empty; no value is
   chosen. All values are listed in `issues.csv`.
3. **CONUS only:** drop GISJOINs whose state code (characters 2–3) is 02, 15 or 72
   (Alaska, Hawaii, Puerto Rico; also catches territorial codes such as G025/G155), on
   both the table side and the polygon side.
4. **Join** to that year's tract polygons on GISJOIN. Reprojected to ESRI:102039 (HISDAC's
   CRS). Polygons sharing a GISJOIN are dissolved (logged).
   - polygon without pop → kept, `status = no_pop`
   - pop without polygon → not in the GeoPackage; listed in `issues.csv` (`pop_only`)
5. **County and area:** `county_gisjoin` = first 8 characters of the tract GISJOIN
   (`G` + state + `0` + county + `0`, the NHGIS county code). Checked against
   `counties_{YEAR}.gpkg` two ways, both logged and listed in `issues.csv`:
   - `county_not_found`: no county with that code in that year
   - `county_mismatch`: the tract's representative point falls in another county or in
     none (e.g. a water tract outside the county polygons)
   `area_km2` is computed in ESRI:102039.

### `status` values

| Value | Meaning | `pop` |
|---|---|---|
| `ok` | One value (or several equal values) and a polygon | value |
| `conflict` | Tables disagree for this tract | empty |
| `no_pop` | Polygon without any table value | empty |

`pop = 0` stays `ok` (tracts of parks, water, institutions are real zeros).

## Outputs

| File | Content |
|---|---|
| `/projects/jaju1407/data/processed/tract/tracts_{YEAR}.gpkg` | layer `tracts`: `GISJOIN, county_gisjoin, pop, status, source_tables, area_km2, geometry`. `source_tables` = e.g. `ds40:NT22;ds40:NT49` or `AV0`. Written to node-local disk first, then copied (SQLite locking on /projects, as for counties) |
| `results/tract/qa_by_year.csv` (+ `_MA`) | per year: `n_tables, n_tracts, n_with_pop, total_pop, n_conflict, n_unmatched_pop, pop_unmatched, n_unmatched_poly, n_county_not_found, n_county_mismatch` |
| `results/tract/coverage_by_county.csv` (+ `_MA`) | per county-year with at least one tract: `county_pop`, `tract_pop` (sum of tract pops with a polygon; conflicts excluded), `coverage = tract_pop / county_pop`, `n_tracts`, `n_tracts_pop`, `n_conflict` |
| `results/tract/table_inventory.csv` | every 1910–1960 table: title, universe, variables, chosen column(s), rule |
| `results/tract/issues.csv` | `year, GISJOIN, issue, pop, source_tables, detail`; issue = `conflict`, `pop_only`, `no_pop`, `county_not_found`, `county_mismatch` |

`_MA` files keep only Massachusetts (GISJOIN prefix `G250`). `total_pop` counts tracts with
a polygon; `pop_unmatched` is the pop of `pop_only` rows.

## QA to read after the run

- `table_inventory.csv`: every table's chosen column is a total population.
- `qa_by_year.csv`: `n_conflict`, `n_unmatched_pop`, `n_county_*` near 0; from 1990 on,
  `total_pop` close to the county CONUS total (tracts cover the whole country from 1990).
- `coverage_by_county.csv`: early years cover only tracted cities, so coverage < 1 is
  expected; coverage > 1 means a table or join problem.

## Notes

- 1910–1930 tract data were keyed from printed reports by Andrew Beveridge's team (Queens
  College, CUNY); 1960 NBT tables also come from printed reports.
- Boundaries are nominal (each year's own tracts). No harmonization across years.

## Open items

- [x] Table inventory (job 33886550): 26 of 27 tables have one variable. 1920 ds48 NT1
  ("Population, 1910 and 1920") has BBQ001 = 1910 and BBQ002 = 1920 → config row uses BBQ002.
- [ ] Quick test (1910, 1960, 1970); review conflicts and coverage.
