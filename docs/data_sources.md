# Data Sources

Registry of every external dataset used in this project. Add a row (and a
citation) before a dataset is used in any pipeline step. Keep download details
precise enough that anyone can obtain the same files again. Acknowledgement text
for compute resources (Alpine) is in `docs/acknowledgements.md`.

Last updated: 2026-10-30 (PLURAL grid: feature test on v5.6, 1940 / 1980 / 2010); 2026-10-30 (BUPR_contemp not in the Dataverse BUPR.tar: record uncertainty from NobuiltYear until it is found); 2026-10-30 (HISDAC-US `BUPR_contemp.tif` for the record-uncertainty diagnosis; NHGIS 2020 counties as the CONUS 2020 input); 2026-10-28 (external gridded population products: GHS-POP, WorldPop, GPW v4.11, GRUMP v1, Fang & Jawitz 2018); 2026-10-28 (VIIRS-like NTL, Chen et al. 2021); 2026-10-24 (Siqiao's PLURAL grid + tract data); 2026-10-23 (PLURAL in v4.1 code; Stefan's CSV as the CONUS population input)

## Summary

| Dataset | Version / extract | Local path | Used for | Status |
|---|---|---|---|---|
| HISDAC-US (BUI, BUPL, BUPR, BUA, FBUY, NobuiltYear) | v2, 250 m | `/pl/active/Leyk_Lab/data/HISDAC_US_V2/` | Ch1 features, Ch2 patches | In use |
| HISDAC-US BUPR_contemp (all property records, with or without a built year) | v2 BUPR record, Harvard Dataverse doi:10.7910/DVN/45B8IU, `BUPR_contemp.tif` (~2016), 250 m | `/projects/jaju1407/data/raw/hisdac_extra/` | Record-uncertainty diagnosis per county (share of records without a built year; `src/grid/record_uncertainty.py`) | Registered 2026-10-30; **not in the Dataverse BUPR.tar** (download run 2026-10-29, `logs/hisdac_extra_download.txt`); location asked of Stefan. Optional input: without it the diagnosis uses NobuiltYear (`ratio_A_nby`) |
| HISDAC-US Land Use (class counts) | v2 (Version II), 250 m, 1940–2020 | `/pl/active/Leyk_Lab/data/HISDAC_US_V2/Land_Use/` | Ch1 features (E2, E3) | In use |
| NHGIS county population | Time series A00, nominal, extract nhgis0001 | `/projects/jaju1407/data/raw/nhgis/` | Ch1 target; CONUS 2020 county input on the 2010 polygons (2026-10-30, `conus_counties.py`) | In use |
| NHGIS county boundaries | 1810–2020, extract nhgis0001 | `/projects/jaju1407/data/raw/nhgis/nhgis0001_shape/` | Ch1 zones | In use |
| NHGIS tract population + boundaries | Extract nhgis0002: 1910–1960 source tables, 1970–2020 time series AV0 (nominal); boundaries 1910–2020 | `/projects/jaju1407/data/raw/nhgis/` (`nhgis0002_csv/`, `nhgis0002_shape/`) | Ch1 fine-scale validation of dasymetric outputs | Downloaded 2026-10-12; `src/census/prepare_tracts.py` written, not yet run |
| Census Bureau historical totals (Forstall 1996) | 1996 publication | (reference only) | Manual fills, QA | In use |
| Harmonized global NTL | Li et al. (2020), extended release | `/projects/jaju1407/data/raw/ntl/` | Ch1 feature (E3) | In use |
| NPP-VIIRS-like global NTL | Chen et al. (2021), Harvard Dataverse doi:10.7910/DVN/YGIVCD, **Version1**, 2000 and 2010 | `/projects/jaju1407/data/raw/ntl/viirs_like/v1/` | CONUS feature test `ntlv` (`Dasy_CONUS_RF_v3_ntlv`, cutout layer `NTLV`) | Registered 2026-10-28; download by `sbatch/ntlv_download.sh`, not run yet |
| GHS-POP R2023A (JRC) | R2023A V1-0, 100 m Mollweide, epochs 1980 / 1990 / 2000 / 2010 | `/projects/jaju1407/data/raw/external/ghs_pop/` | External comparison on tracts (`configs/external_grids.yaml`) | Registered 2026-10-28; `sbatch/external_download.sh`, not run yet |
| WorldPop USA, unconstrained top-down | Global 2000-2020 (2018 release), `usa_ppp_{2000,2010}.tif`, 3 arc-sec, not UN-adjusted | `/projects/jaju1407/data/raw/external/worldpop/` | External comparison on tracts | Registered 2026-10-28; not downloaded yet |
| GPW v4.11 population count (CIESIN, NASA SEDAC) | Revision 11, 30 arc-sec, 2000 / 2010, not UN-adjusted | `/projects/jaju1407/data/raw/external/gpw4/` | External comparison on tracts | Registered 2026-10-28; needs an Earthdata login; not downloaded yet |
| GRUMP v1 population count (CIESIN et al., NASA SEDAC) | v1.00, 30 arc-sec, 1990 / 2000, global `.bil` | `/projects/jaju1407/data/raw/external/grump1/` | External comparison on tracts | Registered 2026-10-28; needs an Earthdata login; **no redistribution**; not downloaded yet |
| Fang & Jawitz (2018) US population 1790-2010 | figshare 5803110 v1, 1 km Albers (ESRI:102003), models M1-M5 (M3, M5 used), 1910-2010 without 1960 | `/projects/jaju1407/data/raw/external/fang_jawitz/` | External comparison on tracts (the only one with county input, as ours) | Registered 2026-10-28; not downloaded on Alpine yet (archive checked on the laptop) |
| JRC Global Surface Water (occurrence) | v1.4 (1984–2021), 30 m, 21 CONUS tiles | `/projects/jaju1407/data/raw/water/jrc_occurrence/` | Water fraction → v3.1 water mask | Downloaded 2026-10-05 |
| HydroLAKES polygons | v1.0 | `/projects/jaju1407/data/raw/water/` | Reservoir areas removed from water fraction (v3.1) | Superseded by GDW for reservoir removal |
| Global Dam Watch (GDW) reservoirs + barriers | v1.0 | `/projects/jaju1407/data/raw/water/gdw/` | Reservoir polygons with dam years → year-dependent water fraction | Downloaded 2026-10-12; in code for v4 (`water_frac.py`, `reservoir_source: gdw`), not run yet |
| County census by 2010 FIPS (+ CBSA/CSA codes), from Stefan Leyk | `all_county_census_MSA_full.csv`, 1900–2010 + 2015 est. | `/projects/jaju1407/data/raw/census_std/` (git: `data/census_std/`) | Massachusetts: CBSA attributes only. **CONUS (2026-10-23): county population input** on 2010 polygons (`src/census/conus_counties.py`, `docs/conus_plan.md`) + the train/test split's county list (`configs/conus_split.csv`) | In use; publisher to confirm |
| HydroRIVERS | v1.0, North America | `/projects/jaju1407/data/raw/water/` | Distance-to-river feature (later) | Optional |
| USGS GMTED2010 (mean elevation) | `mn75_grd`, 7.5 arc-seconds, global | `/projects/jaju1407/data/raw/dem/gmted2010/` | Ch1 elevation and slope features | In use: Massachusetts v4 (2026-10-19); CONUS v3 / v4 (cutout layer `DEM`, `average`; code 2026-10-27) |
| PLURAL place-level urban–rural indices | 2023 release (points, 1930–2018) | `/projects/jaju1407/data/raw/plural/plural_2023/` | Distance features `d_10k` … `d_250k` (v4.1: place populations + points → km to the nearest place per size class) | On Alpine; in code for v4.1 (`src/grid/place_dist.py`), not run yet |
| PLURAL gridded + tract (from Siqiao) | received 2026-10-24: 900 m grid 1940, 1980, 2010; tracts 1990–2020 on 2010 boundaries | `/projects/jaju1407/data/raw/plural/siqiao_2026/` | Grid: feature test (v5.6 + plural, 1940 / 1980 / 2010; cutout layers PLURAL bilinear / PLURALC cubic); tracts: not a feature | On Alpine; method of the grid ("index3") to confirm with Siqiao (see Details: possible same-year population leakage) |

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
- **BUPR_contemp.tif** (from `BUPR_README.txt`, checked 2026-10-28, `logs/hisdac_inventory.txt`): all built-up property
  records of the underlying ZTRAX data regardless of the value or availability of the built year, i.e. the record
  distribution around 2016. Part of the Dataverse BUPR archive (doi:10.7910/DVN/45B8IU) but **not in `$HISDAC_DIR`**
  (only `BUPR/{1810..2020}_BUPR.tif`). It is the "complete" layer for the record-uncertainty idea (meeting 2026-10-28).
  README says ZTRAX only, while the time series also use Parcel Atlas and Open City Model: check before comparing.
  **Checked 2026-10-30: not in the Dataverse BUPR.tar either** (v2, 45 members: `BUPR/1810..2020_BUPR.tif` + README;
  `results/hisdac_uncertainty/BUPR.tar_members.txt`). The README sentence seems carried over; where the file is: ask Stefan.
  Until then `record_uncertainty.py` runs without it: the share of records without a built year comes from
  NobuiltYear as `ratio_A_nby = NobuiltYear / (BUPR_2015 + NobuiltYear)` (contemp = records with a year + records
  without one, so the same share; needs NobuiltYear to be a count). If the file turns up, put it at
  `$DATA_ROOT/raw/hisdac_extra/BUPR_contemp.tif` and rerun: `ratio_A_contemp` is added and compared with `ratio_A_nby`.
- `FBUY/NobuiltYear.tif` (`FBUY_README.txt`): "values indicate the presence of built structures without built year";
  whether it is a count or a 0/1 flag is to be checked from its values (`record_uncertainty.py` writes its value
  distribution, `results/hisdac_uncertainty/nobuilt_values.csv`).
- **BUPR_contemp download (registered 2026-10-30; run 2026-10-29: the archive has no such file, see above):** `bash sbatch/hisdac_extra_download.sh` on a login node
  (tmux). It lists the files of doi:10.7910/DVN/45B8IU through the Dataverse API
  (`https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=doi:10.7910/DVN/45B8IU`; the listing is
  saved as `results/hisdac_uncertainty/dataverse_45B8IU_files.tsv`), downloads `BUPR_contemp.tif` alone if it is a file
  of its own, otherwise the BUPR archive to scratch (`$SCRATCH/hisdac_extra/`, md5 from the API checked) and unpacks only
  that file into `$DATA_ROOT/raw/hisdac_extra/` (+ `.md5`). Same citation and terms as the other HISDAC layers (Ahn
  et al. 2024, below; the dataset's license / terms are printed by the script).
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

### NPP-VIIRS-like global nighttime lights (Chen et al. 2021)

- What: annual global "NPP-VIIRS-like" night lights, 2000-2018. **2000-2012 are DMSP-OLS data converted to
  VIIRS-like values by an auto-encoder** (input: calibrated DMSP-OLS + MODIS EVI, "EANTLI"); **2013-2018 are annual
  composites of real NPP-VIIRS** (median of the 12 monthly VIIRS composites). Used here for 2000 and 2010, so both
  are converted DMSP values (less blooming than the DMSP DN of Li et al. 2020, which is why it is tested:
  `docs/conus_plan.md`, "VIIRS-like NTL test").
- Format (paper, Data availability / Sect. 2.2): GeoTIFF, WGS84, 15 arc-seconds (~500 m), radiance in
  nW cm-2 sr-1. Dark background = 0, simulated values < 1 nW set to 0, sea removed with a land mask, abnormal
  pixels above a city-derived maximum replaced by their 8-neighbour maximum. The paper gives no nodata value or data
  type: `src/grid/ntlv_check.py` logs them (and how the sea is stored) before the cutout.
- Dataverse record (checked through the API 2026-10-28, dataset version 10.1): **license CC0 1.0**
  (http://creativecommons.org/publicdomain/zero/1.0). The record now also holds a **Version2** (1992-2025, Chen et
  al. 2026, deep-learning super-resolution; top-level `{YEAR}_Version2.zip`, updated December 2025 and July 2026)
  and `HasMask` files (Version1, 2013-2024). This project uses **Version1** (the 2021 paper):
  `Version1/2000_Version1.zip` (file id 3986638, 59,122,309 bytes, md5 2a206d41905af713248ca37959110613) and
  `Version1/2010_Version1.zip` (file id 3987119, 78,849,392 bytes, md5 cb98449db9d4e2e38235e145394f2113).
- Download: `bash sbatch/ntlv_download.sh` on a login node (API listing -> ids + md5 -> `/api/access/datafile/<id>`,
  md5 checked, unpacked flat into `viirs_like/v1/<year>/`); `VERSION=2` would put Version2 into `viirs_like/v2/`.
  Without internet on the cluster: download on the laptop and copy (`docs/runbooks/Running_CONUS.md`, section 7).
  Record the download date here after the first run.
- Citation: Chen, Z., Yu, B., Yang, C., Zhou, Y., Yao, S., Qian, X., Wang, C., Wu, B., & Wu, J. (2021). An extended
  time series (2000-2018) of global NPP-VIIRS-like nighttime light data from a cross-sensor calibration. *Earth
  System Science Data*, 13, 889-906. https://doi.org/10.5194/essd-13-889-2021
- Data: Chen, Z., Yu, B., et al. (2020). Harvard Dataverse. https://doi.org/10.7910/DVN/YGIVCD

### External gridded population products (comparison on tracts, 2026-10-28)

Compared with CONUS v5.4 (`Dasy_CONUS_RF_v3_all`) on the same census tracts (`docs/conus_plan.md`, "External
comparison"; paths and years in `configs/external_grids.yaml`). Downloaded by `bash sbatch/external_download.sh` (login
node) into `/projects/jaju1407/data/raw/external/<product>/`; none of these files go into git. **US input unit** = the
census unit a product spreads over its grid in the US. A product whose input is finer than tracts (blocks, block
groups) starts from counts that already add up to (nearly) the tract totals, so it has an advantage on a tract
validation; ours and Fang & Jawitz start from counties. "Unverified" = the official document could not be read on
2026-10-28 (the SEDAC documents need an Earthdata login; the inventory step prints the USA rows of the GPWv4.11 country
summary once it is downloaded). Write the verified unit here and in `configs/external_grids.yaml` when known.

#### GHS-POP R2023A

- What: residential population per 100 m cell (World Mollweide, ESRI:54009), epochs 1975-2030 every 5 years; used:
  1980, 1990, 2000, 2010. People per cell.
- US input unit: the CIESIN **GPWv4.11** census / administrative units, spread over cells with the GHS built-up volume
  (dataset description: residential population estimates "derived from CIESIN GPWv4.11 were disaggregated from census
  or administrative units to grid cells"; https://data.europa.eu/89h/2ff68a52-5b5b-4a22-8f40-c41da8332cfe). So the US
  unit is GPWv4.11's (unverified, see GPW). GPWv4.11 starts in 2000: the 1980 and 1990 epochs are estimates for those
  units, not that year's census counts (method: GHSL Data Package 2023, not read here).
- Files (JRC's own AWS bucket, Registry of Open Data `ghs-pop`, no account):
  `https://jrc-ghsl.s3.eu-central-1.amazonaws.com/ghs-pop/r2023a/54009/100m/<YEAR>/GHS_POP_E<YEAR>_GLOBE_R2023A_54009_100_V1_0.tif`;
  bytes (bucket listing 2026-10-28): 1980 4,189,468,816; 1990 4,542,378,023; 2000 4,742,953,518; 2010 5,121,499,452
  (size checked; the bucket's ETags are multipart, not md5). The JRC FTP
  (`https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/`, one zip per epoch) did not answer
  from the laptop on 2026-10-28. The 3 arc-sec WGS84 version (8.9-12.6 GB per epoch) is in the same bucket
  (`ghs-pop/r2023a/4326/3asec/`); not used.
- License: CC BY 4.0.
- Citation: Schiavina, M., Freire, S., Carioli, A., & MacManus, K. (2023). GHS-POP R2023A - GHS population grid
  multitemporal (1975-2030). European Commission, Joint Research Centre.
  https://doi.org/10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE

#### WorldPop USA (unconstrained, top-down)

- What: people per ~100 m cell (3 arc-seconds, WGS84), random-forest dasymetric redistribution of census-based unit
  counts, unconstrained (every land cell may get people); `usa_ppp_2000.tif`, `usa_ppp_2010.tif` (not the `_UNadj`
  files).
- US input unit: **unverified**. The 2000-2020 global series uses subnational census-based counts prepared with
  CIESIN (Lloyd et al. 2019, GPWv4 units); the dataset pages (https://hub.worldpop.org/geodata/summary?id=4055 and
  `?id=1573`) do not name the US unit level.
- Files: `https://data.worldpop.org/GIS/Population/Global_2000_2020/<YEAR>/USA/usa_ppp_<YEAR>.tif`; bytes (2026-10-28):
  2000 4,006,455,556; 2010 4,012,143,985 (size checked).
- License: CC BY 4.0 (https://hub.worldpop.org/data/licence.txt).
- Citation: WorldPop (School of Geography and Environmental Science, University of Southampton; Department of
  Geography and Geosciences, University of Louisville; Departement de Geographie, Universite de Namur) and CIESIN,
  Columbia University (2018). Global High Resolution Population Denominators Project (OPP1134076).
  https://doi.org/10.5258/SOTON/WP00645

#### GPW v4.11 population count

- What: people per 30 arc-second cell (WGS84), census units spread evenly over their area (no ancillary data), 2000 /
  2005 / 2010 / 2015 / 2020; used: 2000, 2010, the population count (not the one adjusted to UN WPP).
- US input unit: **unverified** here: 2010-round census units at "the most detailed spatial resolution available"
  (https://www.earthdata.nasa.gov/data/projects/gpw). The US row of the country-level summary
  (`gpw-v4-rev11-country-level-summary-general-documentation.xlsx`, Earthdata login) is printed by the inventory step.
- Files (NASA Earthdata login, `~/.netrc`):
  `https://data.earthdata.nasa.gov/nasa-earth/human-dimensions/sedac-root/downloads/data/gpw-v4/gpw-v4-population-count-rev11/gpw-v4-population-count-rev11_<YEAR>_30_sec_tif.zip`
  (~405 MB each, CMR granule listing 2026-10-28; zip integrity checked); documents in
  `.../sedac-root/downloads/docs-repo/` (`gpw-v4-rev11-documentation.pdf`, the country summary `.xlsx`).
- License: CC BY 4.0 (CMR collection CIESIN_SEDAC_GPWv4_POPCOUNT_R11).
- Citation: Center for International Earth Science Information Network (CIESIN), Columbia University (2018).
  Gridded Population of the World, Version 4 (GPWv4): Population Count, Revision 11. NASA SEDAC.
  https://doi.org/10.7927/H4JW8BX5

#### GRUMP v1 population count

- What: people per 30 arc-second cell, 1990 / 1995 / 2000; GPWv3 census units allocated with urban extents (urban /
  rural split); used: 1990, 2000, global `.bil` (`gl_grumpv1_pcount_{90,00}_bil_30.zip`; a UN-adjusted grid in the
  same zip, if any, is left out by `exclude` in the config).
- US input unit: **unverified** (GPWv3 units; `gpw-v3-documentation.pdf` is downloaded with the GPW documents).
- Files (Earthdata login):
  `https://data.earthdata.nasa.gov/nasa-earth/human-dimensions/sedac-root/gpw/app/_region_Global_file_grumpv1_data_pcount_type_bil_level-scope_continent_resolut_30_year_<YY>`
  (CMR collection CIESIN_SEDAC_GRUMPv1_POPCOUNT; 1990 281 MB, 2000 277 MB; zip integrity checked).
- License (CMR use constraints): copyright CIESIN, IFPRI, The World Bank, CIAT; **no commercial use, resale or
  redistribution without written permission**; acknowledge the four as the source. Kept on the cluster only.
- Citation: CIESIN, IFPRI, The World Bank, & CIAT (2011). Global Rural-Urban Mapping Project, Version 1 (GRUMPv1):
  Population Count Grid. NASA SEDAC. https://doi.org/10.7927/H4VT1Q1H; Balk, D. L., et al. (2006). Determining global
  population distribution: methods, applications and data. Advances in Parasitology, 62, 119-156.

#### Fang & Jawitz (2018): conterminous US population 1790-2010

- What: people per 1 km cell, USA Contiguous Albers (ESRI:102003, NAD83), every census decade 1790-2010 **without
  1960** (no digital urban population for 1960); five models M1-M5, Esri GRID folders `pop_m<model>_<year>` (+ the
  shared `info/` folder). M1: county pop spread evenly; M2: urban / rural split; **M3**: + non-inhabitable areas
  removed (water bodies, protected areas, highlands, **low-population census tracts**); M4: + topography; **M5**: +
  socio-economic desirability. Used: M3 and M5 (request: M3 the most efficient, M5 the most complete; in the paper's
  tract validation M4 had the lowest mean error, M5 almost the same).
- US input unit: **county** (NHGIS county totals and urban population; paper: "we use county-level census data, as
  this is the highest resolution data consistently available from 1790 to 2010"). But M3-M5 use 2000 census tracts:
  tracts below a cutoff population (per census division) are non-inhabitable, and the s / d parameters were calibrated
  on 2000 data; the paper validates on 2000 tracts and county subdivisions. So 2000 is not an independent test for M3 /
  M5.
- Files: figshare collection https://doi.org/10.6084/m9.figshare.c.3890191, article 5803110: one archive
  `USA_HistoricalPopulationDataset.7z` (file 10257111, 601,757,624 bytes, md5 a7e869b0cd128721b1594151bd8f45d7, from the
  figshare API 2026-10-28), LZMA2, unpacked with py7zr into `fang_jawitz/grids/USA_HistoricalPopulationDataset/`.
  Checked on the laptop 2026-10-28: `pop_m3_2010` float32, 5999 x 3232 cells of 1000 m, nodata outside CONUS and on
  the sea, sum 306.6 million (2010); `pop_m5_1910` sum 91.8 million.
- License: data CC0 (figshare); paper CC BY 4.0.
- Citation: Fang, Y., & Jawitz, J. W. (2018). High-resolution reconstruction of the United States human population
  distribution, 1790 to 2010. Scientific Data, 5, 180067. https://doi.org/10.1038/sdata.2018.67; data: Fang, Y., &
  Jawitz, J. W. (2018). figshare. https://doi.org/10.6084/m9.figshare.c.3890191

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
    Use (2026-10-30, request `docs/handoff/plural_grid_request.md`): feature test (v5.6 + plural, 1940 / 1980 / 2010;
    `docs/conus_plan.md` "PLURAL grid test"): resampled to the HISDAC 250 m grid (bilinear = main, cubic clipped to
    0-1 = sensitivity; cutout layers PLURAL / PLURALC), continuous and in 3 / 5 classes. Still unknown: whether
    index3 is PLURAL-1 or PLURAL-2 and whether it is population-weighted. Caution: if the index is built from
    population (place populations, focal population density, population weights), a grid of the same year carries
    that year's census population into the model as a feature (leakage into the county target and the tract
    validation), and a good score would partly measure that. Confirm with Siqiao before any result is used beyond
    this test.
  - `PLURAL_tract_data/`: `PLURAL_rurality_index_tract_2010boundaries.csv` (72,271 CONUS tracts, 2010 boundaries,
    1990/2000/2010/2020; five versions 0–100, higher = more remote: `remote_area_wt`, `remote_pop_wt` (population
    weighted), `remote_dist_place` / `_metro` / `_balanced` (distances to five place tiers, percentile ranks pooled
    over years)), `codebook.csv`, `README.md`. Read GISJOIN and GEOID10 as text.
  - `PLURAL_open_data/`: copy of the published release (same as `plural_2023/`) plus `PLURAL_VIS/`.
  - Use: not a model feature (few years; `remote_pop_wt` uses tract population = leakage into tract validation).
    Used to check our cell distances: aggregate `d_*` to 2010 tracts / the 900 m grid and compare.
  - Citation: cite Uhl et al. (2023) with the dataset (README); dataset citation to confirm with Siqiao.
