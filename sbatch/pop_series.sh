#!/bin/bash
# National population maps of one version (src/validation/pop_series.py): `export` sums the 250 m predictions to 1 km
# (log10 float16 npz + state outlines) into results/validation/conus/pop_series/ (tracked, a few MB per year), so the
# map style can be tuned on the laptop with `render`; `render` draws pop_<YEAR>.png.
# Usage (repo root, logs/ must exist):
#   sbatch sbatch/pop_series.sh export --years 1900
#   sbatch sbatch/pop_series.sh render --years 1900 1910 ...
# Resources: one 250 m CONUS raster (~1 GB float32, ~2 GB float64) at a time: 1 core, 16 GB, 30 min (estimate).
#SBATCH --job-name=pop_series
#SBATCH --partition=acpu
#SBATCH --qos=cpu-normal
# Ascent allocation ucb852_asc1 (450,000 SU), valid until 2027-10-05; see CLAUDE.md.
#SBATCH --account=ucb852_asc1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x.%j.out

set -euo pipefail
source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
job_banner
activate_env hisdac
cd "$REPO"
export MPLBACKEND=Agg
cmd="$1"; shift
if [ "$cmd" = export ]; then
    python -u src/validation/pop_series.py export --version "${POP_VERSION:-Dasy_CONUS_RF_v3_all_nby}" \
        --dasym-root "$HISDAC_SCRATCH/dasymetric" \
        --counties-gpkg "$DATA_ROOT/processed/census/counties_2020.gpkg" "$@"
else
    python -u src/validation/pop_series.py render "$@"
fi
ls -l results/validation/conus/pop_series/
