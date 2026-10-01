# Study-Area Cutout (Chapter 1)

Rules for cutting a test region out of the HISDAC-US V2 rasters and building the
per-year county zone grids that link each 250 m cell to its census county.

Last updated: 2026-10-02

Code: `src/grid/make_cutout.py` · Config: `configs/study_area.yaml` · Job:
`sbatch/grid_cutout.sh` · Runbook: `docs/runbooks/Making_Cutout.md`

## Inputs

| Item | Path | Notes |
|---|---|---|
| Yearly HISDAC layers | `/pl/active/Leyk_Lab/data/HISDAC_US_V2/{LAYER}/{YEAR}_{LAYER}.tif` | BUI, BUPL, BUPR, BUA; 22 years, 1810–2020. **Read only** |
| Single-file HISDAC layers | `/pl/active/Leyk_Lab/data/HISDAC_US_V2/**/*FBUY*.tif`, `**/*NobuiltYear*.tif` | No year; cut once. Each glob must match exactly one file |
| Land use counts | `/pl/active/Leyk_Lab/data/HISDAC_US_V2/Land_Use/{CLASS}/Count_{YEAR}_{CLASS}.tif` | 8 classes: A, C, GV, I, RC, RI, RO, VL. 1940–2020 only. `Count_{YEAR}_Theme*.tif` in the same folders duplicate the class files (RO = Theme6) and are **not used** |
| External rasters (later) | any path | e.g. DEM, night lights, land cover; one config line each |
| County units | `/projects/jaju1407/data/processed/census/counties_{YEAR}.gpkg` | Output of `docs/census_preprocessing.md` |

## Configuration (`configs/study_area.yaml`)

| Key | Current value | Meaning |
|---|---|---|
| `name` | `massachusetts` | Output folder name |
| `states` | `[Massachusetts]` | Values of the county `state` column (case-insensitive). `all` = all CONUS counties; the same code runs unchanged |
| `years` | 1810–2020, step 10 | 22 years |
| `grid_reference` | `BUI` | The layer whose first file defines the grid (origin, 250 m, ESRI:102039) |
| `layers` | BUI, BUPL, BUPR, BUA, FBUY, NobuiltYear, Land_Use (8 classes) | **The only list of layers.** Adding a raster = adding one entry |

Fields of a `layers` entry (details in the comments of `configs/study_area.yaml`):

| Field | Meaning |
|---|---|
| `name` | Label and default output folder |
| `path` | Relative = under the HISDAC root, absolute = as is. `{YEAR}` and `{CLASS}` are filled in. Globs must match exactly one file. Always quoted |
| `years` | `all` (every study year), `none` (single file, cut once), or the layer's own years (`{start, stop, step}` or a list). Study years the layer lacks are skipped |
| `classes` | Optional; the entry is repeated once per class |
| `resampling` | `none` = must already be on the HISDAC grid (direct window read; stop otherwise). Otherwise the GDAL method used to warp onto the grid: `bilinear` / `average` for continuous values, `sum` for counts, `nearest` / `mode` for categories |
| `dtype` | `int32` (default) or `float32` |
| `out` | Optional output path under `layers/` |

## Outputs

Written to `/scratch/alpine/jaju1407/hisdac/cutouts/{name}/`. This is scratch storage: files are
purged 90 days after creation, so rerun the job to rebuild them.

| File | Content |
|---|---|
| `window.json` | The shared window: HISDAC column/row offset, width, height, bounds, transform, CRS, reference raster |
| `layers/{LAYER}/{YEAR}_{LAYER}.tif` | Yearly layers clipped to the window. int32 (or float32 if configured), deflate |
| `layers/{LAYER}/<source file name>` | Single-file layers (FBUY, NobuiltYear) |
| `layers/Land_Use/{CLASS}/{YEAR}_{CLASS}.tif` | Land use counts, 1940–2020 |
| `zones/zones_{YEAR}.tif` | County ID per cell (uint16). 0 = nodata (outside the selected counties) |
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
3. **Check the inputs before cutting.** Every input file for the years being written must exist.
   Each yearly layer's **first year is checked even when that year isn't being written** (e.g.,
   every Land_Use class folder must contain its 1940 file). This catches file-naming differences on
   any run. When a file is missing, the error lists what the folder does contain. Layers with
   `resampling: none` must be on the HISDAC grid (same CRS, same cell size, origin offset by whole
   cells). The job stops before cutting anything if any check fails.
4. **Layers on the HISDAC grid: windowed read.** Only the window is read, never the whole CONUS
   array. **0 means "no building" and is never nodata.** The source nodata value (or NaN) is kept
   as nodata. If the source declares nodata = 0, it is ignored with a warning. For int32 layers,
   non-integer values stop the job.
5. **Layers on other grids (external rasters): GDAL warp** onto the window with the layer's
   `resampling` method. The source's declared nodata is honored, and cells the source doesn't
   cover become nodata. For int32 layers the warped values are rounded (e.g., `sum` gives
   fractional counts at partial coverage).
6. **Store with deflate compression**, as int32 or float32 per layer.
7. **Zone grids.** Each selected county is rasterized by cell center (`all_touched=False`).
   `zone_id` is the county's row number in that year's `counties_{YEAR}.gpkg` (the GPKG feature
   ID, starting at 1), so it is stable for a given census output. Cells in counties that were
   not selected, and cells outside all counties, are 0 (nodata).
8. **QA.** For every year and county, record the number of cells assigned and the ratio of
   cell area to polygon area in `cutout_qa.csv`. Counties with 0 cells trigger a warning.

**NobuiltYear is a count, not a year.** Each cell holds the number of built structures (records)
with no built year (HISDAC README: "built structures without built year"). Values are whole-number
counts (0–733 checked around Boston; a maximum of 2744 is normal), so int32 is correct.

**Downstream stages use only cells with zone > 0.** In the layers, 0 mixes "no building" with
"outside the study counties", so the two are always told apart with `zones/zones_{YEAR}.tif`,
never with the layer values.

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
