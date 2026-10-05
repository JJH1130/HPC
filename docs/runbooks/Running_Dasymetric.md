# Running dasymetric (county features → model → cell population)

Runs the three stages of `docs/dasymetric_v1.md` (changes: `docs/dasymetric_v2.md`,
`docs/dasymetric_v3.md`) on the study-area cutout. Code: `src/dasymetric/`; settings:
`configs/model.yaml` (version, eras with their years and features, feature groups, model, search
space, statuses, `compare_with`, `folds_from`, map years); study area and years come from
`configs/study_area.yaml`. The current version is **v3**: one model per era (E1 1810–1930,
E2 1940–1990, E3 2000–2020). v1 and v2 settings are in git history (8d93125, 38ed1e2).
Prerequisite: the full grid_cutout run plus NTL (`Making_Cutout.md`, sections 4 and 7), because every
stage reads `/scratch/alpine/jaju1407/hisdac/cutouts/massachusetts/` (E3 needs `layers/NTL`, E2 and E3
need `layers/Land_Use`). Scratch is purged 90 days after creation;
if the cutout is gone, rerun grid_cutout first.

| Stage | Script | Job | Resources | Writes (under `/scratch/alpine/jaju1407/hisdac/dasymetric/massachusetts/<version>/`) |
|---|---|---|---|---|
| 1 | `county_features.py` | `sbatch/dasymetric_features.sh` | acpu, 2 cores, 30 min | `<era>/features/county_features.csv` |
| 2 | `train.py` | `sbatch/dasymetric_train.sh` | acpu, 4 cores, 30 min | `<era>/model/` (rf.joblib, folds, feature_correlation, cv_results, best_params, metrics, feature_importance, shap_*, oof_predictions, compare_v2.json), `cv_summary.csv` |
| 3 | `predict.py` | `sbatch/dasymetric_predict.sh` | acpu, 8 cores, 1 h | `predictions/pop_{YEAR}.tif` (each year with its era's model), `qa/reallocation_qa.csv`, `maps/pop_{1810,1950,2020}.png`, `maps/pop_2020_v2_vs_v3.png` |

Without `eras:` in the config (v1, v2), there is no `<era>/` level and one pooled model.

Each stage runs on its own and reads only what the stage before it wrote, so a stage can be rerun
alone (e.g., only stage 3 after changing the map years). The small outputs are copied to
`results/dasymetric/massachusetts/<version>/[<era>/]` for git. The rasters stay on scratch.

v3 only **reads** v2. `folds_from: v2` reuses `v2/model/folds.csv`, filtered to each era's counties; the
run stops if it is missing. With `compare_with: v2`, stage 2 refits v2 (its features and best params)
on the same folds over all v2 rows and scores its out-of-fold predictions on each era's rows. This
reads `v2/features/county_features.csv` and `v2/model/{best_params,metrics}.json`. Stage 3 reads
`v2/predictions/pop_2020.tif` for the side-by-side map. If the comparison inputs are missing, those
outputs are skipped with a warning and the run still finishes. Stage 3 also reads
`/projects/jaju1407/data/processed/census/counties_2020.gpkg` for the state background of the maps.

**Status:** v1 passed on Alpine: jobs 33217129 / 33217130 / 33217131 (features / train / predict), 2026-10-01 cluster time.
v2 passed on Alpine: jobs 33445813 / 33445814 / 33445815, 2026-10-05 cluster time.
v3: tested on fake data only; not yet run on Alpine.

## 1. Sync + preflight (login node)

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs
ls /scratch/alpine/jaju1407/hisdac/cutouts/massachusetts/zones | head -3
ls /scratch/alpine/jaju1407/hisdac/cutouts/massachusetts/layers
ls /scratch/alpine/jaju1407/hisdac/cutouts/massachusetts/layers/FBUY
ls /scratch/alpine/jaju1407/hisdac/cutouts/massachusetts/layers/NTL
grep -E '^(version|compare_with|folds_from):' configs/model.yaml
ls /scratch/alpine/jaju1407/hisdac/dasymetric/massachusetts/v2/features /scratch/alpine/jaju1407/hisdac/dasymetric/massachusetts/v2/model
ls /scratch/alpine/jaju1407/hisdac/dasymetric/massachusetts/v2/predictions/pop_2020.tif
ls /projects/jaju1407/data/processed/census/counties_2020.gpkg
```

Good: `zones` lists `zones_1810.csv` …, `layers` lists BUA, BUI, BUPL, BUPR, FBUY, Land_Use,
NobuiltYear and NTL. The FBUY folder has exactly one `.tif`, and NTL has `2000_NTL.tif`,
`2010_NTL.tif` and `2020_NTL.tif` (if not, run `Making_Cutout.md` section 7 first).
`configs/model.yaml` shows `version: v3`, `compare_with: v2` and `folds_from: v2`. The v2 folder has
`county_features.csv`, `folds.csv`, `best_params.json`, `metrics.json` and `pop_2020.tif`, and
`counties_2020.gpkg` exists.

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
- features: one `era E1/E2/E3 | ... features [...]` line per era, then a line per year, then `era E1: 188 training rows | 22 counties`, `era E2: 84 ... | 14`, `era E3: 42 ... | 14` (counted from the v2 features), `county-years: 314 before status filtering ...`, `DONE`
- train: `folds from .../v2/model/folds.csv: 22 counties in 5 folds`. Then, for each era: `era Ex: training rows ...`, `folds (v2/model/folds.csv by GISJOIN): counties per fold {...}`, the Spearman table and `|rho| > 0.80` lines, `fold 0..4: CV RMSE ...`, `best params`, `CV RMSE ... | CV R2 ...`, the importance and SHAP tables (grouped: Land use in E2/E3, Lights in E3), `v2 (refit on these folds, scored on these N rows): ...`, `era Ex: CV v3 vs v2 (same folds and rows): ...`. At the end, the `CV by era:` table and `DONE`
- predict: `maps: [1810, 1950, 2020] | side by side with v2: [2020]`, one `model rf era Ex` line per era, one line per year with its era (`1810 (E1): ...`), `plot` lines for the four maps, `mass check: 314 county-years ... 0 fail | bad cells 0`, `DONE`

## 4. If it fails

| Symptom | Fix |
|---|---|
| `zones_{YEAR}.tif not found` / `layers/... not found` | the cutout is missing or purged: rerun grid_cutout (`Making_Cutout.md`) |
| `used counties with 0 cells, pop <= 0 or area <= 0` | a county can't be modeled or reallocated; send Claude the listed rows (needs a decision) |
| `nodata cells inside the used counties` | send Claude the log; the cutout isn't what the rules assume |
| `model 'lgbm' is a placeholder` | only `model: rf` is implemented |
| `no built cell (BUA = 1) in the window for {YEAR}` | `dist_built` is undefined; send Claude the log |
| `feature_groups must list every feature exactly once` | fix `feature_groups` in `configs/model.yaml` after changing an era's features |
| `every study year must be in exactly one era` / `give either features or eras` | fix `eras:` in `configs/model.yaml` |
| `folds_from v2: ... folds.csv not found` | v2 outputs were purged; rerun v2 (git 38ed1e2 settings) or tell Claude |
| `layers/NTL/2000_NTL.tif not found` / `layers/Land_Use/... not found` | cut NTL first (`Making_Cutout.md` section 7) / the cutout was purged |
| `rf.joblib was trained on [...], the config says [...]` | features changed after training; rerun stages 1-2 |
| `compare_with v2 skipped: missing ...` (warning) | v2 outputs were purged; v3 results are still valid, only the comparison is missing |
| `--counties-gpkg ... not found` | rerun census_prepare (`Preparing_Census.md`) or check `$DATA_ROOT` |
| `county_features.csv not found` / `rf.joblib not found` | run the earlier stage first |
| `reallocation checks failed` | the QA CSV is still copied back; push it and send Claude the log |
| `CANCELLED ... DUE TO TIME LIMIT` | raise `--time` in that stage's script |

## 5. Close the loop (login node)

```bash
cd /projects/jaju1407/HPC
git add logs/dasymetric_features.$j1.out logs/dasymetric_train.$j2.out logs/dasymetric_predict.$j3.out results/dasymetric/
git commit -m "run: dasymetric v3 $j1 $j2 $j3"
git pull --rebase
git push
```

Then tell Claude to pull.

## Notes

- 2026-10-06: v3 implemented (`docs/dasymetric_v3.md`). The eras and their features are in
  `configs/model.yaml`; v2 and v1 configs still run unchanged (no `eras:` = one pooled model). Tested on
  a fake Boston-area setup with 7 years (E1 1810, 1900; E2 1950, 1990; E3 2000-2020). Two extra
  1810-only counties stood in for Maine. The fake cutout was built with the real `make_cutout.py`
  (+ `--layers NTL`). v2 was run with the committed v2 code, then v3 with the new code. All three v3
  stages ran: one model per era, v2 folds reused per era, and each year predicted with its era's model.
  Mass was preserved (max relative difference 3.0e-8), and the v2 output folder was byte-identical
  afterwards. Checks of the comparison: each era's v3 out-of-fold fold RMSE equals the search's fold
  scores, and v2's refit out-of-fold predictions pooled over all eras reproduce v2's reported CV
  exactly (0.1587). An overlapping or missing era year, `features` together with `eras`, an ungrouped
  feature, a missing `folds_from` file, `compare_with` with several eras but no `folds_from`, and a
  model trained on other features all stopped with clear errors.

- 2026-10-05 (cluster time), v2 jobs 33445813 / 33445814 / 33445815 (code 38ed1e2). Features took
  1.5 min, training 2 min, and prediction 1.5 min. Predictions take 19 MB on scratch. There were 314
  training rows (22 GISJOIN, 22 years). Each county has one GISJOIN in every year, so the folds don't
  leak. Fold 4 holds Bristol, Nantucket, Somerset and all seven 1810-only Maine counties.
  - CV on the same folds: v2 RMSE 0.756 +/- 0.438, R2 0.699 +/- 0.202, against v1 0.766 / 0.684.
    v1 recomputed on the v2 folds reproduced v1's reported values exactly, so the comparison is like
    for like. v2 is not worse, but the gain is small. Fold RMSE: 0.23 / 1.43 / 0.32 / 0.92 / 0.88.
    Best params: n_estimators 1000, max_depth 10, min_samples_leaf 2, max_features 0.5. Training
    RMSE was 0.254.
  - Per county (out-of-fold, recomputed on the laptop from the results CSVs): the large errors are the
    same as in v1. 1810 Somerset, Washington, Hancock and Oxford are over-predicted by 2.2-3.0
    (v1: the same to within 0.02). Their county-mean dist_built is 38-96 km, and no other training
    county is above 7 km. They are all in fold 4, so when they are held out the model has never
    seen a remote county. Suffolk is under-predicted by about 1.9-2.5, as in v1, because RF can't
    predict above the training range. Dukes is over-predicted by 1.1-2.2. v2 improved Barnstable,
    Dukes, Nantucket, Plymouth and Norfolk by 0.1-0.3, and was worse for Hampden, Franklin and
    Berkshire County (2010/2020) by 0.15-0.3.
  - Correlation (Spearman, county features): the design expected no |rho| > 0.8 within Building,
    and that did not hold. bldg_size-mu_ratio is 0.989, bui-bldg_size 0.984 and bui-mu_ratio 0.979.
    age-year is 0.950. All features have |rho| >= 0.80 with each other except year with the
    building ratios (0.86-0.88). The county means are ordered by development level in both space
    and time, so ratios computed per cell still move together once averaged to the county.
  - SHAP (mean |SHAP|): bldg_size 0.52, bui 0.46, dist_built 0.39, year 0.19, age 0.12,
    mu_ratio 0.07. Grouped: Building 1.01, Settlement context 0.34, Period 0.19. Permutation importance
    gives the same order for the top three. By year: age falls from 0.30 (1810) to 0.04-0.09 (after
    1900). year is about 0.3 before 1900, 0.06 in 1900-1950 and 0.18 after 1980. dist_built is steady
    at 0.32-0.44 after 1820 (0.72 in 1810).
  - Maps: in 1810 v2, cells in inland Maine vary with distance to the nearest built cell (rings around
    isolated built cells), and population is denser along the coast and at built cells in
    Massachusetts. The straight county boundaries in inland Maine are weaker but still visible.
    Reallocation keeps each county's census total, so a step at a boundary between counties of
    different density stays. Cell y_hat bottoms out at 0.629 in every year from 1820 on (0.101 in
    1810), so the most remote cells share one value.
  - Reallocation: all 314 county-years were preserved (max relative difference 9.4e-9), with no
    negative or NaN cells. Max cell population was 7231 (1810) and 750 (2020).
  - mu_ratio (BUPR / BUPL) goes up to 2.9 as a county mean. BUPR can be greater than BUPL in a
    cell, so it is not a share bounded by 1.
- 2026-10-06: v2 implemented (`docs/dasymetric_v2.md`). Tested on a fake 3-year cutout (13 counties,
  one `nodata_zero` in 1900, built cells outside the counties). v1 was run first with the committed
  v1 code (eaebf31), then v2 with the new code. All three v2 stages ran. Mass was preserved (max relative
  difference 2.6e-8). v1 CV recomputed on the v2 folds matched v1's reported CV exactly (RMSE
  0.30755, R2 0.87001), so GroupKFold gives the same folds and the comparison is like for like. The v1
  output folder was byte-identical before and after the v2 run. All PNGs rendered (correlation
  heatmap, SHAP beeswarm, SHAP by year, maps with state background and scale bar, 1810 v1 vs v2). A
  year with no built cell, `feature_groups` that leave out a feature, and a missing `--counties-gpkg`
  all stopped with clear errors. The fake features are almost perfectly correlated (|rho| 0.97-0.99)
  because of how the fake data were made; this says nothing about the real data. Local env: `hisdac`
  built from `envs/hisdac/environment.yml` (sklearn 1.9.1, shap 0.52.0), run via `conda run -n hisdac`.
- 2026-10-02: runbook written. Tested on a fake 3-year cutout (24 counties, one `nodata_zero`): all
  three stages ran, mass was preserved (max relative difference 3e-8), the excluded county and
  cells outside the counties were NoData, and the lgbm placeholder and a used county with 0 cells
  stopped with clear errors. The PNG maps were checked in a separate Python environment, because
  matplotlib crashes when saving PNGs in the laptop env.
- 2026-10-01 (cluster time), jobs 33217129 / 33217130 / 33217131 (code 8d93125). Features took 20 s,
  training 1 min, and prediction 2.5 min, including about 1.5 min loading the model. 314 training rows
  from 22 counties (GISJOIN) over 22 years. Best params: n_estimators 200, max_depth 20,
  min_samples_leaf 2, max_features 1.0. CV RMSE 0.766 +/- 0.435 and CV R2 0.684 +/- 0.220; training
  RMSE 0.262; sd(y) 1.552. Fold RMSE: 0.23 / 1.41 / 0.33 / 0.97 / 0.89. Reproducing the folds on the
  laptop showed that the large errors come from the extremes. Suffolk, the densest county, is
  under-predicted by about 2 when it is held out, because RF can't predict past the training range.
  The 1810 Maine counties (Somerset, Washington, Hancock, Oxford; y near 0) are over-predicted by
  2-3. Dukes and Nantucket (islands) are over-predicted. Mainland counties have per-county RMSE
  0.05-0.5. Permutation importance: bui 1.97, year 0.74, bua 0.33, others 0.11-0.15. Reallocation: all 314
  county-years were preserved (max relative difference 3.4e-8), with no negative or NaN cells. y_hat
  ranges 0.16-8.5; the floor 0.161 is the unbuilt cell. Max cell population falls from 6289 (1810)
  to 592 (2020): in early years, the few HISDAC-built cells take most of a county's population.
  Predictions take 8.3 MB on scratch.
