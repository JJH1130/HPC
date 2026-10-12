#!/bin/bash
# NHGIS tract population + boundaries (extract nhgis0002) -> tracts_{YEAR}.gpkg (ESRI:102039,
# CONUS, 1910-2020) in $DATA_ROOT/processed/tract, for validating the dasymetric outputs.
# Reads counties_{YEAR}.gpkg (read only). Small CSVs go to results/tract/.
# Rules: docs/tract_preprocessing.md; steps: docs/runbooks/Preparing_Tracts.md.
#
# Submit from the repo root (logs/ must exist). Extra args go to the Python script:
#   mkdir -p logs && sbatch sbatch/tract_prepare.sh                          # all 12 years
#   mkdir -p logs && sbatch sbatch/tract_prepare.sh --years 1910 1960 1970   # quick subset
#SBATCH --job-name=tract_prepare
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

RAW=$DATA_ROOT/raw/nhgis
OUT=$DATA_ROOT/processed/tract
echo "== python: $(command -v python)"
echo "== raw: $RAW  out: $OUT  extra args: $*"

python -u src/census/prepare_tracts.py \
    --csv-dir "$RAW/nhgis0002_csv" \
    --ts-csv "$RAW/nhgis0002_csv/nhgis0002_ts_nominal_tract.csv" \
    --shape-dir "$RAW/nhgis0002_shape" \
    --census-dir "$DATA_ROOT/processed/census" \
    --table-config configs/nhgis_tract_tables.csv \
    --out-dir "$OUT" \
    --results-dir results/tract \
    "$@"

ls -la "$OUT" results/tract
echo "== done $(date -Is)"
