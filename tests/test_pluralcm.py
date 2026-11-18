"""PLURAL at county level only (docs/handoff/plural_countymean_request.md; docs/conus_plan.md "PLURAL at county level
only"). Plain script, no pytest; needs the local hisdac env (see CLAUDE.md).
  test_config    the two cm configs = their PLURAL configs + plural cell_value county_mean + model_from; mutations
                 reported; `config` exit codes; load_config rejects a bad cell_value / model_from; features and train
                 refuse a model_from config
  test_world     one synthetic CONUS-like world (tests/test_conus_dasymetric.py cutout + PLURAL + NOBUILT), versions
                 named as the real ones: v5.7 / pq5 / plc trained, pq5cm / plccm predicted from their models.
                 - default cell_value: pop_{YEAR}.tif + reallocation_qa.csv byte for byte = the code before this change
                   (git show REF:src/dasymetric/*.py) and = an explicit `cell_value: cell`
                 - county_mean: every cell's plural = its county's county_features.csv value (constant in a county),
                   predictions = model on those features by hand (mass preserved), strips = whole window; model_from
                   reads the model without changing it (sha256 before / after = model_from.json), writes no model;
                   a changed TEST prediction of the source stops predict; county_plural missing / extra rows
                 - snapshot + model check (hashes; a changed model file is reported)
                 - variance split = brute force; a changed county feature stops it (VARIANCE CHECK)
                 - built contrast = brute force per county (water-masked cells left out); people = the cell pass
  test_compare   `compare` on a synthetic results world whose earlier tables come from v54_nby_compare /
                 plural_compare / v57_plural_compare themselves: cm county rows = the PLURAL version's, tract metrics,
                 d_mdape / d_mdape_orig and the interpretation rule by hand (cell_level / county_level); a changed
                 earlier number, a failed / missing model check or a snapshot mismatch stops
  test_real      the tracked v5.7 / pq5 / plc rows = plural_v57_comparison.csv (135 rows)
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path[:0] = [str(Path(__file__).resolve().parent)]
import test_conus_dasymetric as T  # noqa: E402  (stubs shap / plots; synthetic cutout + configs)

import joblib  # noqa: E402
import yaml  # noqa: E402

import common as dcommon  # noqa: E402
import county_features  # noqa: E402
import predict  # noqa: E402
import train  # noqa: E402

REPO = T.REPO
sys.path[:0] = [str(REPO / "src" / "validation")]
import plural_countymean as pcm  # noqa: E402

SCRIPT = str(REPO / "src" / "validation" / "plural_countymean.py")
REF = "7508b5f"  # the commit before cell_value / model_from (the old predict.py / common.py)
V57, PQ5, PLC = pcm.V57, f"{pcm.V57}_pq5", f"{pcm.V57}_plc"
PQ5CM, PLCCM = f"{PQ5}cm", f"{PLC}cm"


def run(*args, cwd=REPO):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=cwd)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def stops(fn, *args, why=""):
    try:
        fn(*args)
    except SystemExit as e:
        assert why in str(e), (why, str(e))
        return
    raise AssertionError(f"did not stop: {why}")


# ---------------------------------------------------------------- config

def test_config():
    for v in pcm.PAIRS:
        cm = dcommon.load_config(REPO / pcm.config_path(v, True))
        orig = dcommon.load_config(REPO / pcm.config_path(v, False))
        assert pcm.config_problems(cm, orig, v) == [], pcm.config_problems(cm, orig, v)
        assert cm["model_from"] == orig["version"] and cm["plural"]["cell_value"] == "county_mean"
        assert "cell_value" not in orig["plural"] and orig["model_from"] is None
    cm = dcommon.load_config(REPO / pcm.config_path("pq5", True))
    orig = dcommon.load_config(REPO / pcm.config_path("pq5", False))
    for mut in (lambda c: c["search"].update(n_iter=50), lambda c: c["plural"].pop("cell_value"),
                lambda c: c.update(model_from=PLC), lambda c: c.update(compare_with=V57),
                lambda c: c["eras"]["Y1980"]["features"].remove("plural"), lambda c: c.update(version="x"),
                lambda c: c["plural"].update(classes=3), lambda c: c.update(years=[1980, 2010])):
        m = copy.deepcopy(cm)
        mut(m)
        assert pcm.config_problems(m, orig, "pq5"), mut
    r = run(SCRIPT, "config")
    assert r.returncode == 0 and "CONFIG OK: 2 cm configs" in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]
    made = []
    try:
        for v in pcm.PAIRS:  # in configs/: load_config resolves the study-area path from there
            p = REPO / "configs" / f"_test_pluralcm_{v}.yaml"
            txt = (REPO / pcm.config_path(v, True)).read_text()
            p.write_text(txt.replace("cell_value: county_mean", "cell_value: cell") if v == "plc" else txt)
            made.append(p)
        r = run(SCRIPT, "config", "--cm-pattern", "configs/_test_pluralcm_{v}.yaml")
        assert r.returncode == 1 and "CONFIG DIFFERS plccm: plural block" in r.stdout, r.stdout[-2000:]
        assert "CONFIG DIFFERS pq5cm" not in r.stdout
        bad = REPO / "configs" / "_test_pluralcm_bad.yaml"
        made.append(bad)
        for edit, why in ((lambda t: t.replace("cell_value: county_mean", "cell_value: mean"), "cell_value must be"),
                          (lambda t: t.replace(f"model_from: {PQ5}", f"model_from: {PQ5}cm"), "model_from must be")):
            bad.write_text(edit((REPO / pcm.config_path("pq5", True)).read_text()))
            stops(dcommon.load_config, bad, why=why)
        bad.write_text((REPO / pcm.config_path("pq5", True)).read_text())
        for step in (train, county_features):
            stops(step.main, ["--config", str(bad), "--out-root", "x", "--cutout-root", "x"][:4 if step is train else 6],
                  why="is not run for it")
    finally:
        for p in made:
            p.unlink(missing_ok=True)
    print("ok config: cm configs = PLURAL configs + county_mean / model_from; mutations reported, exit codes; bad "
          "cell_value / model_from rejected; features / train refuse model_from")


# ---------------------------------------------------------------- synthetic world

def make_world(tmp: Path):
    counties = T.county_table()
    cut, zones = T.make_cutout(tmp, counties)
    rng = np.random.default_rng(11)
    centre = np.hypot(*np.meshgrid(np.arange(T.W) - 30, np.arange(T.H) - 20))
    pl = np.clip(centre / centre.max() + 0.15 * rng.random((T.H, T.W)), 0, 1).astype("float32")
    for y in T.YEARS:
        T.write_tif(cut / "layers" / "PLURAL" / f"{y}_PLURAL.tif", pl, float("nan"))
    nby = rng.poisson(np.exp(-centre / 20) * 3).astype("int32")
    T.write_tif(cut / "layers" / "NOBUILT" / "NOBUILT.tif", nby)
    split = T.make_split.make_split(counties[["GISJOIN", "fips", "state", "name"]], 0.2, 5, 42)
    split.to_csv(tmp / "split.csv", index=False)
    paths = T.write_configs(tmp, tmp / "split.csv")
    base = yaml.safe_load(paths["blocks"].read_text())
    feats = base["eras"]["Y2010"]["features"] + ["nby"]
    groups = {**base["feature_groups"], "Undated records": ["nby"]}
    cfgs = {}

    def write(version, plural=None, block_rows=7, **extra):
        f = feats + (["plural"] if plural else [])
        c = {**base, "version": version, "block_rows": block_rows,
             "eras": {f"Y{y}": {"years": [y], "features": f} for y in T.YEARS},
             "feature_groups": {**groups, **({"PLURAL": ["plural"]} if plural else {})}, **extra}
        if plural:
            c["plural"] = plural
        if block_rows is None:
            c.pop("block_rows")
        p = tmp / "configs" / f"{version}.yaml"
        p.write_text(yaml.safe_dump(c))
        cfgs[version] = p
    pq5 = {"layer": "PLURAL", "classes": 5, "breaks": "quantile"}
    plc = {"layer": "PLURAL", "classes": None}
    write(V57)
    write(PQ5, pq5)
    write(PLC, plc)
    write(PQ5CM, {**pq5, "cell_value": "county_mean"}, model_from=PQ5, compare_with=PQ5)
    write(PLCCM, {**plc, "cell_value": "county_mean"}, model_from=PLC)
    write(PQ5CM + "_whole", {**pq5, "cell_value": "county_mean"}, block_rows=None, model_from=PQ5)
    write(PQ5 + "_cell", {**pq5, "cell_value": "cell"}, model_from=PQ5)  # explicit default (model_from: same model)
    return cut, zones, pl, nby, cfgs


def cm_by_hand(cut: Path, cfg: dict, model_cfg_version: str, out_root: Path, year: int):
    """Predicted cell people of a county_mean version, rebuilt from the model, its county features and the cutout."""
    era = f"Y{year}"
    src = out_root / "conus" / model_cfg_version / era
    bundle = joblib.load(src / "model" / "rf.joblib")
    zones, table, grid = dcommon.read_zones(cut, year)
    used = dcommon.county_selection(table, zones, bundle["use_status"], year, cfg["unusable"])
    ids = used["zone_id"].to_numpy()
    mask = dcommon.used_mask(zones, ids)
    cf = pd.read_csv(src / "features" / "county_features.csv")
    cf = cf[cf["year"] == year]
    lut = np.zeros(int(zones.max()) + 1)
    lut[cf["zone_id"].to_numpy()] = cf["plural"].to_numpy()
    plural = {"layer": "PLURAL", "inner": None, "county": lut, "zones": zones}
    X = dcommon.cell_features(cut, year, grid, mask, bundle["features"], None, {}, plural)
    z = zones[mask]
    for zid in np.unique(z):  # plural is constant in a county = the county feature
        v = X["plural"].to_numpy()[z == zid]
        assert (v == v[0]).all() and v[0] == lut[zid], zid
    w = np.exp(bundle["model"].predict(X))
    w[dcommon.water_mask(cut, year, grid, mask, cfg["water_mask"])[0]] = 0.0
    ws = np.bincount(z, weights=w, minlength=len(lut))
    pop = np.zeros(len(lut))
    pop[ids] = used["pop"].to_numpy()
    keep = ws[z] > 0
    out = np.full(zones.shape, np.nan)
    vals = np.full(len(z), np.nan)
    vals[keep] = pop[z[keep]] * w[keep] / ws[z[keep]]
    out[mask] = vals
    return out, mask & ~np.isnan(out)


def old_code(tmp: Path) -> Path | None:
    d = tmp / "old_src"
    d.mkdir()
    for f in ("predict.py", "common.py", "models.py", "plots.py"):
        r = subprocess.run(["git", "show", f"{REF}:src/dasymetric/{f}"], capture_output=True, text=True, cwd=REPO)
        if r.returncode:
            return None
        (d / f).write_text(r.stdout, encoding="utf-8")
    return d


def test_world():
    tmp = Path(tempfile.mkdtemp())
    try:
        cut, zones, pl, nby, cfgs = make_world(tmp)
        out_root = tmp / "dasymetric"
        com = ["--out-root", str(out_root)]
        cutr = ["--cutout-root", str(tmp / "cutouts")]
        for v in (V57, PQ5, PLC):
            county_features.main(["--config", str(cfgs[v])] + cutr + com)
            train.main(["--config", str(cfgs[v]), "--n-jobs", "1"] + com)
        models = {(v, y): out_root / "conus" / v / f"Y{y}" / "model" / "rf.joblib" for v in (PQ5, PLC) for y in T.YEARS}
        before = {k: sha(p) for k, p in models.items()}
        for v in (V57, PQ5, PLC, PQ5CM, PLCCM, PQ5CM + "_whole", PQ5 + "_cell"):
            predict.main(["--config", str(cfgs[v])] + cutr + com)
        assert {k: sha(p) for k, p in models.items()} == before, "model files changed"
        vd = {v: out_root / "conus" / v for v in cfgs}

        # default cell_value = the code before the change, byte for byte (and = explicit cell_value: cell)
        old = old_code(tmp)
        assert old is not None, f"git show {REF} failed (needs the repo history)"
        old_root = tmp / "old_out"
        shutil.copytree(vd[PQ5], old_root / "conus" / PQ5, ignore=shutil.ignore_patterns("predictions", "qa", "maps"))
        r = run(old / "predict.py", "--config", cfgs[PQ5], *cutr, "--out-root", old_root)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        for y in T.YEARS:
            a = (vd[PQ5] / "predictions" / f"pop_{y}.tif").read_bytes()
            assert a == (old_root / "conus" / PQ5 / "predictions" / f"pop_{y}.tif").read_bytes(), y
            assert a == (vd[PQ5 + "_cell"] / "predictions" / f"pop_{y}.tif").read_bytes(), y
        assert ((vd[PQ5] / "qa" / "reallocation_qa.csv").read_bytes()
                == (old_root / "conus" / PQ5 / "qa" / "reallocation_qa.csv").read_bytes())
        print(f"ok default: cell_value cell = the code of {REF} byte for byte (pop tifs + reallocation_qa.csv)")

        # county_mean by hand, mass preserved, strips = whole window; no model of its own
        for cmv, src in ((PQ5CM, PQ5), (PLCCM, PLC)):
            assert not (vd[cmv] / f"Y{T.YEARS[0]}" / "model").exists() and not (vd[cmv] / "cv_summary.csv").exists()
            qa = pd.read_csv(vd[cmv] / "qa" / "reallocation_qa.csv")
            assert (qa["rel_diff"] < 1e-6).all()
            cfg = dcommon.load_config(cfgs[cmv])
            for y in T.YEARS:
                info = json.loads((vd[cmv] / f"Y{y}" / "model_from.json").read_text())
                assert info["test_check"] == "OK" and info["model_sha256"] == before[(src, y)], info
                assert info["model_from"] == src and info["test_max_abs_diff"] < 1e-9 and info["cv_summary"]
                assert (info["plural_breaks_sha256"] is not None) == (src == PQ5)
                got = T.read(vd[cmv] / "predictions" / f"pop_{y}.tif").astype("float64")
                ref, m = cm_by_hand(cut, cfg, src, out_root, y)
                assert np.allclose(got[m], ref[m], rtol=1e-5, atol=1e-6), (cmv, y)
                cell = T.read(vd[src] / "predictions" / f"pop_{y}.tif").astype("float64")
                assert not np.allclose(got[m], cell[m], rtol=1e-3), "county_mean = cell values?"
        for y in T.YEARS:
            a = T.read(vd[PQ5CM] / "predictions" / f"pop_{y}.tif")
            b = T.read(vd[PQ5CM + "_whole"] / "predictions" / f"pop_{y}.tif")
            assert np.allclose(a, b, rtol=1e-6, atol=1e-6), y
        print("ok county_mean: cell plural = county value (constant), prediction by hand, mass preserved, strips = "
              "whole window, model files unchanged (sha256 = model_from.json), no model of its own")

        # a source whose TEST predictions do not come from its model stops predict; county_plural rows
        tp = vd[PQ5] / "Y2010" / "model" / "test_predictions.csv"
        keep = tp.read_text()
        t = pd.read_csv(tp)
        t.loc[3, "y_hat"] += 1e-6
        t.to_csv(tp, index=False)
        stops(predict.main, ["--config", str(cfgs[PQ5CM])] + cutr + com, why="not the same model")
        assert json.loads((vd[PQ5CM] / "Y2010" / "model_from.json").read_text())["test_check"] == "DIFFERS"
        tp.write_text(keep)
        predict.main(["--config", str(cfgs[PQ5CM])] + cutr + com)
        cfp = vd[PQ5] / "Y2010" / "features" / "county_features.csv"
        z, table, _ = dcommon.read_zones(cut, 2010)
        used = dcommon.county_selection(table, z, ["ok", "filled_nhgis", "filled_nhgis_alloc"], 2010, "skip")
        spec = {"layer": "PLURAL", "inner": None}
        cf = pd.read_csv(cfp)
        drop = tmp / "cf_drop.csv"
        cf.drop(index=[0]).to_csv(drop, index=False)
        res = predict.county_plural(spec, drop, 2010, z, table, used)
        assert res["missing"] == {int(cf.loc[0, "zone_id"])}
        cf2 = cf.copy()
        cf2.loc[0, "GISJOIN"] = "GXXX"
        cf2.to_csv(drop, index=False)
        stops(predict.county_plural, spec, drop, 2010, z, table, used, why="differ from the cutout's zone table")
        print("ok model_from: a changed source TEST prediction stops predict; county_plural: missing rows listed, "
              "a GISJOIN mismatch stops")

        # results layout (results/dasymetric/conus/<version>/Y<year>/) for the analysis script
        for v in (V57, PQ5, PLC):
            for y in T.YEARS:
                for f in ("county_features.csv", "plural_breaks.csv"):
                    s = vd[v] / f"Y{y}" / "features" / f
                    if s.exists():
                        shutil.copy(s, vd[v] / f"Y{y}" / f)
        ns = dict(pairs=["pq5", "plc"], years=T.YEARS, name="conus", results_root=tmp, block_rows=7,
                  water_mask="yearly", cutout_root=tmp / "cutouts", dasym_root=out_root,
                  snapshot=tmp / "snap.json", out_dir=tmp / "cm_out")

        # snapshot + model check
        r = run(SCRIPT, "snapshot", "--dasym-root", out_root, "--snapshot", ns["snapshot"], "--years", *T.YEARS)
        assert r.returncode == 0 and "SNAPSHOT OK: 10 files" in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]
        mc = pcm.model_checks(Namespace(**ns))
        assert (mc["status"] == "OK").all() and len(mc) == 4, mc
        mp = models[(PLC, 2010)]
        raw = mp.read_bytes()
        mp.write_bytes(raw + b"x")
        mc = pcm.model_checks(Namespace(**ns))
        mp.write_bytes(raw)
        bad = mc[mc["status"] != "OK"]
        assert len(bad) == 1 and bad.iloc[0]["version"] == PLCCM and "scratch now" in bad.iloc[0]["status"], mc
        print("ok snapshot + model check: hashes = model_from.json; a changed model file is reported")

        # variance split = brute force
        r = run(SCRIPT, "variance", "--results-root", tmp, "--cutout-root", tmp / "cutouts", "--years", *T.YEARS,
                "--block-rows", 7, "--out-dir", ns["out_dir"])
        assert r.returncode == 0 and "VARIANCE OK" in r.stdout, r.stdout[-3000:] + r.stderr[-3000:]
        vs = pd.read_csv(ns["out_dir"] / "pluralcm_variance_split.csv").set_index(["year", "feature"])
        for y in T.YEARS:
            cf = pd.read_csv(vd[V57] / f"Y{y}" / "county_features.csv")
            bui = T.read(cut / "layers" / "BUI" / f"{y}_BUI.tif").astype("float64")
            bupl = T.read(cut / "layers" / "BUPL" / f"{y}_BUPL.tif").astype("float64")
            wf = T.read(cut / "layers" / "water_frac" / f"{y}_water_frac.tif")
            m = np.isin(zones, cf["zone_id"]) & ~((wf >= 1) & (bui == 0))
            brk = pd.read_csv(vd[PQ5] / f"Y{y}" / "plural_breaks.csv").iloc[0]
            inner = np.array([brk[f"break_{i}"] for i in range(1, 5)])
            vals = {"plural_plc": pl.astype("float64"), "plural_pq5": np.digitize(pl, inner) + 1.0, "bui": bui,
                    "nby": nby.astype("float64"), "bldg_size": np.divide(bui, bupl, out=np.zeros_like(bui),
                                                                         where=bupl > 0)}
            z = zones[m]
            for f, a in vals.items():
                x = a[m]
                tot = ((x - x.mean()) ** 2).sum()
                wit = sum(((x[z == k] - x[z == k].mean()) ** 2).sum() for k in np.unique(z))
                row = vs.loc[(y, f)]
                assert row["cells"] == m.sum() and row["counties"] == len(cf), (y, f)
                assert np.isclose(row["within_share"], wit / tot, rtol=1e-9), (y, f, row["within_share"], wit / tot)
                assert np.isclose(row["total_ss"], tot, rtol=1e-9)
        p = vd[PLC] / "Y2010" / "county_features.csv"
        keep = p.read_text()
        t = pd.read_csv(p)
        t.loc[2, "plural"] *= 1 + 1e-6
        t.to_csv(p, index=False)
        r = run(SCRIPT, "variance", "--results-root", tmp, "--cutout-root", tmp / "cutouts", "--years", *T.YEARS,
                "--out-dir", tmp / "x")
        p.write_text(keep)
        assert r.returncode != 0 and "VARIANCE CHECK 2010 plural_plc" in r.stdout + r.stderr, r.stdout[-2000:]
        print("ok variance split: within / between shares = brute force (5 features x 2 years); a changed county "
              "feature stops it")

        # built contrast = brute force; people = the cell pass
        vers = pcm.versions(["pq5", "plc"], base=False)
        a = Namespace(**ns)
        cells = pcm.nc.cells_table(a, vers)
        con = pcm.contrast_part(a, vers, cells)
        for y in T.YEARS:
            bui = T.read(cut / "layers" / "BUI" / f"{y}_BUI.tif")
            wf = T.read(cut / "layers" / "water_frac" / f"{y}_water_frac.tif")
            for lab, v in vers.items():
                p = T.read(vd[v] / "predictions" / f"pop_{y}.tif").astype("float64")
                ok = p != dcommon.NODATA_OUT
                k = ok & ~((wf >= 1) & (bui == 0))
                ratios = {"built_vs_bui0": [], "built_vs_bui0_nb": [], "built_vs_bui0_norec": []}
                for zid in np.unique(zones[k]):
                    c = k & (zones == zid)
                    b = p[c & (bui > 0)].mean() if (c & (bui > 0)).any() else np.nan
                    for key, sel in (("built_vs_bui0", c & (bui == 0)), ("built_vs_bui0_nb", c & (bui == 0) & (nby > 0)),
                                     ("built_vs_bui0_norec", c & (bui == 0) & (nby == 0))):
                        e = p[sel].mean() if sel.any() else np.nan
                        if np.isfinite(b) and np.isfinite(e) and e > 0:
                            ratios[key].append(b / e)
                got = con[(con["variant"] == lab) & (con["year"] == y)].set_index("measure")
                for key, x in ratios.items():
                    assert got.at[key, "counties"] == len(x), (lab, y, key)
                    assert np.isclose(got.at[key, "median"], np.median(x), rtol=1e-9), (lab, y, key)
                    assert np.isclose(got.at[key, "p90"], np.quantile(x, 0.9), rtol=1e-9)
                    assert np.isclose(got.at[key, "share_lt1"], np.mean(np.array(x) < 1))
        print("ok built contrast: per-county built / BUI = 0 weight ratios = brute force (5 versions x 2 years), people "
              "= the cell pass")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- compare on a synthetic results world

def test_compare():
    import test_v57plural as TP
    tmp = Path(tempfile.mkdtemp())
    saved = (TP.VARS, TP.V, TP.F, TP.CV)
    try:
        TP.VARS = ["plc", "pq5"]
        TP.V = {"v56": pcm.V56, "v56_nby": "Dasy_CONUS_RF_v3_u070_nby", "v54": "Dasy_CONUS_RF_v3_all", "v57": V57,
                "v57_plc": PLC, "v57_pq5": PQ5, "v56_plc": f"{pcm.V56}_plc", "v56_pq5": f"{pcm.V56}_pq5"}
        TP.F = {"v56": 1.0, "v56_nby": 0.8, "v54": 1.2, "v57": 0.9, "v57_plc": 1.15, "v57_pq5": 1.3, "v56_plc": 1.05,
                "v56_pq5": 0.97}
        TP.CV = {"v56": 0.50, "v56_nby": 0.45, "v54": 0.56, "v57": 0.50, "v57_plc": 0.48, "v57_pq5": 0.47,
                 "v56_plc": 0.49, "v56_pq5": 0.52}
        years = [1940, 2010]
        cf, noise, test_ids, err = TP.write_world(tmp, years, np.random.default_rng(3))
        nb, pg, o57, out = tmp / "nobuilt", tmp / "plural_grid", tmp / "o57", tmp / "out"
        for d in (nb, pg, o57, out):
            d.mkdir()
        ex = tmp / "excluded.csv"
        pd.DataFrame({"GISJOIN": TP.EXCL}).to_csv(ex, index=False)
        TP.seed_cells(nb, o57, years)
        ys = [str(y) for y in years]
        common = ["--results-root", str(tmp), "--exclusions", str(ex), "--years", *ys]
        for script, extra in (("v54_nby_compare.py", ["--split", tmp / "split.csv", "--out-dir", nb, "--nobuilt-dir", nb]),
                              ("plural_compare.py", ["--variants", "plc", "pq5", "--out-dir", pg]),
                              ("v57_plural_compare.py", ["compare", "--variants", "plc", "pq5", "--split",
                                                         tmp / "split.csv", "--out-dir", o57, "--nobuilt-dir", nb,
                                                         "--plural-dir", pg])):
            a = [extra[0], *common, *extra[1:]] if script.startswith("v57") else [*common, *extra]
            r = run(REPO / "src" / "validation" / script, *a)
            assert r.returncode == 0, (script, r.stdout[-3000:] + r.stderr[-3000:])
        # the cm versions: tract errors (pq5cm back near v5.7, plccm = plc) + model_from.json + snapshot
        tracts = pd.read_csv(tmp / "validation" / "conus" / V57 / "tract_errors_1940.csv")
        fcm = {PQ5CM: 0.91, PLCCM: 1.15}
        snap = {"versions": {}}
        for cmv, fv in fcm.items():
            src = cmv[:-2]
            d = tmp / "validation" / "conus" / cmv
            d.mkdir(parents=True)
            for y in years:
                tracts.assign(pop_model=tracts["pop_obs"] * (1 + fv * err)).to_csv(d / f"tract_errors_{y}.csv",
                                                                                     index=False)
                e = tmp / "dasymetric" / "conus" / cmv / f"Y{y}"
                e.mkdir(parents=True)
                h = hashlib.sha256(f"{src}{y}".encode()).hexdigest()
                (e / "model_from.json").write_text(json.dumps({
                    "version": cmv, "model_from": src, "era": f"Y{y}", "model_sha256": h, "county_features_sha256": "c",
                    "plural_breaks_sha256": None, "test_rows": 8, "test_max_abs_diff": 0.0, "test_check": "OK"}))
                snap["versions"].setdefault(src, {})[f"Y{y}"] = {"model": {"sha256": h},
                                                                 "county_features": {"sha256": "c"}}
        (tmp / "snap.json").write_text(json.dumps(snap))
        cells = pd.read_csv(o57 / "plural_v57_cells.csv")
        cells = cells[cells["version"].isin([V57, PQ5, PLC])]
        cm_cells = cells[cells["version"].isin([PQ5, PLC])].assign(version=lambda t: t["version"] + "cm",
                                                                    variant=lambda t: t["variant"] + "cm")
        cm_cells = cm_cells.assign(pop_bui0=cm_cells["pop_bui0"] * 0.9, share_bui0=cm_cells["share_bui0"] * 0.9)
        pd.concat([cells, cm_cells]).to_csv(out / "pluralcm_cells.csv", index=False)
        args = ["compare", *common, "--split", tmp / "split.csv", "--out-dir", out, "--prev-dir", o57,
                "--snapshot", tmp / "snap.json"]
        r = run(SCRIPT, *args)
        assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
        s = r.stdout
        assert s.index("RULE: interpretation rule") < s.index("== model check"), "the rule is logged first"
        assert s.count("MATCH") == 2, s[-3000:]  # comparison, cells
        cmp = pd.read_csv(out / "pluralcm_comparison.csv")
        assert set(cmp["variant"]) == {"v57", "v57_pq5", "v57_pq5cm", "v57_plc", "v57_plccm", "areal_weighting"}
        c = cmp[cmp["level"] == "county"].set_index(["variant", "year", "set"])
        num = ["n", "mdape", "mape", "r2", "cv_rmse_train_all", "plural_perm_rank", "nby_perm_rank"]
        for v in ("pq5", "plc"):
            a, b = c.xs(f"v57_{v}cm", level="variant")[num], c.xs(f"v57_{v}", level="variant")[num]
            pd.testing.assert_frame_equal(a, b)
            assert (c.xs(f"v57_{v}cm", level="variant")["county_from"] == f"{V57}_{v}").all()
        tr = cmp[(cmp["level"] == "tract") & (cmp["set"] == "all")].set_index(["variant", "year"])
        F = {**{k: TP.F[k] for k in ("v57", "v57_pq5", "v57_plc")}, "v57_pq5cm": 0.91, "v57_plccm": 1.15}
        for lab, f in F.items():
            for y in years:
                assert np.isclose(tr.at[(lab, y), "mdape"], 100 * np.median(np.abs(f * err))), (lab, y)
                assert np.isclose(tr.at[(lab, y), "d_mdape"], tr.at[(lab, y), "mdape"] - tr.at[("v57", y), "mdape"])
        assert np.isclose(tr.at[("v57_pq5cm", 2010), "d_mdape_orig"],
                          tr.at[("v57_pq5cm", 2010), "mdape"] - tr.at[("v57_pq5", 2010), "mdape"])
        assert np.isnan(tr.at[("v57_pq5", 2010), "d_mdape_orig"])
        rule = pd.read_csv(out / "pluralcm_rule.csv")
        j = rule[rule["judged"]].set_index(["pair", "year"])
        assert (j.xs("pq5", level="pair")["outcome"] == "cell_level").all(), j
        assert (j.xs("plc", level="pair")["outcome"] == "county_level").all(), j
        x = j.loc[("pq5", 2010)]
        assert np.isclose(x["recovered"], (x["mdape_plural"] - x["mdape_cm"]) / (x["mdape_plural"] - x["mdape_v57"]))
        assert "RULE: pq5 2010 all tracts" in s and "-> cell_level" in s and "-> county_level" in s
        ce = cmp[(cmp["level"] == "cells") & (cmp["set"] == "share_bui0")].set_index(["variant", "year"])
        assert ce.at[("v57_pq5cm", 1940), "share"] < ce.at[("v57_pq5", 1940), "share"]
        assert pd.read_csv(out / "pluralcm_model_check.csv")["status"].eq("OK").all()

        # the rule outcomes on small tables
        t = pd.DataFrame([{"level": "tract", "variant": v, "year": 1980, "set": "all", "mdape": m}
                          for v, m in (("v57", 27.0), ("v57_pq5", 31.0), ("v57_pq5cm", 26.0), ("v57_plc", 27.5),
                                       ("v57_plccm", 28.0))]
                         + [{"level": "tract", "variant": v, "year": 2010, "set": "all", "mdape": m}
                            for v, m in (("v57", 25.0), ("v57_pq5", 28.0), ("v57_pq5cm", 26.5), ("v57_plc", 28.0),
                                         ("v57_plccm", 29.0))])
        rt = pcm.rule_table(t, ["pq5", "plc"]).set_index(["pair", "year"])["outcome"]
        assert rt[("pq5", 1980)] == "beyond_v57" and rt[("plc", 1980)] == "not_judged"
        assert rt[("pq5", 2010)] == "partial" and rt[("plc", 2010)] == "further", rt

        def must_stop(path: Path, edit, why):
            keep = path.read_text()
            edit(path)
            rr = run(SCRIPT, *args)
            path.write_text(keep)
            assert rr.returncode != 0 and why in rr.stdout + rr.stderr, (path.name, why, (rr.stdout + rr.stderr)[-2000:])

        def csv_edit(fn):
            def go(p):
                tt = pd.read_csv(p)
                fn(tt)
                tt.to_csv(p, index=False)
            return go

        def bump(var, level, st, col="mdape"):
            return csv_edit(lambda tt: tt.__setitem__(col, tt[col] + 0.5 * ((tt["variant"] == var)
                                                                            & (tt["level"] == level)
                                                                            & (tt["set"] == st))))
        must_stop(o57 / "plural_v57_comparison.csv", bump("v57_pq5", "tract", "dens_0_50"), "differs from")
        must_stop(o57 / "plural_v57_comparison.csv", bump("v57", "county", "test_all", "r2"), "differs from")
        must_stop(o57 / "plural_v57_cells.csv", csv_edit(lambda tt: tt.__setitem__("pop", tt["pop"] + 1)),
                  "differs from")
        mj = tmp / "dasymetric" / "conus" / PQ5CM / "Y2010" / "model_from.json"
        must_stop(mj, lambda p: p.write_text(p.read_text().replace('"test_check": "OK"', '"test_check": "DIFFERS"')),
                  "model check failed")
        must_stop(tmp / "snap.json", lambda p: p.write_text(p.read_text().replace('"c"', '"d"', 1)),
                  "county_features sha256 differs from the snapshot")
        must_stop(mj, lambda p: p.unlink(), "without a model check")
        r = run(SCRIPT, *args)
        assert r.returncode == 0, r.stdout[-2000:]
        print("ok compare: earlier tables written by the earlier scripts match; cm county rows = the PLURAL "
              "version's; tracts, d_mdape / d_mdape_orig, rule (cell_level / county_level / partial / beyond / "
              "further / not_judged) by hand; changed numbers, a failed / missing model check, a snapshot mismatch stop")
    finally:
        TP.VARS, TP.V, TP.F, TP.CV = saved
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- the tracked numbers

def test_real():
    tmp = Path(tempfile.mkdtemp())
    try:
        r = run(SCRIPT, "compare", "--out-dir", tmp, "--snapshot", tmp / "none.json")
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
        assert "plural_v57_comparison.csv: 135 rows" in r.stdout, r.stdout[-3000:]
        print("ok real: tracked v5.7 / pq5 / plc rows = plural_v57_comparison.csv (135 rows)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_config()
    test_world()
    test_compare()
    test_real()
