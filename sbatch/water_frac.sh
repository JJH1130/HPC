#!/bin/bash
# Static water-fraction layer in the study-area cutout (src/grid/water_frac.py; design docs/dasymetric_v3_1.md;
# settings: water: block of configs/study_area.yaml; sources docs/data_sources.md).
# Input: JRC occurrence tiles + HydroLAKES under /projects/jaju1407/data/raw/water/, and the existing cutout.
# Output: $HISDAC_SCRATCH/cutouts/<name>/layers/water_frac/water_frac.tif and qa/water_qa.csv
# (the QA CSV is copied to results/cutout/<name>/, also on failure).
#
# Submit from the repo root (logs/ must exist):
#   mkdir -p logs && sbatch sbatch/water_frac.sh
#SBATCH --job-name=water_frac
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# --account is OPTIONAL: no project allocation, so jobs run on the free default account (ucb-general).
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
    [[ -f $CUT_ROOT/$NAME/qa/water_qa.csv ]] && cp "$CUT_ROOT/$NAME/qa/water_qa.csv" "results/cutout/$NAME/"
    return 0
}
trap copy_back EXIT

python -u src/grid/water_frac.py \
    --config "$CONFIG" \
    --cutout-root "$CUT_ROOT" \
    "$@"

echo "== done $(date -Is)"
