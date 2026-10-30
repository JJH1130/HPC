#!/bin/bash
# QA of the PLURAL layers in the CONUS cutout (src/grid/plural_qa.py; docs/conus_plan.md "PLURAL grid test"): does the
# 0 fill outside the US leak into coast / border cells (edge vs interior, weight of outside pixels), and the 900 m
# source vs the 250 m cells at a few points. Looks only.
# Input: $HISDAC_SCRATCH/cutouts/<name>/ with layers/PLURAL and layers/PLURALC (grid_cutout.sh --layers PLURAL PLURALC)
# and the source rasters of the config. Output: <cutout>/qa/plural_qa.csv + plural_points.csv, copied to
# results/cutout/<name>/ (also on failure).
#
# Submit from the repo root (logs/ must exist):
#   mkdir -p logs && sbatch sbatch/plural_qa.sh
#SBATCH --job-name=plural_qa
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --time=00:45:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

CONFIG=${CONFIG:-configs/conus_study_area.yaml}
NAME=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['name'])")
CUT_ROOT=$HISDAC_SCRATCH/cutouts
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME)  cutout: $CUT_ROOT/$NAME  extra args: $*"

copy_back() {
    mkdir -p "results/cutout/$NAME"
    for f in plural_qa.csv plural_points.csv; do
        [[ -f $CUT_ROOT/$NAME/qa/$f ]] && cp "$CUT_ROOT/$NAME/qa/$f" "results/cutout/$NAME/"
    done
    return 0
}
trap copy_back EXIT

python -u src/grid/plural_qa.py \
    --config "$CONFIG" \
    --cutout-root "$CUT_ROOT" \
    "$@"

echo "== done $(date -Is)"
