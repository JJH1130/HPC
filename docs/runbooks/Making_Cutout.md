# Making a study-area cutout (HISDAC layers + county zones)

Cuts the HISDAC-US V2 layers to the study area in `configs/study_area.yaml` and builds the
per-year county zone grids. Rules are in `docs/cutout.md`. Code: `src/grid/make_cutout.py`;
job: `sbatch/grid_cutout.sh` (acpu, 2 cores, 1 h, env `hisdac`). Prerequisite: the full
census_prepare run (`Preparing_Census.md`), because this job reads `counties_{YEAR}.gpkg`.

**Status:** code written 2026-09-30, tested only on synthetic data on the laptop. Not yet run on Alpine.

HISDAC is read from `/pl/active/Leyk_Lab/data/HISDAC_US_V2` (**read only**; nothing is written
to PetaLibrary). Output goes to `/scratch/alpine/jaju1407/hisdac/cutouts/massachusetts/`.

## 1. Sync + preflight (login node)

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs
ls /pl/active/Leyk_Lab/data/HISDAC_US_V2/
ls /pl/active/Leyk_Lab/data/HISDAC_US_V2/BUI | head -3
find /pl/active/Leyk_Lab/data/HISDAC_US_V2 -name '*FBUY*.tif' -o -name '*NobuiltYear*.tif'
ls /projects/jaju1407/data/processed/census/ | head -3
```

Good: the folders BUI, BUPL, BUPR, BUA exist, BUI contains `1810_BUI.tif`, and `find` prints exactly
one FBUY file and one NobuiltYear file. If `find` prints more than one or none, change the globs
under `static_layers` in `configs/study_area.yaml`.

## 2. Quick test: one year (login node)

The window still comes from all 22 years; only 1810 layers and zones are written, plus FBUY and
NobuiltYear.

```bash
cd /projects/jaju1407/HPC
jid=$(sbatch --parsable sbatch/grid_cutout.sh --years 1810)
echo "submitted $jid"
```

## 3. Monitor (login node)

```bash
squeue -u jaju1407
tail -n 60 logs/grid_cutout.$jid.out
```

Check these lines in the log:
- `reference grid: 1810_BUI.tif | ... | cell 250.0 x 250.0 | origin (...)` and `all N rasters share the reference grid`
- `1810: N counties, bounds [...]`, one line per year. 1810 has more counties than later years because it includes Maine.
- `window: col_off ... | W x H cells`
- one line per layer with source dtype and nodata, `-> int32`, min/max. A `source declares nodata=0` warning means 0 was kept as a value.
- `zones 1810: N counties, ... area ratio min/median/max`, and any `got 0 cells` warnings
- `DONE`

## 4. Full run (login node)

```bash
cd /projects/jaju1407/HPC
jid=$(sbatch --parsable sbatch/grid_cutout.sh)
echo "submitted $jid"
```

## 5. If it fails

| Symptom | Fix |
|---|---|
| `ERROR: HISDAC inputs ... missing:` or `matched 0 files` / `matched 2 files` | check the file names (`ls`) and fix `yearly_pattern` / `static_layers` in `configs/study_area.yaml` |
| `ERROR: rasters not on the reference grid` | a layer has a different grid; send Claude the listed lines |
| `ERROR: no county matches states` / `never appear in the state column` | spelling of `states` vs the `state` column in `counties_{YEAR}.gpkg` |
| `ERROR: ... non-integer values` / `don't fit int32` | send Claude the log; the layer isn't what the rules assume |
| `counties_{YEAR}.gpkg not found` | run the full census_prepare first |
| `CANCELLED ... DUE TO TIME LIMIT` | raise `--time` in `sbatch/grid_cutout.sh` |

## 6. Close the loop (login node)

```bash
cd /projects/jaju1407/HPC
git add logs/grid_cutout.$jid.out results/cutout/
git commit -m "run: grid_cutout $jid"
git pull --rebase
git push
```

Then tell Claude to pull.

## Notes

- 2026-09-30: runbook written. The FBUY/NobuiltYear file names aren't known yet; the config uses the globs `**/*FBUY*.tif` and `**/*NobuiltYear*.tif`, which must each match exactly one file.
