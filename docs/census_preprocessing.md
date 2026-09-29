# NHGIS County Census Preprocessing (Chapter 1)

Rules for turning raw NHGIS county population and boundary files (1810–2020) into
clean, analysis-ready county units for dasymetric mapping.

Last updated: 2026-09-30

## Inputs

| Item | Path | Notes |
|---|---|---|
| County population | `/projects/jaju1407/data/raw/nhgis/nhgis0001_ts_nominal_county.csv` | NHGIS time series A00 (Total Population), nominal integration, time varies by row. Key columns: `GISJOIN`, `YEAR`, `STATE`, `COUNTY`, `NAME`, `A00AA` (total population) |
| County boundaries | `/projects/jaju1407/data/raw/nhgis/nhgis0001_shape/**/US_county_{YEAR}*.shp` | 22 decennial years, 1810–2020. Basis: 2008 TIGER/Line+ for 1810–2000, 2010 TIGER/Line+ for 2010, 2020 TIGER/Line+ for 2020 |

"Nominal" means each year uses the counties as they existed in that year. Boundaries
are not harmonized across years; each year is joined to its own boundary file.

## Outputs

Written to `/projects/jaju1407/data/processed/census/`.

| File | Content |
|---|---|
| `counties_{YEAR}.gpkg` | One layer per year. CRS **ESRI:102039** (same as HISDAC-US). Columns: `GISJOIN`, `year`, `state`, `name`, `pop`, `status`, `area_km2`, `geometry` |
| `qa_report.csv` | Per year: number of polygons, population rows, unmatched units, CONUS population total, population dropped (count and %) |
| `dropped_rows.csv` | Every population row or polygon removed, with year, GISJOIN, name, population and reason |

### `status` values

| Value | Meaning | Used for training? | Used for reallocation? |
|---|---|---|---|
| `ok` | Polygon and population matched | Yes | Yes |
| `manual_fill` | Population or polygon filled from an external source (see `configs/nhgis_manual_fills.csv`) | Yes | Yes |
| `nodata_unenumerated` | Polygon exists but the census did not enumerate it (e.g., Indian lands, unorganized territory) | No | No, output cells are NoData |
| `nodata_zero` | Population recorded as 0 (e.g., legally created but unorganized counties whose residents were counted in another county) | No | No, output cells are NoData |

NoData is kept distinct from zero population. Cells in `nodata_*` units mean "not
enumerated", not "no people".

## Processing rules (applied in order)

1. **Keep CONUS only.** Drop Alaska, Hawaii and Puerto Rico (and their territorial
   predecessors). HISDAC-US covers the conterminous U.S. only.
2. **Drop multi-county group rows.** Rows whose `COUNTY` or `NAME` contains
   "multi-county group" are aggregates that duplicate county rows. Before dropping,
   check that they equal the sum of the matching county rows and log the result.
3. **Apply the manual crosswalk** (`configs/nhgis_crosswalk.csv`: `year`,
   `csv_gisjoin`, `shp_gisjoin`, `note`). Reassigns population rows whose code does
   not match any polygon. When several rows map to one polygon, populations are summed.
4. **Apply manual population fills** (`configs/nhgis_manual_fills.csv`: `year`,
   `gisjoin`, `pop`, `source`). Sets `status = manual_fill`.
5. **Reconstruct missing polygons** where both polygon and population are missing
   for a unit that existed (currently only D.C. 1820; see below).
6. **Polygons without population** → `status = nodata_unenumerated`. Keep the polygon.
7. **Population equal to 0** → `status = nodata_zero`.
8. **Population rows without a polygon** (after steps 3–5) → drop and log in
   `dropped_rows.csv`.
9. **Reproject** all polygons to ESRI:102039 and compute `area_km2`.
10. **QA:** write per-year CONUS population totals and dropped population to
    `qa_report.csv`.

## Known cases

Findings from the initial join check (`notebooks/01_check_nhgis.ipynb`).

### Join summary (before cleaning)

| Year | Polygons | Pop. rows | Polygon only | Pop. only | Pop. ≤ 0 | Pop. without polygon |
|---|---|---|---|---|---|---|
| 1810 | 587 | 582 | 9 | 4 | 0 | 701,959 (8.84%) |
| 1820 | 778 | 761 | 17 | 0 | 0 | 0 |
| 1830 | 1,001 | 994 | 8 | 1 | 0 | 356 |
| 1840 | 1,285 | 1,280 | 5 | 0 | 0 | 0 |
| 1850 | 1,632 | 1,623 | 9 | 0 | 0 | 0 |
| 1860 | 2,126 | 2,077 | 50 | 1 | 0 | 782 |
| 1870 | 2,334 | 2,291 | 48 | 5 | 1 | 1,161 |
| 1880 | 2,614 | 2,612 | 3 | 1 | 42 | 134 |
| 1890 | 2,799 | 2,802 | 4 | 7 | 23 | 0 |
| 1900 | 2,848 | 2,857 | 3 | 12 | 0 | 30,552 (0.04%) |
| 1910 | 2,963 | 2,959 | 6 | 2 | 3 | 0 |
| 1920–2020 | | | ≤ 1 | 0 | ≤ 1 | 0 |

Counts for 2010 and 2020 (3,221) include Alaska, Hawaii and Puerto Rico; rule 1 removes them.

### Multi-county groups (rule 2)

| Year | GISJOIN | Name | Population | Check |
|---|---|---|---|---|
| 1810 | G2509993 | Massachusetts (ME part), multi-county group | 228,705 | County rows in MA sum to 700,745 = 228,705 + 472,040 |
| 1810 | G2509997 | Massachusetts (non-ME part), multi-county group | 472,040 | CSV total 7,940,626 − 700,745 = 7,239,881 = official 1810 U.S. total |

Massachusetts county-level data for 1810 are complete; only the aggregate rows are removed.

### Crosswalk entries (rule 3)

| Year | CSV GISJOIN | CSV name | Polygon GISJOIN | Polygon name | Note |
|---|---|---|---|---|---|
| 1900 | G1789177 | Quapaw Indian Reservation | G1789175 | Quapaw Agency | Code mismatch |
| 1900 | G5105100 | Alexandria city | *(Alexandria County polygon, to confirm)* | Alexandria County | Independent city without its own polygon; merge into county |

### Manual population fills (rule 4)

D.C. (`G1100010`) is missing from the population table in four census years.

| Year | Population | Source |
|---|---|---|
| 1820 | 23,336 | U.S. Census; see Sources |
| 1860 | 75,080 | U.S. Census; see Sources |
| 1880 | 177,624 | U.S. Census; see Sources |
| 1900 | 278,718 | U.S. Census; see Sources |

Values should be cross-checked against Census Bureau publications before final use.

### Reconstructed polygon (rule 5): D.C. 1820

In 1820 the NHGIS boundary file has a hole where D.C. should be, and the population
table has no D.C. row. D.C. boundaries did not change between 1801 and 1846 (the
original 10-mile square, including Alexandria). The 1820 unit is built by dissolving
the five 1830 D.C. polygons (GISJOIN starting with `G110`: Alexandria, Georgetown,
Rural Alexandria County, Rural Washington County, Washington City) into one polygon,
with `pop = 23,336` and `status = manual_fill`.

For reference, the five D.C. units sum to the D.C. total in years where they are
reported separately (1810: 24,023; 1830: 39,834).

### Unenumerated polygons (rule 6), examples

| Year | Examples |
|---|---|
| 1810 | Indian lands (Louisiana, Indiana, Michigan, Mississippi Territories; Georgia; North Carolina; Tennessee), Unattached (Louisiana Territory), Unorganized (South Carolina) |
| 1860–1870 | About 50 polygons per year, mostly western territories |

### Zero-population counties (rule 7), examples

| Year | Examples |
|---|---|
| 1880 | Dakota Territory (e.g., Bottineau, Cavalier, McHenry, Unorganized Territory); unorganized Texas counties (e.g., Andrews, Bailey) |
| 1890 | 23 counties |

Residents of these counties, if any, were counted in the county they were attached
to. Merging them into their parent county is a possible later refinement.

### Population without polygon (rule 8), examples

| Year | Examples | Population |
|---|---|---|
| 1900 | Indian reservations reported separately (San Carlos, AZ; Modoc, Ottawa, Peoria, Seneca, Shawnee, Wyandotte in Indian Territory; White Earth, MN; Crow, MT); Armstrong County, SD | about 30,000 in total |

## Interpretation note

Outputs represent the **enumerated** population. Early censuses did not count most
Native American populations, and unorganized areas were not enumerated. Cells
marked NoData mean "not enumerated", not "unpopulated". This must be stated as a
limitation in Chapter 1 and carried into Chapter 2 exposure estimates.

## Open items

- [ ] Confirm the Alexandria County polygon GISJOIN for the 1900 crosswalk entry.
- [ ] Review 1830–1910 "population only" rows not listed above (1–7 per year).
- [ ] Cross-check manual fills against Census Bureau publications.
- [ ] Decide whether to merge `nodata_zero` counties into their parent counties.

## Sources

- IPUMS NHGIS: https://www.nhgis.org
- 1810 United States census: https://en.wikipedia.org/wiki/1810_United_States_census
- Demographics of Washington, D.C. (historical census populations): https://en.wikipedia.org/wiki/Demographics_of_Washington,_D.C.
