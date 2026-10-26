#!/bin/bash
# Zoomed county maps of several CONUS dasymetric versions side by side (src/validation/county_maps.py;
# docs/conus_plan.md "v3 and v4"). Reads the cutout, $HISDAC_SCRATCH/dasymetric/<name>/<version>/predictions/, the tract
# errors in results/validation/<name>/<version>/ and the tracts; writes results/validation/<name>/county_maps/.
#
# Submit from the repo root (logs/ must exist). Args go to the Python script; --counties and --versions are required:
#   mkdir -p logs && sbatch sbatch/county_maps.sh --counties G5300070 G2001550 \
#       --versions Dasy_CONUS_RF_v1 Dasy_CONUS_RF_v2 Dasy_CONUS_RF_v4
#SBATCH --job-name=county_maps
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
NAME=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['name'])")
CENSUS_DIR=${CENSUS_DIR:-$DATA_ROOT/processed/census_conus}
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME)  census: $CENSUS_DIR  args: $*"

python -u src/validation/county_maps.py \
    --study-config "$CONFIG" \
    --dasym-root "$HISDAC_SCRATCH/dasymetric" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --counties-gpkg "$CENSUS_DIR/counties_2010.gpkg" \
    --tract-dir "$DATA_ROOT/processed/tract" \
    --validation-root results/validation \
    --out-dir "results/validation/$NAME/county_maps" \
    "$@"

echo "== done $(date -Is)"
