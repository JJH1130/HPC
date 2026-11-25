"""Synthetic test of src/validation/cap_allocation.py (cap allocation 1980; docs/handoff/cap_allocation_1980_request.md):

    python tests/test_cap_allocation.py      (needs the hisdac env: rasterio, geopandas, scikit-learn, scipy, matplotlib)

  test_allocate     cell = P_c x cap x score / group score sum by hand; county sums kept; a group without cells ->
                    the other caps scaled up (counted); scores summing to 0 -> even (counted); NaN cap rows of empty
                    counties; scores (mixed, plural_inv with nodata)
  test_shares       log ratios with eps, softmax back = the shares (sum 1), a group without cells -> 0
  test_oof          out of fold: changing a county's own target (or a TEST county's) leaves its own prediction
                    unchanged, changing another fold's target changes it; TEST rows = the all-train model; importance
  test_design       cap model features = county features + plural + cell shares; no GHS-derived column (no
                    DEGURBA county class: built on the county's own GHS-POP, no GHS before 1975); one stops the run
  test_group_capture group capture = an independent loop (test_missed_cells.capture_by_hand), even = k, GHS >= others
  test_run          end to end on the missed-cells test world (missed_cells and tract_validate run first): county table
                    = county_missed_1980.csv, cap v57 = its v57 shares, cap v57 + score v57 = v5.7 (cells and the
                    tract_errors file), a combination's tract sums and metrics by hand, caps / shares / capture files;
                    a changed missed-table number or tract pop_model stops with nothing written; --check
  test_real_config  the cap_allocation block of configs/external_grids.yaml
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

import cap_allocation as ca  # noqa: E402
import external_city_density as ecd  # noqa: E402
import external_city_maps as ecm  # noqa: E402
import missed_cells as mc  # noqa: E402
import tract_validate as tv  # noqa: E402
from test_external_city_meeting import OUR  # noqa: E402
from test_missed_cells import add_missed_inputs, capture_by_hand, deg_world, expect_exit  # noqa: E402


def test_allocate(tmp: Path):
    ci = np.array([0, 0, 0, 0, 1, 1, 1, 2])
    grp = np.array([0, 1, 2, 2, 0, 0, 2, 2])
    P = np.array([100.0, 50.0, 7.0, 0.0])                      # county 3: no cells, no people
    S = np.array([[0.5, 0.3, 0.2], [0.6, 0.3, 0.1], [0.2, 0.2, 0.6], [np.nan] * 3])
    sc = np.array([2.0, 5.0, 1.0, 3.0, 0.0, 0.0, 4.0, 9.0])
    cells, info = ca.allocate(ci, grp, P, S, sc, 4)
    # county 0: built 50, undated 30, no_record 20 split 1 : 3; county 1: undated cap 0.3 has no cells -> 0.6 / 0.7
    # and 0.1 / 0.7, built scores 0 -> even; county 2: only no_record -> all 7
    want = [50, 30, 5, 15, 50 * 0.6 / 0.7 / 2, 50 * 0.6 / 0.7 / 2, 50 * 0.1 / 0.7, 7]
    assert np.allclose(cells, want), cells
    assert info == {"counties_renormalized": 2, "groups_even_zero_score": 1, "counties_even_zero_score": 1}
    assert np.allclose(np.bincount(ci, weights=cells, minlength=4), P)
    ca.check_county_sums(ci, cells, P, 4, "t")
    assert "county sums" in expect_exit(ca.check_county_sums, ci, cells * 1.001, P, 4, "t")
    c = {"grp": np.array([0, 1, 2]), "v57": np.array([1.0, 2.0, 3.0], np.float32),
         "pq5": np.array([4.0, 5.0, 6.0], np.float32), "plural": np.array([0.2, 0.7, np.nan], np.float32)}
    assert np.allclose(ca.cell_scores(c, "mixed"), [1, 2, 6])
    assert np.allclose(ca.cell_scores(c, "plural_inv"), [1, 1 - np.float32(0.7), 0])
    assert np.allclose(ca.cell_scores(c, "even"), 1)
    print("ok allocate: cap x score share by hand, county sums kept, empty group rescaled, zero scores even")


def test_shares(tmp: Path):
    s = np.array([[0.5, 0.3, 0.2], [0.2, 0.0, 0.8], [0.0, 0.4, 0.6]])
    y = ca.log_ratios(s, 1e-4)
    assert np.allclose(y[0], [np.log(0.6), np.log(0.4)])
    assert np.isclose(y[1, 0], np.log(1e-4 / 0.2)) and np.isclose(y[2, 1], np.log(0.6 / 1e-4))
    back = ca.softmax_shares(y, np.ones((3, 3), bool))
    assert np.allclose(back.sum(1), 1) and np.allclose(back[0], s[0])
    has = np.array([[True, True, False], [True, True, True], [False, False, False]])
    b2 = ca.softmax_shares(y, has)
    assert np.allclose(b2[0], [0.625, 0.375, 0]) and np.isnan(b2[2]).all()
    assert np.allclose(ca.softmax_shares(np.array([[800.0, -800.0]]), np.ones((1, 3), bool)).sum(), 1)
    print("ok shares: log ratios with eps, softmax back = shares, sum 1, a group without cells -> 0")


def test_oof(tmp: Path):
    rng = np.random.default_rng(4)
    n = 70
    X = rng.random((n, 4))
    Y = np.column_stack([X[:, 0] * 3 + rng.normal(0, 0.1, n), X[:, 1] - X[:, 2]])
    fold = np.r_[np.repeat(np.arange(5), 12), np.full(10, -1)]
    fit = np.ones(n, bool)
    fit[3] = False                                         # a train county without a target
    rf = {"n_estimators": 30, "min_samples_leaf": 2, "max_features": 0.5, "random_state": 42}
    p0, how, imp = ca.oof_predict(X, Y, fold, fit, rf, 1, perm_repeats=3)
    assert (how[:60] == "oof").all() and (how[60:] == "all_train").all()
    assert imp.shape == (2, 4) and imp[0, 0] > imp[0, 3]   # feature 0 drives y1
    for i in (0, 25, 65):                                  # own target changed: own prediction unchanged
        Y2 = Y.copy()
        Y2[i] += 50.0
        p1, _, _ = ca.oof_predict(X, Y2, fold, fit, rf, 1)
        assert np.allclose(p1[i], p0[i]), i
        other = (fold != fold[i]) & (fold >= 0) if fold[i] >= 0 else np.zeros(n, bool)
        if fold[i] >= 0:
            assert not np.allclose(p1[other], p0[other])   # the other folds saw it
    Y3 = Y.copy()
    Y3[13] += 50.0                                         # fold 1 changed -> fold 0 and TEST predictions move
    p3, _, _ = ca.oof_predict(X, Y3, fold, fit, rf, 1)
    assert not np.allclose(p3[:12], p0[:12]) and not np.allclose(p3[60:], p0[60:])
    assert np.allclose(p3[12:24], p0[12:24])               # fold 1 itself unchanged
    print("ok oof: own target never seen (train and TEST), other folds see it, TEST from all train, importance")


def test_design(tmp: Path):
    ct = pd.DataFrame({"GISJOIN": ["A", "B"], "county_class": ["city", "rural"]})
    cf = pd.DataFrame({"GISJOIN": ["B", "A"], "bui": [2.0, 1.0], "nby": [0.5, 0.1], "pop": [9.0, 8.0]})
    pf = pd.DataFrame({"GISJOIN": ["A", "B"], "plural": [0.3, 0.7]})
    cnt = np.array([[2, 1, 1], [0, 0, 5]])
    X = ca.county_design(ct, cf, pf, ["bui", "nby"], cnt)
    assert list(X.columns) == ["bui", "nby", "plural", "cells_built", "cells_undated", "cells_no_record"]
    assert X["bui"].tolist() == [1.0, 2.0] and np.allclose(X.iloc[0, 3:], [0.5, 0.25, 0.25])
    assert ca.ghs_derived(X.columns) == []                  # no GHS-derived feature (no county class)
    assert ca.ghs_derived(["bui", "county_class", "class_city", "ghs_share", "smod_30", "gap"]) == [
        "county_class", "class_city", "ghs_share", "smod_30", "gap"]
    assert "derived from GHS" in expect_exit(ca.county_design, ct, cf.assign(county_class=1), pf,
                                             ["bui", "county_class"], cnt)
    print("ok design: features = county features + plural + cell shares; no GHS-derived column, one stops the run")


def test_group_capture(tmp: Path):
    rng = np.random.default_rng(5)
    m = 900
    c = {"ci": rng.integers(0, 4, m).astype(np.int32), "grp": rng.integers(0, 3, m).astype(np.int8),
         "v57": rng.random(m).astype(np.float32), "pq5": np.round(rng.random(m), 1).astype(np.float32),
         "plural": rng.random(m).astype(np.float32), "ghs": rng.gamma(0.5, 10, m),
         "nobuilt": rng.integers(0, 3, m).astype(np.float32)}
    c["plural"][:20] = np.nan
    ct = pd.DataFrame({"county_class": ["city", "rural", "rural", "town_suburb"]})
    t = ca.group_capture(c, ct, [0.05, 0.2])
    for g, gi in (("undated", 1), ("no_record", 2)):
        sel = c["grp"] == gi
        G = c["ghs"][sel].sum()
        for score, s in (("pq5", c["pq5"]), ("plural_inv", 1 - c["plural"].astype(float)), ("nobuilt", c["nobuilt"])):
            if score == "nobuilt" and g == "no_record":
                assert t[(t["group"] == g) & (t["score"] == "nobuilt")].empty
                continue
            for k in (0.05, 0.2):
                r = t[(t["group"] == g) & (t["subset"] == "all") & (t["score"] == score) & (t["k"] == k)].iloc[0]
                assert np.isclose(r["value"], capture_by_hand(c["ci"][sel], s[sel], c["ghs"][sel], k) / G)
        e = t[(t["group"] == g) & (t["score"] == "even")]
        assert np.allclose(e["value"], e["k"])
    print("ok group capture: = an independent loop, even = k, GHS upper bound checked")


# ---------------------------------------------------------------- end to end

def y_feats() -> list:
    return ["bui", "bldg_size", "mu_ratio", "dist_built", "res_share", "rent_share", "elev", "slope", "nby"]


def add_cap_inputs(w: dict, x: dict, tmp: Path) -> dict:
    """Tracts, the v5.7 tract validation (tract_validate.py), split, county features, exclusions, config block."""
    import geopandas as gpd
    from shapely.geometry import box
    gt = w["gt"]
    rng = np.random.default_rng(11)
    geoms, ids, cty, pops = [], [], [], []
    k = 0
    for r0 in range(8, 240, 24):
        for c0 in range(0, 240, 20):
            x0, y1 = gt.c + c0 * 250, gt.f - r0 * 250
            geoms.append(box(x0, y1 - 24 * 250, x0 + 20 * 250, y1))
            ids.append(f"G01{k:07d}")
            cty.append("G0100010")
            pops.append(float(rng.integers(0, 3000)))
            k += 1
    tdir = tmp / "tracts"
    tdir.mkdir()
    gpd.GeoDataFrame({"GISJOIN": ids, "county_gisjoin": cty, "pop": pops, "status": "ok"}, geometry=geoms,
                     crs=OUR).to_file(tdir / "tracts_1980.gpkg", driver="GPKG")
    pred = w["dasym"] / "conus" / "V57"
    (pred / "qa").mkdir(parents=True, exist_ok=True)
    gj = ["G0100010", "G0100030", "G0100050"]
    pd.DataFrame({"year": 1980, "zone_id": [1, 2, 3], "GISJOIN": gj, "name": ["A", "B", "C"], "pop": x["pops"][:3],
                  "n_masked": 0}).to_csv(pred / "qa" / "reallocation_qa.csv", index=False)
    split = tmp / "split.csv"
    pd.DataFrame({"GISJOIN": gj, "fips": ["01001", "01003", "01005"], "state": "Alabama", "name": ["A", "B", "C"],
                  "part": ["train", "train", "test"], "fold": [0, 1, -1]}).to_csv(split, index=False)
    feats = y_feats()
    cf = pd.DataFrame({"year": 1980, "GISJOIN": gj, **{f: rng.random(3) for f in feats}, "pop": x["pops"][:3],
                       "n_cells": 1000, "n_masked": 0})
    (pred / "Y1980" / "features").mkdir(parents=True, exist_ok=True)
    cf.assign(bui=[5.0, 0.01, 4.0]).to_csv(pred / "Y1980" / "features" / "county_features.csv", index=False)
    res = tmp / "res"
    (res / "v57").mkdir(parents=True)
    cf.to_csv(res / "v57" / "county_features.csv", index=False)
    cf.assign(plural=rng.random(3)).to_csv(res / "plc_county_features.csv", index=False)
    pd.DataFrame({"GISJOIN": ["G0100030"]}).to_csv(res / "excl.csv", index=False)
    vroot = tmp / "valid"
    tv.main(["--version", "V57", "--name", "conus", "--dasym-root", str(w["dasym"]), "--cutout-root", str(w["cut"]),
             "--tract-dir", str(tdir), "--results-root", str(vroot), "--years", "1980", "--map-years",
             "--state-prefix", "", "--split", str(split), "--gap-share", "0.05"])
    te = vroot / "conus" / "V57" / "tract_errors_1980.csv"
    cfg = w["cfg"]
    cfg["cap_allocation"] = {"missed_table": str(tmp / "missed" / "county_missed_1980.csv"), "tract_errors": str(te),
                             "county_features": str(res / "v57" / "county_features.csv"),
                             "plural_features": str(res / "plc_county_features.csv"), "split": str(split),
                             "exclusions": str(res / "excl.csv"), "features": feats, "eps": 1e-4,
                             "rf": {"n_estimators": 20, "min_samples_leaf": 5, "max_features": 0.5,
                                    "random_state": 42},
                             "perm_repeats": 2, "caps": list(ca.CAPS), "scores": list(ca.SCORES),
                             "ks": [0.05, 0.1, 0.2], "mape_min": 10}
    w["cp"].write_text(yaml.safe_dump(cfg, sort_keys=False))
    return {"tdir": tdir, "te": te, "split": split}


def test_run(tmp: Path):
    w = deg_world(tmp)
    x = add_missed_inputs(w, tmp)
    common = ["run", "--config", str(w["cp"]), "--data-root", str(w["data"]), "--dasym-root", str(w["dasym"]),
              "--cutout-root", str(w["cut"]), "--census-dir", str(x["cen"]), "--box-check",
              str(w["deg"] / "cell_type_shares.csv"), "--workers", "1"] + w["hd"]
    assert mc.main(common + ["--out-dir", str(tmp / "missed")]) == 0
    y = add_cap_inputs(w, x, tmp)
    base = common + ["--tract-dir", str(y["tdir"])]
    out = tmp / "cap"
    assert ca.main(base + ["--out-dir", str(out), "--check"]) == 0 and not out.exists()
    assert ca.main(base + ["--out-dir", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["cap_model_1980.csv", "caps_1980.csv", "group_capture_1980.csv",
                                                     "group_shares_1980.csv", "tract_mdape_1980.png",
                                                     "tract_metrics_1980.csv", "tract_pop_1980.csv.gz"]
    caps = pd.read_csv(out / "caps_1980.csv")
    miss = pd.read_csv(tmp / "missed" / "county_missed_1980.csv")
    v = caps[caps["cap"] == "v57"].reset_index(drop=True)
    for g in ("undated", "no_record"):
        assert np.allclose(v[f"share_{g}"], miss[f"{g}_share_v57"], rtol=1e-12)
    gh = caps[caps["cap"] == "ghs"].reset_index(drop=True)
    assert np.allclose(gh["share_undated"], miss["undated_share_ghs"], rtol=1e-12)
    for cap in ca.CAPS:
        s = caps[caps["cap"] == cap][["share_built", "share_undated", "share_no_record"]].to_numpy()
        assert np.allclose(s.sum(1), 1)
    mo = caps[caps["cap"] == "model"]
    assert list(mo["pred_from"]) == ["oof", "oof", "all_train"]
    # by hand on the whole window
    gt, H, W = w["gt"], 240, 240
    zones, mask, v57 = x["zones"], x["mask"], x["v57"]
    ghs = ecm.to_grid(w["data"] / "ghs" / "ghs_1980.tif", gt, (H, W), OUR, 25)[0]
    with rasterio.open(w["cut"] / "conus" / "layers" / "BUI" / "1980_BUI.tif") as src:
        bui = src.read(1).astype(float)
    ctype = ecd.cell_types(bui, w["nby"])
    import geopandas as gpd
    tracts = gpd.read_file(y["tdir"] / "tracts_1980.gpkg")
    tid = tv.tract_ids(tracts, {"shape": (H, W), "transform": gt})
    te = pd.read_csv(y["te"])
    ok = te[te["flag"] == "ok"].reset_index(drop=True)
    pos = {g: i + 1 for i, g in enumerate(tracts["GISJOIN"])}
    tp = pd.read_csv(out / "tract_pop_1980.csv.gz")
    assert list(tp["GISJOIN"]) == list(ok["GISJOIN"]) and len(ok) > 20
    # ghs cap + even score: each cell = P x GHS group share / cells of the group
    alloc = np.zeros((H, W))
    fac = {}
    for i, z in enumerate((1, 2, 3)):
        m = mask & (zones == z)
        fac[miss["GISJOIN"].iloc[i]] = x["pops"][i] / v57[m].sum()
        for g in range(3):
            mg = m & (ctype == g)
            if mg.any():
                alloc[mg] = x["pops"][i] * ghs[mg].sum() / ghs[m].sum() / mg.sum()
    want = np.array([alloc[tid == pos[g]].sum() for g in ok["GISJOIN"]])
    assert np.allclose(tp["ghs+even"], want, rtol=1e-6, atol=1e-3)
    want57 = ok["pop_model"].to_numpy() * ok["zone_gisjoin"].map(fac).to_numpy()
    assert np.allclose(tp["v57+v57"], want57, rtol=1e-6, atol=1e-3)
    assert np.allclose(tp["v5.7"], ok["pop_model"], atol=1e-3)
    # metrics of one combination and part by hand
    tm = pd.read_csv(out / "tract_metrics_1980.csv")
    cls = dict(zip(miss["GISJOIN"], miss["county_class"]))
    for part, sel in (("all", np.ones(len(ok), bool)), ("excluded_t070", (ok["zone_gisjoin"] == "G0100030").to_numpy()),
                      ("test", (ok["part"] == "test").to_numpy()),
                      (miss["county_class"].iloc[0], (ok["zone_gisjoin"].map(cls) == miss["county_class"].iloc[0])
                       .to_numpy())):
        r = tm[(tm["combination"] == "ghs+even") & (tm["part"] == part)].iloc[0]
        o, e = ok["pop_obs"].to_numpy()[sel], tp["ghs+even"].to_numpy()[sel]
        assert r["n"] == sel.sum()
        if sel.sum():
            pos_o = o > 0
            assert np.isclose(r["mdape"], np.median(np.abs(e[pos_o] - o[pos_o]) / o[pos_o]) * 100, rtol=1e-4)
            keep = o >= 10
            assert np.isclose(r["mape"], np.mean(np.abs(e[keep] - o[keep]) / o[keep]) * 100, rtol=1e-4)
            r0 = tm[(tm["combination"] == "v5.7") & (tm["part"] == part)].iloc[0]
            assert np.isclose(r["d_mdape"], r["mdape"] - r0["mdape"])
    assert set(tm["combination"]) == {"v5.7", *(f"{c}+{s}" for c in ca.CAPS for s in ca.SCORES)}
    assert {"all", "train", "test", "kept_t070", "excluded_t070", "gap", "no_gap", "dens_0_50", "city", "rural",
            "town_suburb"} <= set(tm["part"])
    # group shares: the cap fixes the pooled shares whatever the score
    gs = pd.read_csv(out / "group_shares_1980.csv")
    a = gs[(gs["county_class"] == "all") & (gs["cap"] == "ghs")]
    P = np.array(x["pops"][:3])
    assert len(a) == 5 and np.allclose(a["share_undated"], (P * miss["undated_share_ghs"]).sum() / P.sum())
    g0 = gs[(gs["county_class"] == "all") & (gs["combination"] == "GHS-POP")].iloc[0]
    assert np.isclose(g0["share_undated"], (miss["pop_ghs"] * miss["undated_share_ghs"]).sum() / miss["pop_ghs"].sum())
    cm = pd.read_csv(out / "cap_model_1980.csv")
    assert {"model", "model_noplural", "v57"} == set(cm["variant"])
    used_feats = set(cm[cm["variant"] == "model"]["feature"].dropna())
    assert used_feats == {*y_feats(), "plural", "cells_built", "cells_undated", "cells_no_record"}
    assert ca.ghs_derived(used_feats) == []                 # no GHS-derived feature (county class not a feature)
    assert used_feats - set(cm[cm["variant"] == "model_noplural"]["feature"].dropna()) == {"plural"}
    gc = pd.read_csv(out / "group_capture_1980.csv")
    assert set(gc["group"]) == {"undated", "no_record"}
    # a changed missed-table number / tract pop_model stops with nothing written
    bad = tmp / "missed_bad.csv"
    t = miss.copy()
    t.loc[1, "undated_share_v57"] += 1e-6
    t.to_csv(bad, index=False)
    cfg = yaml.safe_load(w["cp"].read_text())
    keep = dict(cfg["cap_allocation"])
    cfg["cap_allocation"]["missed_table"] = str(bad)
    w["cp"].write_text(yaml.safe_dump(cfg, sort_keys=False))
    assert "undated_share_v57" in expect_exit(ca.main, base + ["--out-dir", str(tmp / "x1")])
    assert not (tmp / "x1").exists()
    te2 = te.copy()
    i = te2.index[te2["flag"] == "ok"][3]
    te2.loc[i, "pop_model"] *= 1.001
    te2.to_csv(tmp / "te_bad.csv", index=False)
    cfg["cap_allocation"] = {**keep, "tract_errors": str(tmp / "te_bad.csv")}
    w["cp"].write_text(yaml.safe_dump(cfg, sort_keys=False))
    assert "cap v57 + score v57" in expect_exit(ca.main, base + ["--out-dir", str(tmp / "x2")])
    assert not (tmp / "x2").exists()
    print("ok run: county table = missed table, cap v57 + v57 = v5.7, a combination's tracts / metrics by hand, "
          "checks stop")


def test_real_config():
    from external_compare import load_config
    cfg = load_config(REPO / "configs" / "external_grids.yaml")
    c = ca.ca_config(cfg)
    assert c["eps"] == 1e-4 and c["rf"] == {"n_estimators": 500, "min_samples_leaf": 5, "max_features": 0.5,
                                           "random_state": 42}
    assert c["caps"] == list(ca.CAPS) and c["scores"] == list(ca.SCORES) and c["ks"] == [0.05, 0.1, 0.2]
    for k in ("missed_table", "tract_errors", "county_features", "plural_features", "split", "exclusions"):
        assert (REPO / c[k]).exists(), c[k]
    cf = pd.read_csv(REPO / c["county_features"])
    assert ca.ghs_derived(c["features"]) == []
    assert set(c["features"]) <= set(cf.columns) and "plural" in pd.read_csv(REPO / c["plural_features"]).columns
    print("ok real config: cap_allocation block, fixed settings, tracked inputs exist")


if __name__ == "__main__":
    test_real_config()
    for fn in (test_allocate, test_shares, test_oof, test_design, test_group_capture, test_run):
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
    print("ALL OK")
