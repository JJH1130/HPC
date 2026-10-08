# Open Items and Decisions

Pending items and important decisions for this project. This file is the
durable record: Claude's local memory does not move between computers, so any
important decision saved to memory is also written here.

Last updated: 2026-10-09 (Stefan CSV decision; Ascent allocation approved)

## Open items

### Compute allocation (Ascent)

- **Status:** approved. Slurm account `ucb852_asc1`, 450,000 SU,
  **valid until 2027-10-05**.
- Every `sbatch/*.sh` sets `#SBATCH --account=ucb852_asc1` (before this, jobs
  ran on `ucb-general`). New scripts must carry the same line.
- Before 2027-10-05: renew the allocation, or switch the scripts back to
  `ucb-general` (remove the line); jobs on an expired account are rejected.
- Publications: include the Alpine acknowledgement in
  `docs/acknowledgements.md`.

### 2010-standardized counties

- **Status:** decided 2026-10-09 (see below). Open: ask Stefan whether an
  areally standardized version exists.
- The advisor suggested using counties standardized to 2010 boundaries.
- NHGIS standardized tables cover only 1990–2020. The source said to cover
  years from 1900 is not yet identified; the user is confirming what it is.
- 2026-10-06: received `data/census_std/all_county_census_MSA_full.csv` from
  Stefan Leyk (counties 1900–2010 by 2010 FIPS + 2015 estimate, with CBSA/CSA
  codes). Original publisher to confirm (`docs/data_sources.md`).
- 2026-10-07: values look like each year's count for the county holding that
  FIPS, not areally standardized to 2010 boundaries. Diagnostic
  `src/census/std_county_check.py` (`docs/runbooks/Checking_Std_Counties.md`)
  classifies each county-year as stable / boundary_change / missing against the
  nominal counties. Grouping of changed counties waits for its summary.
- 2026-10-09: result of `std_county_check` job 33505541 (reviewed by the user
  with the advisor; not re-analyzed here):
  - The CSV equals the NHGIS nominal counts: 36,560 of 36,565 county-years
    match (1900–2010). 5 small differences: Morton ND 1900, James City VA
    1910/1920, Fremont ID 1930, Park MT 1980. It is **not** areally
    standardized.
  - Attaching its counts to 2010 polygons misplaces ~10 % of population in
    1900–1910 (counties whose area differs > 5 % from 2010) and drops ~1–2 %
    (counties absent in 2010, e.g. Indian Territory 1900; Miami-Dade,
    Broomfield, Shannon, Bedford city).
- **Decision (2026-10-09):** keep NHGIS nominal boundaries + counts for the
  dasymetric model (1810–2020). For a consistent-boundary series, aggregate
  the 250 m outputs to 2010 counties. Use the CSV only for CBSA attributes
  (Metropolitan/Micropolitan, Central/Outlying).
- **Open:** ask Stefan whether an areally standardized version exists.

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

- **Status:** implemented and run on Alpine 2026-10-05: NTL cutout 33458909,
  NTL QA 33458910, v3 33459257-33459259. Results are in the Notes of
  `docs/runbooks/Making_Cutout.md` and `docs/runbooks/Running_Dasymetric.md`.
  Waiting on the user's review.
- NTL QA failed only because 2010 peaks at DN 59 (fixed rule DN >= 60). The user
  judged the layer correct (NTL-BUI Spearman 0.528 / 0.540 / 0.516). **The QA
  rule change is on hold** (do not edit `src/grid/ntl_qa.py` until decided).
- CV vs v2 on the same rows: E1 about equal (0.781 vs 0.774), E2 better
  (0.557 vs 0.668), E3 better (0.498 vs 0.679). Land use and Lights take a
  visible SHAP share in E2/E3.
- Needs a decision: in E2 and E3 the cell-level contrast shrinks (y_hat floor
  3.07 / 3.77 against 0.63 in v2's 2020; 2020 map visibly flatter), because RF
  can't predict below the lowest county y of the era's training rows. The
  floor jumps at the 1930/1940 and 1990/2000 boundaries.
- Eras (E1 1810-1930, E2 1940-1990, E3 2000-2020) and their feature lists
  live in `configs/model.yaml`; v3 reuses `v2/model/folds.csv` and compares
  each era model with v2's out-of-fold predictions on the same rows.
- Small samples per era (E3: 42 rows, 14 counties): v3 checks mechanics, not
  model quality. Per the design, do not tune or drop features on v3
  Massachusetts results alone.
- Later (design "Open items"): scale to CONUS (per-year models; re-check
  collinearity and `age` there), Ascent allocation (approved 2026-10, see above), DEM, water,
  PLURAL, fine-scale validation.

### Dasymetric v3.1 (water mask)

- **Status:** run on Alpine 2026-10-05 (water_frac 33463268, v3.1
  33463269-33463271); results in the Notes of both runbooks. Waiting on the
  user's review.
- Result: the mask removes 0.32 % of cells from 1820 on (0.72 % in 1810); CV
  changes by < 0.004 in every era; the 2020 map changes only at ponds.
- Decided (2026-10-06): dam-raised natural lakes flagged as reservoirs by
  HydroLAKES (`Lake_type = 2`: Moosehead, Chesuncook, Chamberlain, Eagle Lake in
  the 1810 Maine area) **stay land** for now. Decide again together with
  reservoir construction years (GRanD/NID) at CONUS scale. Reason: treating water
  as land only leaks a small weight onto unbuilt water cells, while treating land
  as water would delete real population. Keeping them land is the safer error.
- Decided (2026-10-06): JRC no-data (255; not defined in the JRC Data Users
  Guide v4) **counts as water** (`nodata_as_water: true` in the `water:` block).
  Basis: `jrc_nodata_check` job 33464358 found 0 no-data pixels in the study
  counties in every year. All of it (18 % of window pixels) lies on the open
  sea, starting about 10-20 km off the coast. Coastal water near land has valid
  values. v3.1 results do not change: water_frac is identical in every study
  cell (confirmed by the rerun, job 33464549). Re-check where land could be
  affected when scaling to CONUS.
- Rule: per year, mask only cells with water_frac = 1 **and** BUI = 0 (weight 0,
  left out of county area and county feature means). Dry unbuilt cells and
  partly-water cells are not masked; features are raw (no land-share scaling);
  water is not a feature.
- JRC tiles are selected by overlap with the window (Massachusetts: 80W_50N
  and 70W_50N; all 21 CONUS tiles are on Alpine).
- Check after the run: a river narrower than 250 m never fills a cell, so it is
  never masked (the Connecticut River QA point may warn).
- Deferred (design): occurrence threshold sensitivity, reservoir construction
  years (GRanD), distance to water as a feature.

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
| 2026-10-06 | NTL QA: 2010 failure on the fixed DN >= 60 rule accepted as a rule artifact (layer correct); QA rule change on hold. |
| 2026-10-06 | New external data must first be added (row + citation) to `docs/data_sources.md`; rule also in CLAUDE.md. |
| 2026-10-06 | HydroLAKES `Lake_type = 2` dam-raised natural lakes stay land until reservoir years (GRanD/NID) are handled at CONUS scale: land-as-water would delete real population, water-as-land only leaks a small weight. |
| 2026-10-07 | Stefan's county CSV is treated as nominal-by-FIPS, not areally standardized; run a stable/boundary_change/missing diagnostic before deciding how to group changed counties. Existing census outputs stay unchanged. |
| 2026-10-07 | Track `all_county_census_MSA_full.csv` in git (`data/census_std/`, .gitignore exception); source provisionally "Stefan", to re-confirm. |
| 2026-10-06 | JRC no-data (255): check where it lies first (map + per-county share). Only at sea → treat as water; also inland → decide from the results. |
| 2026-10-06 | JRC no-data check (job 33464358): only on the open sea, 0 pixels in the study counties → `nodata_as_water: true`. |
| 2026-10-06 | v3.1 water: final design = mask only (water_frac = 1 and BUI = 0, per year); earlier drafts (weights x land share, BUI / land share) dropped. |
| 2026-10-09 | Stefan's county CSV = NHGIS nominal counts (36,560 / 36,565 county-years match, job 33505541), not areally standardized. Keep NHGIS nominal boundaries + counts for dasymetric (1810–2020); consistent-boundary series = 250 m outputs aggregated to 2010 counties; CSV used only for CBSA attributes. |
| 2026-10-09 | Ascent allocation approved: account `ucb852_asc1`, 450,000 SU, valid until 2027-10-05. All sbatch scripts use `--account=ucb852_asc1`; Alpine acknowledgement kept in `docs/acknowledgements.md`. |
| 2026-10-06 | v3 per `docs/dasymetric_v3.md`: one model per era, era boundaries and feature lists in `configs/model.yaml`, v2 folds reused; order = NTL cutout + QA, then era training/prediction; v1/v2 outputs read only. |
