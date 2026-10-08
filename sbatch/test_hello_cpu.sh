#!/bin/bash
# Smoke test: confirms sbatch submission, the acpu/cpu-normal partition+qos
# pair, and the logs/ pipeline work end to end before any real job runs.
# No conda env required.
#
# Submit from the repo root (logs/ must exist):
#   mkdir -p logs && sbatch sbatch/test_hello_cpu.sh
#SBATCH --job-name=test_hello_cpu
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=00:05:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
echo "== job $SLURM_JOB_ID ($SLURM_JOB_NAME) on $(hostname) at $(date -Is)"
echo "== cores=$SLURM_CPUS_ON_NODE"
echo "hello from Alpine, ${USER:-$(whoami)}"
python3 --version || true
echo "== done $(date -Is)"
