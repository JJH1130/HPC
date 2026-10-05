# Open Items and Decisions

Pending items and important decisions for this project. This file is the
durable record: Claude's local memory does not move between computers, so any
important decision saved to memory is also written here.

Last updated: 2026-10-06 (v2 first run)

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

### Dasymetric v2 design delivered

- **Status:** design delivered (`docs/dasymetric_v2.md`) and implemented.
  First Alpine run passed 2026-10-05 (jobs 33445813-33445815); results are in
  `docs/runbooks/Running_Dasymetric.md` (Notes). Waiting on the user's review.
- Run results that need a decision: the Building features are still highly
  correlated (|rho| 0.98-0.99, against the design's "none above 0.8"), and
  age-year rho is 0.950 with age at mean |SHAP| 0.12.
- Focal (neighborhood) means were rejected in the design; v2 adds
  `bldg_size` and `dist_built` instead, drops `bupl`, `bupr`, `bua`, and uses
  SHAP (per feature, grouped by concept, by year) as the main importance.
- v1 outputs (scratch `.../dasymetric/massachusetts/v1/`,
  `results/dasymetric/massachusetts/v1/`) are read only and must not change.
- Open after the run: keep or drop `age` (correlation with `year` + SHAP);
  see "Open items" in `docs/dasymetric_v2.md`.

## Decision log

| Date | Decision |
|---|---|
| 2026-10-06 | Keep nominal counties until the source for pre-1990 2010-standardized counties is confirmed. |
| 2026-10-06 | No dasymetric code changes until the v2 design is given. (Lifted the same day: design delivered.) |
| 2026-10-06 | Implement v2 per `docs/dasymetric_v2.md`: v1 code structure kept, features and their SHAP groups in `configs/model.yaml`, v1 outputs read only. |
| 2026-10-06 | Important decisions saved to Claude's memory are also recorded in this file. |
