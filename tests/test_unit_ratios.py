"""Synthetic test of src/validation/unit_ratios.py (unit ratios; docs/handoff/unit_ratios_request.md):

    python tests/test_unit_ratios.py      (needs the hisdac env: rasterio, geopandas, scipy, matplotlib)

  test_local        part A on synthetic tables: ratios per county and year (zero denominators -> no ratio), region /
                    class / t070 columns, summaries (median, p10 / p90, pooled = sum / sum) and the household column,
                    flags outside the class-year quantiles (+ no_records) and the flag summary, all by hand; a county
                    missing in the bupr table stops; local mode end to end writes the 5 files
  test_job          part B on the cap-transfer test world (16 counties, 1980 + 2010) + BUPR layers: allocated ratios by
                    hand (people / BUPR on built cells, people per built cell, people / NobuiltYear on undated cells),
                    county tract MdAPE = by hand from tract_errors, Spearman of the class-median deviation = scipy;
                    --check writes nothing; a census number that differs from the v5.7 county sums stops
  test_real_config  the unit_ratios block of configs/external_grids.yaml + its tracked inputs
"""
from __future__ import annotations

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

import external_city_density as ecd  # noqa: E402
import unit_ratios as ur  # noqa: E402
from test_external_city_maps import write  # noqa: E402
from test_external_city_meeting import OUR  # noqa: E402
from test_missed_cells import expect_exit  # noqa: E402

REGIONS = {"South": ["01"], "West": ["08"]}


def tables():
    gj = ["G0100010", "G0100030", "G0800010", "G0800030", "G0800050"]
    cfs = {y: pd.DataFrame({"year": y, "GISJOIN": gj, "state": "s", "name": list("ABCDE"),
                            "pop": [100.0, 50.0, 0.0, 30.0, 400.0] if y == 1940 else [120.0, 60.0, 10.0, 40.0, 500.0]})
           for y in (1940, 2010)}
    bupr = pd.DataFrame({"GISJOIN": gj, "bupr_1940": [10.0, 0.0, 2.0, 3.0, 40.0],
                         "bupr_2010": [40.0, 20.0, 5.0, 8.0, 100.0], "nobuilt": [10.0, 5.0, 0.0, 2.0, 60.0],
                         "ratio_A_nby": [0.2, 0.9, 0.0, 0.4, 0.37]})
    cls = {"G0100010": "rural", "G0100030": "rural", "G0800010": "city", "G0800030": "rural"}   # E: no label
    built = pd.DataFrame({"year": 2010, "GISJOIN": gj, "n_cells_built": [4, 6, 0, 2, 10]})
    return gj, cfs, bupr, cls, built


def test_local(tmp: Path):
    gj, cfs, bupr, cls, built = tables()
    regions = {"01": "South", "08": "West"}
    cr = ur.county_ratios(cfs, bupr, cls, {"G0100030"}, built, regions)
    a = cr[cr["year"] == 1940].set_index("GISJOIN")
    assert np.isclose(a.loc["G0100010", "ratio_dated"], 10) and np.isnan(a.loc["G0100030", "ratio_dated"])
    assert np.isclose(a.loc["G0100030", "ratio_lower"], 50 / 5) and np.isclose(a.loc["G0800050", "ratio_lower"], 4)
    assert np.isclose(a.loc["G0800010", "ratio_dated"], 0) and np.isnan(a.loc["G0800010", "records_per_capita"])
    assert a["n_cells_built"].isna().all() and a.loc["G0800050", "county_class_1980"] == "none"
    assert a.loc["G0800030", "region"] == "West" and bool(a.loc["G0100030", "excluded_t070"])
    b = cr[cr["year"] == 2010].set_index("GISJOIN")
    assert np.isclose(b.loc["G0100030", "pop_per_built_cell"], 10) and np.isnan(b.loc["G0800010", "pop_per_built_cell"])
    sm = ur.summary(cr, {2010: 2.59})
    r = sm[(sm["year"] == 2010) & (sm["group"] == "rural") & (sm["measure"] == "ratio_dated")].iloc[0]
    v = np.array([120 / 40, 60 / 20, 40 / 8])
    assert r["n"] == 3 and np.isclose(r["median"], np.median(v)) and np.isclose(r["p90"], np.quantile(v, 0.9))
    assert np.isclose(r["pooled"], 220 / 68) and np.isclose(r["avg_pop_per_household_us"], 2.59)
    r = sm[(sm["year"] == 1940) & (sm["group"] == "all") & (sm["measure"] == "ratio_dated")].iloc[0]
    assert r["n"] == 4 and r["n_no_ratio"] == 1 and np.isclose(r["pooled"], 530 / 55)
    assert np.isnan(r["avg_pop_per_household_us"])
    r = sm[(sm["year"] == 1940) & (sm["group"] == "West") & (sm["measure"] == "ratio_lower")].iloc[0]
    assert np.isclose(r["pooled"], 430 / (2 + 5 + 100))
    fl = ur.flags(cr, [0.01, 0.99])
    f = fl[(fl["year"] == 1940) & (fl["measure"] == "ratio_dated")]
    # rural 1940 ratios: A 10, D 10 (B no ratio, with people) -> no low / high, B no_records
    assert set(zip(f["GISJOIN"], f["side"])) == {("G0100030", "no_records")}
    f = fl[(fl["year"] == 2010) & (fl["measure"] == "ratio_dated") & (fl["county_class_1980"] == "rural")]
    v = np.array([3.0, 3.0, 5.0])
    lo, hi = np.quantile(v, [0.01, 0.99])
    assert set(f["GISJOIN"]) == {g for g, x in zip(["G0100010", "G0100030", "G0800030"], v) if x < lo or x > hi}
    assert (f["side"] == "high").all() and np.isclose(f["q_high"].iloc[0], hi)
    fs = ur.flag_summary(cr, fl)
    r = fs[(fs["measure"] == "ratio_dated") & (fs["year"] == 1940) & (fs["side"] == "no_records")].iloc[0]
    assert r["n_flagged"] == 1 and r["excluded_share_flagged"] == 1.0 and np.isclose(r["excluded_share_all"], 1 / 5)
    assert "missing" in expect_exit(ur.county_ratios, cfs, bupr.iloc[1:], cls, set(), None, regions)
    # local mode end to end
    res = tmp / "res"
    res.mkdir()
    for y, cf in cfs.items():
        (res / f"Y{y}").mkdir()
        cf.to_csv(res / f"Y{y}" / "county_features.csv", index=False)
    bupr.to_csv(res / "bupr.csv", index=False)
    pd.DataFrame({"GISJOIN": list(cls), "county_class": list(cls.values())}).to_csv(res / "cls.csv", index=False)
    pd.DataFrame({"GISJOIN": ["G0100030"]}).to_csv(res / "excl.csv", index=False)
    built.assign(method="v57").to_csv(res / "caps.csv", index=False)
    (res / "hh.csv").write_text("# test\nyear,avg_pop_per_household,hh6_row\n2010,2.59,2010\n")
    cfg = {"products": {}, "rural_boxes": {"select": {"regions": REGIONS}},
           "unit_ratios": {"version": "V", "model_config": "m.yaml", "years": [1940, 2010],
                           "county_features": str(res / "Y{YEAR}" / "county_features.csv"),
                           "bupr": str(res / "bupr.csv"), "county_class": str(res / "cls.csv"),
                           "exclusions": str(res / "excl.csv"), "built_cells": str(res / "caps.csv"),
                           "household": str(res / "hh.csv"), "flag_quantiles": [0.01, 0.99], "job_years": [2010],
                           "tract_errors": "x_{YEAR}.csv", "min_tracts": 5}}
    cp = tmp / "c.yaml"
    cp.write_text(yaml.safe_dump(cfg))
    out = tmp / "out"
    assert ur.main(["local", "--config", str(cp), "--out-dir", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["county_ratios.csv", "ratio_by_year.png", "ratio_flag_summary.csv",
                                                     "ratio_flags.csv", "ratio_summary.csv"]
    got = pd.read_csv(out / "county_ratios.csv")
    assert np.allclose(got["ratio_lower"], cr["ratio_lower"], equal_nan=True)
    print("ok local: ratios, summaries, pooled, household column, flags and flag summary by hand; end to end")


def test_job(tmp: Path):
    import geopandas as gpd
    from scipy.stats import spearmanr
    import test_cap_transfer as tct
    w = tct.make_world(tmp)
    rng = np.random.default_rng(5)
    cutc = w["cut"] / "conus"
    bupr = {}
    for y in tct.YEARS:
        bupr[y] = np.where(w["bui"][y] > 0, rng.integers(1, 6, (tct.H, tct.W)), 0).astype(float)
        write(cutc / "layers" / "BUPR" / f"{y}_BUPR.tif", bupr[y], w["gt"], OUR, -1.0)
    cfg = w["cfg"]
    tbl = pd.DataFrame({"GISJOIN": tct.GJ, "nobuilt": 1.0, "ratio_A_nby": 0.3,
                        **{f"bupr_{y}": [bupr[y][w["zones"] == z].sum() for z in range(1, 17)] for y in tct.YEARS}})
    tbl.to_csv(w["res"] / "bupr_tbl.csv", index=False)
    cfg["rural_boxes"] = {"select": {"regions": REGIONS}}
    cfg["unit_ratios"] = {"version": "V57", "model_config": cfg["missed_cells"]["model_config"], "years": [1980, 2010],
                          "county_features": cfg["cap_transfer"]["county_features"],
                          "bupr": str(w["res"] / "bupr_tbl.csv"), "county_class": str(w["res"] / "classes.csv"),
                          "exclusions": str(w["res"] / "excl.csv"), "built_cells": str(tmp / "none.csv"),
                          "household": str(REPO / "configs" / "household_size_hh6.csv"),
                          "flag_quantiles": [0.01, 0.99], "job_years": [1980, 2010],
                          "tract_errors": cfg["cap_transfer"]["tract_errors"], "min_tracts": 5}
    w["cp"].write_text(yaml.safe_dump(cfg, sort_keys=False))
    base = ["job", "--config", str(w["cp"]), "--dasym-root", str(w["dasym"]), "--cutout-root", str(w["cut"]),
            "--hisdac-dir", str(w["hisdac"]), "--workers", "1"]
    out = tmp / "ur"
    assert ur.main(base + ["--out-dir", str(out), "--check"]) == 0 and not out.exists()
    assert ur.main(base + ["--out-dir", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["allocated_ratios.csv", "ratio_vs_tract.csv", "ratio_vs_tract.png"]
    al = pd.read_csv(out / "allocated_ratios.csv")
    vt = pd.read_csv(out / "ratio_vs_tract.csv")
    for y in tct.YEARS:
        ctype = ecd.cell_types(w["bui"][y], w["nby"])
        m = w["mask"][y]
        d = al[al["year"] == y].set_index("GISJOIN")
        for z in range(1, 17):
            r = d.loc[tct.GJ[z - 1]]
            mz = m & (w["zones"] == z)
            b, u = mz & (ctype == 0), mz & (ctype == 1)
            assert np.isclose(r["alloc_pop_per_record_built"], w["v57"][y][b].sum() / bupr[y][b].sum())
            assert np.isclose(r["alloc_pop_per_built_cell"], w["v57"][y][b].sum() / b.sum())
            assert np.isclose(r["alloc_pop_per_record_undated"], w["v57"][y][u].sum() / w["nby"][u].sum())
            assert np.isclose(r["alloc_pop_per_undated_cell"], w["v57"][y][u].sum() / u.sum())
            assert np.isclose(r["pop_built"] + r["pop_undated"] + r["pop_no_record"], w["cen"][y][z - 1])
        te = pd.read_csv(w["vroot"] / "conus" / "V57" / f"tract_errors_{y}.csv")
        ok = te[te["flag"] == "ok"]
        for gjz, e in ok.groupby("zone_gisjoin"):
            o, p = e["pop_obs"].to_numpy(), e["pop_model"].to_numpy()
            assert np.isclose(d.loc[gjz, "tract_mdape"], np.median(np.abs(p[o > 0] - o[o > 0]) / o[o > 0]) * 100)
            assert d.loc[gjz, "n_tracts"] == len(e)
        mm = "alloc_pop_per_record_built"
        med = d.groupby("county_class_1980")[mm].median()
        dev = np.abs(np.log(d[mm] / d["county_class_1980"].map(med)))
        s = d["n_tracts"] >= 5
        rho = spearmanr(dev[s], d.loc[s, "tract_mdape"])[0]
        r = vt[(vt["year"] == y) & (vt["measure"] == mm) & (vt["county_class_1980"] == "all")].iloc[0]
        assert r["n_counties"] == s.sum() and np.isclose(r["spearman"], rho)
    # a census number that differs from the v5.7 county sums stops
    zc = w["cut"] / "conus" / "zones" / "zones_2010.csv"
    z = pd.read_csv(zc)
    z.loc[3, "pop"] *= 1.01
    z.to_csv(zc, index=False)
    assert "census" in expect_exit(ur.main, base + ["--out-dir", str(tmp / "x")]) and not (tmp / "x").exists()
    print("ok job: allocated ratios by hand, tract MdAPE by hand, Spearman = scipy, a census difference stops")


def test_real_config():
    from external_compare import load_config
    cfg = load_config(REPO / "configs" / "external_grids.yaml")
    u = ur.ur_config(cfg)
    assert u["years"] == list(range(1900, 2021, 10)) and u["job_years"] == [1940, 1960, 1980, 2010]
    assert u["flag_quantiles"] == [0.01, 0.99] and u["min_tracts"] == 5
    for k in ("bupr", "county_class", "exclusions", "built_cells", "household", "model_config"):
        assert (REPO / u[k]).exists(), u[k]
    for y in u["years"]:
        assert (REPO / ur.ypath(u["county_features"], y)).exists(), y
    for y in u["job_years"]:
        assert (REPO / ur.ypath(u["tract_errors"], y)).exists(), y
    reg = ur.regions_of(cfg)
    assert len(reg) == 49 and reg["08"] == "West"
    hh = pd.read_csv(REPO / u["household"], comment="#")
    assert list(hh["year"]) == list(range(1940, 2021, 10))
    print("ok real config: unit_ratios block, tracked inputs, 49 state FIPS in 4 regions, HH-6 years 1940-2020")


if __name__ == "__main__":
    test_real_config()
    for fn in (test_local, test_job):
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
    print("ALL OK")
