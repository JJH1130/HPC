# Dasymetric Mapping v4: terrain + reservoir years (Massachusetts)

v4 = v3.4 (`docs/dasymetric_v3_4.md`: eras E1 1810–1930 and E23 1940–2020, no `ntl`, `folds_from: v2`, RF
with the usual search) plus two changes. Everything else stays as in v3.4 so the effect of these two
can be read off the comparison with v3.4.

Last updated: 2026-10-20

## Changes

| Change | What | Where |
|---|---|---|
| Terrain features | `elev` = GMTED2010 mean elevation (m), averaged onto the 250 m grid; `slope` = slope in degrees computed on that 250 m elevation grid. Added to both eras; each its own SHAP group (`Elevation`, `Slope`) so the two are read separately, as in the per-feature summary plot | DEM layer: `configs/study_area.yaml` (`layers:`), `src/grid/make_cutout.py`; features: `src/dasymetric/common.py` |
| Reservoir years in the water mask | Global Dam Watch (GDW) reservoirs replace HydroLAKES `Lake_type = 2`. A reservoir counts as water only from its completion year; `water_frac` becomes one layer per study year | `water:` block of `configs/study_area.yaml` (`reservoir_source: gdw`), `src/grid/water_frac.py`; `water_mask: yearly` in `configs/model.yaml` |

### Terrain

- Source: USGS GMTED2010 `mn75_grd` (7.5 arc-seconds, ~230 m, EPSG:4326, Int16 m, nodata −32768;
  `docs/data_sources.md`).
- Cutout: GDAL warp with `average` onto the HISDAC grid (elevation is continuous), float32, written to
  `layers/DEM/DEM.tif`.
- Features (cell level): `elev` = the cell's value; `slope` = arctan(|∇z|) in degrees from central
  differences on the 250 m grid (`numpy.gradient`, spacing 250 m). Nodata (sea) is set to 0 m before both,
  and the count is logged. County value = mean over the county's unmasked cells, as for every feature.
- Slope from a 250 m mean surface is lower than slope from a 30 m DEM; it describes broad relief, not
  individual hillsides.

### Reservoir years (decided 2026-10-13, `docs/open_items.md`)

Water at 30 m = JRC occurrence ≥ 75 (no data counted as water), as in v3.1. Then, for each GDW reservoir
polygon (`GDW_reservoirs_v1_0.shp`):

| GDW record | Effective year | Pixels inside the polygon in census year Y |
|---|---|---|
| `LAKE_CTRL` = Yes or Maybe (natural lake raised by a dam) | – | JRC decides in every year (water) |
| `YEAR_DAM` > 0 and `QUALITY` 1–3 | `YEAR_DAM` | water if `YEAR_DAM` ≤ Y, else land |
| No `YEAR_DAM`, or `QUALITY` 4–5 | never | land in every year (as HydroLAKES in v3.1) |

`water_frac_Y` = area-weighted share of water pixels per 250 m cell, one layer per study year
(`layers/water_frac/{YEAR}_water_frac.tif`). The mask rule is unchanged: a cell gets weight 0 in year Y
only if `water_frac_Y` = 1 and BUI_Y = 0.

Known limits: `YEAR_DAM` is the construction or completion year, not the filling year (Quabbin: dam 1939,
filled by 1946, so 1940 is treated as water). Dam-raised natural lakes not flagged in `LAKE_CTRL` (e.g.,
Moosehead 1835, Chesuncook 1916) are land before their dam year, the same error as in v3.1 for those years.

## QA

- DEM cutout log: `DEM ... warped (average) -> float32` with min/max in metres and the nodata cell count.
- `water_frac` log: GDW counts (natural lakes kept, dated, never water), per year the share of study cells
  with `water_frac = 1`, and the QA points: Quabbin 1930 `expect dry`, Quabbin 2020 `expect full_water`.
- Features log: `DEM: N nodata cells in the window set to 0 m (sea)`.
- Usual checks: mass preservation, totals QA in `validate_tract`.

## Comparison

Against v3.4 on the same folds and the same tract validation: county CV per era, tract MdAPE and R² of log
tract density per year (`docs/validation_tract.md`), and SHAP of `elev` and `slope` separately (summary plot, per-feature and grouped importance). Expectation:
terrain helps most where buildings are sparse (early decades, rural tracts); reservoir years change only the
cells of reservoirs built after 1810.

## Run

`docs/runbooks/Running_Dasymetric.md`, section "v4".

## Provisional

PLURAL (urban–rural index, PLURAL-1 scaled across years; `docs/data_sources.md`) is not yet included.
