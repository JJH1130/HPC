#!/bin/bash
# Strata (src/validation/strata.py run; docs/conus_plan.md "Strata (PLURAL area type x cell group)"; request
# docs/handoff/strata_request.md): v5.7's people per county x area type (PLURAL with breaks fixed once from GHS-SMOD
# 2010 cell shares) x cell group (built / undated / no_record) kept; inside each stratum the cells ordered by another
# model's cell people (1940 / 1980: pq5; 2010: pq5 + the four new v5.7 + NTL / NTLV (+ PLURAL) versions); per stratum
# the score chosen on TRAIN-county tracts (> 0.1 pp better than v57, else v57), reported on TEST-county tracts. No
# change to v5.7. `strata:` block of configs/external_grids.yaml (+ rural_boxes.smod).
# Inputs: v5.7 predictions 1940 / 1980 / 2010, the score versions' pop_{YEAR}.tif, cutout zones / BUI / PLURAL of the
# three years, NobuiltYear, tracts_{YEAR}.gpkg, GHS-SMOD 2010 ($DATA_ROOT/raw/external/ghs_smod), and in git v5.7's
# tract_errors_{YEAR}.csv, configs/conus_split.csv, excluded_counties_t070.csv, county_missed_1980.csv.
# Writes results/validation/conus/strata/ (5 tables + 1 PNG, tracked).
# Usually submitted by: bash sbatch/submit_conus.sh strata (after the four new versions). Alone (repo root, logs/):
#   sbatch sbatch/strata.sh
#   bash sbatch/strata.sh --check        # login node: inputs + the new configs (seconds; new maps may be missing)
# Resources: cap_transfer's year passes (job of section 30: one pass per year, ~10 min each with 12 cores) without
# product moves but with up to six score maps per cell (~40 bytes per mask cell, ~5 GB in 2010) and ~50 swaps of
# strata cells: 12 cores (45 GB), 3 h (estimate).
#SBATCH --job-name=strata
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=12
#SBATCH --time=03:00:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"
export MPLBACKEND=Agg OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
echo "== python: $(command -v python)  workers ${SLURM_CPUS_ON_NODE:-1}  args: $*"

python -u src/validation/strata.py run \
    --config configs/external_grids.yaml \
    --data-root "$DATA_ROOT/raw/external" \
    --dasym-root "$HISDAC_SCRATCH/dasymetric" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --census-dir "$DATA_ROOT/processed/census_conus" \
    --tract-dir "$DATA_ROOT/processed/tract" \
    --hisdac-dir "$HISDAC_DIR" \
    --workers "${SLURM_CPUS_ON_NODE:-1}" \
    "$@"

echo "== done $(date -Is)"
