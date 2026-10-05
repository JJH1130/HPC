# Open Items and Decisions

Pending items and important decisions for this project. This file is the
durable record: Claude's local memory does not move between computers, so any
important decision saved to memory is also written here.

Last updated: 2026-10-06

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

### Dasymetric v2 design

- **Status:** waiting on the user's v2 design, based on review of v1 results.
- Expected topics: neighborhood (surrounding-cell) features, and variable
  importance computed with the county grouping used for CV.
- **Until the design arrives:** do not write or change dasymetric code
  (`src/dasymetric/`, `configs/model.yaml`, `sbatch/dasymetric_*.sh`).

## Decision log

| Date | Decision |
|---|---|
| 2026-10-06 | Keep nominal counties until the source for pre-1990 2010-standardized counties is confirmed. |
| 2026-10-06 | No dasymetric code changes until the v2 design is given. |
| 2026-10-06 | Important decisions saved to Claude's memory are also recorded in this file. |
