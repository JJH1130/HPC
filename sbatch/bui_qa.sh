#!/bin/bash
# BUI outlier check of a cutout: quantiles, cells above caps, the largest cells with their county (src/grid/bui_qa.py;
# CONUS request 2026-10-27, docs/conus_plan.md "BUI outliers"). Looks only; nothing in the cutout changes.
# Input: $HISDAC_SCRATCH/cutouts/<name>/ (layers BUI, BUPL, BUPR + zones). README / metadata files under $HISDAC_DIR
# are printed into the log (BUI unit). Output: results/cutout/<name>/bui_quantiles.csv, bui_top.csv.
#
# Submit from the repo root (logs/ must exist). Extra args go to the Python script:
#   mkdir -p logs && sbatch --export=ALL,CONFIG=configs/conus_study_area.yaml sbatch/bui_qa.sh
#SBATCH --job-name=bui_qa
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

CONFIG=${CONFIG:-configs/conus_study_area.yaml}
read -r NAME YEARS < <(python -c "
import sys; sys.path.insert(0, 'src/grid')
from make_cutout import load_config
c = load_config(__import__('pathlib').Path('$CONFIG')); print(c['name'], *c['years'])")
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME years=$YEARS)  cutout: $HISDAC_SCRATCH/cutouts/$NAME  extra args: $*"

python -u src/grid/bui_qa.py \
    --cutout "$HISDAC_SCRATCH/cutouts/$NAME" \
    --years $YEARS \
    --out-dir "results/cutout/$NAME" \
    --hisdac-dir "$HISDAC_DIR" \
    "$@"

echo "== done $(date -Is)"
