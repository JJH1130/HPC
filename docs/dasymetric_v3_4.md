# Dasymetric Mapping v3.4: E2 and E3 merged (diagnostic, last Massachusetts experiment)

Diagnostic only. Same as v3.1 (`docs/dasymetric_v3_1.md`: water mask, `folds_from: v2`, model and
search) except the eras: **E2 (1940–1990) and E3 (2000–2020) become one era `E23` (1940–2020)** with
E2's features (no `ntl`), 126 training rows (84 + 42, 14 counties). The hyperparameter search runs as
usual (n_iter 20, 5 folds, the same v2 fold table). E1 is unchanged.

| Era | Years | Features | Rows |
|---|---|---|---|
| E1 | 1810–1930 | bui, bldg_size, mu_ratio, dist_built, year | 188 |
| E23 | 1940–2020 | + res_share, rent_share | 126 |

Settings: `configs/model.yaml` (`version: v3_4`, `compare_with: v3_1`). v3.1 has no `E23`, so the
county-CV comparison runs only for E1 (identical expected); for E23 train.py logs
`compare_with v3_1 skipped` and the comparison is done at tract level.

Last updated: 2026-10-13

## Question

Is the 2000–2020 tract gap a small-sample problem or period-specific? So far (`docs/validation_tract.md`):
E2 reaches 28 % tract MdAPE in 1990, E3 stays at 44–46 % (v3.1, v3.2) or 41–43 % (v3.3, E2's
hyperparameters). Merging gives the 2000–2020 years E2's 84 rows to learn from.

- 2000–2020 tract MdAPE drops toward ~30 % → small-sample problem (E3's 42 rows).
- Stays at ~41–46 % → period-specific (the 2000+ relation between the features and population differs).
- 1940–1990 should stay near v3.1's E2 (28–44 %); a clear loss there is the cost of merging.

## Run

Stages 1–3, predict 1940–2020 (`--years 1940 1950 1960 1970 1980 1990 2000 2010 2020`), then
`validate_tract --version v3_4` for the same years. Steps: `docs/runbooks/Running_Dasymetric.md`,
section "v3.4".

## Provisional

Conclusions on the E3 gap are provisional: PLURAL (urban–rural continuum, from Siqiao) is not yet
included and may address the remaining rural-over / urban-under pattern.

## Result (jobs 33928611 / 33928613 / 33928615 + validate_tract 33928617, code 8599fa3, 2026-10-13)

- Features: E23 126 rows, 14 counties. Train: E1 CV identical to v3.1; E23 searched params = E2's
  (200 / 20 / 2 / 1.0), CV RMSE 0.554 / R² 0.727 (other rows than v3.1's E2/E3, so not directly
  comparable); `compare_with v3_1 skipped` for E23 as expected. Predict 1940–2020: mass check 126
  county-years 0 fail. Tract totals QA 488 rows, 0 flagged.
- Tract MdAPE (model, all tracts, %):

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

- **2000–2020: MdAPE 44–46 % → 30–31 %** (−14 to −17 pt), MAE ~2,200–2,450 → 1,690–1,730 people per
  tract, R² on log density 0.77–0.87 (best of all versions), i.e. at E2's 1990 level.
- Cost of merging in 1940–1990: +0 to +2.4 pt MdAPE (largest 1980: 29.8 → 32.2), R² −0.01 to −0.02.
- Cell y_hat floor 2000–2020: 3.79 (E3) → 3.24.
- **The E3 gap was a small-sample problem** (42 rows, 14 counties × 3 years), not period-specific.
  The v3.3 hyperparameter effect (3–4 pt) is a symptom of the same small sample.
- **CONUS implication: enough training rows, not pooled years.** CONUS keeps per-year models (needed
  for per-year SHAP); each has ~3,000 counties, far more than v3.4's 126 rows. Check at CONUS: compare
  per-year vs pooled models on tract validation.
- **Provisional:** PLURAL (urban–rural continuum, from Siqiao) is not yet included and may address the
  remaining rural-over / urban-under pattern.
- Massachusetts experiments are closed with v3.4.

## Open items

- [x] Run v3.4 and compare with v3.1 and v3.3 (above).
