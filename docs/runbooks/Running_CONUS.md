# Running the CONUS dasymetric models (Dasy_CONUS_RF_v1 - v4, v1_bui, v3_bui, model family n60, v3_all + 2020, v3_ntl, v3_ntlv), the external comparison, metrics over time, the HISDAC record uncertainty, the uncertainty filter and the PLURAL grid test

Plan, decisions and the scale table: `docs/conus_plan.md`. Configs: `configs/conus_study_area.yaml` (window, years,
layers, water, distances), `configs/conus_rf_v1.yaml` ... `configs/conus_rf_v4.yaml`, `conus_rf_v1_bui.yaml`, `conus_rf_v3_bui.yaml`, `conus_{rf,lgbm,xgb,cat}_v3_n60.yaml`, `conus_rf_v3_all.yaml`, `conus_rf_v3_ntl.yaml`, `conus_rf_v3_ntlv.yaml` (models), `configs/external_grids.yaml`
(external products, section 8), split table
`configs/conus_split.csv` (made once, 2026-10-23; never regenerate it). The Massachusetts configs
(`configs/study_area.yaml`, `configs/model.yaml`) and runbooks are unchanged.

All jobs are the usual stage scripts (`sbatch/*.sh`, account `ucb852_asc1`, env `hisdac`), submitted by
`sbatch/submit_conus.sh` with the CONUS config and CONUS resources. Order: **step 0 (trial) first**; the pilot
(1920 / 1960 / 2010) only after Claude has read the trial logs.

**Status:** trial passed 2026-10-23 (jobs 34814376-34814382; result in `docs/conus_plan.md`, "Trial result"). Fixed
before the pilot (2026-10-24): 4 counties without a CSV row filled from NHGIS (`filled_nhgis`), per-county JRC
no-data QA, pilot resources from the trial. Pilot passed 2026-10-26 (jobs 34918220-34918231; `docs/conus_plan.md`,
"Pilot result"). Section 2 (v3 + v4, BUI check, density classes) ran 2026-10-26 (jobs 34921582-34921594; county maps
failed on a CRS bug, fixed). Next: section 3 (BUI fix, v1_bui + v3_bui for 1920 / 1960 / 2010, county maps). Section 3 ran 2026-10-26 (jobs 34926193-34926203). Next: section 4
(model family). Section 4 ran 2026-10-27 (jobs 34932548-34932563; RF chosen). Next: section 5
(all census years 1900-2010). Section 5 ran 2026-10-27 (jobs 34939345-34939353). Next: section 6 (night lights
test, 2000 / 2010). Section 6 ran 2026-10-28 (jobs 34956826-34956833). Next: section 7 (VIIRS-like night lights).
Section 7 ran 2026-10-28 (jobs 34961482-34961489). Next: section 8 (external products on the same tracts; written
2026-10-28, not run yet). Written 2026-10-30, not run yet: section 9 (county MdAPE + fixed tract sets: 1900-2010 computed on
the laptop, no job needed), section 10 (2020 added to v3_all: pre-check, then `submit_conus.sh y2020`), section 11
(HISDAC record uncertainty: download, then `submit_conus.sh uncertainty`). Sections 8, 10 and 11 are independent.
Section 10 ran 2026-10-29 (jobs 35053415-35053424). Section 11 block 1 ran 2026-10-29: `BUPR_contemp.tif` is not in the
Dataverse archive; the job runs without it (NobuiltYear only; job 35056349, 2026-10-29). Written 2026-10-30, not run
yet: section 12 (uncertainty filter, `submit_conus.sh uncfilter`).

## Inputs / outputs

| | Path |
|---|---|
| county input (in) | `/projects/jaju1407/data/processed/census/counties_std_2010.gpkg` (`Checking_Std_Counties.md`) |
| county input (out) | `/projects/jaju1407/data/processed/census_conus/counties_{YEAR}.gpkg` (1920 / 1960 / 2010; 1900-2010 from section 5) |
| HISDAC | `/pl/active/Leyk_Lab/data/HISDAC_US_V2` (read only) |
| water | `/projects/jaju1407/data/raw/water/jrc_occurrence/` (21 tiles), `.../water/gdw/GDW_v1_0_shp/` |
| PLURAL | `/projects/jaju1407/data/raw/plural/plural_2023/` |
| tracts | `/projects/jaju1407/data/processed/tract/tracts_{YEAR}.gpkg` |
| cutout (scratch) | `/scratch/alpine/jaju1407/hisdac/cutouts/conus/` (~5-10 GB) |
| models, predictions (scratch) | `/scratch/alpine/jaju1407/hisdac/dasymetric/conus/Dasy_CONUS_RF_v{1,2,3,4}/`, `..._v{1,3}_bui/` |
| BUI fix (scratch) | cutout `layers/BUI/` = fixed (from section 3 on), `layers/BUI_raw/` = original |
| DEM (v3, v4) | `/projects/jaju1407/data/raw/dem/gmted2010/mn75_grd` -> cutout `layers/DEM/DEM.tif` |
| NTL (v3_ntl) | `/projects/jaju1407/data/raw/ntl/Harmonized_DN_NTL_{YEAR}_*.tif` -> cutout `layers/NTL/{YEAR}_NTL.tif` (2000, 2010) |
| NTLV (v3_ntlv) | `/projects/jaju1407/data/raw/ntl/viirs_like/v1/{YEAR}/*.tif` (`sbatch/ntlv_download.sh`) -> cutout `layers/NTLV/{YEAR}_NTLV.tif` (2000, 2010) |
| external products (section 8) | `/projects/jaju1407/data/raw/external/{ghs_pop,worldpop,gpw4,grump1,fang_jawitz,docs}/` (`sbatch/external_download.sh`) -> tract sums `/scratch/alpine/jaju1407/hisdac/external/conus/sums/` |
| results (git) | `results/census_conus/`, `results/cutout/conus/`, `results/dasymetric/conus/<version>/`, `results/validation/conus/<version>/`, `results/validation/conus/external/` |
| job ids | `logs/conus_trial_jobs.txt`, `logs/conus_pilot_jobs.txt`, `logs/conus_v3v4_jobs.txt`, `logs/conus_bui_jobs.txt`, `logs/conus_models_jobs.txt`, `logs/conus_all_jobs.txt`, `logs/conus_ntl_jobs.txt`, `logs/conus_ntlv_jobs.txt`, `logs/conus_external_jobs.txt` |

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

## 4. Model family: RF / LightGBM / XGBoost / CatBoost, 60 candidates each (2026-10-27)

On the BUI-fixed cutout with v3_bui's features (`docs/conus_plan.md`, "Model family"). First the env update
(xgboost, catboost), then one submission of 16 jobs:

| Job | Needs | What |
|---|---|---|
| `test_env_hisdac` | nothing | env check incl. LightGBM / XGBoost / CatBoost search, pickle, SHAP. Every other job waits for it |
| `validate_tract` v3_bui | env check | rerun with `--gap-share 0.05`: parts `no_gap` / `gap` (20-candidate reference) |
| train, predict, validate for RF / LGBM / XGB / CAT n60 | env check | 1920 + 1960 + 2010; features copied from v3_bui at submit time; compared with v3_bui (same folds, checked) |
| `compare_models` | the 5 validations | `results/validation/conus/model_comparison.csv` + a summary per year in the log |
| `county_maps` | the 4 predicts + validations | 2010, the 4 counties, the four n60 models -> `results/validation/conus/county_maps/` |

Block 0, env update (login node, then the compile node; about 5-15 min):

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
sinteractive --partition=acompile --qos=compile --ntasks=4 --time=01:00:00
```

Then, inside `sinteractive` (the prompt shows a compute node):

```bash
export USER=jaju1407
export TMPDIR=/scratch/alpine/jaju1407/tmp
mkdir -p "$TMPDIR"
eval "$(/projects/jaju1407/software/miniforge3/bin/conda shell.bash hook)"
cd /projects/jaju1407/HPC/envs/hisdac
conda env update -f environment.yml -p /projects/jaju1407/software/envs/hisdac --prune
conda activate /projects/jaju1407/software/envs/hisdac
python -c "import numpy as np, catboost, xgboost, lightgbm, shap, sklearn; from sklearn.model_selection import RandomizedSearchCV as R; X = np.random.rand(60, 3); R(catboost.CatBoostRegressor(verbose=0, allow_writing_files=False, thread_count=1), {'depth': [2, 3]}, n_iter=2, cv=2).fit(X, X[:, 0]); print('ENV UPDATED | xgboost', xgboost.__version__, '| catboost', catboost.__version__, '| lightgbm', lightgbm.__version__, '| shap', shap.__version__, '| sklearn', sklearn.__version__)"
cd /projects/jaju1407/HPC
echo "== end of block 0"
exit
```

Good: `conda env update` ends without an error, then one line `ENV UPDATED | xgboost 3.x | catboost 1.2.8 or later
| ...`, `== end of block 0`, and `exit` returns to the login node. If the `python -c` line prints a traceback, stop
and send it to Claude (do not run block 1).

Block 1, preflight + submit (login node; nothing is copied or submitted if an input is missing or the env lacks a
package):

```bash
cd /projects/jaju1407/HPC
git log --oneline -1
source sbatch/cluster_env.sh
C=$HISDAC_SCRATCH/cutouts/conus
D=$HISDAC_SCRATCH/dasymetric/conus
V=$D/Dasy_CONUS_RF_v3_bui
P=$DATA_ROOT/raw/plural/plural_2023
need=()
need+=($V/Y{1920,1960,2010}/features/county_features.csv)
need+=($V/Y{1920,1960,2010}/model/oof_predictions.csv $V/Y{1920,1960,2010}/model/test_predictions.csv)
need+=($V/predictions/pop_{1920,1960,2010}.tif $V/qa/reallocation_qa.csv)
need+=($C/zones/zones_{1920,1960,2010}.tif $C/layers/BUI/{1920,1960,2010}_BUI.tif)
need+=($C/layers/DEM/DEM.tif $C/layers/water_frac/{1920,1960,2010}_water_frac.tif)
need+=($DATA_ROOT/processed/tract/tracts_{1920,1960,2010}.gpkg)
need+=($DATA_ROOT/processed/census_conus/counties_2010.gpkg)
need+=($P/PLURAL_SHP/PLURAL_SHP/plural_indices_scaled_across_years_2010.shp)
need+=($P/PLURAL_CSV/PLURAL_CSV/place_level_remoteness_all_scaled_across_years.csv)
ok=1
for f in "${need[@]}"; do [[ -e $f ]] || { echo "MISSING $f"; ok=0; }; done
echo "checked ${#need[@]} inputs"
$ENVS/hisdac/bin/python -c "import xgboost, catboost, lightgbm; print('env ok | catboost', catboost.__version__)" || ok=0
grep -E '^(version|model|compare_with):|n_iter' configs/conus_{rf,lgbm,xgb,cat}_v3_n60.yaml
if (( ok )); then bash sbatch/submit_conus.sh models; else echo "NOT SUBMITTED: fix the MISSING inputs / env above first"; fi
echo "== end of block 1"
```

Good: no `MISSING` line, `checked 29 inputs`, `env ok | catboost 1.2.8` (or later), per config `version`, `model`
(rf / lgbm / xgb / catboost), `compare_with: Dasy_CONUS_RF_v3_bui`, `n_iter: 60`, then `copied Dasy_CONUS_RF_v3_bui
features ...`, one line `env_check N | validate Dasy_CONUS_RF_v3_bui N | rf train N predict N validate N | lgbm ...
| xgb ... | cat ... | compare_models N | county_maps N` (16 ids, also in `logs/conus_models_jobs.txt`) and
`== end of block 1`. If `== end of block 1` is missing, the paste was cut: run `cat logs/conus_models_jobs.txt` and
`squeue -u $USER` before pasting again (never submit twice).

Block 2, monitor:

```bash
cd /projects/jaju1407/HPC
squeue -u $USER
for j in $(grep -oE '[0-9]{6,}' logs/conus_models_jobs.txt); do f=$(ls logs/*.$j.out 2>/dev/null); [[ -n $f ]] && { echo "== $f"; tail -n 3 "$f"; }; done
echo "== end of block 2"
```

Good: the last lines of the started jobs (`== done ...` when finished) and `== end of block 2`. Check in the logs:
- `test_env_hisdac`: `lightgbm ok: search ...`, `xgboost ok: search ...`, `catboost ok: search ...` (each `top x0`),
  `ENV OK`. If it fails, every other job stays `(DependencyNeverSatisfied)`: `scancel` them and send the log
- `dasymetric_train` (each model, per era): `model <name> | search 60 of continuous candidates | 5 folds`, the
  `search space` line, `best params {...} (search N s)`, `CV RMSE ...`, `TEST ...`, `Dasy_CONUS_RF_v3_bui (its saved
  out-of-fold predictions, same folds ...)`, `DONE`
- `dasymetric_predict`: `mass check: ... 0 fail | bad cells 0`, `DONE`
- `validate_tract` (5): per year `BUI gap counties (floor area per person < 5 % of the median ...): 533 / 479 / 416
  of ...` (1920 / 1960 / 2010), `N evaluated tracts in N gap counties`, `DONE`
- `compare_models`: one table per year (5 versions), `chosen hyperparameters`, `wrote ... model_comparison.csv`,
  `DONE`
- `county_maps`: four `plot ...` lines, `DONE`

Block 3, close the loop (after the last job left `squeue`):

```bash
cd /projects/jaju1407/HPC
ids=$(grep -oE '[0-9]{6,}' logs/conus_models_jobs.txt | paste -sd,)
sacct -j "$ids" --format=JobID,JobName%22,State,Elapsed,MaxRSS,ReqCPUS,TotalCPU > logs/conus_models_sacct.txt
for j in ${ids//,/ }; do seff "$j"; echo; done > logs/conus_models_seff.txt
cat logs/conus_models_sacct.txt
du -sh results/validation/conus/* results/dasymetric/conus/*
git add logs/ results/dasymetric/conus results/validation/conus
git commit -m "run: CONUS model family (RF/LGBM/XGB/CAT n60), v3_bui gap validation, comparison (logs + results)"
git pull --rebase
git push
git log --oneline -1
echo "== end of block 3"
```

Good: `sacct` shows `COMPLETED` for all 16 jobs, `git push` ends with `main -> main`, the last commit is the
`run: CONUS model family ...` one, then `== end of block 3`.

## 5. All census years 1900-2010: Dasy_CONUS_RF_v3_all (2026-10-27)

The CONUS base (RF, v3 features, 60 candidates; `docs/conus_plan.md`, "All census years") for the 12 census years of
Stefan's CSV, one era per year. Everything runs as batch jobs; **no step needs a compute node** (no env change: the
hisdac env of section 4 has everything). One submission of 9 jobs, each waiting for the one before (bui_fix and
water_frac side by side):

| Job | What | Estimate (from the 3-year runs) |
|---|---|---|
| `census_conus` | all 12 years (1920 / 1960 / 2010 rewritten the same) | < 5 min |
| `grid_cutout --years <9 new>` | 1900, 1910, 1930, 1940, 1950, 1970, 1980, 1990, 2000: BUI, BUPL, BUPR, BUA, Land_Use (1940+ only), zones; DEM kept; `cutout_qa.csv` keeps the old years' rows | ~10 min |
| `bui_fix --years <9 new>` | BUI cap on the new years (`bui_fixed_{YEAR}.csv`; the summary keeps the old rows); the fixed 1920 / 1960 / 2010 are not touched | ~2 min |
| `water_frac` | all 12 yearly layers (GDW completion years), so the QA points (1920 / 1960 / 2010) and one QA file stay as before; the 3 old layers come out the same | ~30-45 min |
| features, train, predict | 12 eras; train = 12 searches of 60 candidates | ~15 min, ~1.5-2 h, ~1 h |
| `validate_tract` | 1910-2010 (no tracts in 1900), split parts, density classes, `--gap-share 0.05`, areal weighting | ~20-30 min |
| `compare_models` (summary) | `results/validation/conus/Dasy_CONUS_RF_v3_all/summary_by_year.csv` + `mdape_by_year.png`; repro check against `Dasy_CONUS_RF_v3_n60` | < 1 min |

Block 0, preflight + submit (login node; nothing is submitted if an input is missing or the env fails):

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
source sbatch/cluster_env.sh
C=$HISDAC_SCRATCH/cutouts/conus
D=$HISDAC_SCRATCH/dasymetric/conus
N=$D/Dasy_CONUS_RF_v3_n60
NEW="1900 1910 1930 1940 1950 1970 1980 1990 2000"
need=()
for y in 1900 1910 1920 1930 1940 1950 1960 1970 1980 1990 2000 2010; do need+=($DATA_ROOT/processed/census/counties_$y.gpkg); done
need+=($DATA_ROOT/processed/census/counties_std_2010.gpkg $DATA_ROOT/processed/census/counties_2020.gpkg)
for y in $NEW; do for n in BUI BUPL BUPR BUA; do need+=($HISDAC_DIR/$n/${y}_$n.tif); done; done
for y in 1940 1950 1970 1980 1990 2000; do for c in A C GV I RC RI RO VL; do need+=($HISDAC_DIR/Land_Use/$c/Count_${y}_$c.tif); done; done
need+=($C/window.json $C/layers/DEM/DEM.tif $C/layers/BUI_raw/{1920,1960,2010}_BUI.tif)
need+=($N/Y{1920,1960,2010}/model/oof_predictions.csv $N/Y{1920,1960,2010}/model/test_predictions.csv)
need+=(results/validation/conus/Dasy_CONUS_RF_v3_n60/metrics_by_year.csv)
for y in 1910 1920 1930 1940 1950 1960 1970 1980 1990 2000 2010; do need+=($DATA_ROOT/processed/tract/tracts_$y.gpkg); done
need+=($DATA_ROOT/raw/water/jrc_occurrence $DATA_ROOT/raw/water/gdw/GDW_v1_0_shp/GDW_reservoirs_v1_0.shp)
ok=1
for f in "${need[@]}"; do [[ -e $f ]] || { echo "MISSING $f"; ok=0; }; done
echo "checked ${#need[@]} inputs"
per=$(du -cb $C/layers/*/1960_*.tif $C/layers/Land_Use/*/1960_*.tif $C/zones/zones_1960.* | tail -1 | cut -f1)
echo "cutout: 1960 files $((per / 1000000)) MB -> 9 new years ~$((9 * per / 1000000)) MB"
v=$(du -sb $N | cut -f1)
echo "Dasy_CONUS_RF_v3_n60 (3 years) $((v / 1000000)) MB -> Dasy_CONUS_RF_v3_all (12 years) ~$((4 * v / 1000000)) MB"
r=$(du -cb results/validation/conus/Dasy_CONUS_RF_v3_n60 results/dasymetric/conus/Dasy_CONUS_RF_v3_n60 | tail -1 | cut -f1)
echo "results in git (3 years) $((r / 1000000)) MB -> 12 years ~$((4 * r / 1000000)) MB"
df -h $HISDAC_SCRATCH | tail -1
curc-quota 2>/dev/null | grep -iE "scratch|projects" || true
$ENVS/hisdac/bin/python -c "import sklearn, rasterio, geopandas, shap; print('env ok | sklearn', sklearn.__version__)" || ok=0
grep -E '^(version|compare_with):|^years:' configs/conus_rf_v3_all.yaml configs/conus_study_area.yaml
if (( ok )); then bash sbatch/submit_conus.sh all; else echo "NOT SUBMITTED: fix the MISSING inputs / env above first"; fi
echo "== end of block 0"
```

Good: no `MISSING` line, `checked 123 inputs`, the size lines (cutout ~9 x the 1960 files, v3_all ~4 x v3_n60; the
scratch `df` / `curc-quota` line must show far more free space than their sum), `env ok | sklearn ...`, the
`version` / `years` / `compare_with` lines (`Dasy_CONUS_RF_v3_all`, `{start: 1900, stop: 2010, step: 10}` in both
files, `Dasy_CONUS_RF_v3_n60`), then one line `census_conus N | grid_cutout N | bui_fix N | water_frac N | features N
| train N | predict N | validate N | summary N` (9 ids, also in `logs/conus_all_jobs.txt`) and `== end of block 0`.
If `== end of block 0` is missing, the paste was cut: run `cat logs/conus_all_jobs.txt; squeue -u $USER` before
pasting again (never submit twice).

If a `counties_{YEAR}.gpkg` of `processed/census` is MISSING (NHGIS nominal counties, made for 1810-2020 on
2026-09-29, job 33163853): `conus_counties.py` needs it in every year, because 4 of the 2010 polygons have no CSV row
(Broomfield CO, Miami-Dade FL, Shannon SD, Bedford city VA; 1960: 0.94 M people, 0.5 %; 1920: 45 k) and are filled
from it; without the file the job stops. Do not go on without the fill: rebuild the file (about 5 min,
`sbatch sbatch/census_prepare.sh --years <YEAR>`, `docs/runbooks/Preparing_Census.md`), then rerun block 0.

Block 1, monitor:

```bash
cd /projects/jaju1407/HPC
squeue -u $USER
for j in $(grep -oE '[0-9]{6,}' logs/conus_all_jobs.txt); do f=$(ls logs/*.$j.out 2>/dev/null); [[ -n $f ]] && { echo "== $f"; tail -n 3 "$f"; }; done
echo "== end of block 1"
```

Good: the last lines of the started jobs (`== done ...` when finished) and `== end of block 1`. Check in the logs:
- `census_conus`: 12 years, `filled from NHGIS` lines for the 4 polygons, `DONE`
- `grid_cutout`: `DEM kept (static, already in the cutout ...)`, 9 years of BUI / BUPL / BUPR / BUA, Land_Use for
  1940, 1950, 1970-2000, `zones` for the 9 years, `DONE`
- `bui_fix`: the 9 new years, `years with cells above the cap: [...]`, `DONE`
- `water_frac`: `yearly layers [1900, ..., 2010]`, the 6 QA points `ok`, `wrote 12 yearly layers`, `DONE`
- `dasymetric_features`: 12 eras, `DONE`
- `dasymetric_train`: per era `search 60 of continuous candidates`, `best params`, `CV RMSE`, `TEST`; Y1920 / Y1960
  / Y2010 also `Dasy_CONUS_RF_v3_n60 (its saved out-of-fold predictions, same folds ...)`, the others `compare_with
  Dasy_CONUS_RF_v3_n60 has no era ...`; `DONE`
- `dasymetric_predict`: `mass check by year` (12 rows, `fail` 0), `mass check: ... 0 fail | bad cells 0`, `DONE`
- `validate_tract`: 11 years (1910-2010), `BUI gap counties ...` per year, `DONE`
- `compare_models` (summary): `repro 1920 / 1960 / 2010 vs Dasy_CONUS_RF_v3_n60: ... -> SAME`, one table per year,
  `mass check ...: 0 county-years fail`, `wrote .../mdape_by_year.png`, `DONE`

Block 2, close the loop (after the last job left `squeue`):

```bash
cd /projects/jaju1407/HPC
ids=$(grep -oE '[0-9]{6,}' logs/conus_all_jobs.txt | paste -sd,)
sacct -j "$ids" --format=JobID,JobName%22,State,Elapsed,MaxRSS,ReqCPUS,TotalCPU > logs/conus_all_sacct.txt
for j in ${ids//,/ }; do seff "$j"; echo; done > logs/conus_all_seff.txt
cat logs/conus_all_sacct.txt
du -sh results/census_conus results/cutout/conus results/dasymetric/conus/Dasy_CONUS_RF_v3_all results/validation/conus/Dasy_CONUS_RF_v3_all
git add logs/ results/census_conus results/cutout/conus results/dasymetric/conus/Dasy_CONUS_RF_v3_all results/validation/conus/Dasy_CONUS_RF_v3_all
git commit -m "run: CONUS RF v3 all census years 1900-2010 (logs + results)"
git pull --rebase
git push
git log --oneline -1
echo "== end of block 2"
```

Good: `sacct` shows `COMPLETED` for all 9 jobs, `git push` ends with `main -> main`, the last commit is the `run: CONUS
RF v3 all census years ...` one, then `== end of block 2`.

## 6. Night lights test: Dasy_CONUS_RF_v3_ntl, 2000 / 2010 (2026-10-28)

`Dasy_CONUS_RF_v3_all` + `ntl` for 2000 and 2010 (`docs/conus_plan.md`, "NTL test"): does night light improve the
tract allocation on ~2,500 counties (Massachusetts dropped it on 14)? Same model, 60 candidates, split, folds,
statuses, water mask and strips as v3_all; compared with it on the same CV / TEST rows and tracts. No env change, no
compute node. One submission of 8 jobs:

| Job | What | Estimate (from v3_all, 12 years) |
|---|---|---|
| `grid_cutout --layers NTL` | `layers/NTL/{2000,2010}_NTL.tif` in the existing cutout (Harmonized DN, nearest, int16); nothing else re-cut | ~10 min |
| `ntl_qa` | DN range, Boston box (the old DN >= 60 rule: a 2010 failure is a known rule artifact), NTL-BUI Spearman, lights outside the counties, glow at the coast / border, top counties; **nothing waits for it** | ~10 min |
| features, train, predict | 2 eras (Y2000, Y2010) with 9 features; train = 2 searches of 60 candidates | ~5 min, ~20-30 min, ~10 min |
| `validate_tract` | 2000 / 2010, split parts, density classes, `--gap-share 0.05` | ~5 min |
| `compare_models` | `results/validation/conus/ntl_comparison.csv`: v3_all vs v3_ntl, 2000 / 2010, + ntl rank (permutation, SHAP) | < 1 min |
| `county_maps` | 2010, Chelan WA / Reno KS / Fremont CO / Macoupin IL, v3_all vs v3_ntl -> `results/validation/conus/county_maps_ntl/` (+ `county_maps.csv`: share of people on BUI = 0 cells) | ~5 min |

Block 0, preflight + submit (login node; `submit_conus.sh ntl` checks every input again and submits nothing if one
is missing):

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
source sbatch/cluster_env.sh
ls -l /projects/jaju1407/data/raw/ntl/Harmonized_DN_NTL_{2000,2010}_*.tif
C=$HISDAC_SCRATCH/cutouts/conus
A=$HISDAC_SCRATCH/dasymetric/conus/Dasy_CONUS_RF_v3_all
ls $C/layers/NTL 2>/dev/null && echo "NOTE: layers/NTL exists already (it will be rewritten the same)"
ls -d $A/Y2000/model $A/Y2010/model $A/predictions/pop_2010.tif
df -h $HISDAC_SCRATCH | tail -1
$ENVS/hisdac/bin/python -c "import sklearn, rasterio, shap; print('env ok | sklearn', sklearn.__version__)"
grep -E '^(version|compare_with|years):' configs/conus_rf_v3_ntl.yaml
grep -n 'name: NTL' configs/conus_study_area.yaml
bash sbatch/submit_conus.sh ntl
echo "== end of block 0"
```

Good: one `Harmonized_DN_NTL_2000_*.tif` and one `..._2010_*.tif`, the three v3_all paths listed, `env ok | sklearn
...`, `version: Dasy_CONUS_RF_v3_ntl`, `years: [2000, 2010]`, `compare_with: Dasy_CONUS_RF_v3_all`, the `name: NTL`
line, then one line `ntl_cutout N | ntl_qa N | features N | train N | predict N | validate N | compare N |
county_maps N` (8 ids, also in `logs/conus_ntl_jobs.txt`) and `== end of block 0`. A `MISSING ...` list + `ERROR:
nothing submitted` means an input is gone (scratch purge?): send it to Claude. If `== end of block 0` is missing, the
paste was cut: run `cat logs/conus_ntl_jobs.txt; squeue -u $USER` before pasting again (never submit twice).

Block 1, monitor:

```bash
cd /projects/jaju1407/HPC
squeue -u $USER
for j in $(grep -oE '[0-9]{6,}' logs/conus_ntl_jobs.txt); do f=$(ls logs/*.$j.out 2>/dev/null); [[ -n $f ]] && { echo "== $f"; tail -n 3 "$f"; }; done
echo "== end of block 1"
```

Good: the last lines of the started jobs (`== done ...` when finished) and `== end of block 1`. Check in the logs:
- `grid_cutout`: `--layers ['NTL']: window matches ...`, two `NTL` lines (`warped (nearest)`, min 0, max <= 63), `DONE`
- `ntl_qa`: per year `DN 0..63`, `Spearman ntl~bui`, an `edges:` line and the top counties; `wrote .../ntl_glow_counties.csv`.
  It may end with `ERROR: NTL QA failed: 2010: no cell with DN >= 60 in the box` (the Massachusetts rule artifact):
  expected, nothing waits for it
- `dasymetric_features`: eras Y2000, Y2010 with `ntl` in the feature list, `DONE`
- `dasymetric_train`: per era `search 60 of continuous candidates`, the permutation / SHAP tables (ntl's place),
  `Dasy_CONUS_RF_v3_all (its saved out-of-fold predictions, same folds ...)`, `TEST`, `DONE`
- `dasymetric_predict`: `mass check ... 0 fail`, `DONE`
- `validate_tract`: 2000 / 2010, `BUI gap counties ...`, `DONE`
- `compare_models`: one table per year (v3_all and v3_ntl), `rank of ntl ...`, `wrote .../ntl_comparison.csv`, `DONE`
- `county_maps`: 4 PNGs + `county_maps.csv` in `county_maps_ntl/`, `DONE`

Block 2, close the loop (after the last job left `squeue`):

```bash
cd /projects/jaju1407/HPC
ids=$(grep -oE '[0-9]{6,}' logs/conus_ntl_jobs.txt | paste -sd,)
sacct -j "$ids" --format=JobID,JobName%22,State,Elapsed,MaxRSS,ReqCPUS,TotalCPU > logs/conus_ntl_sacct.txt
for j in ${ids//,/ }; do seff "$j"; echo; done > logs/conus_ntl_seff.txt
cat logs/conus_ntl_sacct.txt
du -sh results/cutout/conus results/dasymetric/conus/Dasy_CONUS_RF_v3_ntl results/validation/conus/Dasy_CONUS_RF_v3_ntl results/validation/conus/county_maps_ntl
git add logs/ results/cutout/conus results/dasymetric/conus/Dasy_CONUS_RF_v3_ntl results/validation/conus/Dasy_CONUS_RF_v3_ntl results/validation/conus/ntl_comparison.csv results/validation/conus/county_maps_ntl
git commit -m "run: CONUS RF v3 + night lights 2000/2010 (logs + results)"
git pull --rebase
git push
git log --oneline -1
echo "== end of block 2"
```

Good: `sacct` shows `COMPLETED` for 7 jobs (`ntl_qa` may be `FAILED` on the DN >= 60 rule: fine, its CSVs are
copied anyway), `git push` ends with `main -> main`, the last commit is the `run: CONUS RF v3 + night lights ...`
one, then `== end of block 2`.

## 7. VIIRS-like night lights: Dasy_CONUS_RF_v3_ntlv, 2000 / 2010 (2026-10-28)

The DMSP `ntl` of section 6 halved the tract error in BUI gap counties but raised it elsewhere (glow on empty land;
`docs/conus_plan.md`, "NTL test result"). Same test with the VIIRS-like NTL of Chen et al. (2021, Version1, 15
arc-seconds, radiance; `docs/data_sources.md`): `Dasy_CONUS_RF_v3_ntlv` = v3_ntl with `ntlv` instead of `ntl`,
compared with v3_all and v3_ntl (`docs/conus_plan.md`, "VIIRS-like NTL test"). No env change.

| Job | What | Estimate (from section 6) |
|---|---|---|
| `ntlv_download.sh` (login node, not a job) | Dataverse API -> file ids + md5 -> `2000_Version1.zip`, `2010_Version1.zip` (59 + 79 MB) -> `viirs_like/v1/{2000,2010}/` | a few min |
| `ntlv_check` (`sbatch --wait`) | CRS, cell size, value range, nodata, sea mask (sample points), coverage of the CONUS window -> `results/cutout/conus/ntlv_check.csv` | ~2 min |
| `grid_cutout --layers NTLV` | `layers/NTLV/{2000,2010}_NTLV.tif` (float32, nearest; sea mask -> 0, counted inside the counties); nothing else re-cut | ~5 min |
| `ntl_qa --layer NTL NTLV` | both layers side by side: range, box (DMSP: DN >= 60 rule, may fail again; VIIRS-like: p99 of lit cells, warning only), Spearman, edge / interior lit share and glow of BUI = 0 cells (`ntl_edges_compare.csv`); **nothing waits for it** | ~5 min |
| features, train, predict | 2 eras (Y2000, Y2010), 9 features, 2 x 60 candidates | ~6, ~20, ~11 min |
| `validate_tract` | 2000 / 2010, split parts, density classes, `--gap-share 0.05` | ~7 min |
| `compare_models` | `results/validation/conus/ntl_viirs_comparison.csv`: v3_all / v3_ntl / v3_ntlv, 2000 / 2010, tract MdAPE gap / no_gap / density classes, rank of ntl and ntlv | < 1 min |
| `county_maps` | 2010, Chelan WA, Reno KS, Fremont CO, Macoupin IL (BUI gap), DuPage IL (BUI gap); v3_all / v3_ntl / v3_ntlv -> `results/validation/conus/county_maps_ntlv/` (+ `county_maps.csv`: share of people on BUI = 0 cells) | ~3 min |

Block 0, download + check (login node; the check is a small job, `--wait` returns when it ends):

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs
bash sbatch/ntlv_download.sh
ls -l /projects/jaju1407/data/raw/ntl/viirs_like/v1/2000 /projects/jaju1407/data/raw/ntl/viirs_like/v1/2010
sbatch --wait sbatch/ntlv_check.sh; echo "ntlv_check exit code $?"
f=$(ls -t logs/ntlv_check.*.out | head -1); echo "== $f"; tail -n 32 "$f"
echo "== end of block 0"
```

Good: `Dataverse API reached: dataset version ... | license CC0 1.0`, `2000_Version1.zip: md5 ok` and the same for
2010, one `.tif` per year folder (no `WARNING`), `ntlv_check exit code 0`, and in the check log per year `EPSG:4326 |
cell 0.004167 deg = 15.00 arc-sec`, `covers the window: True`, the window box counts, the sample points (sea / lake:
`nodata` or `0`, cities: large values), `DONE`, then `== end of block 0`. A nonzero exit code or an `ERROR` line:
send the output to Claude and do not go on to block 1.

If the download fails (`curl: (6)`, `(7)`, `(28)`, or `ERROR: ... md5`), get the two files on the laptop instead:
open https://doi.org/10.7910/DVN/YGIVCD, folder `Version1`, download `2000_Version1.zip` and `2010_Version1.zip`.
Upload them to `/projects/jaju1407/data/raw/ntl/viirs_like/v1/` with the OnDemand Files app
(https://ondemand.rc.colorado.edu -> Files -> Upload), or from the laptop's PowerShell through the data-transfer node:

```powershell
scp $HOME\Downloads\2000_Version1.zip $HOME\Downloads\2010_Version1.zip jaju1407@dtn.rc.colorado.edu:/projects/jaju1407/data/raw/ntl/viirs_like/v1/
```

Good: both files listed at 100 %. Then run block 0 again: the script finds the zips, checks their md5 and only unpacks.

Block 1, preflight + submit (login node; `submit_conus.sh ntlv` checks every input again and submits nothing if one
is missing):

```bash
cd /projects/jaju1407/HPC
source sbatch/cluster_env.sh
C=$HISDAC_SCRATCH/cutouts/conus
D=$HISDAC_SCRATCH/dasymetric/conus
ls $C/layers/NTLV 2>/dev/null && echo "NOTE: layers/NTLV exists already (it will be rewritten the same)"
ls -d $C/layers/NTL/2000_NTL.tif $C/layers/NTL/2010_NTL.tif $D/Dasy_CONUS_RF_v3_all/predictions/pop_2010.tif $D/Dasy_CONUS_RF_v3_ntl/predictions/pop_2010.tif
cut -d, -f1,3,6,7,9,14 results/cutout/conus/ntlv_check.csv
df -h $HISDAC_SCRATCH | tail -1
grep -E '^(version|compare_with|years):' configs/conus_rf_v3_ntlv.yaml
grep -n 'name: NTLV' configs/conus_study_area.yaml
bash sbatch/submit_conus.sh ntlv
echo "== end of block 1"
```

Good: the four paths listed, the check table (`year,crs,dtype,nodata,cell_arcsec,covers_window` with `EPSG:4326`,
`15.0`, `True` for 2000 and 2010), `version: Dasy_CONUS_RF_v3_ntlv`, `years: [2000, 2010]`, `compare_with:
Dasy_CONUS_RF_v3_all`, the `name: NTLV` line, then one line `ntlv_cutout N | ntl_qa N | features N | train N |
predict N | validate N | compare N | county_maps N` (8 ids, also in `logs/conus_ntlv_jobs.txt`) and `== end of block
1`. A `MISSING ...` list + `ERROR: nothing submitted` means an input is gone (scratch purge?) or block 0 did not
finish: send it to Claude. If `== end of block 1` is missing, the paste was cut: run `cat logs/conus_ntlv_jobs.txt;
squeue -u $USER` before pasting again (never submit twice).

Block 2, monitor:

```bash
cd /projects/jaju1407/HPC
squeue -u $USER
for j in $(grep -oE '[0-9]{6,}' logs/conus_ntlv_jobs.txt); do f=$(ls logs/*.$j.out 2>/dev/null); [[ -n $f ]] && { echo "== $f"; tail -n 3 "$f"; }; done
echo "== end of block 2"
```

Good: the last lines of the started jobs (`== done ...` when finished) and `== end of block 2`. Check in the logs:
- `grid_cutout`: `--layers ['NTLV']: window matches ...`, per year `nodata_to 0: N nodata cells set to 0 (M of them
  inside the ... zones)` (only when the sea is stored as nodata) and an `NTLV` line (`warped (nearest)`, min >= 0), `DONE`
- `ntl_qa`: per layer and year the range, box and `edges` lines, the `edges side by side` table, `wrote
  .../ntl_edges_compare.csv`. It may end with `ERROR: NTL QA failed: NTL 2010: no cell with DN >= 60 in the box` (the
  known DMSP rule artifact): expected; any `NTLV ...` line in that error is not
- `dasymetric_features`: eras Y2000, Y2010 with `ntlv` in the feature list, `DONE`
- `dasymetric_train`: per era `search 60 of continuous candidates`, the permutation / SHAP tables (ntlv's place),
  `Dasy_CONUS_RF_v3_all (its saved out-of-fold predictions, same folds ...)`, `TEST`, `DONE`
- `dasymetric_predict`: `mass check ... 0 fail`, `DONE`
- `validate_tract`: 2000 / 2010, `BUI gap counties ...`, `DONE`
- `compare_models`: one table per year (v3_all, v3_ntl, v3_ntlv), `tract MdAPE (%) by part`, `rank of ntl ...`,
  `rank of ntlv ...`, `wrote .../ntl_viirs_comparison.csv`, `DONE`
- `county_maps`: 5 PNGs + `county_maps.csv` in `county_maps_ntlv/`, `DONE`

Block 3, close the loop (after the last job left `squeue`):

```bash
cd /projects/jaju1407/HPC
ids=$(grep -oE '[0-9]{6,}' logs/conus_ntlv_jobs.txt | paste -sd,)
sacct -j "$ids" --format=JobID,JobName%22,State,Elapsed,MaxRSS,ReqCPUS,TotalCPU > logs/conus_ntlv_sacct.txt
for j in ${ids//,/ }; do seff "$j"; echo; done > logs/conus_ntlv_seff.txt
cat logs/conus_ntlv_sacct.txt
du -sh results/cutout/conus results/dasymetric/conus/Dasy_CONUS_RF_v3_ntlv results/validation/conus/Dasy_CONUS_RF_v3_ntlv results/validation/conus/county_maps_ntlv
git add logs/ results/cutout/conus results/dasymetric/conus/Dasy_CONUS_RF_v3_ntlv results/validation/conus/Dasy_CONUS_RF_v3_ntlv results/validation/conus/ntl_viirs_comparison.csv results/validation/conus/county_maps_ntlv
git commit -m "run: CONUS RF v3 + VIIRS-like night lights 2000/2010 (logs + results)"
git pull --rebase
git push
git log --oneline -1
echo "== end of block 3"
```

Good: `sacct` shows `COMPLETED` for 7 jobs (`ntl_qa` may be `FAILED` on the DMSP DN >= 60 rule only: fine, its CSVs
are copied anyway), `git push` ends with `main -> main`, the last commit is the `run: CONUS RF v3 + VIIRS-like ...`
one, then `== end of block 3`.

## 8. External gridded population products vs v5.4 on the same tracts (2026-10-28)

How good is v5.4 (= `Dasy_CONUS_RF_v3_all`) next to published population grids, on the same tracts with the same
metrics (`docs/conus_plan.md`, "External comparison"; request `docs/handoff/external_grids_request.md`)? Products and
years: `configs/external_grids.yaml`; sources, licenses and each product's US input unit: `docs/data_sources.md`. The
products are summed per tract in their own CRS (exactextract, no reprojection or resampling of the rasters); v5.4 and
areal weighting are taken from `tract_errors_{YEAR}.csv` on the same tracts. Env change: `exactextract`, `py7zr`,
`openpyxl` (block 1a).

| Step | Where | What | Estimate |
|---|---|---|---|
| env update | `sinteractive` (acompile) | three packages added to `envs/hisdac/environment.yml` | 5-15 min |
| `.netrc` (once, optional) | login node | NASA Earthdata login for GPW v4.11 and GRUMP v1; without it both are skipped | 1 min |
| `external_download.sh` | login node, not a job | GHS-POP 4 x 4.2-5.1 GB, WorldPop 2 x 4.0 GB (size checked), Fang & Jawitz 602 MB (md5) + unpack, GPW 2 x 405 MB + GRUMP 2 x ~280 MB (zip checked) + GPW / GRUMP documents -> `$DATA_ROOT/raw/external/` (~27 GB) | 20-90 min (network) |
| inventory | login node | per product and year: the file found, CRS, cell size, nodata, bounds; USA rows of the GPWv4 country summary -> `results/validation/conus/external/external_inventory.csv` | seconds |
| `extract` x product | jobs, no dependency | tract sums per year -> `$HISDAC_SCRATCH/external/conus/sums/<product>_<year>.csv` | GHS-POP / WorldPop: unknown (100 m, 46-72k tracts per year; 16 cores, 6 h / 4 h wall); 1 km products: minutes |
| `evaluate` | after all extract jobs (`afterany`) | `external_comparison.csv` (product x year x method) + `external_mdape_by_year.png`; a product without sums is a `missing` row | minutes |

Block 1a, env update (login node, then the compile node):

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
sinteractive --partition=acompile --qos=compile --ntasks=4 --time=01:00:00
```

Then, inside `sinteractive` (the prompt shows a compute node):

```bash
export USER=jaju1407
export TMPDIR=/scratch/alpine/jaju1407/tmp
mkdir -p "$TMPDIR"
eval "$(/projects/jaju1407/software/miniforge3/bin/conda shell.bash hook)"
cd /projects/jaju1407/HPC/envs/hisdac
conda env update -f environment.yml -p /projects/jaju1407/software/envs/hisdac --prune
conda activate /projects/jaju1407/software/envs/hisdac
python -c "import exactextract, py7zr, openpyxl, rasterio, geopandas; print('ENV UPDATED | exactextract', exactextract.__version__, '| py7zr', py7zr.__version__, '| openpyxl', openpyxl.__version__)"
cd /projects/jaju1407/HPC
echo "== end of block 1a"
exit
```

Good: one line `ENV UPDATED | exactextract 0.x | py7zr 1.x | openpyxl 3.x`, `== end of block 1a`, and `exit` returns
to the login node. A traceback: stop and send it to Claude.

Earthdata login (once, optional; login node). An account from https://urs.earthdata.nasa.gov/users/new. This asks for
the user name and password (the password is not shown and does not go into the shell history), so paste it alone:

```bash
read -p "Earthdata user name: " EDU; read -s -p "Earthdata password: " EDP; echo
printf 'machine urs.earthdata.nasa.gov login %s password %s\n' "$EDU" "$EDP" >> ~/.netrc; chmod 600 ~/.netrc; unset EDP
grep -c urs.earthdata.nasa.gov ~/.netrc
```

Good: the last line prints `1`. Without an account skip this: GPW v4.11 and GRUMP v1 are then left out and everything
else runs.

Block 1b, download + check (login node; the download takes a while, keep the terminal open; a broken run resumes when
the block is pasted again):

```bash
cd /projects/jaju1407/HPC
git log --oneline -1
mkdir -p logs
f=logs/external_download.$(date +%Y%m%d_%H%M).log
bash sbatch/external_download.sh 2>&1 | tee "$f"; echo "download exit code ${PIPESTATUS[0]}"
bash sbatch/external_compare.sh inventory 2>&1 | tail -n 45
echo "== end of block 1"
```

Good: `download exit code 0`; in the summary `ghs_pop: ok`, `worldpop: ok`, `fang_jawitz: ok`, and `gpw4: ok` /
`grump1: ok` (or `skipped` without `.netrc`); the Fang & Jawitz listing shows `pop_m3_*` and `pop_m5_*` folders; the
inventory ends with `products with all files: ghs_pop worldpop gpw4 grump1 fj_m3 fj_m5` (fewer without `.netrc`),
`wrote .../external_inventory.csv`, `DONE`, then `== end of block 1`. Exit code 1 or `ERROR:` lines: the summary says
which product; the others are fine and block 2 can still run (it submits only products with all files), but send the
log `logs/external_download.*.log` to Claude with the block 3 commit. If the GPWv4 country summary was downloaded, the
inventory also prints its USA rows (the US input unit): keep them in the log.

Block 2, preflight + submit (login node; nothing is submitted if an input or a package is missing):

```bash
cd /projects/jaju1407/HPC
source sbatch/cluster_env.sh
ls $DATA_ROOT/processed/tract/tracts_{1910,1920,1930,1940,1950,1970,1980,1990,2000,2010}.gpkg | wc -l
ls results/validation/conus/Dasy_CONUS_RF_v3_all/tract_errors_{1910,1920,1930,1940,1950,1970,1980,1990,2000,2010}.csv | wc -l
df -h $HISDAC_SCRATCH | tail -1
bash sbatch/submit_conus.sh external
squeue -u $USER
echo "== end of block 2"
```

Good: `10` and `10`, then one line `extract_ghs_pop N | extract_worldpop N | ... | evaluate N` (also in
`logs/conus_external_jobs.txt`), `== not downloaded (skipped): ` (empty, or `gpw4 grump1` without `.netrc`), the jobs in
`squeue`, then `== end of block 2`. `MISSING ...` + `ERROR: nothing submitted`: send it to Claude. If `== end of block
2` is missing, the paste was cut: run `cat logs/conus_external_jobs.txt; squeue -u $USER` before pasting again (never
submit twice). The jobs need no attention: a failed extract job only turns that product into `missing` rows.

Block 3, close the loop (later, after the last job left `squeue`; evaluate starts after all extract jobs end):

```bash
cd /projects/jaju1407/HPC
squeue -u $USER
ids=$(grep -oE '[0-9]{6,}' logs/conus_external_jobs.txt | paste -sd,)
sacct -j "$ids" --format=JobID,JobName%22,State,Elapsed,MaxRSS,ReqCPUS,TotalCPU > logs/conus_external_sacct.txt
for j in ${ids//,/ }; do seff "$j"; echo; done > logs/conus_external_seff.txt
cat logs/conus_external_sacct.txt
ls -l results/validation/conus/external/
git add logs/ results/validation/conus/external
git commit -m "run: external gridded population products vs v5.4 on tracts (logs + results)"
git pull --rebase
git push
git log --oneline -1
echo "== end of block 3"
```

Good: `squeue` shows no `external_*` job; `sacct` lists every job of `conus_external_jobs.txt` with `COMPLETED` (an
extract job `FAILED` / `TIMEOUT` is allowed: its product is `missing` in the table; `evaluate` must be `COMPLETED`);
`external_comparison.csv`, `external_mdape_by_year.png` and `external_inventory.csv` listed; `git push` ends with
`main -> main`; the last commit is the `run: external ...` one; then `== end of block 3`. If jobs are still in
`squeue`, wait and paste the block again later.

What to look for in the logs (Claude reads them after the pull):
- `extract`: per year the raster header, `N tracts: ... fully inside the raster, ... with nodata pixels ...`, the
  product's population in the tracts vs the census, `DONE`
- `evaluate`: per product and year `kept / left out` (outside the raster, nodata pixels: e.g. coastal tracts that reach
  over the sea), the MdAPE table (product, v5.4 and areal weighting on the same tracts), the MAPE / p90 / gap / density
  table, `missing (skipped): ...` for products without sums, `DONE`

## 9. County MdAPE and fixed tract sets for v5.4 (2026-10-30)

County MdAPE (TEST and CV counties, model before allocation) and tract MdAPE on fixed county sets (counties tracted in
every year from 1910 / 1920 / 1940 / 1960 on) next to all tracts, by year (`docs/conus_plan.md`, "Metrics over
time"; request `docs/handoff/validation_2020_uncertainty_request.md`, part A). No job is needed for 1900-2010:
`src/validation/metrics_over_time.py` reads only tracked result files and was run on the laptop (results committed in
`results/validation/conus/Dasy_CONUS_RF_v3_all/`). The 2020 chain (section 10) runs it again as a job
(`sbatch/metrics_over_time.sh`) so 2020 is included. To rerun it alone (login node, then a light job):

```bash
cd /projects/jaju1407/HPC
git pull
mkdir -p logs
sbatch sbatch/metrics_over_time.sh --version Dasy_CONUS_RF_v3_all
echo "== end of block 9"
```

Good: `Submitted batch job N`, then `== end of block 9`. In its log: `recomputed R2 = reported TEST R2 / pooled OOF R2
in all N rows`, `all-tracts MdAPE vs metrics_by_year.csv: max |difference| ...e-15`, `DONE`.

## 10. 2020 added to v5.4 (Dasy_CONUS_RF_v3_all, era Y2020) (2026-10-30)

2020 from the NHGIS 2020 counties on the 2010 polygons, the same model settings as the other years
(`docs/conus_plan.md`, "2020"). Only 2020 is computed (`--years 2020`); 1900-2010 stay as they are and are checked in
block 3. Tract validation, `summary_by_year.csv` / `mdape_by_year.png` and section 9's metrics are redone for
1900-2020.

| Step | Job | What | Estimate (from v3_all, jobs 34939345-34939353) |
|---|---|---|---|
| pre-check | login node, not a job | inputs for 2020 + the v3_all outputs on scratch; Land_Use 2020 vs 2015 | 2-5 min |
| census_conus | `census_conus.sh --years 2020` | NHGIS 2020 on the 2010 polygons -> `counties_2020.gpkg`, `results/census_conus/counties_2020_nhgis_match.csv` | 2 min |
| grid_cutout | `--years 2020` | BUI / BUPL / BUPR / BUA / Land_Use 2020 + zones 2020 | 3 min |
| bui_fix, water_frac | `--years 2020`; water all 13 years | BUI cap; GDW yearly water (old layers deterministic) | 1 min; 15 min |
| features / train / predict | `--years 2020` | Y2020 era (60 candidates) + 2020 map | 2 / 10 / 5 min |
| validate | 1910-2020 | `metrics_by_year.csv`, `tract_errors_2020.csv` (old years must come out the same) | 15 min |
| summary, metrics_over_time | after validate | `summary_by_year.csv`, `mdape_by_year.png`, section 9's files with 2020 | 1 min each |

Block 1, pre-check (login node):

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs
bash sbatch/y2020_precheck.sh 2>&1 | tee logs/y2020_precheck.txt | tail -n 45
echo "== end of block 1"
```

Good: every line `ok`, NHGIS 2020 `3108 counties`, Connecticut `8 units` (G0900010 ... G0900150, the old
counties, not planning regions), `G4601020` present and `G4601130` / `G5105150` `not in 2020`, the eight Land_Use lines `differs from 2015`,
then `PRECHECK OK` and `== end of block 1`. **Stop and send the output to Claude** (do not run block 2) if any line says
`MISSING`, `PRECHECK FAILED`, Connecticut has 9 units, or a Land_Use class is `IDENTICAL to 2015` or missing: then the
Land_Use rule for 2020 has to be decided first (`docs/conus_plan.md`, "2020", Land_Use 2020).

Block 2, submit (login node; nothing is submitted if an input is missing):

```bash
cd /projects/jaju1407/HPC
bash sbatch/submit_conus.sh y2020
squeue -u $USER
echo "== end of block 2"
```

Good: one line `census_conus N | grid_cutout N | bui_fix N | water_frac N | features N | train N | predict N |
validate N | summary N | metrics_over_time N` (also in `logs/conus_y2020_jobs.txt`), 10 jobs in `squeue`, then `==
end of block 2`. `MISSING ...` + `ERROR: nothing submitted`: send it to Claude. If `== end of block 2` is missing, the
paste was cut: run `cat logs/conus_y2020_jobs.txt; squeue -u $USER` before pasting again (never submit twice).

Block 3, close the loop (after the last job left `squeue`; ~1 h): sacct / seff, the reproducibility check of
1900-2010, commit.

```bash
cd /projects/jaju1407/HPC
squeue -u $USER
ids=$(grep -oE '[0-9]{6,}' logs/conus_y2020_jobs.txt | paste -sd,)
sacct -j "$ids" --format=JobID,JobName%22,State,Elapsed,MaxRSS,ReqCPUS,TotalCPU > logs/conus_y2020_sacct.txt
for j in ${ids//,/ }; do seff "$j"; echo; done > logs/conus_y2020_seff.txt
cat logs/conus_y2020_sacct.txt
R=results/dasymetric/conus/Dasy_CONUS_RF_v3_all; Q=results/validation/conus/Dasy_CONUS_RF_v3_all
if git diff --quiet -- $R/Y19?0 $R/Y2000 $R/Y2010 $Q/tract_errors_19?0.csv $Q/tract_errors_2000.csv $Q/tract_errors_2010.csv; then echo "REPRO OK: 1900-2010 model files and tract errors unchanged"; else echo "REPRO DIFFERS:"; git diff --stat -- $R/Y19?0 $R/Y2000 $R/Y2010 $Q/tract_errors_19?0.csv $Q/tract_errors_2000.csv $Q/tract_errors_2010.csv; fi
for f in $R/cv_summary.csv $R/reallocation_qa.csv $R/water_mask_by_year.csv $Q/metrics_by_year.csv $Q/summary_by_year.csv results/census_conus/counties_conus_summary.csv; do echo "$f: $(git diff -U0 -- $f | grep -c '^-[^-]') old lines changed (must be 0)"; done
git add logs/ results/
git commit -m "run: 2020 added to Dasy_CONUS_RF_v3_all (logs + results)"
git pull --rebase
git push
git log --oneline -1
echo "== end of block 3"
```

Good: no `census_conus` ... `metrics_over_time` job left in `squeue`; every job `COMPLETED` in `sacct`; `REPRO OK:
1900-2010 model files and tract errors unchanged`; six lines ending `0 old lines changed (must be 0)`; `git push`
ends with `main -> main`; then `== end of block 3`. `REPRO DIFFERS` or a count above 0: still commit and push (the
diff is the evidence), and tell Claude. If jobs are still in `squeue`, wait and paste the block again later.

What to look for in the logs (Claude reads them after the pull):
- `census_conus`: `Connecticut units 8`, the match rules (`same_code` 3,106-3,107, `remapped` 1, `merged_into` 1),
  statuses, the polygons not matched 1:1, no `not allocated` warning, the area-ratio range
- `train`: `era Y2020`, 60 candidates, `compare_with ... has no era Y2020`, TEST R2; `--years: cv_summary.csv keeps
  the rows of eras [...]` (12 eras)
- `predict`: `--years: reallocation_qa.csv keeps ... rows of years [1900 ... 2010]`, mass check 0 fail
- `compare_models`: the 2020 row; `metrics_over_time`: the fixed sets now need 2020 tracts too

## 11. HISDAC record uncertainty: share of records without a built year (2026-10-30)

Share of property records without a built year per county, compared with the BUI gap counties, and tables of how many
counties / people remain at each threshold (`docs/conus_plan.md`, "HISDAC record uncertainty"). Diagnosis only;
independent of section 10. Ratios (column names say the definition):

- `ratio_A_contemp = (BUPR_contemp - BUPR_2015) / BUPR_contemp`: needs `BUPR_contemp.tif`.
- `ratio_A_nby = NobuiltYear / (BUPR_2015 + NobuiltYear)` (+ `ratio_A_nby_2020` with BUPR_2020): the same share from
  NobuiltYear; needs NobuiltYear to be a count.
- `ratio_B_<year> = NobuiltYear / (BUPR_year + NobuiltYear)` per census year (upper bound); needs a count.

**Status 2026-10-30:** block 1 ran 2026-10-29: `BUPR_contemp.tif` is **not** in the Dataverse BUPR.tar
(`logs/hisdac_extra_download.txt`, `results/hisdac_uncertainty/BUPR.tar_members.txt`); its location is asked of Stefan.
The job runs without it (`ratio_A_nby` + `ratio_B`): **skip block 1, go to block 2.** If NobuiltYear turns out to be a 0/1
flag, no ratio can be computed without contemp; the job then writes only the value distribution and still ends
`COMPLETED` (exit 0). When the file turns up, put it at `/projects/jaju1407/data/raw/hisdac_extra/BUPR_contemp.tif` and
run blocks 2-3 again: `ratio_A_contemp` is added and compared with `ratio_A_nby`.

| Step | Where | What | Estimate |
|---|---|---|---|
| download | login node in tmux, not a job | Dataverse file listing; `BUPR_contemp.tif` alone, or the BUPR archive to scratch and only that file unpacked -> `$DATA_ROOT/raw/hisdac_extra/` | ran 2026-10-29 (archive 660 MB, 12 s; no contemp in it) |
| record_uncertainty | job, 2 cores, 2 h wall | NobuiltYear value pass, then grid / cell checks, county ratios, gap comparison, threshold tables + figure -> `results/hisdac_uncertainty/` | 20-40 min (NobuiltYear + 15 CONUS rasters read in strips; estimate) |

Block 1, download (done 2026-10-29; only again if Stefan names a new Dataverse source and the script is changed for
it). Login node, inside tmux so a dropped connection does not stop it:

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
tmux new -s hisdac_dl
```

Then, inside tmux:

```bash
cd /projects/jaju1407/HPC
mkdir -p logs
bash sbatch/hisdac_extra_download.sh 2>&1 | tee logs/hisdac_extra_download.txt | tail -n 40
echo "== end of block 1"
```

Good: the file table of the dataset, then either `BUPR_contemp.tif is a file of its own` or `archive BUPR... ` +
`md5 ok` + `unpacking only .../BUPR_contemp.tif`, then `== raster: 18459 x 11615 ...` (or another size: that is
checked in block 2), `DOWNLOAD OK` and `== end of block 1`. Leave tmux with `exit` when it is done (if the connection
drops: log in again and `tmux attach -t hisdac_dl`). `ERROR:` (no such file, md5 mismatch, a 403 for a restricted
file): send `logs/hisdac_extra_download.txt` to Claude.

Block 2, submit (login node):

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs
bash sbatch/submit_conus.sh uncertainty
squeue -u $USER
echo "== end of block 2"
```

Good: `BUPR_contemp not found (...): NobuiltYear only ...` (or `BUPR_contemp found ...`), then `record_uncertainty N`
(also in `logs/conus_uncertainty_jobs.txt`), the job in `squeue`, `== end of block 2`. `MISSING ...`: send it to Claude.

Block 3, close the loop (after the job left `squeue`):

```bash
cd /projects/jaju1407/HPC
squeue -u $USER
j=$(grep -oE '[0-9]{6,}' logs/conus_uncertainty_jobs.txt)
sacct -j "$j" --format=JobID,JobName%22,State,Elapsed,MaxRSS,ReqCPUS,TotalCPU | tee logs/conus_uncertainty_sacct.txt
seff "$j" > logs/conus_uncertainty_seff.txt; cat logs/conus_uncertainty_seff.txt
grep -E "NobuiltYear: max|outcome|DONE" logs/record_uncertainty.$j.out
ls -l results/hisdac_uncertainty/
git add logs/ results/hisdac_uncertainty
git commit -m "run: HISDAC record uncertainty (logs + results)"
git pull --rebase
git push
git log --oneline -1
echo "== end of block 3"
```

Good: `record_uncertainty` `COMPLETED`; the grep shows `NobuiltYear: max ... -> a COUNT ...` (or `a 0/1 FLAG`) and a
`DONE` line; with a count the folder lists `county_record_uncertainty.csv`, `threshold_table.csv`,
`threshold_counties.png`, `grid_check.csv`, `cell_check.csv`, `nobuilt_values.csv` and the gap files (with a flag and no
contemp: only `nobuilt_values.csv`, `grid_check.csv`, `cell_check.csv`); `git push` ends with `main -> main`;
`== end of block 3`.

What to look for in the log: `BUPR_contemp not found` (expected now), the grid line of each raster (`direct` or
`WarpedVRT nearest onto the zones`), `NobuiltYear: max ... -> a COUNT ...` or `a 0/1 FLAG`, `C3 ratio_A_nby` quantiles,
`ratio_A_nby 2015 vs 2020` (difference and counties above each threshold), the C4 overlap and the C5 tables, `DONE`.
With contemp also: the cell check (d == NobuiltYear share, d < 0 cells, `cells_a_*`), counties with contemp <
BUPR_2015, `ratio_A_contemp vs ratio_A_nby`.

## 12. Uncertainty filter sensitivity: u090 / u070 / u050 vs v5.4 (2026-10-30)

Counties with unreliable HISDAC records left out of training and testing, allocated by the model of the others
(`docs/conus_plan.md`, "Uncertainty filter"). Three thresholds on `ratio_A_nby` (0.9 / 0.7 / 0.5) plus two fixed rules
(records / area missing), 1920 / 1960 / 2010 / 2020, compared with v5.4 on the same county sets. Needs the results of
section 11 (`results/hisdac_uncertainty/county_record_uncertainty.csv`, in git) and v5.4 (section 5 + 10).

| Step | Job | What | Estimate |
|---|---|---|---|
| uncertainty_filter | 1 core, 30 min wall | BUI_2015 county sums, the three rules -> `results/hisdac_uncertainty/excluded_counties_t{090,070,050}.csv` + summaries | a few minutes |
| features (x3) | 6 cores, 45 min | county features of the 4 years (same as v5.4's) | ~6 min each |
| train (x3) | 16 cores, 2 h | per year: search (60) + fit without the excluded counties, TEST score, `excluded_predictions.csv` | ~35 min each |
| predict (x3) | 32 cores, 1 h | allocation of every county (excluded ones included), map 2010 | ~16 min each |
| validate (x3) | 8 cores, 1 h | tracts 1920 / 1960 / 2010 / 2020 | ~5 min each |
| filter_compare | 1 core, 15 min | `results/validation/conus/uncertainty_filter/` + the rule line | < 1 min |

The three versions run side by side; the whole chain ~1-1.5 h after the jobs start (estimates). Override a wall time:
`FILTER_TIME`, `FEATURES_TIME`, `TRAIN_TIME`, `PREDICT_TIME`, `VALIDATE_TIME`.

Block 1, pre-check + submit (login node):

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs
bash sbatch/submit_conus.sh uncfilter
squeue -u $USER
echo "== end of block 1"
```

Good: `PRECHECK: 0 missing ...`, then one line `uncertainty_filter N | u090 features ... | ... | filter_compare N` (also in
`logs/conus_uncfilter_jobs.txt`), 14 jobs in `squeue`, `== end of block 1`. `MISSING ...` + `ERROR: nothing
submitted`: send the output to Claude (nothing was submitted).

Block 2, progress (login node, any time):

```bash
cd /projects/jaju1407/HPC
ids=$(grep -oE '[0-9]{6,}' logs/conus_uncfilter_jobs.txt | paste -sd,)
sacct -j "$ids" -X --format=JobID,JobName%22,State,Elapsed,ReqCPUS
f=$(ls -t logs/uncertainty_filter.*.out 2>/dev/null | head -1); [[ -n $f ]] && grep -E "records rule|area rule|NOTE|t = 0" "$f"
echo "== end of block 2"
```

Good: states `PENDING` / `RUNNING` / `COMPLETED`, and once the first job is done its lines (`records rule: median ...`,
`area rule: ...`, the even / odd `NOTE`, one `t = 0.x` line per threshold) and `== end of block 2`. A `FAILED` job:
the later ones stay `PENDING (DependencyNeverSatisfied)`; `scancel` them and send the log to Claude.

Block 3, close the loop (after every job left `squeue`):

```bash
cd /projects/jaju1407/HPC
squeue -u $USER
ids=$(grep -oE '[0-9]{6,}' logs/conus_uncfilter_jobs.txt | paste -sd,)
sacct -j "$ids" --format=JobID,JobName%22,State,Elapsed,MaxRSS,ReqCPUS,TotalCPU > logs/conus_uncfilter_sacct.txt
for j in ${ids//,/ }; do seff "$j"; echo; done > logs/conus_uncfilter_seff.txt
cat logs/conus_uncfilter_sacct.txt
grep -h "RULE RESULT" logs/filter_compare.*.out | tail -1
git add logs/ results/
git commit -m "run: uncertainty filter u090 / u070 / u050 (logs + results)"
git pull --rebase
git push
git log --oneline -1
echo "== end of block 3"
```

Good: every job `COMPLETED`, one `RULE RESULT: ...` line (the rule's pick; the decision is yours), `git push` ends with
`main -> main`, `== end of block 3`.

What to look for in the logs: `uncertainty_filter` (rule medians, counties per rule, pop kept, sets nested: True),
`train` (`exclude_counties: N rows left out ...`, CV / TEST vs v5.4 on the same rows, `excluded counties ... RMSE`),
`predict` (mass preserved as before), `filter_compare` (the (a) / (b) set sizes per year, MdAPE table, selection, `DONE`).

## 13. PLURAL grid test: v5.6 + plural, 1940 / 1980 / 2010 (2026-10-30)

Siqiao's 900 m PLURAL grid (`index3`) on the 250 m grid as one more feature of v5.6 (`docs/conus_plan.md`, "PLURAL
grid test"): continuous (bilinear `plc`, cubic `plcc`) and classed (3 / 5 classes, quantile `pq*` / equal `pe*`
breaks). v5.6 (`Dasy_CONUS_RF_v3_u070`) gets 1940 and 1980 first (its other years stay as they are). Needs the
PLURAL files in `/projects/jaju1407/data/raw/plural/siqiao_2026/PLURAL_grid_data/`, the CONUS cutout (1940 / 1980 / 2010
with water), v5.6 (section 12) and v5.4 (section 5) on scratch.

| Step | Job | What | Estimate |
|---|---|---|---|
| plural_cutout | 8 cores, 1 h | `grid_cutout.sh --layers PLURAL PLURALC`: 2 warps x 3 years; cubic clip counts in the log | a few minutes |
| plural_qa | 8 cores, 45 min | coast / border leak of the 0 fill (edge vs interior), points -> `results/cutout/conus/plural_qa.csv`, `plural_points.csv`; nothing waits for it | ~5 min |
| v5.6 features / train / predict | 6 / 16 / 32 cores | 1940 + 1980 only (`--years`) | ~3 / 20 / 8 min |
| v5.6 validate | 8 cores, 1.5 h | tracts of all six v5.6 years (old ones must come out the same) | ~10 min |
| variants (x6) features / train / predict / validate | 6 / 16 / 32 / 8 cores | 1940 / 1980 / 2010, side by side; train waits for v5.6's train | ~5 / 30 / 12 / 6 min |
| plural_compare | 4 cores, 45 min | table, figure, best classed variant, county maps 2010 -> `results/validation/conus/plural_grid/` | ~5 min |

31 jobs; the whole chain ~1.5-2 h after the jobs start (estimates). Override a wall time: `CUTOUT_TIME`, `QA_TIME`,
`FEATURES_TIME`, `TRAIN_TIME`, `PREDICT_TIME`, `VALIDATE_TIME`.

Block 1, pre-check + submit (login node):

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs
ls -l /projects/jaju1407/data/raw/plural/siqiao_2026/PLURAL_grid_data/index3_*_900_US.tif
bash sbatch/submit_conus.sh plural
squeue -u $USER | wc -l
echo "== end of block 1"
```

Good: three `index3_{1940,1980,2010}_900_US.tif` files listed, `PRECHECK: 0 missing ...`, then one line `plural_cutout N |
plural_qa N | v5.6 features N ... | plural_compare N` (also in `logs/conus_plural_jobs.txt`), 32 from `wc -l` (31 jobs + the
header line, if nothing else of yours is queued), `== end of block 1`. `MISSING ...` + `ERROR: nothing submitted`: send the
output to Claude (nothing was submitted).

Block 2, progress (login node, any time):

```bash
cd /projects/jaju1407/HPC
ids=$(grep -oE '[0-9]{6,}' logs/conus_plural_jobs.txt | paste -sd,)
sacct -j "$ids" -X --format=JobID,JobName%22,State,Elapsed,ReqCPUS
f=$(ls -t logs/grid_cutout.*.out 2>/dev/null | head -1); [[ -n $f ]] && grep -E "PLURAL|clip" "$f" | tail -8
f=$(ls -t logs/plural_qa.*.out 2>/dev/null | head -1); [[ -n $f ]] && grep -E " edge | interior " "$f" | tail -6
echo "== end of block 2"
```

Good: states `PENDING` / `RUNNING` / `COMPLETED`; once the cutout is done, `PLURAL 1940 ... warped (bilinear)` lines and
`PLURALC ...: clip [0, 1]: N cells below ..., N above ...` per year; once plural_qa is done, the edge / interior lines;
`== end of block 2`. A `FAILED` job: the later ones stay `PENDING (DependencyNeverSatisfied)`; `scancel` them and send
the log to Claude.

Block 3, close the loop (after every job left `squeue`):

```bash
cd /projects/jaju1407/HPC
squeue -u $USER
ids=$(grep -oE '[0-9]{6,}' logs/conus_plural_jobs.txt | paste -sd,)
sacct -j "$ids" --format=JobID,JobName%22,State,Elapsed,MaxRSS,ReqCPUS,TotalCPU > logs/conus_plural_sacct.txt
for j in ${ids//,/ }; do seff "$j"; echo; done > logs/conus_plural_seff.txt
cat logs/conus_plural_sacct.txt
B=results/dasymetric/conus/Dasy_CONUS_RF_v3_u070
V=results/validation/conus/Dasy_CONUS_RF_v3_u070
ch=$(git status --porcelain $B/Y1920 $B/Y1960 $B/Y2010 $B/Y2020 $V/tract_errors_{1920,1960,2010,2020}.csv | wc -l)
del=$(git diff -U0 -- $B/cv_summary.csv $B/reallocation_qa.csv $B/water_mask_by_year.csv $V/metrics_by_year.csv | grep -c '^-[^-]' || true)
echo "v5.6 OLD YEARS: $ch changed files, $del removed CSV lines (0 and 0 = unchanged)"
grep -h "RULE RESULT" logs/plural_compare.*.out | tail -1
git add logs/ results/
git commit -m "run: PLURAL grid test, v5.6 1940 / 1980 + six plural variants (logs + results)"
git pull --rebase
git push
git log --oneline -1
echo "== end of block 3"
```

Good: every job `COMPLETED`, `v5.6 OLD YEARS: 0 changed files, 0 removed CSV lines`, one `RULE RESULT: best classed
variant ...` line (picks only the map variant; keeping PLURAL is your decision), `git push` ends with `main -> main`,
`== end of block 3`. Any number other than 0 in `OLD YEARS`: commit anyway and tell Claude.

What to look for in the logs: `grid_cutout` (clip counts of PLURALC per year), `plural_qa` (outside pixels exactly 0
~1.0, edge vs interior, deficit, points), `dasymetric_features` of a classed variant (`plural PLURAL k classes ...: inner
breaks [...] | cell share per class [...]`), `train` (CV / TEST vs v5.6), `predict` (`plural breaks = ...`, mass
preserved), `plural_compare` (tract MdAPE / MAPE tables, TEST counties + plural rank, `RULE RESULT`, county maps summary).

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
| models: `CatBoostRegressor object has no attribute __sklearn_tags__` | catboost older than 1.2.8 in the env: block 0 was not run or the update failed; rerun block 0 |
| models: `ModuleNotFoundError: xgboost` / `catboost` | the env was not updated (block 0) |
| models: train `CANCELLED ... DUE TO TIME LIMIT` | boosting slower than estimated: resubmit only that model's train / predict / validate with `TRAIN_TIME=04:00:00` (send Claude the log first) |
| models: `compare_with Dasy_CONUS_RF_v3_bui: its folds differ` | the split table changed: never regenerate it; send Claude the log |
| all: `MISSING .../processed/census/counties_{YEAR}.gpkg` | see block 0 of section 5: rebuild it with `census_prepare.sh --years <YEAR>` (do not go on without the NHGIS fill) |
| all: `grid_cutout` or `bui_fix` failed | the later jobs never start: `scancel` them, send the log. Both reruns are safe: `--years` touches only the new years; `bui_fix` reads `layers/BUI_raw/` |
| all: `water_frac` `OUT_OF_MEMORY` | 12 yearly layers in memory (~11 GB) + the workers: resubmit the chain from water_frac with more cores (send Claude `seff` first) |
| all: train `CANCELLED ... DUE TO TIME LIMIT` | `TRAIN_TIME=08:00:00`; or train only the eras not done yet with `--years` (send Claude the log first: `cv_summary.csv` is written at the end of the job) |
| y2020: `PRECHECK FAILED` / a Land_Use class `IDENTICAL to 2015` | do not submit; send `logs/y2020_precheck.txt` to Claude (the Land_Use rule for 2020 is the user's decision, `docs/conus_plan.md` "2020") |
| y2020: a job failed | the later ones never start (`DependencyNeverSatisfied`): `scancel` them, send the log. Reruns are safe: `--years 2020` touches only 2020 (the other years' rows of the QA / summary CSVs are kept), water and validation are deterministic |
| y2020: `REPRO DIFFERS` | commit anyway and tell Claude: something changed an old year's file (the run itself only adds 2020) |
| uncertainty: download `ERROR` (403, md5) | send `logs/hisdac_extra_download.txt`; a rerun resumes the archive download (`curl -C -`) and skips a checked tif |
| uncfilter: `train` stops with `exclude_counties ... not found` | the `uncertainty_filter` job failed or wrote elsewhere: send its log; rerun the chain after the fix (the features jobs can stay) |
| uncfilter: `filter_compare` stops with `... counties missing` or `excluded counties in its TEST predictions` | a version's results are incomplete or old (e.g. a train run before the sets changed): send the log; nothing is chosen |
| plural: `MISSING .../index3_<YEAR>_900_US.tif` | the PLURAL grid is not where the config says: send `ls -lR /projects/jaju1407/data/raw/plural/siqiao_2026/` |
| plural: features `nodata cells inside the used counties` (`.../PLURAL/...`) | the warped grid does not cover a county cell: send the features and cutout logs |
| plural: predict `plural breaks [...] differ from .../plural_breaks.csv` | the cutout layer or the county selection changed between features and predict: send the log; rerun that variant's chain from features |
| plural: `plural_compare` stops with `TEST counties differ` | a version ran with another split or exclusion set (an old config?): send the log |
| plural: `v5.6 OLD YEARS` not 0 | commit anyway and tell Claude: something changed an old year's file (the run only adds 1940 / 1980) |
| uncertainty: log ends `DONE (NobuiltYear value distribution only)` | not a failure: NobuiltYear is a 0/1 flag and contemp is missing, so no ratio exists; commit as block 3 and tell Claude (the next step waits for contemp from Stefan) |
| all: `repro ... -> DIFFERENT` in the summary log | 1920 / 1960 / 2010 should equal v3_n60 (same seed, features, folds): send Claude the log; nothing is rerun automatically |
| ntl: `ntl_qa` `FAILED` with `no cell with DN >= 60 in the box` | the fixed DN rule (known since Massachusetts 2026-10-06, change on hold); nothing waits for it: send the log with the others |
| ntl: `ntl_qa` `OUT_OF_MEMORY` | nothing waits for it; rerun alone with more cores: `sbatch --ntasks=16 --time=00:45:00 --export=ALL,CONFIG=configs/conus_study_area.yaml sbatch/ntl_qa.sh` |
| ntl: features `nodata cells inside the used counties` (`.../NTL/..._NTL.tif`) | the NTL raster does not cover a used county cell: the job stops on purpose (no silent 0); send Claude the log and the `ntl_qa` log (`zone cells with nodata`) |
| ntl: `compare_with Dasy_CONUS_RF_v3_all skipped: missing ...` | v3_all's scratch outputs were purged: send the log (the comparison table still reads the result files in git) |
| ntlv: `ntlv_download.sh` `curl: (6)` / `(7)` / `(28)` | no route to Dataverse from the login node: the laptop route in section 7, block 0 |
| ntlv: `ERROR: <label> md5 ..., expected ...` | a broken download: run block 0 again (the `.part` file is replaced); twice in a row: send the log |
| ntlv: `WARNING: <label> md5 changed since 2026-10-28` | the file was replaced on Dataverse: the new md5 is used; send the log before going on (record it in `docs/data_sources.md`) |
| ntlv: `WARNING: <year> has N .tif files` | the zip holds more than one raster: send the listing to Claude (the config expects one per year folder) |
| ntlv: `ntlv_check` `ERROR: VIIRS-like check failed` | CRS, coverage or negative values: do not submit block 1; send the check log |
| ntlv: features `nodata cells inside the used counties` (`.../NTLV/..._NTLV.tif`) | nodata left after `nodata_to` (should not happen): send the features and cutout logs |
| ntlv: `ntl_qa` `FAILED` with `NTL 2010: no cell with DN >= 60` only | the known DMSP rule; nothing waits for it. Any `NTLV ...` line in the error (negative values): send the log |
| external: `ModuleNotFoundError: exactextract` / `py7zr` / `openpyxl`, or `MISSING exactextract ...` | block 1a (env update) was not run or failed |
| external: `gpw4` / `grump1` `ERROR: ... download failed (Earthdata login ...)` or `not a valid zip (a login page?)` | `.netrc` missing or wrong, or the Earthdata account has not authorized the data app yet: log in once at https://urs.earthdata.nasa.gov, open one GPW file link in the browser and accept; then block 1b again (only the missing files are fetched). Or leave them out: the rest runs without them |
| external: `curl: (6)` / `(7)` / `(28)` for GHS-POP or WorldPop | no route from the login node: send the log; the files can come from the laptop through `dtn.rc.colorado.edu` (as section 7) into `/projects/jaju1407/data/raw/external/<product>/` with the same names (the script then only checks sizes) |
| external: `WARNING: ... size changed since 2026-10-28` | the file was replaced at the source: the new size is used; send the log (record it in `docs/data_sources.md`) |
| external: inventory `MISSING: N matches for ...` | the zip / archive holds more files than the config path expects: send the inventory log (fix in `configs/external_grids.yaml`) |
| external: an extract job `CANCELLED ... DUE TO TIME LIMIT` / `OUT_OF_MEMORY` | that product is `missing` in the table; send `seff` + log. Rerun it alone, then evaluate again: `sbatch --ntasks=16 --time=10:00:00 --job-name=external_ghs_pop sbatch/external_compare.sh extract --product ghs_pop`, then `sbatch --ntasks=2 --time=00:30:00 --job-name=external_evaluate sbatch/external_compare.sh evaluate` |
| external: evaluate `ERROR: .../tract_errors_<YEAR>.csv not found` | the v5.4 tract validation files are missing on the cluster: `git pull` |
| `oom-kill` / `OUT_OF_MEMORY` in `sacct` | send the log + `seff`; the stage needs more `--ntasks` in `submit_conus.sh` |
| `N study-county cells have no JRC coverage; missing tiles [...]` | a JRC tile is missing in `jrc_occurrence/`; download it (`docs/data_sources.md`) |
| `counties not in the split table` | a county of the census input is not in `configs/conus_split.csv`: send Claude the list (never regenerate the split) |
| `used counties skipped` / `counties with no unmasked cell skipped` (warnings) | expected for a few tiny or all-water counties; send the list with the logs |
| later jobs `DependencyNeverSatisfied` | an earlier job failed: `scancel` them, fix it, resubmit the chain |

## Notes

- The trial writes no prediction raster (`--measure`), so the pilot redoes 1960 completely.
- `results/cutout/conus/zones/zones_{YEAR}.csv` are the zone tables (zone_id = row of the 2010 polygon file).
