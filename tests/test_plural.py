"""Synthetic test of the PLURAL grid test (docs/conus_plan.md "PLURAL grid test"), runnable without the cluster:

    python tests/test_plural.py      (hisdac env; on Windows with its Library\\bin on PATH, see CLAUDE.md)

Checks:
  - configs: PLURAL (bilinear) / PLURALC (cubic, clip [0, 1]) layers 1940 / 1980 / 2010; v5.6 (u070) gets eras Y1940 /
    Y1980 with v5.4's features; the six variants = v5.6 + plural (same split, exclusions, search ...) with their
    plural block
  - resampling = alignment: a source in LAEA 45N 100W (900 m) holding a linear field, cut onto an Albers 250 m grid
    with make_cutout: bilinear and cubic give the field at every cell centre (a half-pixel shift would not)
  - cubic clipping: a 0 / 1 step overshoots with cubic; with clip [0, 1] every value is inside and the clipped cells
    are the ones outside before; bilinear never leaves 0-1
  - plural_qa.py: 0 fill outside the counties; interior cells untouched; edge cells = (1 - out_w) x the US value, so
    the logged deficit is exactly the fill's pull; points
  - plural feature: equal / quantile breaks (quantiles of the year's study cells), class numbers, county mean, strips
    == whole window, plural_breaks.csv; predict finds the same breaks, a changed breaks file stops it
  - a new era added with --years (1940 / 1980 into v5.6): the other era's files and CSV rows stay byte for byte
  - plural_compare.py on small result files: common tracts, sets, MAPE >= 10, d_mdape, TEST check, plural rank,
    best classed variant, figure (in a subprocess with the real plots module)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path[:0] = [str(Path(__file__).resolve().parent)]
import test_conus_dasymetric as T  # noqa: E402  (stubs shap / plots; synthetic cutout + configs)

import rasterio  # noqa: E402
import yaml  # noqa: E402
from affine import Affine  # noqa: E402
from pyproj import Transformer  # noqa: E402

import common as dcommon  # noqa: E402
import county_features  # noqa: E402
import make_cutout  # noqa: E402
import predict  # noqa: E402
import train  # noqa: E402

REPO = T.REPO
LAEA = "+proj=laea +lat_0=45 +lon_0=-100 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
VARIANTS = {"plc": ("PLURAL", None, None), "plcc": ("PLURALC", None, None), "pq3": ("PLURAL", 3, "quantile"),
            "pq5": ("PLURAL", 5, "quantile"), "pe3": ("PLURAL", 3, "equal"), "pe5": ("PLURAL", 5, "equal")}


def test_configs():
    st = make_cutout.load_config(REPO / "configs" / "conus_study_area.yaml")
    lay = {x["name"]: x for x in st["layers"]}
    for n, res in (("PLURAL", "bilinear"), ("PLURALC", "cubic")):
        assert lay[n]["years"] == [1940, 1980, 2010] and lay[n]["resampling"] == res and lay[n]["dtype"] == "float32"
        assert lay[n]["path"].endswith("index3_{YEAR}_900_US.tif") and lay[n]["nodata_to"] is None
    assert lay["PLURALC"]["clip"] == [0, 1] and lay["PLURAL"]["clip"] is None
    base = dcommon.load_config(REPO / "configs" / "conus_rf_v3_u070.yaml")
    v54 = dcommon.load_config(REPO / "configs" / "conus_rf_v3_all.yaml")
    assert base["years"] == [1920, 1940, 1960, 1980, 2010, 2020]
    for e in base["eras"]:
        assert base["eras"][e]["features"] == v54["eras"][e]["features"], e
    for v, (layer, k, brk) in VARIANTS.items():
        c = dcommon.load_config(REPO / "configs" / f"conus_rf_v3_u070_{v}.yaml")
        assert c["version"] == f"Dasy_CONUS_RF_v3_u070_{v}" and c["years"] == [1940, 1980, 2010]
        assert c["compare_with"] == "Dasy_CONUS_RF_v3_u070"
        assert c["plural"] == {"layer": layer, "classes": k, "breaks": brk}, c["plural"]
        for e in ("Y1940", "Y1980", "Y2010"):
            assert c["eras"][e]["features"] == base["eras"][e]["features"] + ["plural"]
        for key in ("split", "exclude_counties", "use_status", "train_status", "water_mask", "block_rows", "unusable",
                    "model", "search", "models", "permutation", "correlation_threshold"):
            assert c[key] == base[key], (v, key)
        assert c["feature_groups"]["PLURAL"] == ["plural"]
    print("ok configs: PLURAL / PLURALC layers; v5.6 + Y1940 / Y1980 (v5.4 features); six variants = v5.6 + plural")


def write_src(path: Path, arr, transform, crs=LAEA):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1, dtype="float32",
                       crs=crs, transform=transform) as dst:
        dst.write(arr.astype("float32"), 1)


def laea_box(transform, shape, pad=5000.0):
    """LAEA bounds of an Albers window (+ pad), from its corners and edges."""
    h, w = shape
    xs = transform.c + np.r_[np.linspace(0, w, 20), np.full(20, w), np.linspace(0, w, 20), np.zeros(20)] * transform.a
    ys = transform.f + np.r_[np.zeros(20), np.linspace(0, h, 20), np.full(20, h), np.linspace(0, h, 20)] * transform.e
    lx, ly = Transformer.from_crs(T.CRS, LAEA, always_xy=True).transform(xs, ys)
    return min(lx) - pad, min(ly) - pad, max(lx) + pad, max(ly) + pad


def src_grid(box, cell=900.0):
    x0, y0, x1, y1 = box
    w, h = int(np.ceil((x1 - x0) / cell)), int(np.ceil((y1 - y0) / cell))
    t = Affine(cell, 0, x0, 0, -cell, y1)
    cols, rows = np.meshgrid(np.arange(w), np.arange(h))
    return t, (h, w), x0 + (cols + 0.5) * cell, y1 - (rows + 0.5) * cell  # pixel centres


def layer_entry(name, path, res, clip=None):
    return {"label": name, "name": name, "class": None, "path": str(path), "years": [2010], "resampling": res,
            "dtype": "float32", "out": "{name}/{YEAR}_{name}.tif", "nodata_to": None, "clip": clip,
            "aligned": {2010: False}}


def test_resample():
    tmp = Path(tempfile.mkdtemp())
    try:
        cut = tmp / "cut"
        H, W, TR = T.H, T.W, T.TRANSFORM
        box = laea_box(TR, (H, W))
        st, shape, X, Y = src_grid(box)
        a, b = 0.6 / (box[2] - box[0]), 0.3 / (box[3] - box[1])
        field = lambda x, y: 0.05 + a * (x - box[0]) + b * (y - box[1])  # noqa: E731  linear, 0.05-0.95
        write_src(tmp / "src" / "lin_2010.tif", field(X, Y), st)
        ref = {"crs": T.CRS, "transform": TR}
        cols, rows = np.meshgrid(np.arange(W), np.arange(H))
        cx, cy = TR.c + (cols + 0.5) * TR.a, TR.f + (rows + 0.5) * TR.e
        lx, ly = Transformer.from_crs(T.CRS, LAEA, always_xy=True).transform(cx, cy)
        want = field(lx, ly)
        for name, res in (("BIL", "bilinear"), ("CUB", "cubic")):
            make_cutout.cut_layer(layer_entry(name, tmp / "src" / "lin_2010.tif", res), 2010,
                                  tmp / "src" / "lin_2010.tif", TR, (H, W), cut, ref)
            got = T.read(cut / "layers" / name / f"2010_{name}.tif").astype("float64")
            err = np.abs(got - want).max()
            assert err < 2e-4, (res, err)
            shifted = np.abs(got - field(lx + 450.0, ly)).max()  # half a source pixel off
            assert shifted > 20 * err and shifted > 1e-3, (res, shifted)
        print("ok resampling = alignment: bilinear / cubic of a linear LAEA field = the field at every 250 m cell centre "
              "(max error %.1e; half a pixel off: %.1e)" % (err, shifted))

        # cubic overshoots at a 0 / 1 step; clip [0, 1] keeps it inside and changes only those cells
        step = (X > (box[0] + box[2]) / 2).astype("float32")
        write_src(tmp / "src" / "step_2010.tif", step, st)
        p = tmp / "src" / "step_2010.tif"
        for name, res, clip in (("CRAW", "cubic", None), ("CCLIP", "cubic", [0, 1]), ("BSTEP", "bilinear", None)):
            make_cutout.cut_layer(layer_entry(name, p, res, clip), 2010, p, TR, (H, W), cut, ref)
        raw = T.read(cut / "layers" / "CRAW" / "2010_CRAW.tif")
        cl = T.read(cut / "layers" / "CCLIP" / "2010_CCLIP.tif")
        bil = T.read(cut / "layers" / "BSTEP" / "2010_BSTEP.tif")
        out = (raw < 0) | (raw > 1)
        assert out.sum() > 0 and (raw < 0).any() and (raw > 1).any()
        assert cl.min() >= 0 and cl.max() <= 1 and np.array_equal(cl[~out], raw[~out])
        assert np.array_equal(cl[out], np.clip(raw[out], 0, 1)) and bil.min() >= 0 and bil.max() <= 1
        print("ok cubic clip: %d cells outside 0-1 before (min %.3f, max %.3f), none after; the rest unchanged; "
              "bilinear stays in 0-1" % (out.sum(), raw.min(), raw.max()))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_plural_qa():
    """Counties in rows 8-51, columns 8-59; outside (0 fill) all around. US value 0.6 everywhere."""
    import plural_qa
    tmp = Path(tempfile.mkdtemp())
    try:
        H, W = 60, 80
        TR = T.TRANSFORM
        cut = tmp / "cutouts" / "conus"
        zones = np.zeros((H, W), "uint16")
        zones[8:52, 8:60] = 1 + np.arange(52)[None, :] // 18  # 3 counties side by side, outside all around
        (cut / "zones").mkdir(parents=True)
        with rasterio.open(cut / "zones" / "zones_2010.tif", "w", driver="GTiff", width=W, height=H, count=1,
                           dtype="uint16", crs=T.CRS, transform=TR, nodata=0) as dst:
            dst.write(zones, 1)
        box = laea_box(TR, (H, W), pad=20000)
        st, shape, X, Y = src_grid(box)
        # source: 0.6 where the pixel centre lies in a county, 0 elsewhere (fill), as Siqiao's grid
        ax, ay = Transformer.from_crs(LAEA, T.CRS, always_xy=True).transform(X, Y)
        c = np.floor((ax - TR.c) / TR.a).astype(int)
        r = np.floor((ay - TR.f) / TR.e).astype(int)
        inside = (r >= 0) & (r < H) & (c >= 0) & (c < W)
        zsrc = np.zeros(shape, "uint16")
        zsrc[inside] = zones[r[inside], c[inside]]
        src = np.where(zsrc > 0, 0.6, 0.0)
        p = tmp / "src" / "index3_2010_900_US.tif"
        write_src(p, src, st)
        cfg = tmp / "study.yaml"
        lon, lat = Transformer.from_crs(T.CRS, "EPSG:4326", always_xy=True).transform(TR.c + 30.5 * 250,
                                                                                       TR.f - 30.5 * 250)
        cfg.write_text(yaml.safe_dump({
            "name": "conus", "years": [2010], "states": "all", "grid_reference": "BUI",
            "layers": [{"name": "PLURAL", "path": str(tmp / "src" / "index3_{YEAR}_900_US.tif"), "years": [2010],
                        "resampling": "bilinear", "dtype": "float32"},
                       {"name": "PLURALC", "path": str(tmp / "src" / "index3_{YEAR}_900_US.tif"), "years": [2010],
                        "resampling": "cubic", "dtype": "float32", "clip": [0, 1]}],
            "plural_qa": {"layers": ["PLURAL", "PLURALC"], "edge_km": 2,
                          "points": [{"name": "inland", "lon": float(lon), "lat": float(lat)}]}}))
        lays = make_cutout.load_config(cfg)["layers"]
        for lay in lays:
            lay["aligned"] = {2010: False}
            make_cutout.cut_layer(lay, 2010, p, TR, (H, W), cut, {"crs": T.CRS, "transform": TR})
        plural_qa.main(["--config", str(cfg), "--cutout-root", str(tmp / "cutouts")])
        qa = pd.read_csv(cut / "qa" / "plural_qa.csv")
        pts = pd.read_csv(cut / "qa" / "plural_points.csv")
        q = qa.set_index(["layer", "part"])
        assert q.loc[("source", "outside_pixels"), "share_zero"] == 1.0
        assert q.loc[("source", "inside_pixels"), "share_zero"] == 0.0
        v = T.read(cut / "layers" / "PLURAL" / "2010_PLURAL.tif").astype("float64")
        assert np.allclose(v[17:43, 17:51], 0.6, atol=1e-5)  # > 2 km from the outside: untouched
        it = q.loc[("PLURAL", "interior")]
        assert it["touched_cells"] == 0 and np.isclose(it["p05"], 0.6, atol=1e-5)
        ed = q.loc[("PLURAL", "edge")]
        assert ed["touched_cells"] > 0 and ed["p05"] < 0.6
        # bilinear: value = (1 - out_w) x 0.6, so the deficit = 0.6 - value on the touched county cells
        w = plural_qa.outside_weight(zones, TR, rasterio.crs.CRS.from_string(T.CRS), p, "bilinear")[0]
        w = np.nan_to_num(w)
        ok = (zones > 0) & (w > plural_qa.TOUCHED) & (w < plural_qa.RENORM_MAX)
        assert ok.any() and ((zones > 0) & (w > plural_qa.TOUCHED)).sum() == ed["touched_cells"]
        assert np.allclose(v[ok] / (1 - w[ok]), 0.6, atol=1e-4)  # renormalized = the US value
        assert np.isclose(ed["deficit_mean"], (0.6 - v[ok]).mean(), atol=1e-4)  # touched cells are all edge cells
        assert np.isclose(ed["deficit_max"], (0.6 - v[ok]).max(), atol=1e-4)
        pt = pts.iloc[0]
        assert np.isclose(pt["source_900m"], 0.6) and np.isclose(pt["PLURAL"], 0.6, atol=1e-5) and pt["PLURAL_out_w"] == 0
        print("ok plural_qa: fill 0 outside, interior untouched, edge deficit = 0.6 - value (mean %.3f, max %.3f), "
              "point source = 250 m value" % (ed["deficit_mean"], ed["deficit_max"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def plural_config(tmp: Path, base: dict, name: str, spec: dict, years=(2010,), block_rows=7, exclude=None):
    feats = base["eras"]["Y2010"]["features"]
    eras = {f"Y{y}": {"years": [y], "features": feats + ["plural"]} for y in years}
    cfg = {**base, "version": name, "years": list(years), "block_rows": block_rows, "eras": eras, "plural": spec,
           "feature_groups": {**base["feature_groups"], "PLURAL": ["plural"]}}
    if block_rows is None:
        cfg.pop("block_rows")
    if exclude:
        cfg["exclude_counties"] = str(exclude)
    p = tmp / "configs" / f"{name}.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


def test_plural_feature():
    tmp = Path(tempfile.mkdtemp())
    try:
        counties = T.county_table()
        cut, zones = T.make_cutout(tmp, counties)
        rng = np.random.default_rng(3)
        centre = np.hypot(*np.meshgrid(np.arange(T.W) - 30, np.arange(T.H) - 20))
        pl = np.clip(centre / centre.max() + 0.05 * rng.random((T.H, T.W)), 0, 1).astype("float32")
        pl[::5, ::3] = 0.0  # ties (urban zeros)
        for y in T.YEARS:
            T.write_tif(cut / "layers" / "PLURAL" / f"{y}_PLURAL.tif", pl, float("nan"))
        split = T.make_split.make_split(counties[["GISJOIN", "fips", "state", "name"]], 0.2, 5, 42)
        split_path = tmp / "split.csv"
        split.to_csv(split_path, index=False)
        cfgs = T.write_configs(tmp, split_path)
        base = yaml.safe_load(cfgs["blocks"].read_text())
        out_root = tmp / "dasym"
        common = ["--out-root", str(out_root)]
        cutr = ["--cutout-root", str(tmp / "cutouts")]
        specs = {"cont": {"layer": "PLURAL", "classes": None}, "q3": {"layer": "PLURAL", "classes": 3, "breaks": "quantile"},
                 "e5": {"layer": "PLURAL", "classes": 5, "breaks": "equal"}}
        for k, s in specs.items():
            for br in (7, None):
                cfg = plural_config(tmp, base, f"{k}_{br}", s, block_rows=br)
                county_features.main(["--config", str(cfg)] + cutr + common)
        zt = pd.read_csv(cut / "zones" / "zones_2010.csv")
        use = zt[zt["status"].isin(base["use_status"]) & (zt["pop"] > 0)]["zone_id"].to_numpy()
        used = np.isin(zones, use)
        bui = T.read(cut / "layers" / "BUI" / "2010_BUI.tif")
        wf = T.read(cut / "layers" / "water_frac" / "2010_water_frac.tif")
        keep = ~((wf >= 1) & (bui == 0))
        qb = np.quantile(pl[used].astype("float64"), [1 / 3, 2 / 3])
        for k, s in specs.items():
            a = pd.read_csv(out_root / "conus" / f"{k}_7" / "Y2010" / "features" / "county_features.csv")
            b = pd.read_csv(out_root / "conus" / f"{k}_None" / "Y2010" / "features" / "county_features.csv")
            pd.testing.assert_frame_equal(a, b, rtol=1e-12)
            inner = None if not s["classes"] else (qb if s["breaks"] == "quantile" else np.arange(1, 5) / 5)
            cellv = pl.astype("float64") if inner is None else np.digitize(pl, inner) + 1.0
            for r in a.itertuples():
                assert np.isclose(r.plural, cellv[(zones == r.zone_id) & keep].mean()), (k, r.zone_id)
            brk = out_root / "conus" / f"{k}_7" / "Y2010" / "features" / "plural_breaks.csv"
            if inner is None:
                assert not brk.exists()
                continue
            t = pd.read_csv(brk).iloc[0]
            got = t[[f"break_{i}" for i in range(1, len(inner) + 1)]].to_numpy(float)
            assert np.allclose(got, inner, rtol=0, atol=1e-12), (k, got, inner)
            shares = t[[f"share_{i}" for i in range(1, s["classes"] + 1)]].to_numpy(float)
            assert np.isclose(shares.sum(), 1) and t["study_cells"] == used.sum()
            assert a["plural"].between(1, s["classes"]).all() and a["plural"].std() > 0
        assert np.allclose(dcommon.plural_classes(np.array([0.0, 0.2, 0.2001, 0.99, 1.0]), np.arange(1, 5) / 5),
                           [1, 2, 2, 5, 5])
        print("ok plural feature: continuous / quantile 3 / equal 5, county mean of cell classes, strips == whole "
              "window, quantile breaks = study cells, plural_breaks.csv")

        # predict with the classed variant: same breaks found again; a changed file stops it
        cfg = tmp / "configs" / "q3_7.yaml"
        train.main(["--config", str(cfg), "--n-jobs", "1"] + common)
        predict.main(["--config", str(cfg)] + cutr + common)
        qa = pd.read_csv(out_root / "conus" / "q3_7" / "qa" / "reallocation_qa.csv")
        assert (qa["rel_diff"] < 1e-6).all() and set(qa["year"]) == {2010}
        brk = out_root / "conus" / "q3_7" / "Y2010" / "features" / "plural_breaks.csv"
        t = pd.read_csv(brk)
        t["break_1"] += 0.01
        t.to_csv(brk, index=False)
        try:
            predict.main(["--config", str(cfg)] + cutr + common)
            raise AssertionError("changed breaks passed")
        except SystemExit as e:
            assert "plural breaks" in str(e) and "differ" in str(e), e
        print("ok predict: classed plural with the breaks of the features (mass preserved); changed breaks stop it")

        # a new era added with --years (as 1940 / 1980 into v5.6, with exclude_counties): the old era is untouched
        ex = tmp / "excluded.csv"
        pd.DataFrame({"GISJOIN": counties["GISJOIN"].iloc[[2, 17, 30]], "reason": "test"}).to_csv(ex, index=False)
        one = plural_config(tmp, base, "grow", specs["cont"], years=(2010,), exclude=ex)
        c1 = yaml.safe_load(one.read_text())
        c1["years"] = [2010]
        one.write_text(yaml.safe_dump(c1))
        for step in (county_features, train, predict):
            step.main(["--config", str(one)] + ([] if step is train else cutr) + common
                      + (["--n-jobs", "1"] if step is train else []))
        v = out_root / "conus" / "grow"
        old_files = sorted(p for p in (v / "Y2010").rglob("*") if p.is_file())
        before = {p: p.read_bytes() for p in old_files + [v / "predictions" / "pop_2010.tif"]}
        csvs = {f: pd.read_csv(f, float_precision="round_trip") for f in
                (v / "cv_summary.csv", v / "qa" / "reallocation_qa.csv", v / "qa" / "water_mask_by_year.csv")}
        c2 = {**c1, "years": [1960, 2010],
              "eras": {"Y1960": {"years": [1960], "features": c1["eras"]["Y2010"]["features"]}, **c1["eras"]}}
        one.write_text(yaml.safe_dump(c2))
        county_features.main(["--config", str(one), "--years", "1960"] + cutr + common)
        train.main(["--config", str(one), "--years", "1960", "--n-jobs", "1"] + common)
        predict.main(["--config", str(one), "--years", "1960"] + cutr + common)
        for p, b in before.items():
            assert p.read_bytes() == b, p
        for f, old in csvs.items():
            new = pd.read_csv(f, float_precision="round_trip")
            key = "era" if "era" in old and "zone_id" not in old else "year"
            kept = new[new[key].isin(old[key])].reset_index(drop=True)
            pd.testing.assert_frame_equal(kept[old.columns], old, check_dtype=False)
            assert len(new) > len(old), f
        assert (v / "Y1960" / "model" / "excluded_predictions.csv").exists()
        print("ok --years adds an era: %d files of the old era + its prediction byte for byte, cv_summary / "
              "reallocation_qa / water_mask_by_year keep the old rows" % len(before))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_results(root: Path, versions: dict, years, rng):
    """Small result files of a base and variants: tract errors (variant error = base error x factor) + county files."""
    tracts = pd.DataFrame({"GISJOIN": [f"T{i:04d}" for i in range(400)], "zone_gisjoin": [f"G{i % 20:03d}" for i in range(400)],
                           "n_cells": rng.integers(1, 200, 400), "pop_obs": rng.integers(5, 6000, 400).astype(float)})
    tracts["gap"] = tracts["zone_gisjoin"].isin(["G000", "G001"])
    err = rng.normal(0, 0.3, 400)
    for v, f in versions.items():
        for y in years:
            t = tracts.assign(flag="ok", pop_model=tracts["pop_obs"] * (1 + f * err),
                              pop_baseline=tracts["pop_obs"] * (1 + 2 * err))
            if v.endswith("_pq3"):
                t.loc[3, "flag"] = "outside_model"  # left out of every version's scores
            d = root / "validation" / "conus" / v
            d.mkdir(parents=True, exist_ok=True)
            t.to_csv(d / f"tract_errors_{y}.csv", index=False)
            e = root / "dasymetric" / "conus" / v / f"Y{y}"
            e.mkdir(parents=True, exist_ok=True)
            cf = pd.DataFrame({"GISJOIN": [f"G{i:03d}" for i in range(20)], "pop": rng.integers(1000, 9000, 20) * 1.0,
                               "area_km2": 100.0})
            cf["y"] = np.log(cf["pop"] / cf["area_km2"])
            cf.to_csv(e / "county_features.csv", index=False)
            test = cf.iloc[:6].assign(y_hat=lambda d: d["y"] + f * 0.1)
            test[["GISJOIN", "y", "y_hat"]].to_csv(e / "test_predictions.csv", index=False)
            (e / "metrics.json").write_text(json.dumps({"cv_rmse_mean": 0.4 * f, "cv_r2_mean": 0.9, "test_rmse": 0.45,
                                                        "test_r2": 0.91}))
            if "_p" in v:
                fe = ["bui", "plural", "elev"]
                pd.DataFrame({"feature": fe, "permutation_mean": [0.5, 0.2, 0.1]}).to_csv(e / "feature_importance.csv", index=False)
                pd.DataFrame({"feature": fe, "mean_abs_shap": [0.3, 0.05, 0.1]}).to_csv(e / "shap_importance.csv", index=False)
    return tracts, err


def test_compare():
    import plural_compare
    tmp = Path(tempfile.mkdtemp())
    try:
        base = "Dasy_CONUS_RF_v3_u070"
        versions = {base: 1.0, f"{base}_plc": 0.8, f"{base}_pq3": 0.9, f"{base}_pe3": 0.5}
        years = [1940, 2010]
        tracts, err = write_results(tmp, versions, years, np.random.default_rng(1))
        ex = tmp / "excluded.csv"
        pd.DataFrame({"GISJOIN": ["G003", "G004"]}).to_csv(ex, index=False)
        args = ["--results-root", str(tmp), "--exclusions", str(ex), "--years", *map(str, years), "--variants", "plc",
                "pq3", "pe3", "--out-dir", str(tmp / "out")]
        env_py = sys.executable  # figure with the real plots module: a fresh interpreter
        r = subprocess.run([env_py, str(REPO / "src" / "validation" / "plural_compare.py"), *args], capture_output=True,
                           text=True, cwd=REPO)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        assert (tmp / "out" / "plural_comparison.png").stat().st_size > 10_000
        cmp = pd.read_csv(tmp / "out" / "plural_comparison.csv")
        keep = tracts.drop(index=3)
        e = err[keep.index]
        for var, f in (("base", 1.0), ("plc", 0.8), ("pe3", 0.5), ("areal_weighting", 2.0)):
            r_all = cmp[(cmp["variant"] == var) & (cmp["level"] == "tract") & (cmp["set"] == "all") & (cmp["year"] == 2010)].iloc[0]
            assert r_all["n"] == 399 and np.isclose(r_all["mdape"], 100 * np.median(np.abs(f * e))), var
            big = keep["pop_obs"].to_numpy() >= 10
            assert np.isclose(r_all["mape"], 100 * np.mean(np.abs(f * e[big]))), var
            g = cmp[(cmp["variant"] == var) & (cmp["set"] == "excluded_t070") & (cmp["year"] == 2010)].iloc[0]
            assert g["n"] == keep["zone_gisjoin"].isin(["G003", "G004"]).sum() and g["counties"] == 2
            assert np.isclose(r_all["d_mdape"], r_all["mdape"] - 100 * np.median(np.abs(e)))
        dens = keep["pop_obs"] / (keep["n_cells"] * 0.0625)
        d0 = cmp[(cmp["variant"] == "base") & (cmp["set"] == "dens_0_50") & (cmp["year"] == 1940)].iloc[0]
        assert d0["n"] == (dens < 50).sum()
        gp = cmp[(cmp["variant"] == "base") & (cmp["set"] == "gap") & (cmp["year"] == 1940)].iloc[0]
        assert gp["n"] == keep["gap"].sum()
        c = cmp[(cmp["level"] == "county") & (cmp["variant"] == "pq3") & (cmp["year"] == 2010)].iloc[0]
        assert np.isclose(c["mdape"], 100 * abs(np.exp(0.09) - 1)) and c["n"] == 6 and np.isclose(c["cv_rmse"], 0.36)
        assert c["plural_perm_rank"] == 2 and c["plural_shap_rank"] == 3 and c["n_features"] == 3
        best = (tmp / "out" / "plural_best.txt").read_text().strip()
        assert best == f"{base}_pe3", best
        assert "RULE RESULT: best classed variant pe3" in r.stdout
        # a variant with other TEST counties stops the comparison
        tp = tmp / "dasymetric" / "conus" / f"{base}_plc" / "Y2010" / "test_predictions.csv"
        pd.read_csv(tp).iloc[:5].to_csv(tp, index=False)
        try:
            plural_compare.main(args)
            raise AssertionError("different TEST counties passed")
        except SystemExit as ex_:
            assert "TEST counties differ" in str(ex_), ex_
        print("ok plural_compare: common tracts, sets (kept / excluded t070, gap, density), MdAPE / MAPE >= 10 by hand, "
              "d_mdape, TEST MdAPE before allocation, plural rank, best classed = pe3, figure; other TEST set stops it")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_configs()
    test_resample()
    test_plural_qa()
    test_plural_feature()
    test_compare()
    print("ALL OK")
