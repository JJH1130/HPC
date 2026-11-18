"""Synthetic test of src/validation/external_city_density.py (city boxes by density class; docs/handoff/
v57_plural_density_request.md part B):

    python tests/test_external_city_density.py      (needs the hisdac env: rasterio, pyproj, matplotlib, scipy)

  test_classes      class split on the breaks (a block on 100 / 1,000 goes to the upper class) and the class metrics
                    (Spearman, totals, ratio quantiles, zero blocks, x4 / / 4 shares) by hand
  test_end_to_end   on the synthetic city world of test_external_city_meeting: the meeting maps of a v5.7 (its
                    meeting_summary_v56_v57.csv), then the density classes: every class row = by hand from the
                    product moved to our cells (blocks, people, scipy Spearman), classes add up to all, all = the
                    meeting numbers; one PNG size; a changed meeting number stops with nothing written; --check
  test_real_config  the city_density block of configs/external_grids.yaml
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "validation"))
sys.path.insert(0, str(REPO / "tests"))

import rasterio  # noqa: E402
import yaml  # noqa: E402
from pyproj import Transformer  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

import external_city_density as ecd  # noqa: E402
import external_city_maps as ecm  # noqa: E402
import external_city_meeting as mt  # noqa: E402
from test_external_city_maps import write  # noqa: E402
from test_external_city_meeting import OUR, make_world  # noqa: E402

DC = {"class_product": "ghs_pop", "breaks": [100, 1000], "classes": ["rural", "peri_urban", "urban"], "ratio_band": 4}


def test_classes():
    d = np.array([0, 50, 99.999, 100, 100.001, 999.9, 1000, 1000.1, 5000])
    assert ecd.classify(d, DC["breaks"]).tolist() == [0, 0, 0, 1, 1, 1, 2, 2, 2]
    v = np.array([0.0, 0.0, 10.0, 5.0, 40.0, 9.0, 1.0, 30.0])
    p = np.array([0.0, 3.0, 0.0, 5.0, 8.0, 100.0, 2.0, 7.0])
    m = ecd.class_metrics(v, p, 4)
    assert m["n_blocks"] == 8 and m["pop_version"] == v.sum() and m["pop_product"] == p.sum()
    assert np.isclose(m["ratio_total"], v.sum() / p.sum())
    r = v[p > 0] / p[p > 0]  # 0, 1, 5, 0.09, 0.5, 4.2857
    assert np.allclose([m["ratio_p10"], m["ratio_median"], m["ratio_p90"]], np.quantile(r, [.1, .5, .9]))
    assert m["n_version_zero"] == 2 and m["n_product_zero"] == 2 and m["n_both_zero"] == 1
    # not both 0: 7 blocks; above: v=10/p=0, 40 > 32, 30 > 28 -> 3; below: v=0/p=3, 9 < 25 -> 2
    assert m["n_not_both_zero"] == 7 and np.isclose(m["share_above"], 3 / 7) and np.isclose(m["share_below"], 2 / 7)
    assert np.isclose(m["spearman"], spearmanr(v, p)[0])
    assert np.isnan(ecd.class_metrics(v[:2], p[:2], 4)["spearman"])        # < 3 blocks
    rows = ecd.class_rows(v, p, np.array([10, 100, 150, 999, 1000, 2000, 50, 99]), DC, 1.0)
    got = {r["class"]: r["n_blocks"] for r in rows}
    assert got == {"rural": 3, "peri_urban": 3, "urban": 2, "all": 8}, got
    assert rows[1]["dens_lo"] == 100 and rows[2]["dens_hi"] == np.inf
    print("ok classes: breaks to the upper class, metrics by hand")


def add_density_block(cp: Path):
    cfg = yaml.safe_load(cp.read_text())
    cfg["city_density"] = DC
    cp.write_text(yaml.safe_dump(cfg, sort_keys=False))


def test_end_to_end(tmp: Path):
    w = make_world(tmp)
    add_density_block(w["cp"])
    base_out, new_out, dens_out = tmp / "meet", tmp / "meet57", tmp / "dens"
    mt.main(w["base"] + ["--out-dir", str(base_out)])
    pop57, pop57_80 = w["pop"].copy(), np.where(w["pop80"] >= 0, w["pop80"] * 1.1, w["pop80"])
    pop57[116:124, 116:132] = 250.0
    p57 = w["dasym"] / "conus" / "V57" / "predictions"
    write(p57 / "pop_2010.tif", pop57, w["gt"], OUR, -9999.0)
    write(p57 / "pop_1980.tif", pop57_80, w["gt"], OUR, -9999.0)
    mt.main(w["base"] + ["--out-dir", str(new_out), "--version", "V57", "--version-label", "v5.7", "--base-dir",
                         str(base_out)])
    side = new_out / "meeting_summary_v56_v57.csv"
    run = ["--config", str(w["cp"]), "--data-root", str(w["data"]), "--dasym-root", str(w["dasym"]), "--version",
           "V57", "--version-label", "v5.7", "--check-with", str(side), "--out-dir", str(dens_out)]
    assert ecd.main(run + ["--check"]) == 0 and not dens_out.exists()
    assert ecd.main(run) == 0
    t = pd.read_csv(dens_out / "density_class_summary.csv")
    assert set(t["class"]) == {"rural", "peri_urban", "urban", "all"} and set(t["basis"]) == {"ghs_pop", "version"}
    assert len(t) == 2 * 4 * 2 * (2 + 1)  # cities x classes x bases x (2010: 2 products, 1980: 1)
    # by hand: blocks of the product moved to our cells, classes by the GHS block density
    cfg = yaml.safe_load(w["cp"].read_text())
    cm = cfg["city_maps"]
    for city, (lon, lat) in (("chicago", (w["lon"], w["lat"])), ("boston", (w["lon"] + 0.01, w["lat"]))):
        cx, cy = Transformer.from_crs("EPSG:4326", OUR, always_xy=True).transform(lon, lat)
        for year, prods in ((2010, ["ghs_pop", "worldpop"]), (1980, ["ghs_pop"])):
            path = p57 / f"pop_{year}.tif"
            with rasterio.open(path) as src:
                gt = src.transform
            win = ecm.box_window(gt, cx, cy, cm["box_km"])
            vp, mask, bt = ecm.read_box(path, win, gt)
            full = ecm.block_sums(mask.astype(int), 4) == 16
            vb = ecm.block_sums(np.where(mask, vp, 0.0), 4)[full]
            gr = {}
            for prod in prods:
                spec = cfg["products"][prod]
                g, _ = ecm.to_grid(w["data"] / spec["path"].replace("{YEAR}", str(year)), bt, vp.shape, OUR, 25)
                gr[prod] = ecm.block_sums(np.where(mask, g, 0.0), 4)[full]
            gd = gr["ghs_pop"] / 1.0  # 1 km2 blocks
            cls = np.where(gd < 100, "rural", np.where(gd < 1000, "peri_urban", "urban"))
            for prod in prods:
                for c in ("rural", "peri_urban", "urban", "all"):
                    m = np.ones(len(cls), bool) if c == "all" else cls == c
                    r = t[(t["city"] == city) & (t["year"] == year) & (t["product"] == prod) & (t["basis"] == "ghs_pop")
                          & (t["class"] == c)].iloc[0]
                    assert r["n_blocks"] == m.sum(), (city, year, prod, c)
                    assert np.isclose(r["pop_version"], vb[m].sum()) and np.isclose(r["pop_product"], gr[prod][m].sum())
                    if m.sum() >= 3:
                        assert np.isclose(r["spearman"], spearmanr(vb[m], gr[prod][m])[0]), (city, year, prod, c)
            vc = np.where(vb < 100, "rural", np.where(vb < 1000, "peri_urban", "urban"))
            r = t[(t["city"] == city) & (t["year"] == year) & (t["product"] == "ghs_pop") & (t["basis"] == "version")]
            assert r.set_index("class")["n_blocks"].drop("all").to_dict() == \
                {c: int((vc == c).sum()) for c in ("rural", "peri_urban", "urban")}
    assert (t.groupby(["city", "year", "product", "basis"])["class"].count() == 4).all()
    a = t[(t["class"] == "all") & (t["product"] == "ghs_pop") & (t["basis"] == "ghs_pop")].set_index(["city", "year"])
    s = pd.read_csv(new_out / "meeting_summary.csv").set_index(["city", "year", "product"])
    for (city, year), r in a.iterrows():
        assert np.isclose(r["spearman"], s.loc[(city, year, "ghs_pop"), "spearman_1km_vs_version"])
        assert np.isclose(r["total_pop_box_product"], s.loc[(city, year, "ghs_pop"), "total_pop_box"])
    import matplotlib.image as mpimg
    sizes = {mpimg.imread(p).shape for p in dens_out.glob("*.png")}
    assert len(list(dens_out.glob("*.png"))) == 4 and len(sizes) == 1, sizes
    # a changed whole-box number in the meeting table stops before anything is written
    keep = side.read_text()
    x = pd.read_csv(side)
    x.loc[(x["table"] == "summary") & (x["measure"] == "spearman_1km_vs_version") & (x["item"] == "ghs_pop"), "v5.7"] += 1e-4
    x.to_csv(side, index=False)
    out2 = tmp / "dens2"
    try:
        ecd.main([a if a != str(dens_out) else str(out2) for a in run])
    except SystemExit as e:
        assert "whole box differs" in str(e), e
    else:
        raise AssertionError("a changed meeting number did not stop the run")
    assert not out2.exists()
    side.write_text(keep)
    try:  # a version without a column in the meeting table
        ecd.main([a if a not in ("v5.7", str(dens_out)) else {"v5.7": "v9"}.get(a, str(out2)) for a in run])
    except SystemExit as e:
        assert "no column 'v9'" in str(e), e
    else:
        raise AssertionError("missing label column accepted")
    print("ok end to end: class rows by hand, classes add up, all = the meeting numbers, one PNG size, a changed "
          "meeting number stops, --check")


def test_real_config():
    cfg = yaml.safe_load((REPO / "configs" / "external_grids.yaml").read_text())
    assert cfg["city_density"] == DC
    a = ecd.parse_args(["--data-root", "x", "--dasym-root", "y"])
    assert a.version == "Dasy_CONUS_RF_v3_all_nby" and a.version_label == "v5.7"
    assert a.out_dir.as_posix() == "results/validation/conus/external/city_density_classes_v57"
    assert ecd.CHECK_WITH.exists(), ecd.CHECK_WITH
    print("ok real config: breaks 100 / 1,000 on GHS-POP, ratio band 4, v5.7 defaults, meeting table tracked")


if __name__ == "__main__":
    test_classes()
    test_real_config()
    with tempfile.TemporaryDirectory() as d:
        test_end_to_end(Path(d))
    print("ALL OK")
