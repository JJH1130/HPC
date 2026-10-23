# CONUS plan: Dasy_CONUS_RF_v1

The Massachusetts pilot (v1-v4.1) is closed; the pipeline now moves to the conterminous US (48 states + DC).
This file is the plan for the first CONUS runs. Decisions are also in `docs/open_items.md` (decision log).

Last updated: 2026-10-24 (trial measured; 4 counties filled from NHGIS; JRC no-data QA; pilot resources)

Run steps: `docs/runbooks/Running_CONUS.md`. Configs: `configs/conus_study_area.yaml`, `configs/conus_rf_v1.yaml`,
`configs/conus_rf_v2.yaml`, split `configs/conus_split.csv`.

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
| Layers not cut | FBUY, NobuiltYear (`age` dropped), NTL, DEM (terrain later) |
| JRC no data | counted as water as in Massachusetts; checked only there (open sea). From the pilot on, `water_frac.py` logs the share inside study cells (`study_jrc_nodata_mean`, `study_cells_jrc_nodata_gt50` in `water_qa.csv`) and per county (`qa/water_jrc_nodata_by_county.csv`, top 20 in the log); decide from it before the full run |

## Order

1. Scale review of each stage (above) and a resource estimate per job (memory, time, disk). Done 2026-10-23.
2. Trial (1960 only, v1; prediction timed on 3 strips, nothing written): measures time and memory
   (`docs/runbooks/Running_CONUS.md`, step 0). Adjust the resources in `sbatch/submit_conus.sh` from it.
3. Pilot: CONUS cutout for 1920, 1960, 2010 + water mask + distances; census input on 2010 polygons; split
   table (`configs/conus_split.csv`, made 2026-10-23); per-year features, train (v1, v2), predict, tract validation.
4. Review time, memory and results; then the remaining years (1900-2010), then 2020.
