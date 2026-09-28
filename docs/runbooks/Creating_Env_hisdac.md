# Creating the conda env ("hisdac") on Alpine

Builds the `hisdac` env (geospatial + ML: rasterio, geopandas, pyogrio, scikit-learn, LightGBM, SHAP,
pyyaml, pyarrow, matplotlib, ipykernel) from `envs/hisdac/environment.yml`, registers it as a Jupyter
kernel, and checks it with a batch job. It is a separate env so the GDAL stack can't disturb the
validated `analysis` env.

Prerequisite: `Creating_Cluster_Envs.md` steps 1–3 done once (miniforge installed, `~/.condarc`
written) — true since 2026-09-28.

**Last run / verified:** not yet.

| | Path |
|---|---|
| env file | `/projects/jaju1407/HPC/envs/hisdac/environment.yml` |
| env | `/projects/jaju1407/software/envs/hisdac` |
| package cache | `/scratch/alpine/jaju1407/conda_pkgs` (from `~/.condarc`) |
| Jupyter kernel spec | `~/.local/share/jupyter/kernels/hisdac/` (a few KB) |

`shap` is pinned to its CPU build (`shap=*=cpu*`): otherwise the solver may pick the CUDA build and
pull in GBs of CUDA libraries this CPU work never uses.

## 0. Sync (login node)

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs
```

## 1. Start an interactive session (login node → compute node)

```bash
sinteractive --partition=acompile --qos=compile --ntasks=4 --time=01:00:00
```

## 2. Create the env (sinteractive)

`$USER` can be empty in `sinteractive`, so it is set first. Takes ~5–15 minutes (GDAL stack is large).

```bash
export USER=jaju1407
export TMPDIR=/scratch/alpine/jaju1407/tmp
mkdir -p "$TMPDIR"
eval "$(/projects/jaju1407/software/miniforge3/bin/conda shell.bash hook)"
cd /projects/jaju1407/HPC/envs/hisdac
conda env create -f environment.yml -p /projects/jaju1407/software/envs/hisdac
```

## 3. Verify (sinteractive)

```bash
conda activate /projects/jaju1407/software/envs/hisdac
which python
python -c "import rasterio, geopandas, pyogrio, sklearn, lightgbm, shap, yaml, pyarrow, matplotlib, ipykernel; print('imports ok | rasterio', rasterio.__version__, '| GDAL', rasterio.__gdal_version__, '| geopandas', geopandas.__version__, '| shap', shap.__version__)"
python -c "from pyproj import CRS; print(CRS('EPSG:5070').name)"
```

Good:
- `which python` → `/projects/jaju1407/software/envs/hisdac/bin/python`
- `imports ok | ...` with versions
- `NAD83 / Conus Albers` (proves PROJ's data files are found)

## 4. Register the Jupyter kernel (sinteractive, env still active)

Writes a small kernel spec to `~/.local/share/jupyter/kernels/hisdac/` that points at this env's
python by absolute path, so Jupyter (e.g. an Open OnDemand Jupyter session) can offer
"Python (hisdac)" without activating anything.

```bash
python -m ipykernel install --user --name hisdac --display-name "Python (hisdac)"
jupyter kernelspec list
```

Good: the list shows `hisdac   /home/jaju1407/.local/share/jupyter/kernels/hisdac`.

First cell to run in a notebook with this kernel (checks it's the right env and PROJ works):

```python
import sys, rasterio
from pyproj import CRS
print(sys.executable, rasterio.__gdal_version__, CRS("EPSG:5070").name)
```

Expected: `/projects/jaju1407/software/envs/hisdac/bin/python 3.x.x NAD83 / Conus Albers`.

Then leave the session:

```bash
exit
```

## 5. Batch test (login node)

`sbatch/test_env_hisdac.sh` (acpu, 1 core, 10 min) runs a tiny pass through every package.

```bash
cd /projects/jaju1407/HPC
jid=$(sbatch --parsable sbatch/test_env_hisdac.sh)
echo "submitted $jid"
```

## 6. Monitor (login node)

```bash
squeue -u jaju1407
cat logs/test_env_hisdac.$jid.out
```

Good: `== python: /projects/jaju1407/software/envs/hisdac/bin/python`, a version line per group,
then `rasterio GeoTIFF ok: EPSG:5070 50x50`, `geopandas ok`, `lightgbm ok`, `shap ok ... top feature =
x0`, `yaml + matplotlib ok`, `ENV OK`, `== done`. Well under a minute once running.

## 7. If it fails

| Symptom | Cause | Fix |
|---|---|---|
| `CondaValueError: prefix already exists` | earlier attempt left an env | `conda env remove -p /projects/jaju1407/software/envs/hisdac`, then step 2 |
| `which python` not inside `envs/hisdac` / create interrupted | half-built env | same remove, then step 2 |
| `NoWritablePkgsDirError` mentioning `/$USER` | `$USER` empty | `export USER=jaju1407`, retry |
| `No space left on device` / quota | a cache landed in home | `du -sh ~/.cache ~/.conda`, delete, check `cat ~/.condarc` has `pkgs_dirs` on scratch |
| `PROJ: proj_create_from_database: ... proj.db` / CRS errors | PROJ data not found | make sure the env is activated (job: `activate_env hisdac`); in Jupyter, confirm the kernel is "Python (hisdac)" |
| kernel missing in Jupyter | spec not registered, or Jupyter session started before step 4 | re-run step 4, restart the Jupyter session |
| job log: `ModuleNotFoundError` | package missing from the env | add it to `envs/hisdac/environment.yml`, then update (below) |

## 8. Close the loop (login node)

```bash
cd /projects/jaju1407/HPC
git add logs/test_env_hisdac.$jid.out
git commit -m "run: test_env_hisdac $jid"
git push
```

Then tell Claude to pull.

## Updating the env later

Edit `envs/hisdac/environment.yml` locally → push → on Alpine `git pull`, step 1, then in
`sinteractive` (never `mamba install` directly — the file is the source of truth, and `--prune`
removes anything not in it):

```bash
export USER=jaju1407
eval "$(/projects/jaju1407/software/miniforge3/bin/conda shell.bash hook)"
cd /projects/jaju1407/HPC/envs/hisdac
conda env update -f environment.yml -p /projects/jaju1407/software/envs/hisdac --prune
```

## Laptop (optional)

```bash
conda env create -f envs/hisdac/environment.yml
conda activate hisdac
```

## Notes

- 2026-09-29: env file written; linux-64 dry-run solve on the laptop resolved all packages from
  conda-forge (python 3.12.14, rasterio 1.5.1 / GDAL 3.13.3, geopandas 1.2.0, lightgbm 4.7.0,
  shap 0.52.0 cpu, numpy 2.5.3). Not yet built on Alpine.
