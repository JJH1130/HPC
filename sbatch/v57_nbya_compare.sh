#!/bin/bash
# v5.7 with nby_age instead of nby (docs/conus_plan.md "v5.7 with nby_age instead of nby"; request
# docs/handoff/v57_nbya_request.md): src/validation/v57_nbya_compare.py, one subcommand per job:
#   factors  after the features job, before train: the new nby_age factors = Dasy_CONUS_RF_v3_u070_nbya's (common
#            counties) and the new county features = v5.7's with nby -> nby_age; FACTORS OK or exit 1 (the chain
#            stops) -> results/validation/conus/nobuilt/v57_nbya_factor_{check,summary}.csv
#   compare  after validate: v5.4 / v5.6 / v5.7 / v5.7 + nby_age / v5.6 + nby_age on ALL TEST counties (kept / excluded
#            t070 labelled), tracts, people on BUI = 0 cells (and on NobuiltYear > 0 cells) from the predictions on
#            scratch, city gap blocks of the meeting maps, ranks, factor summary, the CV rule; v5.4 / v5.6 / v5.7 rows
#            must equal v54_nby_*.csv and v5.6 + nby_age rows nobuilt_*.csv, else stop. Summary in lines SUMMARY / RULE.
#            -> results/validation/conus/nobuilt/v57_nbya_*.csv
#
# Usually submitted by: bash sbatch/submit_conus.sh v57nbya. Alone (repo root, logs/ must exist):
#   mkdir -p logs && sbatch --time=00:15:00 --ntasks=1 sbatch/v57_nbya_compare.sh factors
#   mkdir -p logs && sbatch sbatch/v57_nbya_compare.sh compare
# Resources: v54_nby_compare (4 versions) took 4 min on 4 cores (job 35241004); 5 versions: 4 cores, 45 min wall.
#SBATCH --job-name=v57_nbya_compare
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
CMD=${1:-}
[[ $CMD == factors || $CMD == compare ]] || { echo "ERROR: first argument factors | compare (got '$CMD')"; exit 1; }
shift
echo "== python: $(command -v python)  subcommand: $CMD  extra args: $*"

if [[ $CMD == factors ]]; then
    python -u src/validation/v57_nbya_compare.py factors --out-dir results/validation/conus/nobuilt "$@"
else
    python -u src/validation/v57_nbya_compare.py compare \
        --dasym-root "$HISDAC_SCRATCH/dasymetric" \
        --cutout-root "$HISDAC_SCRATCH/cutouts" \
        --ext-config configs/external_grids.yaml \
        --data-root "$DATA_ROOT/raw/external" \
        --out-dir results/validation/conus/nobuilt \
        "$@"
fi

echo "== done $(date -Is)"
