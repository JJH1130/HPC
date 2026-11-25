#!/bin/bash
# 1980 missed cells (src/validation/missed_cells.py; docs/conus_plan.md "1980 missed cells"; request
# docs/handoff/missed_cells_1980_request.md): GHS-POP / GHS-BUILT-S 1980 on the cells HISDAC calls unbuilt (BUI = 0),
# per 2010 county and DEGURBA class, what v5.7 / v5.7 pq5 / v5.4 put there, and whether PLURAL / remoteness ranks
# those cells (capture curves). No model change. `missed_cells:` block of configs/external_grids.yaml.
# Inputs: GHS-POP 1980 + GHS-BUILT-S 1980 (sbatch/external_download.sh, PRODUCTS=ghs_built, login node) + GHS-SMOD 1980
# in $DATA_ROOT/raw/external; the v5.7 / pq5 / v5.4 predictions 1980, the cutout zones / BUI / PLURAL on scratch;
# NobuiltYear from $HISDAC_DIR; counties_2010.gpkg; the DEGURBA boxes' cell_type_shares.csv in git (box check).
# Writes results/validation/conus/missed_cells_1980/ (3 CSV + 2 PNG, tracked).
# Usually submitted by: bash sbatch/submit_conus.sh missed1980. Alone (repo root, logs/ must exist):
#   sbatch sbatch/missed_cells.sh
#   bash sbatch/missed_cells.sh --check          # login node: inputs only (seconds)
# Resources: the whole CONUS window in strips of block_rows rows, one worker per core (each strip moves GHS-POP and
# GHS-BUILT-S, 100 m -> 250 m, in column tiles); the unbuilt cells (~10^8) kept as ~30 bytes each (~4 GB) + sorts for the
# capture curves; between degurba_boxes (4 cores) and aggregation_diag (8 cores, 1:30): 8 cores (30 GB), 3 h (estimate).
#SBATCH --job-name=missed_cells
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --time=03:00:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"
export MPLBACKEND=Agg OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
echo "== python: $(command -v python)  workers ${SLURM_CPUS_ON_NODE:-1}  args: $*"

python -u src/validation/missed_cells.py run \
    --config configs/external_grids.yaml \
    --data-root "$DATA_ROOT/raw/external" \
    --dasym-root "$HISDAC_SCRATCH/dasymetric" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --census-dir "$DATA_ROOT/processed/census_conus" \
    --hisdac-dir "$HISDAC_DIR" \
    --workers "${SLURM_CPUS_ON_NODE:-1}" \
    "$@"

echo "== done $(date -Is)"
