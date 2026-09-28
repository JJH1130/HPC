#!/bin/bash
# sbatch/cluster_env.sh — the ONE place this repo's Alpine paths live.
# Sourced by every sbatch script (and usable interactively):
#     source "${SLURM_SUBMIT_DIR:-.}/sbatch/cluster_env.sh"
#     activate_env <env-name>
# Python code never hardcodes these; it reads configs/ and CLI flags.
#
# CURC_USER defaults to you. A collaborator reusing another member's repo/envs
# can `export CURC_USER=<owner>` before sbatch (with --export=ALL) instead of
# editing this file. ${USER:-$(whoami)} because $USER can be empty in srun shells.

: "${CURC_USER:=${USER:-$(whoami)}}"
export CURC_USER

export PROJ_ROOT=/projects/$CURC_USER
export REPO=$PROJ_ROOT/HPC
export CONDA_ROOT=$PROJ_ROOT/software/miniforge3
export ENVS=$PROJ_ROOT/software/envs

# Working space: fast, big, NOT backed up, purged 90 days after creation.
export SCRATCH=/scratch/alpine/${USER:-$(whoami)}/HPC
# Finished deliverables only (snapshotted — never write temp files here).
# TODO: fill in once the PetaLibrary lab/allocation name is known, e.g.
#   export PL_ROOT=/pl/active/<LabName>
export PL_ROOT=

# Keep every cache off the 2 GB home quota.
export TMPDIR=$SCRATCH/tmp
export HF_HOME=$SCRATCH/cache/hf
export TORCH_HOME=$SCRATCH/cache/torch
export XDG_CACHE_HOME=$SCRATCH/cache/xdg
export PIP_CACHE_DIR=$SCRATCH/cache/pip
mkdir -p "$TMPDIR" "$HF_HOME" "$TORCH_HOME" "$XDG_CACHE_HOME" "$PIP_CACHE_DIR"

# Threads: one per worker by default; a single multithreaded process should
# export OMP_NUM_THREADS=$SLURM_CPUS_ON_NODE before sourcing this.
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1}
export MKL_NUM_THREADS=$OMP_NUM_THREADS
export OPENBLAS_NUM_THREADS=$OMP_NUM_THREADS
export NUMEXPR_NUM_THREADS=$OMP_NUM_THREADS

activate_env() {
    # conda's hook and packages' activate.d scripts can read unset variables,
    # which kills a `set -u` job script; relax nounset just for activation.
    local had_u=0
    [[ $- == *u* ]] && had_u=1
    set +u
    eval "$("$CONDA_ROOT/bin/conda" shell.bash hook)"
    conda activate "$ENVS/$1"
    if (( had_u )); then set -u; fi
}

# ROCm (AMD MI100) jobs: MIOpen must write a kernel DB. Per-job dir avoids two
# concurrent jobs corrupting a shared one.
rocm_caches() {
    export MIOPEN_USER_DB_PATH=$SCRATCH/cache/miopen/${SLURM_JOB_ID:-interactive}
    export MIOPEN_CUSTOM_CACHE_DIR=$MIOPEN_USER_DB_PATH
    mkdir -p "$MIOPEN_USER_DB_PATH"
}

# Start banner so every pulled-back log says what ran.
job_banner() {
    echo "== job ${SLURM_JOB_ID:-local} (${SLURM_JOB_NAME:-}) on $(hostname) at $(date -Is)"
    echo "== cores=${SLURM_CPUS_ON_NODE:-$(nproc)} gpus=${CUDA_VISIBLE_DEVICES:-${ROCR_VISIBLE_DEVICES:-none}} restart=${SLURM_RESTART_COUNT:-0}"
    if git -C "$REPO" rev-parse --short HEAD >/dev/null 2>&1; then
        echo "== git $(git -C "$REPO" rev-parse --short HEAD)$(git -C "$REPO" diff --quiet || echo ' (DIRTY tree)')"
    fi
}
