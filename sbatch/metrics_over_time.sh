#!/bin/bash
# County MdAPE (TEST / CV) and the fixed tract sets by year for one CONUS version (src/validation/metrics_over_time.py;
# docs/conus_plan.md "Metrics over time"). Reads only tracked result files (results/dasymetric/conus/<version>/Y*/,
# results/validation/conus/<version>/tract_errors_*.csv) and writes county_metrics_by_year.csv,
# fixed_tract_metrics.csv, fixed_tract_counties.csv and mdape_over_time.png next to them. Light: 1 core, < 1 min.
#
# Submit from the repo root (logs/ must exist). Args go to the Python script:
#   mkdir -p logs && sbatch sbatch/metrics_over_time.sh                       # Dasy_CONUS_RF_v3_all
#   mkdir -p logs && sbatch sbatch/metrics_over_time.sh --version Dasy_CONUS_RF_v3_bui
#SBATCH --job-name=metrics_over_time
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

python -u src/validation/metrics_over_time.py --name conus --results-root results "$@"

echo "== done $(date -Is)"
