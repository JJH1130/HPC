# Open Items and Decisions

Pending items and important decisions for this project. This file is the
durable record: Claude's local memory does not move between computers, so any
important decision saved to memory is also written here.

Last updated: 2026-10-27 (CONUS pilot result; v3 / v4 terrain, BUI check, density classes, county maps submitted as code)

## Open items

### CONUS Dasy_CONUS_RF_v1 - v4

- **Status (2026-10-27):** pilot passed (`docs/conus_plan.md`, "Pilot result"). Code written for the next submission
  (`bash sbatch/submit_conus.sh v3v4`, `docs/runbooks/Running_CONUS.md` section 2), not run yet: BUI outlier check
  (look only), DEM cutout, `Dasy_CONUS_RF_v3` (v1 + elev, slope) and `Dasy_CONUS_RF_v4` (v1 + distances + elev, slope)
  for 1960 / 2010, tract density classes (v1 / v2 validation rerun), zoomed county maps v1 / v2 / v4 (2010).
- Open (BUI): treatment of the implausible BUI maxima (cap, neighbour value, nothing) waits for `bui_quantiles.csv` /
  `bui_top.csv` and the BUI unit from the HISDAC README (printed by `bui_qa`).

- **Status (2026-10-23):** scale review done (`docs/conus_plan.md`, "Scale checks"); trial (1960, v1) passed, jobs
  34814376-34814382: whole chain ~25 min, peak 16 GB (water), prediction ~4 min per year (far below the estimate);
  1960 test RMSE 0.778 / R² 0.738, CV R² 0.719 (`docs/conus_plan.md`, "Trial result"). Before the pilot
  (2026-10-24): the 4 counties without a CSV row filled from NHGIS (status `filled_nhgis`), per-county JRC no-data
  QA added, pilot resources set from the trial. Next: the 1920/1960/2010 pilot (`docs/runbooks/Running_CONUS.md`,
  section 1).
- Implementation decisions (details in `docs/conus_plan.md`, "Implementation decisions"): separate configs
  `configs/conus_*.yaml`; window = whole HISDAC raster; county statuses ok / no_value / zero_pop (only ok used, others
  NoData); counties with 0 cells or no unmasked cell skipped with a warning; one era per year; split
  `configs/conus_split.csv` (seed 42, 2,483 train / 622 test, DC has no test county; + 4 filled counties appended
  as train 2026-10-24), never regenerated; tract
  totals QA by nominal county skipped for CONUS.
- Pilot 2026-10-26 (jobs 34820550-34820561): grid_cutout failed, `BUI 2010 values 0.0..5447140510.0 don't fit
  int32`; the 12 dependent jobs were cancelled. Fix: BUI dtype float32 in `configs/conus_study_area.yaml`; resubmit.
- Open: implausible BUI maxima on the CONUS grid: 306,635,538 (1920), 709,978,539 (1960), 5,447,140,510 (2010) in a
  single 250 m cell (62,500 m2), whatever the unit (BUI unit still to confirm, data inventory). Likely a few
  outlier records; they enter `bui` and `bldg_size` (county means, cell weights). Before the full run: count cells
  above a plausible cap per year and look at where they are.
- Open: JRC no data counted as water was only checked in Massachusetts (trial: 2.0 % of the covered JRC pixels in
  the computed blocks). The pilot writes the share inside study cells and per county
  (`results/cutout/conus/water_jrc_nodata_by_county.csv`); decide from it before the full run.
- Decided 2026-10-24: the 2010 polygons without a CSV row (Miami-Dade, Shannon SD, Broomfield, Bedford city; no row
  under any code, so no FIPS remap) take that year's NHGIS nominal county pop (Miami-Dade = Dade G1200250 where
  NHGIS uses the old code); years without an NHGIS county stay `no_value`. Area ratio NHGIS / 2010 polygon logged
  (`results/census_conus/counties_conus_filled.csv`). Same day (user): they are appended to `configs/conus_split.csv`
  as train (existing rows unchanged) and trained on when the area ratio is within 0.95-1.05 (status `filled_nhgis`);
  outside it they are `filled_nhgis_alloc`, allocated only.

### Compute allocation (Ascent)

- **Status:** approved. Slurm account `ucb852_asc1`, 450,000 SU,
  **valid until 2027-10-05**.
- Every `sbatch/*.sh` sets `#SBATCH --account=ucb852_asc1` (before this, jobs
  ran on `ucb-general`). New scripts must carry the same line.
- Before 2027-10-05: renew the allocation, or switch the scripts back to
  `ucb-general` (remove the line); jobs on an expired account are rejected.
- Publications: include the Alpine acknowledgement in
  `docs/acknowledgements.md`.

### PetaLibrary mount (closed ticket)

- After the October 2026 Alpine maintenance, `/pl/active/Leyk_Lab` was not mounted. RC ticket
  **INC1495434** ("/pl/active/Leyk_Lab not mounted after maintenance") was closed by Andrew Monaghan
  (OIT Research Computing) on 2026-10-20 as "Resolved - Successful"; the mount works again (v4 ran on it).
- If it breaks again: within five business days of the closure, reply "Not Resolved: INC1495434" to
  rc-help@colorado.edu (keep the ticket number in the subject); after that, open a new incident at the same
  address and cite INC1495434.

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

### Tract validation data (nhgis0002)

- **Status:** design + code written 2026-10-13 (`docs/tract_preprocessing.md`,
  `src/census/prepare_tracts.py`); not yet run. Next: quick test 1910/1960/1970,
  review the table inventory, conflicts and coverage, then the full run
  (`docs/runbooks/Preparing_Tracts.md`).
- Tracts in several tables with different values are `conflict` with pop left
  empty (no value is chosen). County outputs are not changed.

### Tract validation of the dasymetric outputs

- **Status:** design + code written 2026-10-13 (`docs/validation_tract.md`,
  `src/validation/tract_validate.py`); not yet run on v3_1. Massachusetts only,
  11 years (1920 has no MA tracts); model vs areal-weighting baseline; stops if
  cells of a fully tracted county are lost in rasterization.

### Dasymetric v3.2–v3.4: the 2000–2020 (E3) gap (closed 2026-10-13)

- **v3.2 result (2026-10-13):** E3 tract MdAPE unchanged (45–46 %), E3 county CV worse → `ntl` is not
  the cause (`docs/dasymetric_v3_2.md`).
- **v3.3 result (2026-10-13):** E3 with E2's hyperparameters (max_features 1.0): tract MdAPE 2000–2020
  43.0 / 41.8 / 40.6 vs v3.1 46.5 / 45.1 / 44.0, R² log density +0.03–0.04, although the E3 county CV is
  worse (R² 0.646 vs 0.657). **County CV (42 rows) and tract validation disagree**; for CONUS, don't rely on
  small per-era county CV alone to pick hyperparameters. Gain is modest (still 12+ pt above 1990's 28 %).
- **v3.4 result (2026-10-13, `docs/dasymetric_v3_4.md`):** E2 + E3 merged into E23 (1940–2020, no ntl,
  126 rows): 2000–2020 tract MdAPE 44–46 % → 29.8 / 30.5 / 30.9 %, R² log density 0.77–0.87; 1940–1990
  cost 0–2.4 pt. **The E3 gap was a small-sample problem** (42 rows), not period-specific.
- **CONUS implication: enough training rows, not pooled years.** CONUS keeps per-year models (needed
  for per-year SHAP); each has ~3,000 counties, far more than v3.4's 126 rows. Check at CONUS: compare
  per-year vs pooled models on tract validation.
- **Massachusetts experiments closed (2026-10-13)** with v3.4.
- **Provisional:** conclusions on the E3 gap wait for PLURAL (urban–rural continuum, from Siqiao), which is
  not yet included and may address the remaining rural-over / urban-under pattern.
- v3.2 background: tract validation (2026-10-13) rejected the E3 y_hat-floor explanation: 2000–2020 tract MdAPE is
  ~45 % for both v2 and v3_1, while v3_1 is better in 1940–1990. v3.2 drops `ntl` from E3 (E2's
  features) to test whether night lights cause it. Compare with v3_1 for 2000–2020.

### Dasymetric v4 (terrain + reservoir years)

- **Status:** run 2026-10-19 (cluster time; jobs 34662977–34662982, code 7f83c2e); result in
  `docs/dasymetric_v4.md`, "Result". Run steps `docs/runbooks/Running_Dasymetric.md`, section "v4".
- **Result:** worse than v3.4. County CV RMSE E1 0.780 → 0.852, E23 0.554 → 0.580. Tract MdAPE 1950–2020
  +6 to +8 pt (2020: 30.9 → 38.0 %), R² log density −0.03 to −0.05. Better only for small (rural) tracts and
  1910. SHAP: E1 `elev` 3rd (0.19), `slope` last; in E23 both near the bottom (0.03).
- **Decision (2026-10-20):** no mask-only run. The mask change touches only 0.35 % of the cells, so terrain is
  taken as the cause (a static county mean that acts as a county label with 14–22 counties). The drop is
  most likely overfitting with few Massachusetts counties; terrain is **not decided** and is re-tested on
  CONUS. GDW yearly water mask **kept** (it is the correct treatment of reservoirs, independent of the
  score). Terrain re-test on CONUS (~3,000 counties per year, much larger relief
  contrast), with and without, and possibly as relative elevation (cell minus county mean) instead of absolute
  elevation, which means different things in different regions.
- v4 = v3.4 + `elev`, `slope` (GMTED2010 averaged to 250 m; slope in degrees on the 250 m grid) in both eras
  + yearly water mask from GDW reservoir years (`water_mask: yearly`, `water.reservoir_source: gdw`).
- `reservoir_source: hydrolakes` + `water_mask: true` reproduce v3.1–v3.4 (static `water_frac.tif`, kept in the
  cutout).
- Census for v4 and later Massachusetts experiments: keep the current setup (NHGIS nominal counties,
  1810–2020) so versions stay comparable; switch to the 1900–2020 study period with Stefan's CSV on 2010
  county polygons only at the end (decided 2026-10-20).

### Dasymetric v4.1 (PLURAL-1 distances)

- **Status:** run 2026-10-22 (cluster time; jobs 34785497-34785501, code ee55448). Result in
  `docs/dasymetric_v4_1.md`, "Result": worse than v3.4 and v4 (tract MdAPE 2020 30.9 -> 43.0 %, E23 CV R2
  0.727 -> 0.694); the distances dominate SHAP with 14 counties. Not kept for Massachusetts; re-test on CONUS.
- v4.1 = v3.4 features + yearly GDW water mask (as v4) + `d_10k`, `d_20k`, `d_50k`, `d_100k`, `d_250k` (km from
  each cell centre to the nearest place of that size class that year, all US PLURAL places) in E23 only.
  No terrain. `compare_with: v3_4`, `folds_from: v2`. 2020 uses PLURAL 2018.
- Gap fill for New England towns missing in single decades (0 between two > 0 neighbouring PLURAL years → mean
  of the two; 1930 and 2018 not filled). Millbury 1940 (= Milford's 15,388, likely a PLURAL matching error) is
  left as is (limit in the design doc).

### PLURAL gridded data

- **Meeting with Siqiao (2026-10-20):** she has two PLURAL-1 products for 1992–2022: census tract level and a
  900 m grid (same years). Details and code to reproduce them arrive Wednesday 2026-10-21. Options under
  discussion: (a) compute PLURAL ourselves for earlier years from tract (or other) population; (b) use the
  1992–2022 products as they are (tract value given to every 250 m cell in the tract, or the 900 m grid
  resampled). Open concern: PLURAL is computed from population, so as a dasymetric predictor it can leak the
  target (and the tract validation data); see the discussion before choosing.
- **Decision (Stefan meeting, 2026-10-23):** compute only the five PLURAL-1 **distance** terms ourselves, per
  250 m cell, and use them as features (v4.1). Place population and focal population density are **excluded**
  (they are population, so they would leak the target). This replaces options (a)/(b) above for now.
- **Status:** waiting to receive the grid from Siqiao (not needed for v4.1). The published point data are on Alpine:
  `/projects/jaju1407/data/raw/plural/plural_2023/` (`PLURAL_CSV/PLURAL_CSV/`, `PLURAL_SHP/PLURAL_SHP/`,
  `PLURAL_indices_documentation.pdf`).
- Use **PLURAL-1 scaled across years** only: PLURAL-2 is rank-based and not comparable over time (Uhl et al.
  2023). Values 0–1, 0 = large place near other places (urban), 1 = small remote place (rural); New York 2010
  = 0.013. Years 1930–2010 + 2018 (no 1900–1920, no 2020). Points in ESRI:102003.
- PLURAL (urban–rural continuum) may address the rural-over / urban-under pattern left in the
  tract validation (2026-10-13); the E3-gap conclusions (v3.2–v3.4) are provisional until it is tested.
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
- Later (design "Open items"): scale to CONUS (per-year models, ~3,000 counties each; compare per-year
  vs pooled on tract validation, see v3.4 below; re-check collinearity and `age` there), Ascent allocation (approved 2026-10, see above), DEM, water,
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
- Deferred (design): occurrence threshold sensitivity, distance to water as a
  feature. Reservoir construction years: decided 2026-10-13 (next section).

### CONUS water step: reservoirs from GDW (decided 2026-10-13)

- **Status:** implemented in `src/grid/water_frac.py` (`reservoir_source: gdw`, yearly layers) for v4
  (2026-10-20), not run yet; first tested on Massachusetts. Data: GDW v1.0 (`docs/data_sources.md`).
- Water = JRC occurrence >= 75 (unchanged).
- GDW reservoir polygons replace HydroLAKES `Lake_type = 2`:
  - a) `YEAR_DAM` present and `QUALITY` 1–3: water from `YEAR_DAM` on; land
    before.
  - b) `LAKE_CTRL` = Yes or Maybe: water in all years (natural lake raised by a
    dam).
  - c) No `YEAR_DAM`, or `QUALITY` 4–5: land in all years (current behaviour).
- Known gap (accepted): dam-raised natural lakes not flagged in `LAKE_CTRL`
  (e.g. Moosehead 1835, Chesuncook 1916, Chamberlain 1890, Red Lake MN 1931) are
  land before `YEAR_DAM`. Same error as now, only for pre-dam years.
- Consequence: `water_frac` becomes year-dependent (reservoir pixels switch at
  `YEAR_DAM`); today it is one static layer.
- This supersedes the 2026-10-06 rule that dam-raised natural lakes stay land
  (for the CONUS step; v3.1 Massachusetts outputs stay as they are).

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
| 2026-10-13 | CONUS water step: JRC occurrence >= 75 unchanged; GDW v1.0 reservoir polygons replace HydroLAKES `Lake_type = 2`. `YEAR_DAM` + `QUALITY` 1–3 → water from `YEAR_DAM` on; `LAKE_CTRL` Yes/Maybe → water in all years; no `YEAR_DAM` or `QUALITY` 4–5 → land in all years. Unflagged dam-raised natural lakes are land before `YEAR_DAM` (accepted). `water_frac` becomes year-dependent. |
| 2026-10-13 | Massachusetts dasymetric experiments closed (v3.2–v3.4). The 2000–2020 tract gap was a small-sample problem (E3 = 42 rows; merging E2+E3 → MdAPE 30–31 %). Lesson for CONUS: enough training rows, not pooled years; CONUS keeps per-year models (per-year SHAP, ~3,000 counties each) and checks per-year vs pooled on tract validation. Provisional until PLURAL is included. |
| 2026-10-06 | v3 per `docs/dasymetric_v3.md`: one model per era, era boundaries and feature lists in `configs/model.yaml`, v2 folds reused; order = NTL cutout + QA, then era training/prediction; v1/v2 outputs read only. |
| 2026-10-20 | v4 = v3.4 + terrain (`elev`, `slope` from GMTED2010) + GDW reservoir years in a yearly water mask; HydroLAKES path kept for reproducing v3.1–v3.4. PLURAL: use PLURAL-1 scaled across years only (PLURAL-2 not comparable over time). |
| 2026-10-20 | Experiments (v4 onward) keep NHGIS nominal counties 1810–2020 for comparability; the switch to 1900–2020 with Stefan's CSV on 2010 county polygons (agreed with Stefan 2026-10-14) is made last. SHAP: `elev` and `slope` are separate groups, not one `Terrain` group. |
| 2026-10-20 | v4 result (worse than v3.4) attributed to terrain without a mask-only run. Likely overfitting with few MA counties; terrain not decided, re-tested on CONUS. GDW yearly water mask kept. Terrain re-test (with/without; absolute vs relative elevation). |
| 2026-10-20 | Version order: v4.1 = PLURAL-1 distance terms from cell centres (1930–2020); v5 = HISDAC-US v3; v6 = CONUS with model comparison and hyperparameter tuning last, after all data and the study area are fixed. |
| 2026-10-23 | Stefan meeting: (1) approved computing only the five PLURAL-1 distance terms per cell as features; place population and focal population density excluded (target leakage). (2) Population data: go with Stefan's CSV (2010 boundaries, 1900–) for now and fix later if needed; Massachusetts experiments continue on NHGIS same-year boundaries, and the switch to the CSV stays the last step (2026-10-20 decision kept). |
| 2026-10-23 | v4.1 design: v3.4 features + yearly GDW water mask + `d_10k` … `d_250k` in E23 only (E1 = v3.4); no terrain; `compare_with: v3_4`, `folds_from: v2`; PLURAL year = census year (2020 → 2018); single-decade gaps filled with the mean of the neighbouring PLURAL years. |
| 2026-10-23 | v4.1 (PLURAL-1 distances in E23) worse than v3.4 and v4 in Massachusetts; like terrain, likely overfitting with 14 counties. Not kept for Massachusetts; distances and terrain re-tested on CONUS. |
| 2026-10-24 | CONUS: the 4 filled counties are appended to `configs/conus_split.csv` as train (existing rows unchanged; fold = fewest train counties) and trained on when NHGIS / 2010 area ratio is within 0.95-1.05 (`filled_nhgis`); otherwise allocation only (`filled_nhgis_alloc`). Supersedes "allocation only" below. |
| 2026-10-24 | CONUS: Miami-Dade, Shannon SD, Broomfield, Bedford city (no CSV row under any code) filled from the NHGIS nominal county of the same year (Dade = G1200250), status `filled_nhgis`, allocation only (`train_status: [ok]`, split unchanged). JRC no-data share checked per county in the pilot before deciding the inland rule. Pilot resources from the trial (features 6 cores, wall times ~3-4x measured). |
| 2026-10-23 | CONUS implementation (`docs/conus_plan.md`, "Implementation decisions"): configs `configs/conus_study_area.yaml`, `conus_rf_v1.yaml`, `conus_rf_v2.yaml` (Massachusetts configs unchanged); window = whole HISDAC raster; Stefan CSV on 2010 polygons via `conus_counties.py` with status ok / no_value / zero_pop (only ok used); unallocatable counties skipped (NoData); per-year eras; split table `configs/conus_split.csv` made once (seed 42); trial run (1960, prediction timed only) before the 1920/1960/2010 pilot. |
| 2026-10-23 | CONUS (`docs/conus_plan.md`): name `Dasy_CONUS_RF_v1`; RF; census years 1900-2010 first (2020 later from NHGIS; CSV 2015 is an estimate); Stefan CSV on 2010 polygons; one model per year; counties split at random 80:20 within each state (stratified, fixed seed) into train/test before tuning, 5-fold CV grouped by county inside train (whole-state hold-out rejected: every state's land-use coding should be seen in training; tract validation is the independent check); trial years 1920, 1960, 2010; feature sets v1 (MA v3.4 set) and v2 (+ PLURAL-1 distances). |
| 2026-10-27 | CONUS v3 = v1 + elev, slope; v4 = v1 + distances + elev, slope (1960, 2010; split, folds and compare_with v1 as v2). Absolute elevation only: elevation relative to the county mean has county mean 0, so a county-level model can't learn it. Slope computed per strip with one halo row (= whole window). BUI outliers: look first (`bui_qa`), treatment decided after. Tract metrics get observed-density classes < 50, 50-500, 500-2000, 2000+ people/km2. |
| 2026-10-27 | CONUS pilot (1920/1960/2010): v1 tract MdAPE 38.4 % (1960) and 29.8 % (2010) vs 82.7 / 74.5 % areal weighting, test ~ train. v2 (+ PLURAL-1 distances) better on county TEST R2 (0.90 vs 0.78 in 2010) but worse on tracts (40.2 vs 29.8 %): distances not used for allocation; tract validation, not county CV, chooses features. JRC no data inside study cells = 0, `nodata_as_water` kept. |
| 2026-10-27 | CONUS v3 (+ elev, slope) best on tracts (2010 MdAPE 29.2 vs 29.8 %, every density class) and becomes the CONUS base; v4 (+ distances + terrain) ~ v2: distances dropped. BUI unit = sq ft (README); cells > 3e7 sq ft are record errors (10 / 119 / 298 cells in 1920 / 1960 / 2010), treatment to decide. |
