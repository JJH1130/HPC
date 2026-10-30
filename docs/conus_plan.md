# CONUS plan: Dasy_CONUS_RF_v1

The Massachusetts pilot (v1-v4.1) is closed; the pipeline now moves to the conterminous US (48 states + DC).
This file is the plan for the first CONUS runs. Decisions are also in `docs/open_items.md` (decision log).

Last updated: 2026-10-30 (uncertainty filter code: exclusion sets t = 0.9 / 0.7 / 0.5 + fixed rules, u090 / u070 / u050, comparison + fixed selection rule); 2026-10-30 (record uncertainty without BUPR_contemp: ratio_A_nby from NobuiltYear); 2026-10-30 (metrics over time: county MdAPE + fixed tract sets, result 1900-2010; 2020 code; HISDAC record uncertainty code; map label fix); 2026-10-28 (external comparison code: GHS-POP, WorldPop, GPW v4.11, GRUMP v1, Fang & Jawitz vs v5.4 on tracts); 2026-10-28 (VIIRS-like NTL test code)

Run steps: `docs/runbooks/Running_CONUS.md`. Configs: `configs/conus_study_area.yaml`, `configs/conus_rf_v1.yaml`,
`configs/conus_rf_v2.yaml`, `configs/conus_rf_v3.yaml`, `configs/conus_rf_v4.yaml`, `configs/conus_rf_v1_bui.yaml`,
`configs/conus_rf_v3_bui.yaml`, `configs/conus_{rf,lgbm,xgb,cat}_v3_n60.yaml`, `configs/conus_rf_v3_all.yaml`,
`configs/conus_rf_v3_ntl.yaml`, `configs/conus_rf_v3_ntlv.yaml`, split `configs/conus_split.csv`.

## Version summary (for meetings; updated 2026-10-30)

Naming: CONUS = v5 series on HISDAC-US v2 (v6 = HISDAC-US v3, later). One RF per census year, county split 80 / 20 by
state (fixed), 60-candidate random search on county CV only. Tract MdAPE = all tracts of the year.

| Version | Folder | What | Tract MdAPE 1960 / 2010 | Status |
|---|---|---|---|---|
| v5 | `Dasy_CONUS_RF_v1` | MA v3.4 features (bui, bldg_size, mu_ratio, dist_built; res_share, rent_share from 1940) | 38.4 / 29.8 % | reference |
| v5.1 | `Dasy_CONUS_RF_v2` | + PLURAL-1 distances | 41.6 / 40.2 % | dropped |
| v5.2 | `Dasy_CONUS_RF_v3` | + elevation, slope | 38.3 / 29.2 % | kept |
| v5.3 | `Dasy_CONUS_RF_v4` | + distances + terrain | 40.3 / 39.8 % | dropped |
| v5.4 | `Dasy_CONUS_RF_v3_all` | v5.2 on BUI-fixed input, RF (vs LightGBM / XGBoost / CatBoost), 60 candidates, 1900-2020 | 37.9 / 26.6 % (2020: 26.1) | base |
| v5.5 | `Dasy_CONUS_RF_v3_ntl` / `_ntlv` | + night lights (DMSP / VIIRS-like), 2000 / 2010 | 2010: 31.0 / 36.2 % | dropped (helps only gap counties) |
| v5.6 | `Dasy_CONUS_RF_v3_u070` | v5.4 trained / tested without counties with >= 70 % records lacking a built year (+ record / area rules), those imputed | 36.0 / 23.8 % (2020: 23.7) | **chosen**, 6 years so far (+1940 / 1980) |
| v5.7 (test) | `Dasy_CONUS_RF_v3_u070_{plc,plcc,pq3,pq5,pe3,pe5}` | v5.6 + Siqiao's 900 m PLURAL grid (continuous / 3 or 5 classes), 1940 / 1980 / 2010 | 2010: 24.1-28.2 % (v5.6 23.8) | worse on tracts; drop proposed (user decides) |

Next (2026-10-30): PLURAL grid test done (section "PLURAL grid test result"): no variant beats v5.6 on tracts; PLURAL
dropped. v5.6 for all census years 1900-2020 written as code (section "v5.6 all years"), not run yet.
Supporting results: model family (RF best on tracts), external comparison (v5.4 beats Fang & Jawitz in every year;
GHS-POP / WorldPop use sub-tract inputs), county TEST MdAPE 27-33 % in every year, fixed tract sets, record uncertainty
(gap counties = counties without built years).

## Uncertainty filter result (jobs in `logs/conus_uncfilter_jobs.txt`, run 2026-10-30)

All jobs COMPLETED. Excluded counties (fixed set for all years): t = 0.9 / 0.7 / 0.5 -> 538 / 1,020 / 1,776 (ratio rule
519 / 1,011 / 1,772; records rule 3; area rule 36); population kept 2010: 94 / 91 / 80 %; all 416 gap counties
excluded at 0.7 and 0.5 (415 at 0.9). `results/validation/conus/uncertainty_filter/`.

Tract MdAPE (%):

| Year | v5.4 (no filter) | t = 0.9 | t = 0.7 | t = 0.5 | Areal weighting |
|---|---|---|---|---|---|
| 1920 | 53.3 | 52.6 | 52.4 | 52.9 | 79.2 |
| 1960 | 37.9 | 37.8 | 36.0 | 34.9 | 82.7 |
| 2010 | 26.6 | 26.1 | 23.8 | 23.7 | 74.5 |
| 2020 | 26.1 | 25.8 | 23.7 | 23.8 | 74.5 |

2010 split by the t = 0.7 sets: kept counties 25.0 -> 22.4 %, excluded (imputed) counties 55.7 -> 51.2 %; gap-county
tracts 72.0 -> 77.5 % (areal weighting 75.6 %).

- County level: common TEST counties slightly better with filters (2010 23.8 -> 22.6 % at 0.7); county totals of the
  excluded counties much worse (51 -> 89-94 %): the filtered model reads their thin records as few people. Allocation
  uses only relative weights inside a county and the census sets the total, so this does not reach the product.
- The pre-set rule (mean of (a) and (b)) picked v5.4; it was ill-posed because (b) scores county totals before
  allocation. **Decision 2026-10-30: t = 0.7** (tracts ~ t = 0.5, keeps 91 % vs 80 % of the population), chosen on
  tract validation among 4 candidates, stated openly; all thresholds reported as a sensitivity.
- Next: u070 for all years 1900-2020 (= v5.6).

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
| `Dasy_CONUS_RF_v3_ntl` | v3 + ntl (2000 / 2010 only) | v3 (E3), dropped in v3.2 on 14 counties | run 2026-10-28 ("NTL test result") |
| `Dasy_CONUS_RF_v3_ntlv` | v3 + ntlv (VIIRS-like NTL, 2000 / 2010 only) | - | code 2026-10-28 ("VIIRS-like NTL test") |

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
2. **Distances (v2, v4).** Distance to places explains how dense a county is (regional urbanisation), hence
   the large R2 gain. Inside a county the distance surface is smooth (rings around the nearest small places), so
   weight spreads onto empty land around them (confirmed by the county maps, "BUI fix + v1_bui / v3_bui result"). The largest losses are in
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

## BUI fix + v1_bui / v3_bui result (jobs 34926193-34926203, code fe4804c, run 2026-10-26)

All 11 jobs completed. BUI cap 3e7 sq ft: 10 / 119 / 298 cells replaced (1920 / 1960 / 2010; 2 / 10 / 74 of them set
to 0 because all neighbours were 0); they held 2.6 / 9.0 / 10.6 % of all BUI. Massachusetts: 0 cells above the cap.

| Version | Tract MdAPE 1920 / 1960 / 2010 | MAE 2010 | 2010 test counties | County TEST R2 2010 |
|---|---|---|---|---|
| v1 | 55.7 / 38.4 / 29.8 % | 1,693 | 30.3 % | 0.775 |
| v1_bui | 55.1 / 38.3 / 29.7 % | 1,683 | 30.4 % | 0.776 |
| v3 | - / 38.3 / 29.2 % | 1,613 | 29.4 % | 0.875 |
| **v3_bui** | **53.7 / 38.2 / 25.2 %** | **1,464** | **26.0 %** | 0.875 |

2010 by tract density (people / km2), MdAPE: v3_bui 28.2 (<50), 23.7 (50-500), 21.5 (500-2000), 30.4 (2000+) vs v1
35.2 / 29.2 / 25.4 / 34.2.

- The BUI fix alone changes little: v1 -> v1_bui and v3 -> v3_bui in 1960 move by 0.1 point (same hyperparameters).
- **The 2010 gain of v3_bui (29.2 -> 25.2 %) comes with a different hyperparameter choice**: the search picked
  `max_features: 1.0` (v3 picked 0.5), a CV difference of 0.0007 RMSE (0.8647 vs 0.8644 R2), essentially a tie on
  county CV. With 1.0, SHAP puts `bui` far ahead (0.98) and `bldg_size` drops (0.25 -> 0.07). So the gain is real on
  tracts (train and test counties alike: 25.0 / 26.0 %) but was not chosen for it: county CV cannot tell these
  settings apart, while tract error differs by 4 points (expected: different scale; tracts are not used for tuning,
  `docs/open_items.md`).
- v3_bui is the CONUS base (best in every year and density class).

County maps (2010; `results/validation/conus/county_maps/`), share of the county population put on cells with BUI = 0:

| County | v1_bui | v2 | v3_bui | v4 |
|---|---|---|---|---|
| Chelan WA | 44 % | 68 % | 18 % | 56 % |
| Fremont CO | 45 % | 68 % | 4 % | 48 % |
| Reno KS | 25 % | 51 % | 6 % | 42 % |
| Macoupin IL | 95 % | 99 % | 96 % | 99 % |

- Distances spread people onto empty cells: v2 puts 51-68 % of the population on cells without buildings, against
  25-45 % for v1. The maps show smooth rings around the nearest small places (d_10k, d_20k lead the v2 SHAP), not a
  shift toward the large metro (population-weighted distance to it changes by 1-8 km). The earlier reading ("toward the
  city") is replaced by this one.
- Terrain does the opposite: v3_bui follows valley floors and rivers and puts only 4-18 % on empty cells.
- v1 itself puts 25-45 % on empty cells: exp(y_hat) is positive everywhere, and in large rural counties the many
  empty cells add up. Terrain is what limits this.
- Macoupin IL: 95-99 % on empty cells in every version, so its BUI is nearly empty: a likely gap in the source
  records (ZTRAX coverage) for that county. Counted 2026-10-27: 416 counties (4.7 % of the population) in
  2010 have BUI per person below 5 % of the median (`docs/open_items.md`).

## All census years (request 2026-10-27; run steps `docs/runbooks/Running_CONUS.md`, section 5)

The model chosen by the family comparison (RF, v3 features, 60 candidates; "Model family result") for every census
year of Stefan's CSV. Request: `docs/handoff/conus_all_years_request.md`.

| Topic | Decision |
|---|---|
| Version | `Dasy_CONUS_RF_v3_all` (`configs/conus_rf_v3_all.yaml`): `conus_rf_v3_n60.yaml` with years 1900-2010 (12), one era per year (own search + fit). 1900-1930 without res_share / rent_share (Land_Use from 1940), as Y1920. 2020 later: the CSV ends in 2010, so 2020 needs another county input |
| Study area | `configs/conus_study_area.yaml` years `{start: 1900, stop: 2010, step: 10}`. Configs with their own `years:` keep theirs; `conus_rf_v1.yaml` / `conus_rf_v1_bui.yaml` got `years: [1920, 1960, 2010]` (they had none). The `pilot` mode of `submit_conus.sh` would now cut / water all 12 years (history only) |
| Inputs | census input for all 12 years (cheap; 1920 / 1960 / 2010 rewritten the same). Cutout and BUI fix only for the 9 new years (`--years`; the fixed 1920 / 1960 / 2010 BUI is never re-cut; `cutout_qa.csv` / `bui_fix_summary.csv` keep the other years' rows; a static layer already in the cutout, DEM, is kept). Water for all 12 years: the QA points are for 1920 / 1960 / 2010 and stay as they are, and the GDW layers are deterministic, so the 3 old ones come out the same. No place_dist (v3 has no distances) |
| Features / train / predict | recomputed for all 12 years in the new version (the 3 old years too: they are the reproducibility check). One job per stage (simplest), longer wall times: features 1 h, train 5 h, predict 3 h, validate 2 h |
| Reproducibility | `compare_with: Dasy_CONUS_RF_v3_n60`: train.py compares 1920 / 1960 / 2010 on the same folds (eras that v3_n60 lacks are skipped with a log line). `compare_models.py --repro-with Dasy_CONUS_RF_v3_n60` logs one line per shared year: hyperparameters, CV RMSE, tract MdAPE the same or not (column `repro_Dasy_CONUS_RF_v3_n60`). Same seed, features and folds -> they must be the same; a difference is investigated, not ignored |
| Validation | tracts 1910-2010 (none in 1900): split parts, density classes, `--gap-share 0.05`, areal weighting |
| Summary | `results/validation/conus/Dasy_CONUS_RF_v3_all/summary_by_year.csv` (`compare_models.py`, one version x 12 years: CV RMSE / R2, TEST R2, chosen hyperparameters, tract count and counties with tracts (`tract_counties`), MdAPE all / test / no_gap / density classes, baseline MdAPE, gap counties, mass check per year `mass_fail`) and `mdape_by_year.png` (tract MdAPE by year: model, model without gap counties, areal weighting; below: counties with tracts). Population maps per year from predict (`maps.years` = all 12) |
| Mass check | predict logs `mass check by year`; the summary repeats it per year from `reallocation_qa.csv` |

## Model family result (jobs 34932548-34932563, code 7abfaf6, run 2026-10-27)

All 16 jobs COMPLETED. v3_bui features, same split and folds, RandomizedSearchCV with 60 candidates per model and
continuous ranges (`configs/conus_{rf,lgbm,xgb,cat}_v3_n60.yaml`); `RF_v3_bui` = the earlier RF with 20 candidates.
Table: `results/validation/conus/model_comparison.csv`.

| Year | Version | CV RMSE | TEST R2 | Tract MdAPE all | train / test part | no gap counties | dens < 50 | dens 2000+ |
|---|---|---|---|---|---|---|---|---|
| 1920 | RF n60 | 0.576 | 0.834 | **53.3** | 53.1 / 65.4 | 53.3 | 141 | 50.1 |
| 1920 | RF 20 | 0.576 | 0.837 | 53.7 | 53.2 / 65.7 | 53.7 | 156 | 50.4 |
| 1920 | XGB | 0.583 | 0.836 | 55.1 | 54.4 / 72.0 | 55.1 | 211 | 51.0 |
| 1920 | LGBM | 0.588 | 0.828 | 56.9 | 56.4 / 70.0 | 56.9 | 299 | 52.6 |
| 1920 | CatBoost | 0.578 | 0.836 | 54.3 | 53.6 / 74.1 | 54.3 | 364 | 50.9 |
| 1960 | RF n60 | 0.600 | 0.861 | **37.9** | 38.8 / 34.6 | 37.1 | 127 | 35.8 |
| 1960 | RF 20 | 0.601 | 0.861 | 38.2 | 39.1 / 34.9 | 37.4 | 128 | 36.1 |
| 1960 | XGB | 0.600 | 0.855 | 38.1 | 39.0 / 34.7 | 37.3 | 116 | 36.9 |
| 1960 | LGBM | 0.610 | 0.854 | 39.0 | 39.5 / 37.0 | 38.2 | 95 | 38.3 |
| 1960 | CatBoost | 0.594 | 0.856 | 38.7 | 39.6 / 34.9 | 38.0 | 128 | 37.1 |
| 2010 | RF n60 | 0.626 | 0.878 | 26.6 | 26.4 / 27.4 | 25.6 | 30.7 | 31.7 |
| 2010 | RF 20 | 0.630 | 0.875 | **25.2** | 25.0 / 26.0 | 24.1 | 28.2 | 30.4 |
| 2010 | XGB | 0.625 | 0.879 | 27.2 | 27.0 / 28.0 | 26.1 | 31.0 | 32.8 |
| 2010 | LGBM | 0.618 | 0.877 | 28.1 | 27.9 / 28.7 | 27.0 | 30.4 | 35.0 |
| 2010 | CatBoost | 0.612 | 0.882 | 35.6 | 35.5 / 36.3 | 34.6 | 43.1 | 39.2 |

Areal-weighting baseline: 79.2 / 82.7 / 74.5 %. Tracts in gap counties: ~90 % (1960) and ~72 % (2010) for every model.

- **County level the four are a tie** (CV RMSE within 0.01-0.02, TEST R2 within 0.01). **On tracts RF is best or tied
  in every year**; the boosting models lose most in 2010 and in sparse tracts (1920 density < 50: RF 141 %, CatBoost
  364 %).
- 2010: lower county CV RMSE goes with *higher* tract error (CatBoost 0.612 -> 35.6 %, LGBM 0.618 -> 28.1 %, XGB 0.625
  -> 27.2 %, RF 0.626 -> 26.6 %, RF 20 0.630 -> 25.2 %). Likely reason (not tested): the model is fit on county means
  and applied to cells, whose feature values are far more extreme; finer county-level fits (boosting, deeper RF)
  transfer worse to cells (change of support). RF averages bounded leaf means and extrapolates least.
- 1920 tracts cover 10 counties only (New York City boroughs, Chicago, Detroit, Pittsburgh, Cleveland, Milwaukee, ...;
  4 more with 1 tract), so 1920 compares big cities; the test part is a few counties.
- Ranges: chosen values mostly inside the ranges; near an edge: learning rate near the lower bound 0.01 (XGB 2010
  0.011), XGB 2010 `reg_lambda` 7.1 (upper 10), RF `min_samples_leaf` 1 (lower bound) and `max_depth` none / 30.
  `tract r2_log` (log1p of tract counts) is negative for all and not informative (tracts have similar populations);
  MdAPE and density classes are used.
- **Decision: RF** (see `docs/open_items.md`). Hyperparameters stay those chosen by county CV with 60 candidates
  (`RF_v3_n60`); the 20-candidate run is better on 2010 tracts but choosing it for that would tune on tracts.

## All census years result (jobs 34939345-34939353, run 2026-10-27)

`Dasy_CONUS_RF_v3_all`: RF, v3 features, 60 candidates, one model per year (12 models), same split and folds. All 9
jobs COMPLETED; wall time ~3.6 h (train 1:37, predict 0:47, features 0:16, water 0:14, validate 0:12, cutout 0:10).
1920 / 1960 / 2010 reproduce `RF_v3_n60` exactly (same hyperparameters, CV RMSE, tract MdAPE); mass check: 0
county-years fail. Table `results/validation/conus/Dasy_CONUS_RF_v3_all/summary_by_year.csv`, figure `mdape_by_year.png`.

| Year | Train counties | CV R2 | TEST R2 | Tract counties | Tracts | MdAPE all | test part | no gap | areal weighting |
|---|---|---|---|---|---|---|---|---|---|
| 1900 | 2,238 | 0.815 | 0.845 | 0 | - | - | - | - | - |
| 1910 | 2,344 | 0.812 | 0.822 | 10 | 1,897 | 53.2 | 72.1 | 53.2 | 82.9 |
| 1920 | 2,443 | 0.823 | 0.834 | 8 | 2,197 | 53.3 | 65.4 | 53.3 | 79.2 |
| 1930 | 2,471 | 0.815 | 0.839 | 24 | 6,362 | 49.7 | 50.5 | 49.7 | 81.5 |
| 1940 | 2,471 | 0.827 | 0.858 | 74 | 7,350 | 42.6 | 39.8 | 42.6 | 86.9 |
| 1950 | 2,474 | 0.832 | 0.856 | 114 | 12,300 | 41.8 | 37.4 | 41.5 | 83.1 |
| 1960 | 2,477 | 0.843 | 0.861 | 295 | 22,042 | 37.9 | 34.6 | 37.1 | 82.7 |
| 1970 | 2,483 | 0.853 | 0.863 | 607 | 33,298 | 34.0 | 32.9 | 33.2 | 81.3 |
| 1980 | 2,484 | 0.857 | 0.861 | 1,772 | 44,586 | 32.3 | 31.4 | 31.2 | 79.9 |
| 1990 | 2,486 | 0.860 | 0.876 | 3,016 | 57,338 | 28.5 | 28.3 | 27.3 | 76.9 |
| 2000 | 2,486 | 0.863 | 0.875 | 3,007 | 62,380 | 27.2 | 27.4 | 26.1 | 75.9 |
| 2010 | 2,487 | 0.866 | 0.878 | 3,109 | 72,243 | 26.6 | 27.4 | 25.6 | 74.5 |

- Every year beats areal weighting by 30-50 points. Tract error falls over time, but the tract set changes (big
  cities only before 1940, nationwide from 1990), so years are not directly comparable; 1910-1930 are a few big
  cities and their test part is a handful of counties.
- No tracts in gap counties before 1950; from 1950 the gap-county tracts stay near or above areal weighting (72-90 %).
- Density class < 50 people/km2 is not meaningful before ~1980: it is mostly tiny tracts (median 3-9 cells) with
  population 0 or near 0 (1910: 22 tracts, MdAPE 9,228 %).
- Hyperparameters repeat across years (same 60 candidates every year, random_state 42): `max_features` 0.5 / 0.75,
  `min_samples_leaf` 1-2, depth 20 / 30 / none.

## NTL test (request 2026-10-28; run steps `docs/runbooks/Running_CONUS.md`, section 6)

Massachusetts dropped `ntl` in v3.2 with 14 counties per year: too few to see an effect (tract error unchanged, county
CV slightly worse; `docs/dasymetric_v3_2.md`). CONUS has ~2,500 counties per year. Features stay era-specific (the
original plan: before 1940 no Land_Use, from 2000 NTL; harmonized DMSP/VIIRS exists from 1992), so NTL can only
enter 2000 / 2010 (2020 with the 2020 step). Request: `docs/handoff/conus_ntl_request.md`.

| Topic | Decision |
|---|---|
| Layer | `NTL` in `configs/conus_study_area.yaml` = the Massachusetts definition (`Harmonized_DN_NTL_{YEAR}_*.tif`, 30 arc-seconds, DN 0-63, nearest, int16), years [2000, 2010]. Cut into the existing cutout with `grid_cutout.sh --layers NTL` (nothing else re-cut; the window must match `window.json`) |
| Version | `Dasy_CONUS_RF_v3_ntl` (`configs/conus_rf_v3_ntl.yaml`): v3_all's model, search space, 60 candidates, split, statuses, water mask, `block_rows`; eras Y2000 / Y2010 = v3_all's features + `ntl`; feature group `Night lights: [ntl]`; `compare_with: Dasy_CONUS_RF_v3_all` (same split -> same folds, CV and TEST on the same rows). `tests/test_conus_dasymetric.py` checks that the config differs from v3_all only by `ntl` and the years |
| Feature | `ntl` = mean DN over the county's unmasked cells (as Massachusetts v3). NTL nodata inside a used county stops the job (`read_layer`, no silent 0); outside the used counties it is ignored. The CONUS window lies inside the global NTL raster, so none is expected; `ntl_qa` counts zone cells with nodata |
| QA | `src/grid/ntl_qa.py` on the CONUS cutout (`CONFIG=` override of `sbatch/ntl_qa.sh`): DN range, Boston box (the fixed DN >= 60 rule, unchanged; its 2010 failure is a known rule artifact, change on hold), NTL-BUI Spearman, plus new edge lines (logged only): lit / bright cells outside every county (sea, Canada, Mexico), "glow" cells (BUI = 0, DN >= 30) within 5 km of the county edge (coast, border, Great Lakes) vs the interior, mean DN on BUI = 0 cells, top 15 counties by edge glow (`ntl_glow_counties.csv`). The box now uses row / column ranges (no whole-window coordinate grids; same cells). Nothing waits for the QA job |
| Validation | tracts 2000 / 2010: split parts, density classes, `--gap-share 0.05` (as v3_all) |
| Comparison | `compare_models.py --versions Dasy_CONUS_RF_v3_all Dasy_CONUS_RF_v3_ntl --years 2000 2010 --rank-features ntl` -> `results/validation/conus/ntl_comparison.csv`: CV RMSE, TEST R2, tract MdAPE all / test / no_gap / density classes, chosen hyperparameters, and ntl's rank (1 = first) by permutation importance and mean abs SHAP with the values (`ntl_perm_rank`, `ntl_shap_rank`, `n_features`) |
| County maps | 2010, Chelan WA / Reno KS / Fremont CO / Macoupin IL, v3_all vs v3_ntl -> `results/validation/conus/county_maps_ntl/` (own folder: the model family maps stay); `county_maps.csv` has the share of people on BUI = 0 cells |
| Decision rule | not fixed in advance; read with the user: tract MdAPE (all, test, no_gap, density classes) first, county TEST R2 second, as for the model family |

## NTL test result (jobs 34956826-34956833, run 2026-10-28)

All jobs COMPLETED except `ntl_qa` (fails only on the DN >= 60 box rule, on hold since 2026-10-06). NTL in study
counties: no nodata; Spearman ntl ~ bui 0.40 (2010); glow (BUI = 0, DN >= 30) on 9.9 % of cells within 5 km of the
coast / border vs 2.8 % inland. Same hyperparameters as v3_all in both years. `results/validation/conus/ntl_comparison.csv`.

| Year | Version | CV R2 | TEST R2 | Tract MdAPE all | test part | < 50 | 50-500 | 500-2000 | 2000+ |
|---|---|---|---|---|---|---|---|---|---|
| 2000 | v3_all | 0.863 | 0.875 | **27.2** | 27.4 | 29.4 | 27.4 | 23.1 | 31.2 |
| 2000 | v3_ntl | 0.963 | 0.955 | 32.8 | 32.4 | 27.4 | 38.0 | 27.5 | 39.6 |
| 2010 | v3_all | 0.866 | 0.878 | **26.6** | 27.4 | 30.7 | 25.4 | 22.5 | 31.7 |
| 2010 | v3_ntl | 0.958 | 0.952 | 31.0 | 31.1 | 27.7 | 33.6 | 26.1 | 38.2 |

Share of the county population on BUI = 0 cells (2010, `county_maps_ntl/`): Chelan 15 -> 41 %, Reno 7 -> 21 %,
Fremont 5 -> 36 %, Macoupin 96 -> 99 %.

- ntl is the top feature (permutation and SHAP rank 1) and explains county density very well (CV R2 +0.10), but
  allocation inside counties gets worse except in the sparsest tracts: the same pattern as the PLURAL distances (v2).
- Likely reason: the lights are ~1 km and bloom over unbuilt land around towns, so within a county the weight spreads
  onto empty cells; between counties total brightness tracks total population, hence the county gain.
- **Split by BUI gap counties it reverses** (tract MdAPE): gap counties 75.7 -> 39.0 % (2000) and 72.0 -> 35.1 % (2010),
  other counties 26.1 -> 32.5 % and 25.6 -> 30.8 %. Where HISDAC records are missing, the lights show the settlements
  (the user's reading: lit cells without BUI point to missing / not surviving records, not to empty land); where the
  records are complete, the DMSP glow spreads people onto empty land.
- Decision (2026-10-28, with the user): ntl not dropped. Test a less-blooming NTL product: VIIRS-like NTL (Chen et al.
  2021, 2000-2018, 15 arc-sec) for 2000 / 2010 (`docs/handoff/conus_ntl_viirs_request.md`); EOG VIIRS for 2020 later.

## VIIRS-like NTL test (request 2026-10-28; run steps `docs/runbooks/Running_CONUS.md`, section 7)

Does a less blooming night-light product keep the gain in BUI gap counties (DMSP `ntl`, 2010: 72.0 -> 35.1 %) and
lose less elsewhere (25.6 -> 30.8 %)? Request: `docs/handoff/conus_ntl_viirs_request.md`. Data: Chen et al. (2021),
NPP-VIIRS-like NTL (`docs/data_sources.md`).

| Topic | Decision |
|---|---|
| Product version | **Version1** (the 2021 paper, as requested). The Dataverse record now also has a Version2 (Chen et al. 2026, 1992-2025, super-resolution, updated 12/2025); not used here, can be tested the same way (`VERSION=2 bash sbatch/ntlv_download.sh` -> `viirs_like/v2/`) |
| Download | `sbatch/ntlv_download.sh` (login node): file ids + md5 from the Dataverse API (fallback: the values recorded 2026-10-28), md5 checked, unpacked flat into `$DATA_ROOT/raw/ntl/viirs_like/v1/{2000,2010}/` (exactly one `.tif` each). Laptop + OnDemand / `scp` to `dtn.rc.colorado.edu` if the cluster cannot reach Dataverse |
| Check before the cutout | `src/grid/ntlv_check.py` (`sbatch/ntlv_check.sh`): CRS, cell size, dtype, nodata tag, bounds, coverage of the CONUS window (as a lon/lat box from `window.json`), over that box nodata / negative / zero / lit counts and lit quantiles, values at fixed sea / lake / dark / city points (how the sea mask is stored) -> `results/cutout/conus/ntlv_check.csv`. Fails on a non-geographic CRS, missing coverage, negative values or no light |
| Layer | `NTLV` in `configs/conus_study_area.yaml`: `viirs_like/v1/{YEAR}/*.tif`, years [2000, 2010], float32 (radiance), **nearest** as NTL: the 250 m cells are smaller than the ~460 x 350 m source pixels, so each takes the pixel it lies in; `average` would give nearly the same, `bilinear` would smear light onto neighbouring cells, against the point of the test |
| Sea mask | `nodata_to: 0` (new `make_cutout.py` key): the producers removed the sea with a land mask; if it is stored as nodata, a coastal county cell whose centre falls on a masked pixel would stop the features (NTL rule: nodata in a used county stops the job). Masked sea = no light, so it is written as 0, counted in the cutout log (cells inside the counties). NTL (DMSP) keeps the stop rule |
| Version | `Dasy_CONUS_RF_v3_ntlv` (`configs/conus_rf_v3_ntlv.yaml`) = `conus_rf_v3_ntl.yaml` with `ntlv` (layer NTLV) instead of `ntl`; same split / folds / search space / 60 candidates; `compare_with: Dasy_CONUS_RF_v3_all`. The test checks that only the feature differs |
| QA | `ntl_qa.py --layer NTL NTLV` (one job): per layer `ntl_qa.csv` / `ntlv_qa.csv` + glow counties, and `ntl_edges_compare.csv` side by side. DMSP keeps its rules (DN 0-63, DN >= 60 box, on hold). VIIRS-like (radiance, no 0-63 scale): fails only on negative values; box "bright" = p99 of the lit zone cells (warning if none); glow = BUI 0 and >= 10 nW (logged only, not calibrated to DN 30). Scale-free edge lines for both: lit share of BUI = 0 cells (edge 5 km vs interior) and mean value on BUI = 0 cells / mean on built cells |
| Comparison | `compare_models.py --versions Dasy_CONUS_RF_v3_all Dasy_CONUS_RF_v3_ntl Dasy_CONUS_RF_v3_ntlv --years 2000 2010 --rank-features ntl ntlv` -> `results/validation/conus/ntl_viirs_comparison.csv`; the log adds a table of tract MdAPE all / test / no_gap / gap / density classes side by side |
| County maps | 2010, Chelan WA, Reno KS, Fremont CO, Macoupin IL (BUI gap), DuPage IL (BUI gap, G1700430); v3_all / v3_ntl / v3_ntlv -> `results/validation/conus/county_maps_ntlv/` (own folder) with the share of people on BUI = 0 cells |
| Decision rule | not fixed in advance: gap vs no_gap tract MdAPE first (does ntlv keep the gap gain and lose less elsewhere?), density classes, county TEST R2 second |

## VIIRS-like NTL test result (jobs 34961482-34961489, run 2026-10-28)

`Dasy_CONUS_RF_v3_ntlv` = v3_all + `ntlv` (VIIRS-like NTL, Chen et al. 2021, 16 arc-sec, sea -> 0), 2000 / 2010. All
jobs COMPLETED except `ntl_qa` (DMSP box rule). Far less glow than DMSP: lit share of BUI = 0 cells within 5 km of the
coast / border 0.11-0.12 vs 0.58-0.59 (DMSP); 96-97 % of window cells are 0. Table `ntl_viirs_comparison.csv`.

| Year | Version | Tract MdAPE all | gap counties | other counties | < 50 | 50-500 | 500-2000 | 2000+ |
|---|---|---|---|---|---|---|---|---|
| 2000 | v3_all | **27.2** | 75.7 | **26.1** | 29.4 | **27.4** | **23.1** | **31.2** |
| 2000 | + DMSP ntl | 32.8 | **39.0** | 32.5 | **27.4** | 38.0 | 27.5 | 39.6 |
| 2000 | + VIIRS-like ntlv | 35.0 | 40.4 | 34.8 | 33.9 | 42.9 | 30.2 | 37.0 |
| 2010 | v3_all | **26.6** | 72.0 | **25.6** | 30.7 | **25.4** | **22.5** | **31.7** |
| 2010 | + DMSP ntl | 31.0 | **35.1** | 30.8 | **27.7** | 33.6 | 26.1 | 38.2 |
| 2010 | + VIIRS-like ntlv | 36.2 | 38.6 | 36.0 | 35.3 | 44.1 | 31.6 | 37.8 |

Share on BUI = 0 cells (2010): Chelan 15 / 41 / 29 %, Reno 7 / 21 / 16 %, Fremont 5 / 36 / 37 % (v3 / DMSP / VIIRS-like).

- Less glow did not help: VIIRS-like is worse than DMSP outside gap counties and slightly worse inside them. So the
  loss is not (only) blooming: night light is the top feature for county density (rank 1), and inside a county its
  coarse, peaked pattern (lit cores, zero elsewhere) concentrates people in lit cells and empty land near them.
- Night light helps only where HISDAC records are missing (gap counties 72 -> 35-39 %).
- Rejected (2026-10-28, user): using the night-light model only in gap counties. That model learned its relationships
  mostly from complete counties, so applying it to one group of counties picks a model by region after the fact.
- Mean APE (tracts >= 10 people, 2010): v3 54.0 %, + DMSP 79.7 %, + VIIRS-like 87.0 % (areal weighting 273.5 %); gap
  counties 94.1 / 49.3 / 55.0 %, others 51.8 / 81.4 / 88.8 %. Night light raises the mean much more than the median
  (a few tracts get very large overestimates), while the 90th percentile APE drops a little with DMSP (83.1 -> 77.2 %).

## External comparison (request 2026-10-28; run steps `docs/runbooks/Running_CONUS.md`, section 8)

Where does v5.4 (= `Dasy_CONUS_RF_v3_all`: RF, v3 features, 60 candidates) stand next to published population grids,
on the same tracts and with the same metrics? Request: `docs/handoff/external_grids_request.md`. Version names: CONUS =
v5 series (`docs/open_items.md`, 2026-10-28). Products, years and paths: `configs/external_grids.yaml`; sources,
licenses, US input units: `docs/data_sources.md` ("External gridded population products").

| Product | Years (with US tracts) | Grid / CRS | US input unit (Details in data_sources.md) |
|---|---|---|---|
| GHS-POP R2023A | 1980, 1990, 2000, 2010 | 100 m, Mollweide | GPWv4.11 units (US level unverified); 1980 / 1990 extrapolated, not that year's census |
| WorldPop USA, unconstrained | 2000, 2010 | 3 arc-sec, WGS84 | unverified (CIESIN / GPWv4 units) |
| GPW v4.11 count | 2000, 2010 | 30 arc-sec, WGS84 | unverified (2010-round units; printed by the inventory once the country summary is downloaded) |
| GRUMP v1 count | 1990, 2000 | 30 arc-sec, WGS84 | unverified (GPWv3 units) |
| Fang & Jawitz 2018, M3 and M5 | 1910-2010 without 1960 | 1 km, ESRI:102003 | **county** (as ours); M3-M5 also use 2000 tracts (low-population mask, calibration) |

| Topic | Decision |
|---|---|
| Aggregation | each product's pixel population is summed per tract **in the product's own CRS**: the tract polygons are reprojected (vector only), the raster is not reprojected or resampled. exactextract: each pixel x the share of its area inside the tract (partial pixels exact; tested against a brute-force polygon intersection). Our own numbers are not recomputed this way: v5.4 and areal weighting come from `tract_errors_{YEAR}.csv` (250 m cells by cell centre, as in every tract validation so far) |
| Tracts | the tracts evaluated for v5.4 that year (`flag == ok` in its `tract_errors_{YEAR}.csv`: same tract files, same filter), of those only the tracts the product covers completely without nodata: tract inside the raster (pixel coverage = tract area), no nodata pixel touched (`--max-nodata-share 0`, as requested), no negative pixel. Coastal tracts that reach over a sea masked as nodata drop out; the log gives how many and their population share. Allowing some nodata share needs only `evaluate` again (the sums keep the nodata coverage) |
| Fair subsets | per product and year, v5.4 and areal weighting are recomputed on exactly that product's tracts (three rows: product, `Dasy_CONUS_RF_v3_all`, `areal_weighting`); rows `all_tracts` = v5.4 and areal weighting on all evaluated tracts (the usual numbers) |
| Metrics | MdAPE (tracts with observed pop > 0, as `tract_validate.py`), MAPE (tracts >= 10 people), p90 APE, total ratio (sum predicted / sum observed), MdAPE per observed density class (people per km2 over the tract's 250 m cells, the same 4 classes), MdAPE in / outside BUI gap counties (the `gap` column of v5.4), tract count, share of the evaluated tracts and of their population, tracts left out (outside / nodata) |
| Outputs | `results/validation/conus/external/external_comparison.csv` (year x product x method, with `input_unit` + its source URL), `external_mdape_by_year.png` (v5.4 and areal weighting on all tracts as lines, each product on its tracts), `external_inventory.csv` (files, CRS, cell size, nodata). Tract sums on scratch only (`$HISDAC_SCRATCH/external/conus/sums/`) |
| Download | `sbatch/external_download.sh` (login node, as `ntlv_download.sh`): GHS-POP from JRC's AWS bucket (the JRC FTP did not answer 2026-10-28; same R2023A V1-0 files, uncompressed GeoTIFF), 100 m Mollweide (preferred over 3 arc-sec: half the size); size checks from the listings of 2026-10-28; F&J md5 from figshare; GPW / GRUMP with a NASA Earthdata login (`~/.netrc`), zip integrity; without the login those two are skipped |
| Chain | `bash sbatch/submit_conus.sh external`: one `extract` job per product whose files are all there (no dependencies between them), `evaluate` with `afterany` on all of them: a failed or missing product becomes `missing` rows, the rest is still evaluated |
| Interpretation | products with input units finer than tracts (likely GPW / GHS-POP / WorldPop in 2000 / 2010, if US blocks or block groups) start from near-correct tract totals; only Fang & Jawitz has county input like v5.4. Read the table by input unit, and F&J 2000 as not independent (their M3-M5 used 2000 tracts) |
| Env | `exactextract`, `py7zr` (the F&J archive; no 7z on Alpine, and `p7zip` has no Windows build for the laptop env), `openpyxl` (GPW country summary) added to `envs/hisdac/environment.yml` |

## External comparison result (jobs 35052315-35052319, run 2026-10-30)

All 5 jobs COMPLETED (minutes each). GPW v4.11 and GRUMP v1 skipped (Earthdata login failed; `missing` rows).
`results/validation/conus/external/external_comparison.csv`, figure `external_mdape_by_year.png`. Each product is
compared with v5.4 and areal weighting on the tracts it covers without nodata.

Tract MdAPE (%), product vs v5.4 on the same tracts:

| Year | GHS-POP | WorldPop | Fang & Jawitz M3 / M5 | v5.4 (same tracts as F&J) | Areal weighting |
|---|---|---|---|---|---|
| 1910 | - | - | 84.5 / 81.3 | 52.7 / 53.1 | 83.3 |
| 1930 | - | - | 84.7 / 83.6 | 48.0 / 47.8 | 81.1 |
| 1950 | - | - | 76.8 / 75.2 | 41.0 / 40.8 | 83.1 |
| 1970 | - | - | 61.5 / 60.2 | 33.8 / 33.8 | 81.3 |
| 1980 | 23.8 | - | 52.8 / 51.8 | 32.1 / 32.1 | 79.9 |
| 1990 | 15.2 | - | 46.6 / 46.2 | 28.2 / 28.2 | 76.9 |
| 2000 | 7.9 | 8.7 | (2000 tracts used by F&J) | 27.1 | 75.9 |
| 2010 | 1.0 | 0.8 | 38.6 / 38.2 | 26.3 / 26.3 | 74.6 |

- **GHS-POP and WorldPop are near-exact in 2000 / 2010 (MdAPE about 1 %)**: in the US they are built from census
  units finer than tracts (blocks), so tract validation measures their input, not their method. Not a fair
  benchmark for a county-input model; report them as such. Their 1980 / 1990 values are GPWv4 counts carried back
  from 2000+ units, hence 24 / 15 % (still finer input than counties).
- **Against the only county-input product (Fang & Jawitz 2018), v5.4 is better in every year** by 12-33 points
  (2010: 26.3 vs 38.2 %; 1910: 53 vs 81-85 %), on the same tracts. F&J M3 and M5 hardly differ.
- In BUI gap counties F&J is better (2010: 31-32 % vs 73 %): it does not depend on HISDAC records.
- Coverage: WorldPop leaves out 32 % of the population (tracts with nodata pixels, coast); F&J 6-13 %.

## Metrics over time (request 2026-10-30, part A; run steps `docs/runbooks/Running_CONUS.md`, section 9)

Stefan (meeting 2026-10-28): report R2 and MdAPE together, county MdAPE for the TEST counties, and tract error on a
fixed set next to all tracts. Request: `docs/handoff/validation_2020_uncertainty_request.md`, part A. No retraining:
`src/validation/metrics_over_time.py` reads the tracked result files of v5.4 (= `Dasy_CONUS_RF_v3_all`) only.

| Topic | Decision |
|---|---|
| County MdAPE (A1) | per year, TEST counties (`test_predictions.csv`: the model's log density before the mass-preserving allocation) and CV (`oof_predictions.csv`, train counties): predicted pop = exp(y_hat) x `area_km2` of `county_features.csv` (the target's own area: 0.0625 km2 x unmasked cells, water mask), observed = census pop. The script stops if exp(y) x area_km2 does not give the census pop back. Metrics: counties, MdAPE, MAPE (every county has >= 10 people), R2 of log density, checked against the reported TEST R2 / pooled OOF R2 |
| Fixed tract set (A2) | the 2010 county of each evaluated tract (`zone_gisjoin` of `tract_errors_{YEAR}.csv`, flag ok); set = the counties with evaluated tracts in every tract year from the start year on, each year scored on its own tracts in those counties (decided 2026-10-28). Start years 1910, 1920, 1940, 1960 (1910+ has very few counties). Metrics: MdAPE (observed > 0), MAPE (tracts >= 10 people), areal weighting on the same tracts; the all-tracts set next to them (its MdAPE is checked against `metrics_by_year.csv`) |
| Outputs | `results/validation/conus/Dasy_CONUS_RF_v3_all/`: `county_metrics_by_year.csv`, `fixed_tract_metrics.csv`, `fixed_tract_counties.csv` (the members of each set), `mdape_over_time.png` (MdAPE by year: all tracts, fixed sets, county TEST; dashed = areal weighting). Rerun in the 2020 chain (`metrics_over_time.sh`) so 2020 is added |

### Result, 1900-2010 (computed locally from the tracked files, 2026-10-30)

County level (model before allocation vs census). The recomputed R2 equals the reported TEST R2 / pooled OOF R2 in all
24 rows, so the area definition is the target's.

| Year | TEST counties | TEST MdAPE | TEST MAPE | TEST R2 | CV counties | CV MdAPE | CV MAPE |
|---|---|---|---|---|---|---|---|
| 1900 | 576 | 32.3 | 61.3 | 0.845 | 2,238 | 29.3 | 57.6 |
| 1910 | 595 | 30.4 | 51.2 | 0.822 | 2,344 | 29.3 | 48.2 |
| 1920 | 612 | 31.5 | 47.6 | 0.834 | 2,443 | 29.5 | 49.9 |
| 1930 | 615 | 32.8 | 48.3 | 0.839 | 2,471 | 29.4 | 49.9 |
| 1940 | 615 | 31.1 | 44.2 | 0.858 | 2,471 | 29.2 | 47.6 |
| 1950 | 617 | 30.1 | 46.3 | 0.856 | 2,474 | 29.5 | 49.6 |
| 1960 | 618 | 30.5 | 48.5 | 0.861 | 2,477 | 29.5 | 50.1 |
| 1970 | 620 | 30.4 | 49.8 | 0.863 | 2,483 | 29.9 | 52.1 |
| 1980 | 622 | 29.6 | 51.0 | 0.861 | 2,484 | 29.3 | 52.5 |
| 1990 | 622 | 27.2 | 47.7 | 0.876 | 2,486 | 28.7 | 54.4 |
| 2000 | 622 | 27.2 | 50.7 | 0.875 | 2,486 | 28.5 | 56.9 |
| 2010 | 622 | 28.4 | 51.3 | 0.878 | 2,487 | 29.4 | 57.8 |

- County MdAPE is flat at 27-33 % over 110 years, while R2 rises from 0.82-0.85 to 0.88: R2 grows with the spread of
  county densities, the typical county error does not. MAPE (44-61 %) is pulled up by a few counties with large
  over-predictions.

Fixed tract sets (MdAPE %, model / areal weighting; tracts in the set that year):

| Year | all tracts | 1910+ (6 counties) | 1920+ (8) | 1940+ (73) | 1960+ (295) |
|---|---|---|---|---|---|
| 1910 | 53.2 / 82.9 | 48.6 / 82.3 (1,199) | | | |
| 1920 | 53.3 / 79.2 | 52.3 / 77.9 (1,838) | 53.3 / 79.2 (2,197) | | |
| 1930 | 49.7 / 81.5 | 51.0 / 77.1 (4,027) | 52.0 / 78.8 (4,680) | | |
| 1940 | 42.6 / 86.9 | 40.9 / 81.5 (1,521) | 40.6 / 81.4 (1,739) | 42.6 / 86.9 (7,349) | |
| 1950 | 41.8 / 83.1 | 42.0 / 65.7 (3,385) | 43.6 / 68.4 (4,051) | 41.9 / 81.4 (10,628) | |
| 1960 | 37.9 / 82.7 | 34.5 / 58.3 (3,240) | 35.5 / 59.9 (3,860) | 35.6 / 75.9 (13,011) | 37.9 / 82.7 (22,042) |
| 1970 | 34.0 / 81.3 | 31.3 / 55.6 | 32.2 / 56.4 | 31.7 / 72.2 | 33.8 / 79.5 |
| 1980 | 32.3 / 79.9 | 30.9 / 54.1 | 31.7 / 54.4 | 29.8 / 69.1 | 31.2 / 76.3 |
| 1990 | 28.5 / 76.9 | 33.0 / 52.9 | 33.3 / 53.3 | 29.1 / 66.4 | 28.8 / 74.0 |
| 2000 | 27.2 / 75.9 | 31.4 / 52.5 | 31.6 / 53.0 | 28.5 / 64.8 | 28.2 / 73.1 |
| 2010 | 26.6 / 74.5 | 29.5 / 49.5 | 29.6 / 50.2 | 27.9 / 62.9 | 27.7 / 71.6 |

- 1910+: Cook IL, Cuyahoga OH and the four NYC boroughs Kings, New York, Queens, Richmond (Bronx has no evaluated 1910
  tract); 1920+ adds Bronx and Milwaukee. 1940+ = 73 counties, 1960+ = 295 (lists in `fixed_tract_counties.csv`).
- On the fixed sets the model error still falls over time (1910+: 49-52 % before 1940, 31-34 % from 1960 on), so the
  fall in the all-tracts curve is not only the changing tract set. In the same big-city counties areal weighting also
  improves (82 -> 49 %): tracts there get more uniform in density, so part of the gain is the easier target, not only
  better input data. On the 1910+ set the model beats areal weighting by 26-41 points in 1910-1940 and by 20-24 points
  from 1950 on.
- From 1990 the 1910+ / 1920+ sets (dense NYC tracts) are 3-5 points worse than all tracts: big cities are harder than
  the national mix in recent years, so the early all-tracts numbers (big cities only) are not pessimistic by
  construction.
- 1940 has fewer evaluated tracts in the 1910+ counties (1,521) than 1930 (4,028): not the flags (38 tracts flagged),
  the 1940 tract input itself has few NYC tracts (Kings 118, Queens 60, New York 93 vs 929 / 1,367 / 275 in 1930;
  Cook and Cuyahoga unchanged). The 1940 point of the fixed sets is mostly Cook + Cuyahoga; check the NHGIS 1940 NYC
  tracts (`results/tract/`) if this year matters.
- MAPE (tracts >= 10 people) is 54-326 % for the model and dominated by small tracts with large relative errors; MdAPE
  is the stable one.

## 2020 (request 2026-10-30, part B; run steps `docs/runbooks/Running_CONUS.md`, section 10)

| Topic | Decision |
|---|---|
| Version | 2020 is added to `Dasy_CONUS_RF_v3_all` (= v5.4) as era `Y2020` (same features, split, folds, search space, 60 candidates, seed), not a new version. Run with `--years 2020` only: the 1900-2010 eras are not recomputed. `train.py` / `predict.py` / `county_features.py` keep the other years' rows of `cv_summary.csv` / `reallocation_qa.csv` / `water_mask_by_year.csv` with `--years` (read back with round-trip floats, so the kept rows are unchanged byte for byte; tested) |
| Study area | `configs/conus_study_area.yaml` years 1900-2020. Every CONUS model config has its own `years:`, so only v3_all gains a year |
| County input | `conus_counties.py --years 2020`: NHGIS 2020 nominal counties (`$DATA_ROOT/processed/census/counties_2020.gpkg` from `prepare_census.py`, extract nhgis0001: 3,108 CONUS counties, pop 329,260,619 per `results/census/qa_report.csv`) on the 3,109 2010 polygons by GISJOIN. Changes 2010-2020: Shannon SD -> Oglala Lakota (G4601130 -> G4601020, 2015, same unit: remapped); Bedford city VA merged into Bedford County (2013): Bedford city `no_value` (its cells NoData, its people in Bedford County), Bedford County `filled_nhgis_alloc` (allocation only: its 2020 pop includes the former city); Connecticut: planning regions only from 2022, the 2020 census has the 8 counties (the log lists the CT units; 3,108 = 3,109 - Bedford city fits); Alaska / Hawaii / Puerto Rico are in neither file. Status rules as for the filled polygons: `ok` = same unit with NHGIS / 2010 area ratio 0.95-1.05, else `filled_nhgis_alloc`; `zero_pop`; `no_value`. Every decision: `results/census_conus/counties_2020_nhgis_match.csv` (one row per polygon + NHGIS units no polygon takes) |
| Cutout | `grid_cutout --years 2020`: BUI, BUPL, BUPR, BUA (HISDAC has 2020 files, inventory 2026-10-28) and Land_Use 2020 (`Count_2020_{CLASS}.tif`: in the config since Massachusetts, whose v3.4 used it; the LU README says 1940-2015, so `y2020_precheck.sh` compares each class file with 2015 by md5); BUI fix `--years 2020`; DEM static, kept. Water: all 13 years again (one QA file with the 1920 / 1960 / 2010 QA points; GDW yearly layers are deterministic) |
| Land_Use 2020 | to decide from the pre-check: if the 2020 files exist and differ from 2015, use them (as Massachusetts did). If they are missing, or identical to 2015, the options are (a) 2015 for 2020 (counts are cumulative to mid-decade: 2015 = records up to 2019, the closest state; written in the config as a `year_map`, recorded) or (b) Y2020 without res_share / rent_share (as the pre-1940 eras); the user decides |
| Validation | tract validation rerun for 1910-2020 (`metrics_by_year.csv` holds all years; the old `tract_errors_{YEAR}.csv` must come out byte-identical: checked with `git diff` after the run), `summary_by_year.csv` / `mdape_by_year.png` 1900-2020 (`compare_models.py`, repro with v3_n60 as before), `metrics_over_time.py` with 2020 |
| Maps | the 2020 map is drawn with the fixed colour-bar label (below) |

### Map label fix (A4, 2026-10-30)

`predict.py` draws CONUS maps as sums over 4 x 4 cells (the 250 m array is too big for matplotlib): the title said
"Population per 1 km cell" (right: the drawn value is people per 1 km block), the colour bar said "people per 250 m
cell" (wrong). `plots.pop_maps` now takes the cell label from `predict.py` and uses it for both. Old PNGs are **not
redrawn**: the values and the colour scale are right, only the colour-bar text is wrong, and redrawing needs the
prediction step of every year again (~47 min for v3_all). New maps (2020 and later versions) carry the right label.

## HISDAC record uncertainty (request 2026-10-30, part C; run steps `docs/runbooks/Running_CONUS.md`, section 11)

Meeting item 4 (2026-10-28): the share of records without a built year per county, as a basis for leaving unreliable
counties out of training and testing (imputation by the model trained on the others). This step only measures it;
thresholds and the selection rule are decided by the user from the tables, then requested separately.

| Topic | Decision |
|---|---|
| Data | `BUPR_contemp.tif` (all ZTRAX records with or without a built year, ~2016) from Dataverse doi:10.7910/DVN/45B8IU (`docs/data_sources.md`), `sbatch/hisdac_extra_download.sh` (login node, tmux): only that file if Dataverse has it on its own, else the BUPR archive to scratch and only that member unpacked, into `$DATA_ROOT/raw/hisdac_extra/` |
| C2 checks | CRS / grid of contemp, BUPR_2015 and NobuiltYear vs the zone grid (= the HISDAC grid): read directly when equal, else through a WarpedVRT with nearest onto the zones (exact for a whole-cell shift; logged). NobuiltYear count or 0/1 flag from its values (`nobuilt_values.csv`). Per cell with any record: d = contemp - BUPR_2015 vs NobuiltYear (equal / larger / smaller, d < 0): the README says contemp is ZTRAX only, the yearly layers ZTRAX + Parcel Atlas + Open City Model, so they may differ |
| C3 ratios | per 2010 county (sums over its cells on the 2010 zones): A = (contemp - BUPR_2015) / contemp (fixed; negative -> 0, counted; contemp = 0 -> undefined); B_year = NobuiltYear / (BUPR_year + NobuiltYear) per census year (upper bound, as the records without a year may be old or new; only if NobuiltYear is a count). `results/hisdac_uncertainty/county_record_uncertainty.csv` |
| C4 gap counties | BUI gap counties (floor area per person < 5 % of the year's median, as `tract_validate.py`; 416 in 2010) vs A: overlap per threshold, A quantiles gap vs other, Spearman A vs floor area per person, by state |
| C5 thresholds | 0.1 ... 0.9: counties kept (ratio <= t; undefined kept and counted), their share of the year's pop (used counties of v3_all's `county_features.csv`), train / test kept (`configs/conus_split.csv`), gap counties kept, by state; A with the pop of every census year, B_year for its own year. Figure `threshold_counties.png` (counties / pop kept vs threshold: A 2010, B 1920 / 1960 / 2010 / 2020) |
| Chain | `bash sbatch/submit_conus.sh uncertainty` (one job, `record_uncertainty.sh`), independent of `y2020`; uses Y2020 pop only if that run finished first |
| Without contemp (request 2026-10-30, `docs/handoff/record_uncertainty_fallback_request.md`) | `BUPR_contemp.tif` is not in the Dataverse BUPR.tar (v2; `results/hisdac_uncertainty/BUPR.tar_members.txt`); asked of Stefan. contemp is optional: without it the A share is `ratio_A_nby = NobuiltYear / (BUPR_2015 + NobuiltYear)` (contemp = records with a year + records without one; 2015 = the series year nearest the ZTRAX collection ~2016), with `ratio_A_nby_2020` (BUPR_2020) beside it and the 2015 - 2020 difference logged. `ratio_B_<year>` as before. Column names say the definition: `ratio_A_contemp` (with contemp), `ratio_A_nby`, `ratio_B_<year>`; C4 and C5 run for every ratio that exists (column `measure`: A_contemp, A_nby, B). Both A ratios -> `a_compare.csv` + `a_compare_thresholds.csv` (county) and the per-cell difference in `cell_check.csv` (`cells_a_*`; d == NobuiltYear = equal A in that cell). No contemp and a 0/1 NobuiltYear: no ratio can be computed; the run writes the value distribution and `outcome` in `cell_check.csv` and ends with exit 0 |

## HISDAC record uncertainty: diagnosis (job 35056349, run 2026-10-29 MT)

`BUPR_contemp.tif` not available (not in the Dataverse BUPR.tar); ratios from `NobuiltYear.tif`, which is a **count**
(max 24,246, 0 fractional cells). Results `results/hisdac_uncertainty/`.

- **Nationally 39 % of all records have no built year**: 109.4 M without vs 168.5 M with a year (BUPR 2015). Of the 26.2 M
  study cells with any record, **54 % (14.2 M) hold only records without a year**: they are BUI = BUA = 0 in every year of
  the time series although buildings stand there.
- County ratio A = NobuiltYear / (BUPR_2015 + NobuiltYear): median 0.55 (all counties), 0.50 outside the gap counties;
  Spearman with BUI floor area per person -0.72.
- **The BUI gap counties are the counties without built years**: their ratio median 1.000 (10th percentile 0.974);
  all 416 are above 0.3, 412 above 0.5. Same states (IL, WI, ND, MI, SD, LA, VT ~0.98-1.00 median).
- Counties kept below each threshold (2010; 3,109 counties):

  | Ratio A below | Counties | Population | Train / test | Gap counties kept |
  |---|---|---|---|---|
  | 0.3 | 515 | 55 % | 414 / 101 | 0 |
  | 0.5 | 1,337 | 80 % | 1,076 / 261 | 4 |
  | 0.6 | 1,745 | 87 % | 1,391 / 354 | 5 |
  | 0.7 | 2,098 | 91 % | 1,671 / 427 | 9 |
  | 0.8 | 2,403 | 94 % | 1,916 / 487 | 13 |
  | 0.9 | 2,590 | 95 % | 2,062 / 528 | 20 |

  Ratio B (per year, NobuiltYear / (BUPR_year + NobuiltYear)) is an upper bound that grows backwards: in 1920 only 62
  counties are below 0.5. 2015 vs 2020 reference: nearly the same counts.
- Caveat: NobuiltYear values are far more often even than odd (1: 8.3 M cells, 2: 5.3 M, 3: 1.6 M, 4: 1.8 M, 5: 0.7 M, 6:
  0.9 M, ...): possibly records counted twice (e.g. the same building from two sources). If so the ratios are too high.
  To ask Stefan, together with where `BUPR_contemp` is.

## Uncertainty filter (request 2026-10-30, `docs/handoff/uncertainty_filter_request.md`; run steps `docs/runbooks/Running_CONUS.md`, section 12)

Meeting 2026-10-28 item 4 (Stefan): counties with unreliable records are left out of training and testing; the model
of the clean counties allocates their population (imputation). The threshold is chosen by a sensitivity run on
county sets, not on tracts.

| Topic | Decision |
|---|---|
| County sets | One fixed set per threshold on the 2010 polygons, the same for every year (`src/grid/uncertainty_filter.py`, job `uncertainty_filter.sh`). Excluded if any of: **ratio** `ratio_A_nby >= t` (t = 0.9 / 0.7 / 0.5; `county_record_uncertainty.csv`); **records** (BUPR_2015 + NobuiltYear) / pop_2010 < 5 % of the national median (median over counties with 2010 pop; ~1.37 per person by eye from the 2010 features, ~3 counties, e.g. DuPage IL, Otero); **area** BUI_2015 / BUPR_2015 (county sums) < 5 % of the median (~1,600 sq ft per dated record by eye; ~37 counties, e.g. Tehama CA, Codington SD). The two fixed rules are not tuned and apply at every t. No 2010 pop / no BUPR_2015 -> no value for that rule (counted). BUI_2015 = raw HISDAC layer summed on the 2010 zones (the cutout has census years only); cells above the BUI cap (3e7) are counted, not changed (an outlier raises BUI per record and cannot exclude a county) |
| Outputs | `results/hisdac_uncertainty/excluded_counties_t{090,070,050}.csv` (GISJOIN, state, name, split part, the three values, `reason_ratio` / `_records` / `_area`, `reasons`, pop_2010, gap_2010), `county_filter_inputs.csv`, `filter_summary.csv` (per t: excluded by reason, fixed rules only, kept, pop share kept 1920 / 1960 / 2010 / 2020, train / test excluded and kept, gap counties excluded), `filter_by_state.csv`. Sets are nested (logged) |
| NobuiltYear even / odd | Far more even than odd values (possible double counting): logged as one NOTE line, used as it is (not corrected) |
| Models | `Dasy_CONUS_RF_v3_u090`, `_u070`, `_u050` (`configs/conus_rf_v3_u*.yaml`): v5.4's features, RF, search space, 60 candidates, split table and folds; `exclude_counties: <csv>` (read by `train.py` only) drops those rows from the search, the refit and the TEST score in every era (the other rows keep their split part and fold); hyperparameters searched again per year. `excluded_predictions.csv` per era = the model's y_hat for the excluded rows (+ split part). `predict.py` allocates every county as before (excluded = imputation), mass preserved. Years 1920 / 1960 / 2010 / 2020; the chosen t is run for all years later. `compare_with: Dasy_CONUS_RF_v3_all` (CV / TEST of v5.4 on the same rows) |
| No filter | v5.4 (`Dasy_CONUS_RF_v3_all`) as it is, not rerun |
| Evaluation | `src/validation/filter_compare.py` (job `filter_compare.sh`, also runs locally) -> `results/validation/conus/uncertainty_filter/filter_comparison.csv` (version x year x set), `filter_selection.csv`, `filter_comparison.png`. County level before allocation (exp(y_hat) x the target's area_km2 vs census, as `metrics_over_time.py`; MdAPE, MAPE over pop >= 10, R2 of log density, counties): **(a) common TEST** = v5.4's TEST counties not excluded at t = 0.5 (every model scored them as TEST); **(b) imputed TEST** = TEST counties excluded at t = 0.9 (no model trained on them; v5.4 from `test_predictions.csv`, the filtered models from `excluded_predictions.csv`); each filtered model's own excluded set (sets differ; shown, not compared). Tract level (not used for the choice): all, gap / no_gap, kept / excluded tracts of each t (by `zone_gisjoin`), areal weighting |
| **Selection rule (fixed 2026-10-30, before any result)** | Per model the mean over 1920 / 1960 / 2010 / 2020 of (MdAPE (a) + MdAPE (b)) / 2; the lowest wins; models within 1 percentage point of it count as equal and the one keeping more counties wins (no filter > 0.9 > 0.7 > 0.5). Every year needed. Logged as one `RULE RESULT` line; **the final decision is the user's** |
| Chain | `bash sbatch/submit_conus.sh uncfilter`: pre-check of the inputs, `uncertainty_filter` + the three features jobs at once, then per version train (after its features and the sets) -> predict -> validate (1920 / 1960 / 2010 / 2020, `--gap-share 0.05`), the three versions side by side; `filter_compare` after the three validations |
| Tests | `tests/test_uncertainty_filter.py` (sets, rules, summary; common / imputed sets, metrics, rule with the tie, a leak stops the run), `tests/test_conus_dasymetric.py` `test_exclude_counties` (out of search / fit / TEST, folds kept, excluded predictions = the model, allocated with mass preserved) |

## PLURAL grid test (request 2026-10-30, `docs/handoff/plural_grid_request.md`; run steps `docs/runbooks/Running_CONUS.md`, section 13)

Meeting 2026-10-28 item 3 (Stefan): Siqiao's 900 m PLURAL grid (`index3`, 0 = urban ... 1 = remote; three years
1940 / 1980 / 2010) resampled to 250 m and tried as a feature, continuous and in a few classes (number of classes and
breaks = sensitivity). If it helps, PLURAL values for 1900-2020 are made and every year is run; if not, v5.6 goes on
to all years. What index3 is (PLURAL-1 / -2, population weighting) is still unknown: if it is built from population,
the same year's census population enters as a feature (`docs/data_sources.md` "PLURAL").

| Topic | Decision |
|---|---|
| Layers | `configs/conus_study_area.yaml`: `PLURAL` (bilinear, main) and `PLURALC` (cubic, sensitivity; `clip: [0, 1]` in `make_cutout.py`, clipped cells below / above, all and inside the zones, in the cutout log), float32, years 1940 / 1980 / 2010, cut with `grid_cutout.sh --layers PLURAL PLURALC`. Cells outside the source extent would be nodata (the features stop on a nodata cell inside a used county) |
| Fill check | `src/grid/plural_qa.py` (`sbatch/plural_qa.sh`, nothing waits for it) -> `results/cutout/conus/plural_qa.csv`, `plural_points.csv`. 0 outside the US is also the urban value, so the leak is measured by weight, not value: out_w = the indicator "900 m pixel centre outside every county" (zones sampled at the pixel centres) warped with the layer's own method; the warp is linear, so value = (1 - out_w) x the US-only value; deficit = value / (1 - out_w) - value. Edge (<= 5 km of a non-county cell) vs interior distributions; points New York, Boston, Chicago, Denver, Pittsfield, Ely NV, Miami, San Diego (900 m pixel vs 250 m cells). If the edge is pulled down a lot, options (user decides): nearest on cells with out_w > 0, or the renormalized value value / (1 - out_w) there |
| Base | v5.6 = `Dasy_CONUS_RF_v3_u070` gets eras Y1940 / Y1980 (v5.4's features of those years), run with `--years 1940 1980` (its other eras and the other rows of `cv_summary.csv` / `reallocation_qa.csv` / `water_mask_by_year.csv` are kept); validated again on all six years (the old `tract_errors_{YEAR}.csv` must come out the same: deterministic) |
| Variants | `configs/conus_rf_v3_u070_{plc,plcc,pq3,pq5,pe3,pe5}.yaml` = v5.6 + `plural` (same split, folds, excluded counties, statuses, water mask, search space, 60 candidates), 1940 / 1980 / 2010, `compare_with` v5.6. Block `plural: {layer, classes, breaks}`: plc = PLURAL continuous, plcc = PLURALC continuous, pq3 / pq5 = 3 / 5 classes with quantile breaks, pe3 / pe5 = equal intervals of 0-1 (classes from the bilinear layer). Quantile breaks = the 1/k ... (k-1)/k quantiles (numpy linear) of the layer over all cells of the used counties that year (water-masked cells included); class = 1 + number of breaks <= value (1 = most urban); `<era>/features/plural_breaks.csv` (breaks + cell share per class), and `predict.py` stops if its recomputed breaks differ. Cell feature = value or class number; county feature = mean over the unmasked cells (as every feature) |
| Evaluation | `src/validation/plural_compare.py` (in `sbatch/plural_compare.sh`; also runs locally) -> `results/validation/conus/plural_grid/plural_comparison.csv` + `.png`: tract MdAPE and MAPE (tracts >= 10 people) on the tracts evaluated in every version, sets all / kept_t070 / excluded_t070 / no_gap / gap / dens_0_50 ... dens_2000_plus, areal weighting; county TEST MdAPE / MAPE before allocation, CV RMSE / R2, TEST RMSE / R2; plural permutation / SHAP rank and value; d_mdape = minus v5.6 |
| **Best classed variant (rule fixed 2026-10-30, before any result)** | The lowest mean over the three years of tract MdAPE (all tracts) among pq3 / pq5 / pe3 / pe5 (`plural_best.txt`, `RULE RESULT` line). Only picks what is drawn in the maps; whether PLURAL is kept is the user's decision |
| Maps | Same job: `county_maps.py`, 2010, Chelan WA, Reno KS, Fremont CO, Macoupin IL, v5.6 / plc / best classed -> `plural_grid/county_maps/` (+ `county_maps.csv`: share of people on BUI = 0 cells: does plural spread people onto empty land, as the distances / night lights did?) |
| Chain | `bash sbatch/submit_conus.sh plural`: pre-check, cutout (`--layers`) -> plural_qa; v5.6 features / train / predict `--years 1940 1980` -> validate (6 years); per variant features (after the cutout) -> train (after its features and v5.6's train) -> predict -> validate; `plural_compare.sh` after every validation |
| Tests | `tests/test_plural.py` (configs; resampling of a linear LAEA field = the field at the cell centres; cubic clip; plural_qa deficit = the fill's pull; breaks, classes, strips; predict breaks check; a new era via `--years` leaves the old era byte for byte; plural_compare by hand + figure) |

## PLURAL grid test result (jobs 35084995-35085025, code 288a921, run 2026-10-29 MT)

All 31 jobs COMPLETED (about 50 min wall). Same tracts (1940: 7,350, 1980: 44,586, 2010: 72,243), same split / folds /
excluded counties / search space as v5.6. Files: `results/validation/conus/plural_grid/plural_comparison.csv`, `.png`,
`county_maps/`.

Tract MdAPE (all tracts, %):

| Year | Areal weighting | v5.6 | plc | plcc | pq3 | pq5 | pe3 | pe5 |
|---|---|---|---|---|---|---|---|---|
| 1940 | 86.9 | 42.2 | 43.3 | 43.4 | 42.1 | 41.5 | 42.4 | 42.2 |
| 1980 | 79.9 | **26.8** | 29.6 | 29.7 | 28.2 | 28.1 | 32.3 | 33.2 |
| 2010 | 74.5 | **23.8** | 25.4 | 25.3 | 24.1 | 24.2 | 28.2 | 25.8 |

- Fixed rule (best classed variant for the maps): pq5, 3-year mean 31.25 % vs v5.6 30.93 % (plc 32.76 %).
- Every variant is worse than v5.6 in 1980 and 2010 (continuous +1.6 to +2.9 pp, equal-interval classes up to +6.4 pp);
  1940 within -0.7 / +1.2 pp. Kept / excluded / gap / density parts show the same; only gap counties move slightly
  (2010: 77.5 -> 76.0-77.8 %, areal weighting 75.6 %).
- County level is the opposite: CV R2 rises by about 0.005-0.01 in every year, TEST R2 about equal, TEST MdAPE mixed
  (2010: 23.0 -> 21.5-24.4 %). plural ranks 2nd-4th of 9 features (permutation and SHAP; pe3 1940: 9th).
- Maps (2010): population on BUI = 0 cells rises (Chelan 3.7 -> 6.5 % plc / 5.1 % pq5, Reno 2.1 -> 3.9 / 3.0, Fremont
  3.8 -> 6.1 / 5.0, Macoupin 55.3 -> 65.3 / 61.9). PLURAL spreads people into empty land, as the PLURAL distances (v5.1)
  and night lights (v5.5) did: it describes county-scale remoteness, which helps the county mean and hurts the
  within-county shape.
- `plural_qa`: interior cells untouched; 2.2 % of county cells are edge cells (<= 5 km of a non-county cell), of
  which 17.6 % (bilinear) / 18.8 % (cubic) use outside-US pixels and about 8 % are exactly 0 (fill). Real leak at
  coasts / borders, but it does not change the conclusion. Cubic clipping and bilinear give the same tract results.
- Reading: PLURAL adds no within-county information beyond BUI / bldg_size / dist_built; with no gain in its three
  years there is no case for building 1900-2020 PLURAL values. Proposed: drop PLURAL; run v5.6 for all years.

## v5.6 all years (request 2026-10-30, `docs/handoff/v56_all_years_request.md`; run steps `docs/runbooks/Running_CONUS.md`, section 14)

v5.6 (`Dasy_CONUS_RF_v3_u070`) is the final version and is run for every census year, next to v5.4, for Stefan's
meeting items (tract MdAPE every decade, county TEST MdAPE, fixed tract sets).

| Topic | Decision |
|---|---|
| Eras | `configs/conus_rf_v3_u070.yaml`: 13 eras 1900-2020, one per year; each era's features = the same year's era of `conus_rf_v3_all.yaml` (no Land_Use before 1940). Split, folds, `exclude_counties` (t = 0.7 set, the same counties every year), statuses, water mask, search space, 60 candidates unchanged |
| Run | `bash sbatch/submit_conus.sh v56all`: one dependency chain (submitted once): features / train / predict `--years 1900 1910 1930 1950 1970 1990 2000` (the six eras run before are not recomputed; the other years' rows of `cv_summary.csv` / `reallocation_qa.csv` / `water_mask_by_year.csv` are kept) -> tract validation of every year with a tract file (1910-2020; 1900 has none, logged as SKIP in the pre-check) -> `compare_models.sh` and `metrics_over_time.sh` side by side. The old years' files must come out byte for byte (`OLD YEARS 0 / 0` line of runbook block 3; validation is deterministic) |
| Summaries | `results/validation/conus/Dasy_CONUS_RF_v3_u070/` with v5.4's file names: `summary_by_year.csv` + `mdape_by_year.png` (`compare_models.py --versions v5.6 v5.4 --exclusions .../excluded_counties_t070.csv`: rows of both versions; new columns `tract_kept_t070_*` / `tract_excluded_t070_*` from `tract_errors_{YEAR}.csv`; the figure draws v5.6 with v5.4's all-tracts MdAPE dotted; no `--repro-with`: v5.6 is not expected to equal v5.4), `county_metrics_by_year.csv`, `fixed_tract_metrics.csv`, `fixed_tract_counties.csv`, `mdape_over_time.png` (`metrics_over_time.py --compare-with v5.4`: v5.4's sets dotted in the same colours; the differences v5.6 minus v5.4 are logged) |
| Caution when reading | v5.6's TEST counties = the TEST counties not excluded at t = 0.7; v5.4's = all TEST counties: the county TEST MdAPE and TEST R2 of the two are on different sets (the uncertainty filter comparison has the common sets). CV R2 likewise. Tracts are the same in both |
| Tests | `tests/test_plural.py`: `test_configs` (13 eras = v5.4's features), `test_plural_feature` (a new era via `--years` leaves the old era byte for byte), `test_v56all` (kept / excluded t070 tract MdAPE by hand, both versions in the summary, figures, `--compare-with` writes nothing of v5.4) |

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
(its config has no cap); the same submission counts the Massachusetts cells above 3e7 from the raw files.

## BUI fix and v3 base rerun (request 2026-10-27; run steps `docs/runbooks/Running_CONUS.md`, section 3)

| Topic | Decision |
|---|---|
| Where | separate step after the cutout: `src/grid/bui_fix.py` (`sbatch/bui_fix.sh`), in place on the cutout's `layers/BUI/`. The first run moves the original to `layers/BUI_raw/{YEAR}_BUI.tif`; every run reads `BUI_raw` and writes `layers/BUI/` again, so a rerun gives the same file. Simpler than inside `make_cutout.py` (no re-cut of the other layers). Re-cutting BUI (`--layers BUI`) needs a new `bui_fix` run |
| Switch | `bui_cap: {max: 3.0e+7, replace: neighbour_median}` in `configs/conus_study_area.yaml`; without the block (Massachusetts `study_area.yaml`) `bui_fix.py` refuses to change a cutout and only `--check` counts |
| Rule | BUI > max -> median of the 3 x 3 neighbours, the cell itself out; neighbours outside the window, with nodata or themselves above max are left out; none left -> 0. Always the original neighbour values (order-free). A cell exactly at max is kept. Nodata stays nodata |
| Strips | `--block-rows` strips (512) read with one halo row above and below: strips = whole window = a brute-force loop (`tests/test_bui_fix.py`, strips of 1, 7, 512 rows) |
| QA | `results/cutout/conus/bui_fix_summary.csv` (per year: cells above max, set to 0, max before / after, BUI sum before / after, share removed) and `bui_fixed_{YEAR}.csv` (every replaced cell: row, col, lon, lat, county, BUI before / after, neighbours in the window / used / above max, BUPL); the 15 largest per year in the log |
| Massachusetts | count only: `bui_fix.py --check --hisdac-dir` on the raw HISDAC BUI over `results/cutout/massachusetts/window.json` (the scratch cutout may be purged) -> `results/cutout/massachusetts/bui_check_summary.csv` (+ `bui_check_{YEAR}.csv` for years with cells above 3e7). Nothing is written in any cutout |
| Versions | `Dasy_CONUS_RF_v1_bui` = v1 on the fixed cutout (1920, 1960, 2010; `compare_with: Dasy_CONUS_RF_v1`): the effect of the fix alone. `Dasy_CONUS_RF_v3_bui` = v3 on the fixed cutout for 1920, 1960, 2010 (1920: v1's 1920 features + `elev`, `slope`; `compare_with: Dasy_CONUS_RF_v3`, which has no 1920, so 1920 has no CV / test comparison in train). Same split and folds. The old v1 / v3 outputs are not overwritten |
| Validation | tract validation 1920 / 1960 / 2010 with the density classes for both |
| County maps | 2010, v1_bui / v2 / v3_bui / v4 on the same 4 counties; differences against v1_bui; BUI drawn = fixed BUI. `place_points` CRS bug fixed (`place_dist.crs_label` takes pyproj and rasterio CRS; `tests/test_place_dist.py`) |

## Model family (request 2026-10-27; run steps `docs/runbooks/Running_CONUS.md`, section 4)

RF, LightGBM, XGBoost and CatBoost under the same conditions, to choose the model before the run over all years.

| Topic | Decision |
|---|---|
| Versions | `Dasy_CONUS_RF_v3_n60`, `Dasy_CONUS_LGBM_v3_n60`, `Dasy_CONUS_XGB_v3_n60`, `Dasy_CONUS_CAT_v3_n60` (`configs/conus_{rf,lgbm,xgb,cat}_v3_n60.yaml` = `conus_rf_v3_bui.yaml` with only `model`, `models` and `search.n_iter` changed). `Dasy_CONUS_RF_v3_bui` (20 candidates) stays as it is, for reference |
| Features | exactly v3_bui's: its `<era>/features/county_features.csv` (1920, 1960, 2010; BUI-fixed cutout) is copied into each version by `submit_conus.sh models`, nothing recomputed. Prediction computes the cell features from the same cutout |
| Split / folds | `configs/conus_split.csv`. `folds_from` can't be combined with `split` (`common.load_config` stops), and it is not needed: the split table gives v3_bui's folds, and train.py checks them against v3_bui's saved out-of-fold predictions (`compare_with: Dasy_CONUS_RF_v3_bui`, error if a fold differs) |
| Search | RandomizedSearchCV, 60 candidates for every model, 5-fold county CV, scoring negative RMSE of log density, `random_state` 42; no early stopping (same CV procedure as RF). Tracts are never used in the search |
| Threads | parallel candidates only (`--n-jobs` = cores); each model single-threaded and quiet: RF / LightGBM / XGBoost `n_jobs=1`, CatBoost `thread_count=1`; `verbose=-1` / `verbosity=0` / `verbose=0`, CatBoost `allow_writing_files=False`; XGBoost `tree_method: hist` (`src/dasymetric/models.py`). Seeds `random_state` / `random_seed` 42 |
| Space syntax | `models.<name>.space`: a list = one of the values (as before; the Massachusetts configs are unchanged), a dict = a distribution: `{dist: loguniform, low, high}` = `scipy.stats.loguniform(low, high)`, `{dist: uniform, ...}` = `uniform(low, high - low)`, `{dist: randint, ...}` = `randint(low, high + 1)` (high included). With a distribution the search draws `n_iter` candidates; with lists only, at most the number of combinations. An era's `params:` still replaces a key with `[value]`. The space and the chosen values go to the log and `metrics.json` (`search_space`, `fixed_params`, `best_params`, `n_candidates`, `search_seconds`, `train_seconds`) |
| RF | `n_estimators` randint 200-1000, `max_depth` [null, 5, 10, 15, 20, 30], `min_samples_leaf` randint 1-10, `max_features` [sqrt, 0.33, 0.5, 0.75, 1.0] |
| LightGBM | `n_estimators` randint 200-2000, `learning_rate` loguniform 0.01-0.2, `num_leaves` randint 7-63, `min_child_samples` randint 5-50, `subsample` uniform 0.5-1.0 (fixed `subsample_freq: 1`), `colsample_bytree` uniform 0.5-1.0, `reg_lambda` / `reg_alpha` loguniform 1e-3-10 |
| XGBoost | `n_estimators` randint 200-2000, `learning_rate` loguniform 0.01-0.2, `max_depth` randint 3-8, `min_child_weight` randint 1-10, `subsample` / `colsample_bytree` uniform 0.5-1.0, `reg_lambda` / `reg_alpha` loguniform 1e-3-10 |
| CatBoost | `iterations` randint 300-2000, `learning_rate` loguniform 0.01-0.2, `depth` randint 4-8, `l2_leaf_reg` loguniform 0.1-10, `rsm` uniform 0.5-1.0, `subsample` uniform 0.5-1.0 (fixed `bootstrap_type: Bernoulli`) |
| Prediction | unchanged: whole CONUS (allocation divides by the county's cell sum, so it can't be limited to tracted areas), w = exp(y_hat), county mass preserved. The fitted model is pickled with joblib as before (`<model>.joblib`) |
| Env | `xgboost>=2.1.4`, `catboost>=1.2.8` added to `envs/hisdac/environment.yml` (conda-forge). CatBoost 1.2.7 has no `__sklearn_tags__` and fails in RandomizedSearchCV with scikit-learn >= 1.6 (seen locally 2026-10-27), hence the pin. `sbatch/test_env_hisdac.sh` runs a search with a distribution, a pickle round trip and SHAP for LightGBM, XGBoost, CatBoost; every job of the chain waits for it |
| Gap counties | `tract_validate.py --gap-share 0.05` (CONUS; default off, so Massachusetts is unchanged): county BUI floor area per person = mean `bui` x (`n_cells` - `n_masked`) / `pop` from the version's `county_features.csv`; below 5 % of that year's median over the counties = gap county (533 / 479 / 416 in 1920 / 1960 / 2010, reproduced from the v3_bui features). Parts `no_gap` and `gap` next to all / train / test, columns `gap_counties`, `gap_tracts`; `gap` column in `tract_errors_{YEAR}.csv`. v3_bui is validated again to get them |
| Comparison | `src/validation/compare_models.py` (`sbatch/compare_models.sh`, end of the chain) -> `results/validation/conus/model_comparison.csv`: per version (4 x n60 + v3_bui) and year CV RMSE mean / sd, CV R2, TEST RMSE / R2, tract MdAPE / MAE / R2 (log pop) for all / train / test / no_gap / gap, MdAPE per density class, areal weighting MdAPE, chosen hyperparameters, train time (empty for v3_bui, trained before the timing was recorded); a summary per year in the log |
| County maps | 2010, the same 4 counties, the four n60 models (differences against RF n60) |
| Choice | tract validation first (all tracts, density classes, no_gap), county TEST R2 second (`docs/open_items.md`) |
| Resources | train 16 cores, 2 h (3 x the candidates of v3_bui, whose train took ~9 min; boosting time unknown); predict, validate, maps as the bui chain |

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
| Layers not cut | FBUY, NobuiltYear (`age` dropped). DEM added 2026-10-27 for v3 / v4, NTL (2000 / 2010) and NTLV (VIIRS-like, 2000 / 2010) 2026-10-28 for v3_ntl / v3_ntlv |
| JRC no data | counted as water as in Massachusetts; checked only there (open sea). From the pilot on, `water_frac.py` logs the share inside study cells (`study_jrc_nodata_mean`, `study_cells_jrc_nodata_gt50` in `water_qa.csv`) and per county (`qa/water_jrc_nodata_by_county.csv`, top 20 in the log); decide from it before the full run |

## Order

1. Scale review of each stage (above) and a resource estimate per job (memory, time, disk). Done 2026-10-23.
2. Trial (1960 only, v1; prediction timed on 3 strips, nothing written): measures time and memory
   (`docs/runbooks/Running_CONUS.md`, step 0). Adjust the resources in `sbatch/submit_conus.sh` from it.
3. Pilot: CONUS cutout for 1920, 1960, 2010 + water mask + distances; census input on 2010 polygons; split
   table (`configs/conus_split.csv`, made 2026-10-23); per-year features, train (v1, v2), predict, tract validation.
4. Review time, memory and results. Done 2026-10-27: v3 chosen (above).
5. BUI fix in the cutout; rerun v3 for 1920, 1960, 2010 (1920 not run with terrain yet); county maps (bug fixed).
   Code 2026-10-27 ("BUI fix and v3 base rerun"; `bash sbatch/submit_conus.sh bui`).
6. Model family: RF / LightGBM / XGBoost / CatBoost on v3_bui features, 1920 / 1960 / 2010, chosen by tract
   validation + county TEST R2 (`docs/handoff/conus_models_request.md`). Code 2026-10-27 ("Model family";
   `bash sbatch/submit_conus.sh models`).
7. Then the remaining years (1900-2010) with the chosen model and v3 features, then 2020. Code 2026-10-27 ("All
   census years"; `bash sbatch/submit_conus.sh all`). Done 2026-10-27 ("All census years result"). Next: 2020.
8. NTL test for 2000 / 2010 (`Dasy_CONUS_RF_v3_ntl` vs v3_all). Code 2026-10-28 ("NTL test";
   `bash sbatch/submit_conus.sh ntl`). If NTL helps, 2020 gets it too. Ran 2026-10-28 ("NTL test result").
9. VIIRS-like NTL test for 2000 / 2010 (`Dasy_CONUS_RF_v3_ntlv` vs v3_all and v3_ntl). Code 2026-10-28 ("VIIRS-like
   NTL test"; `bash sbatch/ntlv_download.sh`, `sbatch --wait sbatch/ntlv_check.sh`, `bash sbatch/submit_conus.sh ntlv`).
   Ran 2026-10-28 ("VIIRS-like NTL test result"): night light left out of the base model.
10. External comparison: v5.4 vs GHS-POP, WorldPop, GPW v4.11, GRUMP v1, Fang & Jawitz (M3, M5) on the same tracts.
   Code 2026-10-28 ("External comparison"; `bash sbatch/external_download.sh`, `bash sbatch/submit_conus.sh external`).
