#!/bin/bash
# HISDAC record uncertainty per cell and county (src/grid/record_uncertainty.py; docs/conus_plan.md "HISDAC record
# uncertainty"): BUPR_contemp ($DATA_ROOT/raw/hisdac_extra/; optional: not in the Dataverse BUPR.tar, checked
# 2026-10-30) and NobuiltYear vs BUPR_2015 / 2020 ($HISDAC_DIR, read only); county ratios ratio_A_contemp (needs
# contemp), ratio_A_nby and ratio_B_<year> (need a NobuiltYear count) on the 2010 county zones of the CONUS cutout, BUI gap
# counties (results/dasymetric/conus/Dasy_CONUS_RF_v3_all/Y*/county_features.csv), threshold tables. Writes
# results/hisdac_uncertainty/ (small CSVs + one PNG). Diagnosis only: nothing is trained or excluded.
# Resources (estimate): NobuiltYear alone first, then up to 17 rasters of 18459 x 11615 cells in strips of 1024 rows,
# ~2-3 GB; IO bound. No contemp and a 0/1 NobuiltYear: only the first pass, then exit 0 (value distribution only).
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
[[ -f $CONTEMP ]] || echo "== BUPR_contemp not found: NobuiltYear only (ratio_A_nby, ratio_B)"
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
