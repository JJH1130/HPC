"""Synthetic test of the county feature aggregation diagnosis (src/validation/aggregation_diag.py; docs/conus_plan.md
"County feature aggregation: diagnosis"), runnable without the cluster:

    python tests/test_aggregation_diag.py      (hisdac env; on Windows with its Library\\bin on PATH, see CLAUDE.md)

On the synthetic CONUS cutout of tests/test_conus_dasymetric.py (48 counties, 1960 / 2010, water mask, terrain), run
through county_features / train / predict with an exclusion list, checks:
  - top_share / gini on small arrays by hand (k = ceil(n / 10) without float error)
  - mean_<f> = county_features.csv (and a changed county_features.csv stops the job)
  - built_share, bmean / bmed (BUI > 0 cells), med (all cells), top10_share, gini_bui = brute force per county
  - set column: train / test (split) / excluded / not_trained (filled_nhgis_alloc)
  - training range = min / max of the training county means; cell and population shares below / above / inside per
    feature and for all features (all / built / empty cells), county out-of-range shares = brute force
  - quantile table (zero share, p50, max) of cells and training county means
  - Spearman rows = pandas on the training counties
  - tract MdAPE per county (>= 5 tracts), its Spearman and quartile table
  - strips (block_rows 7) == whole window; the figure is written (real plots module)
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path[:0] = [str(Path(__file__).resolve().parent)]
import test_conus_dasymetric as T  # noqa: E402  (stubs shap / plots; synthetic cutout + configs)

import yaml  # noqa: E402

import aggregation_diag as ad  # noqa: E402
import common as dcommon  # noqa: E402
import county_features  # noqa: E402
import predict  # noqa: E402
import train  # noqa: E402

FEATS = ["bui", "bldg_size", "mu_ratio", "dist_built", "res_share", "rent_share", "elev", "slope"]


def test_small():
    assert np.isclose(ad.gini(np.array([1.0, 2, 3, 4])), 2 * (1 + 4 + 9 + 16) / 40 - 5 / 4)
    assert np.isclose(ad.gini(np.array([5.0, 5, 5])), 0) and ad.gini(np.array([7.0])) == 0
    assert np.isclose(ad.gini(np.array([0.0, 0, 0, 1])), 0.75)
    x = np.arange(1.0, 31)
    assert np.isclose(ad.top_share(x), (30 + 29 + 28) / x.sum())  # k = 3, not 4 (0.1 x 30 float error)
    assert np.isclose(ad.top_share(np.arange(1.0, 12)), (11 + 10) / 66)  # k = ceil(1.1) = 2
    assert np.isclose(ad.top_share(np.array([4.0])), 1) and np.isnan(ad.top_share(np.array([])))
    print("ok small: gini, top 10 % share by hand")


def config(tmp: Path, base: dict, ex: Path, block_rows):
    c = {**base, "version": "agg", "exclude_counties": str(ex),
         "eras": {f"Y{y}": {"years": [y], "features": FEATS} for y in T.YEARS},
         "feature_groups": {**base["feature_groups"], "Elevation": ["elev"], "Slope": ["slope"]}}
    c.pop("block_rows", None)
    if block_rows:
        c["block_rows"] = block_rows
    p = tmp / "configs" / f"agg_{block_rows}.yaml"
    p.write_text(yaml.safe_dump(c))
    return p


def brute(cut: Path, year: int, base: dict):
    """Kept cells of the used counties: zone, features, pop (whole window, no strips)."""
    zones, table, grid = dcommon.read_zones(cut, year)
    used = dcommon.county_selection(table, zones, base["use_status"], year, "skip")
    m = dcommon.used_mask(zones, used["zone_id"].to_numpy())
    X = dcommon.cell_features(cut, year, grid, m, FEATS)
    wf = T.read(cut / "layers" / "water_frac" / f"{year}_water_frac.tif")[m]
    keep = ~((wf >= 1) & (X["bui"].to_numpy() == 0))
    return zones[m][keep], X[keep].reset_index(drop=True), m, keep


def test_aggregation():
    tmp = Path(tempfile.mkdtemp())
    try:
        counties = T.county_table()
        cut, zones = T.make_cutout(tmp, counties)
        split = T.make_split.make_split(counties[["GISJOIN", "fips", "state", "name"]], 0.2, 5, 42)
        split_path = tmp / "split.csv"
        split.to_csv(split_path, index=False)
        cfgs = T.write_configs(tmp, split_path)
        base = yaml.safe_load(cfgs["blocks"].read_text())
        ex = tmp / "excluded.csv"
        ex_gj = counties["GISJOIN"].iloc[[2, 17, 30]].tolist()
        pd.DataFrame({"GISJOIN": ex_gj, "reasons": "ratio"}).to_csv(ex, index=False)
        c7, cw = config(tmp, base, ex, 7), config(tmp, base, ex, None)
        out_root = tmp / "dasym"
        common = ["--out-root", str(out_root)]
        cutr = ["--cutout-root", str(tmp / "cutouts")]
        county_features.main(["--config", str(c7)] + cutr + common)
        train.main(["--config", str(c7), "--n-jobs", "1"] + common)
        predict.main(["--config", str(c7)] + cutr + common)

        # tract errors: 3-9 tracts in some counties (two counties with < 5)
        rng = np.random.default_rng(5)
        tdir = tmp / "tracts"
        tdir.mkdir()
        for y in T.YEARS:
            rows = []
            for k, gj in enumerate(counties["GISJOIN"].iloc[::2]):
                for i in range(3 + k % 7):
                    obs = float(rng.integers(0 if i == 0 else 50, 5000))
                    rows.append({"GISJOIN": f"{gj}T{i}", "zone_gisjoin": gj, "flag": "ok", "pop_obs": obs,
                                 "pop_model": obs * (1 + rng.normal(0, 0.1 + 0.02 * k)),
                                 "pop_baseline": obs * (1 + rng.normal(0, 0.8))})
            rows.append({"GISJOIN": "X", "zone_gisjoin": None, "flag": "multi_county", "pop_obs": 9.0,
                         "pop_model": 1.0, "pop_baseline": 1.0})
            pd.DataFrame(rows).to_csv(tdir / f"tract_errors_{y}.csv", index=False)

        del sys.modules["plots"]  # the figure with the real plots module (train / predict keep their stub)
        outs = {}
        for name, c in (("strips", c7), ("whole", cw)):
            outs[name] = tmp / f"out_{name}"
            ad.main(["--config", str(c), "--years", "1960", "2010", "--tracts-dir", str(tdir),
                     "--out", str(outs[name])] + cutr + common)
        a, b = outs["strips"], outs["whole"]
        for f in ["county_aggregates_1960.csv", "county_aggregates_2010.csv", "extrapolation.csv",
                  "cell_vs_county_quantiles.csv", "aggregate_correlations.csv", "tract_error_by_county_2010.csv",
                  "aggregate_vs_tract_error.csv"]:
            pd.testing.assert_frame_equal(pd.read_csv(a / f), pd.read_csv(b / f), rtol=1e-12)
        assert (a / "cell_vs_county_2010.png").stat().st_size > 10_000
        print("ok strips == whole window (7 files), figure written")

        sp = dict(zip(split["GISJOIN"], split["part"]))
        ext = pd.read_csv(a / "extrapolation.csv")
        for y in T.YEARS:
            agg = pd.read_csv(a / f"county_aggregates_{y}.csv")
            z, X, m, keep = brute(cut, y, base)
            pop = T.read(out_root / "conus" / "agg" / "predictions" / f"pop_{y}.tif")[m][keep].astype("float64")
            zt = pd.read_csv(cut / "zones" / f"zones_{y}.csv").set_index("GISJOIN")
            for r in agg.itertuples():
                zid = zt.at[r.GISJOIN, "zone_id"]
                sel = z == zid
                b_ = sel & (X["bui"].to_numpy() > 0)
                assert r.cells == sel.sum() and r.n_built == b_.sum() and np.isclose(r.built_share, b_.mean() / sel.mean())
                for f in FEATS:
                    v = X[f].to_numpy()
                    assert np.isclose(getattr(r, f"mean_{f}"), v[sel].mean(), rtol=1e-12), (y, f)
                    assert np.isclose(getattr(r, f"med_{f}"), np.median(v[sel].astype("float32")), rtol=1e-6)
                    if f in ad.BUILT_FEATURES:
                        assert np.isclose(getattr(r, f"bmean_{f}"), v[b_].mean(), rtol=1e-12)
                        assert np.isclose(getattr(r, f"bmed_{f}"), np.median(v[b_].astype("float32")), rtol=1e-6)
                bv = np.sort(X["bui"].to_numpy()[b_].astype("float32").astype("float64"))
                k = -(-len(bv) // 10)
                assert np.isclose(r.top10_share, bv[::-1][:k].sum() / bv.sum())
                n = len(bv)
                assert np.isclose(r.gini_bui, 2 * (np.arange(1, n + 1) * bv).sum() / (n * bv.sum()) - (n + 1) / n)
                want = ("not_trained" if r.status not in base["train_status"] else
                        "excluded" if r.GISJOIN in ex_gj else sp[r.GISJOIN])
                assert r.set == want, (r.GISJOIN, r.set, want)
                assert np.isclose(r.pop_alloc, pop[sel].sum(), rtol=1e-9) and np.isclose(r.pop_alloc, r.pop, rtol=1e-5)
            if y == 2010:
                assert set(agg["set"]) == {"train", "test", "excluded", "not_trained"}, agg["set"].value_counts()
            tr = agg[agg["set"] == "train"]
            inside = np.ones(len(z), bool)
            built = X["bui"].to_numpy() > 0
            for f in FEATS:
                lo, hi = tr[f"mean_{f}"].min(), tr[f"mean_{f}"].max()
                v = X[f].to_numpy().astype("float32")
                below, above = v < lo, v > hi
                inside &= ~(below | above)
                e = ext[(ext["year"] == y) & (ext["range"] == "minmax") & (ext["feature"] == f)].set_index("subset")
                assert np.isclose(e.at["all", "lo"], lo) and np.isclose(e.at["all", "hi"], hi)
                assert np.isclose(e.at["all", "cell_share_below"], below.mean())
                assert np.isclose(e.at["built", "cell_share_above"], above[built].mean())
                assert np.isclose(e.at["empty", "pop_share_below"], pop[below & ~built].sum() / pop[~built].sum())
                assert np.isclose(e.at["all", "pop_share_above"], pop[above].sum() / pop.sum())
                lo_p, hi_p = np.quantile(tr[f"mean_{f}"], [0.01, 0.99])
                e = ext[(ext["year"] == y) & (ext["range"] == "p01_p99") & (ext["feature"] == f)].set_index("subset")
                assert np.isclose(e.at["all", "cell_share_above"], (v > hi_p).mean())
            e = ext[(ext["year"] == y) & (ext["range"] == "minmax") & (ext["feature"] == "all_features")].set_index("subset")
            assert np.isclose(e.at["all", "cell_share_inside"], inside.mean())
            assert np.isclose(e.at["built", "pop_share_inside"], pop[inside & built].sum() / pop[built].sum())
            e = ext[(ext["year"] == y) & (ext["range"] == "minmax") & (ext["feature"] == "bui")].set_index("subset")
            assert 0 < e.at["all", "cell_share_inside"] < 1 and e.at["empty", "cell_share_below"] > 0, e
            for r in agg.itertuples():
                sel = z == zt.at[r.GISJOIN, "zone_id"]
                assert np.isclose(r.oor_cell_share, (~inside[sel]).mean())
                assert np.isclose(r.oor_pop_share, pop[sel & ~inside].sum() / pop[sel].sum())
            q = pd.read_csv(a / "cell_vs_county_quantiles.csv")
            q = q[(q["year"] == y) & (q["feature"] == "bui")].set_index("sample")
            bui = X["bui"].to_numpy()
            assert np.isclose(q.at["cells_all", "zero_share"], (bui == 0).mean())
            assert q.at["cells_empty", "max"] == 0 and q.at["cells_built", "zero_share"] == 0
            assert np.isclose(q.at["counties_train", "p50"], tr["mean_bui"].median())
            assert np.isclose(q.at["cells_built", "max"], bui[built].max())
            cor = pd.read_csv(a / "aggregate_correlations.csv")
            cor = cor[cor["year"] == y].set_index(["a", "b"])["rho"]
            assert np.isclose(cor[("mean_bui", "y")], tr["mean_bui"].corr(tr["y"], method="spearman"))
            assert np.isclose(cor[("bmean_bui", "bmed_bui")], tr["bmean_bui"].corr(tr["bmed_bui"], method="spearman"))
        print("ok aggregates = brute force: means (= county_features.csv), built share, built mean / median, all-cell "
              "median, top 10 % share, Gini, sets, out-of-range shares, quantiles, Spearman")

        tc = pd.read_csv(a / "tract_error_by_county_2010.csv")
        t = pd.read_csv(tdir / "tract_errors_2010.csv")
        t = t[t["flag"] == "ok"]
        n = t.groupby("zone_gisjoin").size()
        assert set(tc["GISJOIN"]) == set(n[n >= 5].index) and len(tc) < len(n)
        r = tc.iloc[0]
        d = t[t["zone_gisjoin"] == r["GISJOIN"]]
        d = d[d["pop_obs"] > 0]
        assert np.isclose(r["tract_mdape"], 100 * np.median(np.abs(d["pop_model"] - d["pop_obs"]) / d["pop_obs"]))
        s = pd.read_csv(a / "aggregate_vs_tract_error.csv")
        s = s[s["year"] == 2010]
        rho = s[(s["kind"] == "spearman") & (s["measure"] == "top10_share")]["rho"].iloc[0]
        assert np.isclose(rho, tc["top10_share"].corr(tc["tract_mdape"], method="spearman"))
        qt = s[(s["kind"] == "quartile") & (s["measure"] == "gini_bui")]
        assert qt["counties"].sum() == tc["gini_bui"].notna().sum() and qt["tracts"].sum() == tc.loc[tc["gini_bui"].notna(), "tracts"].sum()
        print("ok tract MdAPE per county (>= 5 tracts), Spearman and quartiles")

        # a changed county_features.csv stops the job
        f = out_root / "conus" / "agg" / "Y2010" / "features" / "county_features.csv"
        cf = pd.read_csv(f)
        cf.loc[0, "slope"] *= 1.001
        cf.to_csv(f, index=False)
        try:
            ad.main(["--config", str(cw), "--years", "2010", "--tracts-dir", str(tdir), "--out", str(tmp / "o3")]
                    + cutr + common)
            raise AssertionError("changed county_features.csv passed")
        except SystemExit as e:
            assert "differ" in str(e), e
        (out_root / "conus" / "agg" / "predictions" / "pop_1960.tif").unlink()
        try:
            ad.main(["--config", str(cw), "--years", "1960", "--out", str(tmp / "o5")] + cutr + common)
            raise AssertionError("missing prediction passed")
        except SystemExit as e:
            assert "missing inputs" in str(e), e
        print("ok stops: changed county_features.csv, missing prediction raster")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_small()
    test_aggregation()
