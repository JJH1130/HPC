#!/bin/bash
# NHGIS county population + boundaries -> counties_{YEAR}.gpkg (ESRI:102039, CONUS,
# 1810-2020) + qa_report.csv + dropped_rows.csv in $DATA_ROOT/processed/census.
# The two CSVs are also copied to results/census/ so they come back through git.
# Rules and inputs: src/census/prepare_census.py, docs/runbooks/Preparing_Census.md.
#
# Submit from the repo root (logs/ must exist). Extra args go to the Python script:
#   mkdir -p logs && sbatch sbatch/census_prepare.sh                     # all 22 years
#   mkdir -p logs && sbatch sbatch/census_prepare.sh --years 1810 1900   # quick subset
#SBATCH --job-name=census_prepare
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# --account is OPTIONAL: add "#SBATCH --account=<allocation>" only if you have
# a project allocation. This repo currently has none, so jobs run on the free
# default account (ucb-general).
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

RAW=$DATA_ROOT/raw/nhgis
OUT=$DATA_ROOT/processed/census
echo "== python: $(command -v python)"
echo "== raw: $RAW  out: $OUT  extra args: $*"

python -u src/census/prepare_census.py \
    --pop-csv "$RAW/nhgis0001_ts_nominal_county.csv" \
    --shape-dir "$RAW/nhgis0001_shape" \
    --out-dir "$OUT" \
    --crosswalk configs/nhgis_crosswalk.csv \
    --manual-fills configs/nhgis_manual_fills.csv \
    --reconstructed configs/nhgis_reconstructed.csv \
    --official-totals configs/census_official_totals.csv \
    "$@"

mkdir -p results/census
cp "$OUT/qa_report.csv" "$OUT/dropped_rows.csv" results/census/
ls -la "$OUT"
echo "== done $(date -Is)"
