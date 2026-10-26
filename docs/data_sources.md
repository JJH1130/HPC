# Data Sources

Registry of every external dataset used in this project. Add a row (and a
citation) before a dataset is used in any pipeline step. Keep download details
precise enough that anyone can obtain the same files again. Acknowledgement text
for compute resources (Alpine) is in `docs/acknowledgements.md`.

Last updated: 2026-10-24 (Siqiao's PLURAL grid + tract data); 2026-10-23 (PLURAL in v4.1 code; Stefan's CSV as the CONUS population input)

## Summary

| Dataset | Version / extract | Local path | Used for | Status |
|---|---|---|---|---|
| HISDAC-US (BUI, BUPL, BUPR, BUA, FBUY, NobuiltYear) | v2, 250 m | `/pl/active/Leyk_Lab/data/HISDAC_US_V2/` | Ch1 features, Ch2 patches | In use |
| HISDAC-US Land Use (class counts) | v2 (Version II), 250 m, 1940–2020 | `/pl/active/Leyk_Lab/data/HISDAC_US_V2/Land_Use/` | Ch1 features (E2, E3) | In use |
| NHGIS county population | Time series A00, nominal, extract nhgis0001 | `/projects/jaju1407/data/raw/nhgis/` | Ch1 target | In use |
| NHGIS county boundaries | 1810–2020, extract nhgis0001 | `/projects/jaju1407/data/raw/nhgis/nhgis0001_shape/` | Ch1 zones | In use |
| NHGIS tract population + boundaries | Extract nhgis0002: 1910–1960 source tables, 1970–2020 time series AV0 (nominal); boundaries 1910–2020 | `/projects/jaju1407/data/raw/nhgis/` (`nhgis0002_csv/`, `nhgis0002_shape/`) | Ch1 fine-scale validation of dasymetric outputs | Downloaded 2026-10-12; `src/census/prepare_tracts.py` written, not yet run |
| Census Bureau historical totals (Forstall 1996) | 1996 publication | (reference only) | Manual fills, QA | In use |
| Harmonized global NTL | Li et al. (2020), extended release | `/projects/jaju1407/data/raw/ntl/` | Ch1 feature (E3) | In use |
| JRC Global Surface Water (occurrence) | v1.4 (1984–2021), 30 m, 21 CONUS tiles | `/projects/jaju1407/data/raw/water/jrc_occurrence/` | Water fraction → v3.1 water mask | Downloaded 2026-10-05 |
| HydroLAKES polygons | v1.0 | `/projects/jaju1407/data/raw/water/` | Reservoir areas removed from water fraction (v3.1) | Superseded by GDW for reservoir removal |
| Global Dam Watch (GDW) reservoirs + barriers | v1.0 | `/projects/jaju1407/data/raw/water/gdw/` | Reservoir polygons with dam years → year-dependent water fraction | Downloaded 2026-10-12; in code for v4 (`water_frac.py`, `reservoir_source: gdw`), not run yet |
| County census by 2010 FIPS (+ CBSA/CSA codes), from Stefan Leyk | `all_county_census_MSA_full.csv`, 1900–2010 + 2015 est. | `/projects/jaju1407/data/raw/census_std/` (git: `data/census_std/`) | Massachusetts: CBSA attributes only. **CONUS (2026-10-23): county population input** on 2010 polygons (`src/census/conus_counties.py`, `docs/conus_plan.md`) + the train/test split's county list (`configs/conus_split.csv`) | In use; publisher to confirm |
| HydroRIVERS | v1.0, North America | `/projects/jaju1407/data/raw/water/` | Distance-to-river feature (later) | Optional |
| USGS GMTED2010 (mean elevation) | `mn75_grd`, 7.5 arc-seconds, global | `/projects/jaju1407/data/raw/dem/gmted2010/` | Ch1 elevation and slope features | In use: Massachusetts v4 (2026-10-19); CONUS v3 / v4 (cutout layer `DEM`, `average`; code 2026-10-27) |
| PLURAL place-level urban–rural indices | 2023 release (points, 1930–2018) | `/projects/jaju1407/data/raw/plural/plural_2023/` | Distance features `d_10k` … `d_250k` (v4.1: place populations + points → km to the nearest place per size class) | On Alpine; in code for v4.1 (`src/grid/place_dist.py`), not run yet |
| PLURAL gridded + tract (from Siqiao) | received 2026-10-24: 900 m grid 1940, 1980, 2010; tracts 1990–2020 on 2010 boundaries | `/projects/jaju1407/data/raw/plural/siqiao_2026/` | Not a feature: comparison check of the `d_*` distance layers (v2) | On Alpine; method of the grid ("index3") to confirm with Siqiao |

## Details

### HISDAC-US v2

- Layers: BUI (built-up intensity, indoor floor area in sq ft per cell), BUPL
  (built-up property locations), BUPR (built-up property records), BUA
  (built-up area, 0/1), FBUY (first built-up year), NobuiltYear (count of records
  without a built year), 1810–2020 at 5-year steps, 250 m, ESRI:102039
  (USA Contiguous Albers Equal Area Conic, USGS version).
- BUI definition (Harvard Dataverse description of HISDAC-US): the sum of the gross indoor area of all built-up
  properties in a grid cell in a given year. **Unit: square feet** (confirmed 2026-10-27 from `$HISDAC_DIR/BUI_README.txt`: "Integer-valued raster datasets
  containing indoor building gross area sum per pixel area in square feet"; job 34921582). A 250 m cell is 672,700 sq ft.
  The CONUS maxima (5.4e9 sq ft in one cell in 2010) are record errors (`docs/conus_plan.md`, "BUI outliers").
- Source data: ZTRAX (Zillow), Parcel Atlas, BuildZero Open City Model.
- Notes: built from contemporary records filtered by year built, so demolished
  structures are missing and early periods are under-represented. No nodata value;
  0 means no building or outside the U.S.
- Citations:
  - Leyk, S., & Uhl, J. H. (2018). HISDAC-US, historical settlement data
    compilation for the conterminous United States over 200 years. *Scientific
    Data*, 5, 180175. https://doi.org/10.1038/sdata.2018.175
  - Uhl, J. H., Leyk, S., McShane, C. M., Braswell, A. E., Connor, D. S., &
    Balk, D. (2021). Fine-grained, spatiotemporal datasets measuring 200 years of
    land development in the United States. *Earth System Science Data*, 13,
    119–153. https://doi.org/10.5194/essd-13-119-2021
  - Ahn, Y., Leyk, S., Uhl, J. H., & McShane, C. M. (2024). An integrated
    multi-source dataset for measuring settlement evolution in the United States
    from 1810 to 2020. *Scientific Data*, 11, 275.
    https://doi.org/10.1038/s41597-024-03081-x
  - Dataverse: https://dataverse.harvard.edu/dataverse/hisdacus

### HISDAC-US Land Use (Class Counts, Version II)

- Eight classes: A (agriculture), C (commercial), GV (governmental), I
  (industrial), RC (recreational), RI (residential-income), RO
  (residential-owned), VL (vacant land). Cumulative record counts per cell,
  1940–2020. Use `Count_{YEAR}_{CLASS}.tif`; `Theme*` files duplicate class files.
- Citation: McShane, C. M., Uhl, J. H., & Leyk, S. (2021). Historical Land Use
  for the U.S. 1940–2015. Harvard Dataverse. https://doi.org/10.7910/DVN/LNBJIO
  (Version II class counts: https://doi.org/10.7910/DVN/PRJBUF)

### NHGIS (IPUMS)

Common to all extracts:

- Use requires an IPUMS account and agreement to the NHGIS terms; raw files are
  not redistributed in this repository.
- Citation (official text from the nhgis0002 codebook, 2026-10-12):
  Jonathan Schroeder, David Van Riper, Steven Manson, Grace Cooper, Zachary
  Krause, Tracy Kugler, Tsu Zhu, and Steven Ruggles. IPUMS National Historical
  Geographic Information System: Version 21.0 [dataset]. Minneapolis, MN: IPUMS.
  2026. http://doi.org/10.18128/D050.V21.0
  - nhgis0001 (2026-09-30) is the same version: confirmed from its codebook
    (Version 21.0) on 2026-10-13.
  - Popular press / online resources: "IPUMS NHGIS, University of Minnesota,
    www.nhgis.org."
- IPUMS asks for a copy of any publication using the data: nhgis@umn.edu.

**Extract nhgis0001 (county; Ch1 target and zones)**

- Downloaded 2026-09-30.
- Time series table **A00 Total Population**, geographic level County,
  1810–2020, nominal integration, layout "time varies by row".
- GIS files: County, 1810–2000 on **2008 TIGER/Line+** basis, 2010 on
  **2010 TIGER/Line+**, 2020 on **2020 TIGER/Line+**.
- Preprocessing rules: `docs/census_preprocessing.md`.

**Extract nhgis0002 (tract; Ch1 fine-scale validation)**

- Downloaded 2026-10-12, to `/projects/jaju1407/data/raw/nhgis/`.
- `nhgis0002_csv/`: tract total population.
  - 1910–1960: source tables, 24 datasets (ds39–ds92). Coverage in 1910–1950 is
    city-specific (e.g. the 1910 and 1930 "Selected Areas" datasets include
    Massachusetts/Boston). 1960 (ds92) has NTSUP2, NBT1 and NBT4; the NBT tables
    come from printed reports.
  - 1970–2020: time series **AV0 Total Population**, nominal integration
    (`ts_nominal_tract.csv`).
- `nhgis0002_shape/`: tract boundaries per year (one zip per year), 1910–2000
  on **2008 TIGER/Line+**, 2010 on **2010 TIGER/Line+**, 2020 on **2020
  TIGER/Line+**.
- Note: the 1910–1930 tract data were keyed from printed census reports by
  Andrew Beveridge's team (Queens College, CUNY).
- Use: fine-scale validation of the dasymetric outputs (Ch1).
- Preprocessing rules: `docs/tract_preprocessing.md`.

### Census Bureau historical totals

- Forstall, R. L. (1996). *Population of States and Counties of the United
  States: 1790–1990*. U.S. Bureau of the Census, Washington, DC.
  Used for D.C. and Alexandria-side populations (1820, 1860, 1880, 1900).
- U.S. Census Bureau, 1990 CPH-2-1, Table 16 (state and U.S. totals 1790–1990),
  used for QA of annual totals.

### Harmonized global nighttime lights

- Files: `Harmonized_DN_NTL_2000_calDMSP.tif`, `Harmonized_DN_NTL_2010_calDMSP.tif`,
  `Harmonized_DN_NTL_2020_simVIIRS.tif`. EPSG:4326, 30 arc-seconds, DN 0–63.
- 2000 and 2010 are calibrated DMSP; 2020 is VIIRS converted to DMSP-like values.
- Citation: Li, X., Zhou, Y., Zhao, M., & Zhao, X. (2020). A harmonized global
  nighttime light dataset 1992–2018. *Scientific Data*, 7, 168.
  https://doi.org/10.1038/s41597-020-0510-y
- Download: figshare (extended release). [record download date and version]

### JRC Global Surface Water

- Layer: occurrence (percentage of observations with water), version **v1.4
  (1984–2021)**, 30 m, 10° tiles named `occurrence_{LON}_{LAT}v1_4_2021.tif` (LON =
  west edge, LAT = north edge). All 21 tiles covering CONUS were downloaded on
  **2026-10-05**. `src/grid/water_frac.py` selects the tiles that overlap the
  cutout window; Massachusetts uses `80W_50N` and `70W_50N` (the 1810 window
  reaches into Maine).
- Citation: Pekel, J.-F., Cottam, A., Gorelick, N., & Belward, A. S. (2016).
  High-resolution mapping of global surface water and its long-term changes.
  *Nature*, 540, 418–422. https://doi.org/10.1038/nature20584
- Download: https://global-surface-water.appspot.com/download (v1.4, downloaded
  2026-10-05)

### HydroLAKES (superseded by GDW for reservoir removal)

- Superseded (decided 2026-10-13, `docs/open_items.md`): reservoir removal will use
  GDW reservoir polygons with dam years (see below). The entry is kept because
  v3.1 used it.

- Lake and reservoir polygons ≥ 10 ha. `Lake_type`: 1 lake, 2 reservoir,
  3 lake control. Only `Lake_type = 2` polygons are used, to remove reservoirs
  from the JRC water fraction.
- License: CC-BY 4.0.
- Citation: Messager, M. L., Lehner, B., Grill, G., Nedeva, I., & Schmitt, O.
  (2016). Estimating the volume and age of water stored in global lakes using a
  geo-statistical approach. *Nature Communications*, 7, 13603.
  https://doi.org/10.1038/ncomms13603
- Download: https://www.hydrosheds.org/products/hydrolakes

### County census by 2010 FIPS (all_county_census_MSA_full.csv)

- **Source:** provided by Stefan Leyk, 2026-10-06. Original publisher to confirm
  (provisional; to be re-confirmed) — likely U.S. Census Bureau county counts
  1900–1990 + 2000/2010 decennial census + Vintage 2015 population estimates + OMB
  2015 CBSA delineations.
- Tracked in git at `data/census_std/all_county_census_MSA_full.csv` (510 KB, 3,131
  rows incl. AK and HI) and copied to `$DATA_ROOT/raw/census_std/` on Alpine.
- Columns: `FIPS` (stored as a number, leading zero lost), `STNAME`, `CTYNAME`,
  `CENSUS{1900..2010}POP` (decennial), `POPESTIMATE2015`, and OMB delineation fields
  (`CBSA Code`, `Metropolitan Division Code`, `CSA Code`, titles,
  Metropolitan/Micropolitan, Central/Outlying). No 2020 column.
- Checked so far (user, 2026-10-07):
  - Values look like each year's count for the county holding that FIPS, **not**
    areally standardized to 2010 boundaries (e.g. Yuma AZ 1980 seems to include
    La Paz; Virginia Beach 1960 = 8,091, before the Princess Anne merger).
  - NaN = county did not exist yet (291 counties; no gaps after the first value).
  - Missing 4 CONUS counties: 12086 (Miami-Dade), 08014 (Broomfield), 46113
    (Shannon), 51515 (Bedford city). AK and HI are dropped in processing.
- Diagnostic against the nominal NHGIS counties: `src/census/std_county_check.py`,
  `docs/runbooks/Checking_Std_Counties.md`.
- Result (job 33505541, reviewed 2026-10-09): counts equal NHGIS nominal counts
  (36,560 of 36,565 county-years, 1900–2010; 5 small differences: Morton ND 1900,
  James City VA 1910/1920, Fremont ID 1930, Park MT 1980). Not areally
  standardized: on 2010 polygons ~10 % of 1900–1910 population is misplaced and
  ~1–2 % dropped (counties absent in 2010).
- **Use (decided 2026-10-09):** CBSA attributes only (Metropolitan/Micropolitan,
  Central/Outlying). Population targets stay NHGIS nominal (`docs/open_items.md`).
  Open: ask Stefan whether an areally standardized version exists.

### Global Dam Watch (GDW) v1.0

- Files (in `GDW_v1_0_shp/`): `GDW_reservoirs_v1_0.shp` (35,295 reservoir
  polygons) and `GDW_barriers_v1_0.shp` (dams/barriers); technical documentation
  `GDW_TechDoc_v1_0.pdf` is included in the download. WGS84.
- Key reservoir fields: `YEAR_DAM` (dam completion year), `PRE_YEAR`, `YEAR_SRC`
  (source of the year), `QUALITY` (1–5), `LAKE_CTRL` (natural lake raised by a
  dam: Yes / Maybe), `HYLAK_ID` (HydroLAKES link), `GRAND_ID` (GRanD link).
- US check (user, 2026-10-13): 4,465 reservoirs, 44,446 km²; `YEAR_DAM` present
  for 99.1 % of the area; year sources NID 2,298, GRanD 1,884; Quabbin = 1939.
- Use: replaces HydroLAKES `Lake_type = 2` for reservoir removal; reservoirs
  count as water from `YEAR_DAM` on. Rules: `docs/open_items.md` (2026-10-13).
- License: CC BY 4.0.
- Citation: Lehner, B., et al. (2024). The Global Dam Watch database of river
  barrier and reservoir information for large-scale applications. *Scientific
  Data*, 11, 1069. https://doi.org/10.1038/s41597-024-03752-9
  [confirm full author list and order]
- Download: figshare, https://doi.org/10.6084/m9.figshare.25988293
  (downloaded 2026-10-12).

### HydroRIVERS (optional, later)

- River centerlines (no width); for a distance-to-river feature.
- Citation: Lehner, B., & Grill, G. (2013). Global river hydrography and network
  routing: baseline data and new approaches to study the world's large river
  systems. *Hydrological Processes*, 27(15), 2171–2186.
  https://doi.org/10.1002/hyp.9740
- Download: https://www.hydrosheds.org/products/hydrorivers (North America file)

### USGS GMTED2010

- Product: mean elevation statistic at 7.5 arc-seconds (~225 m), global,
  `mn75_grd` (ESRI ArcGrid, inside a zip).
- Specs (gdalinfo on Alpine, 2026-10-12): driver AIG (ESRI ArcGrid), EPSG:4326,
  pixel 0.0020833333° (7.5"), 172,800 × 67,200 cells, Int16 metres, NoData
  -32768. Extent 180°W–180°E, 56°S–84°N; the origin is offset by half a pixel
  (-180.000139, 83.999861). Unzipped grid is 5.3 GB; the zip was deleted after
  extraction.
- Planned use: elevation and slope features for Ch1, resampled to the HISDAC
  250 m grid (ESRI:102039). Slope method and resampling rule to be decided when
  the code is written.
- Citation: Danielson, J. J., & Gesch, D. B. (2011). *Global multi-resolution
  terrain elevation data 2010 (GMTED2010)*. U.S. Geological Survey Open-File
  Report 2011-1073. https://doi.org/10.3133/ofr20111073
- Download:
  https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/topo/downloads/GMTED/Grid_ZipFiles/mn75_grd.zip
  (listed at https://topotools.cr.usgs.gov/gmted_viewer/gmted2010_global_grids.php).
  Downloaded 2026-10-12.

## Pending (not yet obtained)

- Areally standardized (2010-boundary) county data, 1900 on: Stefan's CSV is nominal (see above); ask Stefan whether a standardized version exists.

### PLURAL (place-level urban–rural indices)

- Point data: one record per census place (about 30,000 places, CONUS), 1930–2010 decennial and 2018;
  `PLURAL_CSV/` (tables keyed by NHGIS place code) and `PLURAL_SHP/` (one point shapefile per year,
  ESRI:102003). Technical description: `PLURAL_indices_documentation.pdf` in the same folder.
- Two methods: PLURAL-1 (distance/raster-based: place population, focal population density, distances to the
  nearest places of 10–20k, 20–50k, 50–100k, 100–250k and >250k people) and PLURAL-2 (network-based,
  rank-based). Four weighting schemes each; scaled per year or across all years, range 0–1
  (0 = urban, 1 = remote/rural).
- Use: PLURAL-1 scaled across years only; PLURAL-2 "should not be used for longitudinal analysis" (paper).
- Citation: Uhl, J. H., Hunter, L. M., Leyk, S., Connor, D. S., Nieves, J. J., Hester, C., Talbot, C., &
  Gutmann, M. (2023). Place-level urban–rural indices for the United States from 1930 to 2018. *Landscape and
  Urban Planning*, 236, 104762. https://doi.org/10.1016/j.landurbplan.2023.104762
- Data: figshare https://doi.org/10.6084/m9.figshare.22596946 ; code https://github.com/johannesuhl/plural
- Gridded and tract versions from Siqiao (received 2026-10-24), `/projects/jaju1407/data/raw/plural/siqiao_2026/`:
  - `PLURAL_grid_data/index3_{1940,1980,2010}_900_US.tif`: 900 m, 8634 x 8500 cells, float32 0–1, no nodata value;
    CRS WGS 84 Lambert Azimuthal Equal Area (centre 45 N, 100 W), bounds (-4410000, -3340000, 3360600, 4310000) m,
    larger than CONUS. Checked 2026-10-24 by point samples: 1 = remote (Ely NV 0.81), 0 outside the US (ocean,
    Canada, Mexico all 0.0), so 0 is also the fill value; New York 0.0, Boston 0.56 (1940) / 0.60 (2010), Denver
    0.68 / 0.65, Pittsfield MA 0.55 / 0.69. Contrast between large cities and remote places is weaker than in the
    place-level index (New York 2010 = 0.013 there); what "index3" is (PLURAL-1 or -2, weighting, how points became a
    grid) is not in the `.tif.xml` metadata: ask Siqiao.
  - `PLURAL_tract_data/`: `PLURAL_rurality_index_tract_2010boundaries.csv` (72,271 CONUS tracts, 2010 boundaries,
    1990/2000/2010/2020; five versions 0–100, higher = more remote: `remote_area_wt`, `remote_pop_wt` (population
    weighted), `remote_dist_place` / `_metro` / `_balanced` (distances to five place tiers, percentile ranks pooled
    over years)), `codebook.csv`, `README.md`. Read GISJOIN and GEOID10 as text.
  - `PLURAL_open_data/`: copy of the published release (same as `plural_2023/`) plus `PLURAL_VIS/`.
  - Use: not a model feature (few years; `remote_pop_wt` uses tract population = leakage into tract validation).
    Used to check our cell distances: aggregate `d_*` to 2010 tracts / the 900 m grid and compare.
  - Citation: cite Uhl et al. (2023) with the dataset (README); dataset citation to confirm with Siqiao.
