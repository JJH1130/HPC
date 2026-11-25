"""Synthetic test of `cap_allocation.py transfer` (cap transfer: learn county group shares from GHS in 2010, apply them
to other years; docs/handoff/cap_transfer_request.md):

    python tests/test_cap_transfer.py      (needs the hisdac env: rasterio, geopandas, scikit-learn, scipy, matplotlib)

  test_scale        scaled shares by hand: undated x f_c, the removed share to built / no_record in proportion, sum 1;
                    a county with only undated cells keeps its shares; NaN rows stay NaN
  test_factor       f_c = clip(bupr_year / bupr_ref, 0, 1), 1 where bupr_ref = 0, rules; a missing county stops
  test_features     common feature list over the eras / county features of every year (learn year's order); a
                    GHS-derived name stops; pq5_unbuilt score
  test_run          end to end on a 16-county world, years 1980 + 2010 (learn), PLURAL / pq5 only in 2010: the 2010
                    targets by hand (GHS-POP / GHS-BUILT-S total - NRES moved to the cells), the cap models refit by
                    hand = the y1 / y2 of 1980 (the 2010 models on the 1980 features: other features -> other shares)
                    and of the 2010 TEST counties, scaled = by hand, direct = the targets, county sums kept, v57 + v57
                    = v5.7 (cells and tract file), a 2010 combination's tract sums and MdAPE by hand, 1980 = score v57
                    only ("no PLURAL grid"), circular column, d_mdape; --check writes nothing; a changed tract
                    pop_model / missing bupr county stops with nothing written; the 1980 `run` mode untouched
  test_real_config  the cap_transfer block of configs/external_grids.yaml + its tracked inputs
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "validation"))
sys.path.insert(0, str(REPO / "src" / "dasymetric"))
sys.path.insert(0, str(REPO / "tests"))

import rasterio  # noqa: E402
import yaml  # noqa: E402
from pyproj import Transformer  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402

import cap_allocation as ca  # noqa: E402
import external_city_density as ecd  # noqa: E402
import external_city_maps as ecm  # noqa: E402
import tract_validate as tv  # noqa: E402
from test_external_city_maps import write  # noqa: E402
from test_external_city_meeting import OUR  # noqa: E402
from test_missed_cells import expect_exit  # noqa: E402

H = W = 96                        # 4 x 4 counties of 24 x 24 cells
YEARS = (1980, 2010)
GJ = [f"G01{i:04d}0" for i in range(1, 17)]
FEATS = {1980: ["bui", "bldg_size", "mu_ratio", "nby"], 2010: ["bui", "bldg_size", "mu_ratio", "res_share", "nby"]}
RF = {"n_estimators": 20, "min_samples_leaf": 2, "max_features": 0.5, "random_state": 42}


def test_scale(tmp: Path):
    S = np.array([[0.5, 0.3, 0.2], [0.0, 1.0, 0.0], [0.6, 0.4, 0.0], [np.nan] * 3])
    f = np.array([0.5, 0.2, 0.0, 0.7])
    out, kept = ca.scale_undated(S, f)
    # row 0: undated 0.15, removed 0.15 -> built 0.5 + 0.15 x 0.5 / 0.7, no_record 0.2 + 0.15 x 0.2 / 0.7
    assert np.allclose(out[0], [0.5 + 0.15 * 5 / 7, 0.15, 0.2 + 0.15 * 2 / 7])
    assert np.allclose(out[1], S[1]) and kept == 1                    # only undated cells: kept
    assert np.allclose(out[2], [1.0, 0.0, 0.0]) and np.isnan(out[3]).all()
    assert np.allclose(out[:3].sum(axis=1), 1)
    print("ok scale: undated x f, removed share to built / no_record in proportion, sum 1, undated-only kept")


def test_factor(tmp: Path):
    b = pd.DataFrame({"GISJOIN": ["A", "B", "C", "D"], "bupr_1980": [10.0, 30.0, 5.0, 0.0],
                      "bupr_2015": [40.0, 20.0, 0.0, 8.0]})
    f, rule = ca.f_factor(pd.Series(["C", "A", "B", "D"]), b, 1980, 2015)
    assert np.allclose(f, [1.0, 0.25, 1.0, 0.0]) and list(rule) == ["ref_zero", "ratio", "clipped_1", "ratio"]
    assert "missing" in expect_exit(ca.f_factor, pd.Series(["A", "E"]), b, 1980, 2015)
    assert "bupr_1960" in expect_exit(ca.f_factor, pd.Series(["A"]), b, 1960, 2015)
    print("ok factor: clip(bupr_year / bupr_ref), 1 where bupr_ref = 0, a missing county stops")


def test_features(tmp: Path):
    mc = tmp / "m.yaml"
    mc.write_text(yaml.safe_dump({"eras": {f"Y{y}": {"features": FEATS[y]} for y in YEARS}}))
    cfs = {y: pd.DataFrame(columns=["GISJOIN", *FEATS[2010]]) for y in YEARS}
    keep, dropped = ca.common_features(mc, [2010, 1980], cfs)
    assert keep == ["bui", "bldg_size", "mu_ratio", "nby"] and dropped == ["res_share"]
    cfs[1980] = cfs[1980].drop(columns=["mu_ratio"])               # a column missing in one year's file
    assert ca.common_features(mc, [2010, 1980], cfs)[0] == ["bui", "bldg_size", "nby"]
    mc.write_text(yaml.safe_dump({"eras": {f"Y{y}": {"features": ["bui", "ghs_share"]} for y in YEARS}}))
    cfs = {y: pd.DataFrame(columns=["GISJOIN", "bui", "ghs_share"]) for y in YEARS}
    assert "derived from GHS" in expect_exit(ca.common_features, mc, [2010, 1980], cfs)
    assert "no era Y1960" in expect_exit(ca.common_features, mc, [2010, 1960], cfs)
    c = {"grp": np.array([0, 1, 2]), "v57": np.array([1.0, 2.0, 3.0], np.float32),
         "pq5": np.array([4.0, 5.0, 6.0], np.float32)}
    assert np.allclose(ca.cell_scores(c, "pq5_unbuilt"), [1, 5, 6]) and np.allclose(ca.cell_scores(c, "mixed"),
                                                                                    [1, 2, 6])
    print("ok features: common list in the learn year's order, a GHS-derived name stops; pq5_unbuilt score")


# ---------------------------------------------------------------- end to end

def make_world(tmp: Path) -> dict:
    import geopandas as gpd
    from shapely.geometry import box
    rng = np.random.default_rng(21)
    gt = from_origin(500_000.0, 1_800_000.0, 250.0, 250.0)
    zones = np.zeros((H, W), np.int64)
    for i in range(4):
        for j in range(4):
            zones[i * 24:(i + 1) * 24, j * 24:(j + 1) * 24] = i * 4 + j + 1
    cut, dasym, data, hisdac, res = (tmp / k for k in ("cut", "dasym", "data", "hisdac", "res"))
    cutc = cut / "conus"
    nby = rng.integers(0, 3, (H, W)).astype(float) * (rng.random((H, W)) < 0.5)
    write(hisdac / "FBUY" / "NobuiltYear.tif", nby, gt, OUR, None)
    bui10 = np.where(rng.random((H, W)) < 0.45, rng.gamma(2.0, 1e4, (H, W)), 0.0)
    bui80 = np.where(rng.random((H, W)) < 0.6, bui10, 0.0)             # fewer built cells in 1980
    w = {"gt": gt, "zones": zones, "nby": nby, "bui": {1980: bui80, 2010: bui10}, "pop": {}, "mask": {},
         "v57": {}, "pq5": None, "cen": {}}
    for y in YEARS:
        write(cutc / "layers" / "BUI" / f"{y}_BUI.tif", w["bui"][y], gt, OUR, -1.0)
        zt = zones.astype(np.int32)
        path = cutc / "zones" / f"zones_{y}.tif"
        path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(path, "w", driver="GTiff", width=W, height=H, count=1, dtype="int32", crs=OUR, transform=gt,
                           nodata=0) as d:
            d.write(zt, 1)
        v = rng.gamma(1.5, 4.0 if y == 1980 else 8.0, (H, W)) * (1 + (w["bui"][y] > 0) * 3)
        v[30:36, 30:42] = -9999.0                                    # water-masked cells (two tracts)
        v = v.astype(np.float32).astype(np.float64)
        mask = v != -9999.0
        write(dasym / "conus" / "V57" / "predictions" / f"pop_{y}.tif", v, gt, OUR, -9999.0)
        vv = np.where(mask, v, 0.0)
        cen = [float(vv[zones == z].sum()) for z in range(1, 17)]
        pd.DataFrame({"zone_id": range(1, 17), "GISJOIN": GJ, "state": "Alabama", "name": [f"C{i}" for i in
                                                                                           range(1, 17)],
                      "pop": cen, "status": "ok", "area_km2": 36.0}).to_csv(cutc / "zones" / f"zones_{y}.csv",
                                                                             index=False)
        w["mask"][y], w["v57"][y], w["cen"][y] = mask, vv, cen
        pred = dasym / "conus" / "V57"
        (pred / "qa").mkdir(parents=True, exist_ok=True)
        cf = pd.DataFrame({"year": y, "zone_id": range(1, 17), "GISJOIN": GJ, "pop": cen, "n_cells": 576,
                           "n_masked": 0, **{f: rng.random(16) * (3 if y == 2010 else 1) for f in FEATS[2010]}})
        (pred / f"Y{y}" / "features").mkdir(parents=True, exist_ok=True)
        cf.to_csv(pred / f"Y{y}" / "features" / "county_features.csv", index=False)
        (res / "v57" / f"Y{y}").mkdir(parents=True, exist_ok=True)
        cf.to_csv(res / "v57" / f"Y{y}" / "county_features.csv", index=False)
    pd.concat([pd.DataFrame({"year": y, "zone_id": range(1, 17), "GISJOIN": GJ, "name": "c", "pop": w["cen"][y],
                             "n_masked": 0}) for y in YEARS]).to_csv(dasym / "conus" / "V57" / "qa" /
                                                                       "reallocation_qa.csv", index=False)
    pq = np.where(w["mask"][2010], w["v57"][2010] * rng.uniform(0.5, 1.5, (H, W)), -9999.0)
    pq[40:42, 10:20] = -9999.0                                       # pq5 without a value on mask cells
    write(dasym / "conus" / "V57PQ5" / "predictions" / "pop_2010.tif", pq, gt, OUR, -9999.0)
    w["pq5"] = np.where(w["mask"][2010] & (pq.astype(np.float32) != -9999.0), pq.astype(np.float32), 0.0)
    plural = rng.random((H, W))
    write(cutc / "layers" / "PLURAL" / "2010_PLURAL.tif", plural, gt, OUR, -1.0)
    # GHS-POP 2010 and GHS-BUILT-S 2015 total / NRES, Mollweide 100 m around the window
    cx, cy = 500_000.0 + 125 * W, 1_800_000.0 - 125 * H
    mx, my = Transformer.from_crs(OUR, "ESRI:54009", always_xy=True).transform(cx, cy)
    mt = from_origin(mx - 16_000, my + 16_000, 100.0, 100.0)
    ghs = rng.gamma(0.8, 2.0, (320, 320))
    bt = rng.gamma(1.0, 800.0, (320, 320))
    bn = bt * rng.uniform(0, 0.6, bt.shape)
    bn[100:104, 100:110] = bt[100:104, 100:110] * 1.5               # NRES above the total: residential -> 0
    write(data / "ghs" / "ghs_2010.tif", ghs, mt, "ESRI:54009", -200.0)
    write(data / "built" / "built_2015.tif", bt, mt, "ESRI:54009", -200.0)
    write(data / "nres" / "nres_2015.tif", bn, mt, "ESRI:54009", -200.0)
    # tracts: 6 x 6 cells, 16 per county
    tdir = tmp / "tracts"
    tdir.mkdir()
    for y in YEARS:
        geoms, ids, cty, pops, st = [], [], [], [], []
        k = 0
        for r0 in range(0, H, 6):
            for c0 in range(0, W, 6):
                x0, y1 = gt.c + c0 * 250, gt.f - r0 * 250
                geoms.append(box(x0, y1 - 6 * 250, x0 + 6 * 250, y1))
                ids.append(f"G01{k:07d}")
                cty.append(GJ[int(zones[r0, c0]) - 1])
                pops.append(float(rng.integers(0, 3000)))
                st.append("ok" if k % 17 else "no_pop")
                k += 1
        gpd.GeoDataFrame({"GISJOIN": ids, "county_gisjoin": cty, "pop": pops, "status": st}, geometry=geoms,
                         crs=OUR).to_file(tdir / f"tracts_{y}.gpkg", driver="GPKG")
    split = tmp / "split.csv"
    part = ["train"] * 12 + ["test"] * 4
    pd.DataFrame({"GISJOIN": GJ, "part": part, "fold": [i % 3 for i in range(12)] + [-1] * 4}).to_csv(split,
                                                                                                    index=False)
    vroot = tmp / "valid"
    tv.main(["--version", "V57", "--name", "conus", "--dasym-root", str(dasym), "--cutout-root", str(cut),
             "--tract-dir", str(tdir), "--results-root", str(vroot), "--years", *map(str, YEARS), "--map-years",
             "--state-prefix", "", "--split", str(split), "--gap-share", "0.05"])
    pd.DataFrame({"GISJOIN": GJ[:15], "county_class": (["city", "town_suburb", "rural"] * 5)}).to_csv(
        res / "classes.csv", index=False)                            # the last county without a label
    b15 = rng.uniform(50, 100, 16)
    b15[3] = 0.0
    b80 = b15 * rng.uniform(0.1, 0.9, 16)
    b80[5] = b15[5] * 1.3                                            # clipped to 1
    pd.DataFrame({"GISJOIN": GJ, "bupr_1980": b80, "bupr_2010": b15 * 0.97, "bupr_2015": b15}).to_csv(
        res / "bupr.csv", index=False)
    pd.DataFrame({"GISJOIN": [GJ[2], GJ[13]]}).to_csv(res / "excl.csv", index=False)
    (tmp / "study.yaml").write_text("name: conus\nyears: [1980, 2010]\n")
    mcfg = tmp / "model.yaml"
    mcfg.write_text(yaml.safe_dump({"version": "V57", "study_area": str(tmp / "study.yaml"), "block_rows": 16,
                                    "use_status": ["ok"], "train_status": ["ok"], "unusable": "skip",
                                    "eras": {f"Y{y}": {"years": [y], "features": FEATS[y]} for y in YEARS}}))
    cfg = {"products": {"ghs_pop": {"label": "GHS test", "path": "ghs/ghs_{YEAR}.tif", "years": [2010],
                                    "input_unit": "test", "input_unit_source": "test", "input_unit_class": "block"}},
           "city_maps": {"subpixel_m": 25},
           "missed_cells": {"year": 1980, "model_config": str(mcfg), "mask_map": "v57",
                            "maps": {"v57": "V57", "pq5": "V57PQ5"},
                            "ghs_built": {"label": "b", "path": "built/built_{YEAR}.tif", "years": [1980]},
                            "plural_layer": "PLURAL", "placedist_layer": "PLACEDIST",
                            "county_rule": {"city_urban_share": 0.5, "rural_share": 0.5}, "ks": [0.1],
                            "tile_cols": 40},
           "cap_transfer": {"learn_year": 2010, "years": [1980, 2010], "plural_years": [2010], "ghs_pop_year": 2010,
                            "built_epoch": 2015,
                            "ghs_built": {"label": "b", "path": "built/built_{YEAR}.tif", "years": [2015]},
                            "ghs_built_nres": {"label": "n", "path": "nres/nres_{YEAR}.tif", "years": [2015]},
                            "tract_errors": str(vroot / "conus" / "V57" / "tract_errors_{YEAR}.csv"),
                            "county_features": str(res / "v57" / "Y{YEAR}" / "county_features.csv"),
                            "county_class": str(res / "classes.csv"), "bupr": str(res / "bupr.csv"),
                            "bupr_ref": 2015, "split": str(split), "exclusions": str(res / "excl.csv"),
                            "eps": 1e-4, "rf": RF, "perm_repeats": 2, "methods": list(ca.METHODS),
                            "scores": list(ca.T_SCORES), "mape_min": 10}}
    cp = tmp / "grids.yaml"
    cp.write_text(yaml.safe_dump(cfg, sort_keys=False))
    w.update(cut=cut, dasym=dasym, data=data, hisdac=hisdac, res=res, tdir=tdir, vroot=vroot, cp=cp, cfg=cfg,
             plural=plural.astype(np.float32), split=split, b=(b80, b15))
    return w


def args_for(w, out: Path) -> list:
    return ["transfer", "--config", str(w["cp"]), "--data-root", str(w["data"]), "--dasym-root", str(w["dasym"]),
            "--cutout-root", str(w["cut"]), "--census-dir", str(w["res"]), "--tract-dir", str(w["tdir"]),
            "--hisdac-dir", str(w["hisdac"]), "--workers", "1", "--out-dir", str(out)]


def by_hand_groups(w, y):
    m = w["mask"][y]
    ctype = ecd.cell_types(w["bui"][y], w["nby"])
    return m, ctype


def design(w, y, m, ctype) -> np.ndarray:
    cf = pd.read_csv(w["res"] / "v57" / f"Y{y}" / "county_features.csv")
    cnt = np.array([[((w["zones"] == z) & m & (ctype == g)).sum() for g in range(3)] for z in range(1, 17)], float)
    sh = cnt / cnt.sum(axis=1, keepdims=True)
    return np.column_stack([cf[["bui", "bldg_size", "mu_ratio", "nby"]].to_numpy(float), sh]), cnt


def test_run(tmp: Path):
    from sklearn.ensemble import RandomForestRegressor
    w = make_world(tmp)
    out = tmp / "out"
    assert ca.main(args_for(w, out) + ["--check"]) == 0 and not out.exists()
    assert ca.main(args_for(w, out)) == 0
    assert sorted(p.name for p in out.iterdir()) == ["cap_model.csv", "caps.csv", "fc_summary.csv",
                                                     "group_shares.csv", "tract_mdape.png", "tract_metrics.csv",
                                                     "tract_pop.csv.gz"]
    caps = pd.read_csv(out / "caps.csv")
    zones, gt = w["zones"], w["gt"]
    # 2010 targets by hand
    m10, ct10 = by_hand_groups(w, 2010)
    ghs = ecm.to_grid(w["data"] / "ghs" / "ghs_2010.tif", gt, (H, W), OUR, 25)[0]
    bt = ecm.to_grid(w["data"] / "built" / "built_2015.tif", gt, (H, W), OUR, 25)[0]
    bn = ecm.to_grid(w["data"] / "nres" / "nres_2015.tif", gt, (H, W), OUR, 25)[0]
    bres = np.maximum(bt - bn, 0.0)
    assert ((bt - bn < 0) & m10).any()                               # the negative cells exist and are clipped
    tg = {}
    for k, a in (("P", ghs), ("B", bres)):
        s = np.array([[a[(zones == z) & m10 & (ct10 == g)].sum() for g in range(3)] for z in range(1, 17)])
        tg[k] = s / s.sum(axis=1, keepdims=True)
    c10 = caps[caps["year"] == 2010]
    for k in ("P", "B"):
        d = c10[c10["method"] == f"{k}_direct"][["share_built", "share_undated", "share_no_record"]].to_numpy()
        assert np.allclose(d, tg[k], rtol=1e-6), k
    # cap models refit by hand (all train counties) -> the 1980 shares and the 2010 TEST counties
    X10, cnt10 = design(w, 2010, m10, ct10)
    m80, ct80 = by_hand_groups(w, 1980)
    X80, cnt80 = design(w, 1980, m80, ct80)
    train = np.arange(16) < 12
    for k in ("P", "B"):
        Y = np.log(np.maximum(tg[k], 1e-4)[:, 1:] / np.maximum(tg[k], 1e-4)[:, :1])
        mods = [RandomForestRegressor(**RF, n_jobs=1).fit(X10[train], Y[train, j]) for j in range(2)]
        p80 = np.column_stack([mm.predict(X80) for mm in mods])
        p10 = np.column_stack([mm.predict(X10) for mm in mods])
        r80 = caps[(caps["year"] == 1980) & (caps["method"] == f"{k}_transfer")]
        assert np.allclose(r80[["y1", "y2"]].to_numpy(), p80, rtol=1e-6, atol=1e-9), k
        assert (r80["pred_from"] == "model_2010").all()
        assert not np.allclose(p80, p10)                             # other features -> other shares
        r10 = c10[c10["method"] == f"{k}_transfer"]
        assert np.allclose(r10[["y1", "y2"]].to_numpy()[~train], p10[~train], rtol=1e-6, atol=1e-9)
        assert list(r10["pred_from"]) == ["oof"] * 12 + ["all_train"] * 4
        e = np.exp(np.column_stack([np.zeros(16), p80])) * (cnt80 > 0)
        assert np.allclose(r80[["share_built", "share_undated", "share_no_record"]].to_numpy(),
                           e / e.sum(axis=1, keepdims=True), rtol=1e-9)
    # scaled by hand
    b80, b15 = w["b"]
    f80 = np.where(b15 > 0, np.clip(b80 / np.where(b15 > 0, b15, 1), 0, 1), 1.0)
    for y, f in ((1980, f80), (2010, np.where(b15 > 0, 0.97, 1.0))):
        cy = caps[caps["year"] == y]
        for k in ("P", "B"):
            t = cy[cy["method"] == f"{k}_transfer"][["share_built", "share_undated", "share_no_record"]].to_numpy()
            s = cy[cy["method"] == f"{k}_scaled"][["share_built", "share_undated", "share_no_record"]].to_numpy()
            assert np.allclose(cy[cy["method"] == f"{k}_scaled"]["f_c"], f)
            rem = t[:, 1] * (1 - f)
            want = np.column_stack([t[:, 0] + rem * t[:, 0] / (t[:, 0] + t[:, 2]), t[:, 1] * f,
                                    t[:, 2] + rem * t[:, 2] / (t[:, 0] + t[:, 2])])
            assert np.allclose(s, want, rtol=1e-9) and np.allclose(s.sum(axis=1), 1)
    assert set(caps[caps["year"] == 1980]["method"]) == {"v57", "P_transfer", "P_scaled", "B_transfer", "B_scaled"}
    assert set(c10["method"]) == set(ca.METHODS)
    # tracts
    tm = pd.read_csv(out / "tract_metrics.csv")
    tp = pd.read_csv(out / "tract_pop.csv.gz")
    t80 = tm[tm["year"] == 1980]
    assert set(t80["score"]) == {"v57", "v5.7"} and (t80["plural_grid"] == "no PLURAL grid").all()
    assert set(tm[tm["year"] == 2010]["score"]) == {"v5.7", *ca.T_SCORES}
    circ = tm[(tm["year"] == 2010) & tm["circular"].notna() & (tm["circular"] != "")]
    assert set(circ["method"]) == {"P_transfer", "P_scaled", "P_direct"} and t80["circular"].isna().all()
    assert {"all", "train", "test", "kept_t070", "excluded_t070", "gap", "no_gap", "dens_0_50", "city", "rural",
            "town_suburb"} <= set(tm["part"])
    import geopandas as gpd
    for y in YEARS:
        te = pd.read_csv(w["vroot"] / "conus" / "V57" / f"tract_errors_{y}.csv")
        ok = te[te["flag"] == "ok"].reset_index(drop=True)
        ty = tp[tp["year"] == y].reset_index(drop=True)
        assert list(ty["GISJOIN"]) == list(ok["GISJOIN"]) and len(ok) > 200
        fac = {GJ[z - 1]: w["cen"][y][z - 1] / w["v57"][y][zones == z].sum() for z in range(1, 17)}
        assert np.allclose(ty["v57+v57"], ok["pop_model"] * ok["zone_gisjoin"].map(fac), rtol=1e-6, atol=1e-3)
        r = tm[(tm["year"] == y) & (tm["combination"] == "P_transfer+v57") & (tm["part"] == "all")].iloc[0]
        r0 = tm[(tm["year"] == y) & (tm["combination"] == "v5.7") & (tm["part"] == "all")].iloc[0]
        assert np.isclose(r["d_mdape"], r["mdape"] - r0["mdape"])
    # one 2010 combination by hand: B_scaled shares x pq5_unbuilt score
    S = c10[c10["method"] == "B_scaled"][["share_built", "share_undated", "share_no_record"]].to_numpy()
    score = np.where(ct10 == 0, w["v57"][2010].astype(np.float32), w["pq5"]).astype(np.float64)
    alloc = np.zeros((H, W))
    for z in range(1, 17):
        for g in range(3):
            mg = (zones == z) & m10 & (ct10 == g)
            assert mg.any() and score[mg].sum() > 0
            alloc[mg] = w["cen"][2010][z - 1] * S[z - 1, g] * score[mg] / score[mg].sum()
    tracts = gpd.read_file(w["tdir"] / "tracts_2010.gpkg")
    tid = tv.tract_ids(tracts, {"shape": (H, W), "transform": gt})
    pos = {g: i + 1 for i, g in enumerate(tracts["GISJOIN"])}
    ty = tp[tp["year"] == 2010].reset_index(drop=True)
    want = np.array([alloc[tid == pos[g]].sum() for g in ty["GISJOIN"]])
    assert np.allclose(ty["B_scaled+pq5_unbuilt"], want, rtol=1e-6, atol=1e-3)
    o = ty["pop_obs"].to_numpy()
    r = tm[(tm["year"] == 2010) & (tm["combination"] == "B_scaled+pq5_unbuilt") & (tm["part"] == "all")].iloc[0]
    pos_o = o > 0
    assert np.isclose(r["mdape"], np.median(np.abs(want[pos_o] - o[pos_o]) / o[pos_o]) * 100, rtol=1e-4)
    # group shares: the cap fixes the pooled shares; the products rows of the learn year
    gs = pd.read_csv(out / "group_shares.csv")
    a = gs[(gs["year"] == 2010) & (gs["method"] == "P_direct") & (gs["county_class"] == "all")].iloc[0]
    P = np.array(w["cen"][2010])
    assert np.isclose(a["share_undated"], (P * tg["P"][:, 1]).sum() / P.sum())
    assert {"GHS-POP 2010", "GHS-BUILT-S res 2015"} <= set(gs["method"])
    cm = pd.read_csv(out / "cap_model.csv")
    assert set(cm["target"]) == {"P", "B"} and set(cm["set"]) == {"oof_train", "test"}
    feats = set(cm["feature"].dropna())
    assert feats == {"bui", "bldg_size", "mu_ratio", "nby", "cells_built", "cells_undated", "cells_no_record"}
    assert ca.ghs_derived(feats) == []
    fc = pd.read_csv(out / "fc_summary.csv")
    assert list(fc["year"]) == [1980, 2010] and np.isclose(fc["f_median"].iloc[0], np.median(f80))
    assert fc["n_clipped_1"].iloc[0] == 1 and fc["n_ref_zero"].iloc[0] == 1
    # a changed tract pop_model / a missing bupr county stops with nothing written
    te = w["vroot"] / "conus" / "V57" / "tract_errors_1980.csv"
    keep = te.read_text()
    t = pd.read_csv(te)
    i = t.index[t["flag"] == "ok"][5]
    t.loc[i, "pop_model"] *= 1.001
    t.to_csv(te, index=False)
    assert "v57 + score v57" in expect_exit(ca.main, args_for(w, tmp / "x1"))
    assert not (tmp / "x1").exists()
    te.write_text(keep)
    b = pd.read_csv(w["res"] / "bupr.csv")
    b.iloc[:-1].to_csv(w["res"] / "bupr.csv", index=False)
    assert "bupr table" in expect_exit(ca.main, args_for(w, tmp / "x2"))
    assert not (tmp / "x2").exists()
    print("ok run: targets / transfer / scaled / direct by hand, v57 = v5.7, a combination's tracts and MdAPE by hand, "
          "1980 score v57 only, checks stop")


def test_real_config():
    from external_compare import load_config
    cfg = load_config(REPO / "configs" / "external_grids.yaml")
    t = ca.tr_config(cfg)
    assert t["learn_year"] == 2010 and t["years"] == [1940, 1960, 1980, 2010] and t["plural_years"] == [1940, 1980,
                                                                                                         2010]
    assert t["eps"] == 1e-4 and t["rf"] == {"n_estimators": 500, "min_samples_leaf": 5, "max_features": 0.5,
                                           "random_state": 42}
    assert t["methods"] == list(ca.METHODS) and t["scores"] == list(ca.T_SCORES) and int(t["built_epoch"]) == 2015
    for k in ("county_class", "bupr", "split", "exclusions"):
        assert (REPO / t[k]).exists(), t[k]
    cfs = {}
    for y in t["years"]:
        for k in ("tract_errors", "county_features"):
            assert (REPO / ca.ypath(t[k], y)).exists(), (k, y)
        cfs[y] = pd.read_csv(REPO / ca.ypath(t["county_features"], y))
    mc = cfg["missed_cells"]
    feats, dropped = ca.common_features(REPO / mc["model_config"], [2010, 1940, 1960, 1980], cfs)
    assert feats == ["bui", "bldg_size", "mu_ratio", "dist_built", "res_share", "rent_share", "elev", "slope", "nby"]
    b = pd.read_csv(REPO / t["bupr"])
    for y in t["years"]:
        assert f"bupr_{y}" in b.columns
    print(f"ok real config: cap_transfer block, fixed settings, tracked inputs, common features {feats}")


if __name__ == "__main__":
    test_real_config()
    for fn in (test_scale, test_factor, test_features, test_run):
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
    print("ALL OK")
