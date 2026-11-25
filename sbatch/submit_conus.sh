#!/bin/bash
# Submit the CONUS job chains (docs/conus_plan.md; steps and checks in docs/runbooks/Running_CONUS.md).
# Not a job itself: run it on a login node from the repo root.
#   bash sbatch/submit_conus.sh trial   # step 0: 1960 only, v1; times the prediction (--measure), writes no map
#   bash sbatch/submit_conus.sh pilot   # 1920, 1960, 2010: cutout + water + distances, v1 and v2, tract validation
#                                       # (history: since the study area has 1900-2010, its cutout / water / distance
#                                       # jobs would run all 12 years)
#   bash sbatch/submit_conus.sh v3v4    # on the pilot cutout (distances, water reused): DEM layer -> v3 (v1 + terrain)
#                                       # and v4 (v1 + distances + terrain) features/train/predict/validate (1960, 2010);
#                                       # v1 + v2 validation rerun (density classes); county maps v1/v2/v4 (2010);
#                                       # BUI outlier QA (independent: nothing waits for it)
#   bash sbatch/submit_conus.sh bui     # BUI fix in the pilot cutout (bui_fix.sh) -> v1_bui and v3_bui (1920, 1960,
#                                       # 2010) features/train/predict/validate; county maps v1_bui/v2/v3_bui/v4 (2010);
#                                       # Massachusetts BUI cap count from the raw files (independent, changes nothing)
#   bash sbatch/submit_conus.sh models  # model family (RF / LightGBM / XGBoost / CatBoost, 60 candidates each) on the
#                                       # v3_bui features (copied here, not recomputed): env check -> train / predict /
#                                       # validate per model + v3_bui validation rerun (BUI gap parts) ->
#                                       # compare_models -> county maps of the four (2010)
#   bash sbatch/submit_conus.sh all     # Dasy_CONUS_RF_v3_all, 1900-2010: census input (all 12 years) -> cutout of
#                                       # the 9 new years -> BUI fix (new years) + water (all 12) -> features / train /
#                                       # predict (12 eras) -> tract validation 1910-2010 -> summary_by_year + figure
#   bash sbatch/submit_conus.sh ntl     # Dasy_CONUS_RF_v3_ntl (v3_all + ntl, 2000 / 2010): NTL layer into the cutout
#                                       # (--layers NTL) -> NTL QA (nothing waits for it: a failed DN rule does not
#                                       # stop the chain) and features / train / predict / validate -> comparison
#                                       # with v3_all (ntl_comparison.csv) + county maps v3_all / v3_ntl (2010)
#   bash sbatch/submit_conus.sh ntlv    # Dasy_CONUS_RF_v3_ntlv (v3_all + ntlv = VIIRS-like NTL, 2000 / 2010), after
#                                       # sbatch/ntlv_download.sh + ntlv_check.sh: NTLV layer into the cutout
#                                       # (--layers NTLV) -> NTL QA of NTL and NTLV side by side (nothing waits for
#                                       # it) and features / train / predict / validate -> comparison v3_all / v3_ntl /
#                                       # v3_ntlv (ntl_viirs_comparison.csv) + county maps of the three (2010)
#   bash sbatch/submit_conus.sh external  # external gridded products vs v5.4 (= v3_all) on the same tracts, after
#                                       # sbatch/external_download.sh: one extract job per product with all its files
#                                       # (tract sums, exactextract) -> evaluate after all of them (afterany: a failed
#                                       # product is skipped) -> results/validation/conus/external/
#   bash sbatch/submit_conus.sh y2020   # 2020 added to Dasy_CONUS_RF_v3_all (= v5.4), after sbatch/y2020_precheck.sh:
#                                       # census input 2020 (NHGIS on the 2010 polygons) -> cutout 2020 -> BUI fix 2020 +
#                                       # water (all 13 years, deterministic) -> features / train / predict --years 2020
#                                       # (the 1900-2010 eras are not recomputed) -> tract validation 1910-2020 ->
#                                       # summary_by_year + figure, and metrics_over_time (county MdAPE, fixed sets)
#   bash sbatch/submit_conus.sh uncertainty  # HISDAC record uncertainty (record_uncertainty.sh); BUPR_contemp
#                                       # optional (NobuiltYear only without it); independent of the other modes
#   bash sbatch/submit_conus.sh uncfilter    # uncertainty filter: exclusion sets (uncertainty_filter.sh), then
#                                       # Dasy_CONUS_RF_v3_u090 / u070 / u050 side by side (features, train, predict,
#                                       # validate; 1920 / 1960 / 2010 / 2020), then filter_compare.sh vs v5.4
#   bash sbatch/submit_conus.sh plural  # PLURAL grid test: PLURAL / PLURALC layers into the cutout (--layers) ->
#                                       # plural_qa (nothing waits for it); v5.6 (u070) 1940 / 1980 added (--years) +
#                                       # validated on all its years; six variants v5.6 + plural (plc, plcc, pq3, pq5,
#                                       # pe3, pe5; 1940 / 1980 / 2010) features / train / predict / validate ->
#                                       # plural_compare.sh (table, figure, best classed variant, county maps 2010)
#   bash sbatch/submit_conus.sh v56all  # v5.6 (Dasy_CONUS_RF_v3_u070) for all census years: features / train /
#                                       # predict --years 1900 1910 1930 1950 1970 1990 2000 (the six eras run before
#                                       # stay) -> tract validation of every tract year -> summary_by_year (next to
#                                       # v5.4, kept / excluded t070) and metrics_over_time (v5.4 dotted); one chain
#   bash sbatch/submit_conus.sh aggdiag # county feature aggregation diagnosis of v5.6, 1960 / 2010 (one job, no
#                                       # training / prediction): pre-check of v5.6's predictions + features ->
#                                       # aggregation_diag.sh -> results/aggregation/conus/
#   bash sbatch/submit_conus.sh externalv56  # external comparison with v5.6 (no download, no extract): pre-check of the
#                                       # tract sums on scratch + the city-map inputs, then evaluate (v5.6 + v5.4 on
#                                       # each product's tracts, --strict-sums) and the city maps (two jobs, side by
#                                       # side) -> results/validation/conus/external/*_v56.* + city_maps_internal_with_fj/
#   bash sbatch/submit_conus.sh citymeeting  # meeting city maps 2010 + 1980 (Boston / Denver / Chicago: v5.6 |
#                                       # GHS-POP (| WorldPop 2010) + 1 km scatter, Chicago gap blocks vs HISDAC): pre-check of the
#                                       # inputs, one job -> results/validation/conus/external/city_maps_meeting/
#   bash sbatch/submit_conus.sh builtcell  # built-cell aggregation test, 1960 / 2010: v5.6 + built-cell county means +
#                                       # built_local (bc3 / bc5 / bc9) features / train / predict / validate (gap
#                                       # counties from v5.6) + aggregation_diag per variant, side by side; aggregation_diag
#                                       # of v5.6 (new pop_share_of_total column) -> builtcell_compare.sh (table, figure,
#                                       # window k by the CV rule, county maps 2010)
#   bash sbatch/submit_conus.sh nobuilt  # NobuiltYear feature test, 1910 / 1940 / 1960 / 1980 / 2010: NOBUILT layer
#                                       # into the cutout (--layers) -> v5.6 + nby / + nby_age features / train /
#                                       # predict / validate (gap counties from v5.6), side by side -> nobuilt_compare.sh
#                                       # (tracts, TEST counties, people on BUI = 0 cells, city gap blocks, ranks)
#   bash sbatch/submit_conus.sh v54nby  # v5.4 + nby without the filter (Dasy_CONUS_RF_v3_all_nby), 1910 / 1940 / 1960
#                                       # / 1980 / 2010: features / train / predict / validate (gap counties from v5.6)
#                                       # -> v54_nby_compare.sh (v5.4 / v5.4 + nby / v5.6 / v5.6 + nby on ALL TEST
#                                       # counties); undated_age_diag.sh (FBUY of cells with / without undated records)
#                                       # side by side. Pre-check prints the time left before a CURC maintenance window
#                                       # (MAINT_START / MAINT_END, MT) next to the chain estimate.
#   bash sbatch/submit_conus.sh v57all  # v5.7 (Dasy_CONUS_RF_v3_all_nby) for all census years: snapshot of the five
#                                       # kept years -> features / train / predict --years 1900 1920 1930 1950 1970
#                                       # 1990 2000 2020 -> tract validation of every tract year (gap counties from
#                                       # v5.6) -> kept_years_check, summary_by_year (next to v5.4 / v5.6, all TEST
#                                       # counties, kept / excluded t070) + metrics_over_time, both checked against
#                                       # v54_nby_comparison.csv; meeting maps v5.7 (after predict) and external
#                                       # evaluate with v5.7 as reference (after validate) side by side; one submit
#   bash sbatch/submit_conus.sh v57nbya # v5.7 with nby -> nby_age (Dasy_CONUS_RF_v3_all_nbya), 1910 / 1940 / 1960 /
#                                       # 1980 / 2010: config check -> features -> factor check (= the NobuiltYear
#                                       # test's factors; the chain stops on a difference) -> train / predict / validate
#                                       # (gap counties from v5.6) -> v57_nbya_compare (v5.4 / v5.6 / v5.7 / new /
#                                       # v5.6 + nby_age on ALL TEST counties, CV rule); one submit
#   bash sbatch/submit_conus.sh v57plural  # PLURAL on v5.7: six variants v5.7 + plural (Dasy_CONUS_RF_v3_all_nby_
#                                       # {plc,plcc,pq3,pq5,pe3,pe5}), 1940 / 1980 / 2010: config check -> features x 6
#                                       # side by side -> features check (county plural + breaks = the v5.6 PLURAL
#                                       # test's; the chain stops on a difference) -> train / predict / validate x 6
#                                       # (gap counties from v5.6) -> v57_plural_compare (ALL TEST counties, CV rule);
#                                       # one submit
#   bash sbatch/submit_conus.sh citydensity [VERSION LABEL]  # city boxes by density class (default v5.7:
#                                       # Dasy_CONUS_RF_v3_all_nby v5.7, + DENS_EXTRA default v5.7 + PLURAL pq5) +
#                                       # cell-type shares (BUI / NobuiltYear): input check, one job ->
#                                       # results/validation/conus/external/city_density_classes_<label>/
#   bash sbatch/submit_conus.sh pluralcm   # PLURAL at county level only (no retraining): config check + inputs +
#                                       # model snapshot (logs/conus_pluralcm_models.json) -> predict / validate of
#                                       # Dasy_CONUS_RF_v3_all_nby_{pq5,plc}cm (pq5 / plc models, county plural) and the
#                                       # variance job side by side -> plural_countymean compare; one submit
#   bash sbatch/submit_conus.sh degurbaboxes  # DEGURBA boxes (after the GHS-SMOD download, section 26 block 0): input
#                                       # check -> (only while rural_boxes.boxes is empty) box selection job -> run
#                                       # job (A = GHS-SMOD, B = own density classes, 8 new + 3 city boxes); one submit
#   bash sbatch/submit_conus.sh unbuiltoverlap  # after degurbaboxes: same boxes (config, not chosen again) and cells,
#                                       # overlap of v5.7 / pq5 with GHS-POP / WorldPop on unbuilt / built cells; one job
#   bash sbatch/submit_conus.sh cap1980     # cap allocation 1980 (section 29): input check -> one job (county caps per
#                                       # cell group x scores inside, out-of-fold cap model, 1980 tract metrics)
#   bash sbatch/submit_conus.sh captransfer # cap transfer (section 30; after PRODUCTS=ghs_built_2015 download): input
#                                       # check -> one job (group shares learned in 2010 from GHS-POP / GHS-BUILT-S res,
#                                       # applied to 1940 / 1960 / 1980 / 2010, tract metrics per year)
#   bash sbatch/submit_conus.sh missed1980  # 1980 missed cells (after the GHS-BUILT-S download, section 28 block 0):
#                                       # input check -> one job (GHS-POP / GHS-BUILT on BUI = 0 cells per county and
#                                       # DEGURBA class, v5.7 / pq5 / v5.4 there, PLURAL capture curves)
# The stage scripts are the Massachusetts ones (sbatch/*.sh, #SBATCH --account=ucb852_asc1); the CONUS config and
# the resources below are passed on the sbatch command line (flags override the scripts' #SBATCH lines).
# Pilot resources are set from the trial (jobs 34814376-34814382, docs/conus_plan.md "Trial result"): wall times
# ~3-4x the measured time scaled to 3 years (validation: not measured yet, estimate); features 6 cores (trial peak
# 10 GB of 15 with 4; v2 reads 5 more layers). Override any wall time: CUTOUT_TIME, WATER_TIME, PLACE_TIME,
# FEATURES_TIME, TRAIN_TIME, PREDICT_TIME, VALIDATE_TIME. Override a wall
# time without editing this file, e.g. PREDICT_TIME=12:00:00 bash sbatch/submit_conus.sh pilot.
# v3v4 resources from the pilot (jobs 34918220-34918231, docs/conus_plan.md "Pilot result"): features v2 5 min /
# 10 GB, train v2 19 min, predict 13 min / 15 GB, validate 5 min / 17 GB; v4 has 2 more features than v2.
# bui resources from v3v4 (jobs 34921582-34921594): v3 / v4 features, train, predict, validate each well inside the
# v3v4 wall times; v1_bui / v3_bui add 1920. bui_fix reads and writes the BUI layer once per year (estimate).
# models: train 2 h (3 x the candidates of v3_bui, whose train took ~9 min; boosting time unknown), the rest as bui.
# all: from the 3-year runs (pilot / bui / models): cutout 3 min, water 12 min, bui_fix 1 min, features 3 min, RF 60
# train 23 min, predict 13 min, validate 4 min; x 3-4 for 9-12 years, then ~2-3 x for the wall time.
# ntl: from v3_all (jobs 34939345-34939353; 12 years): features 16 min / 9.6 GB (6 cores), train 1:37, predict 47 min
# / 16 GB, validate 12 min / 17.5 GB, cutout 10 min / 10 GB; for 2 years ~1/6 of that, wall times ~3-5 x. NTL QA holds
# NTL, zones, BUI and a distance transform of the whole window (~8-10 GB, estimate): 8 cores.
# ntlv: from ntl (jobs 34956826-34956833): cutout 2 min / 10.3 GB of 15 (the 15 arc-sec source has 4 x the pixels of
# DMSP: 8 cores), QA 1.6 min / 9.7 GB with one layer (two layers share the zones / BUI / edge masks: 8 cores), features
# 6 min, train 19 min, predict 11 min / 14 GB, validate 7 min / 16 GB, county maps 2 min / 5.5 GB (5 counties x 3
# versions); wall times as ntl.
# y2020: from v3_all (12 years: features 16 min, train 1:37, predict 47 min, validate 12 min, water 14 min) for one
# year ~1/12 of features / train / predict; water and validate run all years again (validate: 12 years, 2 h wall).
# uncfilter: 4 of v3_all's 12 years per version: features ~6 min, train ~35 min (fewer rows), predict ~16 min,
# validate ~5 min (estimates); wall times ~3-4 x. Three versions run at the same time.
# plural: v5.6 2 years ~1/2 of uncfilter's 4-year jobs; variants 3 years + one feature (quantile breaks read the
# layer once more per year); cutout: two warps of a 900 m source per year, 3 years (NTLV took 2 min for 2 years).
# Seven chains side by side (estimates; wall times ~3-4 x).
# v56all: from plural (seff: v5.6 2 years features 4 min, train ~13 min, predict ~8 min / 13 GB, validate 6 years
# ~8 min / 15 GB) for 7 years ~3.5 x; validate 12 years; wall times ~3-4 x (estimates).
# aggdiag: as the v5.6 features job (7 years: 7 min / 9.6 GB) for 2 years + the float32 cell values (~5 GB) and the
# per-county medians: 8 cores, 1:30 wall (estimate).
# builtcell: per variant as one plural variant (2-3 years: features ~4 min, train ~15 min, predict ~8 min, validate
# ~4 min) + built_local per strip (a box sum over BUI / water / zones of the strip + halo: small); aggregation_diag as
# aggdiag (job 35099133); wall times ~3-4 x (estimates).
# externalv56: evaluate took minutes (job 35052319); city maps: 8 maps, window reads of 40 km boxes (estimate
# minutes, 2 cores, 45 min wall).
# citymeeting: the city maps job of externalv56 took 49 s for 8 maps, 0.4 GB (job 35194159); 3 maps + scatter plots:
# 2 cores, 30 min wall (MEET_TIME).
# nobuilt: per variant 5 years + one feature, from v5.6's runs (plural / v56all seff): features ~6 min, train ~30 min,
# predict ~20 min, validate ~10 min; cutout = one static layer (as DEM); wall times ~3-6 x (estimates). nobuilt_compare:
# 15 whole-window reads in strips + 18 city boxes (COMPARE_TIME, 1 h).
# v54nby: from nobuilt (jobs 35233306-35233314, sacct): features 10 min, train 25-33 min, predict 14-22 min, validate
# 5-6 min, nobuilt_compare 6 min; v5.4 trains on ~2,350-2,490 counties instead of ~1,590-1,670 (train ~1.5 x, estimate
# 45 min). Wall times ~2-4 x: features 40 min, train 2 h, predict 1 h, validate 30 min, compare 45 min; diag 1 h
# (record_uncertainty read 17 rasters in < 1 h, job 35056349).
# v57all: from v54nby (jobs 35240999-35241004; 5 years: features 5 min, train 21 min, predict 14 min, validate 4 min)
# for 8 years ~1.6 x; validate 12 years as v56all (16 min, 20 GB, job 35090245); city meeting 2 x citymeeting (the
# v5.6 numbers again); wall times ~3-4 x: features 40 min, train 2:30, predict 1:30, validate 1 h.
# v57nbya: as v54nby's chain (jobs 35240999-35241004: features 5 min, train 21 min, predict 14 min, validate 4 min,
# compare 4 min) + the factor check (two small CSV reads per year, < 1 min); wall times as v54nby.
# v57plural: per variant as v57nbya for 3 of its 5 years + one feature (jobs of v57nbya: features 5 min, train 21 min,
# predict 14 min, validate 4 min) and the v5.6 PLURAL test (quantile breaks: one more layer read per year); six chains
# side by side; wall times as v57nbya (estimates). Compare: 13 versions x 3 years of whole-window cell reads, 1 h.
# citydensity: as citymeeting (same boxes and product moves, 6 small figures): 2 cores, 30 min (DENS_TIME).
# pluralcm: predict / validate as one v57plural variant (jobs 35904624 / 35904625: predict 15 min / 14 GB on 32 cores,
# validate 9 min / 17 GB); variance and compare 4 cores, 1 h each (DIAG_TIME, COMPARE_TIME; estimates).
# degurbaboxes: select 4 cores 1 h (SELECT_TIME), run 4 cores 1 h (DEG_TIME; city density took 1.5 min for 6 of
# the 22 box-years, estimate).
# unbuiltoverlap: the cells of the run job again (the run took minutes) + sums over 11 x 2 box-years: 4 cores, 1 h
# (OVERLAP_TIME).
# missed1980: the whole CONUS window in strips (as aggregation_diag, 8 cores 1:30) + two 100 m product moves per strip
# + sorts of ~10^8 unbuilt cells: 8 cores, 3 h (MISSED_TIME; MISSED_TASKS for more memory; estimates).
# cap1980: missed1980's strips without GHS-BUILT + every mask cell + 20 allocations + the tract grid: 12 cores, 3 h
# (CAP_TIME; CAP_TASKS for more memory; estimates).
# captransfer: cap1980 (job 36298987: 10 min, 23 GB) + 3 product moves in 2010 + 3 more year passes + ~73 allocations:
# 12 cores, 4 h (TRANSFER_TIME; TRANSFER_TASKS for more memory; estimates).
# Job ids go to logs/conus_<mode>_jobs.txt.
set -euo pipefail
mode=${1:-}
[[ $mode =~ ^(trial|pilot|v3v4|bui|models|all|ntl|ntlv|external|y2020|uncertainty|uncfilter|plural|v56all|aggdiag|builtcell|externalv56|citymeeting|nobuilt|v54nby|v57all|v57nbya|v57plural|citydensity|pluralcm|degurbaboxes|unbuiltoverlap|missed1980|cap1980|captransfer)$ ]] || { echo "usage: bash sbatch/submit_conus.sh trial|pilot|v3v4|bui|models|all|ntl|ntlv|external|y2020|uncertainty|uncfilter|plural|v56all|aggdiag|builtcell|externalv56|citymeeting|nobuilt|v54nby|v57all|v57nbya|v57plural|citydensity|pluralcm|degurbaboxes|unbuiltoverlap|missed1980|cap1980|captransfer"; exit 1; }
cd "$(dirname "$0")/.."
source sbatch/cluster_env.sh
mkdir -p logs

S=configs/conus_study_area.yaml
V1=configs/conus_rf_v1.yaml
V2=configs/conus_rf_v2.yaml
CEN=$DATA_ROOT/processed/census_conus

sub() {  # sub <after job ids, space separated or empty> <sbatch args...>
    local dep=""
    [[ -n $1 ]] && dep="--dependency=afterok:${1// /:}"
    shift
    sbatch --parsable $dep "$@"
}

if [[ $mode == trial ]]; then
    Y=1960
    jc=$(sub "" sbatch/census_conus.sh --years 1920 1960 2010)
    jg=$(sub "$jc" --ntasks=4 --time=03:00:00 --export=ALL,CONFIG=$S,CENSUS_DIR=$CEN sbatch/grid_cutout.sh --years $Y)
    jw=$(sub "$jg" --ntasks=16 --time=04:00:00 --export=ALL,CONFIG=$S sbatch/water_frac.sh --years $Y)
    jp=$(sub "$jg" --ntasks=8 --time=01:00:00 --export=ALL,CONFIG=$S sbatch/place_dist.sh --years $Y)
    jf=$(sub "$jw" --ntasks=4 --time=02:00:00 --export=ALL,CONFIG=$V1 sbatch/dasymetric_features.sh --years $Y)
    jt=$(sub "$jf" --ntasks=16 --time=01:00:00 --export=ALL,CONFIG=$V1 sbatch/dasymetric_train.sh --years $Y)
    jm=$(sub "$jt" --ntasks=32 --time=01:00:00 --export=ALL,CONFIG=$V1 sbatch/dasymetric_predict.sh --years $Y \
         --measure 3 --map-years --compare-years)
    echo "census_conus $jc | grid_cutout $jg | water_frac $jw | place_dist $jp | features $jf | train $jt | predict(measure) $jm" \
        | tee logs/conus_trial_jobs.txt
elif [[ $mode == v3v4 ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years"
    jb=$(sub "" --ntasks=2 --time=${BUI_TIME:-00:30:00} --export=ALL,CONFIG=$S sbatch/bui_qa.sh)  # A: nothing waits for it
    jd=$(sub "" --ntasks=4 --time=${CUTOUT_TIME:-01:00:00} --export=ALL,CONFIG=$S,CENSUS_DIR=$CEN sbatch/grid_cutout.sh          --layers DEM)
    r1=$(sub "" --ntasks=8 --time=${VALIDATE_TIME:-01:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh          --version Dasy_CONUS_RF_v1 --years 1920 1960 2010 $VAL)
    r2=$(sub "" --ntasks=8 --time=${VALIDATE_TIME:-01:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh          --version Dasy_CONUS_RF_v2 --years 1960 2010 $VAL)
    ids=""
    for v in 3 4; do
        C=configs/conus_rf_v$v.yaml
        f=$(sub "$jd" --ntasks=6 --time=${FEATURES_TIME:-00:30:00} --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh)
        t=$(sub "$f" --ntasks=16 --time=${TRAIN_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh)
        p=$(sub "$t" --ntasks=32 --time=${PREDICT_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh)
        q=$(sub "$p" --ntasks=8 --time=${VALIDATE_TIME:-01:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh             --version Dasy_CONUS_RF_v$v --years 1960 2010 $VAL)
        ids="$ids | v$v features $f train $t predict $p validate $q"
        [[ $v == 4 ]] && { p4=$p; q4=$q; }
    done
    # D: 4 rural counties 60-150 km from a 250k+ place where v2's rural tract error grew most (docs/conus_plan.md)
    jm=$(sub "$p4 $q4 $r1 $r2" --ntasks=4 --time=${MAPS_TIME:-00:30:00} --export=ALL,CONFIG=$S sbatch/county_maps.sh          --counties G5300070 G2001550 G0800430 G1701170          --versions Dasy_CONUS_RF_v1 Dasy_CONUS_RF_v2 Dasy_CONUS_RF_v4)
    echo "bui_qa $jb | dem_cutout $jd | validate rerun v1 $r1 v2 $r2$ids | county_maps $jm"         | tee logs/conus_v3v4_jobs.txt
elif [[ $mode == bui ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years"
    jf=$(sub "" --ntasks=2 --time=${FIX_TIME:-01:00:00} --export=ALL,CONFIG=$S sbatch/bui_fix.sh)
    # Massachusetts: count cells above the cap in the raw HISDAC BUI over its window; nothing waits for it
    jc=$(sub "" --ntasks=2 --time=${CHECK_TIME:-00:30:00} --export=ALL,CONFIG=configs/study_area.yaml sbatch/bui_fix.sh          --check --cap 3e7 --hisdac-dir "$HISDAC_DIR" --window-json results/cutout/massachusetts/window.json)
    ids="" after=""
    for v in v1_bui v3_bui; do
        C=configs/conus_rf_$v.yaml
        f=$(sub "$jf" --ntasks=6 --time=${FEATURES_TIME:-00:30:00} --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh)
        t=$(sub "$f" --ntasks=16 --time=${TRAIN_TIME:-01:30:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh)
        p=$(sub "$t" --ntasks=32 --time=${PREDICT_TIME:-01:30:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh)
        q=$(sub "$p" --ntasks=8 --time=${VALIDATE_TIME:-01:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh             --version Dasy_CONUS_RF_$v --years 1920 1960 2010 $VAL)
        ids="$ids | $v features $f train $t predict $p validate $q"
        after="$after $p $q"
    done
    # same 4 rural counties as v3v4 (docs/conus_plan.md "County maps"); v2 / v4 tract errors are in results/validation
    jm=$(sub "${after# }" --ntasks=4 --time=${MAPS_TIME:-00:30:00} --export=ALL,CONFIG=$S sbatch/county_maps.sh          --counties G5300070 G2001550 G0800430 G1701170          --versions Dasy_CONUS_RF_v1_bui Dasy_CONUS_RF_v2 Dasy_CONUS_RF_v3_bui Dasy_CONUS_RF_v4)
    echo "bui_fix $jf | ma_check $jc$ids | county_maps $jm" | tee logs/conus_bui_jobs.txt
elif [[ $mode == models ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    D=$HISDAC_SCRATCH/dasymetric/conus
    SRC=Dasy_CONUS_RF_v3_bui
    declare -A VER=([rf]=Dasy_CONUS_RF_v3_n60 [lgbm]=Dasy_CONUS_LGBM_v3_n60 [xgb]=Dasy_CONUS_XGB_v3_n60
                    [cat]=Dasy_CONUS_CAT_v3_n60)
    for e in Y1920 Y1960 Y2010; do  # everything is checked before anything is copied or submitted
        for f in $D/$SRC/$e/features/county_features.csv $D/$SRC/$e/model/oof_predictions.csv; do
            [[ -f $f ]] || { echo "ERROR: $f not found (bui chain, section 3); nothing submitted"; exit 1; }
        done
    done
    # same features as v3_bui: its county_features.csv is copied (identical inputs for every model)
    for m in rf lgbm xgb cat; do
        for e in Y1920 Y1960 Y2010; do
            mkdir -p $D/${VER[$m]}/$e/features
            cp $D/$SRC/$e/features/county_features.csv $D/${VER[$m]}/$e/features/
        done
    done
    echo "copied $SRC features (Y1920 Y1960 Y2010) to ${VER[*]}"
    je=$(sub "" sbatch/test_env_hisdac.sh)  # everything below waits for it: a broken env runs nothing
    r0=$(sub "$je" --ntasks=8 --time=${VALIDATE_TIME:-01:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh          --version $SRC --years 1920 1960 2010 $VAL)
    ids="" after_val="$r0" after_maps=""
    for m in rf lgbm xgb cat; do
        C=configs/conus_${m}_v3_n60.yaml
        t=$(sub "$je" --ntasks=16 --time=${TRAIN_TIME:-02:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh)
        p=$(sub "$t" --ntasks=32 --time=${PREDICT_TIME:-01:30:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh)
        q=$(sub "$p" --ntasks=8 --time=${VALIDATE_TIME:-01:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh             --version ${VER[$m]} --years 1920 1960 2010 $VAL)
        ids="$ids | $m train $t predict $p validate $q"
        after_val="$after_val $q"
        after_maps="$after_maps $p $q"
    done
    jc=$(sub "$after_val" sbatch/compare_models.sh --versions $SRC ${VER[rf]} ${VER[lgbm]} ${VER[xgb]} ${VER[cat]})
    jm=$(sub "${after_maps# }" --ntasks=4 --time=${MAPS_TIME:-00:30:00} --export=ALL,CONFIG=$S sbatch/county_maps.sh          --counties G5300070 G2001550 G0800430 G1701170          --versions ${VER[rf]} ${VER[lgbm]} ${VER[xgb]} ${VER[cat]})
    echo "env_check $je | validate $SRC $r0$ids | compare_models $jc | county_maps $jm" | tee logs/conus_models_jobs.txt
elif [[ $mode == all ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    C=configs/conus_rf_v3_all.yaml
    V=Dasy_CONUS_RF_v3_all
    REF=Dasy_CONUS_RF_v3_n60
    NEW="1900 1910 1930 1940 1950 1970 1980 1990 2000"  # 1920 / 1960 / 2010 are in the cutout already (BUI fixed)
    D=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    miss=()  # everything is checked before anything is submitted
    for y in 1900 1910 1920 1930 1940 1950 1960 1970 1980 1990 2000 2010; do
        [[ -f $DATA_ROOT/processed/census/counties_$y.gpkg ]] || miss+=("$DATA_ROOT/processed/census/counties_$y.gpkg")
    done
    for f in $DATA_ROOT/processed/census/counties_std_2010.gpkg $CUT/window.json $CUT/layers/DEM/DEM.tif \
             $CUT/layers/BUI_raw/{1920,1960,2010}_BUI.tif $D/$REF/Y{1920,1960,2010}/model/oof_predictions.csv \
             results/validation/conus/$REF/metrics_by_year.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    jc=$(sub "" --time=${CENSUS_TIME:-00:30:00} sbatch/census_conus.sh)  # 1900-2010 (default years)
    jg=$(sub "$jc" --ntasks=4 --time=${CUTOUT_TIME:-01:00:00} --export=ALL,CONFIG=$S,CENSUS_DIR=$CEN sbatch/grid_cutout.sh \
         --years $NEW)
    jb=$(sub "$jg" --ntasks=2 --time=${FIX_TIME:-01:00:00} --export=ALL,CONFIG=$S sbatch/bui_fix.sh --years $NEW)
    # all 12 years: the QA points (1920 / 1960 / 2010) and one QA file; the 3 old layers come out the same
    jw=$(sub "$jg" --ntasks=16 --time=${WATER_TIME:-02:00:00} --export=ALL,CONFIG=$S sbatch/water_frac.sh)
    jf=$(sub "$jb $jw" --ntasks=6 --time=${FEATURES_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh)
    jt=$(sub "$jf" --ntasks=16 --time=${TRAIN_TIME:-05:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh)
    jp=$(sub "$jt" --ntasks=32 --time=${PREDICT_TIME:-03:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh)
    jv=$(sub "$jp" --ntasks=8 --time=${VALIDATE_TIME:-02:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
         --version $V --years 1910 1920 1930 1940 1950 1960 1970 1980 1990 2000 2010 $VAL)  # no tracts in 1900
    R=results/validation/conus/$V
    js=$(sub "$jv" --time=${SUMMARY_TIME:-00:20:00} sbatch/compare_models.sh --versions $V --repro-with $REF \
         --out $R/summary_by_year.csv --plot $R/mdape_by_year.png)
    echo "census_conus $jc | grid_cutout $jg | bui_fix $jb | water_frac $jw | features $jf | train $jt | predict $jp | validate $jv | summary $js" \
        | tee logs/conus_all_jobs.txt
elif [[ $mode == ntl ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    C=configs/conus_rf_v3_ntl.yaml
    V=Dasy_CONUS_RF_v3_ntl
    REF=Dasy_CONUS_RF_v3_all
    D=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    miss=()  # everything is checked before anything is submitted
    for y in 1900 1910 1920 1930 1940 1950 1960 1970 1980 1990 2000 2010; do  # --layers checks the window on all years
        [[ -f $CEN/counties_$y.gpkg ]] || miss+=("$CEN/counties_$y.gpkg")
    done
    for y in 2000 2010; do
        n=$(compgen -G "/projects/jaju1407/data/raw/ntl/Harmonized_DN_NTL_${y}_*.tif" | wc -l || true)
        [[ $n == 1 ]] || miss+=("exactly one /projects/jaju1407/data/raw/ntl/Harmonized_DN_NTL_${y}_*.tif (found $n)")
        for f in $CUT/zones/zones_$y.tif $CUT/layers/BUI/${y}_BUI.tif $CUT/layers/water_frac/${y}_water_frac.tif \
                 $D/$REF/Y$y/features/county_features.csv $D/$REF/Y$y/model/oof_predictions.csv \
                 $D/$REF/Y$y/model/test_predictions.csv results/dasymetric/conus/$REF/Y$y/metrics.json \
                 results/validation/conus/$REF/tract_errors_$y.csv; do
            [[ -f $f ]] || miss+=("$f")
        done
    done
    for f in $CUT/window.json $CUT/layers/DEM/DEM.tif $D/$REF/predictions/pop_2010.tif \
             results/validation/conus/$REF/metrics_by_year.csv results/dasymetric/conus/$REF/cv_summary.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    jn=$(sub "" --ntasks=4 --time=${CUTOUT_TIME:-01:00:00} --export=ALL,CONFIG=$S,CENSUS_DIR=$CEN sbatch/grid_cutout.sh \
         --layers NTL)
    jq=$(sub "$jn" --ntasks=8 --time=${QA_TIME:-00:45:00} --export=ALL,CONFIG=$S sbatch/ntl_qa.sh)  # nothing waits for it
    jf=$(sub "$jn" --ntasks=6 --time=${FEATURES_TIME:-00:45:00} --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh)
    jt=$(sub "$jf" --ntasks=16 --time=${TRAIN_TIME:-01:30:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh)
    jp=$(sub "$jt" --ntasks=32 --time=${PREDICT_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh)
    jv=$(sub "$jp" --ntasks=8 --time=${VALIDATE_TIME:-01:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
         --version $V --years 2000 2010 $VAL)
    jc=$(sub "$jv" sbatch/compare_models.sh --versions $REF $V --years 2000 2010 --rank-features ntl \
         --out results/validation/conus/ntl_comparison.csv)
    # same 4 rural counties as before (Chelan WA, Reno KS, Fremont CO, Macoupin IL); own folder: the model family
    # maps in county_maps/ are kept
    jm=$(sub "$jp $jv" --ntasks=4 --time=${MAPS_TIME:-00:30:00} --export=ALL,CONFIG=$S sbatch/county_maps.sh \
         --counties G5300070 G2001550 G0800430 G1701170 --versions $REF $V \
         --out-dir results/validation/conus/county_maps_ntl)
    echo "ntl_cutout $jn | ntl_qa $jq | features $jf | train $jt | predict $jp | validate $jv | compare $jc | county_maps $jm" \
        | tee logs/conus_ntl_jobs.txt
elif [[ $mode == ntlv ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    C=configs/conus_rf_v3_ntlv.yaml
    V=Dasy_CONUS_RF_v3_ntlv
    REF=Dasy_CONUS_RF_v3_all
    NTL=Dasy_CONUS_RF_v3_ntl
    D=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    miss=()  # everything is checked before anything is submitted
    for y in 1900 1910 1920 1930 1940 1950 1960 1970 1980 1990 2000 2010; do  # --layers checks the window on all years
        [[ -f $CEN/counties_$y.gpkg ]] || miss+=("$CEN/counties_$y.gpkg")
    done
    for y in 2000 2010; do
        n=$(compgen -G "$DATA_ROOT/raw/ntl/viirs_like/v1/$y/*.tif" | wc -l || true)
        [[ $n == 1 ]] || miss+=("exactly one $DATA_ROOT/raw/ntl/viirs_like/v1/$y/*.tif (found $n; run sbatch/ntlv_download.sh)")
        for f in $CUT/zones/zones_$y.tif $CUT/layers/BUI/${y}_BUI.tif $CUT/layers/water_frac/${y}_water_frac.tif \
                 $CUT/layers/NTL/${y}_NTL.tif \
                 $D/$REF/Y$y/features/county_features.csv $D/$REF/Y$y/model/oof_predictions.csv \
                 $D/$REF/Y$y/model/test_predictions.csv results/dasymetric/conus/$REF/Y$y/metrics.json \
                 results/dasymetric/conus/$NTL/Y$y/metrics.json results/validation/conus/$REF/tract_errors_$y.csv \
                 results/validation/conus/$NTL/tract_errors_$y.csv; do
            [[ -f $f ]] || miss+=("$f")
        done
    done
    for f in $CUT/window.json $CUT/layers/DEM/DEM.tif $D/$REF/predictions/pop_2010.tif $D/$NTL/predictions/pop_2010.tif \
             results/validation/conus/$REF/metrics_by_year.csv results/dasymetric/conus/$REF/cv_summary.csv \
             results/validation/conus/$NTL/metrics_by_year.csv results/dasymetric/conus/$NTL/cv_summary.csv \
             results/cutout/conus/ntlv_check.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    jn=$(sub "" --ntasks=8 --time=${CUTOUT_TIME:-01:00:00} --export=ALL,CONFIG=$S,CENSUS_DIR=$CEN sbatch/grid_cutout.sh \
         --layers NTLV)
    jq=$(sub "$jn" --ntasks=8 --time=${QA_TIME:-00:45:00} --export=ALL,CONFIG=$S sbatch/ntl_qa.sh \
         --layer NTL NTLV)  # nothing waits for it
    jf=$(sub "$jn" --ntasks=6 --time=${FEATURES_TIME:-00:45:00} --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh)
    jt=$(sub "$jf" --ntasks=16 --time=${TRAIN_TIME:-01:30:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh)
    jp=$(sub "$jt" --ntasks=32 --time=${PREDICT_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh)
    jv=$(sub "$jp" --ntasks=8 --time=${VALIDATE_TIME:-01:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
         --version $V --years 2000 2010 $VAL)
    jc=$(sub "$jv" sbatch/compare_models.sh --versions $REF $NTL $V --years 2000 2010 --rank-features ntl ntlv \
         --out results/validation/conus/ntl_viirs_comparison.csv)
    # the 4 counties of the NTL test (Chelan WA, Reno KS, Fremont CO, Macoupin IL: BUI gap) + DuPage IL (BUI gap);
    # own folder: county_maps_ntl/ is kept
    jm=$(sub "$jp $jv" --ntasks=4 --time=${MAPS_TIME:-00:30:00} --export=ALL,CONFIG=$S sbatch/county_maps.sh \
         --counties G5300070 G2001550 G0800430 G1701170 G1700430 --versions $REF $NTL $V \
         --out-dir results/validation/conus/county_maps_ntlv)
    echo "ntlv_cutout $jn | ntl_qa $jq | features $jf | train $jt | predict $jp | validate $jv | compare $jc | county_maps $jm" \
        | tee logs/conus_ntlv_jobs.txt
elif [[ $mode == external ]]; then
    REF=Dasy_CONUS_RF_v3_all
    TR=$DATA_ROOT/processed/tract
    miss=()
    for y in 1910 1920 1930 1940 1950 1970 1980 1990 2000 2010; do  # the years of configs/external_grids.yaml
        for f in $TR/tracts_$y.gpkg results/validation/conus/$REF/tract_errors_$y.csv; do
            [[ -f $f ]] || miss+=("$f")
        done
    done
    activate_env hisdac
    python -c "import exactextract, py7zr, openpyxl" 2>/dev/null \
        || miss+=("exactextract / py7zr / openpyxl in the hisdac env (env update: Running_CONUS.md section 8, block 1a)")
    avail=$(python src/validation/external_compare.py inventory --available --data-root "$DATA_ROOT/raw/external")
    [[ -n $avail ]] || miss+=("any product with all its files under $DATA_ROOT/raw/external (run sbatch/external_download.sh)")
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    # cores / wall time per product (estimate: exactextract on 46-72k tracts per year; 100 m products have ~70 x
    # the pixels of the 1 km ones): GHS-POP 4 years, WorldPop 2 years at 100 m / 3 arc-sec
    declare -A RES=([ghs_pop]="16 06:00:00" [worldpop]="16 04:00:00" [gpw4]="4 01:00:00" [grump1]="4 01:00:00"
                    [fj_m3]="4 01:30:00" [fj_m5]="4 01:30:00")
    ids=() line=""
    for p in $avail; do
        read -r n t <<< "${RES[$p]:-4 02:00:00}"
        j=$(sub "" --ntasks=$n --time=$t --job-name=external_$p sbatch/external_compare.sh extract --product $p)
        ids+=("$j")
        line+="extract_$p $j | "
    done
    # evaluate after all extract jobs, however they ended: a failed product is a `missing` row, not a stop
    je=$(sbatch --parsable --dependency=afterany:$(IFS=:; echo "${ids[*]}") --ntasks=2 --time=00:30:00 \
         --job-name=external_evaluate sbatch/external_compare.sh evaluate)
    echo "${line}evaluate $je" | tee logs/conus_external_jobs.txt
    echo "== not downloaded (skipped): $(for p in ghs_pop worldpop gpw4 grump1 fj_m3 fj_m5; do [[ " $avail " == *" $p "* ]] || printf '%s ' $p; done)"
elif [[ $mode == externalv56 ]]; then
    PRODS="ghs_pop worldpop fj_m3 fj_m5"  # the downloaded products (GPW / GRUMP were never fetched: no Earthdata login)
    declare -A YRS=([ghs_pop]="1980 1990 2000 2010" [worldpop]="2000 2010"
                    [fj_m3]="1910 1920 1930 1940 1950 1970 1980 1990 2000 2010"
                    [fj_m5]="1910 1920 1930 1940 1950 1970 1980 1990 2000 2010")
    miss=()
    for p in $PRODS; do
        for y in ${YRS[$p]}; do  # tract sums of the 2026-10-30 extract (v5.4's tracts = v5.6's), reused, not redone
            f=$HISDAC_SCRATCH/external/conus/sums/${p}_$y.csv
            [[ -f $f ]] || miss+=("$f")
        done
    done
    for y in 1910 1920 1930 1940 1950 1970 1980 1990 2000 2010; do
        for v in Dasy_CONUS_RF_v3_u070 Dasy_CONUS_RF_v3_all; do
            f=results/validation/conus/$v/tract_errors_$y.csv
            [[ -f $f ]] || miss+=("$f")
        done
    done
    echo "PRECHECK sums + tract errors: $(( ${#miss[@]} )) missing"
    bash sbatch/external_city_maps.sh --check > logs/conus_externalv56_check.txt 2>&1 \
        || miss+=("city-map inputs (see logs/conus_externalv56_check.txt: grep MISSING)")
    grep -E "CHECK OK|MISSING|ERROR" logs/conus_externalv56_check.txt || true
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    je=$(sub "" --ntasks=2 --time=${EVAL_TIME:-00:30:00} --job-name=external_evaluate sbatch/external_compare.sh \
         evaluate --products $PRODS --strict-sums)
    jm=$(sub "" --time=${MAPS_TIME:-00:45:00} sbatch/external_city_maps.sh)
    echo "evaluate $je | city_maps $jm" | tee logs/conus_externalv56_jobs.txt
elif [[ $mode == citymeeting ]]; then
    # inputs: v5.6 pop_2010, the cutout's 2010 BUI, GHS-POP / WorldPop 2010; NobuiltYear optional (NA without it)
    if ! bash sbatch/external_city_meeting.sh --check > logs/conus_citymeeting_check.txt 2>&1; then
        grep -E "MISSING|ERROR" logs/conus_citymeeting_check.txt || true
        echo "ERROR: nothing submitted (see logs/conus_citymeeting_check.txt)"; exit 1
    fi
    grep -E "CHECK OK|NobuiltYear" logs/conus_citymeeting_check.txt || true
    jc=$(sub "" --time=${MEET_TIME:-00:30:00} sbatch/external_city_meeting.sh)
    echo "city_meeting $jc" | tee logs/conus_citymeeting_jobs.txt
elif [[ $mode == y2020 ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    C=configs/conus_rf_v3_all.yaml
    V=Dasy_CONUS_RF_v3_all
    REF=Dasy_CONUS_RF_v3_n60
    D=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    OLD="1900 1910 1920 1930 1940 1950 1960 1970 1980 1990 2000 2010"
    miss=()  # everything is checked before anything is submitted (details: bash sbatch/y2020_precheck.sh)
    for f in $DATA_ROOT/processed/census/counties_2020.gpkg $DATA_ROOT/processed/census/counties_std_2010.gpkg \
             $DATA_ROOT/processed/tract/tracts_2020.gpkg $CUT/window.json $CUT/layers/DEM/DEM.tif \
             $D/$V/qa/reallocation_qa.csv $D/$V/qa/water_mask_by_year.csv $D/$V/cv_summary.csv \
             $D/$REF/Y2010/model/oof_predictions.csv results/validation/conus/$REF/metrics_by_year.csv \
             $HISDAC_DIR/Land_Use/RO/Count_2020_RO.tif; do
        [[ -f $f ]] || miss+=("$f")
    done
    for l in BUI BUPL BUPR BUA; do
        [[ -f $HISDAC_DIR/$l/2020_$l.tif ]] || miss+=("$HISDAC_DIR/$l/2020_$l.tif")
    done
    for y in $OLD; do
        for f in $CEN/counties_$y.gpkg $CUT/zones/zones_$y.tif $D/$V/Y$y/model/rf.joblib $D/$V/predictions/pop_$y.tif; do
            [[ -f $f ]] || miss+=("$f")
        done
    done
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    jc=$(sub "" --time=${CENSUS_TIME:-00:30:00} sbatch/census_conus.sh --years 2020)
    jg=$(sub "$jc" --ntasks=4 --time=${CUTOUT_TIME:-01:00:00} --export=ALL,CONFIG=$S,CENSUS_DIR=$CEN sbatch/grid_cutout.sh \
         --years 2020)
    jb=$(sub "$jg" --ntasks=2 --time=${FIX_TIME:-00:30:00} --export=ALL,CONFIG=$S sbatch/bui_fix.sh --years 2020)
    # all 13 years: one QA file with the QA points (1920 / 1960 / 2010); the 12 old layers come out the same
    jw=$(sub "$jg" --ntasks=16 --time=${WATER_TIME:-02:00:00} --export=ALL,CONFIG=$S sbatch/water_frac.sh)
    jf=$(sub "$jb $jw" --ntasks=6 --time=${FEATURES_TIME:-00:45:00} --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh \
         --years 2020)
    jt=$(sub "$jf" --ntasks=16 --time=${TRAIN_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh --years 2020)
    jp=$(sub "$jt" --ntasks=32 --time=${PREDICT_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh \
         --years 2020)
    # all tract years again (metrics_by_year.csv holds every year; the old tract_errors_{YEAR}.csv must come out the same)
    jv=$(sub "$jp" --ntasks=8 --time=${VALIDATE_TIME:-02:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
         --version $V --years 1910 1920 1930 1940 1950 1960 1970 1980 1990 2000 2010 2020 $VAL)
    R=results/validation/conus/$V
    js=$(sub "$jv" --time=${SUMMARY_TIME:-00:20:00} sbatch/compare_models.sh --versions $V --repro-with $REF \
         --out $R/summary_by_year.csv --plot $R/mdape_by_year.png)
    jm=$(sub "$jv" sbatch/metrics_over_time.sh --version $V)
    echo "census_conus $jc | grid_cutout $jg | bui_fix $jb | water_frac $jw | features $jf | train $jt | predict $jp | validate $jv | summary $js | metrics_over_time $jm" \
        | tee logs/conus_y2020_jobs.txt
elif [[ $mode == uncfilter ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    YRS="1920 1960 2010 2020"
    BASE=Dasy_CONUS_RF_v3_all
    D=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    U=results/hisdac_uncertainty
    miss=()  # everything is checked before anything is submitted
    for f in $U/county_record_uncertainty.csv $U/nobuilt_values.csv $HISDAC_DIR/BUI/2015_BUI.tif $CUT/window.json \
             $CUT/layers/DEM/DEM.tif $CUT/zones/zones_2010.csv $D/$BASE/predictions/pop_2010.tif; do
        [[ -f $f ]] || miss+=("$f")
    done
    for y in $YRS; do
        for f in $CUT/zones/zones_$y.tif $CUT/layers/BUI/${y}_BUI.tif $CUT/layers/water_frac/${y}_water_frac.tif \
                 $DATA_ROOT/processed/tract/tracts_$y.gpkg $D/$BASE/Y$y/model/oof_predictions.csv \
                 results/dasymetric/conus/$BASE/Y$y/test_predictions.csv results/dasymetric/conus/$BASE/Y$y/county_features.csv \
                 results/validation/conus/$BASE/tract_errors_$y.csv; do
            [[ -f $f ]] || miss+=("$f")
        done
    done
    echo "PRECHECK: $(( ${#miss[@]} )) missing of the inputs (record uncertainty, BUI 2015, cutout $YRS, tracts, v5.4 outputs)"
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    jx=$(sub "" --time=${FILTER_TIME:-00:30:00} sbatch/uncertainty_filter.sh)
    ids="" after=""
    for t in 090 070 050; do  # three versions side by side; train waits for the exclusion sets
        C=configs/conus_rf_v3_u$t.yaml
        f=$(sub "" --ntasks=6 --time=${FEATURES_TIME:-00:45:00} --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh)
        tr=$(sub "$f $jx" --ntasks=16 --time=${TRAIN_TIME:-02:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh)
        p=$(sub "$tr" --ntasks=32 --time=${PREDICT_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh)
        q=$(sub "$p" --ntasks=8 --time=${VALIDATE_TIME:-01:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
            --version Dasy_CONUS_RF_v3_u$t --years $YRS $VAL)
        ids="$ids | u$t features $f train $tr predict $p validate $q"
        after="$after $q"
    done
    jc=$(sub "${after# }" sbatch/filter_compare.sh)
    echo "uncertainty_filter $jx$ids | filter_compare $jc" | tee logs/conus_uncfilter_jobs.txt
elif [[ $mode == plural ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    BASE=Dasy_CONUS_RF_v3_u070  # v5.6
    C0=configs/conus_rf_v3_u070.yaml
    V54=Dasy_CONUS_RF_v3_all
    D=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    SRC=$DATA_ROOT/raw/plural/siqiao_2026/PLURAL_grid_data
    miss=()  # everything is checked before anything is submitted
    for y in 1900 1910 1920 1930 1940 1950 1960 1970 1980 1990 2000 2010 2020; do  # --layers checks the window on all years
        [[ -f $CEN/counties_$y.gpkg ]] || miss+=("$CEN/counties_$y.gpkg")
    done
    for y in 1940 1980 2010; do
        for f in $SRC/index3_${y}_900_US.tif $CUT/zones/zones_$y.tif $CUT/layers/BUI/${y}_BUI.tif \
                 $CUT/layers/Land_Use/RO/${y}_RO.tif $CUT/layers/water_frac/${y}_water_frac.tif \
                 $D/$V54/Y$y/model/oof_predictions.csv; do
            [[ -f $f ]] || miss+=("$f")
        done
    done
    for y in 1920 1940 1960 1980 2010 2020; do  # v5.6 is validated again on all its years (the old ones must not change)
        [[ -f $DATA_ROOT/processed/tract/tracts_$y.gpkg ]] || miss+=("$DATA_ROOT/processed/tract/tracts_$y.gpkg")
    done
    for y in 1920 1960 2010 2020; do  # the v5.6 eras that are kept as they are
        for f in $D/$BASE/Y$y/model/rf.joblib $D/$BASE/predictions/pop_$y.tif; do
            [[ -f $f ]] || miss+=("$f")
        done
    done
    for f in $CUT/window.json $CUT/layers/DEM/DEM.tif $D/$BASE/cv_summary.csv $D/$BASE/qa/reallocation_qa.csv \
             $D/$BASE/qa/water_mask_by_year.csv results/hisdac_uncertainty/excluded_counties_t070.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    echo "PRECHECK: $(( ${#miss[@]} )) missing of the inputs (PLURAL 900 m files, cutout 1940 / 1980 / 2010, tracts, v5.6 + v5.4 outputs)"
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    jn=$(sub "" --ntasks=8 --time=${CUTOUT_TIME:-01:00:00} --export=ALL,CONFIG=$S,CENSUS_DIR=$CEN sbatch/grid_cutout.sh \
         --layers PLURAL PLURALC)
    jq=$(sub "$jn" --ntasks=8 --time=${QA_TIME:-00:45:00} --export=ALL,CONFIG=$S sbatch/plural_qa.sh)  # nothing waits for it
    # v5.6 for 1940 / 1980 only (--years: its other eras and the other years' rows of its QA / summary CSVs are kept)
    bf=$(sub "" --ntasks=6 --time=${FEATURES_TIME:-00:45:00} --export=ALL,CONFIG=$C0 sbatch/dasymetric_features.sh --years 1940 1980)
    bt=$(sub "$bf" --ntasks=16 --time=${TRAIN_TIME:-02:00:00} --export=ALL,CONFIG=$C0 sbatch/dasymetric_train.sh --years 1940 1980)
    bp=$(sub "$bt" --ntasks=32 --time=${PREDICT_TIME:-01:00:00} --export=ALL,CONFIG=$C0 sbatch/dasymetric_predict.sh --years 1940 1980)
    bv=$(sub "$bp" --ntasks=8 --time=${VALIDATE_TIME:-01:30:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
         --version $BASE --years 1920 1940 1960 1980 2010 2020 $VAL)
    ids="plural_cutout $jn | plural_qa $jq | v5.6 features $bf train $bt predict $bp validate $bv" after="$bv"
    for v in plc plcc pq3 pq5 pe3 pe5; do  # each = v5.6 + plural, 1940 / 1980 / 2010; train compares with v5.6 (needs its 1940 / 1980)
        C=configs/conus_rf_v3_u070_$v.yaml
        f=$(sub "$jn" --ntasks=6 --time=${FEATURES_TIME:-00:45:00} --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh)
        t=$(sub "$f $bt" --ntasks=16 --time=${TRAIN_TIME:-02:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh)
        p=$(sub "$t" --ntasks=32 --time=${PREDICT_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh)
        q=$(sub "$p" --ntasks=8 --time=${VALIDATE_TIME:-01:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
            --version ${BASE}_$v --years 1940 1980 2010 $VAL)
        ids="$ids | $v features $f train $t predict $p validate $q"
        after="$after $q"
    done
    jc=$(sub "$after" sbatch/plural_compare.sh)
    echo "$ids | plural_compare $jc" | tee logs/conus_plural_jobs.txt
elif [[ $mode == v56all ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    V=Dasy_CONUS_RF_v3_u070  # v5.6, the final version
    C=configs/conus_rf_v3_u070.yaml
    V54=Dasy_CONUS_RF_v3_all
    NEW="1900 1910 1930 1950 1970 1990 2000"
    OLD="1920 1940 1960 1980 2010 2020"
    D=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    TR=$DATA_ROOT/processed/tract
    miss=()  # everything is checked before anything is submitted
    for y in $NEW; do
        for f in $CUT/zones/zones_$y.tif $CUT/zones/zones_$y.csv $CUT/layers/water_frac/${y}_water_frac.tif \
                 $D/$V54/Y$y/model/oof_predictions.csv $D/$V54/Y$y/model/test_predictions.csv; do
            [[ -f $f ]] || miss+=("$f")
        done
        for l in BUI BUPL BUPR BUA; do
            [[ -f $CUT/layers/$l/${y}_$l.tif ]] || miss+=("$CUT/layers/$l/${y}_$l.tif")
        done
        if (( y >= 1940 )); then [[ -f $CUT/layers/Land_Use/RO/${y}_RO.tif ]] || miss+=("$CUT/layers/Land_Use/RO/${y}_RO.tif"); fi
    done
    for y in $OLD; do  # the eras that are kept as they are
        for f in $D/$V/Y$y/model/rf.joblib $D/$V/predictions/pop_$y.tif; do
            [[ -f $f ]] || miss+=("$f")
        done
    done
    for f in $CUT/window.json $CUT/layers/DEM/DEM.tif $D/$V/cv_summary.csv $D/$V/qa/reallocation_qa.csv \
             $D/$V/qa/water_mask_by_year.csv results/hisdac_uncertainty/excluded_counties_t070.csv \
             results/validation/conus/$V54/metrics_by_year.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    VYRS=""  # tract years: every year with a tract file (1900: none expected)
    for y in 1900 1910 1920 1930 1940 1950 1960 1970 1980 1990 2000 2010 2020; do
        if [[ -f $TR/tracts_$y.gpkg ]]; then VYRS="$VYRS $y"
        elif [[ $y == 1900 ]]; then echo "SKIP 1900 tract validation: no $TR/tracts_1900.gpkg (as v5.4)"
        else miss+=("$TR/tracts_$y.gpkg"); fi
    done
    echo "PRECHECK: $(( ${#miss[@]} )) missing of the inputs (cutout $NEW, v5.6 eras $OLD, v5.4 eras, tracts) | tract years:$VYRS"
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    # --years: only the new eras are computed; the old eras and the other years' rows of the QA / summary CSVs stay
    jf=$(sub "" --ntasks=6 --time=${FEATURES_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh --years $NEW)
    jt=$(sub "$jf" --ntasks=16 --time=${TRAIN_TIME:-03:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh --years $NEW)
    jp=$(sub "$jt" --ntasks=32 --time=${PREDICT_TIME:-02:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh --years $NEW)
    # every tract year again (metrics_by_year.csv holds all years; the old tract_errors_{YEAR}.csv must come out the same)
    jv=$(sub "$jp" --ntasks=8 --time=${VALIDATE_TIME:-02:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
         --version $V --years $VYRS $VAL)
    R=results/validation/conus/$V
    js=$(sub "$jv" --time=${SUMMARY_TIME:-00:20:00} sbatch/compare_models.sh --versions $V $V54 \
         --exclusions results/hisdac_uncertainty/excluded_counties_t070.csv --out $R/summary_by_year.csv \
         --plot $R/mdape_by_year.png)
    jm=$(sub "$jv" --time=${SUMMARY_TIME:-00:20:00} sbatch/metrics_over_time.sh --version $V --compare-with $V54)
    echo "features $jf | train $jt | predict $jp | validate $jv | summary $js | metrics_over_time $jm" \
        | tee logs/conus_v56all_jobs.txt
elif [[ $mode == aggdiag ]]; then
    V=Dasy_CONUS_RF_v3_u070  # v5.6
    C=configs/conus_rf_v3_u070.yaml
    D=$HISDAC_SCRATCH/dasymetric/conus/$V
    CUT=$HISDAC_SCRATCH/cutouts/conus
    miss=()
    for y in 1960 2010; do
        for f in $D/predictions/pop_$y.tif $D/Y$y/features/county_features.csv $CUT/zones/zones_$y.tif                  $CUT/zones/zones_$y.csv $CUT/layers/water_frac/${y}_water_frac.tif                  results/validation/conus/$V/tract_errors_$y.csv; do
            [[ -f $f ]] || miss+=("$f")
        done
        for l in BUI BUPL BUPR BUA Land_Use/RO; do
            [[ -f $CUT/layers/$l/${y}_${l#Land_Use/}.tif ]] || miss+=("$CUT/layers/$l/${y}_${l#Land_Use/}.tif")
        done
    done
    for f in $CUT/layers/DEM/DEM.tif results/hisdac_uncertainty/excluded_counties_t070.csv configs/conus_split.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    echo "PRECHECK: $(( ${#miss[@]} )) missing (v5.6 predictions + features 1960 / 2010, cutout, tract errors)"
    if (( ${#miss[@]} )); then printf 'MISSING %s
' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    ja=$(sub "" --ntasks=${AGG_TASKS:-8} --time=${AGG_TIME:-01:30:00} --export=ALL,CONFIG=$C sbatch/aggregation_diag.sh          --years 1960 2010)
    echo "aggregation_diag $ja" | tee logs/conus_aggdiag_jobs.txt
elif [[ $mode == builtcell ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    BASE=Dasy_CONUS_RF_v3_u070  # v5.6
    C0=configs/conus_rf_v3_u070.yaml
    D=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    OUT=results/validation/conus/builtcell
    miss=()  # everything is checked before anything is submitted
    for y in 1960 2010; do
        for f in $D/$BASE/predictions/pop_$y.tif $D/$BASE/Y$y/features/county_features.csv \
                 $D/$BASE/Y$y/model/oof_predictions.csv $D/$BASE/Y$y/model/test_predictions.csv \
                 $CUT/zones/zones_$y.tif $CUT/zones/zones_$y.csv $CUT/layers/water_frac/${y}_water_frac.tif \
                 $DATA_ROOT/processed/tract/tracts_$y.gpkg results/validation/conus/$BASE/tract_errors_$y.csv; do
            [[ -f $f ]] || miss+=("$f")
        done
        for l in BUI BUPL BUPR BUA Land_Use/RO; do
            [[ -f $CUT/layers/$l/${y}_${l#Land_Use/}.tif ]] || miss+=("$CUT/layers/$l/${y}_${l#Land_Use/}.tif")
        done
    done
    for f in $CUT/layers/DEM/DEM.tif $DATA_ROOT/processed/census_conus/counties_2010.gpkg \
             results/hisdac_uncertainty/excluded_counties_t070.csv configs/conus_split.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    echo "PRECHECK: $(( ${#miss[@]} )) missing (v5.6 1960 / 2010 outputs, cutout, tracts, exclusions)"
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    # v5.6 itself is not rerun; only its cells are measured again (empty-cell share next to the variants)
    jb=$(sub "" --ntasks=${AGG_TASKS:-8} --time=${AGG_TIME:-01:30:00} --export=ALL,CONFIG=$C0 sbatch/aggregation_diag.sh \
         --years 1960 2010 --out $OUT/diag/base)
    ids="v5.6 aggregation_diag $jb" after="$jb"
    for v in bc3 bc5 bc9; do  # each = v5.6 features with built-cell county means + built_local (k x k), 1960 / 2010
        C=configs/conus_rf_v3_u070_$v.yaml
        f=$(sub "" --ntasks=6 --time=${FEATURES_TIME:-00:45:00} --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh)
        t=$(sub "$f" --ntasks=16 --time=${TRAIN_TIME:-02:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh)
        p=$(sub "$t" --ntasks=32 --time=${PREDICT_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh)
        q=$(sub "$p" --ntasks=8 --time=${VALIDATE_TIME:-01:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
            --version ${BASE}_$v --years 1960 2010 $VAL --gap-version $BASE)
        a=$(sub "$p" --ntasks=${AGG_TASKS:-8} --time=${AGG_TIME:-01:30:00} --export=ALL,CONFIG=$C \
            sbatch/aggregation_diag.sh --years 1960 2010 --out $OUT/diag/$v)
        ids="$ids | $v features $f train $t predict $p validate $q aggregation_diag $a"
        after="$after $q $a"
    done
    jc=$(sub "$after" sbatch/builtcell_compare.sh)
    echo "$ids | builtcell_compare $jc" | tee logs/conus_builtcell_jobs.txt
elif [[ $mode == nobuilt ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    BASE=Dasy_CONUS_RF_v3_u070  # v5.6 (not rerun)
    YRS="1910 1940 1960 1980 2010"
    D=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    miss=()  # everything is checked before anything is submitted
    for y in 1900 1910 1920 1930 1940 1950 1960 1970 1980 1990 2000 2010 2020; do  # --layers checks the window on all years
        [[ -f $CEN/counties_$y.gpkg ]] || miss+=("$CEN/counties_$y.gpkg")
    done
    for y in $YRS; do
        for f in $CUT/zones/zones_$y.tif $CUT/zones/zones_$y.csv $CUT/layers/water_frac/${y}_water_frac.tif \
                 $D/$BASE/Y$y/model/rf.joblib $D/$BASE/Y$y/model/oof_predictions.csv \
                 $D/$BASE/Y$y/model/test_predictions.csv $D/$BASE/predictions/pop_$y.tif \
                 $DATA_ROOT/processed/tract/tracts_$y.gpkg results/validation/conus/$BASE/tract_errors_$y.csv \
                 results/dasymetric/conus/$BASE/Y$y/test_predictions.csv; do
            [[ -f $f ]] || miss+=("$f")
        done
        for l in BUI BUPL BUPR BUA; do
            [[ -f $CUT/layers/$l/${y}_$l.tif ]] || miss+=("$CUT/layers/$l/${y}_$l.tif")
        done
        if (( y >= 1940 )); then [[ -f $CUT/layers/Land_Use/RO/${y}_RO.tif ]] || miss+=("$CUT/layers/Land_Use/RO/${y}_RO.tif"); fi
    done
    for f in $HISDAC_DIR/FBUY/NobuiltYear.tif $CUT/window.json $CUT/layers/DEM/DEM.tif \
             results/hisdac_uncertainty/county_record_uncertainty.csv \
             results/hisdac_uncertainty/excluded_counties_t070.csv configs/conus_split.csv \
             results/validation/conus/external/city_maps_meeting/gap_blocks.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    # city gap blocks: v5.6 pop / BUI / GHS-POP of 1980 and 2010 = the meeting maps' inputs
    if bash sbatch/external_city_meeting.sh --check > logs/conus_nobuilt_city_check.txt 2>&1; then
        grep -E "CHECK OK" logs/conus_nobuilt_city_check.txt || true
    else
        miss+=("city-map inputs (logs/conus_nobuilt_city_check.txt)")
        grep -E "MISSING|ERROR" logs/conus_nobuilt_city_check.txt || true
    fi
    echo "PRECHECK: $(( ${#miss[@]} )) missing of the inputs (NobuiltYear, cutout $YRS, v5.6 outputs, tracts, BUPR_2015 sums, city maps)"
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    jn=$(sub "" --ntasks=8 --time=${CUTOUT_TIME:-01:00:00} --export=ALL,CONFIG=$S,CENSUS_DIR=$CEN sbatch/grid_cutout.sh \
         --layers NOBUILT)
    ids="nobuilt_cutout $jn" after=""
    for v in nby nbya; do  # v5.6 + nby / + nby_age, 1910 / 1940 / 1960 / 1980 / 2010; train compares with v5.6
        C=configs/conus_rf_v3_u070_$v.yaml
        f=$(sub "$jn" --ntasks=6 --time=${FEATURES_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh)
        t=$(sub "$f" --ntasks=16 --time=${TRAIN_TIME:-03:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh)
        p=$(sub "$t" --ntasks=32 --time=${PREDICT_TIME:-01:30:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh)
        q=$(sub "$p" --ntasks=8 --time=${VALIDATE_TIME:-01:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
            --version ${BASE}_$v --years $YRS $VAL --gap-version $BASE)
        ids="$ids | $v features $f train $t predict $p validate $q"
        after="$after $q"
    done
    jc=$(sub "${after# }" --time=${COMPARE_TIME:-01:00:00} sbatch/nobuilt_compare.sh)
    echo "$ids | nobuilt_compare $jc" | tee logs/conus_nobuilt_jobs.txt
elif [[ $mode == v54nby ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    V54=Dasy_CONUS_RF_v3_all V56=Dasy_CONUS_RF_v3_u070 NEW=Dasy_CONUS_RF_v3_all_nby  # v5.4 / v5.6 / v5.6 + nby not rerun
    YRS="1910 1940 1960 1980 2010"
    D=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    NB=results/validation/conus/nobuilt
    miss=()  # everything is checked before anything is submitted
    for y in $YRS; do
        for f in $CUT/zones/zones_$y.tif $CUT/zones/zones_$y.csv $CUT/layers/water_frac/${y}_water_frac.tif \
                 $D/$V54/Y$y/model/rf.joblib $D/$V54/Y$y/model/oof_predictions.csv $D/$V54/Y$y/model/test_predictions.csv \
                 $DATA_ROOT/processed/tract/tracts_$y.gpkg; do
            [[ -f $f ]] || miss+=("$f")
        done
        for v in $V54 $V56 ${V56}_nby; do  # cells / city (scratch) and tract / county rows (results) of the compared
            for f in $D/$v/predictions/pop_$y.tif results/validation/conus/$v/tract_errors_$y.csv \
                     results/dasymetric/conus/$v/Y$y/test_predictions.csv results/dasymetric/conus/$v/Y$y/metrics.json; do
                [[ -f $f ]] || miss+=("$f")
            done
        done
        for l in BUI BUPL BUPR BUA; do
            [[ -f $CUT/layers/$l/${y}_$l.tif ]] || miss+=("$CUT/layers/$l/${y}_$l.tif")
        done
        if (( y >= 1940 )); then [[ -f $CUT/layers/Land_Use/RO/${y}_RO.tif ]] || miss+=("$CUT/layers/Land_Use/RO/${y}_RO.tif"); fi
    done
    for f in $CUT/layers/NOBUILT/NOBUILT.tif $CUT/window.json $CUT/layers/DEM/DEM.tif $CUT/zones/zones_2010.tif \
             $HISDAC_DIR/FBUY/FBUY.tif $HISDAC_DIR/FBUY/NobuiltYear.tif $HISDAC_DIR/BUPR/2015_BUPR.tif \
             results/hisdac_uncertainty/county_record_uncertainty.csv results/hisdac_uncertainty/excluded_counties_t070.csv \
             configs/conus_split.csv results/validation/conus/external/city_maps_meeting/gap_blocks.csv \
             $NB/nobuilt_cells.csv $NB/nobuilt_city_gaps.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    # city gap blocks: v5.6 pop / BUI / GHS-POP of 1980 and 2010 = the meeting maps' inputs
    if bash sbatch/external_city_meeting.sh --check > logs/conus_v54nby_city_check.txt 2>&1; then
        grep -E "CHECK OK" logs/conus_v54nby_city_check.txt || true
    else
        miss+=("city-map inputs (logs/conus_v54nby_city_check.txt)")
        grep -E "MISSING|ERROR" logs/conus_v54nby_city_check.txt || true
    fi
    echo "PRECHECK: $(( ${#miss[@]} )) missing of the inputs (cutout incl. NOBUILT $YRS, v5.4 / v5.6 / v5.6 + nby outputs, tracts, FBUY, BUPR_2015, nobuilt results, city maps)"
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    # CURC maintenance (default 2026-11-04 06:30-18:30 MT): a job whose wall time does not end before the window starts
    # waits until after it. Chain estimate (nobuilt sacct) vs the minutes left; submitted anyway.
    FT=${FEATURES_TIME:-00:40:00} TT=${TRAIN_TIME:-02:00:00} PT=${PREDICT_TIME:-01:00:00} QT=${VALIDATE_TIME:-00:30:00}
    CT=${COMPARE_TIME:-00:45:00} GT=${DIAG_TIME:-01:00:00}
    MS=${MAINT_START:-2026-11-04 06:30} ME=${MAINT_END:-2026-11-04 18:30}
    mins() { local h m s; IFS=: read -r h m s <<< "$1"; echo $(( 10#$h * 60 + 10#$m + (10#${s:-0} > 0) )); }
    now=$(date +%s); ts=$(TZ=America/Denver date -d "$MS" +%s); te=$(TZ=America/Denver date -d "$ME" +%s)
    echo "TIME now $(TZ=America/Denver date '+%Y-%m-%d %H:%M %Z') | maintenance $MS - $ME MT"
    if (( now >= te )); then
        echo "TIME maintenance window is over: no wait (chain estimate ~1.5 h)"
    elif (( now >= ts )); then
        echo "TIME maintenance in progress: every job waits until it ends ($ME MT), then runs (chain estimate ~1.5 h)"
    else
        left=$(( (ts - now) / 60 )) start=0 late=""
        for step in "features 10 $(mins $FT)" "train 45 $(mins $TT)" "predict 22 $(mins $PT)" "validate 6 $(mins $QT)" \
                    "compare 6 $(mins $CT)"; do  # name, estimated minutes, wall minutes; one after the other
            read -r n est wall <<< "$step"
            (( start + wall <= left )) || late="$late $n"
            start=$(( start + est ))
        done
        (( $(mins $GT) <= left )) || late="$late diag"
        echo "TIME $left min until the maintenance | chain estimate ~$start min (features + train + predict + validate + compare; diag side by side) | wall $FT $TT $PT $QT $CT, diag $GT"
        if [[ -n $late ]]; then
            echo "TIME NOTE: the wall time of${late} does not end before $MS MT at the estimated start: those jobs run AFTER the maintenance (from $ME MT). Submitted anyway."
        else
            echo "TIME OK: every job's wall time ends before the maintenance at the estimated start"
        fi
    fi
    C=configs/conus_rf_v3_all_nby.yaml
    f=$(sub "" --ntasks=6 --time=$FT --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh)
    t=$(sub "$f" --ntasks=16 --time=$TT --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh)
    p=$(sub "$t" --ntasks=32 --time=$PT --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh)
    q=$(sub "$p" --ntasks=8 --time=$QT --export=ALL,COVERAGE= sbatch/validate_tract.sh \
        --version $NEW --years $YRS $VAL --gap-version $V56)
    jc=$(sub "$q" --time=$CT sbatch/v54_nby_compare.sh)
    jd=$(sub "" --time=$GT sbatch/undated_age_diag.sh)
    echo "v54_nby features $f train $t predict $p validate $q | v54_nby_compare $jc | undated_age_diag $jd" \
        | tee logs/conus_v54nby_jobs.txt
elif [[ $mode == v57all ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    V=Dasy_CONUS_RF_v3_all_nby  # v5.7 = v5.4 + nby, no filter (the next base version)
    C=configs/conus_rf_v3_all_nby.yaml
    V54=Dasy_CONUS_RF_v3_all V56=Dasy_CONUS_RF_v3_u070  # not rerun
    NEW="1900 1920 1930 1950 1970 1990 2000 2020"
    OLD="1910 1940 1960 1980 2010"  # run 2026-11-04; must stay as they are (snapshot -> kept_years_check)
    D=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    TR=$DATA_ROOT/processed/tract
    EXT=results/validation/conus/external
    NB=results/validation/conus/nobuilt
    PRODS="ghs_pop worldpop fj_m3 fj_m5"  # as externalv56 (GPW / GRUMP never fetched)
    declare -A PY=([ghs_pop]="1980 1990 2000 2010" [worldpop]="2000 2010"
                   [fj_m3]="1910 1920 1930 1940 1950 1970 1980 1990 2000 2010"
                   [fj_m5]="1910 1920 1930 1940 1950 1970 1980 1990 2000 2010")
    miss=()  # everything is checked before anything is submitted
    for y in $NEW; do
        for f in $CUT/zones/zones_$y.tif $CUT/zones/zones_$y.csv $CUT/layers/water_frac/${y}_water_frac.tif \
                 $CEN/counties_$y.gpkg $D/$V54/Y$y/model/rf.joblib $D/$V54/Y$y/model/oof_predictions.csv \
                 $D/$V54/Y$y/model/test_predictions.csv; do
            [[ -f $f ]] || miss+=("$f")
        done
        for l in BUI BUPL BUPR BUA; do
            [[ -f $CUT/layers/$l/${y}_$l.tif ]] || miss+=("$CUT/layers/$l/${y}_$l.tif")
        done
        if (( y >= 1940 )); then [[ -f $CUT/layers/Land_Use/RO/${y}_RO.tif ]] || miss+=("$CUT/layers/Land_Use/RO/${y}_RO.tif"); fi
    done
    for y in $OLD; do  # the eras that are kept as they are
        for f in $D/$V/Y$y/model/rf.joblib $D/$V/Y$y/model/metrics.json $D/$V/predictions/pop_$y.tif; do
            [[ -f $f ]] || miss+=("$f")
        done
    done
    for f in $CUT/window.json $CUT/layers/DEM/DEM.tif $CUT/layers/NOBUILT/NOBUILT.tif $D/$V/cv_summary.csv \
             $D/$V/qa/reallocation_qa.csv $D/$V/qa/water_mask_by_year.csv \
             results/hisdac_uncertainty/excluded_counties_t070.csv $NB/v54_nby_comparison.csv \
             $EXT/city_maps_meeting/meeting_summary.csv $EXT/city_maps_meeting/gap_blocks.csv \
             $EXT/external_comparison_v56.csv results/validation/conus/$V54/metrics_by_year.csv \
             results/validation/conus/$V56/metrics_by_year.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    VYRS=""  # tract years: every year with a tract file (1900: none expected); gap counties from v5.6
    for y in 1900 1910 1920 1930 1940 1950 1960 1970 1980 1990 2000 2010 2020; do
        if [[ -f $TR/tracts_$y.gpkg ]]; then
            VYRS="$VYRS $y"
            [[ -f $D/$V56/Y$y/features/county_features.csv ]] || miss+=("$D/$V56/Y$y/features/county_features.csv")
        elif [[ $y == 1900 ]]; then echo "SKIP 1900 tract validation: no $TR/tracts_1900.gpkg (as v5.4 / v5.6)"
        else miss+=("$TR/tracts_$y.gpkg"); fi
    done
    for p in $PRODS; do
        for y in ${PY[$p]}; do  # tract sums of the 2026-10-30 extract (v5.6's tracts), reused, not redone
            f=$HISDAC_SCRATCH/external/conus/sums/${p}_$y.csv
            [[ -f $f ]] || miss+=("$f")
        done
    done
    # meeting maps: v5.7 pop 1980 / 2010 (kept years) + v5.6's (recomputed) + BUI / GHS-POP / WorldPop / NobuiltYear
    MEET="MEET_VERSION=$V,MEET_LABEL=v5.7,MEET_OUT=$EXT/city_maps_meeting_v57"
    if MEET_VERSION=$V MEET_LABEL=v5.7 MEET_OUT=$EXT/city_maps_meeting_v57 \
        bash sbatch/external_city_meeting.sh --check > logs/conus_v57all_city_check.txt 2>&1; then
        grep -E "CHECK OK" logs/conus_v57all_city_check.txt || true
    else
        miss+=("city-map inputs (logs/conus_v57all_city_check.txt)")
        grep -E "MISSING|ERROR" logs/conus_v57all_city_check.txt || true
    fi
    echo "PRECHECK: $(( ${#miss[@]} )) missing of the inputs (cutout $NEW, v5.4 eras, v5.7 eras $OLD, v5.6 gap features, tracts, sums, meeting maps) | tract years:$VYRS"
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    # snapshot of the kept years (hashes, rows) before anything runs; kept_years_check compares after the chain
    SNAP=logs/conus_v57all_kept_years.json
    ( activate_env hisdac && python -u src/dasymetric/kept_years_check.py snapshot --json $SNAP --version-dir $D/$V \
        --results-dir results/dasymetric/conus/$V --validation-dir results/validation/conus/$V --years $OLD ) \
        || { echo "ERROR: snapshot failed, nothing submitted"; exit 1; }
    # --years: only the new eras are computed; the old eras and the other years' rows of the QA / summary CSVs stay
    jf=$(sub "" --ntasks=6 --time=${FEATURES_TIME:-00:40:00} --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh --years $NEW)
    jt=$(sub "$jf" --ntasks=16 --time=${TRAIN_TIME:-02:30:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh --years $NEW)
    jp=$(sub "$jt" --ntasks=32 --time=${PREDICT_TIME:-01:30:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh --years $NEW)
    # every tract year again (metrics_by_year.csv holds all years; the old tract_errors_{YEAR}.csv must come out the same)
    jv=$(sub "$jp" --ntasks=8 --time=${VALIDATE_TIME:-01:00:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
         --version $V --years $VYRS $VAL --gap-version $V56)
    jk=$(sub "$jv" sbatch/kept_years_check.sh --json $SNAP)
    R=results/validation/conus/$V
    js=$(sub "$jv" --time=${SUMMARY_TIME:-00:20:00} sbatch/compare_models.sh --versions $V $V54 $V56 \
         --exclusions results/hisdac_uncertainty/excluded_counties_t070.csv --out $R/summary_by_year.csv \
         --plot $R/mdape_by_year.png --check-against $NB/v54_nby_comparison.csv)
    jm=$(sub "$jv" --time=${SUMMARY_TIME:-00:20:00} sbatch/metrics_over_time.sh --version $V --compare-with $V54 $V56 \
         --exclusions results/hisdac_uncertainty/excluded_counties_t070.csv --check-against $NB/v54_nby_comparison.csv)
    # side by side after predict: meeting maps v5.7 (v5.6 recomputed + checked); external evaluate needs v5.7's tracts
    jc=$(sub "$jp" --time=${MEET_TIME:-00:45:00} --export=ALL,$MEET sbatch/external_city_meeting.sh)
    je=$(sub "$jv" --ntasks=2 --time=${EVAL_TIME:-00:30:00} --job-name=external_evaluate --export=ALL,EXT_TAG=v57 \
         sbatch/external_compare.sh evaluate --products $PRODS --strict-sums --reference $V \
         --reference-label "v5.7 ($V)" --compare-versions "$V56=v5.6 ($V56)" "$V54=v5.4 ($V54)" \
         --check-with $EXT/external_comparison_v56.csv)
    echo "features $jf | train $jt | predict $jp | validate $jv | kept_years_check $jk | summary $js | metrics_over_time $jm | city_meeting $jc | external_evaluate $je" \
        | tee logs/conus_v57all_jobs.txt
elif [[ $mode == v57nbya ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    NEW=Dasy_CONUS_RF_v3_all_nbya C=configs/conus_rf_v3_all_nbya.yaml
    V57=Dasy_CONUS_RF_v3_all_nby V54=Dasy_CONUS_RF_v3_all V56=Dasy_CONUS_RF_v3_u070 V56A=Dasy_CONUS_RF_v3_u070_nbya
    YRS="1910 1940 1960 1980 2010"
    D=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    RD=results/dasymetric/conus
    NB=results/validation/conus/nobuilt
    miss=()  # everything is checked before anything is submitted
    # the config = v5.7's eras with nby -> nby_age, every other setting as v5.7, nby_age block as the NobuiltYear test
    if ( activate_env hisdac && python -u src/validation/v57_nbya_compare.py config ) > logs/conus_v57nbya_config.txt 2>&1; then
        grep -E "CONFIG OK" logs/conus_v57nbya_config.txt
    else
        miss+=("config check (logs/conus_v57nbya_config.txt)")
        grep -E "CONFIG DIFFERS|ERROR" logs/conus_v57nbya_config.txt || tail -5 logs/conus_v57nbya_config.txt
    fi
    for y in $YRS; do
        for f in $CUT/zones/zones_$y.tif $CUT/zones/zones_$y.csv $CUT/layers/water_frac/${y}_water_frac.tif                  $D/$V57/Y$y/model/rf.joblib $D/$V57/Y$y/model/oof_predictions.csv $D/$V57/Y$y/model/test_predictions.csv                  $D/$V56/Y$y/features/county_features.csv $DATA_ROOT/processed/tract/tracts_$y.gpkg                  $RD/$V56A/Y$y/nby_age_factor.csv $RD/$V57/Y$y/county_features.csv $RD/$V57/Y$y/folds.csv; do
            [[ -f $f ]] || miss+=("$f")
        done
        for v in $V54 $V56 $V57 $V56A; do  # cells / city (scratch) and tract / county rows (results) of the compared
            for f in $D/$v/predictions/pop_$y.tif results/validation/conus/$v/tract_errors_$y.csv                      $RD/$v/Y$y/test_predictions.csv $RD/$v/Y$y/metrics.json; do
                [[ -f $f ]] || miss+=("$f")
            done
        done
        for l in BUI BUPL BUPR BUA; do
            [[ -f $CUT/layers/$l/${y}_$l.tif ]] || miss+=("$CUT/layers/$l/${y}_$l.tif")
        done
        if (( y >= 1940 )); then [[ -f $CUT/layers/Land_Use/RO/${y}_RO.tif ]] || miss+=("$CUT/layers/Land_Use/RO/${y}_RO.tif"); fi
    done
    for f in $CUT/layers/NOBUILT/NOBUILT.tif $CUT/window.json $CUT/layers/DEM/DEM.tif              results/hisdac_uncertainty/county_record_uncertainty.csv results/hisdac_uncertainty/excluded_counties_t070.csv              configs/conus_split.csv results/validation/conus/external/city_maps_meeting/gap_blocks.csv              $NB/nobuilt_comparison.csv $NB/nobuilt_cells.csv $NB/nobuilt_city_gaps.csv              $NB/v54_nby_comparison.csv $NB/v54_nby_cells.csv $NB/v54_nby_city_gaps.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    [[ -e $D/$NEW ]] && echo "NOTE: $D/$NEW exists already (a rerun overwrites its eras)"
    # city gap blocks: v5.6 pop / BUI / GHS-POP of 1980 and 2010 = the meeting maps' inputs
    if bash sbatch/external_city_meeting.sh --check > logs/conus_v57nbya_city_check.txt 2>&1; then
        grep -E "CHECK OK" logs/conus_v57nbya_city_check.txt || true
    else
        miss+=("city-map inputs (logs/conus_v57nbya_city_check.txt)")
        grep -E "MISSING|ERROR" logs/conus_v57nbya_city_check.txt || true
    fi
    echo "PRECHECK: $(( ${#miss[@]} )) missing of the inputs (config, cutout incl. NOBUILT $YRS, v5.7 eras, old nby_age factors, v5.4 / v5.6 / v5.7 / v5.6 + nby_age outputs, tracts, nobuilt / v54_nby results, city maps)"
    if (( ${#miss[@]} )); then printf 'MISSING %s
' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    jf=$(sub "" --ntasks=6 --time=${FEATURES_TIME:-00:40:00} --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh)
    # nby_age factors = the NobuiltYear test's, county features = v5.7's with nby -> nby_age; else nothing trains
    jk=$(sub "$jf" --ntasks=1 --time=${FACTOR_TIME:-00:15:00} --job-name=v57_nbya_factors sbatch/v57_nbya_compare.sh factors)
    jt=$(sub "$jk" --ntasks=16 --time=${TRAIN_TIME:-02:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh)
    jp=$(sub "$jt" --ntasks=32 --time=${PREDICT_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh)
    jv=$(sub "$jp" --ntasks=8 --time=${VALIDATE_TIME:-00:30:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh          --version $NEW --years $YRS $VAL --gap-version $V56)
    jc=$(sub "$jv" --time=${COMPARE_TIME:-00:45:00} sbatch/v57_nbya_compare.sh compare)
    echo "features $jf | factor_check $jk | train $jt | predict $jp | validate $jv | v57_nbya_compare $jc"         | tee logs/conus_v57nbya_jobs.txt
elif [[ $mode == v57plural ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    V57=Dasy_CONUS_RF_v3_all_nby V56=Dasy_CONUS_RF_v3_u070
    VARS="plc plcc pq3 pq5 pe3 pe5"
    YRS="1940 1980 2010"  # the PLURAL grid's years
    D=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    RD=results/dasymetric/conus
    NB=results/validation/conus/nobuilt
    miss=()  # everything is checked before anything is submitted
    # each config = v5.7's eras + plural, plural block as the v5.6 test, every other setting as v5.7
    if ( activate_env hisdac && python -u src/validation/v57_plural_compare.py config ) > logs/conus_v57plural_config.txt 2>&1; then
        grep -E "CONFIG OK" logs/conus_v57plural_config.txt
    else
        miss+=("config check (logs/conus_v57plural_config.txt)")
        grep -E "CONFIG DIFFERS|ERROR" logs/conus_v57plural_config.txt || tail -5 logs/conus_v57plural_config.txt
    fi
    nref=0
    for y in $YRS; do
        # cutout (PLURAL / PLURALC exist since the v5.6 test; not made again), v5.7's era (compare_with), tracts
        for f in $CUT/zones/zones_$y.tif $CUT/zones/zones_$y.csv $CUT/layers/water_frac/${y}_water_frac.tif \
                 $CUT/layers/PLURAL/${y}_PLURAL.tif $CUT/layers/PLURALC/${y}_PLURALC.tif $CUT/layers/Land_Use/RO/${y}_RO.tif \
                 $D/$V57/Y$y/model/rf.joblib $D/$V57/Y$y/model/oof_predictions.csv $D/$V57/Y$y/model/test_predictions.csv \
                 $RD/$V57/Y$y/county_features.csv $RD/$V57/Y$y/folds.csv $DATA_ROOT/processed/tract/tracts_$y.gpkg; do
            [[ -f $f ]] || miss+=("$f")
        done
        for l in BUI BUPL BUPR BUA; do
            [[ -f $CUT/layers/$l/${y}_$l.tif ]] || miss+=("$CUT/layers/$l/${y}_$l.tif")
        done
        for v in $V56 $V57; do  # tract / county rows (results) and cells (scratch) of the two bases
            for f in $D/$v/predictions/pop_$y.tif results/validation/conus/$v/tract_errors_$y.csv \
                     $RD/$v/Y$y/test_predictions.csv $RD/$v/Y$y/metrics.json; do
                [[ -f $f ]] || miss+=("$f")
            done
        done
        for v in $VARS; do  # the v5.6 PLURAL test: features check + reference columns (results)
            for f in $RD/${V56}_$v/Y$y/county_features.csv $RD/${V56}_$v/Y$y/test_predictions.csv \
                     $RD/${V56}_$v/Y$y/metrics.json results/validation/conus/${V56}_$v/tract_errors_$y.csv; do
                [[ -f $f ]] || miss+=("$f")
            done
            if [[ $v == pq* || $v == pe* ]]; then
                [[ -f $RD/${V56}_$v/Y$y/plural_breaks.csv ]] || miss+=("$RD/${V56}_$v/Y$y/plural_breaks.csv")
            fi
            [[ -f $D/${V56}_$v/predictions/pop_$y.tif ]] || nref=$((nref + 1))  # cells of the reference: optional
        done
    done
    for f in $CUT/layers/NOBUILT/NOBUILT.tif $CUT/window.json $CUT/layers/DEM/DEM.tif \
             results/hisdac_uncertainty/excluded_counties_t070.csv configs/conus_split.csv \
             $NB/v54_nby_comparison.csv $NB/v54_nby_cells.csv results/validation/conus/plural_grid/plural_comparison.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    for v in $VARS; do
        if [[ -e $D/${V57}_$v ]]; then echo "NOTE: $D/${V57}_$v exists already (a rerun overwrites its eras)"; fi
    done
    if (( nref )); then echo "NOTE: $nref v5.6 + plural predictions not on scratch (purged?): their cell rows are left out (tract / county rows kept)"; fi
    echo "PRECHECK: $(( ${#miss[@]} )) missing of the inputs (configs, cutout incl. PLURAL / PLURALC / NOBUILT $YRS, v5.7 eras, v5.6 / v5.7 outputs, v5.6 PLURAL test results, tracts, v54_nby / plural_grid tables)"
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    fs="" ids=""
    for v in $VARS; do
        C=configs/conus_rf_v3_all_nby_$v.yaml
        f=$(sub "" --ntasks=6 --time=${FEATURES_TIME:-00:40:00} --export=ALL,CONFIG=$C sbatch/dasymetric_features.sh)
        fs="$fs $f" ids="$ids | $v features $f"
    done
    # county plural + breaks = the v5.6 test's, other county features = v5.7's; else nothing trains
    jk=$(sub "${fs# }" --ntasks=1 --time=${CHECK_TIME:-00:15:00} --job-name=v57_plural_features sbatch/v57_plural_compare.sh features)
    qs=""
    for v in $VARS; do
        C=configs/conus_rf_v3_all_nby_$v.yaml
        t=$(sub "$jk" --ntasks=16 --time=${TRAIN_TIME:-02:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_train.sh)
        p=$(sub "$t" --ntasks=32 --time=${PREDICT_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh)
        q=$(sub "$p" --ntasks=8 --time=${VALIDATE_TIME:-00:30:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
            --version ${V57}_$v --years $YRS $VAL --gap-version $V56)
        qs="$qs $q" ids="$ids | $v train $t predict $p validate $q"
    done
    jc=$(sub "${qs# }" --time=${COMPARE_TIME:-01:00:00} sbatch/v57_plural_compare.sh compare)
    echo "${ids# | } | features_check $jk | v57_plural_compare $jc" | tee logs/conus_v57plural_jobs.txt
elif [[ $mode == pluralcm ]]; then
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years --gap-share 0.05"
    V57=Dasy_CONUS_RF_v3_all_nby V56=Dasy_CONUS_RF_v3_u070
    VARS="pq5 plc"  # PLURAL versions whose models are reused; new versions <version>cm
    YRS="1940 1980 2010"
    D=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    RD=results/dasymetric/conus
    PG=results/validation/conus/plural_grid_v57
    miss=()  # everything is checked before anything is submitted
    # each cm config = its PLURAL config + model_from / compare_with + plural cell_value county_mean
    if ( activate_env hisdac && python -u src/validation/plural_countymean.py config ) > logs/conus_pluralcm_config.txt 2>&1; then
        grep -E "CONFIG OK" logs/conus_pluralcm_config.txt
    else
        miss+=("config check (logs/conus_pluralcm_config.txt)")
        grep -E "CONFIG DIFFERS|ERROR" logs/conus_pluralcm_config.txt || tail -5 logs/conus_pluralcm_config.txt
    fi
    for y in $YRS; do
        # cutout (prediction features + variance layers), tracts, v5.6 gap counties (scratch), v5.7 / PLURAL results
        for f in $CUT/zones/zones_$y.tif $CUT/zones/zones_$y.csv $CUT/layers/water_frac/${y}_water_frac.tif                  $CUT/layers/PLURAL/${y}_PLURAL.tif $CUT/layers/Land_Use/RO/${y}_RO.tif                  $D/$V56/Y$y/features/county_features.csv $DATA_ROOT/processed/tract/tracts_$y.gpkg                  $RD/$V57/Y$y/county_features.csv $RD/$V57/Y$y/test_predictions.csv $D/$V57/predictions/pop_$y.tif; do
            [[ -f $f ]] || miss+=("$f")
        done
        for l in BUI BUPL BUPR BUA; do
            [[ -f $CUT/layers/$l/${y}_$l.tif ]] || miss+=("$CUT/layers/$l/${y}_$l.tif")
        done
        for v in $V56 $V57; do
            [[ -f results/validation/conus/$v/tract_errors_$y.csv ]] || miss+=("results/validation/conus/$v/tract_errors_$y.csv")
        done
        for v in $VARS; do  # the PLURAL version: model + county features (scratch), results, prediction, tracts
            P=${V57}_$v
            for f in $D/$P/Y$y/model/rf.joblib $D/$P/Y$y/model/test_predictions.csv $D/$P/Y$y/features/county_features.csv                      $D/$P/predictions/pop_$y.tif $RD/$P/Y$y/county_features.csv $RD/$P/Y$y/test_predictions.csv                      $RD/$P/Y$y/metrics.json results/validation/conus/$P/tract_errors_$y.csv; do
                [[ -f $f ]] || miss+=("$f")
            done
            if [[ $v == pq5 ]]; then
                for f in $D/$P/Y$y/features/plural_breaks.csv $RD/$P/Y$y/plural_breaks.csv; do
                    [[ -f $f ]] || miss+=("$f")
                done
            fi
        done
    done
    for v in $VARS; do
        [[ -f $D/${V57}_$v/cv_summary.csv ]] || miss+=("$D/${V57}_$v/cv_summary.csv")
        if [[ -e $D/${V57}_${v}cm ]]; then echo "NOTE: $D/${V57}_${v}cm exists already (a rerun overwrites it)"; fi
    done
    for f in $CUT/layers/NOBUILT/NOBUILT.tif $CUT/window.json $CUT/layers/DEM/DEM.tif              results/hisdac_uncertainty/excluded_counties_t070.csv configs/conus_split.csv              $PG/plural_v57_comparison.csv $PG/plural_v57_cells.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    echo "PRECHECK: $(( ${#miss[@]} )) missing of the inputs (configs, cutout $YRS, pq5 / plc models + county features, v5.6 / v5.7 / PLURAL outputs, tracts, plural_v57 tables)"
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    # hashes of the reused models / county features before anything runs (the compare checks the cm runs against it)
    if ( activate_env hisdac && python -u src/validation/plural_countymean.py snapshot --dasym-root "$HISDAC_SCRATCH/dasymetric" ) \
            > logs/conus_pluralcm_snapshot.txt 2>&1; then
        grep -E "SNAPSHOT OK" logs/conus_pluralcm_snapshot.txt
    else
        grep -E "MISSING|ERROR" logs/conus_pluralcm_snapshot.txt || tail -5 logs/conus_pluralcm_snapshot.txt
        echo "ERROR: nothing submitted (snapshot)"; exit 1
    fi
    jv=$(sub "" --ntasks=4 --time=${DIAG_TIME:-01:00:00} --job-name=pluralcm_variance sbatch/plural_countymean.sh variance)
    qs="" ids="variance $jv"
    for v in $VARS; do
        C=configs/conus_rf_v3_all_nby_${v}cm.yaml
        p=$(sub "" --ntasks=32 --time=${PREDICT_TIME:-01:00:00} --export=ALL,CONFIG=$C sbatch/dasymetric_predict.sh)
        q=$(sub "$p" --ntasks=8 --time=${VALIDATE_TIME:-00:30:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
            --version ${V57}_${v}cm --years $YRS $VAL --gap-version $V56)
        qs="$qs $q" ids="$ids | ${v}cm predict $p validate $q"
    done
    jc=$(sub "$jv$qs" --ntasks=4 --time=${COMPARE_TIME:-01:00:00} --job-name=pluralcm_compare sbatch/plural_countymean.sh compare)
    echo "$ids | compare $jc" | tee logs/conus_pluralcm_jobs.txt
elif [[ $mode == citydensity ]]; then
    V=${2:-Dasy_CONUS_RF_v3_all_nby} L=${3:-v5.7}
    DEF=results/validation/conus/external/city_maps_meeting_v57/meeting_summary_v56_v57.csv
    if [[ $V == Dasy_CONUS_RF_v3_all_nby ]]; then
        CHK=${DENS_CHECK_WITH:-$DEF}
    else
        CHK=${DENS_CHECK_WITH:?another version needs DENS_CHECK_WITH=<its meeting_summary_a_b.csv> or none}
    fi
    # extra versions (class rows + cell-type shares, no whole-box check): one VERSION=LABEL (sbatch --export), or none
    X=${DENS_EXTRA:-Dasy_CONUS_RF_v3_all_nby_pq5=v5.7_pq5}
    if ! DENS_VERSION=$V DENS_LABEL=$L DENS_CHECK_WITH=$CHK DENS_EXTRA=$X bash sbatch/external_city_density.sh --check \
            > logs/conus_citydensity_check.txt 2>&1; then
        grep -E "MISSING|ERROR" logs/conus_citydensity_check.txt || tail -5 logs/conus_citydensity_check.txt
        echo "ERROR: nothing submitted (see logs/conus_citydensity_check.txt)"; exit 1
    fi
    grep -E "CHECK OK|NobuiltYear|NOT checked" logs/conus_citydensity_check.txt || true
    jd=$(sub "" --time=${DENS_TIME:-00:30:00} \
         --export=ALL,DENS_VERSION=$V,DENS_LABEL=$L,DENS_CHECK_WITH=$CHK,DENS_EXTRA=$X sbatch/external_city_density.sh)
    echo "city_density $jd ($V $L; extra $X)" | tee logs/conus_citydensity_jobs.txt
elif [[ $mode == degurbaboxes ]]; then
    miss=()
    for y in 1980 2010; do
        f=$DATA_ROOT/raw/external/ghs_smod/GHS_SMOD_E${y}_GLOBE_R2023A_54009_1000_V2_0.tif
        [[ -f $f ]] || miss+=("$f (PRECHECK: PRODUCTS=ghs_smod bash sbatch/external_download.sh, section 26 block 0)")
    done
    [[ -f $DATA_ROOT/processed/census_conus/counties_2010.gpkg ]] || miss+=("$DATA_ROOT/processed/census_conus/counties_2010.gpkg")
    if (( ${#miss[@]} )); then printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1; fi
    st=$( (activate_env hisdac >/dev/null && python -u src/validation/degurba_boxes.py status) | tail -1)
    echo "boxes in configs/external_grids.yaml: $st"
    if ! bash sbatch/degurba_boxes.sh run --check > logs/conus_degurbaboxes_check.txt 2>&1; then
        grep -E "MISSING|ERROR" logs/conus_degurbaboxes_check.txt || tail -5 logs/conus_degurbaboxes_check.txt
        echo "ERROR: nothing submitted (see logs/conus_degurbaboxes_check.txt)"; exit 1
    fi
    grep -E "CHECK OK|NobuiltYear" logs/conus_degurbaboxes_check.txt || true
    js=""
    if [[ $st == "BOXES EMPTY" ]]; then
        if ! bash sbatch/degurba_boxes.sh select --check >> logs/conus_degurbaboxes_check.txt 2>&1; then
            tail -5 logs/conus_degurbaboxes_check.txt; echo "ERROR: nothing submitted (select inputs)"; exit 1
        fi
        js=$(sub "" --time=${SELECT_TIME:-01:00:00} --job-name=degurba_select sbatch/degurba_boxes.sh select)
        echo "box selection job $js (the run waits for it)"
    else
        echo "boxes chosen already: no selection job (the run reads them)"
    fi
    jr=$(sub "$js" --time=${DEG_TIME:-01:00:00} --job-name=degurba_run sbatch/degurba_boxes.sh run)
    echo "${js:+select $js | }run $jr" | tee logs/conus_degurbaboxes_jobs.txt
elif [[ $mode == unbuiltoverlap ]]; then
    st=$( (activate_env hisdac >/dev/null && python -u src/validation/degurba_boxes.py status) | tail -1)
    echo "boxes in configs/external_grids.yaml: $st"
    [[ $st == "BOXES SET 8" ]] || { echo "ERROR: nothing submitted (the 8 boxes of degurbaboxes are not in the config)"; exit 1; }
    if ! bash sbatch/degurba_boxes.sh overlap --check > logs/conus_unbuiltoverlap_check.txt 2>&1; then
        grep -E "MISSING|ERROR" logs/conus_unbuiltoverlap_check.txt || tail -5 logs/conus_unbuiltoverlap_check.txt
        echo "ERROR: nothing submitted (see logs/conus_unbuiltoverlap_check.txt)"; exit 1
    fi
    grep -E "CHECK OK|cell_type_shares" logs/conus_unbuiltoverlap_check.txt || true
    jo=$(sub "" --time=${OVERLAP_TIME:-01:00:00} --job-name=unbuilt_overlap sbatch/degurba_boxes.sh overlap)
    echo "overlap $jo" | tee logs/conus_unbuiltoverlap_jobs.txt
elif [[ $mode == missed1980 ]]; then
    miss=()
    E=$DATA_ROOT/raw/external
    for f in $E/ghs_built/GHS_BUILT_S_E1980_GLOBE_R2023A_54009_100_V1_0.tif              $E/ghs_pop/GHS_POP_E1980_GLOBE_R2023A_54009_100_V1_0.tif              $E/ghs_smod/GHS_SMOD_E1980_GLOBE_R2023A_54009_1000_V2_0.tif              $DATA_ROOT/processed/census_conus/counties_2010.gpkg              results/validation/conus/external/degurba_boxes_v57/cell_type_shares.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    if (( ${#miss[@]} )); then
        printf 'MISSING %s
' "${miss[@]}"
        echo "ERROR: nothing submitted (GHS-BUILT-S: PRODUCTS=ghs_built bash sbatch/external_download.sh, section 28 block 0)"; exit 1
    fi
    if ! bash sbatch/missed_cells.sh --check > logs/conus_missed1980_check.txt 2>&1; then
        grep -E "MISSING|ERROR" logs/conus_missed1980_check.txt || tail -5 logs/conus_missed1980_check.txt
        echo "ERROR: nothing submitted (see logs/conus_missed1980_check.txt)"; exit 1
    fi
    grep -E "CHECK OK|remoteness|NobuiltYear source" logs/conus_missed1980_check.txt || true
    jm=$(sub "" --ntasks=${MISSED_TASKS:-8} --time=${MISSED_TIME:-03:00:00} sbatch/missed_cells.sh)
    echo "missed_cells $jm" | tee logs/conus_missed1980_jobs.txt
elif [[ $mode == cap1980 ]]; then
    miss=()
    for f in $DATA_ROOT/processed/tract/tracts_1980.gpkg              results/validation/conus/missed_cells_1980/county_missed_1980.csv              results/validation/conus/Dasy_CONUS_RF_v3_all_nby/tract_errors_1980.csv              results/dasymetric/conus/Dasy_CONUS_RF_v3_all_nby/Y1980/county_features.csv              results/dasymetric/conus/Dasy_CONUS_RF_v3_all_nby_plc/Y1980/county_features.csv              configs/conus_split.csv results/hisdac_uncertainty/excluded_counties_t070.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    if (( ${#miss[@]} )); then
        printf 'MISSING %s
' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1
    fi
    if ! bash sbatch/cap_allocation.sh --check > logs/conus_cap1980_check.txt 2>&1; then
        grep -E "MISSING|ERROR" logs/conus_cap1980_check.txt || tail -5 logs/conus_cap1980_check.txt
        echo "ERROR: nothing submitted (see logs/conus_cap1980_check.txt)"; exit 1
    fi
    grep -E "CHECK OK|remoteness|NobuiltYear source" logs/conus_cap1980_check.txt || true
    jc=$(sub "" --ntasks=${CAP_TASKS:-12} --time=${CAP_TIME:-03:00:00} sbatch/cap_allocation.sh)
    echo "cap_allocation $jc" | tee logs/conus_cap1980_jobs.txt
elif [[ $mode == captransfer ]]; then
    miss=()
    E=$DATA_ROOT/raw/external
    V=$HISDAC_SCRATCH/dasymetric/conus
    CUT=$HISDAC_SCRATCH/cutouts/conus
    for f in $E/ghs_built/GHS_BUILT_S_E2015_GLOBE_R2023A_54009_100_V1_0.tif \
             $E/ghs_built_nres/GHS_BUILT_S_NRES_E2015_GLOBE_R2023A_54009_100_V1_0.tif \
             $E/ghs_pop/GHS_POP_E2010_GLOBE_R2023A_54009_100_V1_0.tif \
             results/hisdac_uncertainty/county_record_uncertainty.csv \
             results/validation/conus/missed_cells_1980/county_missed_1980.csv \
             configs/conus_split.csv results/hisdac_uncertainty/excluded_counties_t070.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    for y in 1940 1960 1980 2010; do
        for f in $V/Dasy_CONUS_RF_v3_all_nby/predictions/pop_$y.tif $CUT/layers/BUI/${y}_BUI.tif \
                 $CUT/zones/zones_$y.tif $DATA_ROOT/processed/tract/tracts_$y.gpkg \
                 results/validation/conus/Dasy_CONUS_RF_v3_all_nby/tract_errors_$y.csv \
                 results/dasymetric/conus/Dasy_CONUS_RF_v3_all_nby/Y$y/county_features.csv; do
            [[ -f $f ]] || miss+=("$f")
        done
    done
    for y in 1940 1980 2010; do
        for f in $V/Dasy_CONUS_RF_v3_all_nby_pq5/predictions/pop_$y.tif $CUT/layers/PLURAL/${y}_PLURAL.tif; do
            [[ -f $f ]] || miss+=("$f")
        done
    done
    if (( ${#miss[@]} )); then
        printf 'MISSING %s\n' "${miss[@]}"
        echo "ERROR: nothing submitted (GHS-BUILT-S 2015: PRODUCTS=ghs_built_2015 bash sbatch/external_download.sh, section 30 block 0)"; exit 1
    fi
    if ! bash sbatch/cap_transfer.sh --check > logs/conus_captransfer_check.txt 2>&1; then
        grep -E "MISSING|ERROR|WARNING.*NRES" logs/conus_captransfer_check.txt || tail -5 logs/conus_captransfer_check.txt
        echo "ERROR: nothing submitted (see logs/conus_captransfer_check.txt)"; exit 1
    fi
    grep -E "CHECK OK|FEATURES|NRES|NobuiltYear source" logs/conus_captransfer_check.txt || true
    jt=$(sub "" --ntasks=${TRANSFER_TASKS:-12} --time=${TRANSFER_TIME:-04:00:00} sbatch/cap_transfer.sh)
    echo "cap_transfer $jt" | tee logs/conus_captransfer_jobs.txt
elif [[ $mode == uncertainty ]]; then
    CUT=$HISDAC_SCRATCH/cutouts/conus
    miss=()
    C=$DATA_ROOT/raw/hisdac_extra/BUPR_contemp.tif
    if [[ -f $C ]]; then echo "BUPR_contemp found: ratio_A_contemp + ratio_A_nby + ratio_B"
    else echo "BUPR_contemp not found ($C): NobuiltYear only (ratio_A_nby + ratio_B; none if NobuiltYear is 0/1)"; fi
    for f in $HISDAC_DIR/FBUY/NobuiltYear.tif $HISDAC_DIR/BUPR/2015_BUPR.tif $HISDAC_DIR/BUPR/2020_BUPR.tif \
             $CUT/zones/zones_2010.tif $CUT/zones/zones_2010.csv \
             results/dasymetric/conus/Dasy_CONUS_RF_v3_all/Y2010/county_features.csv; do
        [[ -f $f ]] || miss+=("$f")
    done
    if (( ${#miss[@]} )); then
        printf 'MISSING %s\n' "${miss[@]}"; echo "ERROR: nothing submitted"; exit 1
    fi
    ju=$(sub "" --ntasks=${UNC_TASKS:-2} --time=${UNC_TIME:-02:00:00} sbatch/record_uncertainty.sh)
    echo "record_uncertainty $ju" | tee logs/conus_uncertainty_jobs.txt
else
    jc=$(sub "" sbatch/census_conus.sh --years 1920 1960 2010)
    jg=$(sub "$jc" --ntasks=4 --time=${CUTOUT_TIME:-00:30:00} --export=ALL,CONFIG=$S,CENSUS_DIR=$CEN sbatch/grid_cutout.sh)
    jw=$(sub "$jg" --ntasks=16 --time=${WATER_TIME:-01:00:00} --export=ALL,CONFIG=$S sbatch/water_frac.sh)
    jp=$(sub "$jg" --ntasks=8 --time=${PLACE_TIME:-00:30:00} --export=ALL,CONFIG=$S sbatch/place_dist.sh)
    f1=$(sub "$jw" --ntasks=6 --time=${FEATURES_TIME:-00:20:00} --export=ALL,CONFIG=$V1 sbatch/dasymetric_features.sh)
    f2=$(sub "$jw $jp" --ntasks=6 --time=${FEATURES_TIME:-00:20:00} --export=ALL,CONFIG=$V2 sbatch/dasymetric_features.sh)
    t1=$(sub "$f1" --ntasks=16 --time=${TRAIN_TIME:-00:45:00} --export=ALL,CONFIG=$V1 sbatch/dasymetric_train.sh)
    t2=$(sub "$f2 $t1" --ntasks=16 --time=${TRAIN_TIME:-00:45:00} --export=ALL,CONFIG=$V2 sbatch/dasymetric_train.sh)  # compares with v1
    p1=$(sub "$t1" --ntasks=32 --time=${PREDICT_TIME:-01:00:00} --export=ALL,CONFIG=$V1 sbatch/dasymetric_predict.sh)
    p2=$(sub "$t2 $p1" --ntasks=32 --time=${PREDICT_TIME:-01:00:00} --export=ALL,CONFIG=$V2 sbatch/dasymetric_predict.sh)
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years"
    v1=$(sub "$p1" --ntasks=8 --time=${VALIDATE_TIME:-01:30:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
         --version Dasy_CONUS_RF_v1 --years 1920 1960 2010 $VAL)
    v2=$(sub "$p2" --ntasks=8 --time=${VALIDATE_TIME:-01:30:00} --export=ALL,COVERAGE= sbatch/validate_tract.sh \
         --version Dasy_CONUS_RF_v2 --years 1960 2010 $VAL)
    echo "census_conus $jc | grid_cutout $jg | water_frac $jw | place_dist $jp | features v1 $f1 v2 $f2 | train v1 $t1 v2 $t2 | predict v1 $p1 v2 $p2 | validate v1 $v1 v2 $v2" \
        | tee logs/conus_pilot_jobs.txt
fi
