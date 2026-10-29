#!/bin/bash
# Uncertainty-filter sensitivity table (src/validation/filter_compare.py; docs/conus_plan.md "Uncertainty filter"):
# v5.4 (Dasy_CONUS_RF_v3_all) vs Dasy_CONUS_RF_v3_u090 / u070 / u050 on the same county sets (common TEST, imputed
# TEST) and tract parts, 1920 / 1960 / 2010 / 2020, + the fixed selection rule (logged; the choice is the user's).
# Reads only tracked result files; writes results/validation/conus/uncertainty_filter/. Light: 1 core, < 1 min.
#
# Submit from the repo root (logs/ must exist). Args go to the Python script:
#   mkdir -p logs && sbatch sbatch/filter_compare.sh
#SBATCH --job-name=filter_compare
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=00:15:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"
echo "== python: $(command -v python)  args: $*"

python -u src/validation/filter_compare.py --name conus --results-root results "$@"

echo "== done $(date -Is)"
