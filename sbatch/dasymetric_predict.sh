#!/bin/bash
# Dasymetric stage 3: cell prediction + mass-preserving reallocation of county population
# (src/dasymetric/predict.py; design docs/dasymetric_v1.md + v2.md).
# Input: model/<model>.joblib (stage 2) + the cutout. Output: $HISDAC_SCRATCH/dasymetric/<name>/<version>/
# predictions/pop_{YEAR}.tif (scratch only), qa/reallocation_qa.csv, maps/*.png (state background from
# $DATA_ROOT/processed/census/counties_2020.gpkg; 1810 also side by side with compare_with).
# The QA CSV and the PNGs are copied to results/dasymetric/<name>/<version>/.
#
# Submit from the repo root (logs/ must exist). Extra args go to the Python script:
#   mkdir -p logs && sbatch sbatch/dasymetric_predict.sh                  # all config years
#   mkdir -p logs && sbatch sbatch/dasymetric_predict.sh --years 1900     # quick test
#SBATCH --job-name=dasymetric_predict
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

CONFIG=configs/model.yaml
read -r NAME VERSION < <(python -u src/dasymetric/common.py --print-name-version "$CONFIG")
OUT_ROOT=$HISDAC_SCRATCH/dasymetric
RESULTS=results/dasymetric/$NAME/$VERSION
NJOBS=${SLURM_CPUS_ON_NODE:-1}
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME version=$VERSION)  cutout: $HISDAC_SCRATCH/cutouts/$NAME  out: $OUT_ROOT/$NAME/$VERSION  n_jobs: $NJOBS  extra args: $*"

# Copy QA + maps back even when a check fails, so the failing rows come back through git.
copy_back() {
    mkdir -p "$RESULTS"
    local D=$OUT_ROOT/$NAME/$VERSION
    [[ -f $D/qa/reallocation_qa.csv ]] && cp "$D/qa/reallocation_qa.csv" "$RESULTS/"
    compgen -G "$D/maps/*.png" >/dev/null && cp "$D"/maps/*.png "$RESULTS/"
    du -sh "$D/predictions" 2>/dev/null || true
}
trap copy_back EXIT

python -u src/dasymetric/predict.py \
    --config "$CONFIG" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --out-root "$OUT_ROOT" \
    --counties-gpkg "$DATA_ROOT/processed/census/counties_2020.gpkg" \
    --n-jobs "$NJOBS" \
    "$@"

echo "== done $(date -Is)"
