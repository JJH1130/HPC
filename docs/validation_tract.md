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
   - `r2_logdens`, `mdape_logdens`: the same R2 and MdAPE on log(density + 1), density =
     tract pop / area of its cells (n_cells × 0.0625 km²), people/km². Tracts are drawn to hold
     similar populations, so log(pop) varies little across tracts and `r2_log` is mostly
     negative; density varies far more and tests the spatial contrast. (A plain % error on
     density equals the % error on pop, since obs and pred share the area, so MdAPE is taken
     on the log.)
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
| `metrics_by_year.csv` | `year, method, subset, n, pop_share, rmse, mae, mdape, r2_log, r2_logdens, mdape_logdens` |
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

### v2

- Job 33915573 (code bb3efee) failed in 1910: v2's `reallocation_qa.csv` has no `n_masked`
  (no water mask). Fixed: missing `n_masked` → 0. Rerun needed.

## Open items

- [x] First run (v3_1).
- [ ] Rerun v3_1 (density metric, lon/lat) and v2; compare.
- [ ] Locate 1940 `G2500250A0003` and confirm the demolition explanation.
