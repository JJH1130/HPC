"""Synthetic test of src/grid/place_dist.py (gap fill + nearest-place distance), runnable without the cluster:

    python tests/test_place_dist.py        (needs the hisdac env: numpy, pandas, scipy, geopandas, rasterio)

Builds a small cutout (window.json on an ESRI:102039 grid), a PLURAL-like CSV and yearly point shapefiles in
ESRI:102003 in a temporary folder, runs place_dist.main() and checks the layers against brute-force distances.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "grid"))

import geopandas as gpd  # noqa: E402
import rasterio  # noqa: E402
import yaml  # noqa: E402
from affine import Affine  # noqa: E402
from pyproj import CRS, Transformer  # noqa: E402
from shapely.geometry import Point  # noqa: E402

import place_dist  # noqa: E402

PLURAL_YEARS = [1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2018]
CUT_CRS = CRS.from_user_input("ESRI:102039")


def test_fill_gaps():
    pop = pd.DataFrame({1930: [5, 0, 5, 5, 0], 1940: [0, 0, 6, 0, 3], 1950: [7, 8, 0, 0, 0], 1960: [9, 9, 10, 9, 0]},
                       index=["a", "b", "c", "d", "e"])
    years = [1930, 1940, 1950, 1960]
    out, filled = place_dist.fill_gaps(pop, years)
    assert out.loc["a", 1940] == 6.0 and filled.loc["a", 1940]          # 5, 0, 7 -> mean 6
    assert out.loc["b", 1940] == 0 and not filled.loc["b", 1940]        # no earlier value: not filled
    assert out.loc["c", 1950] == 8.0 and filled.loc["c", 1950]          # 6, 0, 10 -> 8
    assert out.loc["d", 1940] == 0 and out.loc["d", 1950] == 0          # two zeros in a row: not filled
    assert not filled.loc["e"].any()                                    # 3, 0, 0: next year is 0
    assert not filled[1930].any() and not filled[1960].any()           # first/last year never filled
    assert int(filled.values.sum()) == 2
    print("ok fill_gaps")


def test_norm_id():
    s = place_dist.norm_id(["007", "7.0", " 12 ", "G2500", 15])
    assert s.tolist() == ["7", "7", "12", "G2500", "15"], s.tolist()
    print("ok norm_id")


def make_inputs(tmp: Path):
    # grid: 40 rows x 60 cols of 250 m in ESRI:102039 around Boston
    to_cut = Transformer.from_crs(4326, CUT_CRS, always_xy=True)
    bx, by = to_cut.transform(-71.06, 42.36)
    x0, y0 = bx - 30 * 250.0 - 3.0, by + 20 * 250.0 + 7.0  # odd offsets: cell centres not on round numbers
    transform = Affine(250.0, 0, x0, 0, -250.0, y0)
    H, W = 40, 60
    cut = tmp / "cutouts" / "synthetic"
    cut.mkdir(parents=True)
    (cut / "window.json").write_text(json.dumps({"transform": list(transform)[:6], "height": H, "width": W,
                                                 "crs_wkt": CUT_CRS.to_wkt()}))
    places = pd.DataFrame([
        # placeid, name, state, lon, lat, pop per PLURAL year
        ("100", "Boston", "Massachusetts", -71.06, 42.36, [781188, 770816, 801444, 697197, 641071, 562994, 574283,
                                                             589141, 617594, 694583]),
        ("200", "Brookline", "Massachusetts", -71.12, 42.33, [47490, 49786, 0, 54044, 0, 55062, 54718, 57107,
                                                              58732, 59180]),
        ("300", "Far City", "New York", -73.95, 40.75, [300000] * 10),            # outside the window
        ("400", "Ghost", "Massachusetts", -71.30, 42.40, [0, 12000, 0, 0, 15000, 0, 0, 0, 0, 0]),
        ("500", "Lowell", "Massachusetts", -71.31, 42.63, [100234, 101389, 97249, 92107, 94239, 92418, 103439,
                                                           105167, 106519, 110997]),
        ("600", "Small", "Massachusetts", -70.95, 42.45, [9000] * 9 + [21000]),
        ("700", "Mid", "Rhode Island", -71.40, 42.25, [60000] * 10),
        # fillers so that every class has a place in every year
        ("800", "Ten", "Maine", -70.25, 43.65, [15000] * 10),
        ("900", "Twenty", "Connecticut", -72.68, 41.76, [30000] * 10),
        ("1000", "Hundred", "New Hampshire", -71.46, 42.99, [150000] * 10),
    ], columns=["placeid", "place_name", "state_name", "lon", "lat", "pop"])
    csv = pd.DataFrame({"placeid": places["placeid"], "place_name": places["place_name"],
                        "state_name": places["state_name"]})
    for i, y in enumerate(PLURAL_YEARS):
        csv[f"placepop_{y}"] = [p[i] for p in places["pop"]]
    csv.to_csv(tmp / "plural.csv", index=False)
    shp_dir = tmp / "shp"
    shp_dir.mkdir()
    for i, y in enumerate(PLURAL_YEARS):
        keep = [p[i] > 0 for p in places["pop"]]  # like PLURAL: a place is in a year's file only with a record
        sub = places[keep]
        gdf = gpd.GeoDataFrame({"placeid": sub["placeid"].astype(int), "placepop": [p[i] for p in sub["pop"]]},
                               geometry=[Point(a, b) for a, b in zip(sub["lon"], sub["lat"])], crs=4326)
        gdf.to_crs("ESRI:102003").to_file(shp_dir / f"plural_indices_scaled_across_years_{y}.shp")
    cfg = {"name": "synthetic", "states": ["Massachusetts"], "years": {"start": 1930, "stop": 2020, "step": 10},
           "grid_reference": "BUI", "layers": [],
           "place_dist": {"csv": str(tmp / "plural.csv"),
                          "shp": str(shp_dir / "plural_indices_scaled_across_years_{YEAR}.shp"),
                          "shp_crs": "ESRI:102003", "pop_col": "placepop_{YEAR}", "plural_years": PLURAL_YEARS,
                          "year_map": {2020: 2018}, "first_year": 1940, "fill_gaps": True,
                          "classes": {"d_10k": [10000, 20000], "d_20k": [20000, 50000], "d_50k": [50000, 100000],
                                      "d_100k": [100000, 250000], "d_250k": [250000, None]},
                          "check_state": "Massachusetts", "block": 7,
                          "qa_points": [{"name": "Boston", "lon": -71.06, "lat": 42.36, "layer": "d_250k",
                                         "max_km": 1}]}}
    cfg_path = tmp / "study.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return cfg_path, cut, places, transform, H, W


def brute_km(places, idx, transform, H, W):
    to_cut = Transformer.from_crs(4326, CUT_CRS, always_xy=True)
    px, py = to_cut.transform(places.loc[idx, "lon"].to_numpy(), places.loc[idx, "lat"].to_numpy())
    C, R = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    X, Y = transform.c + C * transform.a, transform.f + R * transform.e
    d = np.min(np.hypot(X[..., None] - px, Y[..., None] - py), axis=-1)
    return d / 1000.0


def read(cut, cls, year):
    with rasterio.open(cut / "layers" / "PLACEDIST" / cls / f"{year}_{cls}.tif") as src:
        return src.read(1)


def test_end_to_end():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        cfg_path, cut, places, transform, H, W = make_inputs(tmp)
        place_dist.main(["--config", str(cfg_path), "--cutout-root", str(tmp / "cutouts")])
        layers = sorted(p.relative_to(cut / "layers").as_posix() for p in (cut / "layers").rglob("*.tif"))
        assert len(layers) == 9 * 5, len(layers)  # 1940-2020, 5 classes
        P = places.set_index("placeid")
        # d_250k: Boston every year -> ~0 km at Boston's cell (<= half a cell diagonal)
        for y in (1940, 1970, 2020):
            d = read(cut, "d_250k", y)
            want = brute_km(P, ["100", "300"], transform, H, W)
            assert np.allclose(d, want, atol=1e-3), np.abs(d - want).max()
            c, r = map(int, ~transform * Transformer.from_crs(4326, CUT_CRS, always_xy=True).transform(-71.06, 42.36))
            assert d[r, c] <= 0.18, d[r, c]
        # Brookline is 0 in 1950 and 1970 -> filled (49786+54044)/2 = 51915 and (54044+55062)/2 -> d_50k class
        for y in (1950, 1970):
            d = read(cut, "d_50k", y)
            assert np.allclose(d, brute_km(P, ["200", "700"], transform, H, W), atol=1e-3), y
        # Ghost: 12000 in 1940 (d_10k), 0 in 1950 between 12000 and 0 -> not filled
        assert np.allclose(read(cut, "d_10k", 1940), brute_km(P, ["400", "800"], transform, H, W), atol=1e-3)
        # Lowell: 1950 97249 -> d_50k with Brookline; 1990 103439 -> d_100k
        assert np.allclose(read(cut, "d_50k", 1960), brute_km(P, ["200", "500", "700"], transform, H, W), atol=1e-3)
        assert np.allclose(read(cut, "d_100k", 1990), brute_km(P, ["500", "1000"], transform, H, W), atol=1e-3)
        # 2020 uses PLURAL 2018: Small = 21000 -> d_20k (it is 9000, no class, in 2010)
        assert np.allclose(read(cut, "d_20k", 2020), brute_km(P, ["600", "900"], transform, H, W), atol=1e-3)
        qa = pd.read_csv(cut / "qa" / "place_dist_qa.csv", index_col="item")["value"]
        assert int(qa["filled place-years 1950"]) == 1 and int(qa["filled place-years 1970"]) == 1
        assert int(qa["filled place-years 1960"]) == 0 and int(qa["filled place-years 2018"]) == 0
        assert qa["QA Boston 2020 d_250k"] == "ok"
        fills = pd.read_csv(cut / "qa" / "place_dist_fills.csv", index_col="state_name")
        assert fills.loc["Massachusetts", "1950"] == 1 and fills.loc["Massachusetts", "1970"] == 1
    print("ok end_to_end")


def test_missing_class_fails():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        cfg_path, *_ = make_inputs(tmp)
        cfg = yaml.safe_load(cfg_path.read_text())
        cfg["place_dist"]["classes"]["d_1m"] = [1000000, None]
        cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
        try:
            place_dist.main(["--config", str(cfg_path), "--cutout-root", str(tmp / "cutouts"), "--years", "1940"])
        except SystemExit as e:
            assert "no place in class d_1m" in str(e), e
            print("ok missing_class_fails")
            return
        raise AssertionError("expected SystemExit")


if __name__ == "__main__":
    test_norm_id()
    test_fill_gaps()
    test_end_to_end()
    test_missing_class_fails()
    print("ALL OK")
