"""Synthetic test of the CONUS changes to the dasymetric steps, runnable without the cluster:

    python tests/test_conus_dasymetric.py      (needs the hisdac env: numpy, pandas, scipy, sklearn, geopandas,
                                                rasterio; `shap` and the figures module plots.py are stubs here)

Builds a small cutout (48 counties in 4 states, years 1960 + 2010, BUI/BUPL/BUPR/BUA/Land_Use/yearly water_frac)
in a temporary folder, a split table with make_split.py, and checks:
  - county_features in strips (block_rows) = the whole-window computation
  - train with `split`: test counties are not in the training / CV rows; test score reported
  - predict in strips = whole window with the same model; mass preserved; no_value / zero_pop counties and
    cells outside counties are NoData; test counties are allocated; --measure writes nothing
  - tract_validate with --split and --state-prefix '' reports train and test parts
  - conus_counties.py: status ok / no_value / zero_pop and the same row order every year
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
for sub in ("src/dasymetric", "src/validation", "src/census"):
    sys.path.insert(0, str(REPO / sub))

# stub `shap` (not needed to test the split / strips logic)
_shap = types.ModuleType("shap")


class _TreeExplainer:
    def __init__(self, model):
        self.model = model

    def shap_values(self, X):
        return np.zeros(X.shape)


def _summary_plot(*a, **k):
    import matplotlib.pyplot as plt
    plt.figure()
    plt.gca()


_shap.TreeExplainer, _shap.summary_plot = _TreeExplainer, _summary_plot
sys.modules["shap"] = _shap

# stub the figures module (plots.py): figures are not under test, and matplotlib may be missing or broken locally
_plots = types.ModuleType("plots")
for _f in ("correlation_heatmap", "shap_summary", "shap_by_year", "pop_maps"):
    setattr(_plots, _f, lambda *a, **k: None)
_plots.map_bounds = lambda mask, grid: (0, 0, 1, 1)
_plots.read_states = lambda *a, **k: None
sys.modules["plots"] = _plots

import geopandas as gpd  # noqa: E402
import rasterio  # noqa: E402
import yaml  # noqa: E402
from affine import Affine  # noqa: E402
from shapely.geometry import box  # noqa: E402

import county_features  # noqa: E402
import make_split  # noqa: E402
import predict  # noqa: E402
import train  # noqa: E402
import tract_validate  # noqa: E402

CRS = "EPSG:5070"  # Albers CONUS (the cutouts use ESRI:102039, same projection family)
H, W = 66, 50  # 64 x 48 cells of counties + a 1-cell border outside every county
CS = 8  # county = 8 x 8 cells -> 8 rows x 6 cols = 48 counties
TRANSFORM = Affine(250.0, 0, 1_000_000.0, 0, -250.0, 2_000_000.0)
YEARS = [1960, 2010]
LAND_USE = ["A", "C", "GV", "I", "RC", "RI", "RO", "VL"]
NO_VALUE = {1960: 5}  # zone 5 has no CSV value in 1960
ZERO_POP = {2010: 7}  # zone 7 has pop 0 in 2010


def write_tif(path: Path, arr, nodata=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1,
                       dtype=arr.dtype, crs=CRS, transform=TRANSFORM, nodata=nodata) as dst:
        dst.write(arr, 1)


def county_table():
    rows = []
    for i in range(8):
        for j in range(6):
            zid = i * 6 + j + 1
            st = ["Alpha", "Beta", "Gamma", "Delta"][i // 2]
            fips = f"{10 + i // 2:02d}{zid * 2 + 1:03d}"
            rows.append({"zone_id": zid, "GISJOIN": "G" + fips[:2] + "0" + fips[2:] + "0", "fips": fips,
                         "state": st, "name": f"County {zid}", "r0": 1 + i * CS, "c0": 1 + j * CS})
    return pd.DataFrame(rows)


def make_cutout(tmp: Path, counties: pd.DataFrame):
    rng = np.random.default_rng(0)
    cut = tmp / "cutouts" / "conus"
    zones = np.zeros((H, W), dtype="uint16")
    for r in counties.itertuples():
        zones[r.r0:r.r0 + CS, r.c0:r.c0 + CS] = r.zone_id
    centre = np.hypot(*np.meshgrid(np.arange(W) - 30, np.arange(H) - 20))  # a "city" near row 20, col 30
    for year in YEARS:
        dens = np.exp(-centre / (8 if year == 1960 else 14)) * (1 + 0.3 * rng.random((H, W)))
        bupl = rng.poisson(dens * 20).astype("int32")
        bupl[rng.random((H, W)) < 0.15] = 0
        bui = (bupl * rng.integers(1, 4, (H, W))).astype("int32")
        bupr = (bupl * rng.integers(1, 3, (H, W))).astype("int32")
        bua = (bupl > 0).astype("int32")
        for name, arr in (("BUI", bui), ("BUPL", bupl), ("BUPR", bupr), ("BUA", bua)):
            write_tif(cut / "layers" / name / f"{year}_{name}.tif", arr)
        for c in LAND_USE:
            write_tif(cut / "layers" / "Land_Use" / c / f"{year}_{c}.tif", rng.poisson(bupl * 0.5).astype("int32"))
        wf = np.zeros((H, W), dtype="float32")
        wf[(bui == 0) & (rng.random((H, W)) < 0.05)] = 1.0  # some all-water cells (masked)
        wf[rng.random((H, W)) < 0.05] = 0.5
        write_tif(cut / "layers" / "water_frac" / f"{year}_water_frac.tif", wf, float("nan"))
        t = counties[["zone_id", "GISJOIN", "state", "name"]].copy()
        tot = np.bincount(zones.ravel(), weights=bui.ravel(), minlength=len(t) + 1)[1:]
        t["pop"] = np.round(tot * (5 if year == 1960 else 8) + rng.integers(50, 500, len(t))).astype(float)
        t["status"] = "ok"
        if year in NO_VALUE:
            t.loc[t["zone_id"] == NO_VALUE[year], ["pop", "status"]] = [np.nan, "no_value"]
        if year in ZERO_POP:
            t.loc[t["zone_id"] == ZERO_POP[year], ["pop", "status"]] = [0.0, "zero_pop"]
        t["area_km2"] = CS * CS * 0.0625
        write_tif(cut / "zones" / f"zones_{year}.tif", zones, 0)
        t.to_csv(cut / "zones" / f"zones_{year}.csv", index=False)
    return cut, zones


def write_configs(tmp: Path, split_path: Path):
    (tmp / "configs").mkdir()
    (tmp / "configs" / "study.yaml").write_text(yaml.safe_dump({"name": "conus", "years": YEARS}))
    feats = ["bui", "bldg_size", "mu_ratio", "dist_built", "res_share", "rent_share"]
    base = {"study_area": str(tmp / "configs" / "study.yaml"), "water_mask": "yearly", "compare_with": None,
            "split": str(split_path), "use_status": ["ok"], "unusable": "skip",
            "eras": {f"Y{y}": {"years": [y], "features": feats} for y in YEARS},
            "feature_groups": {"Building": ["bui", "bldg_size", "mu_ratio"], "Settlement context": ["dist_built"],
                               "Land use": ["res_share", "rent_share"]},
            "maps": {"years": [], "compare_years": []}, "correlation_threshold": 0.8, "model": "rf",
            "search": {"n_iter": 2, "random_state": 42, "cv_folds": 5, "scoring": "neg_root_mean_squared_error"},
            "permutation": {"n_repeats": 2, "random_state": 42},
            "models": {"rf": {"fixed": {"random_state": 42},
                              "space": {"n_estimators": [10, 20], "max_depth": [None, 5],
                                        "min_samples_leaf": [1, 2], "max_features": [1.0]}}}}
    paths = {}
    for version, extra in (("blocks", {"block_rows": 7}), ("whole", {})):
        p = tmp / "configs" / f"{version}.yaml"
        p.write_text(yaml.safe_dump({**base, "version": version, **extra}))
        paths[version] = p
    return paths


def read(path):
    with rasterio.open(path) as src:
        return src.read(1)


def test_pipeline():
    tmp = Path(tempfile.mkdtemp())
    try:
        counties = county_table()
        cut, zones = make_cutout(tmp, counties)
        split = make_split.make_split(counties[["GISJOIN", "fips", "state", "name"]], 0.2, 5, 42)
        split_path = tmp / "split.csv"
        split.to_csv(split_path, index=False)
        assert (split.groupby("state")["part"].apply(lambda s: (s == "test").sum()) == 2).all()  # round(0.2 x 12)
        cfgs = write_configs(tmp, split_path)
        out_root = tmp / "dasym"
        common = ["--out-root", str(out_root)]

        # 1. features: strips == whole window
        for v in ("blocks", "whole"):
            county_features.main(["--config", str(cfgs[v]), "--cutout-root", str(tmp / "cutouts")] + common)
        for y in YEARS:
            a = pd.read_csv(out_root / "conus" / "blocks" / f"Y{y}" / "features" / "county_features.csv")
            b = pd.read_csv(out_root / "conus" / "whole" / f"Y{y}" / "features" / "county_features.csv")
            pd.testing.assert_frame_equal(a, b, rtol=1e-12)
            assert NO_VALUE.get(y) not in a["zone_id"].tolist() and ZERO_POP.get(y) not in a["zone_id"].tolist()
            assert len(a) == 47 and np.isfinite(a["y"]).all()
        print("ok features: strips == whole window, no_value / zero_pop counties left out")

        # 2. train with the split (+ --years filter)
        train.main(["--config", str(cfgs["blocks"]), "--n-jobs", "1", "--years", "1960"] + common)
        assert not (out_root / "conus" / "blocks" / "Y2010" / "model").exists()
        train.main(["--config", str(cfgs["blocks"]), "--n-jobs", "1"] + common)
        test_ids = set(split.loc[split["part"] == "test", "GISJOIN"])
        for y in YEARS:
            m = out_root / "conus" / "blocks" / f"Y{y}" / "model"
            met = json.loads((m / "metrics.json").read_text())
            oof = pd.read_csv(m / "oof_predictions.csv")
            tp = pd.read_csv(m / "test_predictions.csv")
            folds = pd.read_csv(m / "folds.csv")
            assert not (set(oof["GISJOIN"]) & test_ids) and set(tp["GISJOIN"]) <= test_ids
            assert met["n_test_counties"] == len(tp) and np.isfinite(met["test_rmse"])
            assert met["n_rows"] + met["n_test_rows"] == 47
            want = split.set_index("GISJOIN")["fold"]
            assert (folds.set_index("GISJOIN")["fold"] == want.loc[folds["GISJOIN"]]).all()
        summ = pd.read_csv(out_root / "conus" / "blocks" / "cv_summary.csv")
        assert {"test_rmse", "test_r2"} <= set(summ.columns)
        print("ok train: test counties held out, folds from the split table, test score written")

        # 3. predict: strips == whole window with the same model
        for y in YEARS:
            shutil.copytree(out_root / "conus" / "blocks" / f"Y{y}" / "model",
                            out_root / "conus" / "whole" / f"Y{y}" / "model")
        predict.main(["--config", str(cfgs["blocks"]), "--cutout-root", str(tmp / "cutouts"), "--measure", "2"]
                     + common)
        assert not (out_root / "conus" / "blocks" / "predictions").exists()
        for v in ("blocks", "whole"):
            predict.main(["--config", str(cfgs[v]), "--cutout-root", str(tmp / "cutouts"), "--n-jobs", "2"] + common)
        for y in YEARS:
            a = read(out_root / "conus" / "blocks" / "predictions" / f"pop_{y}.tif")
            b = read(out_root / "conus" / "whole" / "predictions" / f"pop_{y}.tif")
            assert np.array_equal(a, b), np.abs(a - b).max()
            bad = [NO_VALUE.get(y), ZERO_POP.get(y), 0]
            assert (a[np.isin(zones, bad)] == predict.NODATA_OUT).all()
            assert (a[~np.isin(zones, bad)] >= 0).all()
            zt = pd.read_csv(cut / "zones" / f"zones_{y}.csv")
            sums = np.bincount(zones[a >= 0], weights=a[a >= 0].astype("float64"), minlength=49)
            ok = zt[zt["status"] == "ok"]
            assert np.allclose(sums[ok["zone_id"]], ok["pop"], rtol=1e-6)
            t_zone = zt.loc[zt["GISJOIN"].isin(test_ids) & (zt["status"] == "ok"), "zone_id"]
            assert (sums[t_zone] > 0).all()
        qa = pd.read_csv(out_root / "conus" / "blocks" / "qa" / "reallocation_qa.csv")
        assert len(qa) == 94 and (qa["rel_diff"] < 1e-6).all()
        print("ok predict: strips == whole window, mass preserved, NoData for unused counties, test counties allocated")

        # 4. tract validation with the split
        tracts_dir = tmp / "tracts"
        tracts_dir.mkdir()
        rng = np.random.default_rng(1)
        x0, y0 = TRANSFORM.c, TRANSFORM.f
        for y in YEARS:
            geoms, rows = [], []
            for r in counties.itertuples():
                for half in range(2):  # two tracts per county: left / right half
                    c0 = r.c0 + half * CS // 2
                    geoms.append(box(x0 + c0 * 250, y0 - (r.r0 + CS) * 250, x0 + (c0 + CS // 2) * 250,
                                     y0 - r.r0 * 250))
                    rows.append({"GISJOIN": f"{r.GISJOIN}{half:04d}", "county_gisjoin": r.GISJOIN,
                                 "pop": float(rng.integers(100, 5000)), "status": "ok"})
            gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS).to_file(tracts_dir / f"tracts_{y}.gpkg", driver="GPKG")
        tract_validate.main(["--version", "blocks", "--name", "conus", "--dasym-root", str(out_root),
                             "--cutout-root", str(tmp / "cutouts"), "--tract-dir", str(tracts_dir),
                             "--results-root", str(tmp / "val"), "--years", *map(str, YEARS), "--map-years",
                             "--state-prefix", "", "--split", str(split_path)])
        met = pd.read_csv(tmp / "val" / "conus" / "blocks" / "metrics_by_year.csv")
        assert set(met["part"]) == {"all", "train", "test"}
        a = met[(met["subset"] == "all") & (met["method"] == "model")].set_index(["year", "part"])["n"]
        for y in YEARS:
            assert a[(y, "train")] + a[(y, "test")] == a[(y, "all")] > 0
        te = pd.read_csv(tmp / "val" / "conus" / "blocks" / "tract_errors_2010.csv")
        assert set(te.loc[te["flag"] == "ok", "part"]) == {"train", "test"}
        print("ok tract_validate: train / test parts reported")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_conus_counties():
    import conus_counties
    tmp = Path(tempfile.mkdtemp())
    try:
        g = gpd.GeoDataFrame({"GISJOIN": ["G0100030", "G0100010", "G0100050"], "fips": ["01003", "01001", None],
                              "state": "Alabama", "name": ["B", "A", "C"], "area_km2": [1.0, 2.0, 3.0],
                              "pop_1920": [10.0, np.nan, np.nan], "pop_1960": [0.0, 5.0, np.nan]},
                             geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(2, 0, 3, 1)], crs=CRS)
        g.to_file(tmp / "std.gpkg", driver="GPKG")
        conus_counties.main(["--std-gpkg", str(tmp / "std.gpkg"), "--out-dir", str(tmp / "out"),
                             "--results-dir", str(tmp / "res"), "--years", "1920", "1960"])
        a = gpd.read_file(tmp / "out" / "counties_1920.gpkg")
        b = gpd.read_file(tmp / "out" / "counties_1960.gpkg")
        assert a["GISJOIN"].tolist() == b["GISJOIN"].tolist() == ["G0100010", "G0100030", "G0100050"]
        assert a["status"].tolist() == ["no_value", "ok", "no_value"]
        assert b["status"].tolist() == ["ok", "zero_pop", "no_value"]
        print("ok conus_counties: statuses and row order")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_conus_counties()
    test_pipeline()
    print("ALL OK")
