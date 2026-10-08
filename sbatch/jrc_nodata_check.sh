#!/bin/bash
# Where are the JRC no-data pixels (occurrence > 100)? Diagnostic for the v3.1 water mask
# (src/grid/jrc_nodata_check.py; settings: water: block of configs/study_area.yaml).
# Input: JRC tiles + the existing cutout. Output: $HISDAC_SCRATCH/cutouts/<name>/qa/jrc_nodata_frac.tif,
# jrc_nodata_by_county.csv, jrc_nodata_map.png; the CSV and PNG are copied to results/cutout/<name>/
# (also on failure). The cutout layers (incl. water_frac) are not changed.
#
# Submit from the repo root (logs/ must exist):
#   mkdir -p logs && sbatch sbatch/jrc_nodata_check.sh
#SBATCH --job-name=jrc_nodata_check
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

CONFIG=configs/study_area.yaml
NAME=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['name'])")
CUT_ROOT=$HISDAC_SCRATCH/cutouts
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME)  cutout: $CUT_ROOT/$NAME  extra args: $*"

copy_back() {
    mkdir -p "results/cutout/$NAME"
    local Q=$CUT_ROOT/$NAME/qa
    [[ -f $Q/jrc_nodata_by_county.csv ]] && cp "$Q/jrc_nodata_by_county.csv" "results/cutout/$NAME/"
    [[ -f $Q/jrc_nodata_map.png ]] && cp "$Q/jrc_nodata_map.png" "results/cutout/$NAME/"
    return 0
}
trap copy_back EXIT

python -u src/grid/jrc_nodata_check.py \
    --config "$CONFIG" \
    --cutout-root "$CUT_ROOT" \
    --counties-gpkg "$DATA_ROOT/processed/census/counties_2020.gpkg" \
    "$@"

echo "== done $(date -Is)"
