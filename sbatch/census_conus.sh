#!/bin/bash
# CONUS county input (src/census/conus_counties.py; docs/conus_plan.md): Stefan's CSV on 2010 county polygons,
# one counties_{YEAR}.gpkg per census year with status ok / filled_nhgis / no_value / zero_pop.
# Reads $DATA_ROOT/processed/census/counties_std_2010.gpkg (sbatch/std_county_check.sh) and, for the 2010 polygons
# without a CSV row, the NHGIS nominal counties_{YEAR}.gpkg in the same folder; writes
# $DATA_ROOT/processed/census_conus/counties_{YEAR}.gpkg and results/census_conus/counties_conus_summary.csv.
#
# Submit from the repo root (logs/ must exist). Extra args go to the Python script:
#   mkdir -p logs && sbatch sbatch/census_conus.sh                          # 1900-2010
#   mkdir -p logs && sbatch sbatch/census_conus.sh --years 1920 1960 2010   # trial years
#SBATCH --job-name=census_conus
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

echo "== python: $(command -v python)"
echo "== in: $DATA_ROOT/processed/census/counties_std_2010.gpkg  out: $DATA_ROOT/processed/census_conus  extra args: $*"

python -u src/census/conus_counties.py \
    --std-gpkg "$DATA_ROOT/processed/census/counties_std_2010.gpkg" \
    --census-dir "$DATA_ROOT/processed/census" \
    --out-dir "$DATA_ROOT/processed/census_conus" \
    --results-dir results/census_conus \
    "$@"

ls -la "$DATA_ROOT/processed/census_conus"
echo "== done $(date -Is)"
