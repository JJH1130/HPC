# Dasymetric Mapping v4: terrain + reservoir years (Massachusetts)

v4 = v3.4 (`docs/dasymetric_v3_4.md`: eras E1 1810–1930 and E23 1940–2020, no `ntl`, `folds_from: v2`, RF
with the usual search) plus two changes. Everything else stays as in v3.4 so the effect of these two
can be read off the comparison with v3.4.

Last updated: 2026-10-20 (result)

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

## Result (jobs 34662977 DEM / 34662978 water / 34662979–34662981 dasymetric + validate_tract 34662982, code 7f83c2e, 2026-10-19 cluster time)

- QA: DEM warped (average) → float32, min −116 m, max 1,873 m, **0 nodata cells** (GMTED2010 has values,
  mostly 0, over the sea: 1.3 M zero cells), so the features log has no `DEM: N nodata cells` line and the
  sea-to-0 step was not used. GDW: 280 polygons, 7 `LAKE_CTRL` lakes kept to JRC, 244 dated, 29 never water;
  Quabbin 1930 `dry: ok`, Quabbin 2020 `full_water: ok` (178 cells = 1), Connecticut River `NOT MET` (known).
  Study cells with `water_frac = 1`: 0.0071 (1810) → 0.0178 (1990–2020); v3.1 static 0.0072.
  Features: E1 188 rows, E23 126 rows. Predict: mass check 314 county-years, 0 fail. Tract totals QA 546 rows,
  0 flagged.
- Water mask, MA counties: 1940–2020 masked cells ~1,060 (v3.4) → ~2,200 (v4), +0.35 % of the cells (Quabbin
  and other post-1810 reservoirs); 1820–1930 slightly fewer than v3.4 (reservoirs land before their dam year).
- County CV (same folds, each version on its own target):

  | Era | CV RMSE v3.4 | **v4** | CV R² v3.4 | **v4** | best params v3.4 → v4 (n_est / depth / leaf / max_feat) |
  |---|---|---|---|---|---|
  | E1 | 0.780 | 0.852 | 0.624 | 0.544 | 300 / 15 / 2 / 0.33 → 500 / None / 4 / 1.0 |
  | E23 | 0.554 | 0.580 | 0.727 | 0.704 | 200 / 20 / 2 / 1.0 → 200 / 15 / 1 / 0.5 |

- Tract validation, model, all tracts (reference = v3.4; 1910/1930 = v3.1, whose E1 is v3.4's E1, since v3.4
  was validated from 1940 only):

  | Year | MdAPE ref | **v4** | R² log dens. ref | **v4** |
  |---|---|---|---|---|
  | 1910 | 62.5 | 60.8 | −0.128 | 0.001 |
  | 1930 | 52.6 | 56.4 | −0.312 | −0.409 |
  | 1940 | 43.3 | 47.1 | 0.031 | 0.132 |
  | 1950 | 40.4 | 46.3 | 0.775 | 0.750 |
  | 1960 | 37.2 | 44.0 | 0.799 | 0.752 |
  | 1970 | 33.3 | 41.3 | 0.827 | 0.796 |
  | 1980 | 32.2 | 38.0 | 0.829 | 0.796 |
  | 1990 | 30.4 | 37.7 | 0.849 | 0.814 |
  | 2000 | 29.8 | 37.3 | 0.873 | 0.839 |
  | 2010 | 30.5 | 37.6 | 0.803 | 0.771 |
  | 2020 | 30.9 | 38.0 | 0.774 | 0.743 |

  Non-small tracts: +4 to +9 pt MdAPE in every year. Small tracts (< `SMALL_CELLS` cells, 26–52 per year):
  −0.1 to −11 pt MdAPE in 1910–2010, +2.4 pt in 2020.
- SHAP (mean |SHAP|): E1 `elev` 0.190 (3rd, after `bldg_size` 0.734 and `dist_built` 0.286; rises 0.14 →
  0.29 from 1810 to 1930), `slope` 0.034 (last). E23 `slope` 0.034, `elev` 0.030 (7th and 8th of 9).
  `elev`–`slope` Spearman ρ 0.91 at county level.
- Map 2020 (`pop_2020_v3_4_vs_v4.png`): v4 is flatter, with less contrast between urban cores and suburbs and
  relief patterns in the western hills.
- **Reading (provisional):** v4 is worse than v3.4 for county CV in both eras and for tract MdAPE in 1930–2020
  (+4 to +8 pt from 1950 on). It is better only for small (rural) tracts and 1910, where terrain was expected
  to help. The mask change touches 0.35 % of the cells, so the terrain features are the likely cause. With 14–22
  counties a static county mean of `elev` can act as a county label (E1 importance rises over time with no
  physical reason), and the cell-level relief it learns then shifts people within counties. The two changes
  were not run separately, so this is not yet shown; a mask-only run (v3.4 features + `water_mask: yearly`)
  would separate them.

## Run

`docs/runbooks/Running_Dasymetric.md`, section "v4".

## Provisional

PLURAL (urban–rural index, PLURAL-1 scaled across years; `docs/data_sources.md`) is not yet included.

## Decision (2026-10-20)

No separate mask-only run: the mask change is too small to explain a drop in every year, so terrain is taken as
the cause. The Massachusetts final setup drops `elev` and `slope` and keeps the GDW yearly water mask. Terrain
is re-tested on CONUS (`docs/open_items.md`).

