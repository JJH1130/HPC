#!/bin/bash
# City maps: v5.6 next to GHS-POP / Fang & Jawitz M5 (+ WorldPop in 2010) on our 250 m grid, 40 x 40 km around
# Denver, Salt Lake City, Chicago, Boston, 1980 / 2010 (src/validation/external_city_maps.py; city_maps block of
# configs/external_grids.yaml; docs/conus_plan.md "External comparison with v5.6"). Agreement, not accuracy.
# Reads $HISDAC_SCRATCH/dasymetric/conus/Dasy_CONUS_RF_v3_u070/predictions/pop_{YEAR}.tif, the cutout's BUI and the
# products under $DATA_ROOT/raw/external; writes results/validation/conus/external/city_maps_internal_with_fj/
# (internal check, not for the meeting; renamed from city_maps/ 2026-11-03).
# Usually submitted by: bash sbatch/submit_conus.sh externalv56. Alone (repo root, logs/ must exist):
#   sbatch sbatch/external_city_maps.sh                 # all cities and years of the config
#   bash sbatch/external_city_maps.sh --check           # login node: list the inputs only (seconds)
#SBATCH --job-name=external_city_maps
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --time=00:45:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"
export MPLBACKEND=Agg
echo "== python: $(command -v python)  args: $*"

python -u src/validation/external_city_maps.py \
    --config configs/external_grids.yaml \
    --data-root "$DATA_ROOT/raw/external" \
    --dasym-root "$HISDAC_SCRATCH/dasymetric" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --name conus \
    --out-dir results/validation/conus/external/city_maps_internal_with_fj \
    "$@"

echo "== done $(date -Is)"
