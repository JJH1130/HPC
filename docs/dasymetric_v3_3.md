# Dasymetric Mapping v3.3: E3 with E2's hyperparameters (diagnostic, Massachusetts)

Diagnostic only. Same as v3.1 (`docs/dasymetric_v3_1.md`): E3 **with** `ntl`, same eras, folds
(`folds_from: v2`) and water mask. One change: **E3's hyperparameters are fixed** to E2's best
from v3.1/v3.2 instead of searched:

| | n_estimators | max_depth | min_samples_leaf | max_features |
|---|---|---|---|---|
| v3.3 E3 (fixed) = E2 best (v3.1, v3.2) | 200 | 20 | 2 | 1.0 |
| v3.1 E3 (searched) | 300 | 15 | 2 | 0.33 |
| v3.2 E3 (searched, no ntl) | 1000 | 20 | 2 | sqrt |

Settings: `configs/model.yaml` (`version: v3_3`, `compare_with: v3_1`, E3 `params:`). With all four
parameters fixed, train.py's search has one candidate (`train.py`, era `params:`).

Last updated: 2026-10-13

## Question

Does `max_features` chosen by a noisy 42-row county CV (2–3 of 8 features per split: 0.33 in v3.1,
sqrt in v3.2) flatten the cell allocation? v3.2 showed `ntl` is not the cause: E3 tract MdAPE
2000–2020 stayed at ~45 % (v3.1 44–46 %, v3.2 45–46 %), while E2 reaches 28 % in 1990
(`docs/validation_tract.md`).

## Run

Stages 1–3 as in v3.2 (E1 and E2 retrained, identical to v3.1), predict 2000, 2010, 2020 only, then
`validate_tract --version v3_3 --years 2000 2010 2020`. Steps: `docs/runbooks/Running_Dasymetric.md`,
section "v3.3".

## Reading the result

- Tract MdAPE 2000–2020 drops from ~45 % toward 30 % → the hyperparameters, not the features, flatten
  E3; county-level CV is then not a good selector for cell allocation. This matters for CONUS
  (choose hyperparameters with a cell/tract-level check, or fix them across eras).
- No change → hyperparameters are not the cause either; remaining suspects are the E3 sample
  (42 rows) and the 2000+ data.
- The E3 county CV of v3.3 vs v3.1 (same folds and rows) shows how much county CV the fixed
  parameters give up.

## Open items

- [ ] Run v3.3 and compare with v3.1 (county CV E3; tract MdAPE and R² on log density, 2000–2020).
