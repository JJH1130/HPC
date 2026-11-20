#!/bin/bash
# DEGURBA boxes (docs/conus_plan.md "DEGURBA boxes"; request docs/handoff/rural_boxes_request.md):
# src/validation/degurba_boxes.py, `rural_boxes:` block of configs/external_grids.yaml.
#   select  (once) 4 rural + 4 peri-urban boxes by Census region from the GHS-SMOD 2010 classes of the 2010 counties
#           ($DATA_ROOT/processed/census_conus/counties_2010.gpkg) -> written into configs/external_grids.yaml
#           (`boxes`) + results/validation/conus/external/degurba_boxes_v57/boxes_selected.csv (commit both)
#   run     the 8 boxes + Boston / Denver / Chicago, 1980 / 2010, v5.7 + v5.7 pq5: classes by GHS-SMOD (A) and by the
#           stage I rules on v5.7's density (B), cell types, figures -> results/validation/conus/external/degurba_boxes_v57/
#   overlap (after run) same boxes and cells: do v5.7 / pq5 put people on the same unbuilt (BUI = 0) cells as GHS-POP /
#           WorldPop? -> unbuilt_overlap.csv + .png in the same folder (group sums checked against cell_type_shares.csv)
# Inputs: GHS-SMOD (sbatch/external_download.sh, PRODUCTS=ghs_smod, login node), GHS-POP / WorldPop, v5.7 / pq5
# predictions and the cutout BUI on scratch, NobuiltYear from $HISDAC_DIR, the meeting table in git.
# Usually submitted by: bash sbatch/submit_conus.sh degurbaboxes. Alone (repo root, logs/ must exist):
#   sbatch sbatch/degurba_boxes.sh select
#   sbatch sbatch/degurba_boxes.sh run
#   sbatch sbatch/degurba_boxes.sh overlap
#   bash sbatch/degurba_boxes.sh run --check      # login node: inputs only (seconds)
# Resources: the city density job (6 box-years, product moves of 40 km boxes) took 1.5 min (job 35916297); run = 22
# box-years + a 80 km window per box-year for scheme B; select rasterizes ~3,100 counties on the 1 km SMOD grid and
# unions them (minutes, a few GB): 4 cores, 1 h (estimate).
#SBATCH --job-name=degurba_boxes
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
export MPLBACKEND=Agg
mode=${1:?usage: degurba_boxes.sh select|run|overlap [--check]}
shift
echo "== python: $(command -v python)  mode $mode  args: $*"

python -u src/validation/degurba_boxes.py "$mode" \
    --config configs/external_grids.yaml \
    --data-root "$DATA_ROOT/raw/external" \
    --dasym-root "$HISDAC_SCRATCH/dasymetric" \
    --cutout-root "$HISDAC_SCRATCH/cutouts" \
    --census-dir "$DATA_ROOT/processed/census_conus" \
    --hisdac-dir "$HISDAC_DIR" \
    --name conus \
    "$@"

echo "== done $(date -Is)"
