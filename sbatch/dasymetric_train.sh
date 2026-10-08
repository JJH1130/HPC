#!/bin/bash
# Dasymetric stage 2: train the county model with grouped-CV hyperparameter search
# (src/dasymetric/train.py; design docs/dasymetric_v1.md + v2.md + v3.md; model + search space in configs/model.yaml).
# Input: [<era>/]features/county_features.csv (stage 1). Output: $HISDAC_SCRATCH/dasymetric/<name>/<version>/[<era>/]model/
# (one model per era) and, with eras, <version>/cv_summary.csv.
# Everything in model/ except the model file (.json, .csv, .png: metrics, folds, correlation, SHAP,
# comparison with compare_with) is copied to results/dasymetric/<name>/<version>/[<era>/].
#
# Submit from the repo root (logs/ must exist):
#   mkdir -p logs && sbatch sbatch/dasymetric_train.sh
#SBATCH --job-name=dasymetric_train
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
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
read -r -a ERAS < <(python -u src/dasymetric/common.py --print-eras "$CONFIG")   # empty without eras
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

for ERA in "${ERAS[@]:-}"; do
    M=$OUT_ROOT/$NAME/$VERSION/$ERA/model
    mkdir -p "$RESULTS/$ERA"
    cp "$M"/*.json "$M"/*.csv "$M"/*.png "$RESULTS/$ERA/"
done
S=$OUT_ROOT/$NAME/$VERSION/cv_summary.csv
if [[ -f $S ]]; then cp "$S" "$RESULTS/"; fi
echo "== done $(date -Is)"
