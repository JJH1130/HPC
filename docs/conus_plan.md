# CONUS plan: Dasy_CONUS_RF_v1

The Massachusetts pilot (v1-v4.1) is closed; the pipeline now moves to the conterminous US (48 states + DC).
This file is the plan for the first CONUS runs. Decisions are also in `docs/open_items.md` (decision log).

Last updated: 2026-10-27 (pilot result; v3 / v4 = terrain; BUI outlier check; tract density classes; county maps)

Run steps: `docs/runbooks/Running_CONUS.md`. Configs: `configs/conus_study_area.yaml`, `configs/conus_rf_v1.yaml`,
`configs/conus_rf_v2.yaml`, `configs/conus_rf_v3.yaml`, `configs/conus_rf_v4.yaml`, split `configs/conus_split.csv`.

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

| Name | Features | From MA | Status (2026-10-27) |
|---|---|---|---|
| `Dasy_CONUS_RF_v1` | bui, bldg_size, mu_ratio, dist_built, (+ res_share, rent_share from 1940) | v3.4 set, yearly GDW water mask | run 1920/1960/2010; reference |
| `Dasy_CONUS_RF_v2` | v1 + d_10k, d_20k, d_50k, d_100k, d_250k (from 1940) | v4.1 | run 1960/2010; **dropped** (worse on tracts) |
| `Dasy_CONUS_RF_v3` | v1 + elev, slope | v4 terrain | run 1960/2010; **CONUS base** (best on tracts) |
| `Dasy_CONUS_RF_v4` | v1 + d_10k ... d_250k + elev, slope | v4 + v4.1 | run 1960/2010; dropped (~ v2) |

`year` is constant within a per-year model and is dropped. In 1920 v1 and v2 are identical (distances start in 1940,
`place_dist.first_year`), so 1920 runs v1 only.

## Known input errors (accepted for now)

From `std_county_check` (job 33505541) and `docs/open_items.md`:

- 2010 counties with no CSV value (people placed elsewhere or missing): 291 in 1900 (13.5 % of the area, 55 in
  Oklahoma: Indian Territory), 166 in 1910, 51 in 1920, 20 or fewer from 1930. These counties need a status that
  excludes them from training and allocation (NoData, not zero people; implemented 2026-10-23 as status
  `no_value`); their population is either in a neighbouring code (Yuma/La Paz) or absent.
- 2010 polygons without a CSV row (`results/census_std/std_vs_2010_unmatched.csv`): Miami-Dade (2.5 M people in
  2010), Shannon SD, Broomfield, Bedford city. The CSV has no row for them under any code (12025/12086, 46113/46102
  checked), so a FIPS remap can't fix them. **Fixed 2026-10-24:** `conus_counties.py` takes their pop from that
  year's NHGIS nominal county (`counties_{YEAR}.gpkg`, same GISJOIN; Miami-Dade as Dade County G1200250 where NHGIS
  uses the old code), logged with the NHGIS / 2010 area ratio (`results/census_conus/counties_conus_filled.csv`).
  Years without an NHGIS county (Broomfield before 2010, Bedford city before it became independent) stay `no_value`.
  **Training (2026-10-24, user decision):** the four counties were appended to `configs/conus_split.csv` as train
  (existing rows unchanged; `make_split.py --append-train`: each to the fold with the fewest train counties,
  ties to the lowest fold: Broomfield 3, Miami-Dade 4, Shannon 0, Bedford city 1; folds now 498/498/497/497/497).
  Per county-year, status `filled_nhgis` if the NHGIS / 2010 area ratio is within 0.95-1.05 (allocated and trained on), else `filled_nhgis_alloc` (allocated only); `use_status: [ok, filled_nhgis,
  filled_nhgis_alloc]`, `train_status: [ok, filled_nhgis]`.
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

## Scale checks (code review 2026-10-23)

Grid: the HISDAC-US raster is 18459 x 11615 = **214.4 M cells** (250 m, ESRI:102039; from the cutout logs), 44 times
the Massachusetts window (1711 x 2842 = 4.9 M). The 2010 counties cover about 8.1 M km² = **~130 M cells** (the
rest is ocean, Canada, Mexico). One whole-window layer is 0.43 GB as uint16 (zones), 0.86 GB as int32/float32 and
1.7 GB as float64 (the HISDAC BUI rasters are float64 on disk).

Estimates are scaled from the Massachusetts v4 / v4.1 logs (jobs 34662977-34785501); the **trial run** (runbook
`docs/runbooks/Running_CONUS.md`, step 0) measures the real values (`seff`, `MEASURE` line) before the pilot.

| Stage | Whole-window arrays / slow parts found in the code | Change (2026-10-23) | Peak memory | Time (3 trial years) | Scratch disk | Job (`submit_conus.sh`) | Measured (trial, 1960 v1: elapsed / MaxRSS / cores) |
|---|---|---|---|---|---|---| ---|
| Census input | none | new `src/census/conus_counties.py` | < 2 GB | minutes | 3 GPKG of 2010 polygons | 2 cores, 30 min | 1:14 / 1.8 GB / 2 (3 years) |
| Cutout (`make_cutout.py`) | each layer-year read whole (float64 BUI 1.7 GB) + nodata mask + copy of valid values + cast: ~4 x the layer; zone rasterize 0.43 GB | `window: full`; otherwise none (fits in memory) | ~6-7 GB | 28 rasters + 3 zone grids; MA: ~0.6 s per raster at 4.9 M cells -> ~0.5-1.5 min each: **15-45 min** | ~1-2 GB | 4 cores (15 GB), 3-6 h wall | 1:59 / 8.0 GB / 4 (1 year: 12 rasters, 6-8 s each) |
| Water (`water_frac.py`) | one float32 window per year (0.86 GB) + no-data share; per 256 x 256 block ~8 M JRC pixels in float64 arrays (~1 GB); MA: 5.2 s per block in one process | blocks in `SLURM_CPUS_ON_NODE` processes (same result, tested); `only_zone_blocks: true` skips blocks without a county cell; `--years` | main ~3.5 GB (12 years: ~11 GB) + ~1 GB per worker | 3,358 blocks, ~2,100 with county cells x 5 s = 3 h in one process -> **~15-20 min with 16** | float32 per year, mostly 0: ~0.1-0.3 GB each | 16 cores (60 GB), 4 h | 14:32 / 16.0 GB / 16 (2,102 blocks) |
| Distances (`place_dist.py`) | one float32 layer at a time (0.86 GB); KD-tree queries already in 128-row blocks, `SLURM_CPUS_ON_NODE` workers; MA: 220 M queries in 58 s on 4 workers | none | ~2-3 GB | 5 classes x 214 M = 1.07 B queries per year -> **~3-5 min per year** on 8 workers (1960, 2010) | smooth float32 compresses poorly: ~0.3-0.5 GB per layer, 10 layers: **3-5 GB** | 8 cores, 1-2 h | 2:54 / 3.1 GB / 8 (1 year) |
| Features (`county_features.py`) | every layer read as whole-window float64 and its masked cells cached: ~16 layers x 1 GB + 11 feature columns x 1 GB ≈ **30 GB for v2**; `np.isin` on 214 M cells; `dist_built` = exact distance transform of the whole window | strips of `block_rows: 512` window rows (9.5 M cells) with per-county sums (strips = whole window, tested); lookup-table mask; `dist_built` computed once per year and sliced (float64 1.7 GB kept, ~4 GB inside scipy, in-place km scaling) | ~8 GB | MA: ~1.9 µs per cell-year -> **~7 min per year and version** (v2 reads 5 more layers) | CSV only | 4 cores (15 GB), 2-4 h | 1:03 / 10.0 GB / 4 (23 strips in 43 s) |
| Train (`train.py`) | none: ~2,500 train rows per year | `split:` table (test counties held out, folds from the table, test score once); `--years` | < 4 GB | 20 x 5 fits + refit + SHAP on ~2,500 rows: **~5-15 min per year** | CSV/PNG | 16 cores, 1-2 h | 3:35 / 4.1 GB / 16 (SHAP 2.3 min) |
| Predict (`predict.py`) | whole-window features as above + X for ~130 M cells (6 features float64 6 GB, v2 11 features 11 GB, + a float32 copy inside sklearn) + one RF call; the heaviest step | strips of 512 rows, only cells of used counties, RF threads over trees (`--n-jobs` = cores), weights kept (1 GB) and scaled to county totals in a second pass (strips = whole window, tested); `--measure N` times N strips and writes nothing; maps at 1 km | ~8-12 GB | MA: 336 k cells x 1,000 trees in ~15 s on 8 threads ≈ 2.8 M cell-trees/s per thread; CONUS trees are deeper (~2,000 vs 126 training rows), assume ~1 M/s: 130 M cells x 1,000 trees ≈ 36 core-hours -> **~1-1.5 h per year on 32 threads** (half for 500 trees). v1 3 years + v2 2 years ≈ 5-8 h | float32 pop ~0.5 GB per year: ~2.5 GB | 32 cores, 8 h per version (set from the trial) | 0:45 / 9.7 GB / 32 (3 strips; whole 1960 pass 1 ≈ 3.6 min; dist_built 15.6 s) |
| Validate (`tract_validate.py`) | whole-window float64 arrays (prediction, model cells, baseline: 1.7 GB each), tract ids int32 0.86 GB, `np.unique` of (tract, zone) pairs over ~130 M cells | `--state-prefix ''` (all states), `--split` (train / test parts), coverage QA optional | ~12 GB | 2010: ~73 k tracts; **~5-10 min per year** | CSV only | 8 cores, 2 h | not run in the trial |

Compute cost of the pilot (3 years, v1 + v2): about 300 SU (prediction ~240), against 450,000 SU.
Outputs: `$HISDAC_SCRATCH/cutouts/conus` (~5-10 GB), `$HISDAC_SCRATCH/dasymetric/conus/Dasy_CONUS_RF_v{1,2}`
(~3 GB). Scratch is purged after 90 days: small results are copied to `results/`.

For all 12 years (later): cutout and water scale with the years (~2-3 h, ~11 GB of yearly water arrays in the
water job), prediction ~12-18 h per version (one job per few years, or raise the wall time).

## Trial result (1960, v1; jobs 34814376-34814382, code 563641b, run 2026-10-23)

Measured with `sacct` (`logs/conus_trial_sacct.txt`, `logs/conus_trial_seff.txt`). All seven jobs COMPLETED.

| Stage | Cores | Elapsed | Peak memory (MaxRSS) | vs the estimate above |
|---|---|---|---|---|
| census_conus (3 years) | 2 | 1 min | 1.8 GB | as expected; each `counties_{YEAR}.gpkg` is 196 MB |
| grid_cutout (1960: 12 rasters + zones) | 4 | 2 min | 8.0 GB | faster (sparse rasters, 6-8 s each); memory as estimated |
| water_frac (1960) | 16 | 15 min | 16.0 GB | as estimated (2,102 of 3,358 blocks) |
| place_dist (1960) | 8 | 3 min | 3.1 GB | as estimated |
| features v1 (1960) | 4 | 1 min | 10.0 GB | much faster (43 s for 23 strips); memory near the 15 GB of 4 cores |
| train v1 (1960) | 16 | 3.5 min | 4.1 GB | as estimated (search 18 s, SHAP 2.3 min) |
| predict v1 (1960, 3 strips, `--measure`) | 32 | 45 s | 9.7 GB | **~20x faster**: dist_built 15.6 s; RF 5.4 s for 5.0 M cells x 1,000 trees (max_depth 10) -> 1960 pass 1 ≈ 3.6 min |

Why the prediction estimate was far off: the chosen trees are shallow (`max_depth` 10) and 32 threads scale well
(~30 M cell-trees/s per thread, not ~1 M). Deeper trees (max_depth 20 / None) in other years can be several times
slower, still well under an hour per year.

Pilot resources set from this (`sbatch/submit_conus.sh`, 2026-10-24): wall times ~3-4x the measured time scaled to
3 years (cutout 30 min, water 1 h, distances 30 min, features 20 min on **6** cores (v2 reads 5 more layers), train
45 min, predict 1 h per version, validate 1.5 h: not measured yet); cores otherwise as in the trial.

Results of the trial (1960, v1; not the pilot): 3,109 zones, 3,093 used (16 `no_value`: 4 polygons without a CSV row,
La Paz, Cibola, Menominee, 9 Virginia independent cities), no county with 0 cells (cell-centre area ratio 0.98-1.02).
124.0 M cells in used counties, water mask 0.52 % of them. Split in 1960: 2,475 train / 618 test counties. CV RMSE
0.801 (R² 0.719), **test RMSE 0.778 (R² 0.738)**, best `n_estimators` 1000, `max_depth` 10, `min_samples_leaf` 2,
`max_features` 0.5. SHAP: Building 0.79 (bui 0.45, bldg_size 0.32), Land use, dist_built smaller. County-level
|rho| > 0.8 for most pairs (mu_ratio - res_share 0.985). Water QA: Quabbin and Lake Mead water in 1960, Lake Powell dry
in 1960 (ok). JRC no data = 2.0 % of the covered JRC pixels in the computed blocks (study-cell share is logged from
the pilot on: `study_jrc_nodata_mean`, `study_cells_jrc_nodata_gt50`).

## Pilot result (1920, 1960, 2010; v1 + v2; jobs 34918220-34918231, code b9b3dfa, run 2026-10-26)

All 12 jobs completed (first submission 34820550-34820561 failed at the cutout: BUI 2010 does not fit int32, now
float32). Wall time 3-19 min per job, peak memory 17 GB (water); mass check 0 fail in every county-year. JRC no data
inside study cells: 0 (no county), so `nodata_as_water` is safe on CONUS. Filled counties: Miami-Dade (all three
years), Shannon (1960, 2010; 1920 area ratio 0.46, allocation only), Broomfield and Bedford city (2010 only).

| | v1 1920 | v1 1960 | v2 1960 | v1 2010 | v2 2010 |
|---|---|---|---|---|---|
| County CV R2 (train) | 0.637 | 0.719 | 0.860 | 0.756 | 0.894 |
| County TEST R2 (622 counties) | 0.683 | 0.740 | 0.874 | 0.775 | 0.902 |
| Tract MdAPE, all (areal weighting) | 55.7 % (79.2) | **38.4 %** (82.7) | 41.6 % | **29.8 %** (74.5) | 40.2 % |
| Tract R2 of log density, all | -0.12 | 0.65 | 0.68 | **0.85** | 0.83 |
| Tract MdAPE, test counties | 67.3 % | 35.6 % | 39.9 % | 30.3 % | 41.0 % |

Tracts: 2,197 (1920, 9 % of the population), 22,042 (1960, 56 %), 72,243 (2010, all).

- v1 works on CONUS: tract error less than half of areal weighting in 1960 and 2010, and test counties score like
  train counties (no sign of overfitting with ~2,500 counties per year).
- v2 (PLURAL-1 distances) fits the county target much better (TEST R2 0.77 -> 0.90 in 2010) but allocates worse
  inside counties (tract MdAPE 29.8 -> 40.2 % in 2010). Distances explain how dense a county is (regional
  urbanisation), not where people live inside it; at cell level their smooth gradient pulls weight away from the
  buildings. Same direction as in Massachusetts (v4.1), now with enough counties to rule out overfitting.
- Consequence: county CV / TEST is not the criterion for choosing features; tract validation is. v1 is the CONUS
  base; distances are not used for allocation.
- SHAP (v1): bui > bldg_size > mu_ratio > rent_share > res_share / dist_built; in v2, d_10k and d_20k come second
  and fourth.
- 1920: tracts only in 14 large counties (9 % of the population) and R2 of log density below 0, so 1920 is weakly
  validated.

## v3 and v4: terrain (request 2026-10-27; run steps `docs/runbooks/Running_CONUS.md`, section 2)

| Topic | Decision |
|---|---|
| Versions | `Dasy_CONUS_RF_v3` = v1 + `elev`, `slope`; `Dasy_CONUS_RF_v4` = v1 + the five distances + `elev`, `slope`. 1960 and 2010 (as v2), same split and folds, `compare_with: Dasy_CONUS_RF_v1`. SHAP groups `Elevation`, `Slope` (separate, 2026-10-20) |
| Elevation | absolute (m). Elevation relative to the county mean is not used: its county mean is 0 for every county, so the county-level model can't learn anything from it |
| DEM layer | GMTED2010 `mn75_grd` (as Massachusetts v4), `resampling: average` onto the HISDAC grid, float32, cut into the pilot cutout with `grid_cutout.sh --layers DEM` (`layers/DEM/DEM.tif`; entry in `configs/conus_study_area.yaml`) |
| Sea / nodata | set to 0 m (as Massachusetts `common.py`), before the slope |
| Slope in strips | `common.terrain`: each `block_rows` strip is read with one extra row above and below, so `numpy.gradient` uses the same neighbours as on the whole window; the window's own first / last rows stay one-sided. Strips = whole window exactly (`tests/test_conus_dasymetric.py`, strips of 1, 7 and 512 rows); no whole-window DEM array in memory |
| Reused | pilot cutout, water (`{YEAR}_water_frac.tif`) and distances (`PLACEDIST`); nothing recomputed |

## BUI outliers (request 2026-10-27): look first, decide after

Pilot BUI maxima in one 250 m cell (62,500 m2): 306,635,538 (1920), 709,978,539 (1960), 5,447,140,510 (2010). Even a
cell built over 20 times its land area holds ~1.25e6 m2 (~1.35e7 sq ft), so the maxima are impossible in m2 or sq ft.
`src/grid/bui_qa.py` (`sbatch/bui_qa.sh`, in the v3v4 submission, nothing depends on it) writes per year
`results/cutout/conus/bui_quantiles.csv` (p50, p99, p99.9, p99.99, max over BUI > 0 cells; cells above 1e7, 3e7, 1e8)
and `bui_top.csv` (top 50 cells: lon/lat, county, state, BUI, BUPL, BUPR, bldg_size, BUI / median of the 8 neighbours,
county pop rank and density) and logs whether the top cells sit in the 50 most populous counties or elsewhere, and
how many are isolated spikes (> 100 x the neighbour median). It also prints the README / metadata files under
`$HISDAC_DIR` for the BUI unit (`docs/data_sources.md`). No treatment (cap, neighbour value) until the results are
reviewed.

## Tract density classes (request 2026-10-27)

`tract_validate.py` adds, per year and part, the subsets `dens_0_50`, `dens_50_500`, `dens_500_2000`,
`dens_2000_plus` (observed pop / (n_cells x 0.0625 km2), people per km2) to `metrics_by_year.csv`, with `area_share`
(tract area / evaluated tract area of the part); `n`, `pop_share`, `mae`, `mdape` as for the other subsets. The v1 and
v2 pilot validation is rerun to get them. Claude's check from the pilot `tract_errors_2010.csv` (MdAPE, tracts with
observed > 0): v1 / v2 = 35.2 / 49.8 % (< 50, 13,060 tracts), 29.2 / 39.4 % (50-500, 16,261), 25.4 / 35.6 %
(500-2000, 24,660), 34.2 / 43.8 % (2000+, 18,036): v1 better in every class, v2 worst in the rural class.

## County maps (request 2026-10-27)

`src/validation/county_maps.py` (`sbatch/county_maps.sh`, after v4): 2010, v1 / v2 / v4 people per cell, the tract
error of each and v2 - v1, v4 - v1, on BUI with county and tract boundaries and an arrow to the nearest PLURAL place
of 250k+ people; `county_maps.csv` gives per county and version the share of people on BUI = 0 cells and the
people-weighted distance to that place (lower in v2 = people moved towards the metro). Counties (picked by Claude
from the pilot `tract_errors_2010.csv`, 2026-10-27): county density < 25 people/km2, >= 4 tracts under 50 people/km2,
county mean `d_250k` (v2 `county_features.csv`) 60-150 km, largest rise of the median rural tract error v1 -> v2, one
per state: Chelan WA (`G5300070`, 7 rural tracts, 12 -> 106 %, 141 km), Reno KS (`G2001550`, 6, 67 -> 161 %, 73 km),
Fremont CO (`G0800430`, 5, 26 -> 105 %, 76 km), Macoupin IL (`G1701170`, 9, 42 -> 85 %, 76 km).

## v3 / v4 result (1960, 2010; jobs 34921582-34921594, code 84a2927, run 2026-10-26)

All jobs completed except `county_maps` (bug: `place_points` calls `crs.name` on a rasterio CRS).

Tract MdAPE (%), all tracts and by observed tract density (people / km2), and county TEST R2:

| Version | Year | All | <50 | 50-500 | 500-2000 | 2000+ | MAE | County TEST R2 |
|---|---|---|---|---|---|---|---|---|
| v1 base | 1960 | 38.4 | 119.6 | 55.4 | 31.0 | 36.3 | 2,167 | 0.740 |
| v2 + distances | 1960 | 41.6 | 178.0 | 56.8 | 34.5 | 39.8 | 2,368 | 0.874 |
| v3 + terrain | 1960 | **38.3** | 125.1 | 56.4 | **30.2** | **36.1** | **2,151** | 0.859 |
| v4 + both | 1960 | 40.3 | 167.2 | 55.6 | 33.3 | 38.2 | 2,292 | 0.892 |
| v1 base | 2010 | 29.8 | 35.2 | 29.2 | 25.4 | 34.2 | 1,693 | 0.775 |
| v2 + distances | 2010 | 40.2 | 49.8 | 39.4 | 35.6 | 43.8 | 2,249 | 0.902 |
| v3 + terrain | 2010 | **29.2** | **34.6** | **28.7** | **24.9** | **33.2** | **1,613** | 0.875 |
| v4 + both | 2010 | 39.8 | 49.6 | 39.5 | 35.4 | 42.9 | 2,186 | 0.913 |

- Terrain helps on CONUS: v3 is best on tracts in 2010 in every density class (MAE -5 %) and ties v1 in 1960,
  while raising county TEST R2 0.775 -> 0.875. `elev` is the second feature in SHAP (0.34 in 2010). In
  Massachusetts (14-22 counties) terrain overfit; with ~2,500 counties it does not.
- Distances keep hurting allocation with or without terrain (v4 ~ v2): the non-linear model does not turn them
  into a within-county signal. v1 + distances is dropped; v3 becomes the CONUS base, pending the BUI fix.
- 1960 tracts below 50 people / km2 are few and have very large errors in every version (120-178 %).
- County TEST R2 rises with every added feature while tract error does not follow it: features are chosen on tracts.

## Version comparison v1-v4 and likely reasons (summary, 2026-10-27)

| Version | County TEST R2 1960 / 2010 | Tract MdAPE 1960 / 2010 | Tract MAE 2010 | Verdict |
|---|---|---|---|---|
| v1 base | 0.740 / 0.775 | 38.4 / 29.8 % | 1,693 | reference |
| v2 + distances | 0.874 / 0.902 | 41.6 / 40.2 % | 2,249 | dropped |
| v3 + terrain | 0.859 / 0.875 | 38.3 / **29.2 %** | **1,613** | **CONUS base** |
| v4 + both | 0.892 / 0.913 | 40.3 / 39.8 % | 2,186 | dropped |

Areal weighting: 82.7 / 74.5 % (1960 / 2010). Density classes in "v3 / v4 result" above.

Likely reasons (interpretation, not tested separately):

1. **The model learns between counties and is applied within them.** Training rows are county means and the
   county total is known, so a feature helps only if its county-level relationship also holds inside a county.
   The county TEST R2 measures the first part only; the tract error measures what matters for allocation.
2. **Distances (v2, v4).** Distance to large places explains how dense a county is (regional urbanisation), hence
   the large R2 gain. Inside a county the distance surface is smooth and points toward the nearest city, so weight
   moves to empty land on the city side and away from towns elsewhere in the county. The largest losses are in
   rural tracts (2010 < 50 people / km2: 35.2 -> 49.8 %); single rural counties lose most (Chelan WA rural tracts
   12 -> 106 %, Reno KS 67 -> 161 %, Fremont CO 26 -> 105 %, Macoupin IL 42 -> 85 %). Adding terrain (v4) does not
   remove the effect, so the non-linear model does not turn distance into a within-county signal. The county maps
   meant to show this failed on a bug and are rerun. A relative distance (cell minus county mean) cannot be used:
   its county mean is always 0, so nothing can be learned at county level.
3. **Terrain (v3).** Elevation and slope vary strongly inside counties (valley floors vs hills and mountains) in the
   same direction as between counties (people live low and flat), so the county relationship transfers to cells.
   It improves every 2010 density class a little (MAE -5 %). In Massachusetts it overfit with 14-22 counties; with
   about 2,500 counties per year it does not (TEST R2 close to CV R2).
4. **Validation coverage.** 1960 tracts cover metropolitan areas only (22,042 tracts, 56 % of the population), and
   1920 only 8 large counties; rural allocation is checked only in 2010. The 1960 rural class (< 50 / km2) is small
   and has very large errors in every version.
5. **BUI outliers** (below) were in every version's input; their effect on these comparisons is unknown but the same
   for all versions. The base runs are repeated after the fix.

## BUI outliers (bui_qa, job 34921582)

Unit confirmed from `BUI_README.txt`: "indoor building gross area sum per pixel area in square feet". A 250 m cell is
672,700 sq ft; a very dense Manhattan cell (floor area about 20 x land) is about 1.3e7 sq ft. p99.99 of positive
cells is 6.9-8.1e6 (plausible). Cells above 3e7: 10 (1920), 119 (1960), 298 (2010); above 1e8: 3, 27, 86. Of the top
50 per year, 27-35 are more than 100 x their 3 x 3 neighbour median, and several have BUPL 0 or 2 (e.g. Ingham MI
1920: BUI 3.1e8 with 2 buildings; Carson TX 1920: two cells 8.8e7 with 0 BUPL, county pop 3,078). These are record
errors, not dense cores; they pull county population into single cells.

**Treatment (decided 2026-10-27, with the user):** a cell with BUI > 3e7 sq ft (about 45 x its land area, beyond any
real block) is a record error; its BUI is replaced by the median BUI of its 3 x 3 neighbours (the cell itself left
out). BUPL, BUPR and Land_Use are not changed. Applied in the cutout to every year, logged per year (cells replaced,
before / after values, top cells) and listed in a QA CSV. Affects 10 / 119 / 298 cells (1920 / 1960 / 2010) of
about 1.8 / 4.5 / 10.9 million built cells. The raw HISDAC files are not changed. Massachusetts runs are unchanged
(no cell above the cap there to check in the same QA).

## Implementation decisions (2026-10-23)

Made while implementing; each is the simplest option consistent with the decisions above.

| Topic | Decision |
|---|---|
| Config files | `configs/conus_study_area.yaml`, `configs/conus_rf_v1.yaml`, `configs/conus_rf_v2.yaml` (flat in `configs/`: model configs resolve paths from the repo root). Massachusetts files unchanged |
| Window | `window: full` = the whole HISDAC raster; zones are 2010 counties, the same `zone_id` in every year |
| Census input | `src/census/conus_counties.py` -> `$DATA_ROOT/processed/census_conus/counties_{YEAR}.gpkg` (2010 polygons sorted by GISJOIN; `pop` = CSV value). Status `ok` (pop > 0), `filled_nhgis` / `filled_nhgis_alloc` (2010 polygon without a CSV row, pop from NHGIS, area ratio within / outside 0.95-1.05; added 2026-10-24, see "Known input errors"), `no_value` (no value), `zero_pop` (0). `ok`, `filled_nhgis`, `filled_nhgis_alloc` are allocated; `ok` + `filled_nhgis` are trained on / scored; the others are NoData |
| Counties that can't be allocated | `unusable: skip`: a used county with 0 cells (cell-centre rasterization) or no unmasked cell is dropped with a warning and is NoData (Massachusetts still stops) |
| Per-year models | one era per year (`Y1920`, `Y1960`, `Y2010`); v2 lists `years: [1960, 2010]` (1920 = v1) |
| Split | `configs/conus_split.csv` (`src/dasymetric/make_split.py`, seed 42): the CSV's 3,105 CONUS counties, 2,483 train / 622 test; test = round(0.2 x n) per state, so DC (1 county) has no test county. Folds: train counties in random order, fold = position mod 5 (a GroupKFold with one county per group): 497/497/497/496/496. 2026-10-24: + the 4 counties without a CSV row as train (`--append-train`, existing rows unchanged) -> 3,109 counties, 2,487 train, folds 498/498/497/497/497 |
| Test score | `test_rmse`, `test_r2` in `metrics.json`, `test_predictions.csv`; v2 also scores v1's saved test predictions on the same rows |
| Jobs | the Massachusetts stage scripts with `CONFIG=` (and `CENSUS_DIR=`, `COVERAGE=`) passed by `sbatch/submit_conus.sh`, which also holds the CONUS resources |
| Tract validation | all states; metrics for `all`, `train`, `test` (part of the 2010 county the tract lies in); the totals QA by nominal county (`coverage_by_county`) is skipped, because the zones are 2010 counties |
| Layers not cut | FBUY, NobuiltYear (`age` dropped), NTL. DEM added 2026-10-27 for v3 / v4 |
| JRC no data | counted as water as in Massachusetts; checked only there (open sea). From the pilot on, `water_frac.py` logs the share inside study cells (`study_jrc_nodata_mean`, `study_cells_jrc_nodata_gt50` in `water_qa.csv`) and per county (`qa/water_jrc_nodata_by_county.csv`, top 20 in the log); decide from it before the full run |

## Order

1. Scale review of each stage (above) and a resource estimate per job (memory, time, disk). Done 2026-10-23.
2. Trial (1960 only, v1; prediction timed on 3 strips, nothing written): measures time and memory
   (`docs/runbooks/Running_CONUS.md`, step 0). Adjust the resources in `sbatch/submit_conus.sh` from it.
3. Pilot: CONUS cutout for 1920, 1960, 2010 + water mask + distances; census input on 2010 polygons; split
   table (`configs/conus_split.csv`, made 2026-10-23); per-year features, train (v1, v2), predict, tract validation.
4. Review time, memory and results. Done 2026-10-27: v3 chosen (above).
5. BUI fix in the cutout; rerun v3 for 1920, 1960, 2010 (1920 not run with terrain yet); county maps (bug fixed).
6. Then the remaining years (1900-2010) with v3, then 2020.
