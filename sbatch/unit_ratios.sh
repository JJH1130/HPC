#!/bin/bash
# Unit ratios, part B (src/validation/unit_ratios.py job; docs/conus_plan.md "Unit ratios"; request
# docs/handoff/unit_ratios_request.md): per county the people v5.7 puts on built cells per BUPR record / per built cell
# and on undated cells per NobuiltYear record / per cell, 1940 / 1960 / 1980 / 2010, next to the county tract MdAPE
# (Spearman of |log(ratio / class median)| vs MdAPE by class). Descriptive only. Part A (`unit_ratios.py local`) runs
# on the laptop from tracked files. `unit_ratios:` block of configs/external_grids.yaml.
# Inputs: v5.7 predictions, cutout zones / BUI / BUPR of the four years, NobuiltYear; in git v5.7's
# tract_errors_{YEAR}.csv, county_record_uncertainty.csv, county_missed_1980.csv, excluded_counties_t070.csv.
# Writes results/validation/conus/unit_ratios/ (allocated_ratios.csv, ratio_vs_tract.csv + .png, tracked).
# Usually submitted by: bash sbatch/submit_conus.sh unitratios. Alone (repo root, logs/ must exist):
#   sbatch sbatch/unit_ratios.sh
#   bash sbatch/unit_ratios.sh --check        # login node: inputs only (seconds)
# Resources: four strip passes over the CONUS window without product moves (cap transfer read the same layers);
# county sums only, nothing kept per cell: 8 cores, 1 h (estimate).
#SBATCH --job-name=unit_ratios
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"
export MPLBACKEND=Agg OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
echo "== python: $(command -v python)  workers ${SLURM_CPUS_ON_NODE:-1}  args: $*"

python -u src/validation/unit_ratios.py job \
    --config configs/external_grids.yaml \
    --dasym-root "$HISDAC_SCRATCH/dasymetric" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --hisdac-dir "$HISDAC_DIR" \
    --workers "${SLURM_CPUS_ON_NODE:-1}" \
    "$@"

echo "== done $(date -Is)"
