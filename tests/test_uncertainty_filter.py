"""Synthetic test of the uncertainty filter (docs/conus_plan.md "Uncertainty filter"), runnable without the cluster:

    python tests/test_uncertainty_filter.py      (needs the hisdac env: numpy, pandas, rasterio, matplotlib)

src/grid/uncertainty_filter.py: 8 counties on a small zone grid with a BUI 2015 raster; checks against brute force:
  - BUI 2015 county sums, records per person, BUI per dated record, the two fixed rules (5 % of the median), a county
    without BUPR_2015 (no area value) and one without pop
  - excluded sets per threshold (ratio_A_nby >= t or a fixed rule), reasons, nested sets, summary counts, strips == one
src/validation/filter_compare.py: a results tree of v5.4 + three filtered versions, 2 years:
  - (a) common TEST = TEST counties not excluded at the strictest t; (b) imputed TEST = TEST counties excluded at the
    loosest t (v5.4 from test_predictions, filtered models from excluded_predictions); own excluded sets
  - MdAPE / MAPE / R2 = by hand; tract parts kept / excluded / gap; areal weighting row
  - the selection rule: lowest mean of (a) and (b), within 1 pp the one keeping more counties
  - an excluded county in a filtered model's TEST predictions stops the run
(The train / predict side, exclude_counties, is tested in tests/test_conus_dasymetric.py, test_exclude_counties.)
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from affine import Affine

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src" / "grid"), str(REPO / "src" / "validation")]
import filter_compare as fc  # noqa: E402
import uncertainty_filter as uf  # noqa: E402

CRS = "EPSG:5070"
T = Affine(250, 0, 100000, 0, -250, 2000000)


def write(path: Path, arr):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1, dtype=arr.dtype,
                       crs=CRS, transform=T) as dst:
        dst.write(arr, 1)


def test_filter_sets():
    tmp = Path(tempfile.mkdtemp())
    try:
        n = 8
        z = np.zeros((4, 2 * n + 2), "uint16")
        for k in range(n):
            z[1:3, 1 + 2 * k:3 + 2 * k] = k + 1
        write(tmp / "cut" / "zones" / "zones_2010.tif", z)
        gj = [f"G{k:02d}" for k in range(1, n + 1)]
        pd.DataFrame({"zone_id": range(1, n + 1), "GISJOIN": gj}).to_csv(tmp / "cut" / "zones" / "zones_2010.csv",
                                                                           index=False)
        rng = np.random.default_rng(3)
        bui = rng.integers(500, 3000, z.shape).astype("int32")
        bui[:, 11:13] = 1  # county 6: almost no floor area -> area rule
        bui[0, 0] = int(4e7)  # above the cap, outside every county
        bui[1, 1] = int(5e7)  # above the cap in county 1 (counted, kept)
        write(tmp / "BUI_2015.tif", bui)
        bupr = np.array([100, 100, 100, 100, 100, 100, 0, 100], float)
        nb = np.array([10, 50, 150, 400, 20, 30, 40, 0], float)  # ratios 0.09 ... 0.6, 0.8, ..., 1, 0
        pop10 = np.array([100, 120, 90, 100, 1e6, 110, 100, np.nan])  # county 5: records missing; 8: no pop
        u = pd.DataFrame({"zone_id": range(1, n + 1), "GISJOIN": gj, "state": ["A"] * 4 + ["B"] * 4,
                          "name": [f"c{k}" for k in range(1, n + 1)], "bupr_2015": bupr, "nobuilt": nb,
                          "part": ["train", "test"] * 4, "pop_2010": pop10, "pop_1920": 50.0,
                          "gap_2010": [False, False, False, True, False, True, False, False]})
        u["ratio_A_nby"] = nb / (bupr + nb)
        u.to_csv(tmp / "u.csv", index=False)
        pd.DataFrame({"value": range(101), "cells_all": 0, "cells_study": [0, 5, 9, 2, 4] + [0] * 96}).to_csv(
            tmp / "nv.csv", index=False)
        outs = []
        for block in (1024, 1):
            out = tmp / f"out{block}"
            assert uf.main(["--uncertainty", str(tmp / "u.csv"), "--bui", str(tmp / "BUI_2015.tif"), "--cutout",
                            str(tmp / "cut"), "--nobuilt-values", str(tmp / "nv.csv"), "--years", "1920", "2010",
                            "--block-rows", str(block), "--out-dir", str(out)]) == 0
            outs.append(out)
        c = pd.read_csv(outs[0] / "county_filter_inputs.csv").set_index("GISJOIN")
        bsum = np.array([bui[z == k + 1].sum() for k in range(n)], float)
        assert np.allclose(c["bui_2015"], bsum) and c.at["G01", "bui_cells_above_cap"] == 1
        rpp = (bupr + nb) / pop10
        bpr = np.where(bupr > 0, bsum / np.where(bupr > 0, bupr, 1), np.nan)
        assert np.allclose(c["records_per_person"], rpp, equal_nan=True)
        assert np.allclose(c["bui_per_record"], bpr, equal_nan=True)
        f_rec = rpp < 0.05 * np.nanmedian(rpp)
        f_area = bpr < 0.05 * np.nanmedian(bpr)
        assert list(c.index[f_rec]) == ["G05"] and list(c.index[f_area]) == ["G06"]
        assert (c["flag_records"].to_numpy() == f_rec).all() and (c["flag_area"].to_numpy() == f_area).all()
        ratio = nb / (bupr + nb)
        prev = set()
        for t in (0.9, 0.7, 0.5):
            e = pd.read_csv(outs[0] / f"excluded_counties_{uf.label(t)}.csv").set_index("GISJOIN")
            want = {g for g, r, a, b in zip(gj, ratio, f_rec, f_area) if r >= t or a or b}
            assert set(e.index) == want, (t, set(e.index), want)
            assert prev <= want
            prev = want
            assert e.at["G05", "reasons"] == "records" and e.at["G06", "reasons"] == "area"
            assert e.at["G07", "reasons"] == "ratio"  # nb only: ratio 1, no area value
            pd.testing.assert_frame_equal(e.reset_index(), pd.read_csv(outs[1] / f"excluded_counties_{uf.label(t)}.csv"))
        s = pd.read_csv(outs[0] / "filter_summary.csv").set_index("label")
        e5 = set(pd.read_csv(outs[0] / "excluded_counties_t050.csv")["GISJOIN"])
        assert s.at["t050", "excluded"] == len(e5) and s.at["t050", "fixed_rules_only"] == 2
        assert s.at["t050", "test_excluded"] == sum(u.set_index("GISJOIN").loc[list(e5), "part"] == "test")
        assert s.at["t050", "gap_2010_excluded"] == 2
        keep = ~u["GISJOIN"].isin(e5)
        assert np.isclose(s.at["t050", "pop_share_kept_2010"], u.loc[keep, "pop_2010"].sum() / u["pop_2010"].sum())
        print("ok uncertainty_filter: BUI sums, fixed rules, sets per threshold (nested), reasons, summary, strips")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


ERR = {"Dasy_CONUS_RF_v3_all": 0.20, "Dasy_CONUS_RF_v3_u090": 0.195, "Dasy_CONUS_RF_v3_u070": 0.10,
       "Dasy_CONUS_RF_v3_u050": 0.095}
EXCL = {0.9: {"G01", "G02", "G09"}, 0.7: {"G01", "G02", "G09", "G03", "G10"},
        0.5: {"G01", "G02", "G09", "G03", "G10", "G04", "G11"}}
THR = {"Dasy_CONUS_RF_v3_u090": 0.9, "Dasy_CONUS_RF_v3_u070": 0.7, "Dasy_CONUS_RF_v3_u050": 0.5}


def build_results(tmp: Path, years, leak=False):
    ids = [f"G{k:02d}" for k in range(1, 21)]
    test = ids[:8]
    rng = np.random.default_rng(1)
    for t, s in EXCL.items():
        (tmp / "unc").mkdir(exist_ok=True)
        pd.DataFrame({"GISJOIN": sorted(s)}).to_csv(tmp / "unc" / f"excluded_counties_{fc.label(t)}.csv", index=False)
    for y in years:
        cf = pd.DataFrame({"GISJOIN": ids, "pop": rng.integers(1000, 90000, 20).astype(float),
                           "area_km2": rng.uniform(100, 3000, 20)})
        cf["y"] = np.log(cf["pop"] / cf["area_km2"])
        for v, e in ERR.items():
            d = tmp / "dasymetric" / "conus" / v / f"Y{y}"
            d.mkdir(parents=True)
            cf.to_csv(d / "county_features.csv", index=False)
            ex = EXCL.get(THR.get(v), set())
            # alternate over / under so that MdAPE = MAPE = 100 e
            sign = np.where(np.arange(20) % 2 == 0, 1.0, -1.0)
            p = cf.assign(y_hat=cf["y"] + np.log(1 + sign * e), part=["test"] * 8 + ["train"] * 12)
            tp = p[p["GISJOIN"].isin(test) & (~p["GISJOIN"].isin(ex) | (leak and v.endswith("u050")))]
            tp[["GISJOIN", "y", "y_hat"]].to_csv(d / "test_predictions.csv", index=False)
            if v in THR:
                p[p["GISJOIN"].isin(ex)][["GISJOIN", "y", "y_hat", "part"]].to_csv(d / "excluded_predictions.csv",
                                                                                   index=False)
            vt = tmp / "validation" / "conus" / v
            vt.mkdir(parents=True, exist_ok=True)
            te = pd.DataFrame({"zone_gisjoin": np.repeat(ids, 3), "flag": "ok", "pop_obs": 100.0})
            te["pop_model"] = 100 * (1 + e)
            te["pop_baseline"] = 150.0
            te["gap"] = te["zone_gisjoin"].isin(["G01", "G12"])
            te.loc[0, "flag"] = "no_pop"
            te.to_csv(vt / f"tract_errors_{y}.csv", index=False)


def run_compare(tmp: Path, years):
    return fc.main(["--results-root", str(tmp), "--exclusions", str(tmp / "unc"), "--years", *map(str, years),
                    "--out-dir", str(tmp / "out")])


def test_filter_compare():
    tmp = Path(tempfile.mkdtemp())
    years = [2010, 2020]
    try:
        build_results(tmp, years)
        assert run_compare(tmp, years) == 0
        cmp = pd.read_csv(tmp / "out" / "filter_comparison.csv")
        cty = cmp[cmp["level"] == "county"]
        a = cty[cty["set"] == "common_test"]
        b = cty[cty["set"] == "imputed_test"]
        assert (a["n"] == 4).all() and len(a) == 8  # G05-G08 for every model and year
        assert (b["n"] == 2).all() and len(b) == 8  # G01, G02
        for v, e in ERR.items():
            for s in (a, b):
                r = s[s["version"] == v]
                assert np.allclose(r["mdape"], 100 * e) and np.allclose(r["mape"], 100 * e)
        own = cty[cty["set"] == "own_excluded"].set_index("version")
        assert own.groupby(level=0)["n"].first().to_dict() == {v: len(EXCL[t]) for v, t in THR.items()}
        assert "Dasy_CONUS_RF_v3_all" not in own.index
        # R2 of log density by hand (v5.4, 2010, common set)
        cf = pd.read_csv(tmp / "dasymetric" / "conus" / "Dasy_CONUS_RF_v3_all" / "Y2010" / "county_features.csv")
        tp = pd.read_csv(tmp / "dasymetric" / "conus" / "Dasy_CONUS_RF_v3_all" / "Y2010" / "test_predictions.csv")
        q = tp[tp["GISJOIN"].isin(["G05", "G06", "G07", "G08"])]
        want = 1 - ((q["y_hat"] - q["y"]) ** 2).sum() / ((q["y"] - q["y"].mean()) ** 2).sum()
        got = a[(a["version"] == "Dasy_CONUS_RF_v3_all") & (a["year"] == 2010)]["r2_logdens"].iloc[0]
        assert np.isclose(got, want)
        # tracts: 60 tracts, 1 flagged; excluded_t050 = 7 counties x 3 minus the flagged one (G01)
        tr = cmp[(cmp["level"] == "tract") & (cmp["year"] == 2010)].set_index(["version", "set"])
        assert tr.loc[("Dasy_CONUS_RF_v3_all", "all"), "n"] == 59
        assert tr.loc[("Dasy_CONUS_RF_v3_u050", "excluded_t050"), "n"] == 20
        assert tr.loc[("Dasy_CONUS_RF_v3_u050", "kept_t050"), "n"] == 39
        assert tr.loc[("Dasy_CONUS_RF_v3_u090", "gap"), "n"] == 5
        assert np.isclose(tr.loc[("areal_weighting", "all"), "mdape"], 50)
        assert np.isclose(tr.loc[("Dasy_CONUS_RF_v3_u070", "all"), "mdape"], 10)
        # rule: scores 20 / 19.5 / 10 / 9.5 -> best u050; u070 within 1 pp keeps more counties -> u070
        sel = pd.read_csv(tmp / "out" / "filter_selection.csv").set_index("version")
        assert np.allclose(sel["score"], [100 * ERR[v] for v in sel.index])
        assert sel["within_tie"].to_dict() == {"Dasy_CONUS_RF_v3_all": False, "Dasy_CONUS_RF_v3_u090": False,
                                               "Dasy_CONUS_RF_v3_u070": True, "Dasy_CONUS_RF_v3_u050": True}
        assert sel.index[sel["chosen"]].tolist() == ["Dasy_CONUS_RF_v3_u070"]
        assert (tmp / "out" / "filter_comparison.png").exists()
        print("ok filter_compare: common / imputed TEST sets, metrics by hand, tract parts, rule with the 1 pp tie")
        # a missing year: no model complete -> no choice, still exit 0
        assert run_compare(tmp, [2010, 2020, 2030]) == 0
        assert not pd.read_csv(tmp / "out" / "filter_selection.csv")["chosen"].any()
        print("ok filter_compare: a missing year -> no rule result")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    tmp = Path(tempfile.mkdtemp())
    try:
        build_results(tmp, [2010], leak=True)
        try:
            run_compare(tmp, [2010])
        except SystemExit as e:
            assert "excluded counties in its TEST predictions" in str(e)
        else:
            raise AssertionError("an excluded county in the TEST predictions must stop the run")
        print("ok filter_compare: an excluded county in TEST predictions stops the run")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_filter_sets()
    test_filter_compare()
    print("ALL OK")
