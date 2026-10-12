#!/bin/bash
# Tract validation of the Massachusetts dasymetric predictions (src/validation/tract_validate.py;
# design docs/validation_tract.md). Reads $HISDAC_SCRATCH/dasymetric/massachusetts/<version>/
# (predictions + qa/reallocation_qa.csv), the cutout zones, $DATA_ROOT/processed/tract/tracts_{YEAR}.gpkg
# and results/tract/coverage_by_county_MA.csv. Writes results/validation/massachusetts/<version>/.
#
# Submit from the repo root (logs/ must exist). Args go to the Python script; --version is required:
#   mkdir -p logs && sbatch sbatch/validate_tract.sh --version v3_1
#   mkdir -p logs && sbatch sbatch/validate_tract.sh --version v3_1 --years 1940 1970 2020   # quick test
#SBATCH --job-name=validate_tract
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

echo "== python: $(command -v python)"
echo "== args: $*"

python -u src/validation/tract_validate.py \
    --dasym-root "$HISDAC_SCRATCH/dasymetric" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --tract-dir "$DATA_ROOT/processed/tract" \
    --coverage-csv results/tract/coverage_by_county_MA.csv \
    --results-root results/validation \
    "$@"

du -sh results/validation/*/*
echo "== done $(date -Is)"
