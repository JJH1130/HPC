# CONUS plan: Dasy_CONUS_RF_v1

The Massachusetts pilot (v1-v4.1) is closed; the pipeline now moves to the conterminous US (48 states + DC).
This file is the plan for the first CONUS runs. Decisions are also in `docs/open_items.md` (decision log).

Last updated: 2026-10-23

## Decisions (2026-10-23)

| Topic | Decision |
|---|---|
| Name | `Dasy_CONUS_RF_v1` (study, model and version in one name). Later feature sets or models get new names (`..._v2`, `Dasy_CONUS_LGBM_v1`) |
| Model | Random Forest, the search space of `configs/model.yaml` |
| Years | 1900-2010 census years (12). 2020 added later from NHGIS (the CSV has no 2020; its 2015 value is an estimate, not a census) |
| Census input | Stefan's county CSV on 2010 county polygons (`data/census_std/`, `counties_std_2010.gpkg` from `std_county_check`), as agreed with Stefan 2026-10-23; known errors accepted for now (below) |
| Models | One model per census year (~3,000 counties per year), not pooled eras |
| Train / test | Counties split at random 80:20 within each state (stratified by state, fixed seed), once, before any tuning, and the same split in every year. Every state is in both parts, so the model sees each state's land-use coding (assessor practice differs by state). Test counties (~600) are never used for training or tuning; their county totals are still used for allocation. Within the train counties, 5-fold CV grouped by county picks hyperparameters; then the model is refit on all train counties and scored once on the test counties. Neighbouring train counties make the county test score somewhat optimistic; tract validation (tract counts are never used in training) is the independent check. The split (2010 FIPS -> train/test) and the 5 CV folds are written once to tracked files and reused for every year and every version, so versions are compared on the same counties; a county without a value in a year is simply absent that year |
| Trial years first | 1920, 1960, 2010 (one per former era). Run the rest only after the trial shows time and memory |

## Feature sets to compare

| Name (proposal) | Features | From MA |
|---|---|---|
| `Dasy_CONUS_RF_v1` | bui, bldg_size, mu_ratio, dist_built, (+ res_share, rent_share from 1940) | v3.4 set, yearly GDW water mask |
| `Dasy_CONUS_RF_v2` | v1 + d_10k, d_20k, d_50k, d_100k, d_250k (from 1940) | v4.1 |
| later | + elev, slope (absolute or relative to the county mean) | v4 |

`year` is constant within a per-year model and is dropped. In 1920 v1 and v2 are identical (distances start in 1940,
`place_dist.first_year`), so 1920 runs v1 only.

## Known input errors (accepted for now)

From `std_county_check` (job 33505541) and `docs/open_items.md`:

- 2010 counties with no CSV value (people placed elsewhere or missing): 291 in 1900 (13.5 % of the area, 55 in
  Oklahoma: Indian Territory), 166 in 1910, 51 in 1920, 20 or fewer from 1930. These counties need a status that
  excludes them from training and allocation (NoData, not zero people; to implement); their population is either in a neighbouring code (Yuma/La Paz) or absent.
- Counties whose area differs from the 2010 polygon: 15.5 % of the population in 1900, 5.5 % in 1930, under 5 %
  after; part of this is drawing differences between NHGIS and 2010 polygons (Norfolk MA).
- The alternative (each year's NHGIS polygons, then sum the 250 m output to 2010 counties) stays available if
  the errors matter in the results.

## Validation

- County: 5-fold grouped CV inside the train counties (tuning), and the single test-county score.
- Tract (`src/validation/tract_validate.py`, extend to CONUS): NHGIS tracts cover 14 counties (~9.7 M people) in
  1920, 302 counties (~103 M) in 1960 and all counties in 2010 (`results/tract/coverage_by_county.csv`). Report
  train and test counties separately.
- Areal-weighting baseline and totals QA as in Massachusetts.

## Scale checks before the first run

The Massachusetts window is 1711 x 2842 = 4.9 M cells; CONUS at 250 m is roughly 25 times larger per layer
(order 10^8 cells; exact size from the HISDAC grid). Each stage is checked for whole-window arrays and run time:

| Stage | Script | Check |
|---|---|---|
| Cutout | `src/grid/make_cutout.py` | CONUS window and zones from 2010 polygons; layer files per year; disk on scratch |
| Water | `src/grid/water_frac.py` | JRC tiles for CONUS (21 tiles), GDW for the US; block processing already; time for 12 yearly layers |
| Distances | `src/grid/place_dist.py` | whole-window float32 per class and year; cKDTree queries in row blocks already |
| Features | `src/dasymetric/county_features.py` | county means over ~10^8 cells; `dist_built` distance transform on the whole window (memory) |
| Train | `src/dasymetric/train.py` | per-year model, train/test state split, ~2,500 rows: light |
| Predict | `src/dasymetric/predict.py` | RF prediction for ~10^8 cells per year is the heaviest step (hours with 500-1,000 trees): predict in blocks, in parallel, possibly only cells inside used counties |
| Validate | `src/validation/tract_validate.py` | all states, train/test split in the report |

Outputs: `$HISDAC_SCRATCH/cutouts/conus`, `$HISDAC_SCRATCH/dasymetric/conus/Dasy_CONUS_RF_v1`. Scratch is purged
after 90 days: copy small results to `results/`.

## Order

1. Scale review of each stage (above) and a resource estimate per job (memory, time, disk).
2. CONUS cutout for 1920, 1960, 2010 + water mask + distances.
3. Census input: CSV on 2010 polygons for the three years; train/test state split saved to a tracked file.
4. Per-year features, train (v1, v2), predict, tract validation.
5. Review time, memory and results; then the remaining years (1900-2010), then 2020.
