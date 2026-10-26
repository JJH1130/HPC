#!/bin/bash
# Model family comparison table (src/validation/compare_models.py; docs/conus_plan.md "Model family"): reads the
# small result files of each version under results/dasymetric/<name>/ and results/validation/<name>/ and writes
# results/validation/<name>/model_comparison.csv (+ a summary per year in the log). Light: 1 core, seconds.
#
# Submit from the repo root (logs/ must exist). Args go to the Python script; --versions is required:
#   mkdir -p logs && sbatch sbatch/compare_models.sh --versions Dasy_CONUS_RF_v3_bui Dasy_CONUS_RF_v3_n60
#SBATCH --job-name=compare_models
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=00:10:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"
echo "== python: $(command -v python)  args: $*"

python -u src/validation/compare_models.py --name conus --results-root results "$@"

echo "== done $(date -Is)"
