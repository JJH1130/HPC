# Research plan (dissertation: Ch1-Ch3)

Source: `Research_proposal_sl_JJ2.docx` (user, added 2026-11-24; the plan for all three chapters). Ch1 details and
results: `Research_proposal_ch1_JJ_pilot_v6.docx` and `docs/conus_plan.md`. Read this file before planning Ch2 / Ch3
work. The goal is all three chapters.

Theme: reconstructing long-term population trajectories and evaluating micro-scale exposure to natural hazards using
HISDAC-US (1810-2020).

## Chapter 1. Dasymetric mapping of historical population (in progress, CONUS done for 1900-2020)

Plan (proposal):
- Downscale county population (NHGIS) to grid cells (100 m in the plan; 250 m with HISDAC-US v2 now).
- Space-time-varying features: 1810-1940 HISDAC (BUI, BUPL, BUPR, BUPR/BUPL), elevation, slope, distance to water,
  water body, PLURAL; 1940-1991 + land use; 1992-2020 + nighttime lights.
- Ensemble models stratified by regions and timeline; XAI (SHAP, permutation importance) for the drivers by era / region.

Where the work stands (2026-11-24; `docs/conus_plan.md`, `docs/open_items.md`):
- v5.7 = one Random Forest per census year (1900-2020, 13 years), CONUS, ~3,000 counties per year; features bui,
  bldg_size, mu_ratio (BUPR/BUPL), dist_built, elev, slope, nby (NobuiltYear count); + res_share, rent_share from 1940;
  water mask (JRC, reservoirs by completion year). County totals preserved.
- Tested and not kept: nighttime lights, distances to places, PLURAL as a feature (kept as a county-classing candidate),
  built-cell aggregation, year-scaled NobuiltYear, LightGBM / XGBoost / CatBoost (RF chosen), the record-uncertainty filter.
- Not done yet: 1810-1890 at CONUS scale, region / area-type stratified models (next meeting), ensembles, 100 m (HISDAC v3).

## Chapter 2. Settlement patch trajectories and the drivers of hazard exposure (1810-2020) (not started)

Objective: characterize two centuries of settlement patch trajectories across CONUS (Part A, the core contribution) and
decompose changes in hazard exposure into hazard change, land conversion and population growth in existing settlement
(Part B, application).

Part A, patch trajectories:
- Patch delineation: binary settlement surfaces at 10-year steps from FBUY (or a BUI / BUPL threshold); sensitivity to the
  threshold and the connectivity rule (8-neighbour vs distance-based).
- Backward tracking in calendar time: HISDAC-US v2 is cumulative, so patches emerge, expand and merge but never split
  (limitation: real patches can shrink).
- Patch-period features: screened candidates (fractal dimension, compactness, inter-fragment distance, ...) for
  redundancy and scale sensitivity. Example row set: area, population (from Ch1), fragments, largest-fragment share, shape
  index, residential share (from 1940), new growth as infill / edge / outlying (LEI).
- Trajectory typology: cluster standardized patch time series (e.g. k-means), stratified by patch size.

Part B, exposure decomposition:
- Hazard overlay: wildfire (vegetation baselines, e.g. LANDFIRE BpS, and modeled historical fire weather) or sea-level rise
  (the most tractable over time).
- Exposure change between steps = population effect (population change in previously settled cells) + land conversion
  effect (newly settled cells) + hazard change effect; per patch, compared across trajectory types.
- Case studies: per cluster, the patch closest to the centroid among patches hit by wildfire 1999-2020, linked to
  ICS-209-PLUS incidents (St. Denis et al., 2023).

Part C, decisions still open: settlement layer (BUI vs BUPL) and threshold (shared by patches and LEI); mega-patches
(e.g. the Northeast corridor) under loose connectivity; hazard focus (wildfire vs sea-level rise).

Links to Ch1: the 250 m population grids 1900-2020 (Part B population effect, patch population); NobuiltYear / record
uncertainty and the enumerated-population limitation carry over.

## Chapter 3. Future projection and attribution of settlement expansion (not started)

Objective: project settlements and hazard exposure to 2050 and interpret the changing drivers of expansion.
1. Project BUI at the cell level with spatial time-series models (e.g. ConvLSTM) from historical features.
2. Downscale SSP population with the Ch1 dasymetric framework, the projected BUI as weights.
3-4. Overlay projected settlement and population with hazard maps -> future micro-scale exposure.
5. XAI attribution of projected BUI expansion (shifting drivers of sprawl).

Links to Ch1: the dasymetric model and its features must run on projected inputs (BUI, NobuiltYear has no future values,
land use from 1940); the 13 decadal time steps are the training series.
