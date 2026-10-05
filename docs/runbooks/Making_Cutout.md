# Making a study-area cutout (HISDAC layers + county zones)

Cuts the HISDAC-US V2 layers to the study area in `configs/study_area.yaml` and builds the
per-year county zone grids. Rules are in `docs/cutout.md`. Code: `src/grid/make_cutout.py`;
job: `sbatch/grid_cutout.sh` (acpu, 2 cores, 1 h, env `hisdac`). Prerequisite: the full
census_prepare run (`Preparing_Census.md`), because this job reads `counties_{YEAR}.gpkg`.

**Status:** full run (22 years) passed on Alpine: job 33216032, 2026-10-01 cluster time. Quick test: job 33165456.
NTL (section 7): cut on Alpine, job 33458909 (2026-10-05 cluster time). NTL QA job 33458910 failed only on
the fixed DN >= 60 rule for 2010 (see Notes); the layer was judged correct and the rule is kept as is for now.

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
for c in A C GV I RC RI RO VL; do ls /pl/active/Leyk_Lab/data/HISDAC_US_V2/Land_Use/$c/Count_1940_$c.tif; done
ls /projects/jaju1407/data/processed/census/ | head -3
```

Good: the folders BUI, BUPL, BUPR, BUA exist, BUI contains `1810_BUI.tif`, and `find` prints exactly
one FBUY file and one NobuiltYear file. If `find` prints more than one or none, change the FBUY /
NobuiltYear `path` in `configs/study_area.yaml`. The Land_Use loop should list 8 files and print no
`No such file` errors.

Layers are listed only in `configs/study_area.yaml` (`layers:`). To add a raster (DEM, night lights,
land cover), add one entry there with its `resampling` method. No code change is needed.

## 2. Quick test: 1810 + 1940 (login node)

The window still comes from all 22 years. Only the 1810 and 1940 layers and zones are written,
plus FBUY and NobuiltYear. 1940 is the first Land_Use year, so all 8 classes get cut. (Even with
`--years 1810` alone, every class's 1940 file is checked at the start.)

```bash
cd /projects/jaju1407/HPC
jid=$(sbatch --parsable sbatch/grid_cutout.sh --years 1810 1940)
echo "submitted $jid"
```

## 3. Monitor (login node)

```bash
squeue -u jaju1407
tail -n 60 logs/grid_cutout.$jid.out
```

Check these lines in the log:
- `reference grid: 1810_BUI.tif | ... | cell 250.0 | origin (...)`
- `1810: N counties, bounds [...]`, one line per year. 1810 has more counties than later years because it includes Maine.
- `window: col_off ... | W x H cells`
- `layer ...` lines at the start: one per layer (including `Land_Use_A` … `Land_Use_VL`) with years, resampling, dtype
- `N rasters on the HISDAC grid (window read), 0 to warp onto it`
- one line per cut file showing its source type, `window read` → `int32`, and min/max. A `source declares nodata=0` warning means 0 was kept as a value.
- `zones 1810` and `zones 1940`: `N counties, ... area ratio min/median/max`, and any `got 0 cells` warnings
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
| `ERROR: input rasters ... missing ... folder contains [...]` or `matched 0 files` / `matched 2 files` | the file naming differs; compare with the folder listing in the error and fix that layer's `path` in `configs/study_area.yaml` |
| `ERROR: ... not on the HISDAC grid but have resampling: none` | that raster has a different grid. If it's an external raster, set a `resampling` method. If it's a HISDAC layer, send Claude the listed lines |
| `ERROR: config layers: ... resampling ... not in [...]` | typo in the config |
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

## 7. Add a layer to the existing cutout: NTL + NTL QA (login node)

`docs/dasymetric_v3.md` adds harmonized night lights (2000, 2010, 2020). `--layers NTL` cuts only that
layer into the existing cutout: it checks that the window equals the one in `window.json` and leaves
zones, `window.json` and `cutout_qa.csv` alone. `sbatch/ntl_qa.sh` then checks it (`src/grid/ntl_qa.py`).
Both are small (acpu, 2 cores). The cutout must exist (scratch purges after 90 days; if
`window.json` is gone, rerun the full cutout in section 4 first, and it will include NTL).

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs
ls -l /projects/jaju1407/data/raw/ntl/Harmonized_DN_NTL_{2000,2010,2020}_*.tif
ls /scratch/alpine/jaju1407/hisdac/cutouts/massachusetts/window.json
j1=$(sbatch --parsable sbatch/grid_cutout.sh --layers NTL)
j2=$(sbatch --parsable --dependency=afterok:$j1 sbatch/ntl_qa.sh)
echo "cutout NTL $j1 | NTL QA $j2"
```

Good: `ls` lists exactly one file per year (2000 and 2010 `calDMSP`, 2020 `simVIIRS`). If a year
has more than one, the job stops with `matched 2 files`; tell Claude.

Check (`tail -n 30 logs/grid_cutout.$j1.out`, `tail -n 20 logs/ntl_qa.$j2.out`):
- cutout: `layer NTL years 2000-2020 resampling nearest int16 | files to write: 3`,
  `0 rasters on the HISDAC grid (window read), 3 to warp onto it`, `--layers ['NTL']: window matches ...`,
  three `NTL {YEAR} uint8, warped (nearest) -> int16 ... min 0 max 63` lines (nodata cells should be 0), `DONE`
- QA: one line per year: `DN 0..63`, `box: N bright of M cells, centroid (lon, lat), shift X km`
  (expect well under 1 km; a `WARNING ... moved` line means 1 km or more), `Spearman ntl~bui`, then `DONE`.
  `ERROR: NTL QA failed` lists values outside 0-63 or a year with no DN >= 60 cell near Boston; the CSV
  is still copied back.

| Symptom | Fix |
|---|---|
| `window.json not found; --layers adds to an existing cutout` | the cutout was purged: run the full cutout (section 4); it includes NTL |
| `the window differs from window.json` | the config or census changed since the cutout; run the full cutout |
| `matched 0 files` / `matched 2 files` for NTL | check the file names in `/projects/jaju1407/data/raw/ntl/` against the `path` in `configs/study_area.yaml` |

Close the loop:

```bash
cd /projects/jaju1407/HPC
git add logs/grid_cutout.$j1.out logs/ntl_qa.$j2.out results/cutout/
git commit -m "run: grid_cutout NTL $j1, ntl_qa $j2"
git pull --rebase
git push
```

## Notes

- 2026-10-05 (cluster time), jobs 33458909 (`--layers NTL`) / 33458910 (NTL QA), code 8e6c35e.
  - Cutout: 2.5 min, about 1 min of it reading the 22 county files for the window. The window matched
    `window.json`. 3 files were warped (nearest) to int16, 0.4-0.7 MB each, with no nodata cells.
    Max DN was 62 (2000), 59 (2010) and 63 (2020). About 54-60 % of the window is 0 (ocean and
    unlit land).
  - QA: DN stayed within 0-63 in every year. The job stopped with `ERROR: NTL QA failed: 2010: no cell
    with DN >= 60 in the box`, because the 2010 calDMSP file peaks at 59, below the fixed threshold.
    This is not a data error. The user judged the 2010 alignment correct, because the Spearman of
    NTL with BUI over the 335,9xx cells in the study counties is about the same in every year: 0.528
    (2000), 0.540 (2010), 0.516 (2020). 2000 and 2020 bright-core centroids:
    (-71.084, 42.362) and (-71.090, 42.358), 0.65 km apart (expected well under 1 km).
  - Decision (user, 2026-10-06): keep the QA rule unchanged for now. Observation for a later
    revision: in 2000, 5055 of the 6400 cells in the 20 km box are at DN >= 60 (4354 in 2020).
    The centroid of saturated cells is then close to the box centre, so it is a weak alignment test.

- 2026-10-06: added NTL (`docs/dasymetric_v3.md`), `--layers` (cut only listed layers into an existing
  cutout), dtype `int16`, and `src/grid/ntl_qa.py`. Tested on a fake Boston-area setup: fake HISDAC
  rasters + county GPKGs, and fake NTL in EPSG:4326 at 30 arc-seconds with the 2010 grid shifted half a
  cell. The full cutout was run without NTL, then `--layers NTL`: the 3 NTL files were warped
  (nearest) to int16 with values 0-63 and no nodata cells, and zones, `window.json` and `cutout_qa.csv`
  were byte-identical afterwards. The QA found the fake bright core at the expected place in every
  year (centroid shifts 0.2-0.3 km, including the half-cell-shifted 2010). It stopped with clear
  errors for a value of 70, an unknown `--layers` name, a window that differs from `window.json`, and
  a missing cutout.

- 2026-09-30: runbook written. The FBUY/NobuiltYear file names aren't known yet; the config uses the globs `**/*FBUY*.tif` and `**/*NobuiltYear*.tif`, which must each match exactly one file.
- 2026-09-30: added Land_Use (8 classes, 1940–2020; Theme files not used). Layers are now listed only in the config, each with a `resampling` method, so external rasters (DEM, NTL, land cover) can be added with one line. Tested on synthetic data only.
- 2026-09-29 (cluster time), job 33165456 on `c3cpu-e2-u10` (code a0ba5ad), `--years 1810 1940`: took 1 min 43 s, about 50 s of it reading the 22 county files for the window. Output was 1.6 MB. The HISDAC grid is 18459 x 11615 cells, origin (-2356398.7593, 3172999.2874). The window is 1711 x 2842 cells (col_off 16748, row_off 639). Its height comes from 1810 (Massachusetts including Maine); from 1820 on, Massachusetts uses only ~7% of the window. HISDAC sources are float64 with no nodata declared, all whole numbers. All 18 rasters were on the grid. Area ratio was 0.997–1.007, and no county got 0 cells (20 counties in 1810, 14 in 1940).
- 2026-10-01 (cluster time), job 33216032 on `c3cpu-e2-u1` (code da4b1dc), full run: took 3 min 20 s and wrote 162 rasters (60 MB). All were window reads with no nodata cells and no negative values. NobuiltYear max is 2744; it is a count (see `docs/cutout.md`). QA: 314 county-years, no county got 0 cells, and area ratio was 0.997–1.008 in every year. The largest deviation was Suffolk at 1.0077 in 1850/1860 (about 60 km², so ±1 cell matters). The 1810 window has 20 counties and later years 14. Assigned cells: 336164 in 1820–1860, 335900 in 1870–2000, 335899 in 2010, 335850 in 2020.
