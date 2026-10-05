# Dasymetric Mapping v2: Design (Chapter 1, Massachusetts test)

Changes from v1 (`docs/dasymetric_v1.md`). Everything not mentioned here stays as
in v1: inputs, counties used (`ok`, `manual_fill`), target `y = log(pop / area_km2)`,
pooled 22-year model, Random Forest with `RandomizedSearchCV` and `GroupKFold(5)`
grouped by GISJOIN, mass-preserving reallocation with `w = exp(ŷ)`.

Last updated: 2026-10-06

## Why v2

v1 ran end to end (mass preserved for all 314 county-years, CV R² 0.68), but:

1. **Unbuilt cells all receive the same weight.** Their features are all 0, so
   their prediction is identical. In 1810, inland Maine has almost no building
   records, so each county's population spreads evenly and county boundaries show
   as straight lines on the map.
2. **v1 features are highly collinear.** BUI, BUPL, BUPR and BUA carry nearly the
   same information (about 3.3% non-zero cells each in 1940). This makes SHAP and
   permutation importance hard to interpret.

Neighborhood means (focal BUI) were considered and **rejected**: averaged to the
county, a focal mean is almost equal to the county mean of the raw layer, so the
county-level model cannot learn their separate effect, and collinearity becomes
extreme.

## Features (cell level; county feature = mean over the county's cells, as in v1)

Each feature carries one concept. Overlapping layers are turned into ratios.

| Feature | Definition (cell, year Y) | Concept | Group (for grouped SHAP) |
|---|---|---|---|
| `bui` | BUI_Y | Building intensity | Building |
| `bldg_size` | BUI_Y / BUPL_Y if BUPL_Y > 0, else 0 | Mean building size | Building |
| `mu_ratio` | BUPR_Y / BUPL_Y if BUPL_Y > 0, else 0 | Multi-unit share | Building |
| `age` | Y − FBUY if 0 < FBUY ≤ Y, else 0 | Years since first settlement | Settlement context |
| `dist_built` | Euclidean distance (km) from the cell centre to the nearest cell with BUA_Y = 1; 0 for built cells | Remoteness from settlement | Settlement context |
| `year` | Y | Period | Period |

Dropped from v1: `bupl`, `bupr`, `bua` (covered by `bui` and the ratios).

`dist_built` notes:
- Compute on the full cutout window (it includes HISDAC values outside the study
  counties), so cells near the Massachusetts border see built cells across it.
  Then keep only cells with `zone > 0`.
- Use `scipy.ndimage.distance_transform_edt` on `BUA_Y == 0`, times 0.25 km.
- If a year has no built cell in the window, stop with an error.
- At county level, the mean of `dist_built` describes how dispersed settlement is
  within the county, which the county-level model can learn.

`age` and `year` are expected to be correlated in the pooled model (maximum
possible age grows with year). Keep both in v2 and decide from the checks below.

## Collinearity check (before training)

- Compute the Spearman correlation matrix of the county-level features over all
  training rows. Save as `model/feature_correlation.csv` and a heatmap PNG.
- Log every pair with |ρ| > 0.8. Do not drop features automatically.

## Model training

Same as v1. Also save the **fold assignment** (GISJOIN → fold) to
`model/folds.csv` and reuse it so v1 and v2 can be compared on identical folds.
If v1 did not save folds, recompute v1's CV metrics with the v2 folds.

## Explanation: SHAP

Replaces permutation importance as the main importance measure.

- `shap.TreeExplainer` on the final RF, explaining the county-level training rows
  (314 county-years).
- Save `model/shap_values.csv` (one row per county-year, one column per feature,
  plus GISJOIN, year, y, ŷ).
- Report:
  - mean |SHAP| per feature (`model/shap_importance.csv`),
  - **grouped** mean |SHAP|: sum SHAP values within each group (Building,
    Settlement context, Period) per row, then mean |·| (`model/shap_importance_grouped.csv`),
  - mean |SHAP| per feature **by year**, to show how drivers change over time
    (`model/shap_by_year.csv`).
- Plots: SHAP summary (beeswarm) and a by-year line chart of mean |SHAP| per
  feature. Use a log x-axis only if the plot is unreadable otherwise.

## Maps

Quick-look PNGs for 1810, 1900, 2020:
- Value: population per 250 m cell (unchanged). Title states "per 250 m cell".
- Colour: log scale (display only).
- Background: state boundaries in light grey, from `counties_2020.gpkg` dissolved
  by state (no web tiles; compute nodes may lack internet). Show neighbouring
  states lightly so the study area has context.
- Axes: longitude and latitude in degrees, or no axes with a scale bar. No
  projection name in the axis label.
- Also save a v1-vs-v2 side-by-side PNG for 1810.

## Outputs

Under `/scratch/alpine/jaju1407/hisdac/dasymetric/massachusetts/v2/` with the
same layout as v1, plus the new files above. Copy small files and PNGs to
`results/dasymetric/massachusetts/v2/`. Keep v1 outputs unchanged.

## Comparison with v1 (report in the run log and runbook)

| Check | Expectation |
|---|---|
| CV RMSE and R² (same folds) | v2 not worse than v1 |
| 1810 map | Straight county boundaries in inland Maine weaken; population concentrates near coast and rivers where buildings exist |
| Mass preservation | Unchanged (< 1e-6) |
| Correlation | No |ρ| > 0.8 pair among Building features; report age–year |

## Open items

- [ ] Decide on `age` from correlation and SHAP results.
- [ ] Land_Use model for 1940–2020.
- [ ] DEM, water, PLURAL when available.
- [ ] SHAP on cells (for maps of local drivers), later.
