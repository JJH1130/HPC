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
# Job ids go to logs/conus_<mode>_jobs.txt.
set -euo pipefail
mode=${1:-}
[[ $mode =~ ^(trial|pilot|v3v4|bui|models|all|ntl|ntlv|external|y2020|uncertainty|uncfilter|plural)$ ]] || { echo "usage: bash sbatch/submit_conus.sh trial|pilot|v3v4|bui|models|all|ntl|ntlv|external|y2020|uncertainty|uncfilter|plural"; exit 1; }
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
