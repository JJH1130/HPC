# Dasymetric Mapping v3.2: E3 without night lights (Chapter 1, Massachusetts test)

One change to v3.1 (`docs/dasymetric_v3_1.md`): era **E3 (2000–2020) uses the E2 feature set**,
i.e. no `ntl`. Everything else is as in v3.1: eras, E1 and E2 features, water mask, `folds_from: v2`,
model and search space. Settings: `configs/model.yaml` (`version: v3_2`, `compare_with: v3_1`).

Last updated: 2026-10-13

## Why

Tract validation (`docs/validation_tract.md`, jobs 33917609 / 33917610):

- v3.1 beats v2 only in 1940–1990 (MdAPE 28–44 % vs 45–52 %). In 2000–2020 both are at ~45 %
  (v3.1 44–46 %), and R² on log tract density drops from 0.78–0.86 (1950–1990) to 0.69–0.77.
- The E3 "y_hat floor" explanation is rejected: v2 has a much lower floor but the same 2000–2020 error.
- So the E2 gain (Land Use) disappears in E3. E3 differs from E2 by adding `ntl` and by its
  small sample (42 rows, 14 counties). v3.2 removes `ntl` to test whether it is the cause.

| Era | Years | Features (v3.2) |
|---|---|---|
| E1 | 1810–1930 | bui, bldg_size, mu_ratio, dist_built, year (unchanged) |
| E2 | 1940–1990 | + res_share, rent_share (unchanged) |
| E3 | 2000–2020 | **same as E2** (v3.1: + ntl) |

## Run

- Stages 1–2 run for all eras (E1 and E2 are retrained with the same settings and folds, so their CV
  should equal v3.1's; `compare_v3_1` checks this). Stage 3 predicts **2000, 2010, 2020 only**
  (`--years 2000 2010 2020`).
- Tract validation: `validate_tract --version v3_2 --years 2000 2010 2020 --map-years 2020`.
- Compare with v3.1 for 2000–2020: county CV (E3, same folds and rows) and tract MdAPE /
  R² on log density.

Steps: `docs/runbooks/Running_Dasymetric.md`, section "v3.2".

## Reading the result

- v3.2 E3 clearly better than v3.1 (towards the 1990 level) → `ntl` hurts with 14 counties; keep it out.
- About the same → `ntl` is not the cause; next suspects are the E3 sample size and the Land Use
  layers after 2000 (e.g. pooling E2 + E3).

## Result (jobs 33920625 / 33920627 / 33920629 / 33920631, code a0dd6b9, 2026-10-13)

- E1 and E2 CV identical to v3.1 (as expected). Mass check 42 county-years, 0 fail; tract totals QA
  210 rows, 0 flagged.
- E3 county CV (same folds and rows): v3.2 RMSE 0.545 / R² 0.596 vs v3.1 0.500 / 0.657 — without
  `ntl` the county fit is worse.
- Tract MdAPE (all): 2000 45.2 vs 46.5 (v3.1), 2010 45.5 vs 45.1, 2020 45.9 vs 44.0; R² on log
  density 0.777 / 0.711 / 0.683 vs 0.772 / 0.711 / 0.694. Same as v3.1 (and v2).
- Cell y_hat floor unchanged (2020: 3.77 vs 3.78).
- **`ntl` is not the cause** of the 2000–2020 gap. Next: v3.3 (E3 with E2's hyperparameters,
  `docs/dasymetric_v3_3.md`).

## Open items

- [x] Run v3.2 and compare with v3.1 (above).
