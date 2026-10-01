#!/bin/bash
# Dasymetric stage 2: train the county model with grouped-CV hyperparameter search
# (src/dasymetric/train.py; design docs/dasymetric_v1.md; model + search space in configs/model.yaml).
# Input: features/county_features.csv (stage 1). Output: $HISDAC_SCRATCH/dasymetric/<name>/<version>/model/.
# metrics.json, best_params.json, feature_importance.csv, cv_results.csv are copied to
# results/dasymetric/<name>/<version>/.
#
# Submit from the repo root (logs/ must exist):
#   mkdir -p logs && sbatch sbatch/dasymetric_train.sh
#SBATCH --job-name=dasymetric_train
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# --account is OPTIONAL: no project allocation, so jobs run on the free default account (ucb-general).
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

CONFIG=configs/model.yaml
read -r NAME VERSION < <(python -u src/dasymetric/common.py --print-name-version "$CONFIG")
OUT_ROOT=$HISDAC_SCRATCH/dasymetric
RESULTS=results/dasymetric/$NAME/$VERSION
NJOBS=${SLURM_CPUS_ON_NODE:-1}
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME version=$VERSION)  out: $OUT_ROOT/$NAME/$VERSION  n_jobs: $NJOBS  extra args: $*"

python -u src/dasymetric/train.py \
    --config "$CONFIG" \
    --out-root "$OUT_ROOT" \
    --n-jobs "$NJOBS" \
    "$@"

mkdir -p "$RESULTS"
M=$OUT_ROOT/$NAME/$VERSION/model
cp "$M/metrics.json" "$M/best_params.json" "$M/feature_importance.csv" "$M/cv_results.csv" "$RESULTS/"
echo "== done $(date -Is)"
