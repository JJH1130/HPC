#!/bin/bash
# Built-cell aggregation test, evaluation (docs/conus_plan.md "Built-cell aggregation test"):
# src/validation/builtcell_compare.py (v5.6 vs bc3 / bc5 / bc9 on the same tracts / TEST counties, people on empty cells
# and out-of-range built cells from the aggregation_diag runs, feature ranks, window k by the fixed CV rule), then
# src/validation/county_maps.py for 2010 with v5.6 and the chosen k (the 4 counties of the NTL tests: Chelan WA, Reno KS,
# Fremont CO, Macoupin IL; share of people on BUI = 0 cells).
# Output: results/validation/conus/builtcell/ (builtcell_comparison.csv / .png, builtcell_feature_ranks.csv,
# builtcell_choice.txt, county_maps/).
#
# Submit from the repo root (logs/ must exist), after the validate and aggregation_diag jobs of every version:
#   mkdir -p logs && sbatch sbatch/builtcell_compare.sh
#SBATCH --job-name=builtcell_compare
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --time=00:45:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

S=configs/conus_study_area.yaml
BASE=Dasy_CONUS_RF_v3_u070
OUT=results/validation/conus/builtcell
echo "== python: $(command -v python)"
echo "== base $BASE  out $OUT  extra args (builtcell_compare): $*"

python -u src/validation/builtcell_compare.py --base "$BASE" --out-dir "$OUT" "$@"

BEST=$(head -1 "$OUT/builtcell_choice.txt")
echo "== county maps 2010: $BASE ${BEST:-(no window chosen)}"
python -u src/validation/county_maps.py \
    --study-config "$S" \
    --counties G5300070 G2001550 G0800430 G1701170 \
    --versions "$BASE" $BEST \
    --year 2010 \
    --dasym-root "$HISDAC_SCRATCH/dasymetric" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --counties-gpkg "$DATA_ROOT/processed/census_conus/counties_2010.gpkg" \
    --tract-dir "$DATA_ROOT/processed/tract" \
    --validation-root results/validation \
    --out-dir "$OUT/county_maps"

echo "== done $(date -Is)"
