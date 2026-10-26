# Tract validation of the dasymetric outputs (Massachusetts)

Checks the 250 m population predictions against NHGIS census tracts, which the model never
sees (it is trained on counties only). Compared with a simple areal-weighting baseline.
Code: `src/validation/tract_validate.py`; job: `sbatch/validate_tract.sh`; steps:
`docs/runbooks/Validating_Tracts.md`. `--version` picks the dasymetric version, so later
versions (v4, ...) reuse the same step.

Last updated: 2026-10-13

## Inputs

| Item | Path |
|---|---|
| Predictions | `$HISDAC_SCRATCH/dasymetric/massachusetts/<version>/predictions/pop_{YEAR}.tif` (float32, NoData −9999 outside used counties) |
| Reallocation QA | `$HISDAC_SCRATCH/dasymetric/massachusetts/<version>/qa/reallocation_qa.csv` (county pop, `zone_id`, `n_masked` per county-year; versions without a water mask, e.g. v2, have no `n_masked` → taken as 0 and logged as "no water mask") |
| County zones | `$HISDAC_SCRATCH/cutouts/massachusetts/zones/zones_{YEAR}.tif` + `.csv` (the grid the predictions are on) |
| Tracts | `/projects/jaju1407/data/processed/tract/tracts_{YEAR}.gpkg` (`docs/tract_preprocessing.md`) |
| Tract coverage | `results/tract/coverage_by_county_MA.csv` |

Years: 1910, 1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020 (1920 has no
Massachusetts tracts).

## Method (per year)

1. **Tracts used:** Massachusetts only (GISJOIN prefix `G250`), `status = ok`, `pop` not
   empty. Reprojected to the grid CRS.
2. **Rasterize** all Massachusetts tracts onto the cutout grid: a cell belongs to the tract
   that contains its centre (`all_touched = False`).
3. **Model:** tract pop = sum of predicted cell pop over the tract's cells.
4. **Baseline (areal weighting):** each county's pop spread evenly over the cells the model
   could give people to — cells with a prediction > 0, i.e. the county's cells minus the
   v3.1 water mask (the model's weights `exp(y_hat)` are always > 0, so a 0 cell is a
   masked cell; checked against `n_masked`). Summed to tracts the same way.
5. **Tracts evaluated:** only tracts whose cells all lie in one used county. Flags (in
   `tract_errors_{YEAR}.csv`; flagged tracts are skipped):
   - `no_cells`: no cell centre inside the tract (very small tract)
   - `multi_county`: cells in more than one county zone
   - `outside_model`: some cells have no prediction (county not used, or outside the zones)
   - `not_ok`: tract `status` is not `ok` or `pop` is empty
6. **Metrics** for the model and the baseline, on three subsets: `all`, `non_small`
   (≥ 4 cells) and `small` (< 4 cells, i.e. under 0.25 km²):
   - `n`, `rmse`, `mae` (people per tract)
   - `mdape`: median of |pred − obs| / obs × 100 (tracts with obs > 0)
   - `r2_log`: 1 − SS_res / SS_tot on log(pop + 1)
   - `r2_logdens`: the same R2 on log(density + 1), density = tract pop / area of its cells
     (n_cells × 0.0625 km²), people/km². Tracts are drawn to hold similar populations, so log(pop)
     varies little across tracts and `r2_log` is mostly negative; density varies far more and tests
     the spatial contrast. (`mdape_logdens`, MdAPE on log density, is in the CSVs of runs up to job
     33924857; dropped 2026-10-13, `r2_logdens` kept.)
   - `pop_share`: observed pop of the evaluated tracts / Massachusetts county total

Partial coverage (e.g. Boston-only tracts in 1910–1960): only the covered tracts are compared;
`coverage` per county-year comes from `coverage_by_county_MA.csv` and is listed in `qa_totals.csv`.

## Totals QA (`qa_totals.csv`)

One row per check: `year, county_gisjoin, name, check, coverage, expected, value, rel_diff,
flag` (`flag` = rel_diff > 0.1 %).

| `check` | For | expected → value |
|---|---|---|
| `county_cells` | every used county-year | county pop → sum of predicted cells (already guaranteed by predict.py; re-checked) |
| `masked_cells` | every used county-year | `n_masked` (reallocation QA) → cells with prediction 0 |
| `tracts_obs` (a) | full-coverage county-years | county pop → sum of observed tract pop |
| `tracts_model` (b) | full-coverage county-years | county pop → sum of predicted pop over cells inside any tract |
| `tracts_baseline` (c) | full-coverage county-years | county pop → same for the baseline |
| `partial_coverage` | other county-years with tracts | `value` = coverage share; no comparison |

Full coverage = `0.999 <= coverage <= 1.001`. The job writes everything, then **stops with an
error if any `tracts_model` or `tracts_baseline` row is flagged** (cells lost in
rasterization would bias every tract comparison). Other flags are reported, not fatal.

## Outputs

`results/validation/massachusetts/<version>/`:

| File | Content |
|---|---|
| `tract_errors_{YEAR}.csv` | every Massachusetts tract: `GISJOIN, county_gisjoin, status, flag, n_cells, small, pop_obs, pop_model, pop_baseline, lon, lat` (lon/lat = WGS84 representative point, to look a tract up) |
| `metrics_by_year.csv` | `year, method, subset, n, pop_share, rmse, mae, mdape, r2_log, r2_logdens` (CONUS: + `part`; from 2026-10-27 + `area_share` and the density subsets `dens_0_50`, `dens_50_500`, `dens_500_2000`, `dens_2000_plus` = observed pop / (n_cells x 0.0625 km2) in people per km2; `area_share` = subset tract area / evaluated tract area of the part) |
| `qa_totals.csv` | totals QA above |
| `tract_validation_{YEAR}.png` | 1940, 1970, 2020: map of the model's % error by tract (blue = under, red = over, clipped at ±100 %; grey = not evaluated) and observed vs predicted scatter (model and baseline, log axes) |

## Results

### v3_1 (job 33913781, code d2e2e4e, reviewed 2026-10-13; before the density metric)

- Totals QA: 546 rows, 0 flagged. All 71 fully tracted county-years sum to the county pop for
  observed tracts, model and baseline (no cells lost in rasterization).
- The model beats areal weighting in every year and metric (RMSE roughly 1/2–1/3 of the baseline's).

  | Year | Tracts | MA pop share | Model MdAPE | Baseline MdAPE |
  |---|---|---|---|---|
  | 1910 | 121 | 19 % | 62.5 % | 69.4 % |
  | 1940 | 183 | 20 % | 43.6 % | 70.8 % |
  | 1970 | 1,048 | 92 % | 32.1 % | 79.2 % |
  | 1990 | 1,311 | 100 % | 28.0 % | 74.1 % |
  | 2000 | 1,361 | 100 % | 46.5 % | 72.4 % |
  | 2020 | 1,612 | 100 % | 44.0 % | 71.1 % |

- Best in 1970–1990; the jump at 2000 matches the E3 era boundary (E3 = 2000–2020, 42 training
  rows, high y_hat floor; `docs/open_items.md`, Dasymetric v3).
- Maps: the model is too flat — rural tracts over-predicted (western MA, 2020), dense cores
  under-predicted (Boston 1940 core blue, West Roxbury/Hyde Park red).
- Small tracts (< 4 cells, 36–52 per year): MdAPE 57–64 % vs 27–44 % for the others.
- `r2_log` negative in most years (see the density metric above for why).
- Outlier: **1940 tract `G2500250A0003`** (Suffolk): observed 6,960, model 81, baseline 5,163
  (15 cells). Likely buildings demolished since 1940 and so missing from HISDAC (built from
  present-day records). Location to check from the new `lon`/`lat` columns after the rerun. The
  same GISJOIN in 1910: observed 5,624, model 2,816 (10 cells).

### v2 vs v3_1 (jobs 33917610 / 33917609, code b511530, reviewed 2026-10-13)

v2 first failed (job 33915573, no `n_masked` column; fixed). Totals QA 546 rows, 0 flagged for both
(v2: no cell with prediction 0). Model, all tracts:

| Year | MdAPE v2 | MdAPE v3_1 | MdAPE baseline | R² log dens. v2 | v3_1 | baseline |
|---|---|---|---|---|---|---|
| 1910 | 60.4 | 62.5 | 69.4 | −0.15 | −0.13 | −0.52 |
| 1930 | 46.5 | 52.6 | 64.4 | −0.28 | −0.31 | −0.43 |
| 1940 | 49.2 | 43.6 | 70.8 | −0.17 | 0.03 | −1.75 |
| 1950 | 51.7 | 38.0 | 79.2 | 0.68 | 0.78 | −0.32 |
| 1960 | 49.5 | 36.7 | 81.1 | 0.67 | 0.82 | −0.50 |
| 1970 | 47.0 | 32.1 | 79.2 | 0.73 | 0.84 | −0.09 |
| 1980 | 45.4 | 29.8 | 77.9 | 0.73 | 0.85 | 0.00 |
| 1990 | 45.8 | 28.0 | 74.1 | 0.73 | 0.86 | 0.08 |
| 2000 | 45.2 | 46.5 | 72.4 | 0.75 | 0.77 | 0.13 |
| 2010 | 44.8 | 45.1 | 71.1 | 0.70 | 0.71 | 0.11 |
| 2020 | 45.4 | 44.0 | 71.1 | 0.67 | 0.69 | 0.10 |

1. **E3 floor hypothesis rejected.** MdAPE 2000–2020: v2 ~45 %, v3_1 44–46 % (the same), although
   v2 has a much lower y_hat floor. v3_1 beats v2 only in 1940–1990 (28–44 % vs 45–52 %): the gain
   from Land Use in E2 disappears in E3. R² on log density: v3_1 0.78–0.86 (1950–1990) vs
   0.69–0.77 (2000–2020); v2 0.67–0.75; baseline about 0. Next: v3.2 (`docs/dasymetric_v3_2.md`).
2. **1940 outlier `G2500250A0003`** (obs 6,960; v3_1 81, v2 18; baseline 5,163) lies at 42.374,
   −71.018 = East Boston / Logan Airport: a residential area later taken by the airport, so its
   buildings are missing from HISDAC (survivorship: HISDAC is built from present-day records).
3. 1910 and 1930 cover only Boston (18–19 % of MA pop); both versions have negative R² there.

### E3 experiments, 2000–2020 (v3_2 job 33920631, v3_3 job 33924857)

Model, all tracts:

| Year | MdAPE v2 | v3_1 | v3_2 (no ntl) | v3_3 (E2 params) | R² log dens. v3_1 | v3_2 | v3_3 |
|---|---|---|---|---|---|---|---|
| 2000 | 45.2 | 46.5 | 45.2 | **43.0** | 0.772 | 0.777 | **0.811** |
| 2010 | 44.8 | 45.1 | 45.5 | **41.8** | 0.711 | 0.711 | **0.745** |
| 2020 | 45.4 | 44.0 | 45.9 | **40.6** | 0.694 | 0.683 | **0.723** |

- v3_2: dropping `ntl` changes nothing at tract level (and worsens the E3 county CV).
- v3_3: E2's hyperparameters (max_features 1.0) improve every year by 3.4–3.5 pt MdAPE and
  0.03–0.04 R², the same in non-small tracts, **although the E3 county CV is worse** (R² 0.646 vs
  0.657, RMSE 0.543 vs 0.500). County CV on 42 rows did not pick the better cell allocation.
- Still 12+ pt above E2's 1990 (28 %); the cell y_hat floor stays at ~3.79.

### v3_4: E2 and E3 merged (job 33928617, code 8599fa3)

MdAPE (model, all tracts, %):

  | Year | v2 | v3.1 | v3.3 | **v3.4** | baseline | R² log dens. v3.1 | **v3.4** |
  |---|---|---|---|---|---|---|---|
  | 1940 | 49.2 | 43.6 | | 43.3 | 70.8 | 0.030 | 0.031 |
  | 1950 | 51.7 | 38.0 | | 40.4 | 79.2 | 0.783 | 0.775 |
  | 1960 | 49.5 | 36.7 | | 37.2 | 81.1 | 0.815 | 0.799 |
  | 1970 | 47.0 | 32.1 | | 33.3 | 79.2 | 0.844 | 0.827 |
  | 1980 | 45.4 | 29.8 | | 32.2 | 77.9 | 0.846 | 0.829 |
  | 1990 | 45.8 | 28.0 | | 30.4 | 74.1 | 0.861 | 0.849 |
  | 2000 | 45.2 | 46.5 | 43.0 | **29.8** | 72.4 | 0.772 | **0.873** |
  | 2010 | 44.8 | 45.1 | 41.8 | **30.5** | 71.1 | 0.711 | **0.803** |
  | 2020 | 45.4 | 44.0 | 40.6 | **30.9** | 71.1 | 0.694 | **0.774** |

- 2000–2020 drops to 30–31 % (E2's 1990 level), R² log density 0.77–0.87; 1940–1990 costs 0–2.4 pt.
  The E3 gap was a small-sample problem (42 rows).
- **CONUS implication: enough training rows, not pooled years.** CONUS keeps per-year models (needed
  for per-year SHAP); each has ~3,000 counties, far more than v3.4's 126 rows. Check at CONUS: compare
  per-year vs pooled models on tract validation.

## Open items

- [x] First run (v3_1).
- [x] Rerun v3_1 (density metric, lon/lat) and v2; compare (above).
- [x] Locate 1940 `G2500250A0003`: East Boston / Logan Airport (survivorship).
- [x] v3_2 (2000–2020) vs v3_1: same (MdAPE 45–46 %, R² log density 0.68–0.78; job 33920631;
  `docs/dasymetric_v3_2.md`, Result).
- [x] v3_3 (2000–2020) vs v3_1: better (MdAPE 40.6–43.0 %, R² log density 0.72–0.81; job 33924857;
  `docs/dasymetric_v3_3.md`, Result).
- [x] v3_4 (E2 + E3 merged, 1940–2020; job 33928617): 2000–2020 MdAPE 29.8 / 30.5 / 30.9 % → small-sample
  problem (`docs/dasymetric_v3_4.md`, Result). Massachusetts experiments closed.
- [ ] CONUS: compare per-year vs pooled models on tract validation.

**Provisional:** conclusions about the 2000–2020 (E3) gap are provisional. PLURAL (urban–rural
continuum, from Siqiao) is not yet a feature and may address the remaining pattern of rural tracts
over-predicted and urban tracts under-predicted.
