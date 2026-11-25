#!/bin/bash
# Cap transfer (src/validation/cap_allocation.py transfer; docs/conus_plan.md "Cap transfer (learn 2010, apply
# 1940-1980)"; request docs/handoff/cap_transfer_request.md): county group shares (built / undated / no_record) learned
# in 2010 from GHS-POP 2010 (target P) and GHS-BUILT-S 2015 residential surface (target B; total - NRES), applied to
# 1940 / 1960 / 1980 / 2010 with each year's v5.7 county features, x a score inside the groups (v57 / plural_inv / mixed
# / pq5_unbuilt; 1960 v57 only), scored on each year's tracts. No new dasymetric training (two small forests per
# target). `cap_transfer:` + `missed_cells:` blocks of configs/external_grids.yaml.
# Inputs: v5.7 predictions 1940 / 1960 / 1980 / 2010 (+ pq5 1940 / 1980 / 2010), cutout zones / BUI of the four years
# (+ PLURAL 1940 / 1980 / 2010), NobuiltYear, tracts_{YEAR}.gpkg, GHS-POP 2010 + GHS-BUILT-S total / NRES 2015
# ($DATA_ROOT/raw/external, PRODUCTS=ghs_built_2015 bash sbatch/external_download.sh), and in git v5.7's
# tract_errors_{YEAR}.csv / county features, county_missed_1980.csv (fixed county classes), county_record_uncertainty.csv,
# configs/conus_split.csv, excluded_counties_t070.csv.
# Writes results/validation/conus/cap_transfer/ (6 tables + 1 PNG, tracked).
# Usually submitted by: bash sbatch/submit_conus.sh captransfer. Alone (repo root, logs/ must exist):
#   sbatch sbatch/cap_transfer.sh
#   bash sbatch/cap_transfer.sh --check        # login node: inputs + common feature list only (seconds)
# Resources: cap1980 (job 36298987: 10 min, 23 GB with 12 cores, one product move) + three product moves in 2010, three
# more year passes without products and ~73 allocations instead of 20: 12 cores (45 GB), 4 h (estimate).
#SBATCH --job-name=cap_transfer
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=12
#SBATCH --time=04:00:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"
export MPLBACKEND=Agg OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
echo "== python: $(command -v python)  workers ${SLURM_CPUS_ON_NODE:-1}  args: $*"

python -u src/validation/cap_allocation.py transfer \
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
