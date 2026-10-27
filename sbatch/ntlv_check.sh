#!/bin/bash
# Check the downloaded VIIRS-like night lights (src/grid/ntlv_check.py; docs/conus_plan.md "VIIRS-like NTL test"):
# CRS, cell size, value range, nodata, sea mask, coverage of the CONUS window, for the NTLV years of the config.
# Input: the NTLV paths of configs/conus_study_area.yaml (sbatch/ntlv_download.sh), the cutout's window.json.
# Output: results/cutout/<name>/ntlv_check.csv. Looks only.
#
# Submit from the repo root (logs/ must exist); --wait returns when the job ends:
#   mkdir -p logs && sbatch --wait sbatch/ntlv_check.sh
#SBATCH --job-name=ntlv_check
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

CONFIG=${CONFIG:-configs/conus_study_area.yaml}
NAME=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['name'])")
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME)  cutout: $HISDAC_SCRATCH/cutouts/$NAME  extra args: $*"

python -u src/grid/ntlv_check.py \
    --config "$CONFIG" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --out "results/cutout/$NAME/ntlv_check.csv" \
    "$@"

echo "== done $(date -Is)"
