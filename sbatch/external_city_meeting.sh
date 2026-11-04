#!/bin/bash
# Meeting city maps, 2010 (v5.6 | GHS-POP | WorldPop) and 1980 (v5.6 | GHS-POP) on our 250 m grid + 1 km block
# scatter plots for Boston, Denver, Chicago (+ gap blocks of every city and year vs HISDAC BUI / NobuiltYear)
# (src/validation/external_city_meeting.py; city_maps and city_meeting blocks of configs/external_grids.yaml; requests
# docs/handoff/city_maps_meeting_request.md + city_maps_meeting_fix_request.md). Rank agreement, not accuracy. The
# numbers must equal the previous meeting_summary.csv / gap table and the city maps summary (--compare-with), else the
# run stops before writing. Reads v5.6's pop_{2010,1980}.tif, the cutout's BUI, $HISDAC_DIR/FBUY/NobuiltYear.tif (read only;
# optional) and GHS-POP / WorldPop under $DATA_ROOT/raw/external; writes results/validation/conus/external/city_maps_meeting/.
# Usually submitted by: bash sbatch/submit_conus.sh citymeeting. Alone (repo root, logs/ must exist):
#   sbatch sbatch/external_city_meeting.sh
#   bash sbatch/external_city_meeting.sh --check        # login node: list the inputs only (seconds)
# v5.7 version of the figures (submit_conus.sh v57all; v5.6 recomputed and checked, side-by-side CSV):
#   sbatch --export=ALL,MEET_VERSION=Dasy_CONUS_RF_v3_all_nby,MEET_LABEL=v5.7,MEET_OUT=results/validation/conus/external/city_maps_meeting_v57 \
#       sbatch/external_city_meeting.sh
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

EXT=results/validation/conus/external
if [[ -n ${MEET_VERSION:-} ]]; then  # another version (v5.7): own out dir, v5.6 recomputed against city_maps_meeting/
    VER=(--version "$MEET_VERSION" --version-label "${MEET_LABEL:?MEET_LABEL needed with MEET_VERSION}"
         --out-dir "${MEET_OUT:?MEET_OUT needed with MEET_VERSION}" --base-dir $EXT/city_maps_meeting)
else
    VER=(--out-dir $EXT/city_maps_meeting --compare-with $EXT/city_maps_internal_with_fj/city_maps_summary.csv)
fi
python -u src/validation/external_city_meeting.py \
    --config configs/external_grids.yaml \
    --data-root "$DATA_ROOT/raw/external" \
    --dasym-root "$HISDAC_SCRATCH/dasymetric" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --hisdac-dir "$HISDAC_DIR" \
    --name conus \
    "${VER[@]}" \
    "$@"

echo "== done $(date -Is)"
