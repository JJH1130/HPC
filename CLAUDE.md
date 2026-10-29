# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This repository is an early-stage project (MIT licensed, Jaeheon Jung) for computational work on CU
Boulder's Alpine HPC cluster. Structure so far: `sbatch/` (Slurm submission scripts + `cluster_env.sh`,
the one place this repo's Alpine paths live), `logs/` (tracked job logs pulled back from the cluster),
`src/` (project code), and `environment.yml` (the `analysis` conda env: numpy, pandas,
matplotlib, JupyterLab; conda-forge only). On Alpine the env lives at
`/projects/jaju1407/software/envs/analysis`; build/update steps are in
`docs/runbooks/Creating_Cluster_Envs.md`, and `sbatch/test_env_analysis.sh` checks it. Locally:
`conda env create -f environment.yml`. A second env, `hisdac` (rasterio/geopandas/LightGBM/XGBoost/CatBoost/SHAP/exactextract
stack for the HISDAC_US_V2 work), is defined in `envs/hisdac/environment.yml`, lives at
`/projects/jaju1407/software/envs/hisdac`, is built per `docs/runbooks/Creating_Env_hisdac.md`, and
is checked by `sbatch/test_env_hisdac.sh`. First pipeline stage: `src/census/prepare_census.py` (NHGIS
county pop + boundaries → `counties_{YEAR}.gpkg` in ESRI:102039; manual fixes in `configs/nhgis_*.csv`, rules in `docs/census_preprocessing.md`),
run by `sbatch/census_prepare.sh` per `docs/runbooks/Preparing_Census.md`. `src/census/std_county_check.py` (`sbatch/std_county_check.sh`,
`docs/runbooks/Checking_Std_Counties.md`) compares Stefan's county CSV by 2010 FIPS (`data/census_std/`, tracked in git) with the nominal counties
(stable / boundary_change / missing per county-year → `results/census_std/`) and writes `counties_std_2010.gpkg`.
`src/census/prepare_tracts.py` (`sbatch/tract_prepare.sh`, `docs/runbooks/Preparing_Tracts.md`, rules in `docs/tract_preprocessing.md`;
population column per source table from the codebooks, overrides in `configs/nhgis_tract_tables.csv`) turns NHGIS extract nhgis0002 into
`tracts_{YEAR}.gpkg` (1910–2020, `$DATA_ROOT/processed/tract`) + QA/coverage CSVs in `results/tract/`, for fine-scale validation. `src/validation/tract_validate.py` (`sbatch/validate_tract.sh --version <v>`,
`docs/runbooks/Validating_Tracts.md`, design `docs/validation_tract.md`) scores a dasymetric version's Massachusetts predictions against those tracts
and an areal-weighting baseline (+ totals QA; metrics for all / small / non-small tracts and observed-density classes `dens_*`) → `results/validation/<name>/<version>/`;
`src/validation/county_maps.py` (`sbatch/county_maps.sh`) draws zoomed county maps of several CONUS versions side by side;
`src/validation/external_compare.py` (`sbatch/external_compare.sh inventory|extract|evaluate`; products, years, paths and US
input units in `configs/external_grids.yaml`; data fetched by `sbatch/external_download.sh` on a login node into
`$DATA_ROOT/raw/external/`) sums external population grids (GHS-POP, WorldPop, GPW v4.11, GRUMP v1, Fang & Jawitz M3 / M5)
per tract in each grid's own CRS with exactextract (`extract`, one job per product, sums on scratch) and compares them with
v5.4 (= `Dasy_CONUS_RF_v3_all`) and areal weighting on the same tracts (`evaluate`: tracts the product covers without
nodata; v5.4 rows from its `tract_errors_{YEAR}.csv`) -> `results/validation/conus/external/external_comparison.csv` + figure;
`src/validation/compare_models.py` (`sbatch/compare_models.sh`) tabulates CV / TEST / tract metrics of several versions
(`model_comparison.csv`; for one version over years `--out summary_by_year.csv --plot ... --repro-with <version>`;
`--years` filters, `--rank-features ntl ntlv` adds a feature's permutation / SHAP rank; logs tract MdAPE by part side by side);
`--gap-share 0.05` (CONUS) adds tract parts without / within BUI gap counties;
`src/validation/metrics_over_time.py` (`sbatch/metrics_over_time.sh`; also runs locally, tracked files only) adds county
MdAPE / MAPE / R2 for TEST and CV counties (exp(y_hat) x the target's area_km2 vs census, before allocation) and tract
MdAPE on fixed county sets (counties tracted in every year from 1910 / 1920 / 1940 / 1960) next to all tracts ->
`county_metrics_by_year.csv`, `fixed_tract_metrics.csv`, `mdape_over_time.png` in `results/validation/conus/<version>/`;
`src/grid/record_uncertainty.py` (`sbatch/record_uncertainty.sh`; `BUPR_contemp.tif` from `sbatch/hisdac_extra_download.sh`,
login node) measures the HISDAC records without a built year per 2010 county (`ratio_A_contemp` = (contemp - BUPR_2015) /
contemp, only with contemp - not in the Dataverse BUPR.tar, asked of Stefan; `ratio_A_nby` = NobuiltYear / (BUPR_2015 +
NobuiltYear) (+ `_2020`); `ratio_B_<year>` = NobuiltYear / (BUPR_year + NobuiltYear); both A ratios -> `a_compare.csv`;
no contemp + a 0/1 NobuiltYear = value distribution only, exit 0), vs the BUI gap counties, and threshold tables per
ratio (column `measure`) -> `results/hisdac_uncertainty/` (diagnosis only);
`src/grid/uncertainty_filter.py` (`sbatch/uncertainty_filter.sh`) turns that table + the BUI_2015 county sums into one fixed
exclusion set per threshold (`ratio_A_nby >= t`, t = 0.9 / 0.7 / 0.5, or the fixed records / area rules at 5 % of the
median) -> `results/hisdac_uncertainty/excluded_counties_t{090,070,050}.csv` + summaries, used by
`configs/conus_rf_v3_u{090,070,050}.yaml` (v5.4 settings, 1920 / 1960 / 2010 / 2020, `exclude_counties:` = out of search,
fit and TEST in `train.py`, which writes `excluded_predictions.csv`; still allocated by `predict.py`);
`src/validation/filter_compare.py` (`sbatch/filter_compare.sh`; also runs locally) compares v5.4 and the three on the
common TEST counties (a), the TEST counties excluded at 0.9 (b, imputed) and tract parts, with the selection rule fixed
before the results (lowest mean of (a) and (b); within 1 pp the one keeping more counties; the user decides) ->
`results/validation/conus/uncertainty_filter/`. Compute allocation: Ascent account `ucb852_asc1` (450,000 SU, approved 2026-10, **valid until 2027-10-05**); every
`sbatch/*.sh` has `#SBATCH --account=ucb852_asc1` (renew or remove the line before it expires). Publications must include the Alpine
acknowledgement in `docs/acknowledgements.md`. Raw/processed data live under
`/projects/jaju1407/data` (`$DATA_ROOT` in `sbatch/cluster_env.sh`), not in git. Second stage: `src/grid/make_cutout.py`
(study area + the only layer list in `configs/study_area.yaml` → HISDAC/Land_Use/NTL layers clipped to one shared 250 m window + per-year
county zone grids; `--layers NAME` adds one layer to an existing cutout), run by `sbatch/grid_cutout.sh` per `docs/runbooks/Making_Cutout.md`, rules in
`docs/cutout.md`; `src/grid/ntl_qa.py` (`sbatch/ntl_qa.sh`, `CONFIG=` for CONUS, `--layer NTL NTLV` for several layers side by side)
checks the night-light layers (DMSP NTL: DN >= 60 box rule unchanged, on hold; VIIRS-like NTLV: radiance rules, fails
only on negative values; logged-only edge lines: lights outside the counties, glow / lit share of BUI = 0 cells at the
coast / border); `sbatch/ntlv_download.sh` (login node, not a job) downloads the VIIRS-like NTL (Chen et al. 2021,
Version1, Dataverse API + md5) and `src/grid/ntlv_check.py` (`sbatch/ntlv_check.sh`) checks it before the cutout; a
config layer with `nodata_to: <value>` gets its nodata cells written as that value (NTLV sea mask -> 0, counted); `src/grid/bui_qa.py` (`sbatch/bui_qa.sh`) lists BUI quantiles and the
largest cells of a cutout (CONUS outlier check, look only), `src/grid/bui_fix.py` (`sbatch/bui_fix.sh`; `bui_cap:` block of
`configs/conus_study_area.yaml`, none for Massachusetts) replaces BUI cells above the cap by their 3 x 3 neighbour median
in place on the cutout (original kept in `layers/BUI_raw/`; `--check` counts only, also from the raw HISDAC files), and `src/grid/water_frac.py`
(`sbatch/water_frac.sh`; `water:` block of `configs/study_area.yaml`) adds the water-fraction layer from JRC tiles
(auto-selected by overlap): static minus HydroLAKES reservoirs (`reservoir_source: hydrolakes`, v3.1–v3.4) or one layer per study year with Global Dam Watch reservoirs counted as water from their completion year (`reservoir_source: gdw`, v4).
`src/grid/place_dist.py` (`sbatch/place_dist.sh`; `place_dist:` block of `configs/study_area.yaml`) adds the v4.1 PLURAL-1 distance layers
`layers/PLACEDIST/d_{10k,20k,50k,100k,250k}/{YEAR}_*.tif` (km to the nearest US place of each size class, 1940–2020, single-decade gaps filled). External data sources are listed in `docs/data_sources.md`. HISDAC is read from `$HISDAC_DIR` (PetaLibrary, read only); cutouts go to
`$HISDAC_SCRATCH/cutouts/<name>` (scratch, 90-day purge). Third stage: `src/dasymetric/` (design
`docs/dasymetric_v1.md`, changes in `docs/dasymetric_v2.md`, v3: `docs/dasymetric_v3.md`, v3.1 (water mask): `docs/dasymetric_v3_1.md`, v3.2 (E3 without ntl): `docs/dasymetric_v3_2.md`, v3.3 (E3 with fixed hyperparameters via an era's `params:`): `docs/dasymetric_v3_3.md`, v3.4 (E2+E3 merged; last Massachusetts experiment, closed 2026-10-13): `docs/dasymetric_v3_4.md`, v4 (v3.4 + terrain `elev`/`slope` from the GMTED2010 `DEM` cutout layer + yearly water mask from Global Dam Watch reservoir years, `water_mask: yearly`): `docs/dasymetric_v4.md`, v4.1 (v3.4 + yearly water mask + PLURAL-1 distances `d_*` in E23, no terrain): `docs/dasymetric_v4_1.md`; config currently at v4_1), three separately runnable steps sharing `common.py` (config, cell features, raster
I/O) and `plots.py` (correlation/SHAP plots, maps): `county_features.py` → `train.py` → `predict.py`, run by `sbatch/dasymetric_{features,train,predict}.sh`
per `docs/runbooks/Running_Dasymetric.md`. CONUS (`docs/conus_plan.md`, scale table + implementation decisions there;
steps `docs/runbooks/Running_CONUS.md`): separate configs `configs/conus_study_area.yaml` (`window: full` = the whole
HISDAC raster, 1920/1960/2010, water `only_zone_blocks`), `configs/conus_rf_v1.yaml` / `conus_rf_v2.yaml`
(`Dasy_CONUS_RF_v1/v2`; `conus_rf_v3.yaml` / `conus_rf_v4.yaml` = v1 + terrain / v1 + distances + terrain, 1960 + 2010; `conus_rf_v1_bui.yaml` /
`conus_rf_v3_bui.yaml` = v1 / v3 on the BUI-fixed cutout, 1920 + 1960 + 2010, compared with v1 / v3 (v3_bui = CONUS base);
`conus_{rf,lgbm,xgb,cat}_v3_n60.yaml` = the model family comparison on v3_bui's features (60 candidates each);
`conus_rf_v3_all.yaml` = the chosen RF v3 n60 for all census years 1900-2010 + 2020 (era Y2020, 2026-10-30; study area
years 1900-2020; every other CONUS config has its own `years:`); `conus_rf_v3_ntl.yaml` = v3_all + `ntl` for 2000 / 2010 (NTL layer of the CONUS study
area, years [2000, 2010]), compared with v3_all; `conus_rf_v3_ntlv.yaml` = v3_ntl with `ntlv` (VIIRS-like NTL,
layer NTLV) instead of `ntl`; one era per year, `split: configs/conus_split.csv` = tracked train/test + fold table from
`src/dasymetric/make_split.py`, never regenerated; `block_rows` = strip-wise features/prediction (terrain slope per strip with one halo row = whole window); `unusable: skip`;
`years`), county input `src/census/conus_counties.py` (`sbatch/census_conus.sh`: Stefan's CSV on 2010 polygons, status
ok / filled_nhgis (2010 polygons without a CSV row, pop from NHGIS, area ratio 0.95-1.05: trained, appended to the split as
train) / filled_nhgis_alloc (ratio outside: allocated only, `train_status`) / no_value /
zero_pop; 2020 = NHGIS 2020 counties on the 2010 polygons with the 2010 -> 2020 changes in `NHGIS_REMAP` / `NHGIS_MERGED`,
decisions in `results/census_conus/counties_2020_nhgis_match.csv`; `--years` keeps the other years' summary rows), all
submitted by `bash sbatch/submit_conus.sh trial|pilot|v3v4|bui|models|all|ntl|ntlv|external|y2020|uncertainty|uncfilter` (`uncfilter` = exclusion sets, then u090 / u070 / u050 side by side, then
`filter_compare`; `y2020` =
2020 added to `Dasy_CONUS_RF_v3_all` as era Y2020 with `--years 2020`, after `sbatch/y2020_precheck.sh`; with `--years`,
`county_features` / `train` / `predict` keep the other years' rows of `water_mask_by_year.csv` / `cv_summary.csv` /
`reallocation_qa.csv`; stage scripts take `CONFIG=`,
`CENSUS_DIR=`, `COVERAGE=` env overrides; CONUS resources live there). Model choice, search space, eras (years + features per era; or one `features` list = one
pooled model), SHAP groups, used statuses, `water_mask`, `compare_with` / `folds_from` (earlier version read for comparison / fold reuse) and map
years live in `configs/model.yaml` (model registry `MODELS` in `src/dasymetric/models.py`: rf, lgbm, xgb, catboost, single-threaded models with a parallel
search; a space value is a list or a distribution `{dist: loguniform|uniform|randint, low, high}`). Outputs go to
`$HISDAC_SCRATCH/dasymetric/<name>/<version>[/<era>]`; small files are copied to `results/dasymetric/`. Env changes go through the yml files + `conda env update
--prune`, never ad-hoc `mamba install`. There is no build step. Lint sbatch scripts with
`python <CURC_Alpine skill>/scripts/check_sbatch.py sbatch/*.sh`. Tests (plain scripts, no pytest; need the local
`hisdac` env activated - on Windows, running its python.exe without `Library\bin` on PATH crashes numpy's BLAS
with 0xc06d007f): `python tests/test_place_dist.py` (synthetic check of `place_dist.py` distances and gap fill; `crs_label` / `place_points`
with a rasterio CRS), `python tests/test_models.py` (model registry: list spaces unchanged, distributions, builders, search + pickle per model),
`python tests/test_bui_fix.py` (BUI cap: isolated cell, neighbours above the cap, window edges,
strips = whole window = brute force, rerun, `--check`),
`python tests/test_conus_dasymetric.py` (CONUS: strips = whole window for features and prediction, split held out
in train, NoData for unused counties, tract validation train/test parts + density classes, terrain strips = whole
window, `bui_qa.py`, gap-county parts, LightGBM / XGBoost / CatBoost search -> predict with mass preserved,
`compare_models.py`, all census years (a pre-1940 year without Land_Use; shared years reproduce the compared version;
`--repro-with`, summary figure), `conus_counties.py` statuses + 2020 NHGIS match, `--years` keeps the other years' rows, NTL (`test_ntl`: real configs, ntl era next to one
without, NTL nodata, `ntl_qa.py` against brute force, `compare_models --years --rank-features`), VIIRS-like NTL (`test_ntlv`: real configs, `nodata_to`, `ntlv_check.py`,
county ntlv, `ntl_qa.py` NTL + NTLV); stubs `shap` and `plots`;
one function alone: `python -c "import sys; sys.path[:0]=['tests']; import test_conus_dasymetric as t; t.test_ntl()"`), `python tests/test_external_compare.py` (tract sums of a projected and a lon / lat raster = brute-force polygon x
pixel intersection, nodata / outside tracts left out, extract -> evaluate: product, v5.4 and areal weighting metrics on
the kept subset = by hand, a missing product = `missing` row, path resolution), `python tests/test_record_uncertainty.py` (shifted contemp grid aligned by WarpedVRT, county ratio_A_contemp /
ratio_A_nby / ratio_B, A compare, cell checks, thresholds, gap overlap, strips = one strip; contemp + 0/1 NobuiltYear;
no contemp + NobuiltYear counts = same NobuiltYear ratios; no contemp + 0/1 = value distribution only, exit 0),
`python tests/test_uncertainty_filter.py` (exclusion sets: BUI sums, fixed rules, nested sets, reasons, summary, strips;
filter_compare: common / imputed TEST sets, metrics by hand, tract parts, the rule with the 1 pp tie, a leak stops the
run; `exclude_counties` in train / predict: `test_conus_dasymetric.test_exclude_counties`), `python tests/test_water_frac_parallel.py` (block worker processes = one process, GDW year switch,
`only_zone_blocks`).

When more code is added, update this file with:
- Commands to build, lint, and run tests (including running a single test)
- The high-level architecture/module layout, focused on things not obvious from reading one file

## 언어 규칙

사용자에게 하는 답변은 항상 한국어로 한다. 코드, 주석, 커밋 메시지, docs 문서는 영어로 유지한다.

## 작업 방식: Claude ↔ Alpine 클러스터

이 저장소의 코드는 CU Boulder Alpine HPC 클러스터에서 `sbatch`로 실행된다. **Claude는 클러스터에 직접
접속할 수 없다** (SSH, `sbatch`, `/scratch`, 로그 열람 전부 불가) — 사용자가 유일한 다리다.

워크플로:
1. Claude가 로컬 저장소에서 코드, sbatch 스크립트, 러너북을 작성한다.
2. 사용자가 로컬에서 커밋/푸시 → 클러스터에서 `git pull` → Claude가 준 명령어를 Alpine 터미널에 그대로
   붙여넣어 실행한다.
3. 잡이 `logs/`에 로그를 쓴다 (작은 결과 파일은 결과 폴더로).
4. 사용자가 클러스터에서 `logs/`(+작은 결과물)를 커밋·푸시하면, Claude가 로컬에서 `git pull`해서 읽고
   분석한다.

Claude는 로그/결과를 직접 pull해서 읽기 전까지는 잡이 실행됐다거나 성공했다거나 어떤 수치가 나왔다고
단정하지 않는다.

클러스터 관련 작업(온보딩, sbatch 스크립트 작성, conda 환경, 하드웨어/파티션 선택, 잡 체이닝, 스토리지
경로, 러너북 작성, 잡 상태 확인·트러블슈팅 등)은 `CURC_Alpine` 스킬을 따른다.

클러스터 온보딩(로그인, GitHub SSH, `/projects` clone 등) 절차는 `docs/runbooks/Cluster_Setup.md`
참고.

## 데이터 출처

외부 데이터는 `docs/data_sources.md`에 등록돼 있다. 새 데이터를 파이프라인에서 쓰기 전에 먼저 그 문서에 행(요약
표)과 인용·다운로드 정보(Details)를 추가한다.

## 보류 사항과 결정 기록

보류 사항과 중요한 결정은 `docs/open_items.md`에 있다 — 작업 전에 읽는다. memory는 컴퓨터 간에 옮겨지지
않으므로, memory에 저장하는 중요한 결정은 이 파일에도 같이 기록하고 커밋한다.
