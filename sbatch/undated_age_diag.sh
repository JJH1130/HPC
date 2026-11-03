#!/bin/bash
# Undated HISDAC records vs building age, diagnosis only (src/grid/undated_age_diag.py; docs/conus_plan.md "v5.4 +
# NobuiltYear (no filter)"; request docs/handoff/v54_nby_request.md part 3): FBUY (first built-up year) of the built
# study cells with / without NobuiltYear records ($HISDAC_DIR FBUY/FBUY.tif, FBUY/NobuiltYear.tif, BUPR/2015_BUPR.tif,
# read only; 2010 county zones of the CONUS cutout), and per county Spearman(ratio_A_nby, BUPR_1940 / BUPR_2015) from
# results/hisdac_uncertainty/county_record_uncertainty.csv. No model; nothing goes into a feature or config.
# Output: results/hisdac_uncertainty/undated_age_diag.csv + this log (lines SUMMARY).
#
# Usually submitted by: bash sbatch/submit_conus.sh v54nby (no dependency). Alone (repo root, logs/ must exist):
#   mkdir -p logs && sbatch sbatch/undated_age_diag.sh
# Resources (estimate): 3 HISDAC rasters + the zones (18459 x 11615 cells) in strips of 1024 rows, as
# record_uncertainty.sh (17 rasters, 2 cores); IO bound: 2 cores, 1 h wall.
#SBATCH --job-name=undated_age_diag
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
echo "== python: $(command -v python)  hisdac: $HISDAC_DIR  extra args: $*"

python -u src/grid/undated_age_diag.py \
    --hisdac-dir "$HISDAC_DIR" \
    --cutout "$HISDAC_SCRATCH/cutouts/conus" \
    --county-table results/hisdac_uncertainty/county_record_uncertainty.csv \
    --out-dir results/hisdac_uncertainty \
    "$@"

echo "== done $(date -Is)"
