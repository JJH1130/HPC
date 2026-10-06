#!/bin/bash
# Diagnostic: Stefan's county CSV (1900-2010 by 2010 FIPS) vs the nominal NHGIS counties.
# Reads $DATA_ROOT/raw/census_std/all_county_census_MSA_full.csv and
# $DATA_ROOT/processed/census/counties_{YEAR}.gpkg (read only); writes
# counties_std_2010.gpkg to $DATA_ROOT/processed/census and the CSVs to results/census_std/.
# Rules: src/census/std_county_check.py; steps: docs/runbooks/Checking_Std_Counties.md.
#
# Submit from the repo root (logs/ must exist):
#   mkdir -p logs && sbatch sbatch/std_county_check.sh
#SBATCH --job-name=std_county_check
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# --account is OPTIONAL: add "#SBATCH --account=<allocation>" only if you have
# a project allocation. This repo currently has none, so jobs run on the free
# default account (ucb-general).
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --time=00:20:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

STD_CSV=$DATA_ROOT/raw/census_std/all_county_census_MSA_full.csv
CENSUS=$DATA_ROOT/processed/census
echo "== python: $(command -v python)"
echo "== csv: $STD_CSV  census: $CENSUS"

python -u src/census/std_county_check.py \
    --std-csv "$STD_CSV" \
    --census-dir "$CENSUS" \
    --out-dir "$CENSUS" \
    --results-dir results/census_std

ls -la results/census_std "$CENSUS/counties_std_2010.gpkg"
echo "== done $(date -Is)"
