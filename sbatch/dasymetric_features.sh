#!/bin/bash
# Dasymetric stage 1: county features + target from the study-area cutout
# (src/dasymetric/county_features.py; design docs/dasymetric_v1.md + v2.md + v3.md; settings configs/model.yaml).
# Input: $HISDAC_SCRATCH/cutouts/<name>/ (grid_cutout). Output: $HISDAC_SCRATCH/dasymetric/<name>/<version>/[<era>/]features/.
# county_features.csv is copied to results/dasymetric/<name>/<version>/[<era>/] so it comes back through git.
#
# Submit from the repo root (logs/ must exist):
#   mkdir -p logs && sbatch sbatch/dasymetric_features.sh
#SBATCH --job-name=dasymetric_features
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# --account is OPTIONAL: no project allocation, so jobs run on the free default account (ucb-general).
#SBATCH --nodes=1
#SBATCH --ntasks=2
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
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME version=$VERSION)  cutout: $HISDAC_SCRATCH/cutouts/$NAME  out: $OUT_ROOT/$NAME/$VERSION  extra args: $*"

python -u src/dasymetric/county_features.py \
    --config "$CONFIG" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --out-root "$OUT_ROOT" \
    "$@"

for ERA in "${ERAS[@]:-}"; do
    mkdir -p "$RESULTS/$ERA"
    cp "$OUT_ROOT/$NAME/$VERSION/$ERA/features/county_features.csv" "$RESULTS/$ERA/"
done
echo "== done $(date -Is)"
