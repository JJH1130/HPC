# Data Sources

Registry of every external dataset used in this project. Add a row (and a
citation) before a dataset is used in any pipeline step. Keep download details
precise enough that anyone can obtain the same files again.

Last updated: 2026-10-06

## Summary

| Dataset | Version / extract | Local path | Used for | Status |
|---|---|---|---|---|
| HISDAC-US (BUI, BUPL, BUPR, BUA, FBUY, NobuiltYear) | v2, 250 m | `/pl/active/Leyk_Lab/data/HISDAC_US_V2/` | Ch1 features, Ch2 patches | In use |
| HISDAC-US Land Use (class counts) | v2 (Version II), 250 m, 1940–2020 | `/pl/active/Leyk_Lab/data/HISDAC_US_V2/Land_Use/` | Ch1 features (E2, E3) | In use |
| NHGIS county population | Time series A00, nominal, extract nhgis0001 | `/projects/jaju1407/data/raw/nhgis/` | Ch1 target | In use |
| NHGIS county boundaries | 1810–2020, extract nhgis0001 | `/projects/jaju1407/data/raw/nhgis/nhgis0001_shape/` | Ch1 zones | In use |
| Census Bureau historical totals (Forstall 1996) | 1996 publication | (reference only) | Manual fills, QA | In use |
| Harmonized global NTL | Li et al. (2020), extended release | `/projects/jaju1407/data/raw/ntl/` | Ch1 feature (E3) | In use |
| JRC Global Surface Water (occurrence) | v1.4 (1984–2021), 30 m, 21 CONUS tiles | `/projects/jaju1407/data/raw/water/jrc_occurrence/` | Water fraction → v3.1 water mask | Downloaded 2026-10-05 |
| HydroLAKES polygons | v1.0 | `/projects/jaju1407/data/raw/water/` | Reservoir areas removed from water fraction | To download |
| HydroRIVERS | v1.0, North America | `/projects/jaju1407/data/raw/water/` | Distance-to-river feature (later) | Optional |

## Details

### HISDAC-US v2

- Layers: BUI (built-up intensity, indoor floor area in sq ft per cell), BUPL
  (built-up property locations), BUPR (built-up property records), BUA
  (built-up area, 0/1), FBUY (first built-up year), NobuiltYear (count of records
  without a built year), 1810–2020 at 5-year steps, 250 m, ESRI:102039
  (USA Contiguous Albers Equal Area Conic, USGS version).
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

- Extract nhgis0001, downloaded 2026-09-30.
- Time series table **A00 Total Population**, geographic level County,
  1810–2020, nominal integration, layout "time varies by row".
- GIS files: County, 1810–2000 on **2008 TIGER/Line+** basis, 2010 on
  **2010 TIGER/Line+**, 2020 on **2020 TIGER/Line+**.
- Use requires an IPUMS account and agreement to the NHGIS terms; raw files are
  not redistributed in this repository.
- Citation: Manson, S., Schroeder, J., Van Riper, D., Knowles, K., Kugler, T.,
  Roberts, F., & Ruggles, S. IPUMS National Historical Geographic Information
  System: Version [record version used]. Minneapolis, MN: IPUMS. [record DOI from
  the NHGIS citation page]
- Preprocessing rules: `docs/census_preprocessing.md`.

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

### HydroLAKES (to download)

- Lake and reservoir polygons ≥ 10 ha. `Lake_type`: 1 lake, 2 reservoir,
  3 lake control. Only `Lake_type = 2` polygons are used, to remove reservoirs
  from the JRC water fraction.
- License: CC-BY 4.0.
- Citation: Messager, M. L., Lehner, B., Grill, G., Nedeva, I., & Schmitt, O.
  (2016). Estimating the volume and age of water stored in global lakes using a
  geo-statistical approach. *Nature Communications*, 7, 13603.
  https://doi.org/10.1038/ncomms13603
- Download: https://www.hydrosheds.org/products/hydrolakes

### HydroRIVERS (optional, later)

- River centerlines (no width); for a distance-to-river feature.
- Citation: Lehner, B., & Grill, G. (2013). Global river hydrography and network
  routing: baseline data and new approaches to study the world's large river
  systems. *Hydrological Processes*, 27(15), 2171–2186.
  https://doi.org/10.1002/hyp.9740
- Download: https://www.hydrosheds.org/products/hydrorivers (North America file)

## Pending (not yet obtained)

- PLURAL (gridded) from Siqiao: record resolution, CRS, years, citation.
- DEM (for elevation and slope).
- 2010-standardized county data: source to be confirmed with Stefan.
