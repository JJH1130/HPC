#!/bin/bash
# QA of the night-light layers in the study-area cutout (src/grid/ntl_qa.py; design docs/dasymetric_v3.md).
# Input: $HISDAC_SCRATCH/cutouts/<name>/ with layers/NTL (grid_cutout.sh --layers NTL) and / or layers/NTLV.
# Output: $HISDAC_SCRATCH/cutouts/<name>/qa/<layer>_qa.csv + <layer>_glow_counties.csv (ntl_qa.csv, ... for NTL;
# with several layers also ntl_edges_compare.csv), copied to results/cutout/<name>/ (also on failure). CONFIG= picks
# the study-area config (default Massachusetts); --layer (default NTL) the layers, e.g. for CONUS:
#   sbatch --ntasks=8 --export=ALL,CONFIG=configs/conus_study_area.yaml sbatch/ntl_qa.sh
#   sbatch --ntasks=8 --export=ALL,CONFIG=configs/conus_study_area.yaml sbatch/ntl_qa.sh --layer NTL NTLV
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

CONFIG=${CONFIG:-configs/study_area.yaml}
NAME=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['name'])")
CUT_ROOT=$HISDAC_SCRATCH/cutouts
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME)  cutout: $CUT_ROOT/$NAME  extra args: $*"

copy_back() {
    mkdir -p "results/cutout/$NAME"
    for f in ntl_qa.csv ntl_glow_counties.csv ntlv_qa.csv ntlv_glow_counties.csv ntl_edges_compare.csv; do
        [[ -f $CUT_ROOT/$NAME/qa/$f ]] && cp "$CUT_ROOT/$NAME/qa/$f" "results/cutout/$NAME/"
    done
    return 0
}
trap copy_back EXIT

python -u src/grid/ntl_qa.py \
    --config "$CONFIG" \
    --cutout-root "$CUT_ROOT" \
    "$@"

echo "== done $(date -Is)"
