"""Synthetic test of the CONUS changes to src/grid/water_frac.py, runnable without the cluster:

    python tests/test_water_frac_parallel.py   (needs the hisdac env: numpy, pandas, geopandas, rasterio, pyproj)

Builds one JRC-like occurrence tile (EPSG:4326) and a GDW-like reservoir polygon (dam year 1950) in a temporary
folder, then checks on a small EPSG:5070 window that
  - the blocks computed in 2 worker processes give exactly the one-process result (yearly layers + no-data share)
  - the reservoir is land in 1940 and water in 1960
  - with `need` (only_zone_blocks) blocks without a study cell stay NaN and the others are unchanged
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "grid"))

import geopandas as gpd  # noqa: E402
import rasterio  # noqa: E402
from affine import Affine  # noqa: E402
from pyproj import CRS, Transformer  # noqa: E402
from rasterio.warp import transform_bounds  # noqa: E402
from shapely.geometry import box  # noqa: E402

import water_frac  # noqa: E402

CUT_CRS = CRS.from_epsg(5070)
H, W, BLOCK = 40, 52, 16


def make_inputs(tmp: Path):
    res = 0.001
    tr = Affine(res, 0, -101.0, 0, -res, 41.0)
    rng = np.random.default_rng(3)
    occ = rng.integers(0, 60, (2000, 2000)).astype("uint8")  # mostly land
    occ[980:1010, 980:1030] = 100  # a lake near the window centre (lon -100, lat 40) ...
    occ[1030:1033, 960:1040] = 255  # a JRC no-data stripe
    jrc = tmp / "jrc"
    jrc.mkdir()
    with rasterio.open(jrc / "occurrence_100W_41Nv1_4_2021.tif", "w", driver="GTiff", width=2000, height=2000,
                       count=1, dtype="uint8", crs="EPSG:4326", transform=tr) as dst:
        dst.write(occ, 1)
    # ... half of it a reservoir completed in 1950
    gdw = gpd.GeoDataFrame({"GDW_ID": [1], "RES_NAME": ["Test Res"], "DAM_NAME": ["Test Dam"], "YEAR_DAM": [1950],
                            "QUALITY": ["2: Good"], "LAKE_CTRL": ["No"]},
                           geometry=[box(-100.0, 39.99, -99.97, 40.02)], crs=4326)
    gdw.to_file(tmp / "gdw.shp")
    to_xy = Transformer.from_crs(4326, CUT_CRS, always_xy=True)
    cx, cy = to_xy.transform(-100.0, 40.0)
    transform = Affine(250.0, 0, cx - W / 2 * 250.0 + 11.0, 0, -250.0, cy + H / 2 * 250.0 - 5.0)
    wcfg = {"jrc_dir": str(jrc), "jrc_glob": "occurrence_*.tif", "occurrence_min": 75, "nodata_as_water": True,
            "block": BLOCK, "gdw": {"path": str(tmp / "gdw.shp"), "quality_max": 3, "lake_ctrl_water": ["Yes", "Maybe"]}}
    return wcfg, transform


def main():
    tmp = Path(tempfile.mkdtemp())
    try:
        wcfg, transform = make_inputs(tmp)
        bounds = rasterio.transform.array_bounds(H, W, transform)
        bll = transform_bounds(CUT_CRS, "EPSG:4326", bounds[0], bounds[1], bounds[2], bounds[3], densify_pts=21)
        tiles, res = water_frac.jrc_tiles(wcfg, bll)
        gdw = water_frac.reservoirs_gdw(wcfg, bll)
        years = [1940, 1960]
        args = (wcfg, tiles, res, None, transform, H, W, CUT_CRS)
        one, nd1, st1 = water_frac.cell_shares(*args, res_years=gdw, years=years, workers=1)
        two, nd2, st2 = water_frac.cell_shares(*args, res_years=gdw, years=years, workers=2)
        for y in years:
            assert np.array_equal(one[y], two[y], equal_nan=True), y
        assert np.array_equal(nd1, nd2, equal_nan=True) and st1 == st2
        assert not np.isnan(one[1960]).any()
        assert st1["reservoir_pixels_water_1960"] > 0 == st1["reservoir_pixels_water_1940"]
        assert (one[1960] >= one[1940]).all() and (one[1960] > one[1940]).any()
        assert np.nanmax(nd1) > 0  # the no-data stripe is in the window
        print(f"ok workers: 2 processes == 1 | reservoir water pixels 1940 {st1['reservoir_pixels_water_1940']}, "
              f"1960 {st1['reservoir_pixels_water_1960']}")

        need = np.zeros((H, W), bool)
        need[2:10, 3:12] = True  # only block (0, 0) holds study cells
        part, _, _ = water_frac.cell_shares(*args, res_years=gdw, years=years, need=need, workers=2)
        for y in years:
            assert np.array_equal(part[y][:BLOCK, :BLOCK], one[y][:BLOCK, :BLOCK])
            rest = part[y].copy()
            rest[:BLOCK, :BLOCK] = 0
            assert np.isnan(rest).sum() == H * W - BLOCK * BLOCK
        print("ok only_zone_blocks: blocks without study cells stay NaN, the rest unchanged")
        print("ALL OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
