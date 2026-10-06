# Checking Stefan's county CSV against the nominal counties

Compares `all_county_census_MSA_full.csv` (county counts 1900–2010 keyed by 2010 FIPS, from
Stefan Leyk; see `docs/data_sources.md`) with the nominal NHGIS counties from
`docs/runbooks/Preparing_Census.md`. Diagnostic only: existing census outputs are read, not
changed. Code: `src/census/std_county_check.py`; job: `sbatch/std_county_check.sh`
(acpu, 2 cores, 20 min, env `hisdac`).

**Status:** written 2026-10-07, not yet run.

## What it does

1. Reads the CSV, drops Alaska (02) and Hawaii (15), builds
   `GISJOIN = "G" + state(2) + "0" + county(3) + "0"` (the CSV stores FIPS as a number, so it is
   zero-padded to 5 digits first).
2. Joins to the 2010 polygons (`counties_2010.gpkg`) and lists CSV rows without a polygon and
   polygons without a CSV row.
3. For each year 1900–2010, matches on GISJOIN to `counties_{YEAR}.gpkg` and classifies each
   CSV county-year:

   | class | rule |
   |---|---|
   | `stable` | `pop_std == pop_nominal` and `0.99 <= area_year / area_2010 <= 1.01` |
   | `boundary_change` | any other row with both pops and a 2010 polygon |
   | `missing` | `detail` = `csv_nan` (county not yet in the CSV), `no_nominal_match` (no polygon with that GISJOIN that year), or `nominal_pop_nan` (nominal polygon has no pop) |
   | `no_2010_polygon` | CSV row with a pop but no 2010 polygon, so no area ratio |
   | `nominal_only` | summary only: nominal counties that no CSV row matches |

   `pop_equal` and `area_equal` are also kept as separate columns, so `boundary_change` can be
   split later (pop differs only, area differs only, both).

## Inputs / outputs

| | Path |
|---|---|
| CSV | `/projects/jaju1407/data/raw/census_std/all_county_census_MSA_full.csv` (copy of `data/census_std/` in git) |
| nominal counties (read only) | `/projects/jaju1407/data/processed/census/counties_{1900..2010}.gpkg` |
| results (git) | `results/census_std/std_county_check.csv` (one row per county-year), `std_county_summary.csv`, `std_county_summary_MA.csv`, `std_vs_2010_unmatched.csv` |
| GPKG | `/projects/jaju1407/data/processed/census/counties_std_2010.gpkg` (layer `counties`: 2010 polygons + `pop_1900`…`pop_2010`, `pop_est2015`, CBSA/CSA columns) |

Summary columns: `year, class, n, pop_std, pop_nominal, n_share, pop_std_share,
pop_nominal_share`. `pop_std_share` is over the CSV total for that year; `pop_nominal_share`
is over the nominal total (it includes `nominal_only`).

## 1. Sync + preflight (login node)

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs /projects/jaju1407/data/raw/census_std
cp -n data/census_std/all_county_census_MSA_full.csv /projects/jaju1407/data/raw/census_std/
ls -la /projects/jaju1407/data/raw/census_std/ /projects/jaju1407/data/processed/census/counties_2010.gpkg
```

Good: the CSV (519,502 bytes) and `counties_2010.gpkg` are listed.

## 2. Submit (login node)

```bash
cd /projects/jaju1407/HPC
jid=$(sbatch --parsable sbatch/std_county_check.sh)
echo "submitted $jid"
```

## 3. Monitor (login node)

```bash
squeue -u jaju1407
tail -n 80 logs/std_county_check.$jid.out
```

Check these lines in the log:
- `dropped 26 AK/HI rows`, `counties with NaN in some year: 291; NaN after a first value (gaps): 0`
- `2010: 3105 counties with pop, total 304,102,874` (about 2.5 M below the CONUS total: Miami-Dade is not in the CSV)
- `2010 polygons without a CSV row (...)`: expect 12086, 08014, 46113, 51515
- one `{year}: {...}` class-count line per year, then the two summary tables, `wrote ... counties_std_2010.gpkg`, `DONE`, `== done`

## 4. If it fails

| Symptom | Fix |
|---|---|
| `ERROR: ... counties_{YEAR}.gpkg not found` | run `sbatch/census_prepare.sh` first (`docs/runbooks/Preparing_Census.md`) |
| `ERROR: ... missing columns` | the CSV layout changed; send Claude the columns listed in the error |
| `CANCELLED ... DUE TO TIME LIMIT` | raise `--time` in `sbatch/std_county_check.sh` |

## 5. Close the loop (login node)

```bash
cd /projects/jaju1407/HPC
git add logs/std_county_check.$jid.out results/census_std/
git commit -m "run: std_county_check $jid"
git pull --rebase
git push
```

Then tell Claude to pull.

## Notes

- 2026-10-07: runbook written. Grouping of changed counties comes after the summary is reviewed.
