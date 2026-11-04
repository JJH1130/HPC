#!/bin/bash
# Check that a --years run left the other years as they were (src/dasymetric/kept_years_check.py check; docs/conus_plan.md
# "v5.7 all years"): recomputes the hashes / rows of the snapshot JSON written by the submit script before the run.
# Prints MATCH / DIFFERS per item and `KEPT YEARS OK` or `KEPT YEARS DIFFERS`; exits 1 on a difference (nothing
# depends on this job). Light: 1 core, < 5 min (hashes of a few CSV / JSON files per year, CSV rows).
#
# Usually submitted by: bash sbatch/submit_conus.sh v57all. Alone (repo root, logs/ must exist):
#   sbatch sbatch/kept_years_check.sh --json logs/conus_v57all_kept_years.json
#SBATCH --job-name=kept_years_check
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

python -u src/dasymetric/kept_years_check.py check "$@"

echo "== done $(date -Is)"
