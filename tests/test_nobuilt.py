"""Synthetic test of the NobuiltYear feature test (docs/conus_plan.md "NobuiltYear feature test"), runnable without the
cluster:

    python tests/test_nobuilt.py      (hisdac env; on Windows with its Library\\bin on PATH, see CLAUDE.md)

Checks:
  - configs: nby / nbya = v5.6 (split, exclusions, search ...) + nby / nby_age in every era (1910 / 1940 / 1960 / 1980 /
    2010, v5.6's era features of those years); the NOBUILT cutout layer; bad nby_age blocks stop load_config
  - nby_age factor by hand: f_c = sum BUPR_year / BUPR_2015, clipped to 1 (BUPR_year > BUPR_2015), 1 where BUPR_2015 = 0;
    a county missing from the reference table stops; strips == whole window
  - county_features on the synthetic CONUS cutout: nby = mean of NOBUILT over the unmasked cells, nby_age = f_c x that
    mean (by hand); strips == whole window; the other columns = the config without the feature (unchanged)
  - train + predict with nby_age: mass preserved; a changed or missing nby_age_factor.csv stops predict
  - nobuilt_compare: cell sums by hand (people on BUI = 0 / NobuiltYear > 0 cells, NoData left out); city gap blocks on
    the synthetic city world of test_external_city_meeting (v5.6's own = the meeting gap table, a variant that fills the
    gap has none of its own, on v5.6's blocks by hand; a changed meeting table stops); tables from small result files
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path[:0] = [str(Path(__file__).resolve().parent)]
import test_conus_dasymetric as T  # noqa: E402  (stubs shap / plots; synthetic cutout + configs)
import test_plural as TP  # noqa: E402  (small result files)

import yaml  # noqa: E402

import common as dcommon  # noqa: E402
import county_features  # noqa: E402
import predict  # noqa: E402
import train  # noqa: E402

REPO = T.REPO
YEARS = [1910, 1940, 1960, 1980, 2010]


def test_configs():
    base = dcommon.load_config(REPO / "configs" / "conus_rf_v3_u070.yaml")
    assert base["nby_age"] is None
    for v, f in (("nby", "nby"), ("nbya", "nby_age")):
        c = dcommon.load_config(REPO / "configs" / f"conus_rf_v3_u070_{v}.yaml")
        assert c["version"] == f"Dasy_CONUS_RF_v3_u070_{v}" and c["years"] == YEARS
        assert c["compare_with"] == "Dasy_CONUS_RF_v3_u070"
        assert list(c["eras"]) == [f"Y{y}" for y in YEARS]
        for e in c["eras"]:
            assert c["eras"][e]["features"] == base["eras"][e]["features"] + [f], (v, e)
        for key in ("split", "exclude_counties", "use_status", "train_status", "water_mask", "block_rows", "unusable",
                    "model", "search", "models", "permutation", "correlation_threshold"):
            assert c[key] == base[key], (v, key)
        assert c["search"]["n_iter"] == 60
        if v == "nbya":
            assert c["nby_age"]["bupr_ref"] == REPO / "results" / "hisdac_uncertainty" / "county_record_uncertainty.csv"
            assert c["nby_age"]["bupr_ref"].exists()
            ref = pd.read_csv(c["nby_age"]["bupr_ref"], usecols=["GISJOIN", "bupr_2015"])
            assert ref["GISJOIN"].is_unique and len(ref) > 3000
        else:
            assert c["nby_age"] is None
    study = yaml.safe_load((REPO / "configs" / "conus_study_area.yaml").read_text(encoding="utf-8"))
    lay = [x for x in study["layers"] if x["name"] == "NOBUILT"]
    assert lay == [{"name": "NOBUILT", "path": "FBUY/NobuiltYear.tif", "years": "none", "resampling": "none",
                    "out": "NOBUILT/NOBUILT.tif"}], lay
    tmp = Path(tempfile.mkdtemp())
    try:
        raw = yaml.safe_load((REPO / "configs" / "conus_rf_v3_u070_nbya.yaml").read_text())
        raw["study_area"] = str(REPO / "configs" / "conus_study_area.yaml")
        p = tmp / "bad.yaml"
        for bad, msg in (({"nby_age": None}, "needs"), ({"nby_age": {"x": 1}}, "needs")):
            p.write_text(yaml.safe_dump({**raw, **bad}))
            try:
                dcommon.load_config(p)
                raise AssertionError(f"{bad} passed")
            except SystemExit as e:
                assert msg in str(e), e
        v = yaml.safe_load((REPO / "configs" / "conus_rf_v3_u070_nby.yaml").read_text())
        v["study_area"] = raw["study_area"]
        p.write_text(yaml.safe_dump({**v, "nby_age": raw["nby_age"]}))
        try:
            dcommon.load_config(p)
            raise AssertionError("nby_age block without the feature passed")
        except SystemExit as e:
            assert "not used" in str(e), e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ok configs: nby / nbya = v5.6 eras 1910-2010 + one feature, NOBUILT layer static int32; bad blocks stop")


# ---------------------------------------------------------------- synthetic cutout

def setup_world(tmp: Path):
    """Synthetic cutout + NOBUILT layer + BUPR_2015 reference: zone 2 has BUPR_2015 = 0 (factor 1), zone 3 a BUPR_2015
    below its 1960 sum (clipped to 1 both years), every other zone 1.25 x its 2010 sum."""
    counties = T.county_table()
    cut, zones = T.make_cutout(tmp, counties)
    rng = np.random.default_rng(7)
    nob = rng.poisson(1.5, zones.shape).astype("int32")
    nob[rng.random(zones.shape) < 0.4] = 0
    T.write_tif(cut / "layers" / "NOBUILT" / "NOBUILT.tif", nob)
    sums = {}
    for y in T.YEARS:
        b = T.read(cut / "layers" / "BUPR" / f"{y}_BUPR.tif").astype(float)
        sums[y] = np.bincount(zones.ravel(), weights=b.ravel(), minlength=len(counties) + 1)
    ref = counties[["zone_id", "GISJOIN"]].copy()
    ref["bupr_2015"] = 1.25 * sums[2010][ref["zone_id"]]
    ref.loc[ref["zone_id"] == 2, "bupr_2015"] = 0.0
    ref.loc[ref["zone_id"] == 3, "bupr_2015"] = 0.5 * sums[1960][3]
    ref["bupr_1960"] = sums[1960][ref["zone_id"]]   # the cross-check columns of record_uncertainty.py
    ref_path = tmp / "county_record_uncertainty.csv"
    ref.to_csv(ref_path, index=False)
    return counties, cut, zones, nob, sums, ref, ref_path


def hand_factor(sums, ref, y):
    r = ref.set_index("zone_id")["bupr_2015"]
    return {z: 1.0 if r[z] <= 0 else min(max(sums[y][z] / r[z], 0.0), 1.0) for z in r.index}


def test_factor():
    tmp = Path(tempfile.mkdtemp())
    try:
        counties, cut, zones, nob, sums, ref, ref_path = setup_world(tmp)
        for y in T.YEARS:
            zy, tab, grid = dcommon.read_zones(cut, y)
            used = dcommon.county_selection(tab, zy, ["ok", "filled_nhgis", "filled_nhgis_alloc"], y, "skip")
            whole = dcommon.nby_age_setup(cut, y, grid, zy, used, {"bupr_ref": ref_path})
            strip = dcommon.nby_age_setup(cut, y, grid, zy, used, {"bupr_ref": ref_path}, 7)
            pd.testing.assert_frame_equal(whole["table"], strip["table"])
            assert np.array_equal(whole["f"], strip["f"])
            want = hand_factor(sums, ref, y)
            t = whole["table"].set_index("zone_id")
            for z in t.index:
                assert np.isclose(t.at[z, "factor"], want[z], rtol=1e-15, atol=0), (y, z)
                assert whole["f"][z] == t.at[z, "factor"]
            assert t.at[2, "factor"] == 1.0 and t.at[2, "rule"] == "bupr_2015_zero" and np.isnan(t.at[2, "ratio"])
            assert t.at[3, "factor"] == 1.0 and t.at[3, "rule"] == "clipped_1" and t.at[3, "ratio"] > 1
            other = t.drop(index=[2, 3])
            assert (other["rule"] == "ratio").all() and (other["factor"] < 1).all()
            if y == 2010:
                assert np.allclose(other["factor"], 0.8)
            assert np.allclose(t[f"bupr_{y}"], sums[y][t.index])
        bad = ref[ref["zone_id"] != 4]
        bad.to_csv(tmp / "bad.csv", index=False)
        zy, tab, grid = dcommon.read_zones(cut, 2010)
        used = dcommon.county_selection(tab, zy, ["ok"], 2010, "skip")
        try:
            dcommon.nby_age_setup(cut, 2010, grid, zy, used, {"bupr_ref": tmp / "bad.csv"})
            raise AssertionError("a county missing from the reference passed")
        except SystemExit as e:
            assert "not in" in str(e), e
        print("ok nby_age factor by hand (ratio, clipped to 1, BUPR_2015 = 0 -> 1), strips == whole, missing county stops")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def variant_config(tmp: Path, base: dict, name: str, feat: str, ref_path: Path, block_rows=7):
    c = {**base, "version": name, "compare_with": None,
         "eras": {f"Y{y}": {"years": [y], "features": base["eras"][f"Y{y}"]["features"] + [feat]} for y in T.YEARS},
         "feature_groups": {**base["feature_groups"], "Undated records": [feat]}}
    if feat == "nby_age":
        c["nby_age"] = {"bupr_ref": str(ref_path)}
    c.pop("block_rows", None)
    if block_rows:
        c["block_rows"] = block_rows
    p = tmp / "configs" / f"{name}.yaml"
    p.write_text(yaml.safe_dump(c))
    return p


def test_pipeline():
    tmp = Path(tempfile.mkdtemp())
    try:
        counties, cut, zones, nob, sums, ref, ref_path = setup_world(tmp)
        split = T.make_split.make_split(counties[["GISJOIN", "fips", "state", "name"]], 0.2, 5, 42)
        split_path = tmp / "split.csv"
        split.to_csv(split_path, index=False)
        cfgs = T.write_configs(tmp, split_path)
        base = yaml.safe_load(cfgs["tblocks"].read_text())
        out_root = tmp / "dasym"
        common = ["--out-root", str(out_root)]
        cutr = ["--cutout-root", str(tmp / "cutouts")]
        cn = variant_config(tmp, base, "nby", "nby", ref_path)
        ca = variant_config(tmp, base, "nbya", "nby_age", ref_path)
        caw = variant_config(tmp, base, "nbyaw", "nby_age", ref_path, None)
        for c in (cfgs["tblocks"], cn, ca, caw):
            county_features.main(["--config", str(c)] + cutr + common)
        for y in T.YEARS:
            f0 = pd.read_csv(out_root / "conus" / "tblocks" / f"Y{y}" / "features" / "county_features.csv")
            fn = pd.read_csv(out_root / "conus" / "nby" / f"Y{y}" / "features" / "county_features.csv")
            fa = pd.read_csv(out_root / "conus" / "nbya" / f"Y{y}" / "features" / "county_features.csv")
            fw = pd.read_csv(out_root / "conus" / "nbyaw" / f"Y{y}" / "features" / "county_features.csv")
            pd.testing.assert_frame_equal(fa, fw, rtol=1e-12)
            pd.testing.assert_frame_equal(fn.drop(columns="nby"), f0)      # the other columns unchanged
            pd.testing.assert_frame_equal(fa.drop(columns="nby_age"), f0)
            b_ = T.read(cut / "layers" / "BUI" / f"{y}_BUI.tif")
            w_ = T.read(cut / "layers" / "water_frac" / f"{y}_water_frac.tif")
            keep = ~((w_ >= 1) & (b_ == 0))
            fac = hand_factor(sums, ref, y)
            for r in fn.merge(fa[["zone_id", "nby_age"]], on="zone_id").itertuples():
                m = nob[(zones == r.zone_id) & keep].astype(float).mean()
                assert np.isclose(r.nby, m, rtol=1e-12), (y, r.zone_id)
                assert np.isclose(r.nby_age, fac[r.zone_id] * m, rtol=1e-12), (y, r.zone_id)
            ff = pd.read_csv(out_root / "conus" / "nbya" / f"Y{y}" / "features" / "nby_age_factor.csv")
            assert set(ff["GISJOIN"]) == set(fa["GISJOIN"]) and (ff["year"] == y).all()
            assert not (out_root / "conus" / "nby" / f"Y{y}" / "features" / "nby_age_factor.csv").exists()
        print("ok county features: nby = mean of NOBUILT, nby_age = f_c x that mean (by hand), strips == whole, other "
              "columns unchanged, nby_age_factor.csv per era")

        for c, v in ((cn, "nby"), (ca, "nbya")):
            train.main(["--config", str(c), "--n-jobs", "1"] + common)
            predict.main(["--config", str(c)] + cutr + common)
            qa = pd.read_csv(out_root / "conus" / v / "qa" / "reallocation_qa.csv")
            assert (qa["rel_diff"] < 1e-6).all() and set(qa["year"]) == set(T.YEARS)
            fi = pd.read_csv(out_root / "conus" / v / "Y2010" / "model" / "feature_importance.csv")
            assert ("nby" if v == "nby" else "nby_age") in fi["feature"].tolist()
        fpath = out_root / "conus" / "nbya" / "Y2010" / "features" / "nby_age_factor.csv"
        good = fpath.read_bytes()
        f = pd.read_csv(fpath)
        f.loc[5, "factor"] += 1e-9
        f.to_csv(fpath, index=False)
        try:
            predict.main(["--config", str(ca), "--years", "2010"] + cutr + common)
            raise AssertionError("a changed factor did not stop predict")
        except SystemExit as e:
            assert "differ" in str(e), e
        fpath.unlink()
        try:
            predict.main(["--config", str(ca), "--years", "2010"] + cutr + common)
            raise AssertionError("a missing factor file did not stop predict")
        except SystemExit as e:
            assert "not found" in str(e), e
        fpath.write_bytes(good)
        print("ok train + predict nby / nby_age: mass preserved; a changed (1e-9) or missing factor file stops predict")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- compare

def test_cell_sums():
    import nobuilt_compare as nc
    tmp = Path(tempfile.mkdtemp())
    try:
        rng = np.random.default_rng(3)
        H, W = 30, 20
        pop = rng.uniform(0, 50, (H, W)).astype("float32")
        pop[:4] = -9999.0
        bui = rng.integers(0, 3, (H, W)).astype("float32")
        bui[10, :5] = np.nan                                   # BUI nodata = 0
        nb = rng.integers(0, 3, (H, W)).astype("int32")
        T.write_tif(tmp / "pop.tif", pop, -9999.0)
        T.write_tif(tmp / "bui.tif", bui, float("nan"))
        T.write_tif(tmp / "nb.tif", nb)
        s = nc.cell_sums(tmp / "pop.tif", tmp / "bui.tif", tmp / "nb.tif", block_rows=7)
        ok = pop != -9999.0
        p = pop.astype("float64")
        b0 = ok & ~(bui > 0)
        assert s["cells"] == ok.sum() and s["cells_bui0"] == b0.sum() and s["cells_bui0_nb"] == (b0 & (nb > 0)).sum()
        assert np.isclose(s["share_bui0"], p[b0].sum() / p[ok].sum(), rtol=1e-12)
        assert np.isclose(s["share_nb_of_bui0"], p[b0 & (nb > 0)].sum() / p[b0].sum(), rtol=1e-12)
        assert np.isclose(s["share_bui0_nb"], p[b0 & (nb > 0)].sum() / p[ok].sum(), rtol=1e-12)
        assert s == nc.cell_sums(tmp / "pop.tif", tmp / "bui.tif", tmp / "nb.tif", block_rows=1000)
        print("ok cell sums by hand (NoData left out, BUI nodata = 0), strips == whole")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_city():
    import nobuilt_compare as nc
    import rasterio
    import test_external_city_meeting as TM
    tmp = Path(tempfile.mkdtemp())
    try:
        stub = sys.modules.pop("plots", None)   # the meeting figures need the real plots module
        try:
            TM.test_end_to_end(tmp)   # synthetic world + the meeting gap table (gap_blocks.csv)
        finally:
            if stub is not None:
                sys.modules["plots"] = stub
        ghs = tmp / "data" / "ghs"   # its last step removes the 1980 grid (--check); written back as it was (2010 x 0.7)
        with rasterio.open(ghs / "ghs_2010.tif") as src:
            prof, a = src.profile, src.read(1)
        with rasterio.open(ghs / "ghs_1980.tif", "w", **prof) as dst:
            dst.write(np.where(a == prof["nodata"], a, a * 0.7), 1)
        cfgp, dasym = tmp / "ext.yaml", tmp / "dasym"
        pred = dasym / "conus" / "V56" / "predictions"
        for v, fill in (("V56_nby", 300.0), ("V56_nbya", None)):   # nby fills v5.6's empty core; nbya = v5.6
            d = dasym / "conus" / v / "predictions"
            d.mkdir(parents=True)
            for y in (1980, 2010):
                a = T.read(pred / f"pop_{y}.tif")
                with rasterio.open(pred / f"pop_{y}.tif") as src:
                    prof = src.profile
                if fill is not None and y == 2010:
                    a = a.copy()
                    a[116:132, 116:132] = fill
                with rasterio.open(d / f"pop_{y}.tif", "w", **prof) as dst:
                    dst.write(a, 1)
        ex = tmp / "excluded.csv"
        pd.DataFrame({"GISJOIN": ["G0"]}).to_csv(ex, index=False)
        gap_csv = tmp / "meet" / "gap_blocks.csv"
        args = nc.parse_args(["--base", "V56", "--years", "1980", "2010", "--dasym-root", str(dasym), "--ext-config",
                              str(cfgp), "--data-root", str(tmp / "data"), "--gap-csv", str(gap_csv),
                              "--exclusions", str(ex)])
        versions = {"base": "V56", "nby": "V56_nby", "nbya": "V56_nbya"}
        t = nc.city_table(args, versions).set_index(["city", "year", "variant", "set"])
        gp = pd.read_csv(gap_csv).set_index(["city", "year", "group"])
        for city in ("chicago", "boston"):
            for y in (1980, 2010):
                g = gp.loc[(city, y, "gap")]
                for var in ("base", "nbya"):        # nbya = v5.6: own gap blocks = v5.6's = the meeting table
                    for s in ("gap_own", "gap_v56"):
                        r = t.loc[(city, y, var, s)]
                        assert r["n_blocks"] == g["n_blocks"], (city, y, var, s)
                        assert np.isclose(r["pop_version"], g["pop_v56"], rtol=1e-9, atol=1e-9)
                        assert np.isclose(r["pop_ghs_pop"], g["pop_ghs_pop"], rtol=1e-9)
        # nby 2010 Chicago: the core is filled -> no own gap blocks there; on v5.6's blocks 300 x 16 cells per block
        g = gp.loc[("chicago", 2010, "gap")]
        r = t.loc[("chicago", 2010, "nby", "gap_v56")]
        assert r["n_blocks"] == g["n_blocks"] >= 4
        from pyproj import Transformer
        cx, cy = Transformer.from_crs("EPSG:4326", TM.OUR, always_xy=True).transform(-87.6298, 41.8781)
        with rasterio.open(pred / "pop_2010.tif") as src:
            p0, gt = src.read(1).astype("float64"), src.transform
        rows, _, _, _, _ = TM.by_hand_gap(p0, np.zeros_like(p0), np.zeros_like(p0), tmp / "data" / "ghs" / "ghs_2010.tif",
                                          gt, pred / "pop_2010.tif", cx, cy)
        win = TM.ecm.box_window(gt, cx, cy, 12)
        pn = T.read(dasym / "conus" / "V56_nby" / "predictions" / "pop_2010.tif").astype("float32").astype("float64")
        pn = pn[int(win.row_off):int(win.row_off) + 48, int(win.col_off):int(win.col_off) + 48]
        assert len(rows["gap"]) == g["n_blocks"]
        assert np.isclose(r["pop_version"], sum(pn[sl].sum() for sl in rows["gap"]), rtol=1e-9)
        assert r["pop_version"] > 10 * g["pop_v56"]
        assert np.isclose(r["ratio"], r["pop_version"] / g["pop_ghs_pop"])
        assert t.loc[("chicago", 2010, "nby", "gap_own"), "n_blocks"] < g["n_blocks"]
        # a changed meeting table stops the run
        bad = pd.read_csv(gap_csv)
        bad.loc[(bad["city"] == "chicago") & (bad["year"] == 2010) & (bad["group"] == "gap"), "pop_v56"] += 1.0
        bad.to_csv(tmp / "bad_gap.csv", index=False)
        args.gap_csv = tmp / "bad_gap.csv"
        try:
            nc.city_table(args, versions)
            raise AssertionError("a changed meeting gap table did not stop the run")
        except SystemExit as e:
            assert "pop_v56 differs" in str(e), e
        print("ok city gap blocks: v5.6 = the meeting table, a variant = v5.6 gives the same blocks, filled core -> fewer "
              "own gap blocks, on v5.6's blocks by hand; a changed meeting table stops")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_compare():
    tmp = Path(tempfile.mkdtemp())
    try:
        base = "Dasy_CONUS_RF_v3_u070"
        versions = {base: 1.0, f"{base}_nby": 0.9, f"{base}_nbya": 1.1}
        years = [1910, 2010]
        tracts, err = TP.write_results(tmp, versions, years, np.random.default_rng(1))
        for v in versions:
            fe = ["bui", "elev"] + (["nby"] if v.endswith("_nby") else ["nby_age"] if v.endswith("_nbya") else [])
            for y in years:
                e = tmp / "dasymetric" / "conus" / v / f"Y{y}"
                perm = np.linspace(1, 0.1, len(fe))
                pd.DataFrame({"feature": fe, "permutation_mean": perm}).to_csv(e / "feature_importance.csv", index=False)
                pd.DataFrame({"feature": fe, "mean_abs_shap": perm[::-1]}).to_csv(e / "shap_importance.csv", index=False)
        out = tmp / "out"
        out.mkdir()
        cells = pd.DataFrame([{"version": v, "variant": "base" if v == base else v.rsplit("_", 1)[1], "year": y,
                               "cells": 100, "share_bui0": 0.05 * f, "share_nb_of_bui0": 0.4 * f,
                               "share_bui0_nb": 0.02 * f * f} for v, f in versions.items() for y in years])
        cells.to_csv(out / "nobuilt_cells.csv", index=False)
        city = pd.DataFrame([{"city": "denver", "year": 2010, "version": v,
                              "variant": "base" if v == base else v.rsplit("_", 1)[1], "set": s, "n_blocks": 7,
                              "pop_version": 100 * f, "pop_ghs_pop": 1000.0, "ratio": 0.1 * f}
                             for v, f in versions.items() for s in ("gap_own", "gap_v56")])
        city.to_csv(out / "nobuilt_city_gaps.csv", index=False)
        ex = tmp / "excluded.csv"
        pd.DataFrame({"GISJOIN": ["G003", "G004"]}).to_csv(ex, index=False)
        args = ["--results-root", str(tmp), "--exclusions", str(ex), "--out-dir", str(out), "--years", "1910", "2010"]
        r = subprocess.run([sys.executable, str(REPO / "src" / "validation" / "nobuilt_compare.py"), *args],
                           capture_output=True, text=True, cwd=REPO)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        assert "SUMMARY tract MdAPE" in r.stdout and "SUMMARY city gap blocks" in r.stdout
        cmp = pd.read_csv(out / "nobuilt_comparison.csv")
        for var, f in (("base", 1.0), ("nby", 0.9), ("nbya", 1.1), ("areal_weighting", 2.0)):
            a = cmp[(cmp["variant"] == var) & (cmp["level"] == "tract") & (cmp["set"] == "all") & (cmp["year"] == 2010)]
            assert np.isclose(a["mdape"].iloc[0], 100 * np.median(np.abs(f * err))), var
        assert set(cmp.loc[cmp["level"] == "tract", "set"]) >= {"all", "kept_t070", "excluded_t070", "gap", "no_gap",
                                                                "dens_0_50", "dens_2000_plus"}
        c = cmp[(cmp["level"] == "county") & (cmp["year"] == 1910)].set_index("variant")
        assert c.at["nby", "nby_perm_rank"] == 3 and c.at["nby", "nby_shap_rank"] == 1
        assert c.at["nbya", "nby_age_perm_rank"] == 3 and np.isnan(c.at["nbya", "nby_perm_rank"])
        assert np.isclose(c.at["nby", "cv_rmse"], 0.36)
        ce = cmp[(cmp["level"] == "cells") & (cmp["year"] == 2010)].set_index(["variant", "set"])["share"]
        assert np.isclose(ce[("nbya", "share_bui0")], 0.055) and np.isclose(ce[("base", "share_nb_of_bui0")], 0.4)
        cg = cmp[cmp["level"] == "city_gap"].set_index(["variant", "set"])
        assert cg.at[("nby", "gap_v56"), "city"] == "denver" and np.isclose(cg.at[("nby", "gap_v56"), "share"], 0.09)
        assert cg["d_mdape"].isna().all()
        d = cmp[(cmp["level"] == "tract") & (cmp["set"] == "all") & (cmp["year"] == 2010)].set_index("variant")
        assert np.isclose(d.at["nby", "d_mdape"], d.at["nby", "mdape"] - d.at["base", "mdape"])
        ranks = pd.read_csv(out / "nobuilt_feature_ranks.csv")
        assert set(ranks["feature"]) == {"bui", "elev", "nby", "nby_age"}
        print("ok nobuilt_compare tables: tract / county rows, nby / nby_age ranks, cells + city rows read again, d_mdape")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_configs()
    test_factor()
    test_pipeline()
    test_cell_sums()
    test_city()
    test_compare()
