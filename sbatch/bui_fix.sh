#!/bin/bash
# Replace BUI record errors in a cutout: cells above bui_cap.max -> median of the 3 x 3 neighbours (src/grid/bui_fix.py;
# docs/conus_plan.md "BUI outliers", decided 2026-10-27). In place on $HISDAC_SCRATCH/cutouts/<name>/layers/BUI/;
# the first run keeps the original in layers/BUI_raw/. Needs a bui_cap block in the config (conus_study_area.yaml has
# one, the Massachusetts study_area.yaml has none). QA: results/cutout/<name>/bui_fix_summary.csv, bui_fixed_{YEAR}.csv.
#
# Submit from the repo root (logs/ must exist). Extra args go to the Python script:
#   mkdir -p logs && sbatch --export=ALL,CONFIG=configs/conus_study_area.yaml sbatch/bui_fix.sh
# Count only (nothing written in any cutout), e.g. Massachusetts from the raw HISDAC files over its window:
#   sbatch --export=ALL,CONFIG=configs/study_area.yaml sbatch/bui_fix.sh --check \
#       --hisdac-dir "$HISDAC_DIR" --window-json results/cutout/massachusetts/window.json
#SBATCH --job-name=bui_fix
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

CONFIG=${CONFIG:-configs/conus_study_area.yaml}
NAME=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['name'])")
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME)  cutout: $HISDAC_SCRATCH/cutouts/$NAME  extra args: $*"

python -u src/grid/bui_fix.py \
    --config "$CONFIG" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --qa-dir "results/cutout/$NAME" \
    "$@"

echo "== done $(date -Is)"
