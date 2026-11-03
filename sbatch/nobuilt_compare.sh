#!/bin/bash
# NobuiltYear feature test, evaluation (docs/conus_plan.md "NobuiltYear feature test"; request
# docs/handoff/nobuiltyear_feature_request.md): src/validation/nobuilt_compare.py = v5.6 vs v5.6 + nby / + nby_age on the
# same tracts and TEST counties (1910 / 1940 / 1960 / 1980 / 2010), people on BUI = 0 cells (and of those on NobuiltYear
# > 0 cells) from the predictions on scratch, the city gap blocks of the meeting maps re-measured per version (Boston /
# Denver / Chicago, 1980 / 2010, GHS-POP; v5.6's must equal city_maps_meeting/gap_blocks.csv), feature ranks. No
# selection rule; the summary tables are in this job's log (lines SUMMARY).
# Output: results/validation/conus/nobuilt/ (nobuilt_comparison.csv, nobuilt_cells.csv, nobuilt_city_gaps.csv,
# nobuilt_feature_ranks.csv).
#
# Usually submitted by: bash sbatch/submit_conus.sh nobuilt. Alone (repo root, logs/ must exist), after the validate jobs
# of both variants:
#   mkdir -p logs && sbatch sbatch/nobuilt_compare.sh
# Resources: 3 versions x 5 years of three whole-window rasters read in strips (~1-2 min each, estimate) + 6 city boxes
# x 3 versions (the meeting maps took < 1 min): 4 cores, 1 h wall.
#SBATCH --job-name=nobuilt_compare
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"
echo "== python: $(command -v python)  extra args: $*"

python -u src/validation/nobuilt_compare.py \
    --dasym-root "$HISDAC_SCRATCH/dasymetric" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --ext-config configs/external_grids.yaml \
    --data-root "$DATA_ROOT/raw/external" \
    --out-dir results/validation/conus/nobuilt \
    "$@"

echo "== done $(date -Is)"
