"""v5.4 + NobuiltYear without the filter (docs/handoff/v54_nby_request.md; docs/conus_plan.md "v5.4 + NobuiltYear (no
filter)"). Plain script, no pytest; needs the local hisdac env (see CLAUDE.md).
  test_config   conus_rf_v3_all_nby.yaml = v5.4's eras of 1910 / 1940 / 1960 / 1980 / 2010 + nby, no exclude_counties,
                every other setting as v5.4; v5.4's own config unchanged
  test_compare  v54_nby_compare.py on synthetic result files of four versions: all TEST counties (filter versions =
                test_predictions + the TEST part of excluded_predictions) MdAPE / MAPE / R2 by hand, kept / excluded
                parts, the reported R2 check, CV columns named by their CV set, nby ranks, tract d_mdape vs v5.4, cells /
                city rows read again; the check against the NobuiltYear test's files passes on equal rows, stops on a
                changed one; a different TEST set stops
  test_diag     undated_age_diag.py on a synthetic HISDAC / cutout: groups, FBUY quantiles, decade shares by hand, a
                raster on another grid read through the WarpedVRT; county Spearman = scipy; rerun without rasters
                keeps the cell rows
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
import test_conus_dasymetric as T  # noqa: E402  (stubs shap / plots; paths)

import common as dcommon  # noqa: E402

REPO = T.REPO
YEARS = [1910, 1940, 1960, 1980, 2010]
sys.path[:0] = [str(REPO / "src" / "validation"), str(REPO / "src" / "grid")]


def test_config():
    base = dcommon.load_config(REPO / "configs" / "conus_rf_v3_all.yaml")
    c = dcommon.load_config(REPO / "configs" / "conus_rf_v3_all_nby.yaml")
    # since 2026-11-04 (v5.7 all years, tests/test_v57all.py) 13 eras 1900-2020; the five of this test unchanged
    assert c["version"] == "Dasy_CONUS_RF_v3_all_nby" and set(YEARS) <= set(c["years"])
    assert c["compare_with"] == "Dasy_CONUS_RF_v3_all"
    assert c["exclude_counties"] is None and c["nby_age"] is None
    assert {f"Y{y}" for y in YEARS} <= set(c["eras"])
    for e in c["eras"]:
        assert c["eras"][e]["years"] == base["eras"][e]["years"]
        assert c["eras"][e]["features"] == base["eras"][e]["features"] + ["nby"], e
    for key in ("split", "exclude_counties", "use_status", "train_status", "water_mask", "block_rows", "unusable",
                "model", "search", "models", "permutation", "correlation_threshold", "study_area"):
        assert c[key] == base[key], key
    assert c["search"]["n_iter"] == 60
    # v5.4 itself unchanged: 13 eras 1900-2020 without nby
    assert base["version"] == "Dasy_CONUS_RF_v3_all" and len(base["eras"]) == 13
    assert all("nby" not in e["features"] for e in base["eras"].values())
    # same features as the NobuiltYear test on the shared part: v5.6 + nby has the same era features
    v56n = dcommon.load_config(REPO / "configs" / "conus_rf_v3_u070_nby.yaml")
    assert {e: v56n["eras"][e]["features"] for e in v56n["eras"]} == {e: c["eras"][e]["features"] for e in v56n["eras"]}
    print("ok config: v5.4 + nby = v5.4 eras (1910-2010 of this test) + nby, no filter, settings as v5.4; v5.4 unchanged")


# ---------------------------------------------------------------- compare

V = {"v56": "Dasy_CONUS_RF_v3_u070", "v56_nby": "Dasy_CONUS_RF_v3_u070_nby", "v54": "Dasy_CONUS_RF_v3_all",
     "v54_nby": "Dasy_CONUS_RF_v3_all_nby"}
F = {"v56": 1.0, "v56_nby": 0.8, "v54": 1.2, "v54_nby": 0.9}  # error factor per version
EXCL = ["G003", "G004", "G010"]


def r2(o, p):
    return 1 - ((p - o) ** 2).sum() / ((o - o.mean()) ** 2).sum()


def write_world(root: Path, years, rng):
    """Result files of the four versions: 20 counties, TEST = G000-G007 (G003 / G004 excluded by t070; G010 = an
    excluded train county), tract errors, features with nby in the nby versions."""
    tracts = pd.DataFrame({"GISJOIN": [f"T{i:04d}" for i in range(300)], "zone_gisjoin": [f"G{i % 20:03d}" for i in range(300)],
                           "n_cells": rng.integers(1, 200, 300), "pop_obs": rng.integers(5, 6000, 300).astype(float)})
    tracts["gap"] = tracts["zone_gisjoin"].isin(["G000", "G001"])
    err = rng.normal(0, 0.3, 300)
    cf = pd.DataFrame({"GISJOIN": [f"G{i:03d}" for i in range(20)], "pop": rng.integers(1000, 9000, 20) * 1.0,
                       "area_km2": rng.uniform(50, 500, 20)})
    cf["y"] = np.log(cf["pop"] / cf["area_km2"])
    test_ids = [f"G{i:03d}" for i in range(8)]
    noise = rng.normal(0, 0.4, 20)
    split = pd.DataFrame({"GISJOIN": cf["GISJOIN"], "part": np.where(cf["GISJOIN"].isin(test_ids), "test", "train"),
                          "fold": 0})
    split.to_csv(root / "split.csv", index=False)
    for lab, v in V.items():
        f = F[lab]
        filt = lab.startswith("v56")
        for y in years:
            d = root / "validation" / "conus" / v
            d.mkdir(parents=True, exist_ok=True)
            tracts.assign(flag="ok", pop_model=tracts["pop_obs"] * (1 + f * err),
                          pop_baseline=tracts["pop_obs"] * (1 + 2 * err)).to_csv(d / f"tract_errors_{y}.csv", index=False)
            e = root / "dasymetric" / "conus" / v / f"Y{y}"
            e.mkdir(parents=True, exist_ok=True)
            cf.to_csv(e / "county_features.csv", index=False)
            pred = cf.assign(y_hat=cf["y"] + f * noise)
            test = pred[pred["GISJOIN"].isin(test_ids)]
            own = test[~test["GISJOIN"].isin(EXCL)] if filt else test
            own[["GISJOIN", "y", "y_hat"]].to_csv(e / "test_predictions.csv", index=False)
            if filt:
                ex = pred[pred["GISJOIN"].isin(EXCL)].assign(
                    part=lambda t: np.where(t["GISJOIN"].isin(test_ids), "test", "train"))
                ex[["GISJOIN", "y", "y_hat", "part"]].to_csv(e / "excluded_predictions.csv", index=False)
            train_ids = [g for g in cf["GISJOIN"] if g not in test_ids and not (filt and g in EXCL)]
            pd.DataFrame({"GISJOIN": train_ids, "y": 0.0, "oof": 0.0}).to_csv(e / "oof_predictions.csv", index=False)
            rep = r2(own["y"].to_numpy(), own["y_hat"].to_numpy())
            (e / "metrics.json").write_text(json.dumps({"cv_rmse_mean": 0.4 * f, "cv_r2_mean": 0.9 - 0.01 * f,
                                                        "test_rmse": 0.45, "test_r2": rep}))
            fe = ["bui", "elev"] + (["nby"] if lab.endswith("nby") else [])
            perm = np.linspace(1, 0.1, len(fe))
            pd.DataFrame({"feature": fe, "permutation_mean": perm}).to_csv(e / "feature_importance.csv", index=False)
            pd.DataFrame({"feature": fe, "mean_abs_shap": perm[::-1]}).to_csv(e / "shap_importance.csv", index=False)
    return cf, noise, test_ids, tracts, err


def run_compare(tmp: Path, out: Path, years, extra=()):
    ex = tmp / "excluded.csv"
    pd.DataFrame({"GISJOIN": EXCL}).to_csv(ex, index=False)
    args = ["--results-root", str(tmp), "--exclusions", str(ex), "--split", str(tmp / "split.csv"), "--out-dir",
            str(out), "--nobuilt-dir", str(tmp / "nobuilt"), "--years", *map(str, years), *extra]
    return subprocess.run([sys.executable, str(REPO / "src" / "validation" / "v54_nby_compare.py"), *args],
                          capture_output=True, text=True, cwd=REPO)


def test_compare():
    import v54_nby_compare as vc
    tmp = Path(tempfile.mkdtemp())
    try:
        years = [1910, 2010]
        cf, noise, test_ids, tracts, err = write_world(tmp, years, np.random.default_rng(3))
        out = tmp / "out"
        out.mkdir()
        cells = pd.DataFrame([{"version": v, "variant": lab, "year": y, "cells": 100, "share_bui0": 0.05 * F[lab],
                               "share_nb_of_bui0": 0.4, "share_bui0_nb": 0.02} for lab, v in V.items() for y in years])
        cells.to_csv(out / "v54_nby_cells.csv", index=False)
        city = pd.DataFrame([{"city": "denver", "year": 2010, "version": v, "variant": lab, "set": s, "n_blocks": 7,
                              "pop_version": 100 * F[lab], "pop_ghs_pop": 1000.0, "ratio": 0.1 * F[lab]}
                             for lab, v in V.items() for s in ("gap_own", "gap_v56")])
        city.to_csv(out / "v54_nby_city_gaps.csv", index=False)
        r = run_compare(tmp, out, years)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        assert "DIFFERS" not in r.stdout and "SUMMARY county ALL TEST counties" in r.stdout
        assert "not a selection criterion" in r.stdout
        cmp = pd.read_csv(out / "v54_nby_comparison.csv")
        c = cmp[(cmp["level"] == "county") & (cmp["year"] == 2010)].set_index(["variant", "set"])
        t = cf[cf["GISJOIN"].isin(test_ids)]
        for lab in V:
            for s, m in (("test_all", np.ones(len(t), bool)), ("test_kept_t070", ~t["GISJOIN"].isin(EXCL).to_numpy()),
                         ("test_excluded_t070", t["GISJOIN"].isin(EXCL).to_numpy())):
                o = t["pop"].to_numpy()[m]
                yh = (t["y"] + F[lab] * noise[t.index]).to_numpy()[m]
                est = np.exp(yh) * t["area_km2"].to_numpy()[m]
                ape = np.abs(est - o) / o * 100
                row = c.loc[(lab, s)]
                assert row["n"] == m.sum(), (lab, s)
                assert np.isclose(row["mdape"], np.median(ape)) and np.isclose(row["mape"], ape.mean()), (lab, s)
                assert np.isclose(row["r2"], r2(t["y"].to_numpy()[m], yh)), (lab, s)
            own = "test_kept_t070" if lab.startswith("v56") else "test_all"
            assert c.loc[(lab, own), "r2_reported_same"] == True, lab  # noqa: E712
        assert c.loc[("v56", "test_all"), "n"] == 8 and c.loc[("v56", "test_excluded_t070"), "n"] == 2
        # CV columns named by their CV set; only on test_all rows
        a = c.xs("test_all", level="set")
        assert np.isclose(a.at["v54", "cv_rmse_train_all"], 0.48) and np.isnan(a.at["v54", "cv_rmse_train_kept_t070"])
        assert np.isclose(a.at["v56_nby", "cv_rmse_train_kept_t070"], 0.32) and np.isnan(a.at["v56_nby", "cv_rmse_train_all"])
        assert a.at["v56", "cv_counties"] == 11 and a.at["v54", "cv_counties"] == 12
        assert a["cv_note"].str.contains("not a selection criterion").all()
        assert a.at["v54_nby", "nby_perm_rank"] == 3 and a.at["v54_nby", "nby_shap_rank"] == 1
        assert np.isnan(a.at["v54", "nby_perm_rank"])
        # tracts: same sets as the NobuiltYear test, d_mdape against v5.4
        tr = cmp[(cmp["level"] == "tract") & (cmp["set"] == "all") & (cmp["year"] == 2010)].set_index("variant")
        for lab in V:
            assert np.isclose(tr.at[lab, "mdape"], 100 * np.median(np.abs(F[lab] * err))), lab
            assert np.isclose(tr.at[lab, "d_mdape"], tr.at[lab, "mdape"] - tr.at["v54", "mdape"]), lab
        assert set(cmp.loc[cmp["level"] == "tract", "set"]) >= {"all", "kept_t070", "excluded_t070", "gap", "no_gap",
                                                                "dens_0_50", "dens_2000_plus"}
        ce = cmp[(cmp["level"] == "cells") & (cmp["year"] == 2010)].set_index(["variant", "set"])["share"]
        assert np.isclose(ce[("v54", "share_bui0")], 0.06)
        cg = cmp[cmp["level"] == "city_gap"].set_index(["variant", "set"])
        assert np.isclose(cg.at[("v54_nby", "gap_v56"), "share"], 0.09)
        ranks = pd.read_csv(out / "v54_nby_feature_ranks.csv")
        assert set(ranks["variant"]) == set(V) and "nby" in set(ranks["feature"])
        # the nobuilt files are not written
        assert not (out / "nobuilt_comparison.csv").exists()

        # check against the NobuiltYear test's files (vc.checked): equal rows pass, a changed one stops
        nb = tmp / "nobuilt"
        nb.mkdir()
        old = city[city["variant"].isin(["v56", "v56_nby"])].replace({"variant": {"v56": "base", "v56_nby": "nby"}})
        old.to_csv(nb / "nobuilt_city_gaps.csv", index=False)
        cols = ["n_blocks", "pop_version", "pop_ghs_pop", "ratio"]
        vc.checked(city, nb / "nobuilt_city_gaps.csv", ["city", "year", "version", "set"], cols, "city")
        bad = city.copy()
        bad.loc[(bad["variant"] == "v56_nby") & (bad["set"] == "gap_own"), "pop_version"] += 1
        for frame in (bad, city[city["variant"] != "v56"].pipe(lambda d: pd.concat([d, d.assign(set="gap_x",
                                                                                                 version=V["v56"])]))):
            try:
                vc.checked(frame, nb / "nobuilt_city_gaps.csv", ["city", "year", "version", "set"], cols, "city")
                raise AssertionError("changed / unmatched rows passed")
            except SystemExit:
                pass
        # a different TEST set stops
        e = tmp / "dasymetric" / "conus" / V["v54_nby"] / "Y2010"
        tp = pd.read_csv(e / "test_predictions.csv")
        tp.iloc[1:].to_csv(e / "test_predictions.csv", index=False)
        r = run_compare(tmp, out, years)
        assert r.returncode != 0 and "differ" in (r.stdout + r.stderr), r.stdout[-2000:]
        print("ok v54_nby_compare: all TEST = test + excluded TEST rows, metrics by hand, kept / excluded, reported "
              "R2, CV columns by set, ranks, tracts vs v5.4, cells / city read again, nobuilt check, TEST set check")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- undated age diagnosis

def write_tif(path: Path, a: np.ndarray, transform, nodata=None, crs="EPSG:5070"):
    import rasterio
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", height=a.shape[0], width=a.shape[1], count=1, dtype=a.dtype,
                       crs=crs, transform=transform, nodata=nodata) as dst:
        dst.write(a, 1)


def test_diag():
    from rasterio.transform import from_origin
    from scipy.stats import spearmanr
    tmp = Path(tempfile.mkdtemp())
    try:
        rng = np.random.default_rng(5)
        H, W = 23, 17
        tr = from_origin(1000, 9000, 250, 250)
        zones = rng.integers(0, 4, (H, W)).astype(np.int32)  # 0 = outside the study area
        nb = np.where(rng.random((H, W)) < 0.4, rng.integers(1, 9, (H, W)), 0).astype(np.int32)
        ref = np.where(rng.random((H, W)) < 0.6, rng.integers(1, 30, (H, W)), 0).astype(np.int32)
        fb = np.where(ref > 0, rng.integers(1790, 2016, (H, W)), 0).astype(np.int32)
        fb[0, 0], ref[0, 0], nb[0, 0], zones[0, 0] = -1, 5, 0, 1  # nodata FBUY on a built study cell = none
        hd, cut = tmp / "hisdac", tmp / "cutout"
        write_tif(cut / "zones" / "zones_2010.tif", zones, tr)
        pd.DataFrame({"zone_id": range(4), "GISJOIN": ["", "G1", "G2", "G3"]}).to_csv(cut / "zones" / "zones_2010.csv",
                                                                                      index=False)
        write_tif(hd / "FBUY" / "FBUY.tif", fb, tr, nodata=-1)
        write_tif(hd / "BUPR" / "2015_BUPR.tif", ref, tr)
        # NobuiltYear one column wider on the left: read through the WarpedVRT onto the zone grid
        nb_wide = np.concatenate([np.full((H, 1), 99, np.int32), nb], axis=1)
        write_tif(hd / "FBUY" / "NobuiltYear.tif", nb_wide, from_origin(750, 9000, 250, 250))
        ct = pd.DataFrame({"GISJOIN": [f"G{i:03d}" for i in range(40)], "nobuilt": rng.integers(0, 50, 40),
                           "bupr_1940": rng.integers(0, 50, 40), "bupr_2015": rng.integers(0, 200, 40)})
        ct.loc[0, "bupr_2015"] = 0
        ct["bupr_1940"] = np.minimum(ct["bupr_1940"], ct["bupr_2015"])
        ct["ratio_A_nby"] = ct["nobuilt"] / (ct["bupr_2015"] + ct["nobuilt"]).replace(0, np.nan)
        ct.to_csv(tmp / "county.csv", index=False)
        out = tmp / "out"
        args = ["--county-table", str(tmp / "county.csv"), "--out-dir", str(out)]
        script = str(REPO / "src" / "grid" / "undated_age_diag.py")
        r = subprocess.run([sys.executable, script, "--hisdac-dir", str(hd), "--cutout", str(cut), "--block-rows", "5",
                            *args], capture_output=True, text=True, cwd=REPO)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        assert "WarpedVRT" in r.stdout
        t = pd.read_csv(out / "undated_age_diag.csv")
        cell = t[t["level"] == "cell"].set_index(["group", "item"])["value"]
        study = zones > 0
        b = study & ((ref > 0) | (nb > 0))
        fbv = np.where(fb < 0, 0, fb)
        groups = {"nb_gt0": b & (nb > 0), "nb_eq0": b & (nb == 0), "nb_gt0_dated": b & (nb > 0) & (ref > 0),
                  "nb_only": b & (nb > 0) & (ref == 0)}
        assert cell[("built", "cells")] == b.sum()
        for g, m in groups.items():
            yrs = np.sort(fbv[m][fbv[m] > 0])
            assert cell[(g, "cells")] == m.sum() and cell[(g, "fbuy_cells")] == len(yrs), g
            assert cell[(g, "fbuy_none")] == m.sum() - len(yrs), g
            if len(yrs):
                for q in (0.05, 0.25, 0.5, 0.9):
                    k = int(np.ceil(q * len(yrs))) - 1  # lower quantile: smallest v with share <= v >= q
                    assert cell[(g, f"q{int(round(q * 100)):02d}")] == yrs[max(k, 0)], (g, q)
                assert np.isclose(cell[(g, "mean")], yrs.mean())
                assert np.isclose(cell[(g, "share_1950s")], ((yrs >= 1950) & (yrs < 1960)).mean())
                assert np.isclose(cell[(g, "share_before_1800")], (yrs < 1800).mean())
                assert np.isclose(cell[(g, "share_le_1940")], (yrs <= 1940).mean())
                dec = [i for i in cell[g].index if i.startswith("share_") and i.endswith("0s")]
                assert np.isclose(sum(cell[(g, i)] for i in dec) + cell[(g, "share_before_1800")], 1.0), g
        assert cell[("nb_only", "fbuy_cells")] == 0  # FBUY only where dated records are
        cty = t[t["level"] == "county"].set_index(["group", "item"])["value"]
        d = ct[ct["bupr_2015"] > 0].dropna(subset=["ratio_A_nby"])
        rho = spearmanr(d["ratio_A_nby"], d["bupr_1940"] / d["bupr_2015"]).statistic
        assert cty[("ref_gt0", "counties")] == len(d)
        assert np.isclose(cty[("ref_gt0", "spearman_ratio_A_nby_vs_bupr_1940_share")], rho)
        assert sum(cty[(g, "counties")] for g, i in cty.index if g.startswith("ratio_A_nby_") and i == "counties") == len(d)
        # rerun without rasters: the cell rows are kept, the county rows rewritten
        r = subprocess.run([sys.executable, script, *args], capture_output=True, text=True, cwd=REPO)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        t2 = pd.read_csv(out / "undated_age_diag.csv")
        pd.testing.assert_frame_equal(t2, t, check_dtype=False)
        print("ok undated_age_diag: groups, FBUY quantiles / mean / decade shares by hand, nodata = none, WarpedVRT "
              "read, county Spearman = scipy, rerun keeps the cell rows")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_config()
    test_compare()
    test_diag()
