#!/bin/bash
# Study-area cutout of the HISDAC-US V2 rasters + per-year county zone grids
# (src/grid/make_cutout.py; rules in docs/cutout.md; area set in configs/study_area.yaml).
# Output: $HISDAC_SCRATCH/cutouts/<name>/. The small CSV/JSON outputs are copied to
# results/cutout/<name>/ so they come back through git.
#
# Submit from the repo root (logs/ must exist). Extra args go to the Python script:
#   mkdir -p logs && sbatch sbatch/grid_cutout.sh                  # all config years
#   mkdir -p logs && sbatch sbatch/grid_cutout.sh --years 1810     # quick test
# Layers come only from the config (layers:). states: all (CONUS) reads ~1 GB per layer-year
# window: raise --ntasks to 4 and --time before switching.
#SBATCH --job-name=grid_cutout
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

CONFIG=configs/study_area.yaml
NAME=$(python -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['name'])")
OUT_ROOT=$HISDAC_SCRATCH/cutouts
echo "== python: $(command -v python)"
echo "== config: $CONFIG (name=$NAME)  hisdac: $HISDAC_DIR  out: $OUT_ROOT/$NAME  extra args: $*"

python -u src/grid/make_cutout.py \
    --config "$CONFIG" \
    --hisdac-dir "$HISDAC_DIR" \
    --census-dir "$DATA_ROOT/processed/census" \
    --out-root "$OUT_ROOT" \
    "$@"

mkdir -p "results/cutout/$NAME/zones"
cp "$OUT_ROOT/$NAME/cutout_qa.csv" "$OUT_ROOT/$NAME/window.json" "results/cutout/$NAME/"
cp "$OUT_ROOT/$NAME"/zones/*.csv "results/cutout/$NAME/zones/"
du -sh "$OUT_ROOT/$NAME"
echo "== done $(date -Is)"
