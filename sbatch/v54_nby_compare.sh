#!/bin/bash
# v5.4 + NobuiltYear without the filter, evaluation (docs/conus_plan.md "v5.4 + NobuiltYear (no filter)"; request
# docs/handoff/v54_nby_request.md): src/validation/v54_nby_compare.py = v5.4, v5.4 + nby, v5.6, v5.6 + nby on the same
# years (1910 / 1940 / 1960 / 1980 / 2010), ALL TEST counties (kept / excluded t070 labelled beside), tracts, people on
# BUI = 0 cells (and of those on NobuiltYear > 0 cells) from the predictions on scratch, the city gap blocks of the
# meeting maps (Boston / Denver / Chicago, 1980 / 2010; v5.6 / v5.6 + nby rows must equal the NobuiltYear test's
# nobuilt_cells.csv / nobuilt_city_gaps.csv, else stop), rank of nby. No selection rule; summary tables in this job's
# log (lines SUMMARY).
# Output: results/validation/conus/nobuilt/v54_nby_{comparison,cells,city_gaps,feature_ranks}.csv (the nobuilt_* files
# of the NobuiltYear test are not touched).
#
# Usually submitted by: bash sbatch/submit_conus.sh v54nby. Alone (repo root, logs/ must exist), after the validate
# job of Dasy_CONUS_RF_v3_all_nby:
#   mkdir -p logs && sbatch sbatch/v54_nby_compare.sh
# Resources: nobuilt_compare (3 versions) took 5.6 min on 4 cores (job 35233314); 4 versions: 4 cores, 45 min wall.
#SBATCH --job-name=v54_nby_compare
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
echo "== python: $(command -v python)  extra args: $*"

python -u src/validation/v54_nby_compare.py \
    --dasym-root "$HISDAC_SCRATCH/dasymetric" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --ext-config configs/external_grids.yaml \
    --data-root "$DATA_ROOT/raw/external" \
    --out-dir results/validation/conus/nobuilt \
    "$@"

echo "== done $(date -Is)"
