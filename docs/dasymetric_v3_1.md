# Dasymetric Mapping v3.1: Water Mask (Chapter 1, Massachusetts test)

Adds a water mask to v3 (`docs/dasymetric_v3.md`). Everything else stays as in v3:
eras, features (raw values, no transformation), folds, model, SHAP, maps. Water is
**not** a model feature, and no feature is rescaled by water or land share.

Last updated: 2026-10-06 (third revision; supersedes the earlier drafts that
multiplied weights by land share or divided BUI by land share)

## Principle

Exclude only cells where people certainly cannot live; let the model handle
everything else.

```
masked_cell = (water_frac == 1) and (BUI == 0)
w_cell      = 0                 if masked_cell
            = exp(ŷ_cell)       otherwise
pop_cell    = pop_county × w_cell / Σ_{cells in county} w
```

- A cell is masked only if every 30 m pixel in it is permanent water **and** it has
  no recorded building. Cells with buildings are never masked: buildings imply land,
  and a building record is trusted over a possible misalignment between the JRC and
  HISDAC grids.
- Partly-water cells are not adjusted. Their buildings sit on their land part, so
  BUI already reflects how much is built there, and the model assigns weight from it.
  People concentrated on a small land area are therefore not under-allocated.
- Known simplification: an unbuilt cell that is partly water receives the same
  weight as a dry unbuilt cell. Both weights are small, so the effect is minor.

Why not a feature: county-mean water fractions span a narrow range (mostly near
0–0.2) while cells span 0–1, so no county-trained tree model (RF or boosting) can
learn the cell-level effect.

## Water fraction layer (static, no year)

Inputs (see `docs/data_sources.md`):
- JRC Global Surface Water occurrence v1.4 (1984–2021), 30 m, 10° tiles in
  `/projects/jaju1407/data/raw/water/jrc_occurrence/occurrence_{LON}_{LAT}v1_4_2021.tif`.
  Select every tile that intersects the cutout window automatically (Massachusetts
  needs `80W_50N` and `70W_50N` because the 1810 window extends into Maine). Stop
  with the missing tile names if a needed tile is absent.
- HydroLAKES v1.0 polygons:
  `/projects/jaju1407/data/raw/water/HydroLAKES_polys_v10_shp/HydroLAKES_polys_v10.shp`

Steps:
1. Permanent water at 30 m: occurrence ≥ 75.
2. Remove reservoirs: set to non-water every 30 m pixel inside a HydroLAKES polygon
   with `Lake_type = 2`. Keep `Lake_type` 1 (lake) and 3 (lake control) as water.
   Reservoir handling over time is deferred; reservoir areas count as land in all years.
3. Aggregate to the HISDAC 250 m grid: `water_frac` = share of 30 m water pixels in
   each 250 m cell, float32, 0–1.
4. Write `layers/water_frac/water_frac.tif` in the cutout (same window and grid).
   Natural lakes and rivers are assumed stable over 1810–2020 (limitation to note).

Read only the JRC tiles and HydroLAKES features intersecting the cutout window.

## Target and county features

Masked cells are removed from the county before anything is computed:

```
area_km2 (county) = 0.0625 × number of unmasked cells
y = log(pop / area_km2)
county feature   = mean of the cell feature over unmasked cells
```

Use cell-count area for consistency with the grid (v1–v3: cell area vs polygon area
within 1%). The mask depends on the year (through BUI), so compute it per year.
If a county has no unmasked cell, stop with an error.

## QA

- `water_frac` range 0–1; per year, number and share of masked cells inside the
  study counties.
- Quabbin Reservoir (about −72.3, 42.4): mostly `water_frac` = 0 (reservoir
  removed). A large natural lake or the Connecticut River: masked cells present.
- Cells with `water_frac` = 1 and BUI > 0: count per year (expected small; these are
  kept, not masked).
- Mass preservation unchanged (< 1e-6). No population in masked cells.

## Comparison with v3

Same folds and eras. Report CV per era (v3.1 vs v3) and 2020 maps side by side.
Expect changes on large lakes, wide rivers and coastlines; CV may change slightly
because county area now excludes masked water.

## Outputs

`/scratch/alpine/jaju1407/hisdac/dasymetric/massachusetts/v3_1/`, same layout as v3.
Copy small files and PNGs to `results/dasymetric/massachusetts/v3_1/`. Keep v1–v3
outputs unchanged.

## Deferred

- Occurrence threshold sensitivity (50, 75, 90) at CONUS scale.
- Reservoir construction years (GRanD) so reservoirs are water only after completion.
- Distance to water or river as a feature (HydroRIVERS).
