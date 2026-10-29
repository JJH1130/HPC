#!/bin/bash
# HISDAC record uncertainty per cell and county (src/grid/record_uncertainty.py; docs/conus_plan.md "HISDAC record
# uncertainty"): BUPR_contemp ($DATA_ROOT/raw/hisdac_extra/, sbatch/hisdac_extra_download.sh) vs BUPR_2015 and
# NobuiltYear ($HISDAC_DIR, read only), county ratios A and B_year on the 2010 county zones of the CONUS cutout, BUI gap
# counties (results/dasymetric/conus/Dasy_CONUS_RF_v3_all/Y*/county_features.csv), threshold tables. Writes
# results/hisdac_uncertainty/ (small CSVs + one PNG). Diagnosis only: nothing is trained or excluded.
# Resources (estimate): 16 rasters of 18459 x 11615 cells read in strips of 1024 rows, ~2-3 GB; IO bound.
#
# Submit from the repo root (logs/ must exist). Extra args go to the Python script:
#   mkdir -p logs && sbatch sbatch/record_uncertainty.sh
#SBATCH --job-name=record_uncertainty
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

CONTEMP=${CONTEMP:-$DATA_ROOT/raw/hisdac_extra/BUPR_contemp.tif}
echo "== python: $(command -v python)"
echo "== contemp: $CONTEMP  hisdac: $HISDAC_DIR  cutout: $HISDAC_SCRATCH/cutouts/conus  extra args: $*"

python -u src/grid/record_uncertainty.py \
    --contemp "$CONTEMP" \
    --hisdac-dir "$HISDAC_DIR" \
    --cutout "$HISDAC_SCRATCH/cutouts/conus" \
    --features results/dasymetric/conus/Dasy_CONUS_RF_v3_all \
    --split configs/conus_split.csv \
    --out-dir results/hisdac_uncertainty \
    "$@"

ls -la results/hisdac_uncertainty
echo "== done $(date -Is)"
