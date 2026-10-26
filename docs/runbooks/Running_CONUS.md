# Running the CONUS dasymetric models (Dasy_CONUS_RF_v1 - v4, v1_bui, v3_bui)

Plan, decisions and the scale table: `docs/conus_plan.md`. Configs: `configs/conus_study_area.yaml` (window, years,
layers, water, distances), `configs/conus_rf_v1.yaml` ... `configs/conus_rf_v4.yaml`, `conus_rf_v1_bui.yaml`, `conus_rf_v3_bui.yaml` (models), split table
`configs/conus_split.csv` (made once, 2026-10-23; never regenerate it). The Massachusetts configs
(`configs/study_area.yaml`, `configs/model.yaml`) and runbooks are unchanged.

All jobs are the usual stage scripts (`sbatch/*.sh`, account `ucb852_asc1`, env `hisdac`), submitted by
`sbatch/submit_conus.sh` with the CONUS config and CONUS resources. Order: **step 0 (trial) first**; the pilot
(1920 / 1960 / 2010) only after Claude has read the trial logs.

**Status:** trial passed 2026-10-23 (jobs 34814376-34814382; result in `docs/conus_plan.md`, "Trial result"). Fixed
before the pilot (2026-10-24): 4 counties without a CSV row filled from NHGIS (`filled_nhgis`), per-county JRC
no-data QA, pilot resources from the trial. Pilot passed 2026-10-26 (jobs 34918220-34918231; `docs/conus_plan.md`,
"Pilot result"). Section 2 (v3 + v4, BUI check, density classes) ran 2026-10-26 (jobs 34921582-34921594; county maps
failed on a CRS bug, fixed). Next: section 3 (BUI fix, v1_bui + v3_bui for 1920 / 1960 / 2010, county maps).

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
| models, predictions (scratch) | `/scratch/alpine/jaju1407/hisdac/dasymetric/conus/Dasy_CONUS_RF_v{1,2,3,4}/`, `..._v{1,3}_bui/` |
| BUI fix (scratch) | cutout `layers/BUI/` = fixed (from section 3 on), `layers/BUI_raw/` = original |
| DEM (v3, v4) | `/projects/jaju1407/data/raw/dem/gmted2010/mn75_grd` -> cutout `layers/DEM/DEM.tif` |
| results (git) | `results/census_conus/`, `results/cutout/conus/`, `results/dasymetric/conus/<version>/`, `results/validation/conus/<version>/` |
| job ids | `logs/conus_trial_jobs.txt`, `logs/conus_pilot_jobs.txt`, `logs/conus_v3v4_jobs.txt`, `logs/conus_bui_jobs.txt` |

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
echo "split rows: $(($(wc -l < configs/conus_split.csv) - 1)) (expect 3109)"
if (( ok )); then bash sbatch/submit_conus.sh trial; else echo "NOT SUBMITTED: fix the MISSING inputs above first"; fi
```

Good: no `MISSING` line, `JRC tiles: 21`, `split rows: 3109`, and one line with 7 job ids (also in
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
- `dasymetric_train`: `split ...: 3109 counties, 2487 train / 622 test`, `era Y1960: split: ~2,4xx train rows ...
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
  Miami-Dade, Shannon, Broomfield, Bedford city, each ending `-> filled_nhgis (within 0.95-1.05: training +
  allocation)` or `-> filled_nhgis_alloc (outside ...: allocation only)`; 2010: no `no_value` left
- `water_frac`: `JRC no data by county (zones 2010): N counties with any; top 20 ...` table
- `dasymetric_train`: `N rows trained on with status ['filled_nhgis']: [...]` and, if any area ratio is outside
  0.95-1.05, `rows with a status outside train_status ... left out of training and test: [...]`
- `water_frac`: `JRC no data in study cells: mean share ... | cells with share > 0.5: N` (decides whether
  `nodata_as_water` is safe inland)
- `dasymetric_predict`: per year `strip k/23 ... ETA ... min`, then `1960 (Y1960): N counties, N cells (N masked) |
  ... | max rel diff ... | bad cells 0`, `1960: N min`, `plot` lines (maps at 1 km), `mass check: ... 0 fail | bad
  cells 0`, `DONE`
- `dasymetric_train` (v2): `Dasy_CONUS_RF_v1 on the same N test rows (its own y): RMSE ...`
- `validate_tract`: `split ...: {'train': 2487, 'test': 622}`, per year `all / train / test` lines for model and
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

## 2. v3 + v4, BUI check, density classes, county maps (2026-10-27)

On the pilot cutout (water and distances of 1960 / 2010 are reused; nothing is recomputed). One submission, 14 jobs:

| Job | Needs | What |
|---|---|---|
| `bui_qa` | nothing | BUI quantiles, cells above 1e7 / 3e7 / 1e8, top 50 cells per year with county -> `results/cutout/conus/bui_quantiles.csv`, `bui_top.csv`; prints the HISDAC README / metadata files (BUI unit). Nothing waits for it: if it fails, the rest still runs |
| `grid_cutout --layers DEM` | nothing | GMTED2010 averaged onto the HISDAC grid (float32) -> cutout `layers/DEM/DEM.tif`; zones and the other layers are kept |
| `validate_tract` v1, v2 | nothing | rerun on the pilot predictions: same metrics + the density classes (`subset` `dens_0_50`, `dens_50_500`, `dens_500_2000`, `dens_2000_plus`, column `area_share`) |
| features, train, predict, validate for v3 and for v4 | DEM | 1960 + 2010; compared with v1 (same split and folds) |
| `county_maps` | v4 predict + validate, v1/v2 validation reruns | 2010, 4 rural counties, v1 / v2 / v4 side by side -> `results/validation/conus/county_maps/` |

Preflight + submit (login node; nothing is submitted if an input is missing):

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
source sbatch/cluster_env.sh
C=$HISDAC_SCRATCH/cutouts/conus; D=$HISDAC_SCRATCH/dasymetric/conus
ok=1
for f in $DATA_ROOT/raw/dem/gmted2010/mn75_grd $C/window.json $C/zones/zones_2010.tif          $C/layers/BUI/{1920,1960,2010}_BUI.tif $C/layers/water_frac/{1960,2010}_water_frac.tif          $C/layers/PLACEDIST/d_250k/{1960,2010}_d_250k.tif          $D/Dasy_CONUS_RF_v1/predictions/pop_{1920,1960,2010}.tif $D/Dasy_CONUS_RF_v2/predictions/pop_{1960,2010}.tif          $D/Dasy_CONUS_RF_v1/Y2010/model/oof_predictions.csv $DATA_ROOT/processed/census_conus/counties_2010.gpkg          $DATA_ROOT/processed/tract/tracts_{1920,1960,2010}.gpkg          $DATA_ROOT/raw/plural/plural_2023/PLURAL_SHP/PLURAL_SHP/plural_indices_scaled_across_years_2010.shp; do
    [[ -e $f ]] || { echo "MISSING $f"; ok=0; }
done
grep -E '^(version|years|compare_with):' configs/conus_rf_v3.yaml configs/conus_rf_v4.yaml
grep -n 'name: DEM' configs/conus_study_area.yaml
if (( ok )); then bash sbatch/submit_conus.sh v3v4; else echo "NOT SUBMITTED: fix the MISSING inputs above first"; fi
```

Good: no `MISSING` line; v3 / v4 show `years: [1960, 2010]` and `compare_with: Dasy_CONUS_RF_v1`; one `name: DEM` line;
one line with 14 job ids (also in `logs/conus_v3v4_jobs.txt`). If a scratch file is missing (purged or never written),
send Claude the `MISSING` lines: the pilot chain (section 1) has to be rerun first.

Monitor: as in step 0 with `logs/conus_v3v4_jobs.txt`. Check:
- `bui_qa`: `doc files under /pl/active/...: N` + the printed README text, `tags of .../BUI/...tif`, per year
  `1920: N cells, N with BUI > 0 ... | p50 ... max ... | above caps {...}`, `top 50: N in the 50 most populous
  counties, N elsewhere ...`, a `top cells by county` table, `DONE`
- `grid_cutout` (DEM): `--layers ['DEM']: window matches ...`, `1 to warp onto it`, one line
  `DEM  float64, warped (average) -> float32 ... | min ... max ...` (min about -100 m Death Valley / sea level, max about
  4,300 m), `DONE`
- `dasymetric_features` v3 / v4: `strip 5/23` progress, `feature summary` with `elev` (m) and `slope` (degrees) rows,
  `era Y2010: ~3,1xx training rows`
- `dasymetric_train` v3 / v4: `split ...: 2487 train / 622 test`, `CV RMSE ...`, `TEST ...`, `Dasy_CONUS_RF_v1 on the
  same N test rows ...`
- `dasymetric_predict` v3 / v4: `mass check: ... 0 fail | bad cells 0`, `DONE`
- `validate_tract` (all four): per year `all model all n=...` lines, then `by observed tract density (people/km2),
  MdAPE %` table, `DONE`
- `county_maps`: `metros: N PLURAL places with >= 250000 people in 2010`, per county and version `pop ... | on BUI = 0
  cells ... % | people-weighted km to <place> ...`, four `plot ... county_G..._2010.png` lines, `DONE`

Close the loop (login node, after the last job left `squeue`):

```bash
cd /projects/jaju1407/HPC
ids=$(grep -oE '[0-9]{6,}' logs/conus_v3v4_jobs.txt | paste -sd,)
sacct -j "$ids" --format=JobID,JobName%22,State,Elapsed,MaxRSS,ReqCPUS,TotalCPU > logs/conus_v3v4_sacct.txt
for j in ${ids//,/ }; do seff "$j"; echo; done > logs/conus_v3v4_seff.txt
cat logs/conus_v3v4_sacct.txt
du -sh results/validation/conus/* results/dasymetric/conus/* results/cutout/conus
git add logs/ results/cutout/conus results/dasymetric/conus results/validation/conus
git commit -m "run: CONUS v3 + v4, BUI check, density classes, county maps (logs + results)"
git pull --rebase
git push
```

## 3. BUI fix, v1_bui + v3_bui (1920, 1960, 2010), county maps (2026-10-27)

On the pilot cutout with the DEM layer of section 2 (water, distances reused). One submission, 11 jobs
(`docs/conus_plan.md`, "BUI fix and v3 base rerun"):

| Job | Needs | What |
|---|---|---|
| `bui_fix` (CONUS) | nothing | BUI > 3e7 sq ft -> median of the 3 x 3 neighbours, every year, in place on `layers/BUI/` (original kept in `layers/BUI_raw/`) -> `results/cutout/conus/bui_fix_summary.csv`, `bui_fixed_{YEAR}.csv` |
| `bui_fix --check` (Massachusetts) | nothing | count only, raw HISDAC BUI over the Massachusetts window -> `results/cutout/massachusetts/bui_check_summary.csv`. Nothing waits for it |
| features, train, predict, validate for v1_bui and for v3_bui | `bui_fix` | 1920 + 1960 + 2010; v1_bui compared with v1, v3_bui with v3 (same split and folds) |
| `county_maps` | both predicts + validations | 2010, the 4 counties, v1_bui / v2 / v3_bui / v4 -> `results/validation/conus/county_maps/` |

Block 1, preflight + submit (login node; nothing is submitted if an input is missing):

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
source sbatch/cluster_env.sh
C=$HISDAC_SCRATCH/cutouts/conus
D=$HISDAC_SCRATCH/dasymetric/conus
P=$DATA_ROOT/raw/plural/plural_2023
need=()
need+=($C/window.json $C/zones/zones_{1920,1960,2010}.tif)
need+=($C/layers/BUI/{1920,1960,2010}_BUI.tif $C/layers/BUPL/{1920,1960,2010}_BUPL.tif)
need+=($C/layers/DEM/DEM.tif $C/layers/water_frac/{1920,1960,2010}_water_frac.tif)
need+=($D/Dasy_CONUS_RF_v{1,3}/Y2010/model/oof_predictions.csv)
need+=($D/Dasy_CONUS_RF_v{1,2,3,4}/predictions/pop_2010.tif)
need+=(results/validation/conus/Dasy_CONUS_RF_v{2,4}/tract_errors_2010.csv)
need+=(results/cutout/massachusetts/window.json $HISDAC_DIR/BUI/2010_BUI.tif)
need+=($DATA_ROOT/processed/census_conus/counties_2010.gpkg)
need+=($DATA_ROOT/processed/tract/tracts_{1920,1960,2010}.gpkg)
need+=($P/PLURAL_SHP/PLURAL_SHP/plural_indices_scaled_across_years_2010.shp)
need+=($P/PLURAL_CSV/PLURAL_CSV/place_level_remoteness_all_scaled_across_years.csv)
ok=1
for f in "${need[@]}"; do [[ -e $f ]] || { echo "MISSING $f"; ok=0; }; done
echo "checked ${#need[@]} inputs"
grep -n '^bui_cap' configs/conus_study_area.yaml
grep -c '^bui_cap' configs/study_area.yaml
grep -E '^(version|compare_with):' configs/conus_rf_v1_bui.yaml configs/conus_rf_v3_bui.yaml
ls $C/layers/BUI_raw 2>/dev/null
if (( ok )); then bash sbatch/submit_conus.sh bui; else echo "NOT SUBMITTED: fix the MISSING inputs above first"; fi
echo "== end of block 1"
```

Good: no `MISSING` line, `checked 30 inputs`, one `bui_cap: {max: 3.0e+7, ...}` line, `0` (Massachusetts has no cap),
the two versions with `compare_with: Dasy_CONUS_RF_v1` / `Dasy_CONUS_RF_v3`, no `BUI_raw` listing (first run), then
one line `bui_fix N | ma_check N | v1_bui features N train N predict N validate N | v3_bui ... | county_maps N`
(11 ids, also in `logs/conus_bui_jobs.txt`) and `== end of block 1`. If `== end of block 1` is missing, the paste was
cut: run `cat logs/conus_bui_jobs.txt` and `squeue -u $USER` before pasting again (never submit twice).

Block 2, monitor:

```bash
cd /projects/jaju1407/HPC
squeue -u $USER
for j in $(grep -oE '[0-9]{6,}' logs/conus_bui_jobs.txt); do f=$(ls logs/*.$j.out 2>/dev/null); [[ -n $f ]] && { echo "== $f"; tail -n 3 "$f"; }; done
echo "== end of block 2"
```

Good: the last lines of the started jobs (`== done ...` when finished) and `== end of block 2`. Check in the logs:
- `bui_fix` (CONUS): per year `moved .../layers/BUI/{YEAR}_BUI.tif -> .../BUI_raw/...` (first run only), then
  `{YEAR}: N cells above 3e+07 ...` with N = 10 / 119 / 298 (1920 / 1960 / 2010, as `bui_qa`), `max ... -> ...` at
  most 3e+07, a `largest` table, `summary`, `DONE`
- `bui_fix --check` (Massachusetts): `check only, nothing written` per year (22 years; a warning for a year without
  a raw file), `years with cells above the cap: [...]`, `DONE`
- features / train / predict / validate: as in section 2; train v1_bui `Dasy_CONUS_RF_v1 (its saved out-of-fold
  predictions ...)` for every year; v3_bui the same for 1960 / 2010 and `compare_with Dasy_CONUS_RF_v3 skipped` for 1920
- `county_maps`: `shapefile CRS ... -> cutout CRS ESRI:102039`, `metros: N PLURAL places ...`, four `plot ...` lines, `DONE`

Block 3, close the loop (after the last job left `squeue`):

```bash
cd /projects/jaju1407/HPC
ids=$(grep -oE '[0-9]{6,}' logs/conus_bui_jobs.txt | paste -sd,)
sacct -j "$ids" --format=JobID,JobName%22,State,Elapsed,MaxRSS,ReqCPUS,TotalCPU > logs/conus_bui_sacct.txt
for j in ${ids//,/ }; do seff "$j"; echo; done > logs/conus_bui_seff.txt
cat logs/conus_bui_sacct.txt
du -sh results/validation/conus/* results/dasymetric/conus/* results/cutout/*
git add logs/ results/cutout results/dasymetric/conus results/validation/conus
git commit -m "run: CONUS BUI fix, v1_bui + v3_bui (1920/1960/2010), county maps (logs + results)"
git pull --rebase
git push
git log --oneline -1
echo "== end of block 3"
```

Good: `sacct` shows `COMPLETED` for every job, `git push` ends with `main -> main`, the last commit is the
`run: CONUS BUI fix ...` one, then `== end of block 3`.

## If it fails

| Symptom | Fix |
|---|---|
| `counties_std_2010.gpkg not found` | run `Checking_Std_Counties.md` first |
| `--years [...] not in the config years` | the config on the cluster is old: `git pull` |
| `CANCELLED ... DUE TO TIME LIMIT` | rerun with a longer wall: `WATER_TIME=03:00:00 bash sbatch/submit_conus.sh pilot` (also `CUTOUT_TIME`, `PLACE_TIME`, `FEATURES_TIME`, `TRAIN_TIME`, `PREDICT_TIME`, `VALIDATE_TIME`; v3v4 also `BUI_TIME`, `MAPS_TIME`; bui also `FIX_TIME`, `CHECK_TIME`) and send Claude the log |
| v3v4: `bui_qa` failed | nothing else depends on it; send the log. Rerun alone: `sbatch --export=ALL,CONFIG=configs/conus_study_area.yaml sbatch/bui_qa.sh` |
| v3v4: `county_maps` failed (e.g. a plotting error) | rerun alone after fixing: `sbatch sbatch/county_maps.sh --counties G5300070 G2001550 G0800430 G1701170 --versions Dasy_CONUS_RF_v1 Dasy_CONUS_RF_v2 Dasy_CONUS_RF_v4` |
| bui: `bui_fix` failed | the model jobs never start (`DependencyNeverSatisfied`): `scancel` them, send the log. A rerun is safe: it reads `layers/BUI_raw/` and writes `layers/BUI/` again |
| bui: `has no bui_cap block` | the config on the cluster is old (`git pull`), or the Massachusetts config was given without `--check` (intended: it is never changed) |
| bui: Massachusetts `--check` failed | nothing depends on it; rerun alone: `sbatch --export=ALL,CONFIG=configs/study_area.yaml sbatch/bui_fix.sh --check --cap 3e7 --hisdac-dir "$HISDAC_DIR" --window-json results/cutout/massachusetts/window.json` |
| bui: `county_maps` failed | rerun alone: `sbatch sbatch/county_maps.sh --counties G5300070 G2001550 G0800430 G1701170 --versions Dasy_CONUS_RF_v1_bui Dasy_CONUS_RF_v2 Dasy_CONUS_RF_v3_bui Dasy_CONUS_RF_v4` |
| `oom-kill` / `OUT_OF_MEMORY` in `sacct` | send the log + `seff`; the stage needs more `--ntasks` in `submit_conus.sh` |
| `N study-county cells have no JRC coverage; missing tiles [...]` | a JRC tile is missing in `jrc_occurrence/`; download it (`docs/data_sources.md`) |
| `counties not in the split table` | a county of the census input is not in `configs/conus_split.csv`: send Claude the list (never regenerate the split) |
| `used counties skipped` / `counties with no unmasked cell skipped` (warnings) | expected for a few tiny or all-water counties; send the list with the logs |
| later jobs `DependencyNeverSatisfied` | an earlier job failed: `scancel` them, fix it, resubmit the chain |

## Notes

- The trial writes no prediction raster (`--measure`), so the pilot redoes 1960 completely.
- `results/cutout/conus/zones/zones_{YEAR}.csv` are the zone tables (zone_id = row of the 2010 polygon file).
