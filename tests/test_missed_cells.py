"""Synthetic test of src/validation/missed_cells.py (1980 missed cells; docs/handoff/missed_cells_1980_request.md):

    python tests/test_missed_cells.py      (needs the hisdac env: rasterio, pyproj, geopandas, scipy, matplotlib)

  test_product_strips  to_grid per strip and column tile = to_grid of the whole window, cell by cell; the product's
                       people kept (a raster well inside our grid: the grid total = the raster total)
  test_classes         cell groups (built / undated / no_record, BUI nodata = unbuilt); scheme A class of a cell = its
                       1 km block's majority SMOD code (by hand, a tie -> the more urban code, a strip whose width is
                       not a multiple of 4); county class by the 50 % rule at the boundaries (0.5 = city / rural,
                       0.49, both 0.5 -> city, no GHS people -> no_ghs)
  test_capture         capture by hand (ties share the boundary run evenly, NaN scores last), the GHS score >= any
                       other score at every k (random scores), random = k; Spearman per group = scipy; check_capture
                       stops on a score above the upper bound
  test_run             end to end on the DEGURBA test world (city boxes + a rural box, degurba_boxes run first for
                       cell_type_shares.csv): county rows by hand (people, shares, gap, GHS / census, GHS-BUILT shares,
                       county class, overlap), by-class rows = sums of the county rows, capture of v57 / plural_inv by
                       an independent loop, box sums MATCH; strips of 16 rows = one strip of the whole window; --check
                       writes nothing; a changed cell_type_shares number / census number stops with nothing written
  test_real_config     the missed_cells block of configs/external_grids.yaml
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "validation"))
sys.path.insert(0, str(REPO / "src" / "dasymetric"))
sys.path.insert(0, str(REPO / "tests"))

import rasterio  # noqa: E402
import yaml  # noqa: E402
from pyproj import Transformer  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

import degurba_boxes as db  # noqa: E402
import external_city_density as ecd  # noqa: E402
import external_city_maps as ecm  # noqa: E402
import external_city_meeting as mt  # noqa: E402
import missed_cells as mc  # noqa: E402
from test_degurba_boxes import CODES, RULES, SCHEME_A, write_int  # noqa: E402
from test_external_city_maps import write  # noqa: E402
from test_external_city_meeting import OUR, make_world  # noqa: E402


def expect_exit(fn, *a):
    try:
        fn(*a)
    except SystemExit as e:
        assert e.code not in (0, None), e.code
        return str(e.code)
    raise AssertionError("expected SystemExit")


def test_product_strips(tmp: Path):
    gt = from_origin(500_000.0, 1_800_000.0, 250.0, 250.0)
    H, W = 48, 44
    cx, cy = 500_000.0 + 250 * 22, 1_800_000.0 - 250 * 24
    mx, my = Transformer.from_crs(OUR, "ESRI:54009", always_xy=True).transform(cx, cy)
    rng = np.random.default_rng(1)
    a = rng.uniform(0, 5, (60, 60))
    a[:5, :5] = -200.0                                   # nodata -> 0
    path = tmp / "p.tif"
    write(path, a, from_origin(mx - 3000, my + 3000, 100.0, 100.0), "ESRI:54009", -200.0)
    whole = ecm.to_grid(path, gt, (H, W), OUR, 25)[0]
    parts = np.vstack([mc.product_rows(path, r, min(r + 16, H), gt, OUR, W, 12, 25) for r in range(0, H, 16)])
    assert np.allclose(parts, whole, rtol=1e-12, atol=1e-12)
    assert np.isclose(whole.sum(), a[a >= 0].sum(), rtol=1e-9)     # the raster lies inside the grid: kept
    print("ok product strips: strips x column tiles = whole window; people kept")


def test_classes(tmp: Path):
    bui = np.array([[1.0, 0.0, 0.0, -1.0]])
    nb = np.array([[0.0, 2.0, 0.0, 0.0]])
    assert ecd.cell_types(bui, nb).tolist() == [[0, 1, 2, 2]]   # BUI nodata (-1 after the read) = unbuilt
    # SMOD on our grid, 1 km cells aligned with the 4 x 4 blocks except one shifted SMOD raster
    gt = from_origin(0.0, 8000.0, 250.0, 250.0)
    s = np.array([[30, 21, 11, 10], [12, 23, 13, -200]])
    write_int(tmp / "smod.tif", s, from_origin(0.0, 8000.0, 1000.0, 1000.0), OUR, -200)
    rb = {"smod": {"codes": CODES, "scheme_a": SCHEME_A}}
    cls, found = mc.cell_classes(tmp / "smod.tif", gt, (8, 14), OUR, rb)   # width 14: last block padded
    want = np.array([[2, 1, 0, 3], [0, 1, 0, 3]])                           # urban 2, peri 1, rural 0, excluded 3
    assert (cls == np.repeat(np.repeat(want, 4, 0), 4, 1)[:8, :14]).all()
    # a block half 30, half 11 (SMOD shifted by 2 cells = 500 m): tie -> 30 = urban
    write_int(tmp / "smod2.tif", np.array([[11, 30, 30]]), from_origin(-500.0, 8000.0, 1000.0, 1000.0), OUR, -200)
    cls2, _ = mc.cell_classes(tmp / "smod2.tif", gt, (4, 4), OUR, rb)
    assert (cls2 == 2).all()
    assert found[30] == 4 * 4 * 1 and found[db.NODATA] == 4 * 2      # codes counted per cell (strip 8 x 14)
    r = {"city_urban_share": 0.5, "rural_share": 0.5}
    u = np.array([0.5, 0.49, 0.5, 0.0, 0.2, 0.0])
    ru = np.array([0.0, 0.5, 0.5, 0.49, 0.3, 0.0])
    tot = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 0.0])
    assert mc.county_class(u, ru, tot, r).tolist() == ["city", "rural", "city", "town_suburb", "town_suburb", "no_ghs"]
    print("ok classes: cell groups, block majority classes (tie, padding), county class 50 % rule at the bounds")


def capture_by_hand(group, score, target, k):
    """Independent loop: per group, score levels from the top; a level that crosses k x n counts in part."""
    tot = 0.0
    for g in np.unique(group):
        m = group == g
        s = np.where(np.isfinite(score[m]), score[m], -np.inf)
        t = target[m]
        left = k * m.sum()
        for lv in sorted(set(s.tolist()), reverse=True):
            sel = s == lv
            take = min(left, sel.sum())
            tot += t[sel].sum() * take / sel.sum()
            left -= take
            if left <= 0:
                break
    return tot


def test_capture(tmp: Path):
    g = np.array([0, 0, 0, 0, 1, 1])
    t = np.array([4.0, 3.0, 2.0, 1.0, 5.0, 1.0])
    s = np.array([0.1, 0.9, 0.9, np.nan, 2.0, 1.0])        # ties at the top of group 0; NaN last
    c = mc.capture(g, s, t, [0.25, 0.5, 0.75, 1.0], 2)
    # group 0, n = 4: k = 0.25 -> 1 cell of the tie run (3 + 2) / 2 = 2.5; 0.5 -> 5; 0.75 -> 5 + 4; 1 -> 10
    assert np.allclose(c[0], [2.5, 5.0, 9.0, 10.0])
    # group 1, n = 2: 0.25 -> half a cell of 5; 0.5 -> 5; 0.75 -> 5 + 0.5; 1 -> 6
    assert np.allclose(c[1], [2.5, 5.0, 5.5, 6.0])
    rng = np.random.default_rng(2)
    g = rng.integers(0, 7, 3000)
    t = rng.gamma(0.4, 10, 3000)
    t[rng.random(3000) < 0.3] = 0.0                       # many zero cells: ties in the upper bound
    ks = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5]
    up = mc.capture(g, t, t, ks, 7).sum(0)
    for sc in (rng.random(3000), np.round(rng.random(3000), 1), t + rng.normal(0, 3, 3000)):
        c = mc.capture(g, sc, t, ks, 7).sum(0)
        assert (c <= up + 1e-9).all()
        for j, k in enumerate(ks):
            assert np.isclose(c[j], capture_by_hand(g, sc, t, k))
    const = mc.capture(g, np.zeros(3000), t, ks, 7).sum(0)          # one tie run per group = random = k
    assert np.allclose(const / t.sum(), ks)
    x, y = rng.random(3000), t + rng.random(3000)
    x[:50] = 0.5                                                     # ties
    rho = mc.spearman_groups(g, x, y, 7)
    for i in range(7):
        assert np.isclose(rho[i], spearmanr(x[g == i], y[g == i])[0])
    assert np.isnan(mc.spearman_groups(np.array([0, 0]), np.array([1.0, 2.0]), np.array([1.0, 2.0]), 1)[0])
    rows = [{"subset": "all", "ranking": "within_county", "metric": "capture", "score": sname, "k": k, "value": v}
            for sname, vals in (("ghs", [0.3, 0.5]), ("v57", [0.2, 0.6]), ("random", [0.1, 0.2]))
            for k, v in zip([0.1, 0.2], vals)]
    assert "above the GHS upper bound" in expect_exit(mc.check_capture, pd.DataFrame(rows))
    print("ok capture: ties / NaN by hand, <= the GHS upper bound, = an independent loop, random = k; Spearman = scipy")


# ---------------------------------------------------------------- end to end

def deg_world(tmp: Path) -> dict:
    """The DEGURBA test world (test_degurba_boxes.test_run): meeting maps, v5.7 / pq5, SMOD, one rural box; runs
    degurba_boxes run so cell_type_shares.csv exists."""
    w = make_world(tmp)
    cfg = yaml.safe_load(w["cp"].read_text())
    cfg["city_density"] = {"class_product": "ghs_pop", "breaks": [100, 1000],
                           "classes": ["rural", "peri_urban", "urban"], "ratio_band": 4}
    hd = ["--hisdac-dir", str(w["hisdac"])]
    base_out, new_out = tmp / "meet", tmp / "meet57"
    w["cp"].write_text(yaml.safe_dump(cfg, sort_keys=False))
    pop57, pop57_80 = w["pop"].copy(), np.where(w["pop80"] >= 0, w["pop80"] * 1.1, w["pop80"])
    pop57[116:124, 116:132] = 250.0
    pop57_80[:8, :] = -9999.0                            # no county there (zone 0)
    pop57_80[200:204, 0:4] = 0.0                          # an empty corner
    mt.main(w["base"] + hd + ["--out-dir", str(base_out)])
    p57 = w["dasym"] / "conus" / "V57" / "predictions"
    write(p57 / "pop_2010.tif", pop57, w["gt"], OUR, -9999.0)
    write(p57 / "pop_1980.tif", pop57_80, w["gt"], OUR, -9999.0)
    pq = w["dasym"] / "conus" / "V57PQ5" / "predictions"
    write(pq / "pop_2010.tif", np.where(pop57 >= 0, pop57 * 0.9, pop57), w["gt"], OUR, -9999.0)
    pq80 = np.where(pop57_80 >= 0, pop57_80 * 1.2, pop57_80)
    pq80[60:62, 60:70] = -9999.0                          # pq5 without a value on some mask cells
    write(pq / "pop_1980.tif", pq80, w["gt"], OUR, -9999.0)
    mt.main(w["base"] + hd + ["--out-dir", str(new_out), "--version", "V57", "--version-label", "v5.7", "--base-dir",
                              str(base_out)])
    gt = w["gt"]
    n = 60
    rng = np.random.default_rng(3)
    s10 = rng.choice([11, 12, 13, 21, 22, 23, 30, 10], size=(n, n), p=[.3, .1, .1, .1, .1, .1, .2, .0])
    s10[30:32, 30:33] = 10
    s10[5, 5] = -200
    s80 = np.where(s10 == 30, 23, s10)
    s80[40:50, 0:20] = 30                                 # an urban county part in 1980
    for y, s in ((2010, s10), (1980, s80)):
        write_int(w["data"] / "smod" / f"smod_{y}.tif", s, from_origin(gt.c, gt.f, 1000.0, 1000.0), OUR, -200)
    cx, cy = gt.c + 250 * 152, gt.f - 250 * 80 - 125
    cfg["rural_boxes"] = {"version": "V57", "version_label": "v5.7", "extra_versions": {"V57PQ5": "v5.7_pq5"},
                          "years": {2010: ["ghs_pop", "worldpop"], 1980: ["ghs_pop"]}, "cities": ["boston", "chicago"],
                          "box_km": 12,
                          "smod": {"label": "smod", "path": "smod/smod_{YEAR}.tif", "years": [1980, 2010],
                                   "select_year": 2010, "codes": CODES, "scheme_a": SCHEME_A},
                          "own_rules": {**RULES, "margin_km": 4}, "select": {},
                          "boxes": {"rural_r1": {"label": "Test County, 01 (rural, R1)", "box_type": "rural",
                                                 "region": "R1", "gisjoin": "G0100010", "county": "Test",
                                                 "state_fips": "01", "density_2010": 12.5, "x": cx, "y": cy,
                                                 "crs": OUR}}}
    w["cp"].write_text(yaml.safe_dump(cfg, sort_keys=False))
    deg = tmp / "deg"
    assert db.main(["run", "--config", str(w["cp"]), "--data-root", str(w["data"]), "--dasym-root", str(w["dasym"]),
                    "--cutout-root", str(w["cut"]), "--check-with", str(new_out / "meeting_summary_v56_v57.csv"),
                    "--out-dir", str(deg)] + hd) == 0
    return {**w, "cfg": cfg, "hd": hd, "deg": deg, "pop57_80": pop57_80, "pq80": pq80, "s80": s80}


def add_missed_inputs(w: dict, tmp: Path) -> dict:
    import geopandas as gpd
    from shapely.geometry import box
    gt, H, W = w["gt"], 240, 240
    rng = np.random.default_rng(9)
    zones = np.zeros((H, W), np.int64)
    zones[8:, 0:80], zones[8:, 80:150], zones[8:, 150:240] = 1, 2, 3
    zones[230:, 150:240] = 4                              # a county not used (status no_value)
    v = w["pop57_80"].astype(np.float32).astype(np.float64)   # the values of the float32 prediction file
    mask = v != -9999.0
    v57 = np.where(mask, v, 0.0)
    pops = [float(v57[(zones == z) & mask].sum()) for z in (1, 2, 3, 4)]
    cut = w["cut"] / "conus"
    write_int(cut / "zones" / "zones_1980.tif", zones, gt, OUR, 0)
    zt = pd.DataFrame({"zone_id": [1, 2, 3, 4], "GISJOIN": ["G0100010", "G0100030", "G0100050", "G0100070"],
                       "state": ["Alabama"] * 4, "name": ["A", "B", "C", "D"], "pop": pops,
                       "status": ["ok", "ok", "filled_nhgis_alloc", "no_value"], "area_km2": [100.0] * 4})
    zt.to_csv(cut / "zones" / "zones_1980.csv", index=False)
    plural = rng.random((H, W))
    plural[100:104, 30:34] = -1.0                          # nodata
    write(cut / "layers" / "PLURAL" / "1980_PLURAL.tif", plural, gt, OUR, -1.0)
    v54 = np.where(mask, v * 0.8, -9999.0)
    v54[20:22, 20:30] = -9999.0
    write(w["dasym"] / "conus" / "V54" / "predictions" / "pop_1980.tif", v54, gt, OUR, -9999.0)
    with rasterio.open(w["data"] / "ghs" / "ghs_1980.tif") as src:
        ghs, gtr = src.read(1), src.transform
    built = np.where(ghs >= 0, ghs * 30.0 + rng.uniform(0, 50, ghs.shape), ghs)
    write(w["data"] / "built" / "built_1980.tif", built, gtr, "ESRI:54009", -200.0)
    # model config + study area, counties
    (tmp / "configs").mkdir(exist_ok=True)
    (tmp / "study.yaml").write_text("name: conus\nyears: [1980]\n")
    mcfg = tmp / "configs" / "model.yaml"
    mcfg.write_text(yaml.safe_dump({"version": "V57", "study_area": str(tmp / "study.yaml"), "block_rows": 16,
                                    "use_status": ["ok", "filled_nhgis_alloc"], "train_status": ["ok"],
                                    "unusable": "skip"}))
    cen = tmp / "census"
    cen.mkdir(exist_ok=True)
    x0, y1 = gt.c, gt.f
    geoms = [box(x0, y1 - 240 * 250, x0 + 80 * 250, y1 - 8 * 250), box(x0 + 80 * 250, y1 - 240 * 250, x0 + 150 * 250,
                                                                         y1 - 8 * 250),
             box(x0 + 150 * 250, y1 - 240 * 250, x0 + 240 * 250, y1 - 8 * 250)]
    gpd.GeoDataFrame({"GISJOIN": ["G0100010", "G0100030", "G0100050"]}, geometry=geoms, crs=OUR).to_file(
        cen / "counties_2010.gpkg", driver="GPKG")
    cfg = w["cfg"]
    cfg["missed_cells"] = {"year": 1980, "model_config": str(mcfg), "mask_map": "v57",
                           "maps": {"v57": "V57", "pq5": "V57PQ5", "v54": "V54"},
                           "ghs_built": {"label": "built", "path": "built/built_{YEAR}.tif", "years": [1980]},
                           "plural_layer": "PLURAL", "placedist_layer": "PLACEDIST",
                           "county_rule": {"city_urban_share": 0.5, "rural_share": 0.5},
                           "ks": [0.01, 0.02, 0.05, 0.1, 0.2, 0.5], "tile_cols": 64}
    w["cp"].write_text(yaml.safe_dump(cfg, sort_keys=False))
    return {"zones": zones, "mask": mask, "v57": v57, "v54": v54, "plural": plural, "cen": cen,
            "pops": pops, "built_path": w["data"] / "built" / "built_1980.tif"}


def test_run(tmp: Path):
    w = deg_world(tmp)
    x = add_missed_inputs(w, tmp)
    out = tmp / "missed"
    base = ["run", "--config", str(w["cp"]), "--data-root", str(w["data"]), "--dasym-root", str(w["dasym"]),
            "--cutout-root", str(w["cut"]), "--census-dir", str(x["cen"]), "--box-check",
            str(w["deg"] / "cell_type_shares.csv"), "--workers", "1"] + w["hd"]
    assert mc.main(base + ["--out-dir", str(out), "--check"]) == 0 and not out.exists()
    assert mc.main(base + ["--out-dir", str(out)]) == 0
    ct = pd.read_csv(out / "county_missed_1980.csv")
    bc = pd.read_csv(out / "by_class_1980.csv")
    cap = pd.read_csv(out / "plural_capture_1980.csv")
    assert sorted(p.name for p in out.iterdir()) == ["by_class_1980.csv", "capture_1980.png",
                                                     "county_gap_1980.png", "county_missed_1980.csv",
                                                     "plural_capture_1980.csv"]
    # by hand on the whole window
    gt, H, W = w["gt"], 240, 240
    zones, mask, v57 = x["zones"], x["mask"], x["v57"]
    ghs = ecm.to_grid(w["data"] / "ghs" / "ghs_1980.tif", gt, (H, W), OUR, 25)[0]
    bs = ecm.to_grid(x["built_path"], gt, (H, W), OUR, 25)[0]
    with rasterio.open(w["cut"] / "conus" / "layers" / "BUI" / "1980_BUI.tif") as src:
        bui = src.read(1).astype(float)
    nb = w["nby"]
    ctype = ecd.cell_types(bui, nb)
    blk = np.repeat(np.repeat(w["s80"], 4, 0), 4, 1)
    cls = np.where(blk == 30, 2, np.where(np.isin(blk, [21, 22, 23]), 1, np.where(np.isin(blk, [11, 12, 13]), 0, 3)))
    pq80 = w["pq80"].astype(np.float32).astype(np.float64)
    v54f = x["v54"].astype(np.float32).astype(np.float64)
    pq = np.where(mask & (pq80 != -9999.0), pq80, 0.0)
    v54 = np.where(mask & (v54f != -9999.0), v54f, 0.0)
    assert len(ct) == 3 and list(ct["GISJOIN"]) == ["G0100010", "G0100030", "G0100050"]
    for i, z in enumerate((1, 2, 3)):
        r = ct.iloc[i]
        m = mask & (zones == z)
        u = m & (ctype > 0)
        assert np.isclose(r["census_pop_1980"], x["pops"][i])
        assert np.isclose(r["pop_v57"], v57[m].sum()) and np.isclose(r["pop_ghs"], ghs[m].sum())
        assert np.isclose(r["pop_pq5"], pq[m].sum()) and np.isclose(r["pop_v54"], v54[m].sum())
        for k, a in (("ghs", ghs), ("v57", v57), ("pq5", pq), ("v54", v54)):
            assert np.isclose(r[f"unbuilt_share_{k}"], a[u].sum() / a[m].sum())
            assert np.isclose(r[f"undated_share_{k}"], a[m & (ctype == 1)].sum() / a[m].sum())
        assert np.isclose(r["gap"], ghs[u].sum() / ghs[m].sum() - v57[u].sum() / v57[m].sum())
        assert np.isclose(r["ghs_over_census"], ghs[m].sum() / x["pops"][i])
        assert np.isclose(r["ghs_pop_outside_mask"], ghs[~mask & (zones == z)].sum())
        assert np.isclose(r["bs_unbuilt_share"], bs[u].sum() / bs[m].sum())
        assert np.isclose(r["bs_no_record_share"], bs[m & (ctype == 2)].sum() / bs[m].sum())
        assert r["n_cells_built"] == (m & (ctype == 0)).sum() and r["n_cells_no_record"] == (m & (ctype == 2)).sum()
        us, rs = ghs[m & (cls == 2)].sum() / ghs[m].sum(), ghs[m & (cls == 0)].sum() / ghs[m].sum()
        want = "city" if us >= 0.5 else "rural" if rs >= 0.5 else "town_suburb"
        assert r["county_class"] == want and np.isclose(r["ghs_share_urban_centre"], us)
        o = db.overlap_metrics(v57[u], ghs[u])
        assert np.isclose(r["ov_dist"], o["overlap_dist"]) and np.isclose(r["ov_random"], o["overlap_random"])
        assert np.isclose(r["ov_spearman"], o["spearman_all_cells"])
    # by class: all x all = sums over the counties; a class row by hand
    a = bc[(bc["county_class"] == "all") & (bc["cell_class"] == "all")].iloc[0]
    assert np.isclose(a["pop_ghs"], ct["pop_ghs"].sum()) and a["n_counties"] == 3
    used = mask & np.isin(zones, [1, 2, 3])
    assert np.isclose(a["unbuilt_share_v57"], v57[used & (ctype > 0)].sum() / v57[used].sum())
    for c in bc["county_class"].unique():
        if c == "all":
            continue
        zs = [z for z, cc in zip((1, 2, 3), ct["county_class"]) if cc == c]
        sel = mask & np.isin(zones, zs)
        r = bc[(bc["county_class"] == c) & (bc["cell_class"] == "rural")].iloc[0]
        mm = sel & (cls == 0)
        assert np.isclose(r["pop_ghs"], ghs[mm].sum())
        if ghs[mm].sum() > 0:
            assert np.isclose(r["unbuilt_share_ghs"], ghs[mm & (ctype > 0)].sum() / ghs[mm].sum())
        o = db.overlap_metrics(v57[mm & (ctype > 0)], ghs[mm & (ctype > 0)])
        assert np.isclose(r["ov_v57_amount"], o["overlap_amount"], equal_nan=True)
        r = bc[(bc["county_class"] == c) & (bc["cell_class"] == "all")].iloc[0]
        gp = ct.loc[ct["county_class"] == c, "gap"]
        assert np.isclose(r["gap_median"], gp.median()) and np.isclose(r["gap_p90"], gp.quantile(0.9))
    # capture by an independent loop
    um = used & (ctype > 0)
    grp = zones[um]
    plf = x["plural"].astype(np.float32).astype(np.float64)
    pl = np.where(plf == -1.0, np.nan, plf)[um]
    G = ghs[um].sum()
    for score, sv in (("v57", v57[um]), ("plural_inv", 1 - pl), ("nobuilt", nb[um])):
        for k in (0.05, 0.2):
            r = cap[(cap["subset"] == "all") & (cap["ranking"] == "within_county") & (cap["score"] == score)
                    & (cap["k"] == k)].iloc[0]
            assert np.isclose(r["value"], capture_by_hand(grp, sv, ghs[um], k) / G), (score, k)
            r = cap[(cap["subset"] == "all") & (cap["ranking"] == "conus") & (cap["score"] == score)
                    & (cap["k"] == k)].iloc[0]
            assert np.isclose(r["value"], capture_by_hand(np.zeros(len(grp)), sv, ghs[um], k) / G)
    r = cap[(cap["subset"] == "all") & (cap["score"] == "plural_inv") & (cap["metric"] == "spearman")].iloc[0]
    ok = np.isfinite(pl)
    assert np.isclose(r["value"], spearmanr(1 - pl[ok], ghs[um][ok])[0]) and r["n_cells_no_score"] == (~ok).sum()
    assert set(cap["score"]) == {"ghs", "plural_inv", "v57", "pq5", "nobuilt", "random"}
    # one strip of the whole window = strips of 16 rows
    one = tmp / "missed_one"
    assert mc.main(base + ["--out-dir", str(one), "--block-rows", "240"]) == 0
    for f in ("county_missed_1980.csv", "by_class_1980.csv", "plural_capture_1980.csv"):
        a1, a2 = pd.read_csv(out / f), pd.read_csv(one / f)
        num = a1.select_dtypes("number").columns
        assert a1.drop(columns=num).equals(a2.drop(columns=num))
        assert np.allclose(a1[num].to_numpy(float), a2[num].to_numpy(float), rtol=1e-9, equal_nan=True), f
    # a changed box number / census number stops with nothing written
    bad = tmp / "cts_bad.csv"
    t = pd.read_csv(w["deg"] / "cell_type_shares.csv")
    i = t[(t["box"] == "rural_r1") & (t["year"] == 1980) & (t["scheme"] == "A") & (t["class"] == "all")
          & (t["cell_type"] == "bui0_no_record")].index[0]
    t.loc[i, "pop_v57"] += 1.0
    t.to_csv(bad, index=False)
    b2 = [a if a != str(w["deg"] / "cell_type_shares.csv") else str(bad) for a in base]
    assert "rural_r1 bui0_no_record v57" in expect_exit(mc.main, b2 + ["--out-dir", str(tmp / "x1")])
    assert not (tmp / "x1").exists()
    zc = w["cut"] / "conus" / "zones" / "zones_1980.csv"
    shutil.copy(zc, tmp / "zones_keep.csv")
    z = pd.read_csv(zc)
    z.loc[1, "pop"] *= 1.01
    z.to_csv(zc, index=False)
    assert "census" in expect_exit(mc.main, base + ["--out-dir", str(tmp / "x2")]) and not (tmp / "x2").exists()
    shutil.copy(tmp / "zones_keep.csv", zc)
    print("ok run: county rows / by-class rows / capture by hand, box sums MATCH, strips = whole window, checks stop")


def test_real_config():
    from external_compare import load_config
    cfg = load_config(REPO / "configs" / "external_grids.yaml")
    m = mc.mc_config(cfg)
    assert m["year"] == 1980 and m["mask_map"] == "v57"
    assert m["maps"] == {"v57": "Dasy_CONUS_RF_v3_all_nby", "pq5": "Dasy_CONUS_RF_v3_all_nby_pq5",
                         "v54": "Dasy_CONUS_RF_v3_all"}
    assert m["county_rule"] == {"city_urban_share": 0.5, "rural_share": 0.5}
    assert "ghs_built" not in cfg["products"]           # not a population product of the tract comparison
    rb = db.rb_config(cfg)
    assert {rb["version"], *rb["extra_versions"]} <= set(m["maps"].values())
    model = mc.model_settings(REPO / m["model_config"])
    assert model["name"] == "conus" and model["version"] == m["maps"]["v57"] and model["block_rows"] % 4 == 0
    print("ok real config: missed_cells block, model settings, box versions among the maps")


if __name__ == "__main__":
    test_real_config()
    with tempfile.TemporaryDirectory() as d:
        test_product_strips(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_classes(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_capture(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_run(Path(d))
    print("ALL OK")
