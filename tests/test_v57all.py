"""v5.7 all years (docs/handoff/v57_all_years_request.md; docs/conus_plan.md "v5.7 all years"). Plain script, no pytest;
needs the local hisdac env (see CLAUDE.md).
  test_config        conus_rf_v3_all_nby.yaml: 13 eras 1900-2020 = v5.4's era of the year + nby, every other setting
                     as v5.4; the five eras run 2026-11-04 byte for byte as they were
  test_kept_years    synthetic pipeline (test_conus_dasymetric's cutout): one year run, snapshot
                     (kept_years_check.py), a second year added with --years: features / train / predict keep the first
                     year's files and CSV rows -> KEPT YEARS OK; a changed QA row, a rewritten prediction, a changed tract
                     row each -> DIFFERS + exit 1; the canonical CSV form ignores an added column / int -> float
  test_all_test      compare_models.py and metrics_over_time.py on synthetic results of three versions (one with the
                     t070-like filter): all TEST counties (test + excluded TEST rows) MdAPE / MAPE / R2 by hand, kept /
                     excluded parts, the own reported TEST R2 next to it, --check-against passes on equal numbers and
                     stops on a changed one; metrics_over_time --compare-with two versions leaves their files as they are
  test_real_numbers  the tracked v5.4 / v5.6 / v5.7 results: compare_models + metrics_over_time --check-against
                     v54_nby_comparison.csv match on the five years (v5.7 1980: all-TEST R2 0.908, tract MdAPE 26.9 %)
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
import test_conus_dasymetric as T  # noqa: E402  (stubs shap / plots; paths; synthetic cutout)

import common as dcommon  # noqa: E402

REPO = T.REPO
sys.path[:0] = [str(REPO / "src" / "validation"), str(REPO / "src" / "dasymetric")]
import kept_years_check as kyc  # noqa: E402

OLD = [1910, 1940, 1960, 1980, 2010]
ALL = list(range(1900, 2021, 10))
# the five era blocks of configs/conus_rf_v3_all_nby.yaml as run 2026-11-04 (commit 306cadf)
OLD_BLOCKS = {
    1910: "  Y1910:\n    years: [1910]\n    features: [bui, bldg_size, mu_ratio, dist_built, elev, slope, nby]\n",
    **{y: f"  Y{y}:\n    years: [{y}]\n    features: [bui, bldg_size, mu_ratio, dist_built, res_share, rent_share, "
          f"elev, slope, nby]\n" for y in (1940, 1960, 1980, 2010)}}


def test_config():
    base = dcommon.load_config(REPO / "configs" / "conus_rf_v3_all.yaml")
    path = REPO / "configs" / "conus_rf_v3_all_nby.yaml"
    c = dcommon.load_config(path)
    assert c["version"] == "Dasy_CONUS_RF_v3_all_nby" and c["years"] == ALL
    assert c["compare_with"] == "Dasy_CONUS_RF_v3_all" and c["exclude_counties"] is None
    assert list(c["eras"]) == [f"Y{y}" for y in ALL] == list(base["eras"])
    for e in c["eras"]:
        assert c["eras"][e]["years"] == base["eras"][e]["years"]
        assert c["eras"][e]["features"] == base["eras"][e]["features"] + ["nby"], e
    assert c["eras"]["Y1930"]["features"][-3:] == ["elev", "slope", "nby"] and "res_share" not in c["eras"]["Y1930"]["features"]
    for key in ("split", "use_status", "train_status", "water_mask", "block_rows", "unusable", "model", "search",
                "models", "permutation", "correlation_threshold", "study_area"):
        assert c[key] == base[key], key
    text = path.read_text()
    for y, block in OLD_BLOCKS.items():  # byte for byte as run
        assert text.count(block) == 1, y
    assert base["version"] == "Dasy_CONUS_RF_v3_all" and all("nby" not in e["features"] for e in base["eras"].values())
    print("ok config: v5.7 = 13 eras 1900-2020 = v5.4's eras + nby, settings as v5.4, the five run eras byte for byte")


# ---------------------------------------------------------------- --years keeps the other years + snapshot check

def check(snap: Path) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(REPO / "src" / "dasymetric" / "kept_years_check.py"), "check", "--json",
                        str(snap)], capture_output=True, text=True, cwd=REPO)
    return r.returncode, r.stdout + r.stderr


def copy_results(v: Path, res: Path, eras):
    """As the sbatch scripts: model/*.json *.csv and features/county_features.csv -> results/<era>/."""
    for e in eras:
        d = res / e
        d.mkdir(parents=True, exist_ok=True)
        for f in list((v / e / "model").glob("*.json")) + list((v / e / "model").glob("*.csv")):
            shutil.copy2(f, d / f.name)
        shutil.copy2(v / e / "features" / "county_features.csv", d / "county_features.csv")


def test_kept_years():
    import yaml
    import county_features
    import make_split
    import predict
    import train
    tmp = Path(tempfile.mkdtemp())
    try:
        counties = T.county_table()
        T.make_cutout(tmp, counties)
        split = make_split.make_split(counties[["GISJOIN", "fips", "state", "name"]], 0.2, 5, 42)
        split.to_csv(tmp / "split.csv", index=False)
        cfgs = T.write_configs(tmp, tmp / "split.csv")
        full = yaml.safe_load(cfgs["blocks"].read_text())
        full.update(version="v57t", years=T.YEARS)
        first = {**full, "years": T.YEARS[:1], "eras": {"Y1960": full["eras"]["Y1960"]}}
        (tmp / "first.yaml").write_text(yaml.safe_dump(first))
        (tmp / "full.yaml").write_text(yaml.safe_dump(full))
        out_root, cut_root = tmp / "dasym", tmp / "cutouts"
        common = ["--out-root", str(out_root)]
        v = out_root / "conus" / "v57t"
        res = tmp / "results" / "dasymetric" / "conus" / "v57t"
        val = tmp / "results" / "validation" / "conus" / "v57t"
        for cfg in ("first",):
            county_features.main(["--config", str(tmp / f"{cfg}.yaml"), "--cutout-root", str(cut_root)] + common)
            train.main(["--config", str(tmp / f"{cfg}.yaml"), "--n-jobs", "1"] + common)
            predict.main(["--config", str(tmp / f"{cfg}.yaml"), "--cutout-root", str(cut_root)] + common)
        copy_results(v, res, ["Y1960"])
        val.mkdir(parents=True)
        te = pd.DataFrame({"GISJOIN": ["T1", "T2"], "zone_gisjoin": ["G1", "G2"], "flag": "ok", "n_cells": [3, 4],
                           "pop_obs": [10.0, 20.0], "pop_model": [11.0, 19.0], "pop_baseline": [9.0, 25.0]})
        te.to_csv(val / "tract_errors_1960.csv", index=False)
        mby = pd.DataFrame({"year": [1960, 1960], "part": "all", "method": ["model", "baseline"], "subset": "all",
                            "n": 2, "mdape": [7.5, 17.5]})
        mby.to_csv(val / "metrics_by_year.csv", index=False)
        snap = tmp / "logs" / "kept.json"
        kyc.main(["snapshot", "--json", str(snap), "--version-dir", str(v), "--results-dir", str(res),
                  "--validation-dir", str(val), "--years", "1960"])
        items = json.loads(snap.read_text())["items"]
        assert {"1960 scratch metrics.json", "1960 scratch rf.joblib", "1960 scratch pop_1960.tif",
                "1960 cv_summary.csv rows", "1960 reallocation_qa.csv rows", "1960 tract_errors_1960.csv",
                "1960 results Y1960/metrics.json", "1960 results Y1960/county_features.csv"} <= set(items), set(items)
        assert items["1960 reallocation_qa.csv rows"]["n"] == 47
        # the second year with --years (as v57all: features / train / predict), then the results copy + validation
        for step, extra in ((county_features, ["--cutout-root", str(cut_root)]), (train, ["--n-jobs", "1"]),
                            (predict, ["--cutout-root", str(cut_root)])):
            step.main(["--config", str(tmp / "full.yaml"), "--years", "2010"] + extra + common)
        assert (v / "Y2010" / "model" / "rf.joblib").exists() and (v / "predictions" / "pop_2010.tif").exists()
        copy_results(v, res, ["Y1960", "Y2010"])
        te.to_csv(val / "tract_errors_1960.csv", index=False)                       # validation rerun: same rows
        pd.concat([mby, mby.assign(year=2010, mdape=[5.0, 9.0])]).assign(extra=1).to_csv(val / "metrics_by_year.csv",
                                                                                          index=False)
        qa = pd.read_csv(v / "qa" / "reallocation_qa.csv")
        assert set(qa["year"]) == {1960, 2010}
        code, txt = check(snap)
        assert code == 0 and f"KEPT YEARS OK: {len(items)} items" in txt and "DIFFERS" not in txt, txt[-3000:]
        print("ok --years: a second year added, the first year's model / features / prediction / CSV rows kept "
              "(KEPT YEARS OK)")
        # a changed kept row, a rewritten prediction, a changed tract row: DIFFERS, exit 1
        q = (v / "qa" / "reallocation_qa.csv")
        keep = q.read_bytes()
        bad = qa.copy()
        bad.loc[bad.index[bad["year"] == 1960][0], "pop_cells"] += 1.0
        bad.to_csv(q, index=False)
        code, txt = check(snap)
        assert code == 1 and "DIFFERS 1960 reallocation_qa.csv rows" in txt and "KEPT YEARS DIFFERS: 1 of" in txt, txt
        q.write_bytes(keep)
        p = v / "predictions" / "pop_1960.tif"
        p.write_bytes(p.read_bytes())                                               # same bytes, rewritten
        code, txt = check(snap)
        assert code == 1 and "DIFFERS 1960 scratch pop_1960.tif" in txt, txt
        te.assign(pop_model=[11.0, 19.5]).to_csv(val / "tract_errors_1960.csv", index=False)
        code, txt = check(snap)
        assert code == 1 and "DIFFERS 1960 tract_errors_1960.csv" in txt, txt
        # canonical form: an added column / int -> float is not a change, a value is
        df = pd.DataFrame({"year": [1960, 1960], "n": [1, 2], "s": ["a", "b"]})
        h = kyc.canonical(df, ["year", "n", "s"])
        assert kyc.canonical(df.assign(n=df["n"].astype(float), new=3)[::-1], ["year", "n", "s"]) == h
        assert kyc.canonical(df.assign(n=[1, 3]), ["year", "n", "s"]) != h
        print("ok kept_years_check: changed QA row / rewritten prediction / changed tract row -> DIFFERS + exit 1; "
              "added column and int -> float are not changes")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- all TEST counties in the summaries

V = {"v57": "Dasy_CONUS_RF_v3_all_nby", "v54": "Dasy_CONUS_RF_v3_all", "v56": "Dasy_CONUS_RF_v3_u070"}
F = {"v57": 0.7, "v54": 1.2, "v56": 1.0}
EXCL = ["G003", "G004", "G010"]
YEARS = [1910, 2010]


def r2(o, p):
    return 1 - ((p - o) ** 2).sum() / ((o - o.mean()) ** 2).sum()


def mdape(o, p):
    pos = o > 0
    return float(np.median(np.abs(p[pos] - o[pos]) / o[pos]) * 100)


def write_world(root: Path, rng):
    """Result files of three versions (v56 filtered: EXCL out of its own TEST / CV), 20 counties, TEST = G000-G007."""
    ids = [f"G{i:03d}" for i in range(20)]
    test_ids = ids[:8]
    pop = rng.integers(1000, 9000, 20) * 1.0
    area = rng.uniform(50, 500, 20)
    noise = rng.normal(0, 0.4, 20)
    n_t = 200
    tr = pd.DataFrame({"GISJOIN": [f"T{i:04d}" for i in range(n_t)], "zone_gisjoin": [ids[i % 20] for i in range(n_t)],
                       "n_cells": rng.integers(1, 200, n_t), "pop_obs": rng.integers(5, 6000, n_t).astype(float)})
    err = rng.normal(0, 0.3, n_t)
    world = {}
    for lab, v in V.items():
        f, filt = F[lab], lab == "v56"
        vd, dd = root / "validation" / "conus" / v, root / "dasymetric" / "conus" / v
        vd.mkdir(parents=True, exist_ok=True)
        met_rows, cvs = [], []
        for y in YEARS:
            cf = pd.DataFrame({"GISJOIN": ids, "state": "S", "name": [f"c{i}" for i in range(20)], "year": y,
                               "pop": pop * (1 + (y - 1900) / 100), "area_km2": area})
            cf["y"] = np.log(cf["pop"] / cf["area_km2"])
            e = dd / f"Y{y}"
            e.mkdir(parents=True, exist_ok=True)
            cf.to_csv(e / "county_features.csv", index=False)
            pred = cf.assign(y_hat=cf["y"] + f * noise)
            test = pred[pred["GISJOIN"].isin(test_ids)]
            own = test[~test["GISJOIN"].isin(EXCL)] if filt else test
            own[["GISJOIN", "state", "name", "year", "y", "y_hat"]].to_csv(e / "test_predictions.csv", index=False)
            if filt:
                ex = pred[pred["GISJOIN"].isin(EXCL)].assign(
                    part=lambda t: np.where(t["GISJOIN"].isin(test_ids), "test", "train"))
                ex[["GISJOIN", "state", "name", "year", "y", "y_hat", "part"]].to_csv(e / "excluded_predictions.csv",
                                                                                     index=False)
            trn = pred[~pred["GISJOIN"].isin(test_ids) & ~(filt & pred["GISJOIN"].isin(EXCL))]
            trn.assign(oof=trn["y"] + 0.5 * f * noise[trn.index])[["GISJOIN", "year", "y", "oof"]] \
                .to_csv(e / "oof_predictions.csv", index=False)
            oo = trn["y"].to_numpy()
            (e / "metrics.json").write_text(json.dumps({
                "model": "rf", "cv_rmse_mean": 0.4 * f, "cv_r2_mean": 0.9 - 0.01 * f, "test_rmse": 0.45,
                "test_r2": r2(own["y"].to_numpy(), own["y_hat"].to_numpy()), "n_rows": len(trn),
                "oof_pooled_r2": r2(oo, oo + 0.5 * f * noise[trn.index]), "best_params": {"n_estimators": 10}}))
            cvs.append({"era": f"Y{y}", "years": f"{y}-{y}"})
            t = tr.assign(flag="ok", pop_model=tr["pop_obs"] * (1 + f * err), pop_baseline=tr["pop_obs"] * (1 + 2 * err))
            t.to_csv(vd / f"tract_errors_{y}.csv", index=False)
            o = t["pop_obs"].to_numpy()
            for method, col in (("model", "pop_model"), ("baseline", "pop_baseline")):
                met_rows.append({"year": y, "part": "all", "method": method, "subset": "all", "n": len(t),
                                 "mdape": mdape(o, t[col].to_numpy()), "mae": 1.0, "r2_log": 0.5})
        pd.DataFrame(cvs).to_csv(dd / "cv_summary.csv", index=False)
        pd.DataFrame(met_rows).to_csv(vd / "metrics_by_year.csv", index=False)
        world[lab] = noise
    return pop, area, noise, test_ids, tr, err


def by_hand(lab, y, pop, area, noise, test_ids, sel):
    """MdAPE, MAPE, R2 of version `lab` on the TEST counties `sel` (bool over test_ids)."""
    i = np.arange(8)[sel]
    p = pop[i] * (1 + (y - 1900) / 100)
    yy = np.log(p / area[i])
    yh = yy + F[lab] * noise[i]
    est = np.exp(yh) * area[i]
    ape = np.abs(est - p) / p * 100
    return float(np.median(ape)), float(ape.mean()), float(r2(yy, yh))


def test_all_test():
    import compare_models
    tmp = Path(tempfile.mkdtemp())
    try:
        pop, area, noise, test_ids, tr, err = write_world(tmp, np.random.default_rng(11))
        ex = tmp / "excluded_counties_t070.csv"
        pd.DataFrame({"GISJOIN": EXCL}).to_csv(ex, index=False)
        inside = np.isin(test_ids, EXCL)
        sets = {"test_all": np.ones(8, bool), "test_kept_t070": ~inside, "test_excluded_t070": inside}
        # the comparison table (as v54_nby_comparison.csv) from the numbers by hand
        cmp_rows = []
        for lab, v in V.items():
            for y in YEARS:
                for s, m in sets.items():
                    md, mp, rr = by_hand(lab, y, pop, area, noise, test_ids, m)
                    cmp_rows.append({"version": v, "year": y, "level": "county", "set": s, "mdape": md, "mape": mp,
                                     "r2": rr})
                cmp_rows.append({"version": v, "year": y, "level": "tract", "set": "all",
                                 "mdape": 100 * np.median(np.abs(F[lab] * err)), "mape": np.nan, "r2": np.nan})
        ref = tmp / "v54_nby_comparison.csv"
        pd.DataFrame(cmp_rows).to_csv(ref, index=False)
        out = tmp / "validation" / "conus" / V["v57"]
        args = ["--versions", *V.values(), "--exclusions", str(ex), "--results-root", str(tmp), "--out",
                str(out / "summary_by_year.csv"), "--plot", str(out / "mdape_by_year.png")]
        compare_models.main(args + ["--check-against", str(ref)])
        s = pd.read_csv(out / "summary_by_year.csv").set_index(["version", "year"])
        for lab, v in V.items():
            for y in YEARS:
                r = s.loc[(v, y)]
                for st, m in sets.items():
                    md, mp, rr = by_hand(lab, y, pop, area, noise, test_ids, m)
                    assert r[f"{st}_n"] == m.sum() and np.isclose(r[f"{st}_mdape"], md), (lab, y, st)
                    assert np.isclose(r[f"{st}_mape"], mp) and np.isclose(r[f"{st}_r2"], rr), (lab, y, st)
                own = sets["test_kept_t070"] if lab == "v56" else sets["test_all"]
                assert np.isclose(r["test_r2"], by_hand(lab, y, pop, area, noise, test_ids, own)[2])  # own reported
                assert bool(r["filtered"]) == (lab == "v56")
        assert s.loc[(V["v56"], 2010), "test_all_n"] == 8 and not np.isclose(s.loc[(V["v56"], 2010), "test_r2"],
                                                                              s.loc[(V["v56"], 2010), "test_all_r2"])
        assert (out / "mdape_by_year.png").stat().st_size > 10_000
        bad = pd.DataFrame(cmp_rows)
        bad.loc[(bad["version"] == V["v56"]) & (bad["set"] == "test_all") & (bad["year"] == 2010), "r2"] += 1e-6
        bad.to_csv(tmp / "bad.csv", index=False)
        try:
            compare_models.main(args + ["--check-against", str(tmp / "bad.csv"), "--out", str(tmp / "x.csv")])
        except SystemExit as e:
            assert "county r2 differs" in str(e) and V["v56"] in str(e), e
        else:
            raise AssertionError("a changed number passed --check-against")
        assert not (tmp / "x.csv").exists()
        print("ok compare_models: all TEST (test + excluded TEST rows) / kept / excluded t070 MdAPE / MAPE / R2 by hand, "
              "own reported TEST R2 next to it, --check-against passes / stops before writing")
        # metrics_over_time: v5.7 with v5.4 and v5.6 compared (fresh interpreter: the real plots module)
        before = {f: f.read_bytes() for v in (V["v54"], V["v56"]) for f in (tmp / "validation" / "conus" / v).iterdir()}
        mot = [sys.executable, str(REPO / "src" / "validation" / "metrics_over_time.py"), "--version", V["v57"],
               "--compare-with", V["v54"], V["v56"], "--exclusions", str(ex), "--results-root", str(tmp),
               "--starts", "1910"]
        r = subprocess.run(mot + ["--check-against", str(ref)], capture_output=True, text=True, cwd=REPO)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        assert r.stdout.count("MATCH v54_nby_comparison.csv") == 6, r.stdout[-3000:]
        for other in (V["v54"], V["v56"]):
            assert f"county TEST MdAPE (%), {V['v57']} minus {other} (all TEST counties" in r.stdout
        cm = pd.read_csv(out / "county_metrics_by_year.csv").set_index(["year", "set"])
        for y in YEARS:
            for st, m in sets.items():
                md, mp, rr = by_hand("v57", y, pop, area, noise, test_ids, m)
                assert np.isclose(cm.loc[(y, st), "mdape"], md) and np.isclose(cm.loc[(y, st), "r2_logdens"], rr)
            assert cm.loc[(y, "test_all"), "r2_same"] == True  # noqa: E712  (no filter: test_all = reported TEST)
        assert (out / "mdape_over_time.png").stat().st_size > 10_000 and (out / "fixed_tract_metrics.csv").exists()
        assert all(f.read_bytes() == b for f, b in before.items())  # the compared versions' files are not written
        r = subprocess.run(mot + ["--check-against", str(tmp / "bad.csv")], capture_output=True, text=True, cwd=REPO)
        assert r.returncode != 0 and "differs" in r.stdout + r.stderr
        print("ok metrics_over_time: all TEST / kept / excluded rows by hand, test_all R2 = reported without a filter, "
              "two compared versions (files untouched), --check-against passes / stops")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_real_numbers():
    """The tracked results: the shared five years must equal v54_nby_comparison.csv (the request's stop rule)."""
    import compare_models
    tmp = Path(tempfile.mkdtemp())
    try:
        for v in V.values():
            for kind in ("dasymetric", "validation"):
                shutil.copytree(REPO / "results" / kind / "conus" / v, tmp / kind / "conus" / v)
        ref = REPO / "results" / "validation" / "conus" / "nobuilt" / "v54_nby_comparison.csv"
        ex = REPO / "results" / "hisdac_uncertainty" / "excluded_counties_t070.csv"
        out = tmp / "s.csv"
        compare_models.main(["--versions", *V.values(), "--exclusions", str(ex), "--results-root", str(tmp), "--out",
                             str(out), "--check-against", str(ref)])
        s = pd.read_csv(out).set_index(["version", "year"])
        r = s.loc[(V["v57"], 1980)]
        assert round(r["test_all_r2"], 3) == 0.908 and round(r["tract_all_mdape"], 1) == 26.9, r[["test_all_r2",
                                                                                                "tract_all_mdape"]]
        assert s.loc[(V["v56"], 1980), "test_all_n"] == s.loc[(V["v54"], 1980), "test_all_n"] == r["test_all_n"]
        print("ok real numbers: v5.4 / v5.6 / v5.7 tracked results = v54_nby_comparison.csv on 1910-2010 (v5.7 1980: "
              "all-TEST R2 0.908, tract MdAPE 26.9 %)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_config()
    test_kept_years()
    test_all_test()
    test_real_numbers()
    print("ALL OK")
