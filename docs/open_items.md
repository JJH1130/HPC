# Open Items and Decisions

Pending items and important decisions for this project. This file is the
durable record: Claude's local memory does not move between computers, so any
important decision saved to memory is also written here.

Last updated: 2026-10-06 (v3 design delivered)

## Open items

### 2010-standardized counties

- **Status:** waiting on source check.
- The advisor suggested using counties standardized to 2010 boundaries.
- NHGIS standardized tables cover only 1990–2020. The source said to cover
  years from 1900 is not yet identified; the user is confirming what it is.
- **Until confirmed:** keep using nominal counties (each year's own
  boundaries), as in `docs/dasymetric_v1.md`.

### PLURAL gridded data

- **Status:** waiting to receive the grid from Siqiao.
- On arrival: check resolution, CRS and year coverage, then add it as a layer
  in `configs/study_area.yaml` (the cutout layer list) per `docs/cutout.md`.

### Dasymetric v2: closed

- Design `docs/dasymetric_v2.md`; first Alpine run passed 2026-10-05 (jobs
  33445813-33445815); results in `docs/runbooks/Running_Dasymetric.md` (Notes).
- Decisions from its results are in the decision log (2026-10-06) and in
  `docs/dasymetric_v3.md`, "Decisions carried over from v2 results".
- v1 and v2 outputs (scratch `.../dasymetric/massachusetts/{v1,v2}/`,
  `results/dasymetric/massachusetts/{v1,v2}/`) are read only and must not change.

### Dasymetric v3 (eras + NTL)

- **Status:** design delivered (`docs/dasymetric_v3.md`), implemented and
  tested on fake data; waiting for the Alpine runs, in this order:
  1. NTL cutout + NTL QA (`docs/runbooks/Making_Cutout.md`, section 7)
  2. v3 features → train → predict (`docs/runbooks/Running_Dasymetric.md`)
- Eras (E1 1810-1930, E2 1940-1990, E3 2000-2020) and their feature lists
  live in `configs/model.yaml`; v3 reuses `v2/model/folds.csv` and compares
  each era model with v2's out-of-fold predictions on the same rows.
- Small samples per era (E3: 42 rows, 14 counties): v3 checks mechanics, not
  model quality. Per the design, do not tune or drop features on v3
  Massachusetts results alone.
- Later (design "Open items"): scale to CONUS (per-year models; re-check
  collinearity and `age` there), Ascent allocation (submitted), DEM, water,
  PLURAL, fine-scale validation.

## Decision log

| Date | Decision |
|---|---|
| 2026-10-06 | Keep nominal counties until the source for pre-1990 2010-standardized counties is confirmed. |
| 2026-10-06 | No dasymetric code changes until the v2 design is given. (Lifted the same day: design delivered.) |
| 2026-10-06 | Implement v2 per `docs/dasymetric_v2.md`: v1 code structure kept, features and their SHAP groups in `configs/model.yaml`, v1 outputs read only. |
| 2026-10-06 | Important decisions saved to Claude's memory are also recorded in this file. |
| 2026-10-06 | From v2 results: **drop `age`** (rho 0.95 with `year`, small SHAP; revisit in per-year CONUS models). |
| 2026-10-06 | From v2 results: **keep `bui`, `bldg_size`, `mu_ratio`** despite county-level rho 0.98-0.99 (only 22 counties in Massachusetts); re-check on CONUS; interpret grouped SHAP for now. |
| 2026-10-06 | From v2 results: **no fold changes**; the 1810 Maine errors come from extreme `dist_built`, not from fold assignment. Keep `dist_built`. |
| 2026-10-06 | v3 per `docs/dasymetric_v3.md`: one model per era, era boundaries and feature lists in `configs/model.yaml`, v2 folds reused; order = NTL cutout + QA, then era training/prediction; v1/v2 outputs read only. |
