# Preparing NHGIS county census data (1810–2020, CONUS)

Turns the NHGIS county population time series + county boundary shapefiles into one
GeoPackage per decade in HISDAC's CRS (ESRI:102039), with a QA report and a list of every
dropped row. Code: `src/census/prepare_census.py`; job: `sbatch/census_prepare.sh`
(acpu, 2 cores, 1 h, env `hisdac`). The rules and the evidence behind each manual fix are in
`docs/census_preprocessing.md`. Manual fixes live in `configs/nhgis_crosswalk.csv`,
`configs/nhgis_manual_fills.csv` and `configs/nhgis_reconstructed.csv`. Edit those, not the code.

**Status:** code written 2026-09-30, tested only on synthetic data on the laptop. Not yet run on Alpine.

## Inputs / outputs

| | Path |
|---|---|
| population CSV | `/projects/jaju1407/data/raw/nhgis/nhgis0001_ts_nominal_county.csv` (GISJOIN, YEAR, STATE, COUNTY, NAME, A00AA) |
| boundaries | `/projects/jaju1407/data/raw/nhgis/nhgis0001_shape/**/US_county_{YEAR}*.shp`, exactly one per year |
| outputs | `/projects/jaju1407/data/processed/census/counties_{YEAR}.gpkg`, `qa_report.csv`, `dropped_rows.csv` |
| copies for git | `results/census/qa_report.csv`, `results/census/dropped_rows.csv` |

GPKG columns: `GISJOIN, year, state, name, pop, status, area_km2, geometry` (layer `counties`).
`pop` is float; NaN means no data. `status` is one of `ok`, `nodata_unenumerated`, `nodata_zero`, `manual_fill`.
GDAL reads the CRS back as "NAD83 / Conus Albers" (EPSG:5070). That is the same projection as ESRI:102039, just a different name for it.

## 1. Sync + preflight (login node)

```bash
cd /projects/jaju1407/HPC
git pull
git log --oneline -1
mkdir -p logs
ls /projects/jaju1407/data/raw/nhgis/
find /projects/jaju1407/data/raw/nhgis/nhgis0001_shape -name 'US_county_*.shp' | sort
```

Good: 22 `.shp` files (1810…2020), one per year. If the shapefiles are still `.zip`s, unzip them first.
If one year matches two files, the job stops and lists them.

## 2. Quick test: 1810, 1820, 1900 (login node)

These three years exercise every special rule: multi-county groups, the two reconstructed 1820 D.C. units, the crosswalk, and the manual fills.

```bash
cd /projects/jaju1407/HPC
jid=$(sbatch --parsable sbatch/census_prepare.sh --years 1810 1820 1900)
echo "submitted $jid"
```

## 3. Monitor (login node)

```bash
squeue -u jaju1407
tail -n 60 logs/census_prepare.$jid.out
```

Check these lines in the log:
- `crosswalk 1900: G5105100 (Alexandria city) -> G5100035 (Alexandria...)`, and later `summed 2 CSV rows into G5100035` (6,430 + Alexandria city).
- `multi-county group, Massachusetts: state county-row sum=700,745; group rows sum=700,745 (equal=True)`
- `reconstructed G1100010 ...: dissolved 3 1830 polygons` and `reconstructed G5100035 ...: dissolved 2 1830 polygons`, then manual fills of 23,336 and 9,703.
- the 1810 `wrote ...` line: `CONUS pop ... | expected ~7,239,881 (diff ...)`
- `DONE` then `== done`

## 4. Full run (login node)

Once the quick test looks right:

```bash
cd /projects/jaju1407/HPC
jid=$(sbatch --parsable sbatch/census_prepare.sh)
echo "submitted $jid"
```

## 5. If it fails

| Symptom | Fix |
|---|---|
| `ERROR: crosswalk targets missing ... candidates: [...]` | put the right GISJOIN from the candidates list into `configs/nhgis_crosswalk.csv` (laptop), push, pull, resubmit |
| `ERROR: need exactly one US_county_{YEAR}*.shp` | unzip the missing year, or remove the duplicate |
| `ERROR: ... missing columns` | the CSV has a different layout than expected (e.g. wide); send Claude the columns listed in the error |
| `ERROR: manual fill ... has no boundary` | that GISJOIN doesn't exist in that year's shapefile; fix `configs/nhgis_manual_fills.csv` |
| `ERROR: donor polygons missing` | a 1830 GISJOIN in `configs/nhgis_reconstructed.csv` isn't in the 1830 shapefile; fix the ID |
| `CANCELLED ... DUE TO TIME LIMIT` | raise `--time` in `sbatch/census_prepare.sh` |

## 6. Close the loop (login node)

```bash
cd /projects/jaju1407/HPC
git add logs/census_prepare.$jid.out results/census/
git commit -m "run: census_prepare $jid"
git push
```

Then tell Claude to pull.

## Notes

- 2026-09-30: runbook written.
- 2026-09-30: updated to the final `docs/census_preprocessing.md`. Alexandria County target is `G5100035` (confirmed by the user from the 1900 CSV). 1820 D.C. is now two units: `G1100010` (present-day area, 23,336) and `G5100035` (Alexandria side, 9,703). `G5100035` was chosen because NHGIS uses that code for the same area as a Virginia county in 1900. Sources: Forstall (1996).
