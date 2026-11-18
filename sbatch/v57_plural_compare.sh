#!/bin/bash
# PLURAL on v5.7 (docs/conus_plan.md "PLURAL on v5.7"; request docs/handoff/v57_plural_density_request.md part A):
# src/validation/v57_plural_compare.py, one subcommand per job:
#   features  after the six features jobs, before train: county features of each v5.7 + plural version = v5.7's +
#             plural, plural = the v5.6 PLURAL test's (common counties), plural_breaks.csv = the v5.6 test's (classed);
#             FEATURES OK or exit 1 (the chain stops) -> results/validation/conus/plural_grid_v57/plural_v57_features_check.csv
#   compare   after validate: v5.7 + the six variants (+ v5.6 and v5.6 + the six as reference columns) on ALL TEST
#             counties (kept / excluded t070 labelled), tracts, people on BUI = 0 cells (and on NobuiltYear > 0 cells)
#             from the predictions on scratch, ranks of plural / nby, the CV rule; v5.6 / v5.7 rows must equal
#             v54_nby_*.csv and v5.6 (+ plural) rows plural_comparison.csv, else stop. Summary in lines SUMMARY / RULE.
#             -> results/validation/conus/plural_grid_v57/plural_v57_*.csv (no figure)
#
# Usually submitted by: bash sbatch/submit_conus.sh v57plural. Alone (repo root, logs/ must exist):
#   mkdir -p logs && sbatch --time=00:15:00 --ntasks=1 sbatch/v57_plural_compare.sh features
#   mkdir -p logs && sbatch sbatch/v57_plural_compare.sh compare
# Resources: v57_nbya_compare (5 versions x 5 years, cells + city) took ~4 min on 4 cores; here 13 versions x 3 years
# of whole-window cell reads, no city boxes: 4 cores, 1 h wall (estimate).
#SBATCH --job-name=v57_plural_compare
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
CMD=${1:-}
[[ $CMD == features || $CMD == compare ]] || { echo "ERROR: first argument features | compare (got '$CMD')"; exit 1; }
shift
OUT=results/validation/conus/plural_grid_v57
echo "== python: $(command -v python)  subcommand: $CMD  out: $OUT  extra args: $*"

if [[ $CMD == features ]]; then
    python -u src/validation/v57_plural_compare.py features --out-dir "$OUT" "$@"
else
    python -u src/validation/v57_plural_compare.py compare \
        --dasym-root "$HISDAC_SCRATCH/dasymetric" \
        --cutout-root "$HISDAC_SCRATCH/cutouts" \
        --out-dir "$OUT" \
        "$@"
fi

echo "== done $(date -Is)"
