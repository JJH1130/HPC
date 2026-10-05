# Dasymetric Mapping v3: Design (Chapter 1, Massachusetts test)

Changes from v2 (`docs/dasymetric_v2.md`). Everything not mentioned stays as in v2:
inputs, counties used (`ok`, `manual_fill`), target `y = log(pop / area_km2)`,
county feature = mean of cell feature, Random Forest with `RandomizedSearchCV`
(`n_iter = 20`) and `GroupKFold(5)` grouped by GISJOIN, mass-preserving
reallocation with `w = exp(ŷ)`, SHAP outputs, map style.

**Purpose:** test the era structure (one model per era, era-specific layers) on
Massachusetts before scaling to CONUS. Sample sizes per era are small (see below),
so v3 checks mechanics, not model quality.

Last updated: 2026-10-06

## Decisions carried over from v2 results

| Decision | Reason |
|---|---|
| **Drop `age`** | Spearman ρ = 0.95 with `year` in the pooled model; mean \|SHAP\| 0.12 and near zero after 1900. Revisit in per-year CONUS models, where `year` is constant within a model. |
| Keep `bui`, `bldg_size`, `mu_ratio` | County-level ρ = 0.98–0.99 in Massachusetts, but only 22 counties move together. Re-check on CONUS before dropping. Interpret **grouped** SHAP for now. |
| Keep `dist_built` | Third-largest mean \|SHAP\| (0.39); weakened straight county boundaries in 1810. |
| No fold changes | Large 1810 Maine errors come from extreme `dist_built` (38–96 km vs ≤ 7 km elsewhere), not from fold assignment. |

## Eras

| Era | Census years | Rows (approx.) | Features |
|---|---|---|---|
| E1 | 1810–1930 (13 years) | 188 (20 counties in 1810, 14 after) | `bui`, `bldg_size`, `mu_ratio`, `dist_built`, `year` |
| E2 | 1940–1990 (6 years) | 84 | E1 + Land_Use features |
| E3 | 2000–2020 (3 years) | 42 | E2 + `ntl` |

- One model per era, trained on that era's county-years pooled (with `year`).
- Each census year is predicted with its own era's model.
- 1990 is in E2: NTL starts in 1992.
- Era boundaries and feature lists live in `configs/model.yaml` (no hard-coded years).

## New features

### Land_Use (E2, E3)

Cell-level, from the eight HISDAC land-use count layers (cumulative counts per
class). Shares rather than raw counts, to avoid duplicating `bui`.

| Feature | Definition (cell, year Y) | Group |
|---|---|---|
| `res_share` | (RO + RI) / LU_total if LU_total > 0, else 0 | Land use |
| `rent_share` | RI / (RO + RI) if RO + RI > 0, else 0 | Land use |

`LU_total` = sum of all eight classes (A, C, GV, I, RC, RI, RO, VL). County feature
= mean over the county's cells, as for all features.

### NTL (E3)

| Feature | Definition | Group |
|---|---|---|
| `ntl` | Harmonized NTL digital number (0–63) of the 1 km cell containing the 250 m cell | Lights |

Source: Li, Zhou, Zhao & Zhao (2020), *A harmonized global nighttime light dataset
1992–2018*, Scientific Data 7: 168 (extended release). Files:
`/projects/jaju1407/data/raw/ntl/Harmonized_DN_NTL_{YEAR}_*.tif`
(2000 and 2010 `calDMSP`, 2020 `simVIIRS`).

Notes:
- EPSG:4326, 30 arc-seconds, uint8, no nodata (0 = dark or water).
- **Resampling `nearest`**: NTL is an intensity, not a count, so each 250 m cell
  takes the value of its 1 km parent; values are not split.
- The 2010 file's grid origin is offset by half a cell from 2000 and 2020; each
  file is warped with its own geotransform.
- DMSP saturates at 63 in dense urban cores; `bui` carries within-core variation.
- 2020 is VIIRS converted to DMSP-like values; a 2010→2020 change may partly
  reflect the sensor switch (limitation to note).

## Cutout update (before training)

Add NTL to `configs/study_area.yaml`:
- path pattern `Harmonized_DN_NTL_{YEAR}_*.tif`, years 2000, 2010, 2020,
  `resampling: nearest`, dtype int16.
- Cut only the new layer; existing cutouts stay.

QA for NTL:
- Value range 0–63 inside the window.
- Alignment: in a 20 km box around downtown Boston (lon −71.06, lat 42.36), the
  location of the brightest cells should match across 2000, 2010, 2020 (report
  the centroid of cells with DN ≥ 60 per year; shifts should be well under 1 km).
- Spearman correlation between `ntl` and `bui` over cells with `zone > 0`, per year.

## Model training

Per era, same as v2:
- Collinearity check (Spearman, |ρ| > 0.8 reported).
- Folds: reuse v2's GISJOIN → fold mapping (`v2/model/folds.csv`), filtered to the
  era's rows, so v2 and v3 can be compared on identical folds.
- Hyperparameter search space unchanged.

## SHAP

Per era: per-feature, grouped (Building: `bui`, `bldg_size`, `mu_ratio`;
Settlement context: `dist_built`; Land use: `res_share`, `rent_share`;
Lights: `ntl`; Period: `year`) and by year within the era.

## Comparison with v2

For each era, on the same rows and folds:

| Check | Expectation |
|---|---|
| CV RMSE and R² (era rows only) | v3 era model vs v2 pooled-model predictions for the same rows |
| Grouped SHAP | Land use and Lights take a visible share in E2 and E3 |
| Mass preservation | All county-years < 1e-6 |
| Maps | 1810, 1950, 2020 quick-looks; side-by-side v2 vs v3 for 2020 |

Expect noisy CV in E3 (42 rows, 14 groups). Do not tune or drop features on
v3 Massachusetts results alone.

## Outputs

`/scratch/alpine/jaju1407/hisdac/dasymetric/massachusetts/v3/{E1,E2,E3}/` with the
v2 layout per era, plus `v3/predictions/pop_{YEAR}.tif` for all years. Copy small
files and PNGs to `results/dasymetric/massachusetts/v3/`. Keep v1 and v2 outputs
unchanged.

## Open items

- [ ] Scale to CONUS (per-year models where sample size allows; re-check
      collinearity and `age` there).
- [ ] Ascent allocation (submitted).
- [ ] DEM, water, PLURAL when available.
- [ ] Fine-scale validation (tracts, blocks, Census Place Project).
