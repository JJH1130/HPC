#!/bin/bash
# PLURAL at county level only (docs/conus_plan.md "PLURAL at county level only"; request
# docs/handoff/plural_countymean_request.md): src/validation/plural_countymean.py, one subcommand per job:
#   variance  no model: between / within county variance of plural (bilinear, pq5 class), bui, nby, bldg_size over the
#             study cells of 1940 / 1980 / 2010 (county means checked against the county features first)
#             -> results/validation/conus/plural_grid_v57/countymean/pluralcm_variance_split.csv
#   compare   after the two cm predict / validate chains and the variance job: model check (model_from.json = the
#             snapshot logs/conus_pluralcm_models.json = the model files on scratch), v5.7 / pq5 / pq5cm / plc / plccm on
#             ALL TEST counties (cm = its PLURAL version), tracts, people on BUI = 0 cells, built contrast per county,
#             the interpretation rule; v5.7 / pq5 / plc rows must equal plural_v57_*.csv, else stop
#             -> results/validation/conus/plural_grid_v57/countymean/pluralcm_*.csv
#
# Usually submitted by: bash sbatch/submit_conus.sh pluralcm. Alone (repo root, logs/ must exist):
#   mkdir -p logs && sbatch --job-name=pluralcm_variance sbatch/plural_countymean.sh variance
#   mkdir -p logs && sbatch --job-name=pluralcm_compare sbatch/plural_countymean.sh compare
# Resources: v57_plural_compare (13 versions x 3 years of whole-window cell reads) fit in 1 h on 4 cores; here two strip
# passes over 5 layers x 3 years (variance), 5 versions x 3 years twice (cells + contrast): 4 cores, 1 h (estimate).
#SBATCH --job-name=plural_countymean
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
[[ $CMD == variance || $CMD == compare ]] || { echo "ERROR: first argument variance | compare (got '$CMD')"; exit 1; }
shift
OUT=results/validation/conus/plural_grid_v57/countymean
echo "== python: $(command -v python)  subcommand: $CMD  out: $OUT  extra args: $*"

if [[ $CMD == variance ]]; then
    python -u src/validation/plural_countymean.py variance \
        --cutout-root "$HISDAC_SCRATCH/cutouts" \
        --out-dir "$OUT" \
        "$@"
else
    python -u src/validation/plural_countymean.py compare \
        --dasym-root "$HISDAC_SCRATCH/dasymetric" \
        --cutout-root "$HISDAC_SCRATCH/cutouts" \
        --snapshot logs/conus_pluralcm_models.json \
        --out-dir "$OUT" \
        "$@"
fi

echo "== done $(date -Is)"
