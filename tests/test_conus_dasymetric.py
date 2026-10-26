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
  - terrain (elev, slope; v3 / v4): strips (one halo row) == whole window, cell by cell and as county features
  - bui_qa.py: quantiles, cap counts and the top cells with their county and bldg_size
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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_conus_counties()
    test_pipeline()
    print("ALL OK")
