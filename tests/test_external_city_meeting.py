"""Synthetic test of src/validation/external_city_meeting.py (meeting city maps: v5.6 | GHS-POP | WorldPop + 1 km block
scatter plots, gap blocks vs HISDAC BUI / NobuiltYear):

    python tests/test_external_city_meeting.py      (needs the hisdac env: rasterio, pyproj, matplotlib)

Checks (a) the scatter blocks are the Spearman blocks of external_city_maps.panel_stats (same blocks, same rho);
(b) the gap rule (v5.6 / GHS < ratio_max, GHS >= min_density per km2, full blocks only) and the cell shares = by hand
block by block; (c) NobuiltYear: the cutout layer before HISDAC's FBUY/NobuiltYear.tif, none = NA; a raster on our
cells is read as a window, a shifted one through WarpedVRT (nearest); (d) scatter axes: one square range 0.01 .. 30,000
with fixed ticks, the 0 band "0 (n)" apart from every tick label and as wide on x as on y, 0 < v < 0.01 on the edge
counted in the legend; (e) end to end, 2010 + 1980: one figure size and layout (empty slot for WorldPop 1980), white
PNG margins, meeting_summary.csv (rho and totals = external_city_maps), gap_blocks.csv of every city and year and the
text panels = by hand ("gap blocks: 0" when none), the older chicago_gap_blocks.csv compared then removed, a changed
previous number stops the rerun, without NobuiltYear its columns NA, `--check`.
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

import external_city_maps as ecm  # noqa: E402
import external_city_meeting as mt  # noqa: E402
from test_external_city_maps import write  # noqa: E402

OUR = "ESRI:102039"


def test_blocks_and_gap():
    rng = np.random.default_rng(7)
    f, h, w = 4, 16, 20
    mask = np.ones((h, w), bool)
    mask[1, 1] = mask[9, 14] = False                      # blocks (0, 0) and (2, 3) not full
    ref = np.where(mask, rng.uniform(0, 100, (h, w)), np.nan)
    pop = rng.uniform(0, 100, (h, w))
    ref[4:8, 4:8] = 0.0                                   # block (1, 1): v5.6 empty
    pop[4:8, 4:8] = 200.0                                 #   GHS dense -> gap
    ref[12:16, 0:4] = 14.4                                # block (3, 0): v5.6 / GHS = 0.24 but GHS sparse -> no gap
    pop[12:16, 0:4] = 60.0                                #   (960 per km2)
    pb, rb, full = mt.blocks(pop, ref, mask, f)
    st = ecm.panel_stats(pop, mask, np.ones((h, w)), ref, f)
    assert int(full.sum()) == st["n_blocks_1km"] == 18
    assert abs(ecm.spearman(pb[full], rb[full]) - st["spearman_1km_vs_version"]) < 1e-12
    bkm2 = f * f * ecm.CELL_KM2                           # 1 km2
    gap = mt.gap_blocks(rb, pb, full, bkm2, 0.25, 1000.0)
    want = np.zeros_like(full)
    for bi in range(h // f):
        for bj in range(w // f):
            sl = (slice(f * bi, f * bi + f), slice(f * bj, f * bj + f))
            if not mask[sl].all():
                continue
            g, v = pop[sl].sum() / bkm2, np.nan_to_num(ref[sl]).sum() / bkm2
            want[bi, bj] = g >= 1000 and v < 0.25 * g
    assert (gap == want).all() and gap[1, 1] and not gap[3, 0] and int(gap.sum()) >= 1
    cells = rng.random((h, w)) < 0.3
    flags = gap | (np.arange(gap.size).reshape(gap.shape) % 3 == 0) & full
    n = k = 0
    for bi, bj in zip(*np.nonzero(flags)):
        c = cells[f * bi:f * bi + f, f * bj:f * bj + f]
        n, k = n + c.size, k + c.sum()
    assert abs(mt.cell_share(flags, cells, f) - k / n) < 1e-12
    assert np.isnan(mt.cell_share(np.zeros_like(flags), cells, f))
    print("ok: scatter blocks = Spearman blocks, gap rule and cell shares = by hand")


def test_nobuilt_inputs(tmp: Path):
    class A:
        cutout_root, name, hisdac_dir = tmp / "cut", "conus", None
    p, how = mt.nobuilt_source(A)
    assert p is None and "no --hisdac-dir" in how
    A.hisdac_dir = tmp / "hisdac"
    p, how = mt.nobuilt_source(A)
    assert p is None and "not found" in how
    t = from_origin(500_000.0, 1_800_000.0, 250.0, 250.0)
    a = np.arange(40 * 50, dtype=float).reshape(40, 50)
    a[3, 4] = -1.0                                        # nodata -> 0
    write(A.hisdac_dir / "FBUY" / "NobuiltYear.tif", a, t, OUR, -1.0)
    p, how = mt.nobuilt_source(A)
    assert how == "hisdac" and p.name == "NobuiltYear.tif"
    write(A.cutout_root / "conus" / "layers" / "NobuiltYear" / "NobuiltYear.tif", a, t, OUR, -1.0)
    assert mt.nobuilt_source(A)[1] == "cutout"
    box_t = from_origin(500_000.0 + 2 * 250, 1_800_000.0 - 1 * 250, 250.0, 250.0)
    got = mt.read_on_box(p, box_t, (8, 12), OUR)
    want = a[1:9, 2:14].copy()
    want[want < 0] = 0.0
    assert np.array_equal(got, want)
    shifted = from_origin(500_000.0 + 100, 1_800_000.0 - 100, 250.0, 250.0)   # 0.4 cell off: WarpedVRT nearest
    q = tmp / "shift.tif"
    write(q, a, shifted, OUR, -1.0)
    got = mt.read_on_box(q, from_origin(500_000.0 + 1000, 1_800_000.0 - 1000, 250.0, 250.0), (6, 6), OUR)
    want = a[4:10, 4:10].copy()                          # centres 0.4 cell inside the shifted pixels -> same index
    want[want < 0] = 0.0
    assert np.array_equal(got, want), (got[:2, :3], want[:2, :3])
    print("ok: NobuiltYear source order (cutout, HISDAC, NA), window and WarpedVRT reads")


def test_scatter_axes():
    plt = ecm._plots().plt
    assert [mt.tick_label(t) for t in mt.SC_TICKS] == ["0.01", "0.1", "1", "10", "100", "1,000", "10,000"]
    # Denver 1980 shape: 1 zero block on x, 169 on y, positive blocks from 0.0001 to ~10,000 per km2
    rng = np.random.default_rng(1)
    x = 10.0 ** rng.uniform(-3.3, 3.9, 1581)
    y = 10.0 ** rng.uniform(-3.2, 3.9, 1581)
    x[5], y[:169] = 0.0, 0.0
    x[7] = 0.00012
    x[9] = 50_000.0                                        # above the range: edge, counted
    n_below = int((((x > 0) & (x < 0.01)) | ((y > 0) & (y < 0.01))).sum())
    shapes = []
    for xx, yy, n0 in ((x, y, (1, 169)), (np.minimum(x + 0.5, 20_000.0), y + 0.5, (0, 0))):
        fig = plt.figure(figsize=mt.FIGSIZE, dpi=150, layout="constrained")
        ax = fig.subfigures(2, 1)[1].subplots(1, 3)[0]
        mt.scatter(ax, xx, yy, None, "t", "v5.6, people per km2 (1 km block)", "y")
        fig.canvas.draw()
        r = fig.canvas.get_renderer()
        assert ax.get_xlim() == ax.get_ylim() == (mt.SC_LOW_LIMIT, mt.SC_HI)
        for which, labs, n in (("x", ax.get_xticklabels(), n0[0]), ("y", ax.get_yticklabels(), n0[1])):
            texts = [t.get_text() for t in labs]
            want = (["0 (%d)" % n] if n else []) + ["0.01", "0.1", "1", "10", "100", "1,000", "10,000"]
            assert texts == want, (which, texts)
            if n:
                z = labs[0].get_window_extent(r)
                assert all(not z.overlaps(t.get_window_extent(r)) for t in labs[1:]), (which, texts)
        bands = [p_.get_extents() for p_ in ax.patches]
        assert len(bands) == (n0[0] > 0) + (n0[1] > 0)
        legend = [t.get_text() for t in ax.get_legend().get_texts()]
        if n0[0]:
            assert f"< 0.01 ({n_below})" in legend and "> 30,000 (1)" in legend, legend
            pos = ax.transData.transform([[mt.ZERO_BAND[0], mt.ZERO_BAND[0]], [mt.ZERO_BAND[2], mt.ZERO_BAND[2]]])
            assert abs((pos[1, 0] - pos[0, 0]) - (pos[1, 1] - pos[0, 1])) < 0.5   # band: same width on x and y
        else:
            assert not any(t.startswith(("<", ">")) for t in legend), legend
        shapes.append(ax.get_window_extent(r).size)
        plt.close(fig)
    assert all(abs(w - h) < 1.0 for w, h in shapes), shapes   # square
    xs, xb, xa = mt.clamp(np.array([0.0, 0.004, 0.01, 5.0, 40_000.0]))
    assert xs.tolist() == [mt.ZERO_BAND[1], 0.01, 0.01, 5.0, 30_000.0]
    assert xb.tolist() == [False, True, False, False, False] and xa.tolist() == [False] * 4 + [True]
    print("ok: one square range 0.01 .. 30,000 with fixed ticks, 0 band '0 (n)' apart from the ticks and the same "
          "width on x / y, 0 < v < 0.01 on the edge counted in the legend")


def by_hand_gap(pop, bui, nby, ghs_path, gt, dasym_year_path, cx, cy):
    """{group: block slices} and the source arrays of one city box, by hand (12 km box, 4-cell blocks)."""
    win = ecm.box_window(gt, cx, cy, 12)
    r0, c0, mm = int(win.row_off), int(win.col_off), 48
    vb = pop[r0:r0 + mm, c0:c0 + mm].astype("float32").astype("float64")
    mask = vb != -9999.0
    with rasterio.open(dasym_year_path) as src:
        bt = src.window_transform(win)
    g, _ = ecm.to_grid(ghs_path, bt, (mm, mm), OUR, 25.0)
    rows = {"gap": [], "dense_not_gap": []}
    for bi in range(12):
        for bj in range(12):
            sl = (slice(4 * bi, 4 * bi + 4), slice(4 * bj, 4 * bj + 4))
            if not mask[sl].all():
                continue
            gd, vd = g[sl].sum(), vb[sl].sum()
            if gd >= 1000:
                rows["gap" if vd < 0.25 * gd else "dense_not_gap"].append(sl)
    return rows, g, vb, bui[r0:r0 + mm, c0:c0 + mm], nby[r0:r0 + mm, c0:c0 + mm]


def make_world(tmp: Path) -> dict:
    """Synthetic city world: V56 predictions 2010 / 1980, BUI, NobuiltYear, GHS / WorldPop, the config (two cities)."""
    rng = np.random.default_rng(4)
    lon, lat = -87.6298, 41.8781
    cx, cy = Transformer.from_crs("EPSG:4326", OUR, always_xy=True).transform(lon, lat)
    x0, y1 = 250.0 * np.floor(cx / 250.0) - 30_000, 250.0 * np.floor(cy / 250.0) + 30_000
    n = 240
    gt = from_origin(x0, y1, 250.0, 250.0)
    pop = rng.uniform(0, 40, (n, n))
    pop[140:150, 100:140] = -9999.0                      # water inside the box
    pop[104:136, 104:136] = 300.0                        # v5.6 dense where GHS is dense (core 108-132) ...
    pop[116:132, 116:132] = 0.0                          # ... but empty in a part of it -> gap blocks
    bui = rng.integers(0, 4, (n, n)).astype(float)
    bui[116:132, 116:132] = 0.0                          # no HISDAC record there
    nby = rng.integers(0, 3, (n, n)).astype(float)
    pop80 = np.where(pop >= 0, pop * 0.6, pop)
    pop80[104:136, 104:136] = 900.0                      # 1980: v5.6 dense in the whole core -> no gap blocks
    bui80 = np.maximum(bui - 1, 0)
    dasym, cut, data, hisdac = tmp / "dasym", tmp / "cut", tmp / "data", tmp / "hisdac"
    pred = dasym / "conus" / "V56" / "predictions"
    write(pred / "pop_2010.tif", pop, gt, OUR, -9999.0)
    write(pred / "pop_1980.tif", pop80, gt, OUR, -9999.0)
    write(cut / "conus" / "layers" / "BUI" / "2010_BUI.tif", bui, gt, OUR, -1.0)
    write(cut / "conus" / "layers" / "BUI" / "1980_BUI.tif", bui80, gt, OUR, -1.0)
    write(hisdac / "FBUY" / "NobuiltYear.tif", nby, gt, OUR, None)
    mx, my = Transformer.from_crs(OUR, "ESRI:54009", always_xy=True).transform(cx, cy)
    ghs = rng.uniform(0, 3, (300, 300))
    ghs[120:180, 120:180] = 40.0                         # dense core: 4,000 per km2
    ghs[92:117, :] = 0.0                                 # empty 2.5 km strip in the box: 0-people blocks (band)
    ghs[125:175, 90:115] = 0.00004                       # < 0.01 per km2 blocks, west of the core (edge triangles)
    for y, fct in ((2010, 1.0), (1980, 0.7)):
        write(data / "ghs" / f"ghs_{y}.tif", ghs * fct, from_origin(mx - 15_000, my + 15_000, 100.0, 100.0),
              "ESRI:54009", -200.0)
    r = 1 / 1200
    wp = rng.uniform(0, 3, (200, 260))
    write(data / "wp" / "wp_2010.tif", wp, from_origin(lon - 130 * r, lat + 100 * r, r, r), "EPSG:4326", -99999.0)
    prod = {"label": "x", "years": [1980, 2010], "input_unit": "x", "input_unit_class": "block",
            "input_unit_source": "https://example.org"}
    cfg = {"reference": "V56", "products": {
        "ghs_pop": {**prod, "label": "GHS test (100 m)", "path": "ghs/ghs_{YEAR}.tif"},
        "worldpop": {**prod, "label": "WP test (100 m)", "path": "wp/wp_{YEAR}.tif", "years": [2000, 2010]},
        "fj_m5": {**prod, "label": "FJ test", "path": "fj/none_{YEAR}.tif", "input_unit_class": "county"}},
           "city_maps": {"version": "V56", "version_label": "v5.6", "box_km": 12, "block_km": 1, "subpixel_m": 25,
                         "years": {2010: ["ghs_pop", "worldpop"], 1980: ["ghs_pop"]},   # fj_m5 (no file) unused
                         "cities": {"chicago": {"label": "Chicago, IL", "lon": lon, "lat": lat},
                                    "boston": {"label": "Boston, MA", "lon": lon + 0.01, "lat": lat}}},
           "city_meeting": {"years": {2010: ["ghs_pop", "worldpop"], 1980: ["ghs_pop"]},
                            "cities": ["boston", "chicago"], "labels": {"ghs_pop": "GHS", "worldpop": "WP"},
                            "gap": {"product": "ghs_pop", "ratio_max": 0.25, "min_density": 1000}}}
    cp = tmp / "ext.yaml"
    cp.write_text(yaml.safe_dump(cfg, sort_keys=False))   # keep 2010 before 1980
    return dict(lon=lon, lat=lat, cx=cx, cy=cy, gt=gt, pop=pop, pop80=pop80, bui=bui, bui80=bui80, nby=nby,
                dasym=dasym, cut=cut, data=data, hisdac=hisdac, pred=pred, cp=cp,
                base=["--config", str(cp), "--data-root", str(data), "--dasym-root", str(dasym), "--cutout-root",
                      str(cut)])


def test_end_to_end(tmp: Path):
    w = make_world(tmp)
    lon, lat, cx, cy, gt = w["lon"], w["lat"], w["cx"], w["cy"], w["gt"]
    pop, pop80, bui, bui80, nby = w["pop"], w["pop80"], w["bui"], w["bui80"], w["nby"]
    data, hisdac, pred = w["data"], w["hisdac"], w["pred"]
    out = tmp / "meet"
    common = w["base"] + ["--out-dir", str(out)]
    ecm.main(common[:-1] + [str(tmp / "maps")])          # the city maps summary (both years) to compare with
    old = pd.read_csv(tmp / "maps" / "city_maps_summary.csv")
    mt.main(common + ["--hisdac-dir", str(hisdac), "--check"])
    assert not out.exists()
    drawn = {}
    real_draw = mt.draw

    def spy(*a):
        drawn[a[0].name] = a
        real_draw(*a)

    run = common + ["--hisdac-dir", str(hisdac), "--compare-with", str(tmp / "maps" / "city_maps_summary.csv")]
    mt.draw = spy
    try:
        mt.main(run)
    finally:
        mt.draw = real_draw
    assert sorted(drawn) == ["boston_1980.png", "boston_2010.png", "chicago_1980.png", "chicago_2010.png"]
    import matplotlib.image as mpimg
    sizes = set()
    for k, a in drawn.items():                           # (path, title, maps, mask, box, block, gap, full, scat, text,
        im = mpimg.imread(out / k)[..., :3]              #  missing)
        sizes.add(im.shape)
        for edge in (im[:6], im[-6:], im[:, :6], im[:, -6:]):   # nothing cut: white margin on every side
            assert edge.min() > 0.97, (k, float(edge.min()))
        n_maps, n_scat = (2, 1) if "1980" in k else (3, 2)
        assert len(a[2]) == n_maps and len(a[8]) == n_scat, (k, len(a[2]), len(a[8]))
        assert len(a[10]) == 3 - n_maps and (not a[10] or a[10][0] == "WP: no 1980 grid\n(from 2000)"), a[10]
        assert a[6] is not None                          # gap blocks in every city and year
        assert "white = 0 people" in a[9]
        x0_, y0_ = a[8][0][1], a[8][0][2]                # the GHS scatter has 0 and < 0.01 blocks
        assert (y0_ == 0).any() and ((y0_ > 0) & (y0_ < 0.01)).any(), k
    assert len(sizes) == 1, sizes                        # every figure the same size
    s = pd.read_csv(out / "meeting_summary.csv")
    assert len(s) == 10 and set(s.loc[s["year"] == 1980, "product"]) == {"V56", "ghs_pop"}
    assert list(s["year"].unique()) == [2010, 1980]      # 2010 rows first, 1980 added
    m = s.merge(old, on=["city", "year", "product"], suffixes=("", "_old"))
    assert len(m) == 10
    assert np.allclose(m["spearman_1km_vs_version"], m["spearman_1km_vs_version_old"], rtol=0, atol=1e-12)
    assert np.allclose(m["total_pop_box"], m["total_pop_box_old"], rtol=1e-9)
    assert (m["n_blocks_1km"] == m["n_blocks_1km_old"]).all()
    # one gap table, every city and year, by hand
    gp = pd.read_csv(out / "gap_blocks.csv").set_index(["city", "year", "group"])
    assert len(gp) == 8 and not (out / "chicago_gap_blocks.csv").exists()
    boxes = {"chicago": (cx, cy)}
    boxes["boston"] = Transformer.from_crs("EPSG:4326", OUR, always_xy=True).transform(lon + 0.01, lat)
    n_gap = {}
    for (city, year), (pp, bu) in ((k, v) for k in [(c, y) for c in boxes for y in (2010, 1980)]
                                   for v in [(pop, bui) if k[1] == 2010 else (pop80, bui80)]):
        rows, g, vb, bb, nb = by_hand_gap(pp, bu, nby, data / "ghs" / f"ghs_{year}.tif", gt,
                                          pred / f"pop_{year}.tif", *boxes[city])
        n_gap[(city, year)] = len(rows["gap"])
        for grp, sls in rows.items():
            r = gp.loc[(city, year, grp)]
            assert r["n_blocks"] == len(sls) and r["n_cells"] == 16 * len(sls), (city, year, grp)
            assert abs(r["pop_ghs_pop"] - sum(g[sl].sum() for sl in sls)) < 1e-6 * max(1.0, r["pop_ghs_pop"])
            assert abs(r["pop_v56"] - sum(vb[sl].sum() for sl in sls)) < 1e-6 * max(1.0, r["pop_v56"])
            if not sls:
                assert np.isnan(r["share_cells_bui_gt0"])
                continue
            nn = 16 * len(sls)
            assert abs(r["share_cells_bui_gt0"] - sum((bb[sl] > 0).sum() for sl in sls) / nn) < 1e-12
            assert abs(r["share_cells_nobuilt_gt0"] - sum((nb[sl] > 0).sum() for sl in sls) / nn) < 1e-12
            assert abs(r["share_cells_nobuilt_gt0_bui0"] - sum(((nb[sl] > 0) & (bb[sl] == 0)).sum() for sl in sls)
                       / nn) < 1e-12
            assert abs(r["share_cells_no_record"] - sum(((nb[sl] == 0) & (bb[sl] == 0)).sum() for sl in sls) / nn) \
                < 1e-12
    assert n_gap[("chicago", 2010)] >= 4 and 0 in n_gap.values()     # one city-year without gap blocks
    assert gp.loc[("chicago", 2010, "gap"), "share_cells_bui_gt0"] < 0.5 < \
        gp.loc[("chicago", 2010, "dense_not_gap"), "share_cells_bui_gt0"]
    # text panels = the gap table; 0 gap blocks -> "gap blocks: 0"
    for (city, year) in n_gap:
        text = drawn[f"{city}_{year}.png"][9].split("\n")
        gg, dd = gp.loc[(city, year, "gap")], gp.loc[(city, year, "dense_not_gap")]
        if n_gap[(city, year)] == 0:
            assert "gap blocks: 0" in text and f"  (other dense blocks: {dd['n_blocks']})" in text, text
            continue
        for lab, col in (("  BUI > 0: ", "share_cells_bui_gt0"),
                         ("   (undated records only): ", "share_cells_nobuilt_gt0_bui0"),
                         ("  no record: ", "share_cells_no_record")):
            assert f"{lab}{100 * gg[col]:.0f} % vs {100 * dd[col]:.0f} %" in text, (city, year, lab, text)
        assert f"  blocks: {gg['n_blocks']} vs {dd['n_blocks']}" in text
    # the older Chicago-only table: its rows must come out the same, then it is removed
    gpf = pd.read_csv(out / "gap_blocks.csv")
    legacy = gpf[(gpf["city"] == "chicago") & (gpf["year"] == 2010)]
    legacy.to_csv(out / "chicago_gap_blocks.csv", index=False)
    (out / "gap_blocks.csv").unlink()
    mt.main(run)
    assert (out / "gap_blocks.csv").exists() and not (out / "chicago_gap_blocks.csv").exists()
    bad = legacy.copy()
    bad.loc[bad.index[0], "share_cells_no_record"] += 0.01
    bad.to_csv(out / "chicago_gap_blocks.csv", index=False)
    try:
        mt.main(run)
    except SystemExit as e:
        assert "share_cells_no_record differs" in str(e) and "chicago_gap_blocks.csv" in str(e), e
    else:
        raise AssertionError("a changed Chicago 2010 row did not stop the run")
    assert (out / "chicago_gap_blocks.csv").exists()     # nothing written / removed
    (out / "chicago_gap_blocks.csv").unlink()
    # a changed previous rho stops the rerun, nothing written
    t = pd.read_csv(out / "meeting_summary.csv")
    t.loc[3, "spearman_1km_vs_version"] += 0.01
    t.to_csv(out / "meeting_summary.csv", index=False)
    png_time = (out / "chicago_2010.png").stat().st_mtime_ns
    try:
        mt.main(run)
    except SystemExit as e:
        assert "spearman_1km_vs_version differs" in str(e), e
    else:
        raise AssertionError("a changed rho did not stop the run")
    assert (out / "chicago_2010.png").stat().st_mtime_ns == png_time
    # without NobuiltYear: those columns NA, the rest the same
    out2 = tmp / "meet2"
    mt.main(common[:-1] + [str(out2)])
    gp2 = pd.read_csv(out2 / "gap_blocks.csv").set_index(["city", "year", "group"])
    assert gp2["share_cells_nobuilt_gt0"].isna().all() and gp2["nobuilt_source"].str.startswith("NA").all()
    assert (gp2["n_blocks"] == gp["n_blocks"]).all()
    # a missing product file stops --check
    (data / "ghs" / "ghs_1980.tif").unlink()
    try:
        mt.main(common + ["--check"])
    except SystemExit as e:
        assert "inputs missing" in str(e)
    else:
        raise AssertionError("--check did not stop on a missing file")
    print("ok: end to end (one size and layout for 2010 / 1980, rho / totals = city maps, gap table of every city and "
          "year + text panels by hand, Chicago 2010 = the older table, rerun compared, NobuiltYear NA, --check)")


def test_version_option(tmp: Path):
    """--version / --version-label / --base-dir (v5.7 next to v5.6): the figures of another version on the same boxes
    and gap rule, its gap table by hand with pop_v57, the config version recomputed and checked against the base dir
    (a changed base number stops before anything is written), the side-by-side CSV = both tables."""
    w = make_world(tmp)
    hisdac = ["--hisdac-dir", str(w["hisdac"])]
    base_out, new_out = tmp / "meet", tmp / "meet57"
    mt.main(w["base"] + ["--out-dir", str(base_out)] + hisdac)     # the v5.6 outputs (the base dir)
    pop57, pop57_80 = w["pop"].copy(), w["pop80"].copy()
    pop57[116:124, 116:132] = 250.0                      # v5.7 fills half of the 2010 gap core
    pop57_80 = np.where(pop57_80 >= 0, pop57_80 * 1.1, pop57_80)
    p57 = w["dasym"] / "conus" / "V57" / "predictions"
    write(p57 / "pop_2010.tif", pop57, w["gt"], OUR, -9999.0)
    write(p57 / "pop_1980.tif", pop57_80, w["gt"], OUR, -9999.0)
    before = {f.name: f.stat().st_mtime_ns for f in base_out.iterdir()}
    run = w["base"] + ["--out-dir", str(new_out), "--version", "V57", "--version-label", "v5.7", "--base-dir",
                       str(base_out)] + hisdac
    for bad in (["--version", "V57"], ["--base-dir", str(base_out)]):   # label missing / base without version
        try:
            mt.parse_args(w["base"] + ["--out-dir", str(new_out)] + bad)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"{bad} accepted")
    mt.main(run + ["--check"])
    assert not new_out.exists()
    drawn = {}
    real_draw = mt.draw

    def spy(*a):
        drawn[a[0].name] = a
        real_draw(*a)

    mt.draw = spy
    try:
        mt.main(run)
    finally:
        mt.draw = real_draw
    assert sorted(drawn) == ["boston_1980.png", "boston_2010.png", "chicago_1980.png", "chicago_2010.png"]
    assert all(a[11] == "v5.7" and a[2][0][0].startswith("v5.7 (county input)") for a in drawn.values())
    assert {f.name: f.stat().st_mtime_ns for f in base_out.iterdir()} == before   # the base dir is not written
    s = pd.read_csv(new_out / "meeting_summary.csv")
    assert set(s["product"]) == {"V57", "ghs_pop", "worldpop"} and len(s) == 10
    gp = pd.read_csv(new_out / "gap_blocks.csv").set_index(["city", "year", "group"])
    assert "pop_v57" in gp and "pop_v56" not in gp
    boxes = {"chicago": (w["cx"], w["cy"]),
             "boston": Transformer.from_crs("EPSG:4326", OUR, always_xy=True).transform(w["lon"] + 0.01, w["lat"])}
    for city in boxes:
        for year, pp, bu in ((2010, pop57, w["bui"]), (1980, pop57_80, w["bui80"])):
            rows, g, vb, _, _ = by_hand_gap(pp, bu, w["nby"], w["data"] / "ghs" / f"ghs_{year}.tif", w["gt"],
                                            p57 / f"pop_{year}.tif", *boxes[city])
            for grp, sls in rows.items():
                r = gp.loc[(city, year, grp)]
                assert r["n_blocks"] == len(sls), (city, year, grp)
                assert abs(r["pop_v57"] - sum(vb[sl].sum() for sl in sls)) < 1e-6 * max(1.0, r["pop_v57"])
    g56 = pd.read_csv(base_out / "gap_blocks.csv").set_index(["city", "year", "group"])
    assert gp.loc[("chicago", 2010, "gap"), "n_blocks"] < g56.loc[("chicago", 2010, "gap"), "n_blocks"]
    # side by side: the v5.6 column = the base tables, the v5.7 column = the new ones
    side = pd.read_csv(new_out / "meeting_summary_v56_v57.csv")
    assert list(side.columns) == ["city", "year", "table", "item", "measure", "v5.6", "v5.7", "diff"]
    s56 = pd.read_csv(base_out / "meeting_summary.csv")
    for tab, ref, col in (("v5.6", s56, "V56"), ("v5.7", s, "V57")):
        for r in ref.itertuples():
            item = "model" if r.product == col else r.product
            for meas in ("spearman_1km_vs_version", "total_pop_box", "n_blocks_1km"):
                v = side[(side["city"] == r.city) & (side["year"] == r.year) & (side["table"] == "summary")
                         & (side["item"] == item) & (side["measure"] == meas)][tab]
                assert len(v) == 1 and np.isclose(v.iloc[0], getattr(r, meas), rtol=1e-12), (tab, r, meas)
    for tab, ref, pc in (("v5.6", g56, "pop_v56"), ("v5.7", gp, "pop_v57")):
        for (city, year, grp), r in ref.iterrows():
            for meas, src in (("n_blocks", "n_blocks"), ("pop_model", pc), ("pop_ghs_pop", "pop_ghs_pop")):
                v = side[(side["city"] == city) & (side["year"] == year) & (side["table"] == "gap")
                         & (side["item"] == grp) & (side["measure"] == meas)][tab]
                assert len(v) == 1 and np.isclose(v.iloc[0], r[src], rtol=1e-12, equal_nan=True), (tab, city, meas)
    assert np.allclose(side["diff"], side["v5.7"] - side["v5.6"], equal_nan=True)
    # a changed base number stops the run before anything is written
    t = pd.read_csv(base_out / "meeting_summary.csv")
    t.loc[0, "total_pop_box"] += 1
    t.to_csv(base_out / "meeting_summary.csv", index=False)
    stamp = (new_out / "meeting_summary_v56_v57.csv").stat().st_mtime_ns
    try:
        mt.main(run)
    except SystemExit as e:
        assert "total_pop_box differs" in str(e) and str(base_out) in str(e), e
    else:
        raise AssertionError("a changed base number did not stop the run")
    assert (new_out / "meeting_summary_v56_v57.csv").stat().st_mtime_ns == stamp
    # --check lists the base version's predictions too
    (w["pred"] / "pop_1980.tif").unlink()
    try:
        mt.main(run + ["--check"])
    except SystemExit as e:
        assert "inputs missing" in str(e)
    else:
        raise AssertionError("--check did not stop on a missing base prediction")
    print("ok: --version v5.7 (same boxes / rule, pop_v57 gap table by hand, label on the figures), v5.6 recomputed = "
          "base dir (a change stops), side-by-side CSV = both tables, base dir untouched, --check incl. the base")


def test_real_config():
    cfg = yaml.safe_load((REPO / "configs" / "external_grids.yaml").read_text())
    c = cfg["city_meeting"]
    assert c["years"] == {2010: ["ghs_pop", "worldpop"], 1980: ["ghs_pop"]}
    assert c["cities"] == ["boston", "denver", "chicago"] and "fj_m5" not in str(c["years"])
    assert c["gap"] == {"product": "ghs_pop", "ratio_max": 0.25, "min_density": 1000}
    assert all(y in cfg["products"][p]["years"] for y, ps in c["years"].items() for p in ps)
    sh = (REPO / "sbatch" / "external_city_meeting.sh").read_text()
    assert "city_maps_internal_with_fj/city_maps_summary.csv" in sh
    assert "city_maps_internal_with_fj" in (REPO / "sbatch" / "external_city_maps.sh").read_text()
    print("ok: real config (2010 GHS + WorldPop, 1980 GHS, gap rule for every city and year) and paths")


if __name__ == "__main__":
    test_blocks_and_gap()
    test_scatter_axes()
    test_real_config()
    for t in (test_nobuilt_inputs, test_end_to_end, test_version_option):
        with tempfile.TemporaryDirectory() as d:
            t(Path(d))
    print("ALL OK")
