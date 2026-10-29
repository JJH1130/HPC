#!/bin/bash
# County exclusion sets of the uncertainty filter (src/grid/uncertainty_filter.py; docs/conus_plan.md "Uncertainty
# filter"): ratio_A_nby >= t (t = 0.9 / 0.7 / 0.5) or the fixed records / area rules, from
# results/hisdac_uncertainty/county_record_uncertainty.csv and the county sums of $HISDAC_DIR/BUI/2015_BUI.tif (read
# only) on the 2010 zones of the CONUS cutout. Writes excluded_counties_t{090,070,050}.csv + summaries to
# results/hisdac_uncertainty/. Resources (estimate): one CONUS raster + the zones in strips, < 1 GB, a few minutes.
#
# Submit from the repo root (logs/ must exist). Extra args go to the Python script:
#   mkdir -p logs && sbatch sbatch/uncertainty_filter.sh
#SBATCH --job-name=uncertainty_filter
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"
U=results/hisdac_uncertainty
echo "== python: $(command -v python)  hisdac: $HISDAC_DIR  extra args: $*"

python -u src/grid/uncertainty_filter.py \
    --uncertainty $U/county_record_uncertainty.csv \
    --nobuilt-values $U/nobuilt_values.csv \
    --bui "$HISDAC_DIR/BUI/2015_BUI.tif" \
    --cutout "$HISDAC_SCRATCH/cutouts/conus" \
    --out-dir $U \
    "$@"

ls -la $U/excluded_counties_t*.csv
echo "== done $(date -Is)"
