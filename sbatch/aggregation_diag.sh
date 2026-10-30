#!/bin/bash
# County feature aggregation diagnosis (src/validation/aggregation_diag.py; docs/conus_plan.md "County feature
# aggregation: diagnosis"; request docs/handoff/aggregation_diagnosis_request.md). No training, no prediction: reads
# the CONUS cutout, the version's county_features.csv and its predictions/pop_{YEAR}.tif on scratch, and the tracked
# tract_errors_{YEAR}.csv; writes results/aggregation/conus/ (small CSVs + one PNG, tracked in git).
# Resources as the county features job (strips of block_rows rows, dist_built on the whole window), plus every kept
# cell's values as float32 (~124 M cells x 10 columns, ~5 GB): 8 cores (30 GB).
#
# Submit from the repo root (logs/ must exist):
#   mkdir -p logs && sbatch --export=ALL,CONFIG=configs/conus_rf_v3_u070.yaml sbatch/aggregation_diag.sh --years 1960 2010
#   (or bash sbatch/submit_conus.sh aggdiag: pre-check + this job)
#SBATCH --job-name=aggregation_diag
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --time=01:30:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

CONFIG=${CONFIG:-configs/conus_rf_v3_u070.yaml}
read -r NAME VERSION < <(python -u src/dasymetric/common.py --print-name-version "$CONFIG")
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME version=$VERSION)  cutout: $HISDAC_SCRATCH/cutouts/$NAME  extra args: $*"

python -u src/validation/aggregation_diag.py \
    --config "$CONFIG" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --out-root "$HISDAC_SCRATCH/dasymetric" \
    --tracts-dir "results/validation/$NAME/$VERSION" \
    --out "results/aggregation/$NAME" \
    "$@"

echo "== done $(date -Is)"
