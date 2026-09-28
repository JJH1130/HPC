# Creating the conda env ("analysis") on Alpine

Builds a private miniforge and the project's `analysis` env (numpy, pandas, matplotlib, JupyterLab)
from `environment.yml`, then checks it with a batch job. Prerequisite: `Cluster_Setup.md` done
(repo at `/projects/jaju1407/HPC`).

**Last run / verified:** 2026-09-28, job 33114601 on `c3cpu-e2-u1` — `ENV OK` in 17 s
(python 3.12.14, numpy 2.5.3, pandas 3.0.6, matplotlib 3.11.2, JupyterLab 4.6.4).

## Where things go (and why)

| | Path | Why |
|---|---|---|
| conda itself (miniforge) | `/projects/jaju1407/software/miniforge3` | `/home` is only 2 GB; `/projects` is 250 GB and backed up |
| the env | `/projects/jaju1407/software/envs/analysis` | not `/scratch`: purged after 90 days, which would break the env |
| package download cache | `/scratch/alpine/jaju1407/conda_pkgs` | disposable, so purging is fine; keeps GBs off home |
| settings | `~/.condarc` (a few lines) | conda-forge only, the paths above |

Rules: nothing gets installed into `base` (it only holds conda itself); every install uses
`-p <env path>`. All installs run inside `sinteractive`, never on the login node (CURC kills heavy
processes there and the env ends up half-built). No `conda init` — scripts activate with the `eval`
line instead, so `~/.bashrc` stays untouched.

## 0. Sync (login node)

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs
```

The commit shown should be the one Claude just pushed ("Add analysis conda env ...").

## 1. Start an interactive session (login node → compute node)

`acompile` is CURC's partition for building software. The prompt changes to a compute-node name
when the session starts (may take a minute or two).

```bash
sinteractive --partition=acompile --qos=compile --ntasks=4 --time=01:00:00
```

## 2. Keep caches off home + write ~/.condarc (sinteractive)

`$USER` can be empty inside `sinteractive`, so it's set first and the `.condarc` uses the literal name.

```bash
export USER=jaju1407
export CONDA_PKGS_DIRS=/scratch/alpine/jaju1407/conda_pkgs
export PIP_CACHE_DIR=/scratch/alpine/jaju1407/pip_cache
export TMPDIR=/scratch/alpine/jaju1407/tmp
mkdir -p "$CONDA_PKGS_DIRS" "$PIP_CACHE_DIR" "$TMPDIR" /projects/jaju1407/software/envs
cat > ~/.condarc <<'EOF'
channels:
  - conda-forge
channel_priority: strict
pkgs_dirs:
  - /scratch/alpine/jaju1407/conda_pkgs
envs_dirs:
  - /projects/jaju1407/software/envs
auto_activate_base: false
EOF
cat ~/.condarc
```

## 3. Install miniforge once (sinteractive)

Skips the download if miniforge is already there. `-b` = batch mode: it does not touch `~/.bashrc`.

```bash
cd /projects/jaju1407/software
if [ ! -x miniforge3/bin/conda ]; then
  curl -L -o miniforge.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
  bash miniforge.sh -b -p /projects/jaju1407/software/miniforge3
  rm miniforge.sh
fi
/projects/jaju1407/software/miniforge3/bin/conda --version
```

Good: prints `conda 2x.x.x`.

## 4. Create the env from environment.yml (sinteractive)

Takes ~5–10 minutes.

```bash
eval "$(/projects/jaju1407/software/miniforge3/bin/conda shell.bash hook)"
conda env create -p /projects/jaju1407/software/envs/analysis -f /projects/jaju1407/HPC/environment.yml
```

## 5. Verify the env is real (sinteractive)

```bash
conda activate /projects/jaju1407/software/envs/analysis
which python
python -c "import numpy, pandas, matplotlib, ipykernel; print('imports ok', numpy.__version__, pandas.__version__, matplotlib.__version__)"
jupyter lab --version
du -sh ~ /projects/jaju1407/software
exit
```

Good:
- `which python` → `/projects/jaju1407/software/envs/analysis/bin/python`. Anything else (e.g.
  `/usr/bin/python`) means the env is half-built — see "If it fails".
- `imports ok ...` and a JupyterLab version.
- `du`: home stays small (well under 2 GB); `software` is ~1–2 GB.

`exit` ends the `sinteractive` session and returns to the login node.

## 6. Batch test (login node)

Checks the env the way real jobs will use it (`sbatch/test_env_analysis.sh`: acpu, 1 core, 10 min).

```bash
cd /projects/jaju1407/HPC
jid=$(sbatch --parsable sbatch/test_env_analysis.sh)
echo "submitted $jid"
```

## 7. Monitor (login node)

```bash
squeue -u jaju1407
cat logs/test_env_analysis.$jid.out
```

Good: the log shows `== python: /projects/jaju1407/software/envs/analysis/bin/python`, the package
versions, a pandas groupby table, a figure path under `/scratch/alpine/jaju1407/HPC/`, then
`ENV OK` and `== done`. Runs in well under a minute once it starts.

## 8. If it fails

| Symptom | Cause | Fix |
|---|---|---|
| `No space left on device` / `Disk quota exceeded` during install | a cache landed in home | redo step 2 in this shell, `du -sh ~/.cache ~/.conda` and delete what's there, retry step 4 |
| `NoWritablePkgsDirError` mentioning `/$USER` | `$USER` empty in the session | run `export USER=jaju1407`, retry |
| `which python` is not inside `envs/analysis` / create was interrupted | half-built env | `conda env remove -p /projects/jaju1407/software/envs/analysis`, then step 4 again |
| `CondaValueError: prefix already exists` | env from an earlier attempt | same remove command, then step 4 |
| job log: `ERROR: python is not from ...` or `conda: No such file` | env/miniforge not at the expected path | re-check steps 3–5 |
| job log: `ModuleNotFoundError` | package missing from the env | add it to `environment.yml`, then (sinteractive) `conda env update -p /projects/jaju1407/software/envs/analysis -f /projects/jaju1407/HPC/environment.yml --prune` |

## 9. Close the loop (login node)

```bash
cd /projects/jaju1407/HPC
git add logs/test_env_analysis.$jid.out
git commit -m "run: test_env_analysis $jid"
git push
```

Then tell Claude to pull.

## Laptop (optional): same env locally

With Miniconda/Miniforge installed on the laptop, from the repo folder:

```bash
conda env create -f environment.yml
conda activate analysis
```

Versions may differ slightly (Windows vs Linux builds, later solve date); package set is the same.

## Updating the env later

Edit `environment.yml` locally → push → on Alpine `git pull`, then steps 1, 2 (the `export` lines),
and in `sinteractive`:

```bash
eval "$(/projects/jaju1407/software/miniforge3/bin/conda shell.bash hook)"
conda env update -p /projects/jaju1407/software/envs/analysis -f /projects/jaju1407/HPC/environment.yml --prune
```

## Notes

- 2026-09-29: runbook written.
- 2026-09-28 (cluster time): env built; test job 33114601 passed (`logs/test_env_analysis.33114601.out`).
