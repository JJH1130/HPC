# Dasymetric Mapping v1: Design (Chapter 1, Massachusetts test)

Design for county-level aggregation, model training, cell-level prediction and
mass-preserving reallocation. v1 is a pipeline test on Massachusetts; the same
code must later run on CONUS by changing configuration only.

Last updated: 2026-10-02

## Scope of v1

| Item | v1 choice | Later |
|---|---|---|
| Study area | Massachusetts (`configs/study_area.yaml`) | CONUS |
| Years | 22 census years, 1810–2020, **pooled into one model** (14–20 counties per year is too few for per-year models) | One model per year (CONUS) |
| Features | HISDAC building layers only (no Land_Use) | Add Land_Use (1940+), DEM, water, NTL, land cover, PLURAL |
| Model | Random Forest | LightGBM, XGBoost, CatBoost, ensembles |
| Counties | Nominal (each year's own counties) | Pending decision on 2010-standardized units |

## Inputs

| Input | Path |
|---|---|
| Layer cutouts | `/scratch/alpine/jaju1407/hisdac/cutouts/massachusetts/layers/{LAYER}/{YEAR}_{LAYER}.tif` (FBUY: single file) |
| Zone grids | `.../massachusetts/zones/zones_{YEAR}.tif` (0 = outside selected counties) |
| Zone tables | `.../massachusetts/zones/zones_{YEAR}.csv` (zone_id → GISJOIN, pop, status, area_km2) |

All rasters share one grid (HISDAC 250 m, ESRI:102039). Every stage works only
on cells with `zone > 0`.

## Counties used

| `status` | Training | Reallocation |
|---|---|---|
| `ok`, `manual_fill` | Yes | Yes |
| `nodata_unenumerated`, `nodata_zero` | No | No (output cells = NoData) |

## Cell features

Defined first at the cell level. County features are derived from them (next
section) so that the model sees the same quantities at both scales.

| Feature | Definition (cell, year Y) |
|---|---|
| `bui` | BUI_Y |
| `bupl` | BUPL_Y |
| `bupr` | BUPR_Y |
| `bua` | BUA_Y (0/1) |
| `mu_ratio` | BUPR_Y / BUPL_Y if BUPL_Y > 0, else 0 (multi-unit proxy) |
| `age` | Y − FBUY if 0 < FBUY ≤ Y, else 0 (years since first settlement) |
| `year` | Y (pooled model only) |

No log transform is applied to features. Tree-based models (RF, LightGBM,
XGBoost, CatBoost) split on value order, so monotonic transforms do not change
them. Revisit only if non-tree models are added.

## County features

County feature = **mean of the cell feature over all cells of the county**
(`zone == county`, including cells with value 0).

Rationale: the target is a density (population per area). All cells have equal
area (0.0625 km²), so a county mean equals the county sum divided by the number
of cells, i.e., a per-area intensity. Sums would scale with county area and would
not match the target. Means also keep county and cell features on the same scale,
which is required because the model is trained on counties and applied to cells.
For `bua`, the county mean is the share of built cells.

## Target

`y = log(pop / area_km2)` per county-year, using the polygon area from the
census preprocessing output. Counties with `pop = 0` are already excluded by status.

## Model training

| Setting | Value |
|---|---|
| Estimator | `sklearn.ensemble.RandomForestRegressor` |
| Search | `RandomizedSearchCV`, `n_iter = 20`, `random_state = 42` |
| CV | `GroupKFold(n_splits = 5)`, **groups = GISJOIN** (all years of a county stay in the same fold) |
| Scoring | `neg_root_mean_squared_error` on `y` |
| Refit | Best parameters refit on all training rows |

Search space:

| Parameter | Candidates |
|---|---|
| `n_estimators` | 200, 300, 500, 800, 1000 |
| `max_depth` | None, 5, 10, 15, 20 |
| `min_samples_leaf` | 1, 2, 4, 8 |
| `max_features` | "sqrt", 0.33, 0.5, 1.0 |

Grouped CV is required because the pooled data contain each county once per year.
Random K-fold would place the same county in training and validation folds and
overstate accuracy. Grouped CV measures performance on unseen counties.

### Model registry

`configs/model.yaml` selects the model (`model: rf`) and holds one search space
per model (`rf`, `lgbm`, `xgb`, `catboost`). Switching models must not require
code changes. XGBoost and CatBoost are not yet in `envs/hisdac/environment.yml`;
add them when first used.

## Prediction and reallocation

For each year Y and each county c with status `ok` or `manual_fill`:

1. Compute cell features for all cells of c.
2. Predict `ŷ` per cell; weight `w = exp(ŷ)` (predicted density, > 0).
3. Reallocate: `pop_cell = pop_c × w_cell / Σ_{cells in c} w`.

Cells of unused counties and cells outside the study counties are NoData.

## Outputs

Under `/scratch/alpine/jaju1407/hisdac/dasymetric/massachusetts/v1/`:

| File | Content |
|---|---|
| `features/county_features.csv` | One row per county-year: GISJOIN, year, n_cells, features, pop, area_km2, y |
| `model/rf.joblib` | Fitted model |
| `model/cv_results.csv`, `model/best_params.json` | Search results |
| `model/metrics.json` | Best CV RMSE (mean, sd across folds), CV R², training RMSE |
| `model/feature_importance.csv` | Impurity importance and permutation importance |
| `predictions/pop_{YEAR}.tif` | Cell population, float32, NoData = −9999 |
| `qa/reallocation_qa.csv` | Per county-year: census pop, sum of cell pop, difference |

Small files (`county_features.csv`, `metrics.json`, `best_params.json`,
`feature_importance.csv`, `reallocation_qa.csv`) are also copied to
`results/dasymetric/massachusetts/v1/` for git. Also save quick-look maps (PNG)
of `pop_1810`, `pop_1900`, `pop_2020` there.

## Checks

- Mass preservation: for every county-year, |Σ pop_cell − pop_c| / pop_c < 1e-6.
- No negative or NaN values in cells with `zone > 0` of used counties.
- Log the number of training rows (expected 314 county-years before status filtering).
- Log CV RMSE per fold.

## Open items

- [ ] Add Land_Use: a second pooled model for 1940–2020, or per-era models.
- [ ] Decide on 2010-standardized counties (NHGIS standardized tables cover 1990–2020 only).
- [ ] Add PLURAL (gridded) once received.
- [ ] Fine-scale validation (tracts 1910+, blocks 2020, Census Place Project 1790–1940).
- [ ] SHAP analysis.
