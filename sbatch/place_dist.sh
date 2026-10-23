#!/bin/bash
# PLURAL-1 distance layers in the study-area cutout (src/grid/place_dist.py; design docs/dasymetric_v4_1.md;
# settings: place_dist: block of configs/study_area.yaml; source docs/data_sources.md).
# Input: PLURAL CSV + yearly point shapefiles under /projects/jaju1407/data/raw/plural/plural_2023/, and the existing
# cutout. Output: $HISDAC_SCRATCH/cutouts/<name>/layers/PLACEDIST/<class>/{YEAR}_<class>.tif (1940-2020, 5 classes),
# qa/place_dist_qa.csv and qa/place_dist_fills.csv (both copied to results/cutout/<name>/, also on failure).
#
# Submit from the repo root (logs/ must exist):
#   mkdir -p logs && sbatch sbatch/place_dist.sh
#SBATCH --job-name=place_dist
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --time=00:45:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

CONFIG=${CONFIG:-configs/study_area.yaml}   # CONUS: sbatch --export=ALL,CONFIG=configs/conus_study_area.yaml ...
NAME=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['name'])")
CUT_ROOT=$HISDAC_SCRATCH/cutouts
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME)  cutout: $CUT_ROOT/$NAME  workers: ${SLURM_CPUS_ON_NODE:-1}  extra args: $*"

copy_back() {
    mkdir -p "results/cutout/$NAME"
    for f in place_dist_qa.csv place_dist_fills.csv; do
        [[ -f $CUT_ROOT/$NAME/qa/$f ]] && cp "$CUT_ROOT/$NAME/qa/$f" "results/cutout/$NAME/"
    done
    return 0
}
trap copy_back EXIT

python -u src/grid/place_dist.py \
    --config "$CONFIG" \
    --cutout-root "$CUT_ROOT" \
    "$@"

echo "== $(find "$CUT_ROOT/$NAME/layers/PLACEDIST" -name "*.tif" | wc -l) PLACEDIST layers in $CUT_ROOT/$NAME/layers/PLACEDIST"
echo "== done $(date -Is)"
