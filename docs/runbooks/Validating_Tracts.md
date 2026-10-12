# Validating the Massachusetts dasymetric outputs against tracts

Compares the 250 m predictions of one dasymetric version with NHGIS census tracts and with an
areal-weighting baseline. Code: `src/validation/tract_validate.py`; job:
`sbatch/validate_tract.sh` (acpu, 2 cores, 30 min, env `hisdac`). Design and QA rules:
`docs/validation_tract.md`.

**Status:** v3_1 run 2026-10-13 (job 33913781, passed). v2 failed (job 33915573, fixed in code); both to rerun for the density metric.

## Inputs / outputs

| | Path |
|---|---|
| predictions | `/scratch/alpine/jaju1407/hisdac/dasymetric/massachusetts/<version>/predictions/pop_{YEAR}.tif` + `qa/reallocation_qa.csv` |
| zones | `/scratch/alpine/jaju1407/hisdac/cutouts/massachusetts/zones/zones_{YEAR}.tif` + `.csv` |
| tracts | `/projects/jaju1407/data/processed/tract/tracts_{YEAR}.gpkg` (`docs/runbooks/Preparing_Tracts.md`) |
| coverage | `results/tract/coverage_by_county_MA.csv` (in git) |
| results (git) | `results/validation/massachusetts/<version>/`: `tract_errors_{YEAR}.csv`, `metrics_by_year.csv`, `qa_totals.csv`, `tract_validation_{1940,1970,2020}.png` |

Scratch is purged 90 days after creation. If the predictions are gone, rerun
`sbatch/dasymetric_predict.sh` (`docs/runbooks/Running_Dasymetric.md`) first.

## 1. Sync + preflight (login node)

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs
ls /scratch/alpine/jaju1407/hisdac/dasymetric/massachusetts/v3_1/predictions/ | head -30
ls /scratch/alpine/jaju1407/hisdac/dasymetric/massachusetts/v3_1/qa/reallocation_qa.csv
ls /projects/jaju1407/data/processed/tract/
```

Good: `pop_1910.tif` … `pop_2020.tif`, the QA CSV, and `tracts_1910.gpkg` … `tracts_2020.gpkg`.

## 2. Run, all 11 years (login node)

```bash
cd /projects/jaju1407/HPC
jid=$(sbatch --parsable sbatch/validate_tract.sh --version v3_1)
echo "submitted $jid"
```

## 3. Monitor (login node)

```bash
squeue -u jaju1407
tail -n 80 logs/validate_tract.$jid.out
```

Check these lines in the log:
- per year: `N MA tracts | flags {...}`, then a `model` and a `baseline` line (n, share, rmse, mae, mdape, r2_log)
- `totals QA: ... rows, ... flagged` with a count per check
- `DONE`, then `== done`

If it ends with `ERROR: ... fully tracted county-years where predicted/baseline pop inside tracts differs`,
the results are still written. Push them anyway (step 4): `qa_totals.csv` lists the failing county-years.

## 4. Close the loop (login node)

```bash
cd /projects/jaju1407/HPC
git add logs/validate_tract.$jid.out results/validation/
git commit -m "run: validate_tract $jid (v3_1)"
git pull --rebase
git push
```

Then tell Claude to pull.

## 5. If it fails

| Symptom | Fix |
|---|---|
| `ERROR: inputs not found:` | the listed files are missing; predictions purged from scratch → rerun dasymetric predict; tracts missing → run tract_prepare |
| `ERROR: ... is not on the zones grid` | predictions were made from another cutout; rerun predict for this version |
| `ERROR: ... predicted cells outside the county zones` | predictions and zones don't match; send Claude the log |
| `ERROR: ... fully tracted county-years ...` | cells of a fully tracted county lie in no tract; push the results for review |
| `CANCELLED ... DUE TO TIME LIMIT` | raise `--time` in `sbatch/validate_tract.sh` |

## Notes

- 2026-10-13: written. Tested locally on a small synthetic grid: metrics, flags (`multi_county`,
  `outside_model`, `no_cells`), totals QA and the stop on lost cells. The PNG code could not be run
  locally (broken matplotlib on the laptop); the first Alpine run checks it.
- 2026-10-13 (cluster date 2026-10-12), job 33913781, `--version v3_1`, code d2e2e4e: all 11 years in ~1 min;
  PNGs fine. Totals QA 546 rows, 0 flagged. Model MdAPE 28–62 % vs baseline 69–81 %; best 1970–1990, worse
  from 2000 (E3 era). Results in `docs/validation_tract.md`, Results.
- 2026-10-13, job 33915573, `--version v2`, code bb3efee: failed in 1910 (`'Pandas' object has no attribute
  'n_masked'`): v2 has no water mask, so its reallocation QA lacks the column. Fixed: missing `n_masked` → 0,
  logged as "no water mask". Same change adds the log-density metrics and `lon`/`lat` to `tract_errors_*.csv`.
