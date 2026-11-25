git pull 받고 아래를 해줘. 사용자에게 하는 보고는 한국어로. 배경: open_items "Meeting with Stefan, 2026-11-25" points 4 + 6 (Next steps 3):
"per-unit ratios" (people per building record, per built cell, buildings per capita) by county, area type and year, as a
calibration / sanity reference (over-estimate rural, under-estimate urban) and as a check on the past where tracts cover
only cities. Descriptive only: no model change, no selection.

[A. Local part (tracked files only; runs without the cluster)]
- Inputs: v5.7 county_features.csv of every era (results/dasymetric/conus/Dasy_CONUS_RF_v3_all_nby/Y<year>/: pop, n_cells,
  n_masked, bui, ... per county and year), results/hisdac_uncertainty/county_record_uncertainty.csv (bupr_<year>, nobuilt per
  2010 county), DEGURBA county class = county_missed_1980.csv (fixed 1980 labels; say so in every table), Census region
  from the state.
- Per county x year (1900-2020, 13 census years): census pop; BUPR_year (dated records built <= year); ratios
  pop / BUPR_year (people per dated record) and pop / (BUPR_year + nobuilt) (lower bound: all undated records assumed to
  exist); records per capita (inverse); built-cell count if derivable from the tracked files (else part B).
- Summary by year x county class (and x region): median, 10 / 90 %, pooled ratio (sum pop / sum records).
- Reference: US average household size by census year (Census Bureau historical households table, e.g. HH-6 /
  "Historical Households Tables"; register in docs/data_sources.md first with the exact table and URL; if you cannot
  verify the numbers from the source, do not type them from memory: leave the column empty and say so).
- Flags: counties whose ratio is outside the 1-99 % range of their class and year (list, with ratio_A_nby and the t070
  exclusion flag next to it) -> are the extreme ratios the HISDAC-poor counties?
- Outputs: results/validation/conus/unit_ratios/: county_ratios.csv, ratio_summary.csv, ratio_flags.csv,
  ratio_by_year.png (pooled + median per class over years, household size line if available).

[B. Cluster part (one job, after A; v5.7 rasters)]
- For 1940 / 1960 / 1980 / 2010 (years with tracts): per county, v5.7 people on built cells (BUI_year > 0) / BUPR on those
  cells (people per dated record as v5.7 allocates it) and / built cell count; same for undated cells per NobuiltYear record.
- Per county, these allocated ratios next to the county's tract MdAPE (v5.7 tract_errors_<year>.csv, counties with >= 5
  tracts): Spearman of |log(ratio / class median)| vs county tract MdAPE, by class. Question: do counties with odd
  per-unit ratios have larger tract errors?
- Reuse the missed_cells / cap_allocation strip code (groups, mask); checks: v5.7 county sums = census (else stop).
- Outputs: allocated_ratios.csv, ratio_vs_tract.csv (+ one figure) in the same folder.

[Common]
- src/validation/unit_ratios.py (local / job modes), sbatch/unit_ratios.sh, submit_conus.sh mode unitratios, local test
  (ratios / summaries / flags by hand on a synthetic table; part B on the cap_allocation test world: allocated ratios by
  hand, county sums), docs/conus_plan.md section "Unit ratios", runbook section 31, CLAUDE.md, open_items.
- Run part A locally and commit its outputs. Then the Alpine commands for part B: (1) submit, (2) logs + results commit;
  one success line at the end of each block.
- Numbers only, no interpretation.
