# Running the CONUS dasymetric models (Dasy_CONUS_RF_v1 / v2)

Plan, decisions and the scale table: `docs/conus_plan.md`. Configs: `configs/conus_study_area.yaml` (window, years,
layers, water, distances), `configs/conus_rf_v1.yaml`, `configs/conus_rf_v2.yaml` (models), split table
`configs/conus_split.csv` (made once, 2026-10-23; never regenerate it). The Massachusetts configs
(`configs/study_area.yaml`, `configs/model.yaml`) and runbooks are unchanged.

All jobs are the usual stage scripts (`sbatch/*.sh`, account `ucb852_asc1`, env `hisdac`), submitted by
`sbatch/submit_conus.sh` with the CONUS config and CONUS resources. Order: **step 0 (trial) first**; the pilot
(1920 / 1960 / 2010) only after Claude has read the trial logs.

**Status:** trial passed 2026-10-23 (jobs 34814376-34814382; result in `docs/conus_plan.md`, "Trial result"). Fixed
before the pilot (2026-10-24): 4 counties without a CSV row filled from NHGIS (`filled_nhgis`), per-county JRC
no-data QA, pilot resources from the trial. Next: section 1 (pilot).

## Inputs / outputs

| | Path |
|---|---|
| county input (in) | `/projects/jaju1407/data/processed/census/counties_std_2010.gpkg` (`Checking_Std_Counties.md`) |
| county input (out) | `/projects/jaju1407/data/processed/census_conus/counties_{1920,1960,2010}.gpkg` |
| HISDAC | `/pl/active/Leyk_Lab/data/HISDAC_US_V2` (read only) |
| water | `/projects/jaju1407/data/raw/water/jrc_occurrence/` (21 tiles), `.../water/gdw/GDW_v1_0_shp/` |
| PLURAL | `/projects/jaju1407/data/raw/plural/plural_2023/` |
| tracts | `/projects/jaju1407/data/processed/tract/tracts_{YEAR}.gpkg` |
| cutout (scratch) | `/scratch/alpine/jaju1407/hisdac/cutouts/conus/` (~5-10 GB) |
| models, predictions (scratch) | `/scratch/alpine/jaju1407/hisdac/dasymetric/conus/Dasy_CONUS_RF_v{1,2}/` |
| results (git) | `results/census_conus/`, `results/cutout/conus/`, `results/dasymetric/conus/<version>/`, `results/validation/conus/<version>/` |
| job ids | `logs/conus_trial_jobs.txt`, `logs/conus_pilot_jobs.txt` |

## 0. Trial: measure time and memory (1960, v1)

What it runs (one chain): county input for 1920/1960/2010 → cutout for 1960 only → water (1960) and distances
(1960) → v1 features (1960) → v1 train (1960) → v1 prediction of **3 strips only** (`--measure 3`: times them and
extrapolates the year; writes no raster, no map). No tract validation. Expected: ~1-2 h in total plus queue.

Preflight + submit (login node; one block; nothing is submitted if an input is missing):

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
source sbatch/cluster_env.sh
ok=1
for f in $DATA_ROOT/processed/census/counties_std_2010.gpkg configs/conus_split.csv \
         $HISDAC_DIR/BUI/1960_BUI.tif $HISDAC_DIR/BUA/1960_BUA.tif $HISDAC_DIR/Land_Use/RO/Count_1960_RO.tif \
         $DATA_ROOT/raw/water/gdw/GDW_v1_0_shp/GDW_reservoirs_v1_0.shp \
         $DATA_ROOT/raw/plural/plural_2023/PLURAL_CSV/PLURAL_CSV/place_level_remoteness_all_scaled_across_years.csv; do
    [[ -e $f ]] || { echo "MISSING $f"; ok=0; }
done
n=$(ls $DATA_ROOT/raw/water/jrc_occurrence/occurrence_*.tif | wc -l)
echo "JRC tiles: $n (need 21)"; [[ $n -ge 21 ]] || ok=0
echo "split rows: $(($(wc -l < configs/conus_split.csv) - 1)) (expect 3105)"
if (( ok )); then bash sbatch/submit_conus.sh trial; else echo "NOT SUBMITTED: fix the MISSING inputs above first"; fi
```

Good: no `MISSING` line, `JRC tiles: 21`, `split rows: 3105`, and one line with 7 job ids (also in
`logs/conus_trial_jobs.txt`). If `counties_std_2010.gpkg` is missing, run `Checking_Std_Counties.md` first.

Monitor (login node):

```bash
cd /projects/jaju1407/HPC
squeue -u jaju1407
for j in $(grep -oE '[0-9]{6,}' logs/conus_trial_jobs.txt); do f=$(ls logs/*.$j.out 2>/dev/null); [[ -n $f ]] && { echo "== $f"; tail -n 4 "$f"; }; done
```

Check (each log ends with `DONE` and `== done`):
- `census_conus`: one line per year `1920: {'ok': ..., 'no_value': ...}` (1920: about 55 `no_value`, incl. the 4 polygons without a CSV row), `DONE`
- `grid_cutout`: `window: full`, `window: col_off 0 row_off 0 | 18459 x 11615 cells`, 12 layer lines for 1960 (4 HISDAC + 8 Land_Use),
  `zones 1960: 3109 counties`; a `got 0 cells` warning lists tiny counties (send it); `du -sh` at the end
- `water_frac`: `... of 3358 blocks ... (blocks with study cells), 16 worker process(es)`, `block N/N`,
  `study_uncovered_cells` 0 (no "no JRC coverage" error), QA points Quabbin / Lake Mead 1960 `full_water: ok`
- `place_dist`: five `1960 d_...: N places` lines, QA points Boston / Denver / Ely, `wrote 5 layers for 1960`
- `dasymetric_features`: `strip 5/23 ...` progress, `1960: water mask ...`, `era Y1960: ~3,0xx training rows`;
  `used counties skipped` warnings are allowed (send them)
- `dasymetric_train`: `split ...: 3105 counties, 2483 train / 622 test`, `era Y1960: split: ~2,4xx train rows ...
  ~6xx test rows`, five `fold` lines, `best params`, `CV RMSE ...`, `TEST (scored once, ... test counties): RMSE ...`
- `dasymetric_predict`: `dist_built on the whole window in N s`, three `strip` lines with `features ... s, RF ... s`,
  `MEASURE 1960: ... about N min for pass 1; nothing written`, `DONE (measure only)`

Close the loop (login node, after the last job left `squeue`): records elapsed time and peak memory of every job,
then pushes logs + small results.

```bash
cd /projects/jaju1407/HPC
ids=$(grep -oE '[0-9]{6,}' logs/conus_trial_jobs.txt | paste -sd,)
sacct -j "$ids" --format=JobID,JobName%22,State,Elapsed,MaxRSS,ReqCPUS,TotalCPU > logs/conus_trial_sacct.txt
for j in ${ids//,/ }; do seff "$j"; echo; done > logs/conus_trial_seff.txt
cat logs/conus_trial_sacct.txt
git add logs/ results/census_conus results/cutout/conus results/dasymetric/conus
git commit -m "run: CONUS trial (1960) logs + results"
git pull --rebase
git push
```

Then tell Claude; it reads the logs and sets the pilot wall times / cores in `sbatch/submit_conus.sh` (or tells you
to pass e.g. `PREDICT_TIME=12:00:00`).

## 1. Pilot: 1920, 1960, 2010 (v1 and v2)

Only after the trial was reviewed. One chain: county input → cutout (all three years; 1960 is rewritten) → water
and distances → features, train, predict for v1 and v2 (v2 after v1: it compares with v1's test predictions and
2010 map) → tract validation of both (all states, train / test counties reported separately).

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
grep -E '^(version|years|split|block_rows|compare_with):' configs/conus_rf_v1.yaml configs/conus_rf_v2.yaml
ls /projects/jaju1407/data/processed/tract/tracts_{1920,1960,2010}.gpkg
bash sbatch/submit_conus.sh pilot
```

Good: v1 shows `version: Dasy_CONUS_RF_v1`, `split: configs/conus_split.csv`, `block_rows: 512`; v2 shows
`years: [1960, 2010]`, `compare_with: Dasy_CONUS_RF_v1`; the three tract files exist; 14 job ids are printed (also in
`logs/conus_pilot_jobs.txt`). Wall times can be raised without editing anything, e.g.
`PREDICT_TIME=12:00:00 bash sbatch/submit_conus.sh pilot`.

Monitor: as in step 0 with `logs/conus_pilot_jobs.txt`. Check, in addition to step 0:
- `census_conus`: per year `filled from NHGIS ... area NHGIS / 2010 ...` or `not filled ...: no_value` lines for
  Miami-Dade, Shannon, Broomfield, Bedford city; 2010 status counts `{'filled_nhgis': 4, 'ok': 3105}`
- `water_frac`: `JRC no data by county (zones 2010): N counties with any; top 20 ...` table
- `dasymetric_train`: `rows with a status outside train_status ['ok'] left out of training and test: [...]`
  (the filled counties)
- `water_frac`: `JRC no data in study cells: mean share ... | cells with share > 0.5: N` (decides whether
  `nodata_as_water` is safe inland)
- `dasymetric_predict`: per year `strip k/23 ... ETA ... min`, then `1960 (Y1960): N counties, N cells (N masked) |
  ... | max rel diff ... | bad cells 0`, `1960: N min`, `plot` lines (maps at 1 km), `mass check: ... 0 fail | bad
  cells 0`, `DONE`
- `dasymetric_train` (v2): `Dasy_CONUS_RF_v1 on the same N test rows (its own y): RMSE ...`
- `validate_tract`: `split ...: {'train': 2483, 'test': 622}`, per year `all / train / test` lines for model and
  baseline, `DONE`

Close the loop (login node):

```bash
cd /projects/jaju1407/HPC
ids=$(grep -oE '[0-9]{6,}' logs/conus_pilot_jobs.txt | paste -sd,)
sacct -j "$ids" --format=JobID,JobName%22,State,Elapsed,MaxRSS,ReqCPUS,TotalCPU > logs/conus_pilot_sacct.txt
for j in ${ids//,/ }; do seff "$j"; echo; done > logs/conus_pilot_seff.txt
du -sh results/validation/conus/* results/dasymetric/conus/*
git add logs/ results/census_conus results/cutout/conus results/dasymetric/conus results/validation/conus
git commit -m "run: CONUS pilot (1920, 1960, 2010; v1 + v2) logs + results"
git pull --rebase
git push
```

`tract_errors_2010.csv` has one row per tract (~73 k rows, ~8 MB); if `du` shows the validation folders above
~50 MB, commit only `metrics_by_year.csv` + `qa_totals.csv` and tell Claude.

## If it fails

| Symptom | Fix |
|---|---|
| `counties_std_2010.gpkg not found` | run `Checking_Std_Counties.md` first |
| `--years [...] not in the config years` | the config on the cluster is old: `git pull` |
| `CANCELLED ... DUE TO TIME LIMIT` | rerun with a longer wall: `WATER_TIME=03:00:00 bash sbatch/submit_conus.sh pilot` (also `CUTOUT_TIME`, `PLACE_TIME`, `FEATURES_TIME`, `TRAIN_TIME`, `PREDICT_TIME`, `VALIDATE_TIME`) and send Claude the log |
| `oom-kill` / `OUT_OF_MEMORY` in `sacct` | send the log + `seff`; the stage needs more `--ntasks` in `submit_conus.sh` |
| `N study-county cells have no JRC coverage; missing tiles [...]` | a JRC tile is missing in `jrc_occurrence/`; download it (`docs/data_sources.md`) |
| `counties not in the split table` | a county of the census input is not in `configs/conus_split.csv`: send Claude the list (never regenerate the split) |
| `used counties skipped` / `counties with no unmasked cell skipped` (warnings) | expected for a few tiny or all-water counties; send the list with the logs |
| later jobs `DependencyNeverSatisfied` | an earlier job failed: `scancel` them, fix it, resubmit the chain |

## Notes

- The trial writes no prediction raster (`--measure`), so the pilot redoes 1960 completely.
- `results/cutout/conus/zones/zones_{YEAR}.csv` are the zone tables (zone_id = row of the 2010 polygon file).
