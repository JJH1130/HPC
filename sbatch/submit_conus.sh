#!/bin/bash
# Submit the CONUS job chains (docs/conus_plan.md; steps and checks in docs/runbooks/Running_CONUS.md).
# Not a job itself: run it on a login node from the repo root.
#   bash sbatch/submit_conus.sh trial   # step 0: 1960 only, v1; times the prediction (--measure), writes no map
#   bash sbatch/submit_conus.sh pilot   # 1920, 1960, 2010: cutout + water + distances, v1 and v2, tract validation
# The stage scripts are the Massachusetts ones (sbatch/*.sh, #SBATCH --account=ucb852_asc1); the CONUS config and
# the resources below are passed on the sbatch command line (flags override the scripts' #SBATCH lines).
# Pilot resources are set from the trial (jobs 34814376-34814382, docs/conus_plan.md "Trial result"): wall times
# ~3-5x the measured or scaled run time; features 8 cores (trial peak 10 GB of 15). Override a wall
# time without editing this file, e.g. PREDICT_TIME=12:00:00 bash sbatch/submit_conus.sh pilot.
# Job ids go to logs/conus_<mode>_jobs.txt.
set -euo pipefail
mode=${1:-}
[[ $mode == trial || $mode == pilot ]] || { echo "usage: bash sbatch/submit_conus.sh trial|pilot"; exit 1; }
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
else
    jc=$(sub "" sbatch/census_conus.sh --years 1920 1960 2010)
    jg=$(sub "$jc" --ntasks=4 --time=${CUTOUT_TIME:-01:00:00} --export=ALL,CONFIG=$S,CENSUS_DIR=$CEN sbatch/grid_cutout.sh)
    jw=$(sub "$jg" --ntasks=16 --time=${WATER_TIME:-01:30:00} --export=ALL,CONFIG=$S sbatch/water_frac.sh)
    jp=$(sub "$jg" --ntasks=8 --time=${PLACE_TIME:-00:45:00} --export=ALL,CONFIG=$S sbatch/place_dist.sh)
    f1=$(sub "$jw" --ntasks=8 --time=${FEATURES_TIME:-01:00:00} --export=ALL,CONFIG=$V1 sbatch/dasymetric_features.sh)
    f2=$(sub "$jw $jp" --ntasks=8 --time=${FEATURES_TIME:-01:00:00} --export=ALL,CONFIG=$V2 sbatch/dasymetric_features.sh)
    t1=$(sub "$f1" --ntasks=16 --time=01:00:00 --export=ALL,CONFIG=$V1 sbatch/dasymetric_train.sh)
    t2=$(sub "$f2 $t1" --ntasks=16 --time=01:00:00 --export=ALL,CONFIG=$V2 sbatch/dasymetric_train.sh)  # compares with v1
    p1=$(sub "$t1" --ntasks=32 --time=${PREDICT_TIME:-01:30:00} --export=ALL,CONFIG=$V1 sbatch/dasymetric_predict.sh)
    p2=$(sub "$t2 $p1" --ntasks=32 --time=${PREDICT_TIME:-01:30:00} --export=ALL,CONFIG=$V2 sbatch/dasymetric_predict.sh)
    VAL="--name conus --state-prefix= --split configs/conus_split.csv --map-years"
    v1=$(sub "$p1" --ntasks=8 --time=02:00:00 --export=ALL,COVERAGE= sbatch/validate_tract.sh \
         --version Dasy_CONUS_RF_v1 --years 1920 1960 2010 $VAL)
    v2=$(sub "$p2" --ntasks=8 --time=02:00:00 --export=ALL,COVERAGE= sbatch/validate_tract.sh \
         --version Dasy_CONUS_RF_v2 --years 1960 2010 $VAL)
    echo "census_conus $jc | grid_cutout $jg | water_frac $jw | place_dist $jp | features v1 $f1 v2 $f2 | train v1 $t1 v2 $t2 | predict v1 $p1 v2 $p2 | validate v1 $v1 v2 $v2" \
        | tee logs/conus_pilot_jobs.txt
fi
