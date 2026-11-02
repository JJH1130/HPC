"""Synthetic test of src/validation/external_city_meeting.py (meeting city maps: v5.6 | GHS-POP | WorldPop + 1 km block
scatter plots, gap blocks vs HISDAC BUI / NobuiltYear):

    python tests/test_external_city_meeting.py      (needs the hisdac env: rasterio, pyproj, matplotlib)

Checks (a) the scatter blocks are the Spearman blocks of external_city_maps.panel_stats (same blocks, same rho);
(b) the gap rule (v5.6 / GHS < ratio_max, GHS >= min_density per km2, full blocks only) and the cell shares = by hand
block by block; (c) NobuiltYear: the cutout layer before HISDAC's FBUY/NobuiltYear.tif, none = NA; a raster on our
cells is read as a window, a shifted one through WarpedVRT (nearest); (d) end to end: PNGs, meeting_summary.csv (rho
and totals = external_city_maps), the gap table = by hand, without NobuiltYear its columns NA, `--check`.
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


def test_end_to_end(tmp: Path):
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
    dasym, cut, data, hisdac = tmp / "dasym", tmp / "cut", tmp / "data", tmp / "hisdac"
    write(dasym / "conus" / "V56" / "predictions" / "pop_2010.tif", pop, gt, OUR, -9999.0)
    write(cut / "conus" / "layers" / "BUI" / "2010_BUI.tif", bui, gt, OUR, -1.0)
    write(hisdac / "FBUY" / "NobuiltYear.tif", nby, gt, OUR, None)
    mx, my = Transformer.from_crs(OUR, "ESRI:54009", always_xy=True).transform(cx, cy)
    ghs = rng.uniform(0, 3, (300, 300))
    ghs[120:180, 120:180] = 40.0                         # dense core: 4,000 per km2
    write(data / "ghs" / "ghs_2010.tif", ghs, from_origin(mx - 15_000, my + 15_000, 100.0, 100.0), "ESRI:54009",
          -200.0)
    r = 1 / 1200
    wp = rng.uniform(0, 3, (200, 260))
    write(data / "wp" / "wp_2010.tif", wp, from_origin(lon - 130 * r, lat + 100 * r, r, r), "EPSG:4326", -99999.0)
    prod = {"label": "x", "years": [2010], "input_unit": "x", "input_unit_class": "block",
            "input_unit_source": "https://example.org"}
    cfg = {"reference": "V56", "products": {
        "ghs_pop": {**prod, "label": "GHS test", "path": "ghs/ghs_{YEAR}.tif"},
        "worldpop": {**prod, "label": "WP test", "path": "wp/wp_{YEAR}.tif"},
        "fj_m5": {**prod, "label": "FJ test", "path": "fj/none_{YEAR}.tif", "input_unit_class": "county"}},
           "city_maps": {"version": "V56", "version_label": "v5.6", "box_km": 12, "block_km": 1, "subpixel_m": 25,
                         "years": {2010: ["ghs_pop", "worldpop"]},   # fj_m5 (no file) only in the products
                         "cities": {"chicago": {"label": "Chicago, IL", "lon": lon, "lat": lat},
                                    "boston": {"label": "Boston, MA", "lon": lon + 0.01, "lat": lat}}},
           "city_meeting": {"year": 2010, "cities": ["boston", "chicago"], "products": ["ghs_pop", "worldpop"],
                            "gap": {"city": "chicago", "product": "ghs_pop", "ratio_max": 0.25,
                                    "min_density": 1000}}}
    cp = tmp / "ext.yaml"
    cp.write_text(yaml.safe_dump(cfg))
    out = tmp / "meet"
    common = ["--config", str(cp), "--data-root", str(data), "--dasym-root", str(dasym), "--cutout-root", str(cut),
              "--out-dir", str(out)]
    mt.main(common + ["--hisdac-dir", str(hisdac), "--check"])
    assert not out.exists()
    mt.main(common + ["--hisdac-dir", str(hisdac)])
    assert (out / "chicago_2010.png").exists() and (out / "boston_2010.png").exists()
    s = pd.read_csv(out / "meeting_summary.csv")
    assert len(s) == 6 and set(s["product"]) == {"V56", "ghs_pop", "worldpop"}
    # rho and totals = the city maps module on the same box
    ecm.main(common[:-1] + [str(tmp / "maps"), "--cities", "chicago"])
    old = pd.read_csv(tmp / "maps" / "city_maps_summary.csv").set_index("product")
    sc = s[s["city"] == "chicago"].set_index("product")
    for p in ("V56", "ghs_pop", "worldpop"):
        assert abs(sc.loc[p, "spearman_1km_vs_version"] - old.loc[p, "spearman_1km_vs_version"]) < 1e-12
        assert abs(sc.loc[p, "total_pop_box"] - old.loc[p, "total_pop_box"]) < 1e-6 * old.loc[p, "total_pop_box"]
        assert sc.loc[p, "n_blocks_1km"] == old.loc[p, "n_blocks_1km"]
    # gap table by hand
    win = ecm.box_window(gt, cx, cy, 12)
    r0, c0, m = int(win.row_off), int(win.col_off), 48
    vb = pop[r0:r0 + m, c0:c0 + m].astype("float32").astype("float64")
    mask = vb != -9999.0
    with rasterio.open(dasym / "conus" / "V56" / "predictions" / "pop_2010.tif") as src:
        bt = src.window_transform(win)
    g, _ = ecm.to_grid(data / "ghs" / "ghs_2010.tif", bt, (m, m), OUR, 25.0)
    bb, nb = bui[r0:r0 + m, c0:c0 + m], nby[r0:r0 + m, c0:c0 + m]
    rows = {"gap": [], "dense_not_gap": []}
    for bi in range(12):
        for bj in range(12):
            sl = (slice(4 * bi, 4 * bi + 4), slice(4 * bj, 4 * bj + 4))
            if not mask[sl].all():
                continue
            gd, vd = g[sl].sum(), vb[sl].sum()
            if gd >= 1000:
                rows["gap" if vd < 0.25 * gd else "dense_not_gap"].append(sl)
    gp = pd.read_csv(out / "chicago_gap_blocks.csv").set_index("group")
    assert len(rows["gap"]) >= 4 and len(rows["dense_not_gap"]) >= 1
    for grp, sls in rows.items():
        r = gp.loc[grp]
        assert r["n_blocks"] == len(sls) and r["n_cells"] == 16 * len(sls)
        assert abs(r["pop_ghs_pop"] - sum(g[sl].sum() for sl in sls)) < 1e-6 * max(1.0, r["pop_ghs_pop"])
        assert abs(r["pop_v56"] - sum(vb[sl].sum() for sl in sls)) < 1e-6 * max(1.0, r["pop_v56"])
        n = 16 * len(sls)
        assert abs(r["share_cells_bui_gt0"] - sum((bb[sl] > 0).sum() for sl in sls) / n) < 1e-12
        assert abs(r["share_cells_nobuilt_gt0"] - sum((nb[sl] > 0).sum() for sl in sls) / n) < 1e-12
        assert abs(r["share_cells_nobuilt_gt0_bui0"] - sum(((nb[sl] > 0) & (bb[sl] == 0)).sum() for sl in sls) / n) \
            < 1e-12
        assert abs(r["share_cells_no_record"] - sum(((nb[sl] == 0) & (bb[sl] == 0)).sum() for sl in sls) / n) < 1e-12
    assert gp.loc["gap", "share_cells_bui_gt0"] < 0.5 < gp.loc["dense_not_gap", "share_cells_bui_gt0"]
    # without NobuiltYear: those columns NA, the rest the same
    out2 = tmp / "meet2"
    mt.main(common[:-1] + [str(out2)])
    gp2 = pd.read_csv(out2 / "chicago_gap_blocks.csv").set_index("group")
    assert gp2["share_cells_nobuilt_gt0"].isna().all() and gp2["nobuilt_source"].str.startswith("NA").all()
    assert (gp2["n_blocks"] == gp["n_blocks"]).all()
    # a missing product file stops --check
    (data / "wp" / "wp_2010.tif").unlink()
    try:
        mt.main(common + ["--check"])
    except SystemExit as e:
        assert "inputs missing" in str(e)
    else:
        raise AssertionError("--check did not stop on a missing file")
    print("ok: end to end (rho / totals = city maps, gap table by hand, NobuiltYear NA, --check)")


if __name__ == "__main__":
    test_blocks_and_gap()
    for t in (test_nobuilt_inputs, test_end_to_end):
        with tempfile.TemporaryDirectory() as d:
            t(Path(d))
    print("ALL OK")
