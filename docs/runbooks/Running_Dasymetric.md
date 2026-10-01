# Running dasymetric v1 (county features → model → cell population)

Runs the three stages of `docs/dasymetric_v1.md` on the study-area cutout. Code: `src/dasymetric/`;
settings: `configs/model.yaml` (model, search space, features, statuses); study area and years come
from `configs/study_area.yaml`. Prerequisite: the full grid_cutout run (`Making_Cutout.md`), because
every stage reads `/scratch/alpine/jaju1407/hisdac/cutouts/massachusetts/`. Scratch is purged 90 days
after creation; if the cutout is gone, rerun grid_cutout first.

| Stage | Script | Job | Resources | Writes (under `/scratch/alpine/jaju1407/hisdac/dasymetric/massachusetts/v1/`) |
|---|---|---|---|---|
| 1 | `county_features.py` | `sbatch/dasymetric_features.sh` | acpu, 2 cores, 30 min | `features/county_features.csv` |
| 2 | `train.py` | `sbatch/dasymetric_train.sh` | acpu, 4 cores, 30 min | `model/` (rf.joblib, cv_results, best_params, metrics, feature_importance) |
| 3 | `predict.py` | `sbatch/dasymetric_predict.sh` | acpu, 8 cores, 1 h | `predictions/pop_{YEAR}.tif`, `qa/reallocation_qa.csv`, `maps/pop_{1810,1900,2020}.png` |

Each stage runs on its own and reads only what the stage before it wrote, so a stage can be rerun
alone (e.g., only stage 3 after changing the map years). The small outputs are copied to
`results/dasymetric/massachusetts/v1/` for git. The rasters stay on scratch.

**Status:** tested on fake data only (laptop, 2026-10-02). Not yet run on Alpine.

## 1. Sync + preflight (login node)

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs
ls /scratch/alpine/jaju1407/hisdac/cutouts/massachusetts/zones | head -3
ls /scratch/alpine/jaju1407/hisdac/cutouts/massachusetts/layers
ls /scratch/alpine/jaju1407/hisdac/cutouts/massachusetts/layers/FBUY
```

Good: `zones` lists `zones_1810.csv` …, `layers` lists BUA, BUI, BUPL, BUPR, FBUY, Land_Use,
NobuiltYear, and the FBUY folder has exactly one `.tif`.

## 2. Submit all three stages as a chain (login node)

`afterok` starts each stage only if the previous one finished without error.

```bash
cd /projects/jaju1407/HPC
j1=$(sbatch --parsable sbatch/dasymetric_features.sh)
j2=$(sbatch --parsable --dependency=afterok:$j1 sbatch/dasymetric_train.sh)
j3=$(sbatch --parsable --dependency=afterok:$j2 sbatch/dasymetric_predict.sh)
echo "features $j1 | train $j2 | predict $j3"
```

To run one stage alone (its input must already exist), submit only that script, e.g.
`sbatch sbatch/dasymetric_predict.sh --years 1900`.

## 3. Monitor (login node)

```bash
squeue -u jaju1407
tail -n 40 logs/dasymetric_features.$j1.out
tail -n 40 logs/dasymetric_train.$j2.out
tail -n 40 logs/dasymetric_predict.$j3.out
```

If stage 1 or 2 fails, the later jobs stay pending with reason `DependencyNeverSatisfied`.
Cancel them with `scancel $j2 $j3`, fix the problem, and submit again from step 2.

Check these lines:
- features: `county-years: 314 before status filtering ..., N training rows | ... counties | 22 years`, then `DONE`
- train: `training rows: ...`, `fold 0..4: CV RMSE ...`, `best params {...}`, `CV RMSE ... | CV R2 ... | train RMSE ...`, the importance table, `DONE`
- predict: one line per year (`counties, cells | y_hat ... | pop -> cells | max rel diff`), `map ...` for 1810, 1900 and 2020, `mass check: 314 county-years ... 0 fail | bad cells 0`, `DONE`

## 4. If it fails

| Symptom | Fix |
|---|---|
| `zones_{YEAR}.tif not found` / `layers/... not found` | the cutout is missing or purged: rerun grid_cutout (`Making_Cutout.md`) |
| `used counties with 0 cells, pop <= 0 or area <= 0` | a county can't be modeled or reallocated; send Claude the listed rows (needs a decision) |
| `nodata cells inside the used counties` | send Claude the log; the cutout isn't what the rules assume |
| `model 'lgbm' is a placeholder` | only `model: rf` is implemented in v1 |
| `county_features.csv not found` / `rf.joblib not found` | run the earlier stage first |
| `reallocation checks failed` | the QA CSV is still copied back; push it and send Claude the log |
| `CANCELLED ... DUE TO TIME LIMIT` | raise `--time` in that stage's script |

## 5. Close the loop (login node)

```bash
cd /projects/jaju1407/HPC
git add logs/dasymetric_features.$j1.out logs/dasymetric_train.$j2.out logs/dasymetric_predict.$j3.out results/dasymetric/
git commit -m "run: dasymetric v1 $j1 $j2 $j3"
git pull --rebase
git push
```

Then tell Claude to pull.

## Notes

- 2026-10-02: runbook written. Tested on a fake 3-year cutout (24 counties, one `nodata_zero`): all
  three stages ran, mass was preserved (max relative difference 3e-8), the excluded county and
  cells outside the counties were NoData, and the lgbm placeholder and a used county with 0 cells
  stopped with clear errors. The PNG maps were checked in a separate Python environment, because
  matplotlib crashes when saving PNGs in the laptop env.
