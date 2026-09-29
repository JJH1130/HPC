# Study-Area Cutout (Chapter 1)

Rules for cutting a test region out of the HISDAC-US V2 rasters and building the
per-year county zone grids that link each 250 m cell to its census county.

Last updated: 2026-09-30

Code: `src/grid/make_cutout.py` · Config: `configs/study_area.yaml` · Job:
`sbatch/grid_cutout.sh` · Runbook: `docs/runbooks/Making_Cutout.md`

## Inputs

| Item | Path | Notes |
|---|---|---|
| Yearly HISDAC layers | `/pl/active/Leyk_Lab/data/HISDAC_US_V2/{LAYER}/{YEAR}_{LAYER}.tif` | BUI, BUPL, BUPR, BUA; 22 years, 1810–2020. **Read only** |
| Single-file HISDAC layers | `/pl/active/Leyk_Lab/data/HISDAC_US_V2/**/*FBUY*.tif`, `**/*NobuiltYear*.tif` | No year; cut once. Each glob must match exactly one file |
| County units | `/projects/jaju1407/data/processed/census/counties_{YEAR}.gpkg` | Output of `docs/census_preprocessing.md` |

## Configuration (`configs/study_area.yaml`)

| Key | Current value | Meaning |
|---|---|---|
| `name` | `massachusetts` | Output folder name |
| `states` | `[Massachusetts]` | Values of the county `state` column (case-insensitive). `all` = all CONUS counties; the same code runs unchanged |
| `years` | 1810–2020, step 10 | 22 years |
| `hisdac.yearly_layers` | BUI, BUPL, BUPR, BUA | Cut for every year |
| `hisdac.static_layers` | FBUY, NobuiltYear | Cut once |

## Outputs

Written to `/scratch/alpine/jaju1407/hisdac/cutouts/{name}/`. This is scratch storage: files are
purged 90 days after creation, so rerun the job to rebuild them.

| File | Content |
|---|---|
| `window.json` | The shared window: HISDAC column/row offset, width, height, bounds, transform, CRS, reference raster |
| `layers/{LAYER}/{YEAR}_{LAYER}.tif` | Yearly layers clipped to the window. int32, deflate |
| `layers/{LAYER}/<source file name>` | FBUY and NobuiltYear clipped to the window |
| `zones/zones_{YEAR}.tif` | County ID per cell (uint16). 0 = nodata |
| `zones/zones_{YEAR}.csv` | `zone_id`, `GISJOIN`, `state`, `name`, `pop`, `status`, `area_km2` for the selected counties |
| `cutout_qa.csv` | Per year and county: `n_cells`, `cell_area_km2` = n_cells × 0.0625, `area_ratio` = cell_area_km2 / area_km2 |

Copies of `window.json`, `cutout_qa.csv` and `zones/*.csv` are also saved to `results/cutout/{name}/` in git.

## Processing rules (applied in order)

1. **Select counties per year.** From each `counties_{YEAR}.gpkg`, keep the counties whose
   `state` is listed in the config. The state's area changes over time: 1810 Massachusetts
   includes Maine.
2. **One window for all years.** Take the union of the selected counties' bounds over all 22
   years and snap it outward to the HISDAC grid (same origin, 250 m cells, ESRI:102039). Every
   year and layer uses this window, so all outputs line up cell for cell. If the bounds go past
   the HISDAC extent, the window is clipped and a warning is logged.
3. **Check the inputs before cutting.** Every input file must exist, and all rasters must share
   one grid (transform, size, CRS). The job stops before cutting anything if either check fails.
4. **Windowed reads.** Each layer is read only inside the window, never the whole CONUS array.
5. **Store as int32 with deflate compression.** Values are integers. **0 means "no building"
   and is never nodata.** The source nodata value (or NaN) is kept as nodata. If the source
   declares nodata = 0, that is ignored with a warning. Non-integer values stop the job.
6. **Zone grids.** Each selected county is rasterized by cell center (`all_touched=False`).
   `zone_id` is the county's row number in that year's `counties_{YEAR}.gpkg` (the GPKG feature
   ID, starting at 1), so it is stable for a given census output. Cells in counties that were
   not selected, and cells outside all counties, are 0 (nodata).
7. **QA.** For every year and county, record the number of cells assigned and the ratio of
   cell area to polygon area in `cutout_qa.csv`. Counties with 0 cells trigger a warning.

## Interpreting `area_ratio`

With cell-center rasterization, `area_ratio` should be close to 1 for counties much larger than
a cell (0.0625 km²). It can be lower for coastal counties when the HISDAC extent or the
polygon's shoreline cuts off cells, and it is unstable for very small units such as
independent cities. `n_cells = 0` means the county's area is not represented in the grid, so
its population cannot be allocated. These cases need a decision; see Open items.

## Open items

- [ ] Decide how to handle counties with 0 cells (e.g., assign the cell nearest the centroid).
- [ ] Review counties with `area_ratio` far from 1 after the first Massachusetts run.
- [ ] Before switching to `states: all`, raise `--ntasks` and `--time` in `sbatch/grid_cutout.sh`
  (the CONUS window is about 1 GB per layer-year).
