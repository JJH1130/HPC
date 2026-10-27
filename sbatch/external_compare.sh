#!/bin/bash
# External gridded population products vs v5.4 on the same tracts (src/validation/external_compare.py;
# configs/external_grids.yaml; docs/conus_plan.md "External comparison"). First arg = the step, the rest go to Python.
#   bash sbatch/external_compare.sh inventory              # login node, not a job: headers only, seconds
#   sbatch sbatch/external_compare.sh extract --product fj_m3   # tract sums of one product (cores: --ntasks)
#   sbatch sbatch/external_compare.sh evaluate             # metrics + figure from the sums that are there
# Usually submitted by: bash sbatch/submit_conus.sh external (one extract job per downloaded product, then evaluate
# after all of them, whether they ended well or not).
# Inputs: $DATA_ROOT/raw/external (sbatch/external_download.sh), $DATA_ROOT/processed/tract/tracts_{YEAR}.gpkg,
# results/validation/conus/Dasy_CONUS_RF_v3_all/tract_errors_{YEAR}.csv. Tract sums (scratch):
# $HISDAC_SCRATCH/external/conus/sums/<product>_<year>.csv. Results (git): results/validation/conus/external/.
#SBATCH --job-name=external_compare
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"
export GDAL_CACHEMAX=256  # MB per worker process; GDAL's default (5 % of the node's RAM) x workers overruns the job
export MPLBACKEND=Agg

step=${1:?usage: external_compare.sh inventory|extract|evaluate [args]}
shift
OUT=results/validation/conus/external
echo "== python: $(command -v python)  step: $step  args: $*"
common=(--config configs/external_grids.yaml --data-root "$DATA_ROOT/raw/external" --name conus --results-root results)
case $step in
    inventory) python -u src/validation/external_compare.py inventory "${common[@]}" --out $OUT/external_inventory.csv "$@" ;;
    extract)   python -u src/validation/external_compare.py extract "${common[@]}" \
                   --tract-dir "$DATA_ROOT/processed/tract" --work-dir "$HISDAC_SCRATCH/external/conus" "$@" ;;
    evaluate)  python -u src/validation/external_compare.py evaluate "${common[@]}" \
                   --work-dir "$HISDAC_SCRATCH/external/conus" --out $OUT/external_comparison.csv \
                   --plot $OUT/external_mdape_by_year.png "$@" ;;
    *) echo "ERROR: unknown step $step"; exit 1 ;;
esac

echo "== done $(date -Is)"
