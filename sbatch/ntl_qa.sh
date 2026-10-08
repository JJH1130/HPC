#!/bin/bash
# QA of the NTL layer in the study-area cutout (src/grid/ntl_qa.py; design docs/dasymetric_v3.md).
# Input: $HISDAC_SCRATCH/cutouts/<name>/ with layers/NTL (grid_cutout.sh --layers NTL).
# Output: $HISDAC_SCRATCH/cutouts/<name>/qa/ntl_qa.csv, copied to results/cutout/<name>/ (also on failure).
#
# Submit from the repo root (logs/ must exist):
#   mkdir -p logs && sbatch sbatch/ntl_qa.sh
#SBATCH --job-name=ntl_qa
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --time=00:20:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

CONFIG=configs/study_area.yaml
NAME=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['name'])")
CUT_ROOT=$HISDAC_SCRATCH/cutouts
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME)  cutout: $CUT_ROOT/$NAME  extra args: $*"

copy_back() {
    mkdir -p "results/cutout/$NAME"
    [[ -f $CUT_ROOT/$NAME/qa/ntl_qa.csv ]] && cp "$CUT_ROOT/$NAME/qa/ntl_qa.csv" "results/cutout/$NAME/"
    return 0
}
trap copy_back EXIT

python -u src/grid/ntl_qa.py \
    --config "$CONFIG" \
    --cutout-root "$CUT_ROOT" \
    "$@"

echo "== done $(date -Is)"
