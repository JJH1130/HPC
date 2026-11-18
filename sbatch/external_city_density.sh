#!/bin/bash
# City boxes by density class (docs/conus_plan.md "City boxes by density class"; request
# docs/handoff/v57_plural_density_request.md part B): src/validation/external_city_density.py - the meeting boxes of
# Boston / Denver / Chicago (2010: GHS-POP, WorldPop; 1980: GHS-POP) split into rural / peri-urban / urban 1 km blocks
# by the GHS-POP block density of the year (breaks 100 / 1,000 per km2, `city_density:` block of
# configs/external_grids.yaml; the same breaks on our density as a check). Whole-box numbers must equal the meeting maps
# of the version (meeting_summary_<a>_<b>.csv, column = the label), else the run stops before writing.
# Reads the version's pop_{2010,1980}.tif and GHS-POP / WorldPop under $DATA_ROOT/raw/external; writes
# results/validation/conus/external/city_density_classes_<label>/ (density_class_summary.csv + PNGs). The meeting map
# folders are not touched.
# Usually submitted by: bash sbatch/submit_conus.sh citydensity [VERSION LABEL]. Alone (repo root, logs/ must exist):
#   sbatch sbatch/external_city_density.sh                                   # v5.7 (default)
#   sbatch --export=ALL,DENS_VERSION=<version>,DENS_LABEL=<label>,DENS_CHECK_WITH=<meeting_summary_a_b.csv> \
#       sbatch/external_city_density.sh
#   bash sbatch/external_city_density.sh --check                             # login node: inputs only (seconds)
# A version without meeting maps: DENS_CHECK_WITH=none (the whole box is then not checked; logged).
# Resources: the meeting maps job (6 maps + 9 product moves) took < 2 min, 0.4 GB (citymeeting / v57all); the same
# moves here + 6 small figures: 2 cores, 30 min wall.
#SBATCH --job-name=external_city_density
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
export MPLBACKEND=Agg
VER=${DENS_VERSION:-Dasy_CONUS_RF_v3_all_nby}
LAB=${DENS_LABEL:-v5.7}
CHK=${DENS_CHECK_WITH:-results/validation/conus/external/city_maps_meeting_v57/meeting_summary_v56_v57.csv}
if [[ $CHK == none ]]; then CHECK=(--no-check-with); else CHECK=(--check-with "$CHK"); fi
echo "== python: $(command -v python)  version $VER ($LAB)  whole-box check: $CHK  args: $*"

python -u src/validation/external_city_density.py \
    --config configs/external_grids.yaml \
    --data-root "$DATA_ROOT/raw/external" \
    --dasym-root "$HISDAC_SCRATCH/dasymetric" \
    --name conus \
    --version "$VER" \
    --version-label "$LAB" \
    "${CHECK[@]}" \
    "$@"

echo "== done $(date -Is)"
