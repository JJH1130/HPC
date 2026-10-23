#!/bin/bash
# Study-area cutout of the HISDAC-US V2 rasters + per-year county zone grids
# (src/grid/make_cutout.py; rules in docs/cutout.md; area set in configs/study_area.yaml).
# Output: $HISDAC_SCRATCH/cutouts/<name>/. The small CSV/JSON outputs are copied to
# results/cutout/<name>/ so they come back through git.
#
# Submit from the repo root (logs/ must exist). Extra args go to the Python script:
#   mkdir -p logs && sbatch sbatch/grid_cutout.sh                  # all config years
#   mkdir -p logs && sbatch sbatch/grid_cutout.sh --years 1810     # quick test
#   mkdir -p logs && sbatch sbatch/grid_cutout.sh --layers NTL     # add one layer to the existing cutout
# Layers come only from the config (layers:). CONUS (configs/conus_study_area.yaml, whole HISDAC window,
# ~6 GB peak per layer-year) is submitted with more cores/time and its own census input by
# sbatch/submit_conus.sh (CONFIG=..., CENSUS_DIR=$DATA_ROOT/processed/census_conus).
#SBATCH --job-name=grid_cutout
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"

CONFIG=${CONFIG:-configs/study_area.yaml}   # CONUS: sbatch --export=ALL,CONFIG=configs/conus_study_area.yaml ...
NAME=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['name'])")
OUT_ROOT=$HISDAC_SCRATCH/cutouts
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME)  hisdac: $HISDAC_DIR  out: $OUT_ROOT/$NAME  extra args: $*"

python -u src/grid/make_cutout.py \
    --config "$CONFIG" \
    --hisdac-dir "$HISDAC_DIR" \
    --census-dir "${CENSUS_DIR:-$DATA_ROOT/processed/census}" \
    --out-root "$OUT_ROOT" \
    "$@"

mkdir -p "results/cutout/$NAME/zones"
cp "$OUT_ROOT/$NAME/cutout_qa.csv" "$OUT_ROOT/$NAME/window.json" "results/cutout/$NAME/"
cp "$OUT_ROOT/$NAME"/zones/*.csv "results/cutout/$NAME/zones/"
du -sh "$OUT_ROOT/$NAME"
echo "== done $(date -Is)"
