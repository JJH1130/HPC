#!/bin/bash
# Meeting city maps, 2010: v5.6 | GHS-POP | WorldPop on our 250 m grid + 1 km block scatter plots for Boston, Denver,
# Chicago (+ Chicago gap blocks vs HISDAC BUI / NobuiltYear) (src/validation/external_city_meeting.py; city_maps and
# city_meeting blocks of configs/external_grids.yaml; request docs/handoff/city_maps_meeting_request.md). Rank
# agreement, not accuracy. Reads v5.6's pop_2010.tif, the cutout's BUI, $HISDAC_DIR/FBUY/NobuiltYear.tif (read only;
# optional) and GHS-POP / WorldPop under $DATA_ROOT/raw/external; writes results/validation/conus/external/city_maps_meeting/.
# Usually submitted by: bash sbatch/submit_conus.sh citymeeting. Alone (repo root, logs/ must exist):
#   sbatch sbatch/external_city_meeting.sh
#   bash sbatch/external_city_meeting.sh --check        # login node: list the inputs only (seconds)
# Resources: the 2010 maps of external_city_maps.sh took < 1 min and 0.4 GB (job 35194159).
#SBATCH --job-name=external_city_meeting
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
export MPLBACKEND=Agg
echo "== python: $(command -v python)  args: $*"

python -u src/validation/external_city_meeting.py \
    --config configs/external_grids.yaml \
    --data-root "$DATA_ROOT/raw/external" \
    --dasym-root "$HISDAC_SCRATCH/dasymetric" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --hisdac-dir "$HISDAC_DIR" \
    --name conus \
    --out-dir results/validation/conus/external/city_maps_meeting \
    "$@"

echo "== done $(date -Is)"
