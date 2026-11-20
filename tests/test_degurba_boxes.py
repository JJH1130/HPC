"""Synthetic test of src/validation/degurba_boxes.py (DEGURBA boxes; docs/handoff/rural_boxes_request.md):

    python tests/test_degurba_boxes.py      (needs the hisdac env: rasterio, pyproj, geopandas, scipy, matplotlib)

  test_smod_cells     SMOD code of the SMOD cell each 250 m cell centre falls in (aligned, shifted, Mollweide grid =
                      by hand with pyproj), nodata; block majority with ties to the higher code; scheme A classes
  test_own_rules      scheme B by hand: 4-connected centres (a diagonal pair is two centres), 50,000 / 5,000 people,
                      gap filling (8-connected non-centre group enclosed by one centre, 14 blocks filled, 15 not,
                      open to the edge / diagonal leak / two centres not), edge smoothing 5 of 8 repeated (a block
                      added only in the second pass), 8-connected clusters, centres
                      not counted as clusters; the box + margin window keeps a centre that crosses the box edge
                      (margin 0 cuts it below 50,000)
  test_candidate_order median (odd / even = lower middle), ties by GISJOIN, next by |density - median| (tie -> lower)
  test_select         synthetic counties / SMOD / v5.7: candidates (no_value status and a county without land cells
                      left out), median, 50 km from a city and from a chosen box, a box outside the counties, the
                      chosen boxes by hand, boxes_selected.csv numbers by hand, the config written and read back, a
                      second select refused, an unknown SMOD code stops
  test_run            end to end on the city world of test_external_city_meeting (+ SMOD, one chosen box): A / B class
                      rows by hand, classes add up, pooled box-type rows, totals side by side, cell types add up, city
                      boxes = the meeting numbers (a changed one stops with nothing written), PNGs; the earlier
                      city_density_classes_v57 outputs are not touched
  test_overlap_metrics overlap of the distributions / amounts, random baseline, Spearman by hand; a map with itself
                      = 1, two maps without a shared cell = 0; the pairs of a year
                      (test_run also runs `overlap`: per group / subset / pair by hand for the rural box and the pooled
                      city boxes, the run's tables untouched, a changed cell_type_shares sum stops)
  test_real_config    the rural_boxes block of configs/external_grids.yaml (rules; boxes empty or 8 boxes)
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
from rasterio.transform import from_origin  # noqa: E402
from rasterio.windows import Window  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

import degurba_boxes as db  # noqa: E402
import external_city_maps as ecm  # noqa: E402
import external_city_meeting as mt  # noqa: E402
from test_external_city_maps import write  # noqa: E402
from test_external_city_meeting import OUR, make_world  # noqa: E402

CODES = {30: "urban centre", 23: "duc", 22: "sduc", 21: "suburban", 13: "rural cluster", 12: "low", 11: "very low",
         10: "water"}
SCHEME_A = {"urban": [30], "peri_urban": [21, 22, 23], "rural": [11, 12, 13]}
RULES = {"centre": {"min_density": 1500, "connectivity": 4, "min_pop": 50000},
         "cluster": {"min_density": 300, "connectivity": 8, "min_pop": 5000}, "margin_km": 20,
         "gap_fill_max_km2": 15, "smooth_min_neighbours": 5}


def write_int(path: Path, a: np.ndarray, transform, crs, nodata):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=a.shape[1], height=a.shape[0], count=1, dtype="int16",
                       crs=crs, transform=transform, nodata=nodata) as d:
        d.write(a.astype("int16"), 1)


def test_smod_cells(tmp: Path):
    s = np.array([[11, 12, 30], [10, -200, 22], [13, 21, 23]])
    write_int(tmp / "a.tif", s, from_origin(0.0, 3000.0, 1000.0, 1000.0), OUR, -200)
    got = db.smod_on_cells(tmp / "a.tif", from_origin(0.0, 3000.0, 250.0, 250.0), (12, 12), OUR)
    want = np.kron(np.where(s == -200, db.NODATA, s), np.ones((4, 4), int))
    assert np.array_equal(got, want)
    # shifted box: centres of 250 m cells starting 125 m west of the grid -> first column off the raster (nodata)
    got = db.smod_on_cells(tmp / "a.tif", from_origin(-250.0, 3000.0, 250.0, 250.0), (4, 8), OUR)
    xc = -250.0 + (np.arange(8) + 0.5) * 250
    col = np.floor(xc / 1000).astype(int)
    exp = np.array([s[0, c] if 0 <= c < 3 else db.NODATA for c in col])
    assert np.array_equal(got[0], exp), (got[0], exp)
    # Mollweide SMOD: by hand with pyproj
    m = np.arange(400).reshape(20, 20) % 7 + 10
    tr = Transformer.from_crs(OUR, "ESRI:54009", always_xy=True)
    mx, my = tr.transform(1_000_000.0, 2_000_000.0)
    mt0 = from_origin(np.floor(mx / 1000) * 1000 - 8000, np.floor(my / 1000) * 1000 + 8000, 1000.0, 1000.0)
    write_int(tmp / "m.tif", m, mt0, "ESRI:54009", -200)
    bt = from_origin(1_000_000.0 - 2000, 2_000_000.0 + 2000, 250.0, 250.0)
    got = db.smod_on_cells(tmp / "m.tif", bt, (16, 16), OUR)
    for i, j in ((0, 0), (5, 11), (15, 15), (8, 3)):
        x, y = bt * (j + 0.5, i + 0.5)
        sx, sy = tr.transform(x, y)
        c, r = ~mt0 * (sx, sy)
        assert got[i, j] == m[int(np.floor(r)), int(np.floor(c))]
    # block majority: ties -> the higher code
    codes = np.array([[11, 11, 30, 30], [12, 13, 30, 22], [10, 10, 21, 21], [10, 11, 21, 22]])
    b = db.block_majority(codes, 2)
    # block (0,0): 11 x2, 12, 13 -> 11; (0,1): 30 x3 -> 30; (1,0): 10 x3 -> 10; (1,1): 21 x3 -> 21
    assert b.tolist() == [[11, 30], [10, 21]]
    tie = np.array([[11, 30], [11, 30]])
    assert db.block_majority(tie, 2).tolist() == [[30]]
    tie2 = np.array([[10, 11], [db.NODATA, db.NODATA]])
    assert db.block_majority(tie2, 2).tolist() == [[db.NODATA]]   # nodata x2 beats 10 / 11 once each
    tie3 = np.array([[10, 10], [11, 11]])
    assert db.block_majority(tie3, 2).tolist() == [[11]]          # water vs rural tie -> rural (higher)
    a = db.scheme_a(np.array([30, 23, 21, 13, 11, 10, db.NODATA, 22]), SCHEME_A)
    assert a.tolist() == [2, 1, 1, 0, 0, 3, 3, 1]
    assert db.check_codes(np.array([10, 30, db.NODATA]), CODES, "x") == {db.NODATA: 1, 10: 1, 30: 1}
    try:
        db.check_codes(np.array([10, 31]), CODES, "x")
    except SystemExit as e:
        assert "[31]" in str(e)
    else:
        raise AssertionError("unknown code accepted")
    print("ok smod cells: centre -> SMOD cell (aligned, shifted, Mollweide), nodata, block majority ties, scheme A")


def test_own_rules(tmp: Path):
    z = np.zeros((12, 12))
    # centre 1: 3 x 3 ring of 6,000 per km2 blocks around a 0 hole -> 8 x 6,000 = 48,000 < 50,000 ... add one block
    z[1:4, 1:4] = 6000.0
    z[2, 2] = 0.0                       # hole (all four sides in the centre)
    z[1, 4] = 3000.0                    # 51,000 people, 4-connected
    # two dense blocks touching only diagonally: 4-connectivity -> separate, each 40,000 < 50,000 -> no centre;
    # 8-connected cluster of 80,000 -> peri_urban
    z[8, 8] = 40000.0
    z[9, 9] = 40000.0
    # a cluster of 300+ blocks: 4 blocks x 1,300 = 5,200 >= 5,000 (diagonal chain, 8-connected)
    z[8, 1], z[9, 2], z[10, 3], z[11, 4] = 1300.0, 1300.0, 1300.0, 1300.0
    # a 300+ group with 4,900 people: rural
    z[5, 9], z[5, 10] = 2450.0, 2450.0
    # a hole with only 3 sides in a centre (open to the edge of the centre): not filled
    cls, info = db.own_classes(z, 1.0, RULES)
    assert info["n_centres"] == 1 and info["gap_blocks_filled"] == 1, info
    assert info["smoothing_blocks_added"] == 0, info                 # no outside block has 5 centre neighbours
    assert cls[2, 2] == 2 and (cls[1:4, 1:4] == 2).all() and cls[1, 4] == 2
    assert cls[8, 8] == cls[9, 9] == 1                               # no centre (4-conn), cluster (8-conn)
    assert cls[8, 1] == cls[11, 4] == 1                              # diagonal chain cluster
    assert cls[5, 9] == cls[5, 10] == 0                              # 4,900 < 5,000
    assert cls[0, 0] == 0 and (cls == 2).sum() == 10
    # the centre is not also a cluster: its blocks are 2, never 1
    z2 = z.copy()
    z2[1, 4] = 1000.0                                                # 49,000: no centre; blocks >= 300 -> cluster
    c2, i2 = db.own_classes(z2, 1.0, RULES)
    assert i2["n_centres"] == 0 and c2[2, 2] == 0 and c2[1, 1] == 1
    # gap filling: enclosed by one centre and < 15 blocks (1 km2 blocks: < 15 km2)
    lab = np.ones((8, 11), int)
    lab[2:4, 2:9] = 0                                                # 2 x 7 = 14 blocks: filled
    assert (db.fill_gaps(lab, 15) == 1).all()
    lab = np.ones((9, 11), int)
    lab[2:5, 2:7] = 0                                                # 3 x 5 = 15 blocks: not filled
    assert np.array_equal(db.fill_gaps(lab, 15), lab)
    assert (db.fill_gaps(lab, 16) == 1).all()                        # (the same gap with a larger limit)
    lab = np.ones((6, 6), int)
    lab[2, 2] = lab[1, 1] = lab[0, 0] = 0                            # diagonal chain to the window edge: not enclosed
    assert np.array_equal(db.fill_gaps(lab, 15), lab)
    lab[0, 0] = 1                                                    # now enclosed (2 blocks): filled
    assert (db.fill_gaps(lab, 15) == 1).all()
    lab = np.ones((6, 6), int)
    lab[:, 3:] = 2
    lab[2, 2] = lab[2, 3] = 0                                        # a gap between two centres: not filled
    assert np.array_equal(db.fill_gaps(lab, 15), lab)
    lab = np.ones((5, 7), int)
    lab[0, 3] = lab[1, 3] = 0                                        # open to the window edge: not filled
    assert np.array_equal(db.fill_gaps(lab, 15), lab)
    # edge smoothing, repeated: a 2-block notch in a 5 x 5 centre; (3, 4) has 7 centre neighbours -> pass 1;
    # (2, 4) has 4 before and 5 after -> pass 2; pass 3 adds nothing; nothing else reaches 5
    lab = np.zeros((9, 9), int)
    lab[2:7, 2:7] = 1
    lab[2, 4] = lab[3, 4] = 0
    assert np.array_equal(db.fill_gaps(lab, 15), lab)                # the notch is open: no gap
    sm, passes = db.smooth_edges(lab, 5)
    want = np.zeros((9, 9), int)
    want[2:7, 2:7] = 1
    assert np.array_equal(sm, want) and passes == 3, (sm, passes)
    one = lab.copy()
    one[3, 4] = 1                                                    # after pass 1 only: (2, 4) still out
    assert one[2, 4] == 0 and not np.array_equal(one, sm)
    # in own_classes: the 14-block gap of a centre is filled (after the 50,000 test), the 15-block gap is not filled
    # as a gap (smoothing may still add blocks of it, counted apart)
    for n_rows, n_cols, filled in ((2, 7, 14), (3, 5, 0)):
        zz = np.zeros((14, 14))
        zz[2:2 + n_rows + 4, 2:2 + n_cols + 4] = 2000.0
        zz[4:4 + n_rows, 4:4 + n_cols] = 0.0
        _, ii = db.own_classes(zz, 1.0, RULES)
        assert ii["n_centres"] == 1 and ii["gap_blocks_filled"] == filled, ii
    # margin: a centre of 60,000 people crossing the box edge (only 20,000 inside the box)
    gt = from_origin(0.0, 40_000.0, 250.0, 250.0)
    a = np.zeros((160, 160), "float32")                              # 40 x 40 km, 1 km blocks = 4 x 4 cells
    a[60:72, 56:80] = 5000.0 / 16                                    # 3 x 6 blocks x 5,000 = 90,000 per km2 >= 1,500
    write(tmp / "v.tif", a, gt, OUR, -9999.0)
    win = Window(68, 40, 40, 40)                                     # a 10 km box; centre blocks cols 56-80 -> 3 inside
    rules = {**RULES, "margin_km": 5}
    cb, _ = db.own_classes_box(tmp / "v.tif", win, gt, 4, rules)
    assert cb.shape == (10, 10)
    inside = np.zeros((10, 10), bool)
    inside[5:8, 0:3] = True                                          # rows 60-72 -> blocks 15-17 - 10; cols 68-80 -> 17-19 - 17
    assert (cb[inside] == 2).all() and (cb[~inside] == 0).all(), cb
    cb0, _ = db.own_classes_box(tmp / "v.tif", win, gt, 4, {**RULES, "margin_km": 0})
    assert (cb0[inside] == 1).all()                                  # cut: 45,000 in the box -> not a centre
    print("ok own rules: 4- / 8-connectivity, 50,000 / 5,000, gaps < 15 blocks, 5 / 8 smoothing repeated, margin "
          "keeps a centre at the box edge")


def test_candidate_order():
    t = pd.DataFrame({"GISJOIN": ["G5", "G1", "G3", "G2", "G4"], "density": [10.0, 20.0, 30.0, 40.0, 30.0]})
    o = db.candidate_order(t)   # sorted 10 20 30(G3) 30(G4) 40 -> median 30, G3 first, G4 next, then 20 / 40 -> 20
    assert o["GISJOIN"].tolist() == ["G3", "G4", "G1", "G2", "G5"] and o["median_density"].iloc[0] == 30
    o = db.candidate_order(t.iloc[:4])   # 10 20 30 40: lower middle 20 -> 20, then 10 / 30 tie -> 10, 30, 40
    assert o["GISJOIN"].tolist() == ["G1", "G5", "G3", "G2"] and o["n_candidates"].iloc[0] == 4
    print("ok candidate order: median (lower middle), GISJOIN tie, next by distance (tie -> lower density)")


# ---------------------------------------------------------------- select world

X0, Y1 = 1_000_000.0, 2_000_000.0


def col_x(i):  # column i: x range; column 0 is 20 km wide (its boxes reach outside the counties)
    return (X0, X0 + 20_000) if i == 0 else (X0 + 20_000 + 40_000 * (i - 1), X0 + 20_000 + 40_000 * i)


def centre(i, j):
    a, b = col_x(i)
    return (a + b) / 2, Y1 - 20_000 - 40_000 * j


def select_world(tmp: Path) -> dict:
    import geopandas as gpd
    from shapely.geometry import box
    # (i, j): (type, density, status, gisjoin index); every other county urban
    spec = {(0, 2): ("rural", 10), (1, 2): ("rural", 20), (3, 2): ("rural", 30), (3, 4): ("rural", 40),
            (1, 4): ("water", 25),
            (2, 1): ("peri", 100), (2, 3): ("peri", 200), (4, 3): ("peri", 200), (4, 1): ("peri", 300),
            (6, 2): ("rural", 5), (8, 2): ("rural", 7), (7, 4): ("rural", 6), (6, 1): ("rural", 5.5),
            (7, 3): ("peri", 50), (5, 1): ("peri", 60)}
    smod = np.full((240, 380), 30, np.int64)
    rows = []
    for i in range(10):
        for j in range(6):
            a, b = col_x(i)
            typ, d = spec.get((i, j), ("urban", 1000.0))
            st = "01" if i <= 4 else "02"
            idx = 100 + 10 * i + j
            if (i, j) == (4, 3):
                idx = 1                                         # same density as (2, 3), smaller GISJOIN
            c0, c1 = int((a - X0) / 1000), int((b - X0) / 1000)
            r0 = 40 * j
            blk = smod[r0:r0 + 40, c0:c1]
            blk[:] = {"rural": 11, "peri": 12, "urban": 12, "water": 10}[typ]
            blk[::3, ::5] = 13 if typ != "water" else 10
            if typ == "peri":
                blk[5, 5] = 22
            if typ == "urban":
                blk[5, 5], blk[6, 6] = 30, 23
            area = (b - a) * 40_000 / 1e6
            rows.append({"GISJOIN": f"G{st}0{idx:03d}0", "fips": f"{st}{idx:03d}", "state": st, "name": f"C{i}{j}",
                         "pop": d * area, "status": "no_value" if (i, j) == (6, 1) else "ok", "area_km2": area,
                         "geometry": box(a, Y1 - 40_000 * (j + 1), b, Y1 - 40_000 * j), "ij": (i, j)})
    g = gpd.GeoDataFrame(rows, crs=OUR)
    cen = tmp / "census"
    cen.mkdir(parents=True, exist_ok=True)
    g.drop(columns=["ij"]).to_file(cen / "counties_2010.gpkg", driver="GPKG")
    data = tmp / "data"
    write_int(data / "smod" / "smod_2010.tif", smod, from_origin(X0, Y1, 1000.0, 1000.0), OUR, -200)
    # v5.7 on a 250 m grid 10 km larger on every side; nodata strip
    gt = from_origin(X0 - 10_000, Y1 + 10_000, 250.0, 250.0)
    p10 = np.ones((1040, 1600), "float32")
    p10[500:520, :] = -9999.0
    pred = tmp / "dasym" / "conus" / "V57" / "predictions"
    write(pred / "pop_2010.tif", p10, gt, OUR, -9999.0)
    write(pred / "pop_1980.tif", np.where(p10 > 0, 0.5, p10), gt, OUR, -9999.0)
    to_ll = Transformer.from_crs(OUR, "EPSG:4326", always_xy=True)
    lon, lat = to_ll.transform(*centre(1, 2))                   # a city on county (1, 2)
    cfg = {"products": {}, "city_maps": {"box_km": 40, "subpixel_m": 25,
                                         "cities": {"town": {"label": "Town", "lon": lon, "lat": lat}}},
           "rural_boxes": {"version": "V57", "version_label": "v5.7", "extra_versions": {},
                           "years": {2010: ["ghs_pop"], 1980: ["ghs_pop"]}, "cities": ["town"], "box_km": 40,
                           "smod": {"label": "smod", "path": "smod/smod_{YEAR}.tif", "years": [1980, 2010],
                                    "select_year": 2010, "codes": CODES, "scheme_a": SCHEME_A},
                           "own_rules": RULES,
                           "select": {"counties": "counties_2010.gpkg", "train_status": ["ok", "filled_nhgis"],
                                      "min_dist_km": 50, "outside_tol": 0.001,
                                      "regions": {"R1": ["01"], "R2": ["02"]}},
                           "boxes": {}}}
    cp = tmp / "ext.yaml"
    cp.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return dict(cp=cp, data=data, cen=cen, dasym=tmp / "dasym", gt=gt, p10=p10, smod=smod, g=g)


def test_select(tmp: Path):
    w = select_world(tmp)
    out = tmp / "out"
    run = ["select", "--config", str(w["cp"]), "--data-root", str(w["data"]), "--dasym-root", str(w["dasym"]),
           "--census-dir", str(w["cen"]), "--out-dir", str(out)]
    assert db.main(run + ["--check"]) == 0 and not out.exists()
    assert db.main(["status", "--config", str(w["cp"])]) == 0
    assert db.main(run) == 0
    boxes = yaml.safe_load(w["cp"].read_text())["rural_boxes"]["boxes"]
    # R1 rural: candidates 10 (outside) 20 (city) 30 40 (25 = no land cell) -> median 20 refused (city), 10 / 30
    # tie -> 10 refused (outside), 30 chosen = (3, 2). R1 peri: 100 200 200(G...0010) 300 -> lower middle 200, the
    # smaller GISJOIN (4, 3). R2 rural: 5 6 7 (5.5 is no_value) -> 6 = (7, 4). R2 peri: 50 60 -> 50 = (7, 3) is 40 km
    # from (7, 4) -> 60 = (5, 1).
    want = {"rural_r1": (3, 2), "peri_urban_r1": (4, 3), "rural_r2": (7, 4), "peri_urban_r2": (5, 1)}
    assert list(boxes) == list(want), list(boxes)
    for k, (i, j) in want.items():
        cx, cy = centre(i, j)
        assert np.isclose(boxes[k]["x"], cx) and np.isclose(boxes[k]["y"], cy), (k, boxes[k])
        assert boxes[k]["box_type"] == k.rsplit("_", 1)[0] and boxes[k]["crs"] == OUR
    t = pd.read_csv(out / "boxes_selected.csv")
    r = t.set_index("box")
    assert r.loc["rural_r1", "candidate_order"] == 2 and r.loc["rural_r1", "n_candidates"] == 4
    assert r.loc["rural_r1", "median_density"] == 20 and r.loc["peri_urban_r2", "candidate_order"] == 1
    assert r.loc["rural_r2", "n_candidates"] == 3
    # numbers in the box by hand: v5.7 people (1 per valid cell), outside-mask share, SMOD shares
    gt, p10, smod = w["gt"], w["p10"], w["smod"]
    for k, (i, j) in want.items():
        cx, cy = centre(i, j)
        win = ecm.box_window(gt, cx, cy, 40)
        r0, c0 = int(win.row_off), int(win.col_off)
        sub = p10[r0:r0 + 160, c0:c0 + 160]
        assert sub.shape == (160, 160)
        assert np.isclose(r.loc[k, "pop_v57_2010"], (sub > 0).sum())
        assert np.isclose(r.loc[k, "pop_v57_1980"], 0.5 * (sub > 0).sum())
        assert np.isclose(r.loc[k, "share_cells_outside_mask"], (sub <= 0).mean())
        x0 = gt.c + c0 * 250 + 125
        y0 = gt.f - r0 * 250 - 125
        cols = np.floor((x0 + 250 * np.arange(160) - X0) / 1000).astype(int)
        rws = np.floor((Y1 - (y0 - 250 * np.arange(160))) / 1000).astype(int)
        codes = smod[np.ix_(rws, cols)]
        for c in (11, 12, 13, 30):
            assert np.isclose(r.loc[k, f"smod_share_{c}"], (codes == c).mean()), (k, c)
    # a second select is refused; status says SET
    try:
        db.main(run)
    except SystemExit as e:
        assert "filled already" in str(e)
    else:
        raise AssertionError("second select accepted")
    cfg = yaml.safe_load(w["cp"].read_text())
    assert cfg["rural_boxes"]["select"]["min_dist_km"] == 50                  # rest of the config unchanged
    # an unknown SMOD code stops the select
    w2 = select_world(tmp / "w2")
    s = w2["smod"].copy()
    s[100, 100] = 31
    write_int(w2["data"] / "smod" / "smod_2010.tif", s, from_origin(X0, Y1, 1000.0, 1000.0), OUR, -200)
    try:
        db.main(["select", "--config", str(w2["cp"]), "--data-root", str(w2["data"]), "--dasym-root",
                 str(w2["dasym"]), "--census-dir", str(w2["cen"]), "--out-dir", str(tmp / "w2" / "out")])
    except SystemExit as e:
        assert "[31]" in str(e), e
    else:
        raise AssertionError("unknown SMOD code accepted")
    assert yaml.safe_load(w2["cp"].read_text())["rural_boxes"]["boxes"] == {}
    print("ok select: candidates, median / even / tie, 50 km (city, chosen box), outside the counties, numbers by "
          "hand, config written once, unknown code stops")


# ---------------------------------------------------------------- run

def test_run(tmp: Path):
    w = make_world(tmp)
    cfg = yaml.safe_load(w["cp"].read_text())
    cfg["city_density"] = {"class_product": "ghs_pop", "breaks": [100, 1000],
                           "classes": ["rural", "peri_urban", "urban"], "ratio_band": 4}
    hd = ["--hisdac-dir", str(w["hisdac"])]
    base_out, new_out = tmp / "meet", tmp / "meet57"
    w["cp"].write_text(yaml.safe_dump(cfg, sort_keys=False))
    mt.main(w["base"] + hd + ["--out-dir", str(base_out)])
    pop57, pop57_80 = w["pop"].copy(), np.where(w["pop80"] >= 0, w["pop80"] * 1.1, w["pop80"])
    pop57[116:124, 116:132] = 250.0
    p57 = w["dasym"] / "conus" / "V57" / "predictions"
    write(p57 / "pop_2010.tif", pop57, w["gt"], OUR, -9999.0)
    write(p57 / "pop_1980.tif", pop57_80, w["gt"], OUR, -9999.0)
    pq = w["dasym"] / "conus" / "V57PQ5" / "predictions"
    write(pq / "pop_2010.tif", np.where(pop57 >= 0, pop57 * 0.9, pop57), w["gt"], OUR, -9999.0)
    write(pq / "pop_1980.tif", np.where(pop57_80 >= 0, pop57_80 * 1.2, pop57_80), w["gt"], OUR, -9999.0)
    mt.main(w["base"] + hd + ["--out-dir", str(new_out), "--version", "V57", "--version-label", "v5.7", "--base-dir",
                              str(base_out)])
    side = new_out / "meeting_summary_v56_v57.csv"
    # SMOD on our grid (1 km, aligned with the blocks): one code per block, by design
    gt = w["gt"]
    n = 60
    rng = np.random.default_rng(3)
    s10 = rng.choice([11, 12, 13, 21, 22, 23, 30, 10], size=(n, n), p=[.3, .1, .1, .1, .1, .1, .2, .0])
    s10[30:32, 30:33] = 10
    s10[5, 5] = -200
    s80 = np.where(s10 == 30, 23, s10)
    for y, s in ((2010, s10), (1980, s80)):
        write_int(w["data"] / "smod" / f"smod_{y}.tif", s, from_origin(gt.c, gt.f, 1000.0, 1000.0), OUR, -200)
    cx, cy = gt.c + 250 * 152, gt.f - 250 * 80 - 125           # box window rows 56-104, cols 128-176 (whole blocks)
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
    out = tmp / "deg"
    run = ["run", "--config", str(w["cp"]), "--data-root", str(w["data"]), "--dasym-root", str(w["dasym"]),
           "--cutout-root", str(w["cut"]), "--check-with", str(side), "--out-dir", str(out)] + hd
    assert db.main(run + ["--check"]) == 0 and not out.exists()
    assert db.main(run) == 0
    t = pd.read_csv(out / "density_class_summary.csv")
    ct = pd.read_csv(out / "cell_type_shares.csv")
    side_t = pd.read_csv(out / "totals_side_by_side.csv")
    bc = pd.read_csv(out / "box_classes.csv")
    assert set(t["box"]) == {"boston", "chicago", "rural_r1", "all_city", "all_rural"}
    assert set(t["scheme"]) == {"A", "B"} and set(t["version_label"]) == {"v5.7", "v5.7_pq5"}
    # by hand, the rural box: A classes from the SMOD block code, people per class
    cfgp = cfg["products"]
    for year, prods in ((2010, ["ghs_pop", "worldpop"]), (1980, ["ghs_pop"])):
        win = ecm.box_window(gt, cx, cy, 12)
        path = p57 / f"pop_{year}.tif"
        vp, mask, bt = ecm.read_box(path, win, gt)
        full = ecm.block_sums(mask.astype(int), 4) == 16
        vb = ecm.block_sums(np.where(mask, vp, 0.0), 4)[full]
        r0, c0 = int(win.row_off) // 4, int(win.col_off) // 4
        assert int(win.row_off) % 4 == 0 and int(win.col_off) % 4 == 0
        sc = (s10 if year == 2010 else s80)[r0:r0 + 12, c0:c0 + 12][full]
        cls = np.where(np.isin(sc, [30]), "urban", np.where(np.isin(sc, [21, 22, 23]), "peri_urban",
                                                            np.where(np.isin(sc, [11, 12, 13]), "rural", "excluded")))
        for prod in prods:
            g, _ = ecm.to_grid(w["data"] / cfgp[prod]["path"].replace("{YEAR}", str(year)), bt, vp.shape, OUR, 25)
            gb = ecm.block_sums(np.where(mask, g, 0.0), 4)[full]
            for c in ("rural", "peri_urban", "urban", "excluded", "all"):
                m = np.ones(len(cls), bool) if c == "all" else cls == c
                r = t[(t["box"] == "rural_r1") & (t["year"] == year) & (t["scheme"] == "A") & (t["version"] == "V57")
                      & (t["product"] == prod) & (t["class"] == c)].iloc[0]
                assert r["n_blocks"] == m.sum(), (year, prod, c)
                assert np.isclose(r["pop_version"], vb[m].sum()) and np.isclose(r["pop_product"], gb[m].sum())
            # B classes = own_classes on the box + 4 km margin, by hand
            ew = Window(win.col_off - 16, win.row_off - 16, 80, 80)
            a, valid, _ = ecm.read_box(path, ew, gt)
            cb, _ = db.own_classes(ecm.block_sums(np.where(valid, a, 0.0), 4), 1.0, RULES)
            cb = cb[4:16, 4:16][full]
            for i, c in enumerate(db.CLASSES):
                r = t[(t["box"] == "rural_r1") & (t["year"] == year) & (t["scheme"] == "B") & (t["version"] == "V57")
                      & (t["product"] == prod) & (t["class"] == c)].iloc[0]
                assert r["n_blocks"] == (cb == i).sum() and np.isclose(r["pop_version"], vb[cb == i].sum())
        b = bc[(bc["box"] == "rural_r1") & (bc["year"] == year)].iloc[0]
        assert b["blocks_A_excluded"] == (cls == "excluded").sum() and b["n_full_blocks"] == full.sum()
    # pooled city rows = the two city boxes' blocks together
    for col in ("n_blocks", "pop_version", "pop_product"):
        a = t[(t["box"].isin(["boston", "chicago"])) & (t["class"] == "all")].groupby(
            ["year", "scheme", "version", "product"])[col].sum()
        p = t[(t["box"] == "all_city") & (t["class"] == "all")].set_index(["year", "scheme", "version", "product"])[col]
        assert np.allclose(a.sort_index(), p.loc[a.sort_index().index])
    # totals side by side: whole box ratio and full-block ratio = the all rows
    r = side_t[(side_t["box"] == "rural_r1") & (side_t["year"] == 2010) & (side_t["product"] == "ghs_pop")
               & (side_t["version_label"] == "v5.7")].iloc[0]
    a = t[(t["box"] == "rural_r1") & (t["year"] == 2010) & (t["product"] == "ghs_pop") & (t["version"] == "V57")
          & (t["scheme"] == "A") & (t["class"] == "all")].iloc[0]
    assert np.isclose(r["ratio_whole_box"], a["total_pop_box_version"] / a["total_pop_box_product"])
    assert np.isclose(r["ratio_full_blocks"], a["ratio_total"])
    assert {"ratio_A_rural", "ratio_B_rural", "ratio_A_urban"} <= set(side_t.columns)
    # cell types: shares of a box add up to 1, pooled share = summed people / summed people
    s1 = ct[ct["class"] == "all"].groupby(["box", "year", "scheme"])[["share_ghs_pop", "share_v57"]].sum()
    assert np.allclose(s1, 1.0)
    pc = ct[(ct["box"] == "all_city") & (ct["year"] == 2010) & (ct["scheme"] == "A") & (ct["class"] == "all")
            & (ct["cell_type"] == "bui_gt0")].iloc[0]
    one = ct[(ct["box"].isin(["boston", "chicago"])) & (ct["year"] == 2010) & (ct["scheme"] == "A")
             & (ct["class"] == "all")]
    assert np.isclose(pc["share_v57"], one.loc[one["cell_type"] == "bui_gt0", "pop_v57"].sum() / one["pop_v57"].sum())
    pngs = sorted(p.name for p in out.glob("*.png"))
    assert pngs == sorted(["rural_r1_2010.png", "rural_r1_1980.png"] + [f"{b}_{y}_cell_types.png" for b in
                                                                        ("boston", "chicago", "rural_r1")
                                                                        for y in (2010, 1980)]), pngs
    import matplotlib.image as mpimg
    assert len({mpimg.imread(out / p).shape for p in pngs if "cell_types" not in p}) == 1
    # overlap: same boxes and cells; by hand for the rural box and the pooled city boxes
    keep_files = {f: (out / f).read_bytes() for f in ("density_class_summary.csv", "cell_type_shares.csv")}
    ov = ["overlap" if a == "run" else a for a in run]
    assert db.main(ov + ["--check"]) == 0
    assert db.main(ov) == 0
    assert all((out / f).read_bytes() == b for f, b in keep_files.items())     # the run's tables untouched
    o = pd.read_csv(out / "unbuilt_overlap.csv")
    assert (out / "unbuilt_overlap.png").exists()
    assert set(o["group"]) == {"unbuilt", "undated", "no_record", "built"} and set(o["subset"]) == {"all", "rural_A"}
    assert set(zip(o.loc[o["year"] == 1980, "map_a"], o.loc[o["year"] == 1980, "map_b"])) == {
        ("v57", "ghs_pop"), ("v57pq5", "ghs_pop")}
    assert o.loc[o["reference"], ["map_a", "map_b"]].drop_duplicates().values.tolist() == [["ghs_pop", "worldpop"]]

    def cells_by_hand(ccx, ccy, year):
        win = ecm.box_window(gt, ccx, ccy, 12)
        vp, mask, bt = ecm.read_box(p57 / f"pop_{year}.tif", win, gt)
        qp, qmask, _ = ecm.read_box(pq / f"pop_{year}.tif", win, gt)
        full = ecm.block_sums(mask.astype(int), 4) == 16
        sel = np.kron(full, np.ones((4, 4))).astype(bool)
        r0, c0 = int(win.row_off), int(win.col_off)
        bw = (w["bui"] if year == 2010 else w["bui80"])[r0:r0 + 48, c0:c0 + 48]
        nw = w["nby"][r0:r0 + 48, c0:c0 + 48]
        sm = (s10 if year == 2010 else s80)
        codes = sm[np.ix_((r0 + np.arange(48)) // 4, (c0 + np.arange(48)) // 4)]   # SMOD cell of each cell centre
        codes = np.where(codes == -200, db.NODATA, codes)
        maj = np.zeros((12, 12), int)
        for bi in range(12):
            for bj in range(12):
                v, k = np.unique(codes[4 * bi:4 * bi + 4, 4 * bj:4 * bj + 4], return_counts=True)
                maj[bi, bj] = max(zip(k, v))[1]                       # most cells, a tie -> the higher code
        rural = np.kron(full & np.isin(maj, [11, 12, 13]), np.ones((4, 4))).astype(bool)
        maps = {"v57": np.where(mask, vp, 0.0), "v57pq5": np.where(mask & qmask, qp, 0.0)}
        for prod in (["ghs_pop", "worldpop"] if year == 2010 else ["ghs_pop"]):
            g, _ = ecm.to_grid(w["data"] / cfgp[prod]["path"].replace("{YEAR}", str(year)), bt, vp.shape, OUR, 25)
            maps[prod] = np.where(sel, g, 0.0)
        groups = {"unbuilt": bw <= 0, "undated": (bw <= 0) & (nw > 0), "no_record": (bw <= 0) & (nw <= 0),
                  "built": bw > 0}
        return maps, sel, rural, groups

    def by_hand(xs, ys):
        x, y = np.concatenate(xs), np.concatenate(ys)
        n = len(x)
        return (np.minimum(x / x.sum(), y / y.sum()).sum(), np.minimum(x, y).sum() / y.sum(),
                np.minimum(1 / n, y / y.sum()).sum(), n)

    tr = Transformer.from_crs("EPSG:4326", OUR, always_xy=True)
    city_c = {k: tr.transform(cfg["city_maps"]["cities"][k]["lon"], cfg["city_maps"]["cities"][k]["lat"])
              for k in ("boston", "chicago")}
    for year in (2010, 1980):
        hand = {"rural_r1": cells_by_hand(cx, cy, year), **{k: cells_by_hand(*c, year) for k, c in city_c.items()}}
        for sub in ("all", "rural_A"):
            for g in ("unbuilt", "undated", "no_record", "built"):
                for a_, b_ in (("v57", "ghs_pop"), ("v57pq5", "ghs_pop")) + ((("ghs_pop", "worldpop"),) if year == 2010
                                                                           else ()):
                    for box, keys in (("rural_r1", ["rural_r1"]), ("all_city", ["boston", "chicago"])):
                        xs, ys = [], []
                        for k in keys:
                            maps, sel, rural, groups = hand[k]
                            f = sel & groups[g] & (rural if sub == "rural_A" else True)
                            xs.append(maps[a_][f])
                            ys.append(maps[b_][f])
                        r = o[(o["box"] == box) & (o["year"] == year) & (o["subset"] == sub) & (o["group"] == g)
                              & (o["map_a"] == a_) & (o["map_b"] == b_)].iloc[0]
                        if sum(len(v) for v in xs) == 0 or np.concatenate(ys).sum() == 0:
                            continue
                        dist, amount, rnd, n = by_hand(xs, ys)
                        assert r["n_cells"] == n, (box, year, sub, g, a_, b_)
                        if np.concatenate(xs).sum() > 0:
                            assert np.isclose(r["overlap_dist"], dist), (box, year, sub, g, a_, b_)
                        assert np.isclose(r["overlap_amount"], amount) and np.isclose(r["overlap_random"], rnd)
    assert (o["overlap_dist"].dropna().between(0, 1 + 1e-9)).all()
    # a changed people sum in cell_type_shares.csv stops before anything is written
    (out / "unbuilt_overlap.csv").unlink()
    c = pd.read_csv(out / "cell_type_shares.csv")
    c.loc[(c["box"] == "rural_r1") & (c["cell_type"] == "bui0_no_record"), "pop_v57"] += 1.0
    c.to_csv(out / "cell_type_shares.csv", index=False)
    try:
        db.main(ov)
    except SystemExit as e:
        assert "people of v57" in str(e), e
    else:
        raise AssertionError("a changed group sum did not stop the overlap")
    assert not (out / "unbuilt_overlap.csv").exists()
    (out / "cell_type_shares.csv").write_bytes(keep_files["cell_type_shares.csv"])
    # a changed meeting number of a city box stops before anything is written
    keep = side.read_text()
    x = pd.read_csv(side)
    x.loc[(x["table"] == "summary") & (x["measure"] == "total_pop_box") & (x["item"] == "model"), "v5.7"] += 1.0
    x.to_csv(side, index=False)
    out2 = tmp / "deg2"
    try:
        db.main([a if a != str(out) else str(out2) for a in run])
    except SystemExit as e:
        assert "whole box differs" in str(e), e
    else:
        raise AssertionError("a changed meeting number did not stop the run")
    assert not out2.exists()
    side.write_text(keep)
    # no chosen boxes: run refuses, --check says EMPTY
    cfg["rural_boxes"]["boxes"] = {}
    w["cp"].write_text(yaml.safe_dump(cfg, sort_keys=False))
    assert db.main(run + ["--check"]) == 0
    try:
        db.main([a if a != str(out) else str(out2) for a in run])
    except SystemExit as e:
        assert "is empty" in str(e), e
    else:
        raise AssertionError("run without boxes accepted")
    print("ok run: A / B class rows by hand, pooled rows, totals side by side, cell types, city boxes = meeting, PNGs")


def test_overlap_metrics():
    x = np.array([4.0, 0.0, 1.0, 5.0, 0.0])
    y = np.array([2.0, 2.0, 0.0, 6.0, 0.0])
    m = db.overlap_metrics(x, y)
    a, b = x / 10, y / 10                     # 0.4 0 0.1 0.5 0 | 0.2 0.2 0 0.6 0
    assert np.isclose(m["overlap_dist"], 0.2 + 0 + 0 + 0.5 + 0)
    assert np.isclose(m["overlap_amount"], (2 + 0 + 0 + 5 + 0) / 10)
    assert np.isclose(m["overlap_random"], sum(min(0.2, v) for v in b))   # 1 / 5 = 0.2 each: 0.2 + 0.2 + 0 + 0.2 + 0
    assert np.isclose(m["overlap_random"], 0.6)
    assert m["n_cells"] == 5 and m["n_nonzero_a"] == 3 and m["n_nonzero_b"] == 3 and m["n_nonzero_both"] == 2
    assert m["pop_a"] == 10 and m["pop_b"] == 10
    assert np.isclose(m["spearman_all_cells"], spearmanr(x, y)[0])
    nz = (x > 0) | (y > 0)
    assert np.isclose(m["spearman_nonzero_cells"], spearmanr(x[nz], y[nz])[0])
    s1 = db.overlap_metrics(x, x)                                     # a map with itself = 1
    assert np.isclose(s1["overlap_dist"], 1.0) and np.isclose(s1["overlap_amount"], 1.0)
    assert np.isclose(db.overlap_metrics(x, 3 * x)["overlap_dist"], 1.0)   # same shares, other total
    d = db.overlap_metrics(np.array([1.0, 0, 0]), np.array([0, 2.0, 3.0]))  # no shared cell = 0
    assert d["overlap_dist"] == 0 and d["overlap_amount"] == 0
    e = db.overlap_metrics(np.zeros(3), np.array([1.0, 0, 0]))
    assert np.isnan(e["overlap_dist"]) and e["overlap_amount"] == 0
    assert db.overlap_pairs(["ghs_pop", "worldpop", "v57", "v57pq5"], ["v57", "v57pq5"], ["ghs_pop", "worldpop"]) == [
        ("v57", "ghs_pop", False), ("v57pq5", "ghs_pop", False), ("v57", "worldpop", False),
        ("v57pq5", "worldpop", False), ("ghs_pop", "worldpop", True)]
    assert db.overlap_pairs(["ghs_pop", "v57", "v57pq5"], ["v57", "v57pq5"], ["ghs_pop"]) == [
        ("v57", "ghs_pop", False), ("v57pq5", "ghs_pop", False)]
    print("ok overlap metrics: distributions / amounts / random baseline / Spearman by hand, self = 1, disjoint = 0")


def test_real_config():
    cfg = yaml.safe_load((REPO / "configs" / "external_grids.yaml").read_text())
    rb = cfg["rural_boxes"]
    assert list(cfg)[-1] == "rural_boxes" and list(rb)[-1] == "boxes"
    assert rb["version"] == "Dasy_CONUS_RF_v3_all_nby" and rb["cities"] == ["boston", "denver", "chicago"]
    assert rb["box_km"] == cfg["city_maps"]["box_km"] == 40
    assert rb["smod"]["scheme_a"] == SCHEME_A and set(rb["smod"]["codes"]) == set(CODES)
    assert rb["own_rules"]["centre"] == RULES["centre"] and rb["own_rules"]["cluster"] == RULES["cluster"]
    assert rb["own_rules"]["margin_km"] == 20 and rb["select"]["min_dist_km"] == 50
    assert rb["own_rules"]["gap_fill_max_km2"] == 15 and rb["own_rules"]["smooth_min_neighbours"] == 5
    assert "hole_fill" not in rb["own_rules"]
    st = [s for ss in rb["select"]["regions"].values() for s in ss]
    assert len(st) == len(set(st)) == 49                                    # 48 states + DC
    assert rb["select"]["train_status"] == yaml.safe_load(
        (REPO / "configs" / "conus_rf_v3_all_nby.yaml").read_text())["train_status"]
    boxes = rb["boxes"] or {}
    assert len(boxes) in (0, 8), boxes
    if boxes:
        assert sorted(b["box_type"] for b in boxes.values()) == ["peri_urban"] * 4 + ["rural"] * 4
    a = db.parse_args(["status"])
    assert a.mode == "status"
    # the earlier city density outputs are a different folder (not touched)
    assert (REPO / "results/validation/conus/external/city_density_classes_v57/density_class_summary.csv").exists()
    print(f"ok real config: rules, regions = 48 states + DC, boxes {len(boxes)}")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        test_smod_cells(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_own_rules(Path(d))
    test_candidate_order()
    test_overlap_metrics()
    with tempfile.TemporaryDirectory() as d:
        test_select(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_run(Path(d))
    test_real_config()
    print("ALL OK")
