"""Synthetic test of src/validation/strata.py (strata: PLURAL area type x cell group; v5.7's people per county stratum,
cells ordered by another model; docs/handoff/strata_request.md):

    python tests/test_strata.py      (needs the hisdac env: rasterio, geopandas, scipy, matplotlib)

  test_breaks       quantile-matched breaks by hand (cells without a SMOD class / PLURAL left out, ties), area types
                    with nodata -> none, confusion matrix
  test_swap         swap inside strata by hand: cap x score / sum, county stratum sums kept, a zero score sum keeps
                    v5.7 (counted); the selection rule: > 0.1 pp only, a tie -> the first score, no candidate -> v57
  test_configs      the four real configs = v5.7's Y2010 + one addition (CONFIG OK); mutations (a feature, a search
                    setting, the plural block, the version name, a missing layer year) are reported
  test_run          end to end on the cap-transfer test world (1980 + 2010; SMOD 2010, PLURAL 1980 / 2010, score maps
                    pq5 / ntl): breaks and strata cells by hand, score v57 everywhere = v5.7 (cells and tract file), a
                    single swap's TRAIN / TEST MdAPE by hand (people move only inside the county x type x group),
                    zero-score county strata kept, chosen = the rule on TRAIN numbers, combined by hand (county sums =
                    census), full models by hand; changing TEST tracts' observed people leaves chosen.csv unchanged;
                    a changed pop_model stops; --check writes nothing
"""
from __future__ import annotations

import math
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "validation"))
sys.path.insert(0, str(REPO / "src" / "dasymetric"))
sys.path.insert(0, str(REPO / "tests"))

import yaml  # noqa: E402
from pyproj import Transformer  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402

import degurba_boxes as db  # noqa: E402
import external_city_density as ecd  # noqa: E402
import strata as sm  # noqa: E402
import tract_validate as tv  # noqa: E402
from external_compare import load_config  # noqa: E402
from test_cap_transfer import GJ, H, W, make_world  # noqa: E402
from test_external_city_maps import write  # noqa: E402
from test_external_city_meeting import OUR  # noqa: E402
from test_missed_cells import expect_exit  # noqa: E402

CODES = {30: "uc", 23: "duc", 22: "sduc", 21: "sub", 13: "rc", 12: "ldr", 11: "vldr", 10: "water"}
SCHEME_A = {"urban": [30], "peri_urban": [21, 22, 23], "rural": [11, 12, 13]}


def test_breaks(tmp: Path):
    p = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 0.05, np.nan])
    s = np.array([0, 0, 0, 1, 1, 1, 2, 2, 2, 2, -1, 0])               # 11th: no SMOD class, 12th: no PLURAL
    b = sm.quantile_breaks(p, s)
    assert b["n"] == 10 and np.isclose(b["smod_urban"], 0.3) and np.isclose(b["smod_urban_peri"], 0.6)
    assert np.isclose(b["t1"], 0.3) and np.isclose(b["t2"], 0.6) and np.isclose(b["reached_t1"], 0.3)
    # ties: many 0 values -> share(<= t1) above the target, logged as reached
    b2 = sm.quantile_breaks(np.array([0, 0, 0, 0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]), np.array([0, 0, 1, 1, 1, 2, 2, 2, 2,
                                                                                               2]))
    assert b2["t1"] == 0 and np.isclose(b2["reached_t1"], 0.4) and np.isclose(b2["t2"], 0.5)
    t = sm.area_types(p, 0.3, 0.6)
    assert list(t) == [0, 0, 0, 1, 1, 1, 2, 2, 2, 2, 0, 3]
    cm = sm.confusion(t, s)
    assert cm.sum() == 10 and np.trace(cm) == 10                    # perfect agreement here
    assert "no break" in expect_exit(sm.quantile_breaks, p, np.where(s >= 0, 2, -1))
    print("ok breaks: quantile matching by hand, ties, types (nodata -> none), confusion")


def test_swap(tmp: Path):
    k = np.array([5, 5, 5, 7, 7, 9, 9])
    v = np.array([1.0, 2.0, 3.0, 4.0, 0.0, 2.0, 2.0])
    s = np.array([0.0, 1.0, 3.0, 1.0, 1.0, 0.0, 0.0])
    new, nz = sm.swap_cells(k, v, s)
    assert np.allclose(new, [0, 1.5, 4.5, 2, 2, 2, 2]) and nz == 1   # key 9: score sum 0 -> kept
    assert np.allclose(np.bincount(k, new), np.bincount(k, v))
    assert sm.choose({"v57": 20.0, "a": 19.9, "b": 19.95}, "v57", 0.1)[0] == "v57"     # 0.1 pp: not more than
    c, best, g = sm.choose({"v57": 20.0, "a": 19.85, "b": 19.85}, "v57", 0.1)
    assert c == "a" and best == "a" and np.isclose(g, 0.15)                             # tie -> the first
    assert sm.choose({"v57": 20.0, "a": 21.0}, "v57", 0.1)[:2] == ("v57", "a")
    assert sm.choose({"v57": 20.0}, "v57", 0.1) == ("v57", "v57", 0.0)
    print("ok swap: cap x score / sum by hand, zero score sum kept, rule > 0.1 pp, tie -> first")


def real_st() -> dict:
    return sm.st_config(load_config(REPO / "configs" / "external_grids.yaml"))


def test_configs(tmp: Path):
    import os
    old = os.getcwd()
    os.chdir(REPO)
    try:
        st = real_st()
        assert sm.check_new_configs(st) == []
        assert st["years"] == [1940, 1980, 2010] and st["calib_year"] == 2010 and st["min_gain_pp"] == 0.1
        assert list(st["scores"][2010]) == ["pq5", "ntl", "ntlv", "pq5ntl", "pq5ntlv"]
        assert list(st["scores"][1940]) == ["pq5"] == list(st["scores"][1980])
        for k, f in st["new_versions"].items():
            m = yaml.safe_load(Path(f["config"]).read_text(encoding="utf-8"))
            assert m["eras"]["Y2010"]["features"][-len(f["add"]):] == f["add"]
        muts = {
            "feature": lambda m: m["eras"]["Y2010"]["features"].remove("slope"),
            "search": lambda m: m["search"].update(n_iter=30),
            "plural": lambda m: m.__setitem__("plural", {"layer": "PLURAL", "classes": 3, "breaks": "quantile"}),
            "version": lambda m: m.__setitem__("version", "X"),
            "split": lambda m: m.__setitem__("split", "configs/other.csv"),
            "years": lambda m: m.__setitem__("years", [2000, 2010]),
        }
        for name, fn in muts.items():
            st2 = real_st()
            src = Path(st2["new_versions"]["pq5ntlv"]["config"])
            m = yaml.safe_load(src.read_text(encoding="utf-8"))
            fn(m)
            dst = tmp / f"mut_{name}.yaml"
            m["study_area"] = str(REPO / m["study_area"])
            dst.write_text(yaml.safe_dump(m, sort_keys=False))
            st2["new_versions"]["pq5ntlv"]["config"] = str(dst)
            probs = sm.check_new_configs(st2)
            assert probs and all("mut_" in p or "strata.scores" in p for p in probs), (name, probs)
        st2 = real_st()
        st2["new_versions"]["ntl"]["add"] = ["ntl", "bua"]                  # an addition the file does not have
        assert any("eras" in p for p in sm.check_new_configs(st2))
        st2 = real_st()
        st2["years"] = [1930, 2010]                                         # PLURAL has no 1930 layer
        assert any("lacks years" in p for p in sm.check_new_configs(st2))
        assert sm.main(["config"]) == 0
    finally:
        os.chdir(old)
    print("ok configs: real = v5.7 Y2010 + one addition; mutations reported")


# ---------------------------------------------------------------- end to end

def strata_world(tmp: Path) -> dict:
    w = make_world(tmp)
    rng = np.random.default_rng(7)
    gt, cut = w["gt"], w["cut"] / "conus"
    write(cut / "layers" / "PLURAL" / "1980_PLURAL.tif", rng.random((H, W)), gt, OUR, -1.0)
    pl10 = w["plural"].astype(np.float64).copy()
    pl10[0:3, 0:5] = -1.0                                            # PLURAL nodata on mask cells -> type none
    write(cut / "layers" / "PLURAL" / "2010_PLURAL.tif", pl10, gt, OUR, -1.0)
    # GHS-SMOD 2010, Mollweide 1 km around the window
    cx, cy = 500_000.0 + 125 * W, 1_800_000.0 - 125 * H
    mx, my = Transformer.from_crs(OUR, "ESRI:54009", always_xy=True).transform(cx, cy)
    codes = rng.choice([10, 11, 12, 13, 21, 22, 23, 30, -200], (40, 40),
                       p=[0.05, 0.15, 0.15, 0.1, 0.1, 0.1, 0.1, 0.2, 0.05]).astype(float)
    write(w["data"] / "smod" / "smod_2010.tif", codes, from_origin(mx - 20_000, my + 20_000, 1000.0, 1000.0),
          "ESRI:54009", -200.0)
    # score maps: pq5 1980 (random), ntl 2010 = the tracts' observed people spread over their cells (a good score),
    # 0 in county 1 (its strata keep v5.7)
    import geopandas as gpd
    tr = gpd.read_file(w["tdir"] / "tracts_2010.gpkg")
    good = np.zeros((H, W))
    for k, pop in enumerate(tr["pop"]):
        r0, c0 = (k // 16) * 6, (k % 16) * 6
        good[r0:r0 + 6, c0:c0 + 6] = pop / 36.0
    good = good * rng.uniform(0.8, 1.2, (H, W)) + 0.01
    good[w["zones"] == 1] = 0.0
    ntl = np.where(w["mask"][2010], good, -9999.0)
    write(w["dasym"] / "conus" / "V57NTL" / "predictions" / "pop_2010.tif", ntl, gt, OUR, -9999.0)
    pq80 = np.where(w["mask"][1980], w["v57"][1980] * rng.uniform(0.5, 1.5, (H, W)), -9999.0)
    write(w["dasym"] / "conus" / "V57PQ5" / "predictions" / "pop_1980.tif", pq80, gt, OUR, -9999.0)
    (tmp / "study.yaml").write_text(yaml.safe_dump({"name": "conus", "years": [1980, 2010], "layers": [
        {"name": "PLURAL", "years": [1980, 2010]}]}))
    cfg = dict(w["cfg"])
    cfg["rural_boxes"] = {"years": {2010: ["ghs_pop"]},
                          "smod": {"label": "s", "path": "smod/smod_{YEAR}.tif", "years": [2010], "codes": CODES,
                                   "scheme_a": SCHEME_A}}
    tc = cfg["cap_transfer"]
    cfg["strata"] = {"model_config": cfg["missed_cells"]["model_config"], "base": "V57", "base_label": "v57",
                     "years": [1980, 2010], "calib_year": 2010, "plural_layer": "PLURAL",
                     "scores": {1980: {"pq5": "V57PQ5"}, 2010: {"pq5": "V57PQ5", "ntl": "V57NTL"}},
                     "new_versions": {}, "plural_from": cfg["missed_cells"]["model_config"],
                     "tract_errors": tc["tract_errors"], "split": tc["split"], "exclusions": tc["exclusions"],
                     "county_class": tc["county_class"], "min_gain_pp": 0.1, "mape_min": 10}
    cp = tmp / "grids_strata.yaml"
    cp.write_text(yaml.safe_dump(cfg, sort_keys=False))
    w.update(cp=cp, cfg=cfg, pl={1980: None, 2010: pl10}, ntl=np.where(w["mask"][2010], good, 0.0),
             pq80=np.where(w["mask"][1980], pq80.astype(np.float32), 0.0))
    from rasterio import open as ropen
    with ropen(cut / "layers" / "PLURAL" / "1980_PLURAL.tif") as s:
        w["pl"][1980] = s.read(1).astype(np.float64)
    w["pl"][2010] = np.where(pl10 == -1.0, np.nan, pl10.astype(np.float32).astype(np.float64))
    return w


def args_for(w, out: Path) -> list:
    return ["run", "--config", str(w["cp"]), "--data-root", str(w["data"]), "--dasym-root", str(w["dasym"]),
            "--cutout-root", str(w["cut"]), "--census-dir", str(w["res"]), "--tract-dir", str(w["tdir"]),
            "--hisdac-dir", str(w["hisdac"]), "--workers", "1", "--out-dir", str(out)]


def tract_index(te: pd.DataFrame) -> np.ndarray:
    return te["GISJOIN"].str[3:].astype(int).to_numpy()


def tract_sums(cells: np.ndarray, ks: np.ndarray, mask: np.ndarray) -> np.ndarray:
    x = np.where(mask, cells, 0.0)
    return np.array([x[(k // 16) * 6:(k // 16) * 6 + 6, (k % 16) * 6:(k % 16) * 6 + 6].sum() for k in ks])


def test_run(tmp: Path):
    w = strata_world(tmp)
    out = tmp / "out"
    assert sm.main(args_for(w, out) + ["--check"]) == 0 and not out.exists()
    assert sm.main(args_for(w, out)) == 0
    assert sorted(p.name for p in out.iterdir()) == ["breaks.csv", "chosen.csv", "strata_cells.csv",
                                                     "strata_mdape.png", "stratum_scores.csv", "test_metrics.csv"]
    zones, gt = w["zones"], w["gt"]
    br = pd.read_csv(out / "breaks.csv")
    # breaks by hand (2010 mask cells, SMOD class per cell centre, PLURAL value)
    m10 = w["mask"][2010]
    sm_cls = sm.SMOD_TYPE[db.scheme_a(db.smod_on_cells(w["data"] / "smod" / "smod_2010.tif", gt, (H, W), OUR),
                                      SCHEME_A)]
    p10 = w["pl"][2010]
    ok = m10 & (sm_cls >= 0) & np.isfinite(p10)
    ps = np.sort(p10[ok])
    su, sup = (sm_cls[ok] == 0).mean(), (sm_cls[ok] <= 1).mean()
    t1, t2 = ps[math.ceil(su * ok.sum()) - 1], ps[math.ceil(sup * ok.sum()) - 1]
    b = br[br["section"] == "break"].set_index("name")
    assert np.isclose(b.loc["t1", "value"], t1) and np.isclose(b.loc["t2", "value"], t2), (b, t1, t2)
    assert np.isclose(b.loc["t1", "share"], su) and int(b.loc["t1", "cells"]) == ok.sum()
    ty = {}
    for y in (1980, 2010):
        p = w["pl"][y]
        t = np.full((H, W), 3)
        t[np.isfinite(p) & (p <= t1)] = 0
        t[np.isfinite(p) & (p > t1) & (p <= t2)] = 1
        t[np.isfinite(p) & (p > t2)] = 2
        ty[y] = t
    pt = ty[2010]
    cmh = np.array([[((pt == i) & (sm_cls == j) & m10).sum() for j in range(3)] for i in range(3)])
    conf = br[br["section"] == "confusion"]
    assert conf["cells"].sum() == cmh.sum() and int(conf[(conf["plural_class"] == "urban") &
                                                         (conf["smod_class"] == "rural")]["cells"].iloc[0]) == cmh[0, 2]
    assert np.isclose(br[br["section"] == "agreement"]["value"].iloc[0], np.trace(cmh) / cmh.sum())
    # strata cells by hand
    scl = pd.read_csv(out / "strata_cells.csv")
    for y in (1980, 2010):
        g = ecd.cell_types(w["bui"][y], w["nby"])
        m = w["mask"][y]
        for _, r in scl[scl["year"] == y].iterrows():
            ti, gi = sm.TYPE_NAMES.index(r["area_type"]), sm.GROUPS.index(r["group"])
            sel = m & (ty[y] == ti) & (g == gi)
            assert r["cells"] == sel.sum() and np.isclose(r["people_v57"], w["v57"][y][sel].sum(), rtol=1e-6)
    assert scl[(scl["year"] == 2010) & (scl["area_type"] == "none")]["cells"].sum() == (m10[0:3, 0:5]).sum()
    # a single swap by hand: 2010, urban built, score ntl
    te = pd.read_csv(w["vroot"] / "conus" / "V57" / "tract_errors_2010.csv")
    te = te[te["flag"] == "ok"].reset_index(drop=True)
    ks = tract_index(te)
    split = pd.read_csv(w["split"])
    part = te["zone_gisjoin"].map(dict(zip(split["GISJOIN"], split["part"]))).to_numpy()
    trn, tst = part == "train", part == "test"
    obs = te["pop_obs"].to_numpy(float)
    g10 = ecd.cell_types(w["bui"][2010], w["nby"])
    v = w["v57"][2010]
    base_ts = tract_sums(v, ks, m10)
    assert np.allclose(base_ts, te["pop_model"], rtol=1e-6)

    def swap(cells, score, ti, gi):
        out_ = cells.copy()
        for z in range(1, 17):
            sel = m10 & (zones == z) & (pt == ti) & (g10 == gi)
            cap, ss = v[sel].sum(), score[sel].sum()
            if ss > 0:
                out_[sel] = cap * score[sel] / ss
        return out_

    def md(o, e):
        return tv.metrics(o, e, np.ones(len(o)))["mdape"]

    one = swap(v, w["ntl"], 0, 0)
    assert np.isclose(one[zones == 1].sum(), v[zones == 1].sum())   # people stay in the county ...
    for z in range(1, 17):
        for ti in range(4):
            for gi in range(3):
                sel = m10 & (zones == z) & (pt == ti) & (g10 == gi)
                assert np.isclose(one[sel].sum(), v[sel].sum())        # ... and in each county x type x group
    assert np.allclose(one[(pt != 0) | (g10 != 0)], v[(pt != 0) | (g10 != 0)])   # other strata untouched
    ts = tract_sums(one, ks, m10)
    ss_ = pd.read_csv(out / "stratum_scores.csv")
    r = ss_[(ss_["year"] == 2010) & (ss_["area_type"] == "urban") & (ss_["group"] == "built") &
            (ss_["score"] == "ntl")].iloc[0]
    assert np.isclose(r["train_mdape"], md(obs[trn], ts[trn]), rtol=1e-6)
    assert np.isclose(r["test_d_mdape"], md(obs[tst], ts[tst]) - md(obs[tst], base_ts[tst]), rtol=1e-6, atol=1e-6)
    assert (ss_[(ss_["year"] == 2010) & (ss_["score"] == "ntl") & (ss_["cells"] > 0)]["county_strata_kept_v57"] >= 1
            ).all()                                                  # county 1: ntl = 0 -> kept
    assert set(ss_[ss_["year"] == 1980]["score"]) == {"v57", "pq5"}
    assert set(ss_[ss_["year"] == 2010]["score"]) == {"v57", "pq5", "ntl"}
    # chosen = the rule on the TRAIN numbers
    ch = pd.read_csv(out / "chosen.csv")
    assert len(ch) == 18
    for _, c in ch.iterrows():
        e = ss_[(ss_["year"] == c["year"]) & (ss_["area_type"] == c["area_type"]) & (ss_["group"] == c["group"])]
        d = dict(zip(e["score"], e["train_mdape"]))
        assert sm.choose(d, "v57", 0.1)[0] == c["chosen"] == e[e["chosen"]]["score"].iloc[0]
    assert (ch[ch["year"] == 2010]["chosen"] == "ntl").sum() >= 3      # the good score is chosen somewhere
    # combined by hand
    comb = v.copy()
    for _, c in ch[(ch["year"] == 2010) & (ch["chosen"] != "v57")].iterrows():
        ti, gi = sm.AREA_TYPES.index(c["area_type"]), sm.GROUPS.index(c["group"])
        sc = w["ntl"] if c["chosen"] == "ntl" else w["pq5"]
        comb = swap(comb, sc, ti, gi)
    assert np.allclose([comb[(zones == z) & m10].sum() for z in range(1, 17)], w["cen"][2010], rtol=1e-6)
    tm = pd.read_csv(out / "test_metrics.csv")
    a = tm[(tm["year"] == 2010) & (tm["part"] == "all")].set_index("method")
    assert set(a.index) == {"v5.7", "combined", "full_pq5", "full_ntl"}
    assert np.isclose(a.loc["combined", "mdape"], md(obs[tst], tract_sums(comb, ks, m10)[tst]), rtol=1e-6)
    assert np.isclose(a.loc["full_ntl", "mdape"], md(obs[tst], tract_sums(w["ntl"], ks, m10)[tst]), rtol=1e-6)
    assert np.isclose(a.loc["v5.7", "mdape"], md(obs[tst], obs[tst] * 0 + te["pop_model"].to_numpy()[tst]))
    assert a.loc["v5.7", "n"] == tst.sum() and np.isclose(a.loc["combined", "d_mdape"],
                                                         a.loc["combined", "mdape"] - a.loc["v5.7", "mdape"])
    assert {"all", "dens_0_50", "kept_t070", "excluded_t070", "gap", "no_gap", "city", "rural", "type_urban",
            "type_rural"} <= set(tm["part"]) and not {"train", "test"} & set(tm["part"])
    assert set(tm[tm["year"] == 1980]["method"]) == {"v5.7", "combined", "full_pq5"}
    # TEST tracts' observed people changed -> the same choice
    vroot2 = tmp / "valid2"
    shutil.copytree(w["vroot"], vroot2)
    for y in (1980, 2010):
        f = vroot2 / "conus" / "V57" / f"tract_errors_{y}.csv"
        t = pd.read_csv(f)
        tp = t["zone_gisjoin"].map(dict(zip(split["GISJOIN"], split["part"])))
        t.loc[tp == "test", "pop_obs"] = t.loc[tp == "test", "pop_obs"] * 3 + 7
        t.to_csv(f, index=False)
    cfg2 = dict(w["cfg"])
    cfg2["strata"] = {**w["cfg"]["strata"], "tract_errors": str(vroot2 / "conus" / "V57" / "tract_errors_{YEAR}.csv")}
    cp2 = tmp / "grids2.yaml"
    cp2.write_text(yaml.safe_dump(cfg2, sort_keys=False))
    out2 = tmp / "out2"
    assert sm.main([*args_for(w, out2)[:2], str(cp2), *args_for(w, out2)[3:]]) == 0
    assert pd.read_csv(out2 / "chosen.csv").equals(ch)
    assert not np.allclose(pd.read_csv(out2 / "test_metrics.csv")["mdape"], tm["mdape"], equal_nan=True)
    # a changed pop_model stops, nothing written
    f = vroot2 / "conus" / "V57" / "tract_errors_2010.csv"
    t = pd.read_csv(f)
    t.loc[t["flag"] == "ok", "pop_model"] = t.loc[t["flag"] == "ok", "pop_model"] + 50
    t.to_csv(f, index=False)
    out3 = tmp / "out3"
    assert "v5.7 file" in expect_exit(sm.main, [*args_for(w, out3)[:2], str(cp2), *args_for(w, out3)[3:]])
    assert not out3.exists()
    print("ok run: breaks / strata by hand, v57 = v5.7, a swap by hand inside its strata, chosen by the TRAIN rule, "
          "combined / full by hand, TEST changes leave the choice, a changed pop_model stops")


def main():
    tests = [test_breaks, test_swap, test_configs, test_run]
    only = sys.argv[1:]
    for t in tests:
        if only and t.__name__ not in only:
            continue
        with tempfile.TemporaryDirectory() as d:
            t(Path(d))
    print("ALL OK")


if __name__ == "__main__":
    main()
