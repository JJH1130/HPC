"""v5.7 with nby_age instead of nby (docs/handoff/v57_nbya_request.md; docs/conus_plan.md "v5.7 with nby_age instead of
nby"). Plain script, no pytest; needs the local hisdac env (see CLAUDE.md).
  test_config   conus_rf_v3_all_nbya.yaml = v5.7's eras of 1910-2010 with nby -> nby_age, every other setting as v5.7,
                nby_age block = conus_rf_v3_u070_nbya.yaml; a changed setting / feature is reported; `config` exit codes
  test_factors  `factors` on synthetic result files: equal factors pass (a county only in one set logged), summary
                quantiles / counts / nby_kept_share by hand; a changed factor, a changed other feature or nby_age !=
                nby x factor stops
  test_compare  `compare` on a synthetic world of six versions whose earlier tables are written by v54_nby_compare.py
                and nobuilt_compare.py themselves (the checks pass); all-TEST metrics, d_mdape vs v5.7, ranks of nby /
                nby_age, the CV rule by hand; a changed v5.7 number, a changed v5.6 + nby_age tract number, a changed
                cell row or other folds stop the run
  test_real     the tracked v5.4 / v5.6 / v5.7 / v5.6 + nby_age results = v54_nby_comparison.csv / nobuilt_comparison.csv
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
sys.path[:0] = [str(REPO / "src" / "validation")]
import v57_nbya_compare as vn  # noqa: E402

SCRIPT = str(REPO / "src" / "validation" / "v57_nbya_compare.py")


def run(*args, cwd=REPO):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=cwd)


# ---------------------------------------------------------------- config

def test_config():
    cfg = {k: dcommon.load_config(REPO / p) for k, p in vn.CONFIGS.items()}
    assert vn.config_problems(cfg["new"], cfg["v57"], cfg["old"], YEARS) == []
    n = cfg["new"]
    assert n["version"] == "Dasy_CONUS_RF_v3_all_nbya" and n["compare_with"] == "Dasy_CONUS_RF_v3_all_nby"
    assert n["exclude_counties"] is None and n["search"]["n_iter"] == 60
    for e, era in n["eras"].items():
        assert era["features"] == ["nby_age" if f == "nby" else f for f in cfg["v57"]["eras"][e]["features"]], e
        assert "nby" not in era["features"] and era["features"][-1] == "nby_age"
    # v5.7 itself unchanged: 13 eras with nby
    assert len(cfg["v57"]["eras"]) == 13 and all("nby" in e["features"] for e in cfg["v57"]["eras"].values())
    # mutations are reported
    import copy
    for mut in (lambda c: c["search"].update(n_iter=50), lambda c: c["eras"]["Y1980"]["features"].append("ntl"),
                lambda c: c["eras"]["Y1940"]["features"].__setitem__(-1, "nby"),
                lambda c: c.update(exclude_counties="x.csv"), lambda c: c.update(nby_age={"bupr_ref": "other.csv"}),
                lambda c: c.update(compare_with="Dasy_CONUS_RF_v3_all"), lambda c: c["eras"].pop("Y1910")):
        m = copy.deepcopy(n)
        mut(m)
        assert vn.config_problems(m, cfg["v57"], cfg["old"], YEARS), mut
    r = run(SCRIPT, "config")
    assert r.returncode == 0 and "CONFIG OK" in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]
    bad = REPO / "configs" / "_test_v57nbya_bad.yaml"  # in configs/: load_config resolves paths from there
    try:
        bad.write_text((REPO / vn.CONFIGS["new"]).read_text().replace("n_iter: 60", "n_iter: 30"))
        r = run(SCRIPT, "config", "--new-config", bad)
        assert r.returncode == 1 and "CONFIG DIFFERS: search" in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]
    finally:
        bad.unlink(missing_ok=True)
    print("ok config: v5.7 eras with nby -> nby_age, settings as v5.7, nby_age block as the NobuiltYear test; "
          "mutations reported, exit codes")


# ---------------------------------------------------------------- factors

def factor_world(root: Path, years, rng):
    """Factor files of the new / old nby_age versions + county features of v5.7 (nby) and the new version (nby_age)."""
    rd = root / "dasymetric" / "conus"
    ids = [f"G{i:03d}" for i in range(30)]
    out = {}
    for y in years:
        bupr_ref = rng.integers(0, 500, 30).astype(float)
        bupr_ref[:2] = 0
        b = np.floor(bupr_ref * rng.uniform(0, 1.2, 30))
        ratio = np.divide(b, bupr_ref, out=np.full(30, np.nan), where=bupr_ref > 0)
        fac = np.where(bupr_ref <= 0, 1.0, np.clip(np.nan_to_num(ratio), 0, 1))
        rule = np.where(bupr_ref <= 0, "bupr_2015_zero", np.where(ratio > 1, "clipped_1", "ratio"))
        ft = pd.DataFrame({"year": y, "zone_id": range(1, 31), "GISJOIN": ids, f"bupr_{y}": b,
                           "bupr_ref_2015": bupr_ref, "ratio": ratio, "factor": fac, "rule": rule})
        cf = pd.DataFrame({"year": y, "GISJOIN": ids, "status": "ok", "bui": rng.uniform(0, 9, 30),
                           "elev": rng.uniform(0, 900, 30), "nby": rng.uniform(0, 3, 30),
                           "area_km2": rng.uniform(100, 900, 30), "pop": rng.integers(100, 9000, 30) * 1.0})
        new_cf = cf.drop(columns="nby").assign(nby_age=cf["nby"] * fac)
        new_cf = new_cf[["year", "GISJOIN", "status", "bui", "elev", "nby_age", "area_km2", "pop"]]
        for v, t in ((vn.VERSIONS[vn.NEW], ft), (vn.VERSIONS[vn.OLD], ft.iloc[1:])):  # old: one county fewer
            d = rd / v / f"Y{y}"
            d.mkdir(parents=True, exist_ok=True)
            t.to_csv(d / "nby_age_factor.csv", index=False)
        for v, t in ((vn.VERSIONS[vn.REF], cf), (vn.VERSIONS[vn.NEW], new_cf)):
            (rd / v / f"Y{y}").mkdir(parents=True, exist_ok=True)
            t.to_csv(rd / v / f"Y{y}" / "county_features.csv", index=False)
        out[y] = (ft, cf)
    return out


def test_factors():
    tmp = Path(tempfile.mkdtemp())
    try:
        years = [1910, 1980]
        w = factor_world(tmp, years, np.random.default_rng(11))
        out = tmp / "out"
        args = ["factors", "--results-root", tmp, "--out-dir", out, "--years", *years]
        r = run(SCRIPT, *args)
        assert r.returncode == 0 and "FACTORS OK" in r.stdout, r.stdout[-3000:] + r.stderr[-3000:]
        assert "county sets differ: 1 only in the new factors" in r.stdout
        chk = pd.read_csv(out / "v57_nbya_factor_check.csv").set_index("year")
        assert (chk["status"] == "OK").all() and (chk["n_common"] == 29).all() and (chk["only_new"] == 1).all()
        fs = pd.read_csv(out / "v57_nbya_factor_summary.csv").set_index(["variant", "year"])
        for y in years:
            ft, cf = w[y]
            f = ft["factor"].to_numpy()
            row = fs.loc[(vn.NEW, y)]
            assert row["counties"] == 30
            assert np.allclose([row["factor_p10"], row["factor_median"], row["factor_p90"]], np.quantile(f, [.1, .5, .9]))
            assert row["n_lt_0_05"] == (f < 0.05).sum() and row["n_lt_0_10"] == (f < 0.1).sum()
            assert row["n_clipped_1"] == (ft["rule"] == "clipped_1").sum() and row["n_bupr_2015_zero"] == 2
            wgt = cf["nby"] * cf["area_km2"]
            assert np.isclose(row["nby_kept_share"], (wgt * f).sum() / wgt.sum())
            assert fs.loc[(vn.OLD, y), "counties"] == 29
        rd = tmp / "dasymetric" / "conus"
        # a changed factor of a common county stops (exit 1, DIFFERS in the check table)
        p = rd / vn.VERSIONS[vn.OLD] / "Y1980" / "nby_age_factor.csv"
        keep = p.read_text()
        t = pd.read_csv(p)
        t.loc[3, "factor"] += 1e-6
        t.to_csv(p, index=False)
        r = run(SCRIPT, *args)
        assert r.returncode == 1 and "FACTORS DIFFER" in r.stdout, r.stdout[-2000:]
        assert pd.read_csv(out / "v57_nbya_factor_check.csv").set_index("year").at[1980, "status"] == "DIFFERS"
        p.write_text(keep)
        # another feature changed / nby_age != nby x factor stops
        p = rd / vn.VERSIONS[vn.NEW] / "Y1910" / "county_features.csv"
        keep = p.read_text()
        for col, delta in (("elev", 1.0), ("nby_age", 0.01)):
            t = pd.read_csv(p)
            t.loc[5, col] += delta
            t.to_csv(p, index=False)
            r = run(SCRIPT, *args)
            assert r.returncode != 0, (col, r.stdout[-2000:])
            assert (col == "elev" and "county feature elev differs" in r.stdout + r.stderr) or \
                   (col == "nby_age" and "FACTORS DIFFER" in r.stdout), (col, r.stdout[-2000:] + r.stderr[-2000:])
            p.write_text(keep)
        r = run(SCRIPT, *args)
        assert r.returncode == 0, r.stdout[-2000:]
        print("ok factors: equal factors on the common counties, summary by hand, changed factor / feature / "
              "nby_age stop")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- compare

V = {"v56": "Dasy_CONUS_RF_v3_u070", "v56_nby": "Dasy_CONUS_RF_v3_u070_nby", "v54": "Dasy_CONUS_RF_v3_all",
     "v57": "Dasy_CONUS_RF_v3_all_nby", "v57_nbya": "Dasy_CONUS_RF_v3_all_nbya", "v56_nbya": "Dasy_CONUS_RF_v3_u070_nbya"}
F = {"v56": 1.0, "v56_nby": 0.8, "v54": 1.2, "v57": 0.9, "v57_nbya": 0.95, "v56_nbya": 0.85}  # error factor
CV = {"v56": 0.50, "v56_nby": 0.45, "v54": 0.56, "v57": 0.50, "v57_nbya": 0.48, "v56_nbya": 0.47}
EXCL = ["G003", "G004", "G010"]


def r2(o, p):
    return 1 - ((p - o) ** 2).sum() / ((o - o.mean()) ** 2).sum()


def write_world(root: Path, years, rng):
    tracts = pd.DataFrame({"GISJOIN": [f"T{i:04d}" for i in range(300)],
                           "zone_gisjoin": [f"G{i % 20:03d}" for i in range(300)],
                           "n_cells": rng.integers(1, 200, 300), "pop_obs": rng.integers(5, 6000, 300).astype(float)})
    tracts["gap"] = tracts["zone_gisjoin"].isin(["G000", "G001"])
    err = rng.normal(0, 0.3, 300)
    cf = pd.DataFrame({"GISJOIN": [f"G{i:03d}" for i in range(20)], "pop": rng.integers(1000, 9000, 20) * 1.0,
                       "area_km2": rng.uniform(50, 500, 20)})
    cf["y"] = np.log(cf["pop"] / cf["area_km2"])
    test_ids = [f"G{i:03d}" for i in range(8)]
    noise = rng.normal(0, 0.4, 20)
    pd.DataFrame({"GISJOIN": cf["GISJOIN"], "part": np.where(cf["GISJOIN"].isin(test_ids), "test", "train"),
                  "fold": 0}).to_csv(root / "split.csv", index=False)
    for lab, v in V.items():
        f = F[lab]
        filt = lab.startswith("v56")
        feat = {"v56_nby": "nby", "v57": "nby", "v57_nbya": "nby_age", "v56_nbya": "nby_age"}.get(lab)
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
            pd.DataFrame({"GISJOIN": train_ids, "fold": [i % 5 for i in range(len(train_ids))]}).to_csv(
                e / "folds.csv", index=False)
            rep = r2(own["y"].to_numpy(), own["y_hat"].to_numpy())
            (e / "metrics.json").write_text(json.dumps({"cv_rmse_mean": CV[lab] + y * 1e-5, "cv_r2_mean": 0.9 - CV[lab] / 10,
                                                        "test_rmse": 0.45, "test_r2": rep}))
            fe = ["bui", "elev"] + ([feat] if feat else [])
            perm = np.linspace(1, 0.1, len(fe))
            pd.DataFrame({"feature": fe, "permutation_mean": perm}).to_csv(e / "feature_importance.csv", index=False)
            pd.DataFrame({"feature": fe, "mean_abs_shap": perm[::-1]}).to_csv(e / "shap_importance.csv", index=False)
    return cf, noise, test_ids, err


def seed_cells_city(nb: Path, out: Path, years):
    """Cell / city rows of every version as earlier runs would have written them (same numbers in every table)."""
    cells = pd.DataFrame([{"version": v, "variant": lab, "year": y, "cells": 100.0, "cells_bui0": 40.0,
                           "cells_bui0_nb": 10.0, "pop": 1000.0, "pop_bui0": 50 * F[lab], "pop_bui0_nb": 20 * F[lab],
                           "pop_nb": 300.0, "share_bui0": 0.05 * F[lab], "share_nb_of_bui0": 0.4,
                           "share_bui0_nb": 0.02 * F[lab]} for lab, v in V.items() for y in years])
    city = pd.DataFrame([{"city": c, "year": y, "version": v, "variant": lab, "set": s, "n_blocks": 7,
                          "pop_version": 100 * F[lab], "pop_ghs_pop": 1000.0, "ratio": 0.1 * F[lab],
                          "mask_diff_cells": 0 if lab.startswith("v56") else 3}
                         for lab, v in V.items() for c in ("denver", "boston") for y in (1980, 2010) if y in years
                         for s in ("gap_own", "gap_v56")])
    pick = lambda t, labs, ren: t[t["variant"].isin(labs)].replace({"variant": ren})  # noqa: E731
    pick(cells, ["v56", "v56_nby", "v54", "v57"], {"v57": "v54_nby"}).to_csv(nb / "v54_nby_cells.csv", index=False)
    pick(city, ["v56", "v56_nby", "v54", "v57"], {"v57": "v54_nby"}).to_csv(nb / "v54_nby_city_gaps.csv", index=False)
    pick(cells, ["v56", "v56_nbya"], {"v56": "base", "v56_nbya": "nbya"}).to_csv(nb / "nobuilt_cells.csv", index=False)
    pick(city, ["v56", "v56_nbya"], {"v56": "base", "v56_nbya": "nbya"}).drop(columns="mask_diff_cells").to_csv(
        nb / "nobuilt_city_gaps.csv", index=False)
    lab5 = {"v56": "v56", "v54": "v54", "v57": "v57", "v57_nbya": "v57_nbya", "v56_nbya": "v56_nbya"}
    pick(cells, list(lab5), {}).to_csv(out / "v57_nbya_cells.csv", index=False)
    pick(city, list(lab5), {}).to_csv(out / "v57_nbya_city_gaps.csv", index=False)


def test_compare():
    tmp = Path(tempfile.mkdtemp())
    try:
        years = [1910, 2010]
        cf, noise, test_ids, err = write_world(tmp, years, np.random.default_rng(3))
        nb, out = tmp / "nobuilt", tmp / "out"
        nb.mkdir()
        out.mkdir()
        ex = tmp / "excluded.csv"
        pd.DataFrame({"GISJOIN": EXCL}).to_csv(ex, index=False)
        seed_cells_city(nb, out, years)
        ys = [str(y) for y in years]
        common = ["--results-root", str(tmp), "--exclusions", str(ex), "--years", *ys]
        # the earlier tables, written by the earlier scripts on this world
        r = run(REPO / "src" / "validation" / "v54_nby_compare.py", *common, "--split", tmp / "split.csv",
                "--out-dir", nb, "--nobuilt-dir", nb)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        r = run(REPO / "src" / "validation" / "nobuilt_compare.py", *common, "--variants", "nbya", "--out-dir", nb)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        args = ["compare", *common, "--split", tmp / "split.csv", "--out-dir", out, "--nobuilt-dir", nb]
        r = run(SCRIPT, *args)
        assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
        s = r.stdout
        assert s.count("MATCH") == 7, s[-4000:]  # comparison, nobuilt tracts / county, cells x 2, city x 2
        assert "SUMMARY county ALL TEST counties" in s and "RULE: v5.7 + nby_age has the lower county CV RMSE in 2 of 2" in s
        cmp = pd.read_csv(out / "v57_nbya_comparison.csv")
        c = cmp[(cmp["level"] == "county") & (cmp["year"] == 2010)].set_index(["variant", "set"])
        t = cf[cf["GISJOIN"].isin(test_ids)]
        for lab in ("v57", "v57_nbya", "v56_nbya"):
            for st, m in (("test_all", np.ones(len(t), bool)), ("test_kept_t070", ~t["GISJOIN"].isin(EXCL).to_numpy()),
                          ("test_excluded_t070", t["GISJOIN"].isin(EXCL).to_numpy())):
                o = t["pop"].to_numpy()[m]
                yh = (t["y"] + F[lab] * noise[t.index]).to_numpy()[m]
                ape = np.abs(np.exp(yh) * t["area_km2"].to_numpy()[m] - o) / o * 100
                row = c.loc[(lab, st)]
                assert row["n"] == m.sum() and np.isclose(row["mdape"], np.median(ape)), (lab, st)
                assert np.isclose(row["mape"], ape.mean()) and np.isclose(row["r2"], r2(t["y"].to_numpy()[m], yh))
            assert np.isclose(c.loc[(lab, "test_all"), "d_mdape"],
                              c.loc[(lab, "test_all"), "mdape"] - c.loc[("v57", "test_all"), "mdape"])
        a = c.xs("test_all", level="set")
        assert a.at["v57_nbya", "nby_age_perm_rank"] == 3 and a.at["v57_nbya", "nby_age_shap_rank"] == 1
        assert np.isnan(a.at["v57_nbya", "nby_perm_rank"]) and a.at["v57", "nby_perm_rank"] == 3
        assert np.isclose(a.at["v57_nbya", "cv_rmse_train_all"], 0.48 + 2010e-5)
        assert np.isclose(a.at["v56_nbya", "cv_rmse_train_kept_t070"], 0.47 + 2010e-5)
        tr = cmp[(cmp["level"] == "tract") & (cmp["set"] == "all") & (cmp["year"] == 2010)].set_index("variant")
        for lab in ("v54", "v56", "v57", "v57_nbya", "v56_nbya"):
            assert np.isclose(tr.at[lab, "mdape"], 100 * np.median(np.abs(F[lab] * err))), lab
            assert np.isclose(tr.at[lab, "d_mdape"], tr.at[lab, "mdape"] - tr.at["v57", "mdape"]), lab
        rule = pd.read_csv(out / "v57_nbya_cv_rule.csv").set_index("year")
        assert np.isclose(rule.at[1910, "d_cv_rmse"], -0.02) and (rule["lower"] == "v57_nbya").all()
        assert (rule["same_cv_set"]).all() and (rule["cv_counties"] == 12).all()
        ranks = pd.read_csv(out / "v57_nbya_feature_ranks.csv")
        assert {"nby", "nby_age"} <= set(ranks["feature"]) and set(ranks["variant"]) == {"v56", "v54", "v57",
                                                                                        "v57_nbya", "v56_nbya"}
        assert set(cmp["variant"]) == {"v56", "v54", "v57", "v57_nbya", "v56_nbya", "areal_weighting"}

        def must_stop(path: Path, edit, why):
            keep = path.read_text()
            t = pd.read_csv(path)
            edit(t)
            t.to_csv(path, index=False)
            rr = run(SCRIPT, *args)
            path.write_text(keep)
            assert rr.returncode != 0 and why in rr.stdout + rr.stderr, (path.name, (rr.stdout + rr.stderr)[-2000:])

        def bump(t, var, level, st, col="mdape"):
            t.loc[(t["variant"] == var) & (t["level"] == level) & (t["set"] == st), col] += 0.5
        must_stop(nb / "v54_nby_comparison.csv", lambda t: bump(t, "v54_nby", "county", "test_all"), "differs from")
        must_stop(nb / "v54_nby_comparison.csv", lambda t: t.drop(t.index[(t["variant"] == "v54")
                                                                          & (t["level"] == "tract")][:1], inplace=True),
                  "only on one side")
        must_stop(nb / "nobuilt_comparison.csv", lambda t: bump(t, "nbya", "tract", "gap"), "differs from")
        must_stop(nb / "nobuilt_comparison.csv", lambda t: bump(t, "nbya", "county", "test", "cv_rmse"), "differs from")
        must_stop(nb / "nobuilt_cells.csv",
                  lambda t: t.__setitem__("pop_bui0", t["pop_bui0"] + (t["variant"] == "nbya") * 1.0), "differs from")
        must_stop(nb / "v54_nby_city_gaps.csv", lambda t: t.__setitem__("ratio", t["ratio"] * 1.01), "differs from")
        f = tmp / "dasymetric" / "conus" / V["v57_nbya"] / "Y2010" / "folds.csv"
        must_stop(f, lambda t: t.__setitem__("fold", t["fold"][::-1].to_numpy()), "not comparable")
        r = run(SCRIPT, *args)
        assert r.returncode == 0, r.stdout[-2000:]
        print("ok compare: earlier tables written by v54_nby_compare / nobuilt_compare match, all-TEST metrics and "
              "d_mdape vs v5.7 by hand, ranks, CV rule; changed / missing rows and other folds stop")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- the tracked numbers

def test_real():
    tmp = Path(tempfile.mkdtemp())
    try:
        r = run(SCRIPT, "compare", "--out-dir", tmp)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        assert "MATCH" in r.stdout and "v54_nby_comparison.csv: 225 rows" in r.stdout, r.stdout[-3000:]
        assert "nobuilt_comparison.csv: 45 rows" in r.stdout and "nobuilt_comparison.csv: 5 rows" in r.stdout
        cmp = pd.read_csv(tmp / "v57_nbya_comparison.csv")
        a = cmp[(cmp["level"] == "county") & (cmp["set"] == "test_all") & (cmp["year"] == 1980)].set_index("variant")
        assert round(a.at["v57", "r2"], 3) == 0.908 and round(a.at["v56_nbya", "r2"], 3) == 0.770
        fs = pd.read_csv(tmp / "v57_nbya_factor_summary.csv").set_index(["variant", "year"])
        assert fs.at[("v56_nbya", 1910), "counties"] == 2940
        print("ok real: tracked v5.4 / v5.6 / v5.7 rows = v54_nby_comparison.csv, v5.6 + nby_age = "
              "nobuilt_comparison.csv; 1980 all-TEST R2 v5.7 0.908, v5.6 + nby_age 0.770")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_config()
    test_factors()
    test_compare()
    test_real()
