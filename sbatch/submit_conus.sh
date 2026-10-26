#!/bin/bash
# Submit the CONUS job chains (docs/conus_plan.md; steps and checks in docs/runbooks/Running_CONUS.md).
# Not a job itself: run it on a login node from the repo root.
#   bash sbatch/submit_conus.sh trial   # step 0: 1960 only, v1; times the prediction (--measure), writes no map
#   bash sbatch/submit_conus.sh pilot   # 1920, 1960, 2010: cutout + water + distances, v1 and v2, tract validation
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
# Job ids go to logs/conus_<mode>_jobs.txt.
set -euo pipefail
mode=${1:-}
[[ $mode == trial || $mode == pilot || $mode == v3v4 || $mode == bui || $mode == models ]] || { echo "usage: bash sbatch/submit_conus.sh trial|pilot|v3v4|bui|models"; exit 1; }
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
