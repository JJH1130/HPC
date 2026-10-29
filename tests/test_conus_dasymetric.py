"""Synthetic test of the CONUS changes to the dasymetric steps, runnable without the cluster:

    python tests/test_conus_dasymetric.py      (needs the hisdac env: numpy, pandas, scipy, sklearn, geopandas,
                                                rasterio; `shap` and the figures module plots.py are stubs here)

Builds a small cutout (48 counties in 4 states, years 1960 + 2010, BUI/BUPL/BUPR/BUA/Land_Use/yearly water_frac)
in a temporary folder, a split table with make_split.py, and checks:
  - county_features in strips (block_rows) = the whole-window computation
  - train with `split`: test counties are not in the training / CV rows; test score reported
  - predict in strips = whole window with the same model; mass preserved; no_value / zero_pop counties and
    cells outside counties are NoData; test counties are allocated; --measure writes nothing
  - tract_validate with --split and --state-prefix '' reports train and test parts, and the density classes;
    with --gap-share the parts no_gap / gap (BUI gap counties from county_features.csv)
  - model family (models.py): LightGBM, XGBoost, CatBoost with distribution spaces on the copied features of
    another version: search -> fit -> save -> load -> predict, mass preserved, era params fixed, same folds as
    compare_with; compare_models.py table
  - all census years (v3_all): a pre-1940 year without Land_Use (1900, its own feature list) next to 1960 / 2010;
    the shared years come out the same as the compared version (features, hyperparameters, CV, tracts); no
    comparison for 1900; no tracts in 1900; summary_by_year with --repro-with and the figure
  - terrain (elev, slope; v3 / v4): strips (one halo row) == whole window, cell by cell and as county features
  - bui_qa.py: quantiles, cap counts and the top cells with their county and bldg_size
  - conus_counties.py: status ok / no_value / zero_pop and the same row order every year
  - NTL (Dasy_CONUS_RF_v3_ntl, test_ntl): the real configs (NTL layer 2000 / 2010; v3_ntl = v3_all + ntl); an era
    with ntl (2010) next to one without (1960), county ntl = mean DN, strips == whole window; NTL nodata outside the
    used counties ignored, inside one the features stop; ntl_qa.py box / edge counts against brute force;
    compare_models --years --rank-features
  - VIIRS-like NTL (Dasy_CONUS_RF_v3_ntlv, test_ntlv): the real configs (NTLV layer; v3_ntlv = v3_ntl with ntlv);
    make_cutout `nodata_to` (sea mask -> 0, the rest = the nearest warp); ntlv_check.py on a lon/lat raster (coverage,
    counts; a raster missing the window and a negative value fail); county ntlv = mean radiance; ntl_qa.py with NTL
    and NTLV side by side (radiance: percentile box, lit share and mean ratio on BUI 0 cells; negative fails)
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
for sub in ("src/dasymetric", "src/validation", "src/census", "src/grid"):
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

import bui_qa  # noqa: E402
import common as dcommon  # noqa: E402
import compare_models  # noqa: E402
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
FILLED = {2010: 9}  # zone 9 is filled_nhgis_alloc in 2010: allocated, not trained on or scored
TRAINED_FILL = {2010: 11}  # zone 11 is filled_nhgis in 2010: allocated and trained on


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
    dem = (100 + 3 * np.arange(H)[:, None] ** 1.5 + 40 * np.sin(np.arange(W) / 4)[None, :]
           + 5 * rng.random((H, W))).astype("float32")  # rough terrain, slope varies from row to row
    dem[:3, :] = np.nan  # "sea" rows at the top (nodata -> 0 m), incl. inside zone rows 1-2
    dem[30:33, 40:] = np.nan  # an inland nodata patch across a strip boundary (block_rows 7: rows 28 / 35)
    write_tif(cut / "layers" / "DEM" / "DEM.tif", dem, float("nan"))
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
        if year in FILLED:
            t.loc[t["zone_id"] == FILLED[year], "status"] = "filled_nhgis_alloc"
        if year in TRAINED_FILL:
            t.loc[t["zone_id"] == TRAINED_FILL[year], "status"] = "filled_nhgis"
        t["area_km2"] = CS * CS * 0.0625
        write_tif(cut / "zones" / f"zones_{year}.tif", zones, 0)
        t.to_csv(cut / "zones" / f"zones_{year}.csv", index=False)
    return cut, zones


def write_configs(tmp: Path, split_path: Path):
    (tmp / "configs").mkdir()
    (tmp / "configs" / "study.yaml").write_text(yaml.safe_dump({"name": "conus", "years": YEARS}))
    feats = ["bui", "bldg_size", "mu_ratio", "dist_built", "res_share", "rent_share"]
    base = {"study_area": str(tmp / "configs" / "study.yaml"), "water_mask": "yearly", "compare_with": None,
            "split": str(split_path), "use_status": ["ok", "filled_nhgis", "filled_nhgis_alloc"],
            "train_status": ["ok", "filled_nhgis"],
            "unusable": "skip",
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
    terrain = {"eras": {f"Y{y}": {"years": [y], "features": feats + ["elev", "slope"]} for y in YEARS},
               "feature_groups": {**base["feature_groups"], "Elevation": ["elev"], "Slope": ["slope"]}}
    boost = {  # small spaces with distributions (models.py); the real ones are in configs/conus_*_v3_n60.yaml
        "lgbm": ({"random_state": 42, "subsample_freq": 1},
                 {"n_estimators": {"dist": "randint", "low": 20, "high": 40},
                  "learning_rate": {"dist": "loguniform", "low": 0.05, "high": 0.2},
                  "num_leaves": {"dist": "randint", "low": 4, "high": 15},
                  "min_child_samples": {"dist": "randint", "low": 3, "high": 10},
                  "subsample": {"dist": "uniform", "low": 0.6, "high": 1.0}}),
        "xgb": ({"random_state": 42, "tree_method": "hist"},
                {"n_estimators": {"dist": "randint", "low": 20, "high": 40},
                 "learning_rate": {"dist": "loguniform", "low": 0.05, "high": 0.2},
                 "max_depth": {"dist": "randint", "low": 2, "high": 4}}),
        "catboost": ({"random_seed": 42, "bootstrap_type": "Bernoulli"},
                     {"iterations": {"dist": "randint", "low": 20, "high": 40},
                      "learning_rate": {"dist": "loguniform", "low": 0.05, "high": 0.2},
                      "depth": {"dist": "randint", "low": 2, "high": 4},
                      "subsample": {"dist": "uniform", "low": 0.6, "high": 1.0}}),
    }
    for name, (fixed, space) in boost.items():
        eras = {f"Y{y}": {"years": [y], "features": feats} for y in YEARS}
        if name == "lgbm":
            eras["Y1960"]["params"] = {"num_leaves": 7}  # an era's fixed value overrides the distribution
        p = tmp / "configs" / f"m_{name}.yaml"
        p.write_text(yaml.safe_dump({**base, "version": f"m_{name}", "block_rows": 7, "compare_with": "blocks",
                                     "eras": eras, "model": name, "search": {**base["search"], "n_iter": 3},
                                     "models": {name: {"fixed": fixed, "space": space}}}))
        paths[f"m_{name}"] = p
    for version, extra in (("blocks", {"block_rows": 7}), ("whole", {}),
                           ("v2", {"block_rows": 7, "compare_with": "blocks"}),
                           ("tblocks", {"block_rows": 7, **terrain}), ("twhole", terrain)):
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
        extra = pd.DataFrame({"GISJOIN": ["G9900030", "G9900010"], "fips": ["99003", "99001"], "state": "Omega",
                              "name": ["b", "a"]})
        app = make_split.append_train(split, extra)
        assert app.iloc[:len(split)].equals(split) and (app.iloc[len(split):]["part"] == "train").all()
        tr = split[split["part"] == "train"]["fold"].value_counts()
        first = min(sorted(tr.index), key=lambda k: (tr[k], k))
        assert app.iloc[len(split)]["GISJOIN"] == "G9900010" and app.iloc[len(split)]["fold"] == first
        cfgs = write_configs(tmp, split_path)
        out_root = tmp / "dasym"
        common = ["--out-root", str(out_root)]

        # 0. terrain: strips with one halo row == whole window (elev and slope, every cell)
        _, _, grid = dcommon.read_zones(cut, YEARS[0])
        ew, sw = dcommon.terrain(cut, grid)
        for k in (1, 7, 512):
            parts = [dcommon.terrain(cut, grid, r) for r in dcommon.strips(grid["shape"], k)]
            assert np.array_equal(np.vstack([e for e, _ in parts]), ew)
            assert np.array_equal(np.vstack([sl for _, sl in parts]), sw), k
        assert (ew[:3] == 0).all() and np.isfinite(sw).all() and sw.max() > 1
        print("ok terrain: strips (1, 7, 512 rows) == whole window; nodata -> 0 m")

        # 1. features: strips == whole window
        for v in ("blocks", "whole", "v2", "tblocks", "twhole"):
            county_features.main(["--config", str(cfgs[v]), "--cutout-root", str(tmp / "cutouts")] + common)
        for y in YEARS:
            a = pd.read_csv(out_root / "conus" / "blocks" / f"Y{y}" / "features" / "county_features.csv")
            b = pd.read_csv(out_root / "conus" / "whole" / f"Y{y}" / "features" / "county_features.csv")
            pd.testing.assert_frame_equal(a, b, rtol=1e-12)
            ta = pd.read_csv(out_root / "conus" / "tblocks" / f"Y{y}" / "features" / "county_features.csv")
            tb = pd.read_csv(out_root / "conus" / "twhole" / f"Y{y}" / "features" / "county_features.csv")
            pd.testing.assert_frame_equal(ta, tb, rtol=1e-12)
            assert ta["elev"].std() > 0 and ta["slope"].std() > 0
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
            assert met["n_rows"] + met["n_test_rows"] == 47 - (y in FILLED)
            if y in FILLED:
                gj = counties.loc[counties["zone_id"] == FILLED[y], "GISJOIN"].iloc[0]
                assert gj not in set(oof["GISJOIN"]) | set(tp["GISJOIN"])
            if y in TRAINED_FILL:
                gj = counties.loc[counties["zone_id"] == TRAINED_FILL[y], "GISJOIN"].iloc[0]
                assert gj in set(oof["GISJOIN"]) | set(tp["GISJOIN"])
            want = split.set_index("GISJOIN")["fold"]
            assert (folds.set_index("GISJOIN")["fold"] == want.loc[folds["GISJOIN"]]).all()
        summ = pd.read_csv(out_root / "conus" / "blocks" / "cv_summary.csv")
        assert {"test_rmse", "test_r2"} <= set(summ.columns)
        print("ok train: test counties held out, folds from the split table, test score written")
        train.main(["--config", str(cfgs["v2"]), "--n-jobs", "1"] + common)  # compare_with the "blocks" version
        for y in YEARS:
            m = out_root / "conus" / "v2" / f"Y{y}" / "model"
            cmp_cv = json.loads((m / "compare_blocks.json").read_text())
            cmp_te = json.loads((m / "compare_blocks_test.json").read_text())
            assert cmp_cv["folds"] == "same as this model (checked)"
            assert cmp_te["n_test_rows"] == json.loads((m / "metrics.json").read_text())["n_test_rows"]
            assert "y_hat_blocks" in pd.read_csv(m / "test_predictions.csv").columns
        print("ok train v2: same split and folds as the compared version, CV and test comparison written")

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
            ok = zt[zt["status"].isin(["ok", "filled_nhgis", "filled_nhgis_alloc"])]
            assert np.allclose(sums[ok["zone_id"]], ok["pop"], rtol=1e-6)
            t_zone = zt.loc[zt["GISJOIN"].isin(test_ids) & (zt["status"] == "ok"), "zone_id"]
            assert (sums[t_zone] > 0).all()
            if y in FILLED:
                assert sums[FILLED[y]] > 0
        qa = pd.read_csv(out_root / "conus" / "blocks" / "qa" / "reallocation_qa.csv")
        assert len(qa) == 94 and (qa["rel_diff"] < 1e-6).all()
        train.main(["--config", str(cfgs["tblocks"]), "--n-jobs", "1"] + common)  # terrain (v3 / v4)
        for y in YEARS:
            shutil.copytree(out_root / "conus" / "tblocks" / f"Y{y}" / "model",
                            out_root / "conus" / "twhole" / f"Y{y}" / "model")
        for v in ("tblocks", "twhole"):
            predict.main(["--config", str(cfgs[v]), "--cutout-root", str(tmp / "cutouts"), "--n-jobs", "2"] + common)
        for y in YEARS:
            assert np.array_equal(read(out_root / "conus" / "tblocks" / "predictions" / f"pop_{y}.tif"),
                                  read(out_root / "conus" / "twhole" / "predictions" / f"pop_{y}.tif"))
        print("ok predict (+ terrain): strips == whole window, mass preserved, NoData for unused counties, test counties allocated")

        # 3b. --years adds one year to a version (2020 into v3_all): the other years' rows stay byte for byte
        v = out_root / "conus" / "blocks"
        files = [v / "qa" / "water_mask_by_year.csv", v / "cv_summary.csv", v / "qa" / "reallocation_qa.csv"]
        before = {f: f.read_text() for f in files}
        county_features.main(["--config", str(cfgs["blocks"]), "--cutout-root", str(tmp / "cutouts"), "--years",
                              str(YEARS[-1])] + common)
        train.main(["--config", str(cfgs["blocks"]), "--n-jobs", "1", "--years", str(YEARS[-1])] + common)
        predict.main(["--config", str(cfgs["blocks"]), "--cutout-root", str(tmp / "cutouts"), "--years",
                      str(YEARS[-1])] + common)
        for f in files:  # deterministic reruns: the whole file is the same again (old rows kept, new rows equal)
            assert f.read_text() == before[f], f
        print("ok --years: water_mask_by_year / cv_summary / reallocation_qa keep the other years' rows unchanged")

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
        d = met[met["subset"].str.startswith("dens_")]
        assert set(d["subset"]) <= {"dens_0_50", "dens_50_500", "dens_500_2000", "dens_2000_plus"} and len(d)
        s_n = d.groupby(["year", "part", "method"])["n"].sum()
        s_a = d.groupby(["year", "part", "method"])["area_share"].sum()
        full = met[met["subset"] == "all"].set_index(["year", "part", "method"])
        assert (s_n == full["n"].loc[s_n.index]).all() and np.allclose(s_a, 1.0)
        print("ok tract_validate: train / test parts reported; density classes add up to all tracts")

        # 4b. BUI gap counties (--gap-share): parts no_gap / gap from the version's county_features.csv
        tv_args = ["--name", "conus", "--dasym-root", str(out_root), "--cutout-root", str(tmp / "cutouts"),
                   "--tract-dir", str(tracts_dir), "--years", *map(str, YEARS), "--map-years", "--state-prefix", "",
                   "--split", str(split_path)]
        tract_validate.main(["--version", "blocks", "--results-root", str(tmp / "val_gap"), "--gap-share", "0.8"]
                            + tv_args)
        mg = pd.read_csv(tmp / "val_gap" / "conus" / "blocks" / "metrics_by_year.csv")
        assert set(mg["part"]) == {"all", "train", "test", "no_gap", "gap"}
        n = mg[(mg["subset"] == "all") & (mg["method"] == "model")].set_index(["year", "part"])["n"]
        for y in YEARS:
            f = pd.read_csv(out_root / "conus" / "blocks" / f"Y{y}" / "features" / "county_features.csv")
            f = f[f["pop"] > 0]
            floor = f["bui"] * (f["n_cells"] - f["n_masked"]) / f["pop"]
            want = set(f.loc[floor < 0.8 * floor.median(), "GISJOIN"])
            te = pd.read_csv(tmp / "val_gap" / "conus" / "blocks" / f"tract_errors_{y}.csv")
            ok = te[te["flag"] == "ok"]
            assert (ok["gap"] == ok["zone_gisjoin"].isin(want)).all() and not te.loc[te["flag"] != "ok", "gap"].any()
            assert 0 < n[(y, "gap")] < n[(y, "all")] and n[(y, "no_gap")] + n[(y, "gap")] == n[(y, "all")]
            assert n[(y, "gap")] == ok["gap"].sum()
            g = mg[mg["year"] == y]
            assert (g["gap_tracts"] == ok["gap"].sum()).all() and (g["gap_counties"] == len(want)).all()
        print("ok tract_validate --gap-share: gap counties from county_features, no_gap + gap = all")

        # 6. model family: LightGBM / XGBoost / CatBoost on the copied features of `blocks` (as submit_conus.sh models)
        for name in ("lgbm", "xgb", "catboost"):
            v = f"m_{name}"
            for y in YEARS:
                d = out_root / "conus" / v / f"Y{y}" / "features"
                d.mkdir(parents=True)
                shutil.copy(out_root / "conus" / "blocks" / f"Y{y}" / "features" / "county_features.csv", d)
            train.main(["--config", str(cfgs[v]), "--n-jobs", "2"] + common)
            predict.main(["--config", str(cfgs[v]), "--cutout-root", str(tmp / "cutouts"), "--n-jobs", "2"] + common)
            for y in YEARS:
                m = out_root / "conus" / v / f"Y{y}" / "model"
                met = json.loads((m / "metrics.json").read_text())
                assert met["model"] == name and met["n_candidates"] == 3 and np.isfinite(met["test_rmse"])
                assert met["train_seconds"] >= met["search_seconds"] >= 0
                assert isinstance(met["search_space"][next(iter(met["search_space"]))], (dict, list))
                assert json.loads((m / "best_params.json").read_text()) == met["best_params"]
                if name == "lgbm":
                    assert (met["best_params"]["num_leaves"] == 7) == (y == 1960), met["best_params"]
                    assert met["search_space"]["num_leaves"] == ([7] if y == 1960 else boost_space(cfgs[v]))
                bundle = predict.joblib.load(m / f"{name}.joblib")
                assert type(bundle["model"]).__name__ == {"lgbm": "LGBMRegressor", "xgb": "XGBRegressor",
                                                          "catboost": "CatBoostRegressor"}[name]
                assert json.loads((m / "compare_blocks.json").read_text())["folds"] == "same as this model (checked)"
                a = read(out_root / "conus" / v / "predictions" / f"pop_{y}.tif")
                zt = pd.read_csv(cut / "zones" / f"zones_{y}.csv")
                sums = np.bincount(zones[a >= 0], weights=a[a >= 0].astype("float64"), minlength=49)
                used = zt[zt["status"].isin(["ok", "filled_nhgis", "filled_nhgis_alloc"])]
                assert np.allclose(sums[used["zone_id"]], used["pop"], rtol=1e-6), name
            print(f"ok model {name}: search -> fit -> save -> load -> predict, mass preserved, same folds as blocks")

        # 7. compare_models: the result layout of the sbatch copies (<version>/<era>/metrics.json, cv_summary.csv)
        res = tmp / "results"
        for v in ("blocks", "m_lgbm", "m_xgb", "m_catboost"):
            dst = res / "dasymetric" / "conus" / v
            for y in YEARS:
                shutil.copytree(out_root / "conus" / v / f"Y{y}" / "model", dst / f"Y{y}")
            shutil.copy(out_root / "conus" / v / "cv_summary.csv", dst)
            if v != "blocks":
                tract_validate.main(["--version", v, "--results-root", str(res / "validation"), "--gap-share", "0.8"]
                                    + tv_args)
        shutil.copytree(tmp / "val_gap" / "conus" / "blocks", res / "validation" / "conus" / "blocks")
        compare_models.main(["--versions", "blocks", "m_lgbm", "m_xgb", "m_catboost", "--results-root", str(res)])
        cmp = pd.read_csv(res / "validation" / "conus" / "model_comparison.csv")
        assert len(cmp) == 4 * len(YEARS) and set(cmp["model"]) == {"rf", "lgbm", "xgb", "catboost"}
        r = cmp[(cmp["version"] == "blocks") & (cmp["year"] == 2010)].iloc[0]
        g = mg[(mg["year"] == 2010) & (mg["method"] == "model") & (mg["subset"] == "all")].set_index("part")
        assert np.isclose(r["tract_no_gap_mdape"], g.loc["no_gap", "mdape"]) and r["tract_gap_n"] == g.loc["gap", "n"]
        assert np.isclose(r["cv_rmse_mean"], json.loads((out_root / "conus" / "blocks" / "Y2010" / "model" /
                                                         "metrics.json").read_text())["cv_rmse_mean"])
        dens = [c for c in cmp if c.startswith("tract_dens_")]
        assert len(dens) == 4 and cmp[dens].notna().any().any() and cmp["best_params"].notna().all()
        print("ok compare_models: one row per version and year, CV / TEST / tract columns from the result files")

        # 8. all census years (Dasy_CONUS_RF_v3_all): 1900 (no Land_Use: no res_share / rent_share) added to the
        # cutout; 1960 / 2010 must reproduce `blocks` (same seed, features, folds), 1900 has no compare_with era
        add_year(cut, 1900)
        cfg_all = write_all_config(tmp, cfgs["blocks"], [1900] + YEARS)
        county_features.main(["--config", str(cfg_all), "--cutout-root", str(tmp / "cutouts")] + common)
        train.main(["--config", str(cfg_all), "--n-jobs", "2"] + common)
        predict.main(["--config", str(cfg_all), "--cutout-root", str(tmp / "cutouts"), "--n-jobs", "2"] + common)
        va = out_root / "conus" / "all"
        assert "res_share" not in pd.read_csv(va / "Y1900" / "features" / "county_features.csv").columns
        for y in YEARS:
            pd.testing.assert_frame_equal(
                pd.read_csv(va / f"Y{y}" / "features" / "county_features.csv"),
                pd.read_csv(out_root / "conus" / "blocks" / f"Y{y}" / "features" / "county_features.csv"))
            assert (va / f"Y{y}" / "model" / "compare_blocks.json").exists()
        assert not list((va / "Y1900" / "model").glob("compare_*"))
        q = pd.read_csv(va / "qa" / "reallocation_qa.csv")
        assert set(q["year"]) == {1900, *YEARS} and (q["rel_diff"] < predict.MASS_TOL).all()
        dst = res / "dasymetric" / "conus" / "all"
        for y in [1900] + YEARS:
            shutil.copytree(va / f"Y{y}" / "model", dst / f"Y{y}")
        shutil.copy(va / "cv_summary.csv", dst)
        shutil.copy(va / "qa" / "reallocation_qa.csv", dst)
        tract_validate.main(["--version", "all", "--results-root", str(res / "validation"), "--gap-share", "0.8"]
                            + tv_args)  # tv_args: --years 1960 2010 (no tracts in 1900)
        r = res / "validation" / "conus" / "all"
        compare_models.main(["--versions", "all", "--results-root", str(res), "--repro-with", "blocks",
                             "--out", str(r / "summary_by_year.csv"), "--plot", str(r / "mdape_by_year.png")])
        sy = pd.read_csv(r / "summary_by_year.csv").set_index("year")
        assert sy.index.tolist() == [1900] + YEARS and (sy["mass_fail"] == 0).all()
        assert (sy.loc[YEARS, "repro_blocks"] == "same").all() and pd.isna(sy.loc[1900, "repro_blocks"])
        assert pd.isna(sy.loc[1900, "tract_all_mdape"]) and sy.loc[YEARS, "tract_counties"].gt(0).all()
        assert (r / "mdape_by_year.png").stat().st_size > 0
        print("ok all years: 1900 without Land_Use features, 1960 / 2010 reproduce the compared version, "
              "summary_by_year + figure")

        # 5. bui_qa: quantiles over BUI > 0 cells, cap counts, top cells with county and bldg_size
        bui_qa.main(["--cutout", str(cut), "--years", *map(str, YEARS), "--out-dir", str(tmp / "bq"),
                     "--caps", "5", "50", "--top", "5", "--block-rows", "7", "--metro-rank", "3"])
        q = pd.read_csv(tmp / "bq" / "bui_quantiles.csv").set_index("year")
        top = pd.read_csv(tmp / "bq" / "bui_top.csv")
        for y in YEARS:
            b = read(cut / "layers" / "BUI" / f"{y}_BUI.tif").astype(float)
            pl = read(cut / "layers" / "BUPL" / f"{y}_BUPL.tif").astype(float)
            pos = b[b > 0]
            assert q.loc[y, "cells_bui_pos"] == pos.size and q.loc[y, "max"] == pos.max()
            assert np.isclose(q.loc[y, "p99"], np.quantile(pos.astype("float32"), 0.99))
            assert q.loc[y, "n_gt_5e0"] == (pos > 5).sum() and q.loc[y, "n_gt_5e1"] == (pos > 50).sum()
            t = top[top["year"] == y]
            assert len(t) == 5 and (np.diff(t["BUI"]) <= 0).all() and t["BUI"].iloc[0] == pos.max()
            assert (t["BUI"].to_numpy() == b[t["row"], t["col"]]).all()
            assert (t["zone_id"].to_numpy() == zones[t["row"], t["col"]]).all()
            assert np.allclose(t["bldg_size"], b[t["row"], t["col"]] / pl[t["row"], t["col"]])
        print("ok bui_qa: quantiles, caps, top cells with zone and bldg_size")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def add_year(cut: Path, year: int, src: int = 1960):
    """A pre-1940 year in the synthetic cutout: the src year's building layers halved, its water and zones (pop
    0.4 x), and no Land_Use (HISDAC has it from 1940)."""
    for name in ("BUI", "BUPL", "BUPR", "BUA"):
        a = read(cut / "layers" / name / f"{src}_{name}.tif")
        write_tif(cut / "layers" / name / f"{year}_{name}.tif", a if name == "BUA" else (a // 2).astype(a.dtype))
    write_tif(cut / "layers" / "water_frac" / f"{year}_water_frac.tif",
              read(cut / "layers" / "water_frac" / f"{src}_water_frac.tif"), float("nan"))
    write_tif(cut / "zones" / f"zones_{year}.tif", read(cut / "zones" / f"zones_{src}.tif"), 0)
    t = pd.read_csv(cut / "zones" / f"zones_{src}.csv")
    t["pop"] = np.round(t["pop"] * 0.4)
    t.to_csv(cut / "zones" / f"zones_{year}.csv", index=False)


def write_all_config(tmp: Path, ref_cfg: Path, years: list[int]) -> Path:
    """Like configs/conus_rf_v3_all.yaml: the reference version's config over more years, one era per year
    (before 1940 without res_share / rent_share), compare_with the reference."""
    study = tmp / "configs" / "study_all.yaml"
    study.write_text(yaml.safe_dump({"name": "conus", "years": years}))
    ref = yaml.safe_load(ref_cfg.read_text())
    feats = ref["eras"][f"Y{YEARS[0]}"]["features"]
    eras = {f"Y{y}": {"years": [y], "features": feats if y >= 1940 else
                      [f for f in feats if f not in ("res_share", "rent_share")]} for y in years}
    p = tmp / "configs" / "all.yaml"
    p.write_text(yaml.safe_dump({**ref, "version": "all", "study_area": str(study), "eras": eras,
                                 "compare_with": ref["version"]}))
    return p


def boost_space(cfg_path: Path):
    return yaml.safe_load(cfg_path.read_text())["models"]["lgbm"]["space"]["num_leaves"]


def test_conus_counties():
    import conus_counties
    tmp = Path(tempfile.mkdtemp())
    try:
        # G0100050: no CSV row, in NHGIS 1920 only; G1200860 (Miami-Dade): no CSV row, NHGIS as Dade G1200250 in 1960
        g = gpd.GeoDataFrame({"GISJOIN": ["G0100030", "G0100010", "G0100050", "G1200860"],
                              "fips": ["01003", "01001", None, None], "state": "Alabama", "name": ["B", "A", "C", "M"],
                              "area_km2": [1.0, 2.0, 3.0, 4.0], "pop_1920": [10.0, np.nan, np.nan, np.nan],
                              "pop_1960": [0.0, 5.0, np.nan, np.nan]},
                             geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(2, 0, 3, 1), box(3, 0, 4, 1)], crs=CRS)
        g.to_file(tmp / "std.gpkg", driver="GPKG")
        nom = tmp / "nhgis"
        nom.mkdir()
        for year, rows in ((1920, [("G0100050", 7.0, "ok", 3.3)]),
                           (1960, [("G1200250", 900.0, "ok", 4.0), ("G0100050", np.nan, "nodata_unenumerated", 3.0)])):
            gpd.GeoDataFrame({"GISJOIN": [r[0] for r in rows], "name": "n", "pop": [r[1] for r in rows],
                              "status": [r[2] for r in rows], "area_km2": [r[3] for r in rows]},
                             geometry=[box(0, 0, 1, 1)] * len(rows), crs=CRS).to_file(nom / f"counties_{year}.gpkg",
                                                                                      driver="GPKG")
        conus_counties.main(["--std-gpkg", str(tmp / "std.gpkg"), "--census-dir", str(nom), "--out-dir",
                             str(tmp / "out"), "--results-dir", str(tmp / "res"), "--years", "1920", "1960"])
        a = gpd.read_file(tmp / "out" / "counties_1920.gpkg")
        b = gpd.read_file(tmp / "out" / "counties_1960.gpkg")
        assert a["GISJOIN"].tolist() == b["GISJOIN"].tolist() == ["G0100010", "G0100030", "G0100050", "G1200860"]
        assert a["status"].tolist() == ["no_value", "ok", "filled_nhgis_alloc", "no_value"] and a["pop"].iloc[2] == 7.0
        assert b["status"].tolist() == ["ok", "zero_pop", "no_value", "filled_nhgis"] and b["pop"].iloc[3] == 900.0
        f = pd.read_csv(tmp / "res" / "counties_conus_filled.csv")
        assert len(f) == 4 and f["filled"].sum() == 2
        assert f.loc[f["filled"] & (f["year"] == 1960), "source"].tolist() == ["G1200250"]
        print("ok conus_counties: statuses, NHGIS fill (incl. the Dade alias), area-ratio rule and row order")

        # 2020 from NHGIS on the 2010 polygons: same code, Shannon -> Oglala Lakota, Bedford city merged into Bedford
        # County, a changed area, a zero pop, an NHGIS unit without a polygon; summary keeps 1920 / 1960
        g = gpd.GeoDataFrame({"GISJOIN": ["G0100010", "G0100030", "G4601130", "G5100190", "G5105150", "G0100050"],
                              "fips": ["01001", "01003", "46113", "51019", "51515", "01005"], "state": "S",
                              "name": ["A", "B", "Shannon", "Bedford Co", "Bedford city", "C"],
                              "area_km2": [2.0, 1.0, 5.0, 10.0, 0.1, 3.0], "pop_1920": 1.0, "pop_1960": 1.0},
                             geometry=[box(i, 0, i + 1, 1) for i in range(6)], crs=CRS)
        g.to_file(tmp / "std.gpkg", driver="GPKG")
        rows = [("G0100010", 50.0, 2.02), ("G0100030", 60.0, 1.2), ("G4601020", 14000.0, 5.0),
                ("G5100190", 79000.0, 10.1), ("G0100050", 0.0, 3.0), ("G0100070", 99.0, 1.0)]
        gpd.GeoDataFrame({"GISJOIN": [r[0] for r in rows], "state": "S", "name": "n", "pop": [r[1] for r in rows],
                          "status": "ok", "area_km2": [r[2] for r in rows]},
                         geometry=[box(0, 0, 1, 1)] * len(rows), crs=CRS).to_file(nom / "counties_2020.gpkg",
                                                                                  driver="GPKG")
        conus_counties.main(["--std-gpkg", str(tmp / "std.gpkg"), "--census-dir", str(nom), "--out-dir",
                             str(tmp / "out"), "--results-dir", str(tmp / "res"), "--years", "2020"])
        c = gpd.read_file(tmp / "out" / "counties_2020.gpkg").set_index("GISJOIN")
        want = {"G0100010": ("ok", 50.0), "G0100030": ("filled_nhgis_alloc", 60.0), "G4601130": ("ok", 14000.0),
                "G5100190": ("filled_nhgis_alloc", 79000.0), "G5105150": ("no_value", None),
                "G0100050": ("zero_pop", 0.0)}
        for gj, (st, pop) in want.items():
            assert c.at[gj, "status"] == st, (gj, c.at[gj, "status"])
            assert (pd.isna(c.at[gj, "pop"]) if pop is None else c.at[gj, "pop"] == pop), gj
        assert sorted(c.index) == list(c.index)  # same polygons, same order as the CSV years
        m = pd.read_csv(tmp / "res" / "counties_2020_nhgis_match.csv")
        assert m.set_index("source").at["G0100070", "rule"] == "nhgis_unmatched"
        assert m.set_index("GISJOIN").at["G5105150", "rule"] == "merged_into"
        assert m.set_index("GISJOIN").at["G4601130", "rule"] == "remapped"
        s = pd.read_csv(tmp / "res" / "counties_conus_summary.csv")
        assert sorted(s["year"].unique()) == [1920, 1960, 2020]
        assert sorted(pd.read_csv(tmp / "res" / "counties_conus_filled.csv")["year"].unique()) == [1920, 1960]
        print("ok conus_counties 2020: NHGIS match (remap, merge, area rule, zero pop, unmatched unit), "
              "--years keeps the other years in the summary")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


NTL_NODATA = -1  # what make_cutout writes for int16 cells outside the source (docs/cutout.md)


def write_ntl(cut: Path, centre, nodata_cells):
    """layers/NTL/2010_NTL.tif: DN 0-63 brightest at the 'city', -1 (nodata) at nodata_cells (list of (row, col))."""
    rng = np.random.default_rng(3)
    ntl = np.clip(np.round(63 * np.exp(-centre / 9) + rng.integers(0, 4, centre.shape)), 0, 63).astype("int16")
    for rc in nodata_cells:
        ntl[rc] = NTL_NODATA
    write_tif(cut / "layers" / "NTL" / "2010_NTL.tif", ntl, NTL_NODATA)
    return ntl


def test_ntl():
    """Dasy_CONUS_RF_v3_ntl (docs/conus_plan.md "NTL test"): an era with ntl (2010) next to one without (1960), NTL
    nodata, ntl_qa.py (box, edges) and compare_models --years --rank-features."""
    import make_cutout as cutout_mod
    import ntl_qa
    from pyproj import Transformer

    # the real configs load: NTL 2000 / 2010 in the CONUS study area, v3_ntl = v3_all + ntl for 2000 / 2010
    st = cutout_mod.load_config(REPO / "configs" / "conus_study_area.yaml")
    ntl_layer = [lay for lay in st["layers"] if lay["name"] == "NTL"]
    assert len(ntl_layer) == 1 and ntl_layer[0]["years"] == [2000, 2010] and ntl_layer[0]["dtype"] == "int16"
    real = dcommon.load_config(REPO / "configs" / "conus_rf_v3_ntl.yaml")
    ref = dcommon.load_config(REPO / "configs" / "conus_rf_v3_all.yaml")
    assert real["years"] == [2000, 2010] and real["compare_with"] == ref["version"]
    for e in ("Y2000", "Y2010"):
        assert real["eras"][e]["features"] == ref["eras"][e]["features"] + ["ntl"]
    for k in ("split", "use_status", "train_status", "water_mask", "block_rows", "unusable", "model", "search",
              "models", "permutation"):
        assert real[k] == ref[k], k
    print("ok configs: NTL layer 2000 / 2010; v3_ntl = v3_all + ntl, same model / search / split / statuses")

    tmp = Path(tempfile.mkdtemp())
    try:
        counties = county_table()
        cut, zones = make_cutout(tmp, counties)
        centre = np.hypot(*np.meshgrid(np.arange(W) - 30, np.arange(H) - 20))
        unused = ZERO_POP[2010]  # zone 7: zero_pop in 2010, not allocated
        r7, c7 = (int(v[0]) for v in np.nonzero(zones == unused))
        ntl = write_ntl(cut, centre, [(0, 0), (H - 1, 10), (r7, c7)])  # border (outside zones) + an unused county
        split = make_split.make_split(counties[["GISJOIN", "fips", "state", "name"]], 0.2, 5, 42)
        split_path = tmp / "split.csv"
        split.to_csv(split_path, index=False)
        cfgs = write_configs(tmp, split_path)
        base = yaml.safe_load(cfgs["blocks"].read_text())
        feats = base["eras"]["Y1960"]["features"]
        groups = {**base["feature_groups"], "Night lights": ["ntl"]}
        eras = {"Y1960": {"years": [1960], "features": feats}, "Y2010": {"years": [2010], "features": feats + ["ntl"]}}
        for v, extra in (("ntl", {"block_rows": 7}), ("ntlw", {"block_rows": None})):
            (tmp / "configs" / f"{v}.yaml").write_text(yaml.safe_dump(
                {**base, **extra, "version": v, "eras": eras, "feature_groups": groups, "compare_with": "blocks"}))
            cfgs[v] = tmp / "configs" / f"{v}.yaml"
        out_root = tmp / "dasym"
        common = ["--out-root", str(out_root)]
        cut_args = ["--cutout-root", str(tmp / "cutouts")]
        for v in ("blocks", "ntl", "ntlw"):
            county_features.main(["--config", str(cfgs[v])] + cut_args + common)
        d = out_root / "conus"
        a1960 = pd.read_csv(d / "ntl" / "Y1960" / "features" / "county_features.csv")
        assert "ntl" not in a1960.columns  # the era without ntl reads no NTL layer (there is none for 1960)
        pd.testing.assert_frame_equal(a1960, pd.read_csv(d / "blocks" / "Y1960" / "features" / "county_features.csv"))
        f = pd.read_csv(d / "ntl" / "Y2010" / "features" / "county_features.csv")
        pd.testing.assert_frame_equal(f, pd.read_csv(d / "ntlw" / "Y2010" / "features" / "county_features.csv"),
                                      rtol=1e-12)
        b = pd.read_csv(d / "blocks" / "Y2010" / "features" / "county_features.csv")
        pd.testing.assert_frame_equal(f.drop(columns="ntl"), b)
        bui = read(cut / "layers" / "BUI" / "2010_BUI.tif")
        wf = read(cut / "layers" / "water_frac" / "2010_water_frac.tif")
        keep = ~((wf >= 1) & (bui == 0))
        for r in f.itertuples():  # county ntl = mean DN over its unmasked cells
            m = (zones == r.zone_id) & keep
            assert np.isclose(r.ntl, ntl[m].mean()), r.zone_id
        assert unused not in f["zone_id"].tolist() and f["ntl"].std() > 0
        print("ok features: ntl only in the 2010 era, county mean DN, strips == whole window, nodata outside the "
              "used counties ignored")

        train.main(["--config", str(cfgs["blocks"]), "--n-jobs", "1"] + common)
        train.main(["--config", str(cfgs["ntl"]), "--n-jobs", "1"] + common)
        predict.main(["--config", str(cfgs["ntl"])] + cut_args + ["--n-jobs", "2"] + common)
        imp = pd.read_csv(d / "ntl" / "Y2010" / "model" / "feature_importance.csv")
        assert "ntl" in set(imp["feature"]) and "ntl" not in set(
            pd.read_csv(d / "ntl" / "Y1960" / "model" / "feature_importance.csv")["feature"])
        assert json.loads((d / "ntl" / "Y2010" / "model" / "compare_blocks.json").read_text())["folds"] == \
            "same as this model (checked)"
        p = read(d / "ntl" / "predictions" / "pop_2010.tif")
        zt = pd.read_csv(cut / "zones" / "zones_2010.csv")
        used = zt[zt["status"].isin(["ok", "filled_nhgis", "filled_nhgis_alloc"])]
        sums = np.bincount(zones[p >= 0], weights=p[p >= 0].astype("float64"), minlength=49)
        assert np.allclose(sums[used["zone_id"]], used["pop"], rtol=1e-6) and (p[zones == unused] == predict.NODATA_OUT).all()
        print("ok train / predict with ntl: same folds as the compared version, mass preserved, unused county NoData")

        # NTL nodata inside a used county stops the features (no silent 0)
        r1, c1 = (int(v[0]) for v in np.nonzero(zones == 1))
        write_ntl(cut, centre, [(r1, c1)])
        try:
            county_features.main(["--config", str(cfgs["ntl"]), "--years", "2010"] + cut_args + common)
            raise AssertionError("NTL nodata in a used county was not caught")
        except SystemExit as e:
            assert "nodata cells inside the used counties" in str(e) and "NTL" in str(e), e
        ntl = write_ntl(cut, centre, [(0, 0), (H - 1, 10), (r7, c7)])
        print("ok NTL nodata in a used county: the job stops with the cell count")

        # ntl_qa: the box centroid as the old whole-window version; edges against brute force
        (tmp / "configs" / "qa_study.yaml").write_text(yaml.safe_dump(
            {"name": "conus", "years": YEARS, "states": "all", "layers": [
                {"name": "NTL", "path": "x_{YEAR}.tif", "years": [2010], "resampling": "nearest", "dtype": "int16"}]}))
        cx, cy = TRANSFORM.c + 30.5 * 250, TRANSFORM.f - 20.5 * 250
        lon, lat = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform(cx, cy)
        ntl_qa.main(["--config", str(tmp / "configs" / "qa_study.yaml"), "--cutout-root", str(tmp / "cutouts"),
                     "--lon", str(lon), "--lat", str(lat), "--box-km", "2.9", "--bright", "40", "--edge-km", "0.5",
                     "--glow-dn", "5", "--top", "3"])
        q = pd.read_csv(cut / "qa" / "ntl_qa.csv").iloc[0]
        nd = ntl == NTL_NODATA
        rr, cc = np.mgrid[0:H, 0:W]
        x, y = TRANSFORM.c + (cc + 0.5) * 250, TRANSFORM.f - (rr + 0.5) * 250
        inbox = (np.abs(x - cx) <= 1450) & (np.abs(y - cy) <= 1450)  # 2.9 km box: no cell centre on its edge
        br = inbox & ~nd & (ntl >= 40)
        assert q["box_cells"] == inbox.sum() and q["bright_cells"] == br.sum() > 0
        assert np.isclose(q["centroid_x"], x[br].mean()) and np.isclose(q["centroid_y"], y[br].mean())
        zone = zones > 0
        out_pts = np.argwhere(~zone)
        dmin = np.array([np.hypot(*(out_pts - p).T).min() * 0.25 for p in np.argwhere(zone)])
        edge = np.zeros_like(zone)
        edge[zone] = dmin <= 0.5
        glow = ~nd & (bui == 0) & (ntl >= 5)
        assert q["zone_nodata_cells"] == 1 and q["outside_lit_cells"] == (~zone & ~nd & (ntl > 0)).sum()
        assert q["edge_cells"] == edge.sum() and q["interior_cells"] == (zone & ~edge).sum()
        assert q["edge_glow_cells"] == (glow & edge).sum() and q["interior_glow_cells"] == (glow & zone & ~edge).sum()
        top = pd.read_csv(cut / "qa" / "ntl_glow_counties.csv")
        want = pd.Series(np.bincount(zones[glow & edge], minlength=49)).iloc[1:]
        want = want[want > 0].sort_values(ascending=False, kind="stable")
        assert len(top) == 3 and top["edge_glow_cells"].tolist() == want.head(3).tolist() and top["GISJOIN"].notna().all()
        print("ok ntl_qa: box centroid as before, edge / interior glow and outside-lit counts, top counties")

        # compare_models: --years and --rank-features
        res = tmp / "results"
        for v in ("blocks", "ntl"):
            for e in ("Y1960", "Y2010"):
                shutil.copytree(d / v / e / "model", res / "dasymetric" / "conus" / v / e)
            shutil.copy(d / v / "cv_summary.csv", res / "dasymetric" / "conus" / v)
        out = res / "validation" / "conus" / "ntl_comparison.csv"
        compare_models.main(["--versions", "blocks", "ntl", "--results-root", str(res), "--years", "2010",
                             "--rank-features", "ntl", "--out", str(out)])
        cmp = pd.read_csv(out).set_index("version")
        assert (cmp["year"] == 2010).all() and len(cmp) == 2
        assert pd.isna(cmp.loc["blocks", "ntl_perm_rank"]) and cmp.loc["blocks", "n_features"] == len(feats)
        order = imp.sort_values("permutation_mean", ascending=False, kind="stable")["feature"].tolist()
        assert cmp.loc["ntl", "ntl_perm_rank"] == order.index("ntl") + 1 and cmp.loc["ntl", "n_features"] == len(feats) + 1
        assert 1 <= cmp.loc["ntl", "ntl_shap_rank"] <= len(feats) + 1
        print("ok compare_models --years --rank-features: 2010 only, ntl rank from feature_importance / shap")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_lonlat(path: Path, west, south, east, north, sea_east=None, shift=0.0, negative=False):
    """A 15 arc-second EPSG:4326 raster over the box (as the VIIRS-like files): radiance falling off from the box
    centre, NaN 'sea' west of sea_east (no nodata tag, as a float file may have)."""
    from rasterio.transform import from_origin
    cell = 1 / 240
    w, h = int(np.ceil((east - west) / cell)), int(np.ceil((north - south) / cell))
    lon = west + shift + (np.arange(w) + 0.5) * cell
    lat = north - (np.arange(h) + 0.5) * cell
    d = np.hypot(*np.meshgrid(lon - (west + east) / 2, lat - (south + north) / 2))
    val = (80 * np.exp(-d / 0.03)).astype("float32")
    val[val < 1] = 0  # the producers' rule: < 1 nW -> 0
    if sea_east is not None:
        val[:, lon < sea_east] = np.nan
    if negative:
        val[h // 2, w // 2] = -1
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=w, height=h, count=1, dtype="float32", crs="EPSG:4326",
                       transform=from_origin(west + shift, north, cell, cell)) as dst:
        dst.write(val, 1)


def test_ntlv():
    """Dasy_CONUS_RF_v3_ntlv (docs/conus_plan.md "VIIRS-like NTL test"): the real configs; make_cutout `nodata_to`
    (sea mask -> 0, nothing else changes); a float ntlv era (county mean); ntl_qa.py with NTL and NTLV side by side
    (radiance: percentile box, lit share of BUI 0 cells, negative values fail); ntlv_check.py on a lon/lat raster."""
    import make_cutout as cutout_mod
    import ntl_qa
    import ntlv_check
    from pyproj import Transformer
    from rasterio.warp import transform_bounds

    st = cutout_mod.load_config(REPO / "configs" / "conus_study_area.yaml")
    lay = {lay["name"]: lay for lay in st["layers"]}
    assert lay["NTLV"]["years"] == [2000, 2010] and lay["NTLV"]["dtype"] == "float32"
    assert lay["NTLV"]["resampling"] == "nearest" and lay["NTLV"]["nodata_to"] == 0 and lay["NTL"]["nodata_to"] is None
    real = dcommon.load_config(REPO / "configs" / "conus_rf_v3_ntlv.yaml")
    dmsp = dcommon.load_config(REPO / "configs" / "conus_rf_v3_ntl.yaml")
    assert real["version"] == "Dasy_CONUS_RF_v3_ntlv" and real["compare_with"] == "Dasy_CONUS_RF_v3_all"
    assert real["years"] == [2000, 2010] and real["feature_groups"]["Night lights"] == ["ntlv"]
    for e in ("Y2000", "Y2010"):
        assert real["eras"][e]["features"] == ["ntlv" if f == "ntl" else f for f in dmsp["eras"][e]["features"]]
    for k in ("split", "use_status", "train_status", "water_mask", "block_rows", "unusable", "model", "search",
              "models", "permutation", "maps", "correlation_threshold"):
        assert real[k] == dmsp[k], k
    print("ok configs: NTLV layer 2000 / 2010 float32 nearest nodata_to 0; v3_ntlv = v3_ntl with ntlv for ntl")

    tmp = Path(tempfile.mkdtemp())
    try:
        counties = county_table()
        cut, zones = make_cutout(tmp, counties)
        left, top = TRANSFORM.c, TRANSFORM.f
        bounds = (left, top - H * 250, left + W * 250, top)
        west, south, east, north = transform_bounds(CRS, "EPSG:4326", *bounds, densify_pts=21)
        m = 0.02
        west, south, east, north = west - m, south - m, east + m, north + m

        # make_cutout nodata_to: the sea mask (NaN) becomes 0, every other cell is the plain nearest warp
        src = tmp / "raw" / "2010" / "viirs_like_2010.tif"
        write_lonlat(src, west, south, east, north, sea_east=west + 0.3 * (east - west))
        ref = {"crs": CRS, "transform": TRANSFORM}
        layer = {"label": "NTLV", "name": "NTLV", "class": None, "path": str(src), "years": [2010],
                 "resampling": "nearest", "dtype": "float32", "out": "{name}_cut/{YEAR}_{name}.tif", "nodata_to": 0,
                 "aligned": {2010: False}}
        cutout_mod.cut_layer(layer, 2010, src, TRANSFORM, (H, W), cut, ref)
        cutout_mod.cut_layer({**layer, "nodata_to": None, "out": "{name}_raw/{YEAR}_{name}.tif"}, 2010, src,
                             TRANSFORM, (H, W), cut, ref)
        filled = read(cut / "layers" / "NTLV_cut" / "2010_NTLV.tif")
        raw = read(cut / "layers" / "NTLV_raw" / "2010_NTLV.tif")
        sea = np.isnan(raw)
        assert sea.any() and (sea & (zones > 0)).any() and (~sea & (raw > 0)).any()
        assert np.isfinite(filled).all() and (filled[sea] == 0).all() and np.array_equal(filled[~sea], raw[~sea])
        print("ok make_cutout nodata_to: %d sea cells (%d inside counties) -> 0, the rest = nearest warp"
              % (sea.sum(), (sea & (zones > 0)).sum()))

        # ntlv_check.py: header, coverage, values over the window box; a raster that misses the window fails
        crs_wkt = rasterio.crs.CRS.from_string(CRS).to_wkt()
        (cut / "window.json").write_text(json.dumps({"bounds": list(bounds), "crs_wkt": crs_wkt}))
        chk_cfg = tmp / "chk_study.yaml"
        chk_cfg.write_text(yaml.safe_dump({"name": "conus", "years": YEARS, "states": "all", "layers": [
            {"name": "NTLV", "path": str(tmp / "raw" / "{YEAR}" / "*.tif"), "years": [2010], "resampling": "nearest",
             "dtype": "float32", "nodata_to": 0}]}))
        ntlv_check.main(["--config", str(chk_cfg), "--cutout-root", str(tmp / "cutouts"), "--out", str(tmp / "chk.csv")])
        c = pd.read_csv(tmp / "chk.csv").iloc[0]
        assert c["crs"] == "EPSG:4326" and c["covers_window"] and np.isclose(c["cell_arcsec"], 15)
        assert c["box_nodata"] > 0 and c["box_lit"] > 0 and c["box_negative"] == 0 and c["min"] >= 1
        assert c["box_nodata"] + c["box_zero"] + c["box_lit"] == c["box_cells"]
        write_lonlat(src, west, south, east, north, shift=0.5)  # moved east: misses the window's west part
        try:
            ntlv_check.main(["--config", str(chk_cfg), "--cutout-root", str(tmp / "cutouts"), "--out",
                             str(tmp / "chk.csv")])
            raise AssertionError("a raster missing the window passed")
        except SystemExit as e:
            assert "do not cover the cutout window" in str(e), e
        write_lonlat(src, west, south, east, north, negative=True)
        try:
            ntlv_check.main(["--config", str(chk_cfg), "--cutout-root", str(tmp / "cutouts"), "--out",
                             str(tmp / "chk.csv")])
            raise AssertionError("a negative value passed")
        except SystemExit as e:
            assert "negative cells" in str(e), e
        print("ok ntlv_check: CRS, 15 arc-sec, coverage, nodata / zero / lit counts; missing window and negative fail")

        # features with a float ntlv layer (radiance falling off from the 'city'): county ntlv = mean
        centre = np.hypot(*np.meshgrid(np.arange(W) - 30, np.arange(H) - 20))
        ntlv = (80 * np.exp(-centre / 5)).astype("float32")
        ntlv[ntlv < 1] = 0
        write_tif(cut / "layers" / "NTLV" / "2010_NTLV.tif", ntlv, float("nan"))
        ntl = write_ntl(cut, centre, [(0, 0)])
        split = make_split.make_split(counties[["GISJOIN", "fips", "state", "name"]], 0.2, 5, 42)
        split_path = tmp / "split.csv"
        split.to_csv(split_path, index=False)
        cfgs = write_configs(tmp, split_path)
        base = yaml.safe_load(cfgs["blocks"].read_text())
        feats = base["eras"]["Y2010"]["features"]
        (tmp / "configs" / "ntlv.yaml").write_text(yaml.safe_dump(
            {**base, "block_rows": 7, "version": "ntlv", "eras": {"Y2010": {"years": [2010], "features": feats + ["ntlv"]},
                                                                  "Y1960": base["eras"]["Y1960"]},
             "feature_groups": {**base["feature_groups"], "Night lights": ["ntlv"]}}))
        out_root = tmp / "dasym"
        county_features.main(["--config", str(tmp / "configs" / "ntlv.yaml"), "--cutout-root", str(tmp / "cutouts"),
                              "--out-root", str(out_root)])
        f = pd.read_csv(out_root / "conus" / "ntlv" / "Y2010" / "features" / "county_features.csv")
        bui = read(cut / "layers" / "BUI" / "2010_BUI.tif")
        wf = read(cut / "layers" / "water_frac" / "2010_water_frac.tif")
        keep = ~((wf >= 1) & (bui == 0))
        for r in f.itertuples():
            assert np.isclose(r.ntlv, ntlv[(zones == r.zone_id) & keep].mean()), r.zone_id
        assert f["ntlv"].std() > 0
        print("ok features: ntlv = county mean radiance over unmasked cells (strips)")

        # ntl_qa.py with NTL and NTLV: per-layer CSVs, side by side, radiance rules against brute force
        qa_cfg = tmp / "configs" / "qa_study.yaml"
        qa_cfg.write_text(yaml.safe_dump({"name": "conus", "years": YEARS, "states": "all", "layers": [
            {"name": "NTL", "path": "x_{YEAR}.tif", "years": [2010], "resampling": "nearest", "dtype": "int16"},
            {"name": "NTLV", "path": "y_{YEAR}.tif", "years": [2010], "resampling": "nearest", "dtype": "float32"}]}))
        cx, cy = TRANSFORM.c + 30.5 * 250, TRANSFORM.f - 20.5 * 250
        lon, lat = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform(cx, cy)
        qa_args = ["--config", str(qa_cfg), "--cutout-root", str(tmp / "cutouts"), "--layer", "NTL", "NTLV",
                   "--lon", str(lon), "--lat", str(lat), "--box-km", "2.9", "--bright", "40", "--bright-pct", "90",
                   "--edge-km", "0.5", "--glow-dn", "5", "--glow-rad", "2", "--top", "3"]
        ntl_qa.main(qa_args)
        q = pd.read_csv(cut / "qa" / "ntlv_qa.csv").iloc[0]
        zone = zones > 0
        lit = ntlv[zone & (ntlv > 0)]
        thr = np.percentile(lit, 90)
        rr, cc = np.mgrid[0:H, 0:W]
        x, y = TRANSFORM.c + (cc + 0.5) * 250, TRANSFORM.f - (rr + 0.5) * 250
        inbox = (np.abs(x - cx) <= 1450) & (np.abs(y - cy) <= 1450)
        assert q["layer"] == "NTLV" and q["scale"] == "radiance" and np.isclose(q["bright_threshold"], thr)
        assert q["bright_cells"] == (inbox & (ntlv >= thr)).sum() > 0 and q["negative"] == 0
        out_pts = np.argwhere(~zone)
        dmin = np.array([np.hypot(*(out_pts - p).T).min() * 0.25 for p in np.argwhere(zone)])
        edge = np.zeros_like(zone)
        edge[zone] = dmin <= 0.5
        for name, part in (("edge", edge), ("interior", zone & ~edge)):
            b0, b1 = part & (bui == 0), part & (bui > 0)
            assert np.isclose(q[f"{name}_lit_bui0_share"], (ntlv[b0] > 0).mean()), name
            assert np.isclose(q[f"{name}_bui0_to_built"], ntlv[b0].mean() / ntlv[b1].mean()), name
            assert q[f"{name}_glow_cells"] == (b0 & (ntlv >= 2)).sum(), name
        n = pd.read_csv(cut / "qa" / "ntl_qa.csv").iloc[0]
        assert n["layer"] == "NTL" and n["bright_threshold"] == 40 and n["bright_cells"] == (inbox & (ntl >= 40)).sum()
        side = pd.read_csv(cut / "qa" / "ntl_edges_compare.csv")
        assert side["layer"].tolist() == ["NTL", "NTLV"] and (side["year"] == 2010).all()
        assert (cut / "qa" / "ntlv_glow_counties.csv").exists()
        ntlv[25, 25] = -0.5
        write_tif(cut / "layers" / "NTLV" / "2010_NTLV.tif", ntlv, float("nan"))
        try:
            ntl_qa.main(qa_args)
            raise AssertionError("a negative NTLV value passed")
        except SystemExit as e:
            assert "NTLV 2010: 1 negative cells" in str(e) and "DN >=" not in str(e), e
        print("ok ntl_qa NTL + NTLV: percentile box, lit share / ratio on BUI 0 cells, glow, side-by-side CSV, "
              "negative fails")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_conus_counties()
    test_ntl()
    test_ntlv()
    test_pipeline()
    print("ALL OK")
