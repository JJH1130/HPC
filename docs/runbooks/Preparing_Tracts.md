# Preparing NHGIS tract data (1910–2020, CONUS)

Turns the NHGIS tract population tables (extract nhgis0002) and tract boundaries into one
GeoPackage per decade in HISDAC's CRS (ESRI:102039), for validating the dasymetric outputs
(Ch1). Code: `src/census/prepare_tracts.py`; job: `sbatch/tract_prepare.sh` (acpu, 4 cores,
2 h, env `hisdac`). Rules: `docs/tract_preprocessing.md`. The county outputs
(`counties_{YEAR}.gpkg`) are only read.

**Status:** written 2026-10-13, not yet run.

## Inputs / outputs

| | Path |
|---|---|
| source tables 1910–1960 | `/projects/jaju1407/data/raw/nhgis/nhgis0002_csv/nhgis0002_ds{NN}_{YEAR}_tract.csv` + `_codebook.txt` |
| time series 1970–2020 | `/projects/jaju1407/data/raw/nhgis/nhgis0002_csv/nhgis0002_ts_nominal_tract.csv` (`GISJOIN, YEAR, AV0AA`) |
| boundaries | `/projects/jaju1407/data/raw/nhgis/nhgis0002_shape/nhgis0002_shapefile_tl{2008,2010,2020}_us_tract_{YEAR}.zip` (kept zipped) |
| counties (read only) | `/projects/jaju1407/data/processed/census/counties_{YEAR}.gpkg` |
| table choices | `configs/nhgis_tract_tables.csv` (empty until a table needs a manual choice) |
| outputs | `/projects/jaju1407/data/processed/tract/tracts_{YEAR}.gpkg` (layer `tracts`) |
| results (git) | `results/tract/table_inventory.csv`, `issues.csv`, `qa_by_year.csv`, `qa_by_year_MA.csv`, `coverage_by_county.csv`, `coverage_by_county_MA.csv` |

## 1. Sync + preflight (login node)

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs
ls /projects/jaju1407/data/raw/nhgis/nhgis0002_csv/ | grep -c '_tract.csv$'
ls /projects/jaju1407/data/raw/nhgis/nhgis0002_csv/ | grep -c '_tract_codebook.txt$'
ls /projects/jaju1407/data/raw/nhgis/nhgis0002_shape/
```

Good: 25 CSVs (24 datasets + the time series), 25 codebooks, and 12 zips
(`..._us_tract_1910.zip` … `_2020.zip`), one per year.

## 2. Quick test: 1910, 1960, 1970 (login node)

1910 has two tables (NT22, NT49), 1960 has three (NTSUP2, NBT1, NBT4), and 1970 is the
first time-series year. The job also reads every 1910–1960 codebook and writes
`results/tract/table_inventory.csv` first, so a table it can't resolve stops the job early.

```bash
cd /projects/jaju1407/HPC
jid=$(sbatch --parsable sbatch/tract_prepare.sh --years 1910 1960 1970)
echo "submitted $jid"
```

## 3. Monitor (login node)

```bash
squeue -u jaju1407
tail -n 80 logs/tract_prepare.$jid.out
```

Check these lines in the log:
- `table inventory (N tables):`, then one row per table with `pop_columns` and `rule`
  (`single_variable`, `total_label` or `config`). Each chosen column should be a total population.
- per year: `... rows -> ... GISJOINs; ... conflicts`, `join: ...`, `county check: ...`,
  `wrote .../tracts_{YEAR}.gpkg`
- `QA by year:` table, `DONE`, then `== done`

## 4. Close the loop for the quick test (login node)

```bash
cd /projects/jaju1407/HPC
du -sh results/tract/*
git add logs/tract_prepare.$jid.out results/tract/
git commit -m "run: tract_prepare $jid (quick test)"
git pull --rebase
git push
```

If `issues.csv` is over ~10 MB, leave it out of `git add` and say so. Then tell Claude to pull,
and wait for the review before the full run.

## 5. Full run (login node)

After the quick test is reviewed:

```bash
cd /projects/jaju1407/HPC
jid=$(sbatch --parsable sbatch/tract_prepare.sh)
echo "submitted $jid"
```

Then monitor (step 3) and close the loop (step 4, with message `run: tract_prepare $jid`).

## 6. If it fails

| Symptom | Fix |
|---|---|
| `ERROR: fix these ...: UNRESOLVED; variables: ...` | the table has several variables and none is labelled "Total". Push the log + `results/tract/table_inventory.csv`; Claude adds a row to `configs/nhgis_tract_tables.csv` |
| `... MISSING_COLUMN` | the codebook names a column the CSV lacks; push the log + inventory |
| `ERROR: ... no tables found in the Data Dictionary` | codebook format differs from what the parser expects; send Claude the codebook's "Data Dictionary" section |
| `ERROR: need exactly one *_us_tract_{YEAR}.zip` | download the missing year, or remove a duplicate |
| `ERROR: ... must hold exactly one .shp` | send Claude the zip listing (`unzip -l <zip>`) |
| `ERROR: ... counties_{YEAR}.gpkg not found` | run the county step first (`docs/runbooks/Preparing_Census.md`) |
| `ERROR: ... missing columns` | the CSV layout differs; send Claude the columns listed in the error |
| `oom-kill` / `OUT_OF_MEMORY` | raise `--ntasks` in `sbatch/tract_prepare.sh` (3.8 GB per core) |
| `CANCELLED ... DUE TO TIME LIMIT` | raise `--time` in `sbatch/tract_prepare.sh` |

## Notes

- 2026-10-13: runbook written. Tested locally only on a small synthetic dataset (rules 1–5,
  conflicts, non-CONUS, unmatched both ways, county checks). Codebook parsing assumes the
  NHGIS "Table N: / Universe: / Source code: / NHGIS code:" layout; the first run will confirm it.
