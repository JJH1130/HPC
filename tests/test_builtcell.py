"""Synthetic test of the built-cell aggregation test (docs/conus_plan.md "Built-cell aggregation test"), runnable without
the cluster:

    python tests/test_builtcell.py      (hisdac env; on Windows with its Library\\bin on PATH, see CLAUDE.md)

Checks:
  - configs: bc3 / bc5 / bc9 = v5.6 (split, exclusions, search ...) + built_local with its window, built-cell means of
    bui / bldg_size / mu_ratio / res_share / rent_share; bad aggregation blocks stop load_config
  - built_local by hand on a small grid (k = 3 and 5): centre, window edge, corner, windows with cells of another
    county, of an unused county, of masked water and outside every county; strips (with halo) == whole window
  - county_features on the synthetic CONUS cutout: without an aggregation block (and with `bui: mean`) the output is
    byte for byte the same; with the bc block: built_local county value = mean of the cell values (exactly, by hand),
    bui ... rent_share = mean over the built cells by hand, a county without a built cell = 0; strips == whole window
  - train + predict with built_local: mass preserved; aggregation_diag on the variant: its county values = the
    features file (built-cell means), pop_share_of_total of the empty cells by hand
  - builtcell_compare on small result files: rows as plural_compare, cell rows from the diag files, built_local rank,
    the window rule (lowest mean CV RMSE, within 0.005 the smaller k), figure
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
BC = ["bui", "bldg_size", "mu_ratio", "res_share", "rent_share"]
V56 = ["bui", "bldg_size", "mu_ratio", "dist_built", "res_share", "rent_share", "elev", "slope"]


def test_configs():
    base = dcommon.load_config(REPO / "configs" / "conus_rf_v3_u070.yaml")
    assert base["aggregation"] == {} and base["built_local"] is None
    for k in (3, 5, 9):
        c = dcommon.load_config(REPO / "configs" / f"conus_rf_v3_u070_bc{k}.yaml")
        assert c["version"] == f"Dasy_CONUS_RF_v3_u070_bc{k}" and c["years"] == [1960, 2010]
        assert c["built_local"] == {"window": k} and c["aggregation"] == {f: "built_mean" for f in BC}
        assert c["compare_with"] == "Dasy_CONUS_RF_v3_u070"
        for e in ("Y1960", "Y2010"):
            assert c["eras"][e]["features"] == base["eras"][e]["features"] + ["built_local"]
        for key in ("split", "exclude_counties", "use_status", "train_status", "water_mask", "block_rows", "unusable",
                    "model", "search", "models", "permutation", "correlation_threshold"):
            assert c[key] == base[key], (k, key)
    tmp = Path(tempfile.mkdtemp())
    try:
        raw = yaml.safe_load((REPO / "configs" / "conus_rf_v3_u070_bc3.yaml").read_text())
        raw["study_area"] = str(REPO / "configs" / "conus_study_area.yaml")
        for bad, msg in (({"built_local": {"window": 4}}, "odd"), ({"built_local": None}, "odd"),
                         ({"bui": "median", "built_local": {"window": 3}}, "method"),
                         ({"ntl": "built_mean", "built_local": {"window": 3}}, "method")):
            p = tmp / "bad.yaml"
            p.write_text(yaml.safe_dump({**raw, "aggregation": bad}))
            try:
                dcommon.load_config(p)
                raise AssertionError(f"{bad} passed")
            except SystemExit as e:
                assert msg in str(e), e
        v = yaml.safe_load((REPO / "configs" / "conus_rf_v3_u070.yaml").read_text())
        v["study_area"] = raw["study_area"]
        p.write_text(yaml.safe_dump({**v, "aggregation": {"built_local": {"window": 3}}}))
        try:
            dcommon.load_config(p)
            raise AssertionError("built_local window without the feature passed")
        except SystemExit as e:
            assert "not used" in str(e), e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ok configs: bc3 / bc5 / bc9 = v5.6 + built_local + built-cell means; bad aggregation blocks stop")


def hand_built_local(study, built, k):
    h = k // 2
    H, W = study.shape
    out = np.zeros((H, W))
    for r in range(H):
        for c in range(W):
            s = study[max(r - h, 0):r + h + 1, max(c - h, 0):c + h + 1]
            b = built[max(r - h, 0):r + h + 1, max(c - h, 0):c + h + 1]
            out[r, c] = (s & b).sum() / s.sum() if s.sum() else 0.0
    return out


def test_built_local():
    tmp = Path(tempfile.mkdtemp())
    try:
        cut = tmp / "cut"
        H, W = 9, 10
        zones = np.zeros((H, W), "uint16")
        zones[:, :5] = 1
        zones[:, 5:] = 2
        zones[7:, :] = 3  # unused county (rows 7-8)
        zones[0, 9] = 0  # outside every county
        bui = np.zeros((H, W), "int32")
        bui[[0, 0, 2, 3, 4, 6, 7, 8, 5, 1], [0, 4, 2, 5, 6, 1, 3, 9, 8, 9]] = 100  # (7, 3), (8, 9): unused county
        wf = np.zeros((H, W), "float32")
        wf[4, 1:4] = 1.0  # masked water (BUI 0)
        wf[2, 2] = 1.0  # water with a building: kept
        T.write_tif(cut / "layers" / "BUI" / "2010_BUI.tif", bui)
        T.write_tif(cut / "layers" / "water_frac" / "2010_water_frac.tif", wf, float("nan"))
        grid = {"transform": T.TRANSFORM, "crs": T.CRS, "shape": (H, W)}
        study = np.isin(zones, [1, 2]) & ~((wf >= 1) & (bui == 0))
        built = bui > 0
        for k in (3, 5):
            spec = {"window": k, "zones": zones, "ids": np.array([1, 2]), "water_mask": "yearly"}
            whole = dcommon.built_local_rows(cut, 2010, grid, spec)
            want = hand_built_local(study, built, k)
            assert np.allclose(whole, want, rtol=0, atol=1e-15), (k, np.argwhere(~np.isclose(whole, want)))
            parts = np.vstack([dcommon.built_local_rows(cut, 2010, grid, spec, r) for r in dcommon.strips((H, W), 2)])
            assert np.array_equal(parts, whole), k
        # by hand, k = 3: corner (0, 0): study cells (0,0) (0,1) (1,0) (1,1), built (0,0) -> 1/4
        spec = {"window": 3, "zones": zones, "ids": np.array([1, 2]), "water_mask": "yearly"}
        w3 = dcommon.built_local_rows(cut, 2010, grid, spec)
        assert w3[0, 0] == 1 / 4
        # (3, 2): window rows 2-4, cols 1-3; masked water (4,1..3) out; (2,2) water with BUI kept + built -> 1/6
        assert np.isclose(w3[3, 2], 1 / 6)
        # (1, 8): (0, 9) outside every county out; (0,8) (0,7) (1,7) (1,9) (2,7..9) + itself = 8 study, built (1, 9) -> 1/8
        assert np.isclose(w3[1, 8], 1 / 8)
        # (6, 3): rows 5-7; row 7 = unused county (its building (7, 3) not counted): 6 study cells, none built -> 0
        assert w3[6, 3] == 0 and w3[6, 2] == 1 / 6  # (6, 1) built
        # (3, 5) next to county 1: window cols 4-6, built (2, 4)? no; (3, 5) and (4, 6) built -> 2/9
        assert np.isclose(w3[3, 5], 2 / 9)
        # no water mask: the water cells count as study cells (empty)
        nw = dcommon.built_local_rows(cut, 2010, grid, {**spec, "water_mask": False})
        assert np.allclose(nw, hand_built_local(np.isin(zones, [1, 2]), built, 3))
        print("ok built_local = by hand (k 3 / 5; corner, edge, other / unused county, outside, masked water, water "
              "with BUI), strips with halo == whole window")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def bc_config(tmp: Path, base: dict, name: str, block_rows, k=3, aggregation=True):
    c = {**base, "version": name, "eras": {f"Y{y}": {"years": [y], "features": V56 + ["built_local"]} for y in T.YEARS},
         "feature_groups": {**base["feature_groups"], "Elevation": ["elev"], "Slope": ["slope"],
                            "Built local": ["built_local"]},
         "aggregation": {**{f: "built_mean" for f in BC}, "built_local": {"window": k}}}
    if not aggregation:
        c.pop("aggregation")
    c.pop("block_rows", None)
    if block_rows:
        c["block_rows"] = block_rows
    p = tmp / "configs" / f"{name}.yaml"
    p.write_text(yaml.safe_dump(c))
    return p


def test_pipeline():
    tmp = Path(tempfile.mkdtemp())
    try:
        counties = T.county_table()
        cut, zones = T.make_cutout(tmp, counties)
        nob = 20  # a county without any building in 2010 (keeps its unmasked cells: water_frac 0 there)
        bui = T.read(cut / "layers" / "BUI" / "2010_BUI.tif")
        bui[zones == nob] = 0
        T.write_tif(cut / "layers" / "BUI" / "2010_BUI.tif", bui)
        wf = T.read(cut / "layers" / "water_frac" / "2010_water_frac.tif")
        wf[zones == nob] = 0
        T.write_tif(cut / "layers" / "water_frac" / "2010_water_frac.tif", wf, float("nan"))
        split = T.make_split.make_split(counties[["GISJOIN", "fips", "state", "name"]], 0.2, 5, 42)
        split_path = tmp / "split.csv"
        split.to_csv(split_path, index=False)
        cfgs = T.write_configs(tmp, split_path)
        base = yaml.safe_load(cfgs["blocks"].read_text())
        out_root = tmp / "dasym"
        common = ["--out-root", str(out_root)]
        cutr = ["--cutout-root", str(tmp / "cutouts")]

        # default aggregation: byte for byte; `bui: mean` too
        t = yaml.safe_load(cfgs["tblocks"].read_text())
        p_mean = tmp / "configs" / "tmean.yaml"
        p_mean.write_text(yaml.safe_dump({**t, "version": "tmean", "aggregation": {"bui": "mean"}}))
        for c in (cfgs["tblocks"], p_mean):
            county_features.main(["--config", str(c)] + cutr + common)
        for y in T.YEARS:
            a = (out_root / "conus" / "tblocks" / f"Y{y}" / "features" / "county_features.csv").read_bytes()
            b = (out_root / "conus" / "tmean" / f"Y{y}" / "features" / "county_features.csv").read_bytes()
            assert a == b, y
        print("ok default aggregation (none / bui: mean): county_features.csv byte for byte")

        c7, cw = bc_config(tmp, base, "bc", 7), bc_config(tmp, base, "bcw", None)
        for c in (c7, cw):
            county_features.main(["--config", str(c)] + cutr + common)
        for y in T.YEARS:
            a = pd.read_csv(out_root / "conus" / "bc" / f"Y{y}" / "features" / "county_features.csv")
            b = pd.read_csv(out_root / "conus" / "bcw" / f"Y{y}" / "features" / "county_features.csv")
            pd.testing.assert_frame_equal(a, b, rtol=1e-12)
            zy, tab, grid = dcommon.read_zones(cut, y)
            usey = tab[tab["status"].isin(base["use_status"]) & (tab["pop"] > 0)]["zone_id"].to_numpy()
            b_ = T.read(cut / "layers" / "BUI" / f"{y}_BUI.tif")
            w_ = T.read(cut / "layers" / "water_frac" / f"{y}_water_frac.tif")
            study = np.isin(zy, usey) & ~((w_ >= 1) & (b_ == 0))
            bl = hand_built_local(study, b_ > 0, 3)
            m = np.isin(zy, usey)
            X = dcommon.cell_features(cut, y, grid, m, BC)
            Xf = {f: np.zeros(zy.shape) for f in BC}
            for f in BC:
                Xf[f][m] = X[f].to_numpy()
            for r in a.itertuples():
                sel = (zy == r.zone_id) & study
                assert np.isclose(r.built_local, bl[sel].mean(), rtol=1e-12), (y, r.zone_id)
                bsel = sel & (b_ > 0)
                for f in BC:
                    want = Xf[f][bsel].mean() if bsel.any() else 0.0
                    assert np.isclose(getattr(r, f), want, rtol=1e-12), (y, r.zone_id, f)
            if y == 2010:
                row = a[a["zone_id"] == nob].iloc[0]
                assert all(row[f] == 0 for f in BC)  # built_local > 0 at its edges (neighbour buildings count)
                assert 0 < row["built_local"] < a["built_local"].median()
        print("ok bc features: built_local county = mean of the cell values (by hand), built-cell means by hand, a county "
              "without a building = 0, strips == whole window")

        train.main(["--config", str(c7), "--n-jobs", "1"] + common)
        predict.main(["--config", str(c7)] + cutr + common)
        qa = pd.read_csv(out_root / "conus" / "bc" / "qa" / "reallocation_qa.csv")
        assert (qa["rel_diff"] < 1e-6).all() and set(qa["year"]) == set(T.YEARS)
        assert "built_local" in pd.read_csv(out_root / "conus" / "bc" / "Y2010" / "model" / "feature_importance.csv")["feature"].tolist()
        print("ok train + predict with built_local: mass preserved")

        import aggregation_diag as ad
        del sys.modules["plots"]  # the diag figure with the real plots module (train / predict keep their stub)
        tdir = tmp / "tracts"
        tdir.mkdir()
        od = tmp / "diag"
        ad.main(["--config", str(c7), "--years", "2010", "--tracts-dir", str(tdir), "--out", str(od)] + cutr + common)
        agg = pd.read_csv(od / "county_aggregates_2010.csv")
        e = pd.read_csv(od / "extrapolation.csv")
        e = e[(e["range"] == "minmax") & (e["feature"] == "all_features")].set_index("subset")
        zy, tab, grid = dcommon.read_zones(cut, 2010)
        usey = tab[tab["status"].isin(base["use_status"]) & (tab["pop"] > 0)]["zone_id"].to_numpy()
        b_ = T.read(cut / "layers" / "BUI" / "2010_BUI.tif")
        w_ = T.read(cut / "layers" / "water_frac" / "2010_water_frac.tif")
        keep = np.isin(zy, usey) & ~((w_ >= 1) & (b_ == 0))
        pop = T.read(out_root / "conus" / "bc" / "predictions" / "pop_2010.tif").astype("float64")
        assert np.isclose(e.at["empty", "pop_share_of_total"], pop[keep & (b_ == 0)].sum() / pop[keep].sum())
        assert e.at["all", "pop_share_of_total"] == 1
        q = pd.read_csv(od / "cell_vs_county_quantiles.csv")
        tr = agg[agg["set"] == "train"]
        qb = q[(q["feature"] == "bui") & (q["sample"] == "counties_train")].iloc[0]
        assert np.isclose(qb["max"], tr["bmean_bui"].fillna(0).max())
        print("ok aggregation_diag on the variant: county values = built-cell means (checked against the features), "
              "people on empty cells by hand")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_compare():
    tmp = Path(tempfile.mkdtemp())
    try:
        base = "Dasy_CONUS_RF_v3_u070"
        versions = {base: 1.0, f"{base}_bc3": 1.01, f"{base}_bc5": 1.0, f"{base}_bc9": 0.99}  # CV RMSE = 0.4 x f
        years = [1960, 2010]
        tracts, err = TP.write_results(tmp, versions, years, np.random.default_rng(1))
        fe = V56 + ["built_local"]
        for v in versions:
            for y in years:
                e = tmp / "dasymetric" / "conus" / v / f"Y{y}"
                perm = np.linspace(1, 0.1, len(fe))
                pd.DataFrame({"feature": fe, "permutation_mean": perm}).to_csv(e / "feature_importance.csv", index=False)
                pd.DataFrame({"feature": fe, "mean_abs_shap": perm[::-1]}).to_csv(e / "shap_importance.csv", index=False)
            d = tmp / "out" / "diag" / ("base" if v == base else v.rsplit("_", 1)[1])
            d.mkdir(parents=True)
            rows = []
            for y in years:
                for s, share in (("all", 1.0), ("built", 0.9), ("empty", 0.1 * versions[v])):
                    rows.append({"year": y, "range": "minmax", "feature": "all_features", "subset": s,
                                 "pop_share_of_total": share, "pop_share_inside": 0.5})
                    rows.append({"year": y, "range": "minmax", "feature": "bui", "subset": s, "pop_share_of_total": share,
                                 "pop_share_below": 0.01, "pop_share_above": 0.2 * versions[v]})
                rows.append({"year": y, "range": "p01_p99", "feature": "bui", "subset": "built",
                             "pop_share_below": 0.5, "pop_share_above": 0.5})
            pd.DataFrame(rows).to_csv(d / "extrapolation.csv", index=False)
        ex = tmp / "excluded.csv"
        pd.DataFrame({"GISJOIN": ["G003", "G004"]}).to_csv(ex, index=False)
        args = ["--results-root", str(tmp), "--exclusions", str(ex), "--out-dir", str(tmp / "out")]
        r = subprocess.run([sys.executable, str(REPO / "src" / "validation" / "builtcell_compare.py"), *args],
                           capture_output=True, text=True, cwd=REPO)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        assert (tmp / "out" / "builtcell_comparison.png").stat().st_size > 10_000
        cmp = pd.read_csv(tmp / "out" / "builtcell_comparison.csv")
        for var, f in (("base", 1.0), ("bc9", 0.99), ("areal_weighting", 2.0)):
            a = cmp[(cmp["variant"] == var) & (cmp["level"] == "tract") & (cmp["set"] == "all") & (cmp["year"] == 2010)]
            assert np.isclose(a["mdape"].iloc[0], 100 * np.median(np.abs(f * err))), var
        c = cmp[(cmp["level"] == "county") & (cmp["variant"] == "bc5") & (cmp["year"] == 1960)].iloc[0]
        assert np.isclose(c["cv_rmse"], 0.4) and c["built_local_perm_rank"] == 9 and c["built_local_shap_rank"] == 1
        ce = cmp[(cmp["level"] == "cells") & (cmp["variant"] == "bc9") & (cmp["year"] == 2010)].set_index("set")["share"]
        assert np.isclose(ce["pop_on_empty"], 0.099) and np.isclose(ce["built_oor_bui"], 0.01 + 0.198)
        assert np.isclose(ce["built_inside_all"], 0.5) and len(ce) == 3
        ranks = pd.read_csv(tmp / "out" / "builtcell_feature_ranks.csv")
        assert len(ranks) == 4 * 2 * len(fe) and set(ranks["perm_rank"]) == set(range(1, len(fe) + 1))
        # rule: bc9 0.396 lowest; bc5 0.400 within 0.005 -> bc5 (smaller); bc3 0.404 outside
        assert (tmp / "out" / "builtcell_choice.txt").read_text().strip() == f"{base}_bc5"
        assert "RULE RESULT: k = 5" in r.stdout, r.stdout[-2000:]
        r2 = subprocess.run([sys.executable, str(REPO / "src" / "validation" / "builtcell_compare.py"), *args,
                             "--tol", "0.001"], capture_output=True, text=True, cwd=REPO)
        assert r2.returncode == 0 and "RULE RESULT: k = 9" in r2.stdout
        print("ok builtcell_compare: tract / county rows, cell rows from the diag files, ranks, rule (bc9 lowest, bc5 "
              "within 0.005 -> k = 5; tol 0.001 -> k = 9), figure")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_configs()
    test_built_local()
    test_pipeline()
    test_compare()
