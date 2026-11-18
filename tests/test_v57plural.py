"""PLURAL on v5.7 (docs/handoff/v57_plural_density_request.md part A; docs/conus_plan.md "PLURAL on v5.7"). Plain
script, no pytest; needs the local hisdac env (see CLAUDE.md).
  test_config    conus_rf_v3_all_nby_<variant>.yaml = v5.7's eras of 1940 / 1980 / 2010 + plural, plural block = the
                 v5.6 test's, every other setting as v5.7; mutations reported; `config` exit codes
  test_features  `features` on synthetic result files: v5.7's columns + plural = the v5.6 test's plural (a county only
                 on one side logged), breaks equal; a changed v5.7 column, plural value or break stops
  test_compare   `compare` on a synthetic world whose earlier tables are written by v54_nby_compare.py and
                 plural_compare.py themselves (the checks pass); all-TEST metrics, d_mdape (vs v5.7) / d_mdape_own,
                 ranks, the CV rule by hand; a changed v5.7 / v5.6 + plural number, a cell row or other folds stop
  test_real      the tracked v5.6 / v5.7 / v5.6 + plural results = v54_nby_comparison.csv / plural_comparison.csv
"""
from __future__ import annotations

import copy
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
sys.path[:0] = [str(REPO / "src" / "validation")]
import v57_plural_compare as vp  # noqa: E402

SCRIPT = str(REPO / "src" / "validation" / "v57_plural_compare.py")
YEARS = [1940, 1980, 2010]


def run(*args, cwd=REPO):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=cwd)


# ---------------------------------------------------------------- config

def test_config():
    v57 = dcommon.load_config(REPO / "configs" / "conus_rf_v3_all_nby.yaml")
    for v in vp.VARIANTS:
        new = dcommon.load_config(REPO / vp.config_path("new", v))
        old = dcommon.load_config(REPO / vp.config_path("old", v))
        assert vp.config_problems(new, v57, old, v, YEARS) == [], v
        assert new["version"] == f"Dasy_CONUS_RF_v3_all_nby_{v}" and new["compare_with"] == "Dasy_CONUS_RF_v3_all_nby"
        assert new["exclude_counties"] is None and new["search"]["n_iter"] == 60 and new["plural"] == old["plural"]
        for e, era in new["eras"].items():
            assert era["features"] == v57["eras"][e]["features"] + ["plural"], (v, e)
            assert "nby" in era["features"]
    new = dcommon.load_config(REPO / vp.config_path("new", "pq3"))
    old = dcommon.load_config(REPO / vp.config_path("old", "pq3"))
    for mut in (lambda c: c["search"].update(n_iter=50), lambda c: c["eras"]["Y1980"]["features"].remove("nby"),
                lambda c: c.update(exclude_counties="x.csv"), lambda c: c["plural"].update(classes=5),
                lambda c: c.update(compare_with="Dasy_CONUS_RF_v3_u070"), lambda c: c["eras"].pop("Y1940"),
                lambda c: c["feature_groups"].pop("PLURAL"), lambda c: c.update(version="x")):
        m = copy.deepcopy(new)
        mut(m)
        assert vp.config_problems(m, v57, old, "pq3", YEARS), mut
    r = run(SCRIPT, "config")
    assert r.returncode == 0 and "CONFIG OK: 6 configs" in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]
    made = []  # in configs/: load_config resolves the study-area path from there
    try:
        for v in vp.VARIANTS:
            p = REPO / "configs" / f"_test_v57plural_{v}.yaml"
            txt = (REPO / vp.config_path("new", v)).read_text()
            p.write_text(txt.replace("n_iter: 60", "n_iter: 30") if v == "pe5" else txt)
            made.append(p)
        r = run(SCRIPT, "config", "--new-pattern", "configs/_test_v57plural_{v}.yaml")
        assert r.returncode == 1 and "CONFIG DIFFERS pe5: search" in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]
        assert "CONFIG DIFFERS pq3" not in r.stdout
    finally:
        for p in made:
            p.unlink(missing_ok=True)
    print("ok config: six configs = v5.7 eras + plural, plural blocks as the v5.6 test; mutations reported, exit codes")


# ---------------------------------------------------------------- features

def feature_world(root: Path, variants, years, rng):
    rd = root / "dasymetric" / "conus"
    ids = [f"G{i:03d}" for i in range(30)]
    for y in years:
        cf = pd.DataFrame({"year": y, "GISJOIN": ids, "status": "ok", "bui": rng.uniform(0, 9, 30),
                           "elev": rng.uniform(0, 900, 30), "nby": rng.uniform(0, 3, 30),
                           "area_km2": rng.uniform(100, 900, 30), "pop": rng.integers(100, 9000, 30) * 1.0})
        d = rd / vp.V57 / f"Y{y}"
        d.mkdir(parents=True, exist_ok=True)
        cf.to_csv(d / "county_features.csv", index=False)
        for v in variants:
            pl = rng.uniform(1, 3, 30) if v in vp.pc.CLASSED else rng.uniform(0, 1, 30)
            new = cf.assign(plural=pl)
            old = cf.drop(columns="nby").assign(plural=pl).iloc[1:]  # the v5.6 test: no nby, one county fewer
            for ver, t in ((f"{vp.V57}_{v}", new), (f"{vp.V56}_{v}", old)):
                e = rd / ver / f"Y{y}"
                e.mkdir(parents=True, exist_ok=True)
                t.to_csv(e / "county_features.csv", index=False)
                if v in vp.pc.CLASSED:
                    pd.DataFrame([{"year": y, "layer": "PLURAL", "breaks": "quantile", "classes": 3,
                                   "study_cells": 1000, "break_1": 0.7 + y * 1e-6, "break_2": 0.82, "share_1": 1 / 3,
                                   "share_2": 1 / 3, "share_3": 1 / 3}]).to_csv(e / "plural_breaks.csv", index=False)


def test_features():
    tmp = Path(tempfile.mkdtemp())
    try:
        variants, years = ["plc", "pq3"], [1940, 2010]
        feature_world(tmp, variants, years, np.random.default_rng(5))
        out = tmp / "out"
        args = ["features", "--results-root", tmp, "--out-dir", out, "--years", *years, "--variants", *variants]
        r = run(SCRIPT, *args)
        assert r.returncode == 0 and "FEATURES OK" in r.stdout, r.stdout[-3000:] + r.stderr[-3000:]
        assert "county sets differ from the v5.6 test: 1 only here" in r.stdout
        chk = pd.read_csv(out / "plural_v57_features_check.csv").set_index(["variant", "year"])
        assert (chk["status"] == "OK").all() and (chk["n_common_v56"] == 29).all() and (chk["feature_cols_equal"] == 7).all()
        assert chk.at[("plc", 1940), "breaks"] == "continuous" and chk.at[("pq3", 2010), "breaks"] == "quantile 3"
        rd = tmp / "dasymetric" / "conus"

        def must_stop(path, edit, why):
            keep = path.read_text()
            t = pd.read_csv(path)
            edit(t)
            t.to_csv(path, index=False)
            rr = run(SCRIPT, *args)
            path.write_text(keep)
            assert rr.returncode != 0 and why in rr.stdout + rr.stderr, (path, (rr.stdout + rr.stderr)[-2000:])
        p = rd / f"{vp.V57}_pq3" / "Y2010" / "county_features.csv"
        must_stop(p, lambda t: t.__setitem__("elev", t["elev"] + (t.index == 4)), "county feature elev differs")
        must_stop(p, lambda t: t.__setitem__("plural", t["plural"] + (t.index == 4) * 1e-6), "FEATURES DIFFER")
        must_stop(p, lambda t: t.drop(columns="bui", inplace=True), "not v5.7's + plural")
        must_stop(rd / f"{vp.V56}_pq3" / "Y1940" / "plural_breaks.csv",
                  lambda t: t.__setitem__("break_2", t["break_2"] + 1e-9), "FEATURES DIFFER")
        must_stop(rd / f"{vp.V56}_pq3" / "Y1940" / "plural_breaks.csv",
                  lambda t: t.__setitem__("study_cells", t["study_cells"] + 1), "FEATURES DIFFER")
        (rd / f"{vp.V57}_plc" / "Y1940" / "plural_breaks.csv").write_text("x\n")
        r = run(SCRIPT, *args)
        assert r.returncode != 0 and "continuous variant" in r.stdout + r.stderr
        (rd / f"{vp.V57}_plc" / "Y1940" / "plural_breaks.csv").unlink()
        r = run(SCRIPT, *args)
        assert r.returncode == 0, r.stdout[-2000:]
        print("ok features: v5.7 columns + plural = the v5.6 test's (common counties), breaks equal; a changed column, "
              "plural, break or study cells stops")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- compare

VARS = ["plc", "pq3"]
V = {"v56": vp.V56, "v56_nby": "Dasy_CONUS_RF_v3_u070_nby", "v54": "Dasy_CONUS_RF_v3_all", "v57": vp.V57,
     **{f"v57_{v}": f"{vp.V57}_{v}" for v in VARS}, **{f"v56_{v}": f"{vp.V56}_{v}" for v in VARS}}
F = {"v56": 1.0, "v56_nby": 0.8, "v54": 1.2, "v57": 0.9, "v57_plc": 0.95, "v57_pq3": 0.85, "v56_plc": 1.05,
     "v56_pq3": 0.97}
CV = {"v56": 0.50, "v56_nby": 0.45, "v54": 0.56, "v57": 0.50, "v57_plc": 0.51, "v57_pq3": 0.48, "v56_plc": 0.49,
      "v56_pq3": 0.52}
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
        feats = ["bui", "elev"] + (["nby"] if lab.startswith("v57") or lab == "v56_nby" else []) + \
                (["plural"] if lab.endswith(tuple(VARS)) else [])
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
            (e / "metrics.json").write_text(json.dumps({"cv_rmse_mean": CV[lab] + y * 1e-5,
                                                        "cv_r2_mean": 0.9 - CV[lab] / 10, "test_rmse": 0.45,
                                                        "test_r2": rep}))
            perm = np.linspace(1, 0.1, len(feats))
            pd.DataFrame({"feature": feats, "permutation_mean": perm}).to_csv(e / "feature_importance.csv", index=False)
            pd.DataFrame({"feature": feats, "mean_abs_shap": perm[::-1]}).to_csv(e / "shap_importance.csv", index=False)
    return cf, noise, test_ids, err


def seed_cells(nb: Path, out: Path, years):
    cells = pd.DataFrame([{"version": v, "variant": lab, "year": y, "cells": 100.0, "cells_bui0": 40.0,
                           "cells_bui0_nb": 10.0, "pop": 1000.0, "pop_bui0": 50 * F[lab], "pop_bui0_nb": 20 * F[lab],
                           "pop_nb": 300.0, "share_bui0": 0.05 * F[lab], "share_nb_of_bui0": 0.4,
                           "share_bui0_nb": 0.02 * F[lab]} for lab, v in V.items() for y in years])
    cells[cells["variant"].isin(["v56", "v56_nby", "v54", "v57"])].replace({"variant": {"v57": "v54_nby"}}).to_csv(
        nb / "v54_nby_cells.csv", index=False)
    cells[~cells["variant"].isin(["v56_nby", "v54"])].to_csv(out / "plural_v57_cells.csv", index=False)


def test_compare():
    tmp = Path(tempfile.mkdtemp())
    try:
        years = [1940, 2010]
        cf, noise, test_ids, err = write_world(tmp, years, np.random.default_rng(3))
        nb, pg, out = tmp / "nobuilt", tmp / "plural_grid", tmp / "out"
        for d in (nb, pg, out):
            d.mkdir()
        ex = tmp / "excluded.csv"
        pd.DataFrame({"GISJOIN": EXCL}).to_csv(ex, index=False)
        seed_cells(nb, out, years)
        ys = [str(y) for y in years]
        common = ["--results-root", str(tmp), "--exclusions", str(ex), "--years", *ys]
        r = run(REPO / "src" / "validation" / "v54_nby_compare.py", *common, "--split", tmp / "split.csv",
                "--out-dir", nb, "--nobuilt-dir", nb)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        r = run(REPO / "src" / "validation" / "plural_compare.py", *common, "--variants", *VARS, "--out-dir", pg)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        args = ["compare", *common, "--variants", *VARS, "--split", tmp / "split.csv", "--out-dir", out,
                "--nobuilt-dir", nb, "--plural-dir", pg]
        r = run(SCRIPT, *args)
        assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
        s = r.stdout
        assert s.count("MATCH") == 4, s[-4000:]  # comparison, plural tracts / county, cells
        assert "RULE: v57_pq3 has the lower county CV RMSE in 2 of 2 years" in s
        assert "RULE: v57_plc has the lower county CV RMSE in 0 of 2 years" in s
        cmp = pd.read_csv(out / "plural_v57_comparison.csv")
        assert set(cmp["variant"]) == {"v57", "v57_plc", "v57_pq3", "v56", "v56_plc", "v56_pq3", "areal_weighting"}
        c = cmp[(cmp["level"] == "county") & (cmp["year"] == 2010)].set_index(["variant", "set"])
        t = cf[cf["GISJOIN"].isin(test_ids)]
        for lab in ("v57", "v57_plc", "v57_pq3", "v56_pq3"):
            for st, m in (("test_all", np.ones(len(t), bool)), ("test_kept_t070", ~t["GISJOIN"].isin(EXCL).to_numpy()),
                          ("test_excluded_t070", t["GISJOIN"].isin(EXCL).to_numpy())):
                o = t["pop"].to_numpy()[m]
                yh = (t["y"] + F[lab] * noise[t.index]).to_numpy()[m]
                ape = np.abs(np.exp(yh) * t["area_km2"].to_numpy()[m] - o) / o * 100
                row = c.loc[(lab, st)]
                assert row["n"] == m.sum() and np.isclose(row["mdape"], np.median(ape)), (lab, st)
                assert np.isclose(row["mape"], ape.mean()) and np.isclose(row["r2"], r2(t["y"].to_numpy()[m], yh))
        a = c.xs("test_all", level="set")
        assert np.isclose(a.at["v57_pq3", "d_mdape"], a.at["v57_pq3", "mdape"] - a.at["v57", "mdape"])
        assert np.isclose(a.at["v56_pq3", "d_mdape_own"], a.at["v56_pq3", "mdape"] - a.at["v56", "mdape"])
        assert a.at["v57_pq3", "plural_perm_rank"] == 4 and a.at["v57_pq3", "nby_perm_rank"] == 3
        assert a.at["v56_plc", "plural_shap_rank"] == 1 and np.isnan(a.at["v56_plc", "nby_perm_rank"])
        assert np.isclose(a.at["v57_plc", "cv_rmse_train_all"], 0.51 + 2010e-5)
        assert np.isclose(a.at["v56_pq3", "cv_rmse_train_kept_t070"], 0.52 + 2010e-5)
        tr = cmp[(cmp["level"] == "tract") & (cmp["set"] == "all") & (cmp["year"] == 2010)].set_index("variant")
        for lab in ("v56", "v57", "v57_plc", "v57_pq3", "v56_plc"):
            assert np.isclose(tr.at[lab, "mdape"], 100 * np.median(np.abs(F[lab] * err))), lab
            assert np.isclose(tr.at[lab, "d_mdape"], tr.at[lab, "mdape"] - tr.at["v57", "mdape"]), lab
            ob = "v57" if lab.startswith("v57") else "v56"
            assert np.isclose(tr.at[lab, "d_mdape_own"], tr.at[lab, "mdape"] - tr.at[ob, "mdape"]), lab
        ce = cmp[(cmp["level"] == "cells") & (cmp["set"] == "share_bui0") & (cmp["year"] == 1940)].set_index("variant")
        assert np.isclose(ce.at["v57_pq3", "share"], 0.05 * 0.85)
        rule = pd.read_csv(out / "plural_v57_cv_rule.csv").set_index(["variant", "year"])
        assert np.isclose(rule.at[("v57_pq3", 1940), "d_cv_rmse"], -0.02) and rule.at[("v57_pq3", 1940), "lower"] == "variant"
        assert rule.at[("v57_plc", 2010), "years_lower"] == 0 and np.isclose(rule.at[("v57_plc", 2010), "mean_d_cv_rmse"], 0.01)
        assert (rule["cv_counties"] == 12).all()
        ranks = pd.read_csv(out / "plural_v57_feature_ranks.csv")
        assert {"plural", "nby"} <= set(ranks["feature"])

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
        must_stop(nb / "v54_nby_comparison.csv", lambda t: bump(t, "v56", "tract", "gap"), "differs from")
        must_stop(pg / "plural_comparison.csv", lambda t: bump(t, "pq3", "tract", "dens_0_50"), "differs from")
        must_stop(pg / "plural_comparison.csv", lambda t: bump(t, "plc", "county", "test", "cv_rmse"), "differs from")
        must_stop(pg / "plural_comparison.csv", lambda t: t.drop(t.index[(t["variant"] == "plc")
                                                                        & (t["level"] == "tract")][:1], inplace=True),
                  "only on one side")
        must_stop(nb / "v54_nby_cells.csv",
                  lambda t: t.__setitem__("pop_bui0", t["pop_bui0"] + (t["variant"] == "v54_nby") * 1.0), "differs from")
        f = tmp / "dasymetric" / "conus" / V["v57_pq3"] / "Y2010" / "folds.csv"
        must_stop(f, lambda t: t.__setitem__("fold", t["fold"][::-1].to_numpy()), "not comparable")
        r = run(SCRIPT, *args)
        assert r.returncode == 0, r.stdout[-2000:]
        print("ok compare: earlier tables written by v54_nby_compare / plural_compare match, all-TEST metrics, "
              "d_mdape / d_mdape_own, ranks, cells, CV rule by hand; changed / missing rows and other folds stop")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- the tracked numbers

def test_real():
    tmp = Path(tempfile.mkdtemp())
    try:
        r = run(SCRIPT, "compare", "--out-dir", tmp)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        s = r.stdout
        assert "v54_nby_comparison.csv: 99 rows" in s and "plural_comparison.csv: 216 rows" in s, s[-3000:]
        assert "plural_comparison.csv: 21 rows" in s
        cmp = pd.read_csv(tmp / "plural_v57_comparison.csv")
        a = cmp[(cmp["level"] == "county") & (cmp["set"] == "test_all") & (cmp["year"] == 1980)].set_index("variant")
        assert round(a.at["v57", "r2"], 3) == 0.908 and a.at["v57", "n"] == 622
        print("ok real: tracked v5.6 / v5.7 rows = v54_nby_comparison.csv, v5.6 + plural = plural_comparison.csv; "
              "1980 all-TEST R2 v5.7 0.908 on 622 counties")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_config()
    test_features()
    test_compare()
    test_real()
