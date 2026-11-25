#!/bin/bash
# Cap allocation 1980 (src/validation/cap_allocation.py; docs/conus_plan.md "Cap allocation 1980"; request
# docs/handoff/cap_allocation_1980_request.md): per 2010 county a cap per cell group (built / undated / no_record; caps
# v57 / ghs / model / model_noplural) x a score inside the group (v57 / pq5 / mixed / even / plural_inv), scored on the
# 1980 tracts. No new dasymetric training (two small random forests for the model caps). `cap_allocation:` +
# `missed_cells:` blocks of configs/external_grids.yaml.
# Inputs: the missed_cells inputs (GHS-POP / GHS-BUILT-S / GHS-SMOD 1980, v5.7 / pq5 / v5.4 predictions 1980, cutout
# zones / BUI / PLURAL, NobuiltYear, counties_2010.gpkg), tracts_1980.gpkg, and in git county_missed_1980.csv, v5.7's
# tract_errors_1980.csv, the v5.7 / plc county features 1980, configs/conus_split.csv, excluded_counties_t070.csv.
# Writes results/validation/conus/cap_allocation_1980/ (6 tables + 1 PNG, tracked).
# Usually submitted by: bash sbatch/submit_conus.sh cap1980. Alone (repo root, logs/ must exist):
#   sbatch sbatch/cap_allocation.sh
#   bash sbatch/cap_allocation.sh --check        # login node: inputs only (seconds)
# Resources: as missed_cells (job 36294511: 27 min, 16 GB of 30 with 8 cores) without GHS-BUILT, but every mask cell
# (~1.3 x 10^8, ~33 bytes) + the tract id grid (0.9 GB) + 20 allocations of float64 cell arrays: 12 cores (45 GB),
# 3 h (estimate).
#SBATCH --job-name=cap_allocation
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

python -u src/validation/cap_allocation.py run \
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
