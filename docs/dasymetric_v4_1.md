# Dasymetric Mapping v4.1: PLURAL-1 distance features (Massachusetts)

v4.1 = v3.4 (`docs/dasymetric_v3_4.md`: eras E1 1810–1930 and E23 1940–2020, no `ntl`, `folds_from: v2`, RF with
the usual search) + the yearly GDW water mask of v4 (`water_mask: yearly`, `docs/dasymetric_v4.md`) + five
distance features from PLURAL-1 in E23. Terrain (`elev`, `slope`) is **not** included: in v4 it most likely
overfit the few Massachusetts counties and is re-tested on CONUS (`docs/open_items.md`, 2026-10-20).
`compare_with: v3_4`, so the comparison isolates the distance features (plus the 0.35 % of cells the GDW mask
changes, which v4 showed to be negligible).

Last updated: 2026-10-23 (design; not run yet)

| Era | Years | Features | Rows |
|---|---|---|---|
| E1 | 1810–1930 | bui, bldg_size, mu_ratio, dist_built, year (= v3.4) | 188 |
| E23 | 1940–2020 | + res_share, rent_share, **d_10k, d_20k, d_50k, d_100k, d_250k** | 126 |

E1 stays as in v3.4: PLURAL starts in 1930, so most E1 years would have no value.

## Why distances only (decided with Stefan 2026-10-23)

PLURAL-1 combines seven terms per place: place population, focal population density and the distances to the
nearest places of five size classes (Uhl et al. 2023; `docs/data_sources.md`). The index itself is computed at
place points, not at cells, and two of its terms are population (place population, focal population density):
used as predictors they would leak the target and the tract validation counts. v4.1 therefore recomputes only
the five **distance terms**, from every 250 m cell centre, and leaves the two population terms out. The distance
terms still use census place populations to define the classes, but only through which class a place falls in,
and the places are mostly outside the cell's own county.

## Features

`d_<class>` = straight-line distance (km) from the cell centre to the nearest place of that size class in that
year, among **all US places in PLURAL** (the nearest large city can lie outside the window, e.g. New York for
western Massachusetts).

| Feature | Place population |
|---|---|
| `d_10k` | 10,000 ≤ pop < 20,000 |
| `d_20k` | 20,000 ≤ pop < 50,000 |
| `d_50k` | 50,000 ≤ pop < 100,000 |
| `d_100k` | 100,000 ≤ pop < 250,000 |
| `d_250k` | ≥ 250,000 |

County value = mean over the county's unmasked cells, as for every feature. SHAP: one group `Place distance`
for the five (grouped importance); the summary plot shows each feature.

## Inputs (Alpine)

- `/projects/jaju1407/data/raw/plural/plural_2023/PLURAL_CSV/PLURAL_CSV/place_level_remoteness_all_scaled_across_years.csv`:
  `placeid`, `place_name`, `state_name`, `placepop_{1930…2010, 2018}` (0 = no record that year). No coordinates.
- `/projects/jaju1407/data/raw/plural/plural_2023/PLURAL_SHP/PLURAL_SHP/plural_indices_scaled_across_years_{YEAR}.shp`:
  points with `placeid` (and `placepop`), ESRI:102003. The yearly files are merged into one point per `placeid`
  (latest year it appears in; the log reports how far a place's point moves between years) and reprojected to
  the cutout CRS (ESRI:102039).

## Steps (`src/grid/place_dist.py`, settings `place_dist:` in `configs/study_area.yaml`)

1. Read the CSV populations and the merged points.
2. **Gap fill** (New England towns): a place with 0 in PLURAL year Y and > 0 in both neighbouring PLURAL years
   gets the mean of the two neighbours' original values. Neighbours are the adjacent PLURAL years, so 2010 is
   filled from 2000 and 2018; 1930 and 2018 are never filled; two zeros in a row are not filled. Reason: in
   Massachusetts, towns such as Brookline, Arlington and Framingham drop out in 1950 and 1970 (MA places ≥ 10k in
   the raw CSV: 1930 39, 1940 78, 1950 47, 1960 75, 1970 48, 1980 78). The log lists fills per state and year
   (also `qa/place_dist_fills.csv`), the Massachusetts places that were filled, and the count of MA places
   ≥ 10k before and after the fill, which should become smooth.
3. Size class of each place from its (filled) population.
4. Study year → PLURAL year: 1940–2010 the same year, 2020 → 2018.
5. Nearest-place distance per class for every cell of the window (scipy `cKDTree`, row blocks), written as
   `layers/PLACEDIST/<class>/{YEAR}_<class>.tif` (float32 km), 1940–2020 × 5 classes = 45 layers.
   `src/dasymetric/common.py` maps `d_<class>` to the layer `PLACEDIST/d_<class>`.

QA (`qa/place_dist_qa.csv`, copied to `results/cutout/massachusetts/`): places per class and year, places
≥ 10k without a point, min/mean/max km over the study cells per layer, and the QA points:

| Point | Layer | Expected |
|---|---|---|
| Boston (−71.06, 42.36) | `d_250k` | ≤ 5 km in every year (≈ 0) |
| Worcester (−71.80, 42.26) | `d_100k` | ≤ 5 km in every year (Worcester 160–205k throughout) |
| Pittsfield, Berkshire (−73.25, 42.45) | `d_250k` | ≥ 120 km (nearest ≥ 250k: Boston, Providence or New York, ~170–200 km) |

The job fails if a class has no place in a year, a PLURAL column or shapefile is missing, or a distance is not
finite. A QA point outside its range is a warning.

## Limits

- Places are points, not boundaries: cells inside a large city but far from its point get a positive
  distance (Boston's edge is several km from its point).
- `Millbury 1940` has the same population as Milford (15,388), probably a matching error in PLURAL; left as is.
  The fill cannot repair it.
- A place missing in two decades in a row, or in 1930 / 2018, is not filled.
- 2020 uses PLURAL 2018 populations (class boundaries can differ slightly from the 2020 census).
- Distances are planar in ESRI:102039 (Albers equal area); scale error in the Massachusetts window is well under
  1 %, larger far from the standard parallels (fine for nearest-place ranking and km-scale features).
- With 14 Massachusetts counties in E23, five extra county-mean features risk the same overfitting as terrain in
  v4; the tract validation is the main check.

## Comparison (after the run)

Against v3.4 on the same folds and the same tract validation: county CV per era (E1 should be identical apart
from the water mask), tract MdAPE and R² of log tract density per year (`docs/validation_tract.md`), and SHAP of
`d_*` (per feature and the `Place distance` group). Expectation: the distances help where the remaining error is
the rural-over / urban-under pattern of v3.4.

## Run

`docs/runbooks/Running_Dasymetric.md`, section "v4.1". Local test of the distance and gap-fill code:
`python tests/test_place_dist.py` (hisdac env; synthetic data).

## Result (jobs 34785497 place_dist / 34785498-34785500 dasymetric / 34785501 validate_tract, code ee55448)

- QA: 45 layers written (1940-2020 x 5 classes). Gap fill: 716 place-years in the US; Massachusetts places
  >= 10k after fill 39, 78, 72, 75, 72, 78, 80, 81, 86 (1930-2010; was 47 in 1950 and 48 in 1970). Worcester
  d_100k 1.3 km and Pittsfield d_250k 166-176 km as expected; Boston d_250k 6.8 km (the Boston point sits
  away from the QA coordinate; threshold 5 km too tight, not a fault). Mass check 0 fail, tract totals QA
  0 flagged.
- **Worse than v3.4, and worse than v4.** County CV E23 R2 0.727 -> 0.694 (RMSE 0.554 -> 0.555); E1 unchanged
  (0.624 -> 0.625, as designed). Tract MdAPE 1940-2020: 43-53 % (v3.4 30-43 %, v4 37-47 %); 2020: 30.9 -> 43.0 %.
  R2 of log tract density 2020: 0.77 -> 0.67.
- SHAP (E23): the model leans on the distances: d_50k 2nd (0.19), d_20k 0.12, d_250k 0.10; rent_share drops
  from 0.43 (v4) to 0.25, bui 0.19.
- Reading: with 14 counties, county means of smooth regional distances act as county labels (as terrain in
  v4), and at cell level they pull weight along broad gradients toward the place points instead of following
  buildings. Not kept for Massachusetts; distances are re-tested on CONUS (about 3,000 counties per year).

