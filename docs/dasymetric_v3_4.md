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

## Open items

- [ ] Run v3.4 and compare with v3.1 (1940–2020) and v3.3 (2000–2020) at tract level.
