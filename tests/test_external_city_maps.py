"""Synthetic test of src/validation/external_city_maps.py (v5.6 vs external grids on our 250 m grid, city boxes):

    python tests/test_external_city_maps.py        (needs the hisdac env: rasterio, pyproj, matplotlib)

Checks (a) population kept by the move to our cells: a 100 m Mollweide raster and a 3 arc-sec lon / lat raster lying
inside the box give back their whole sum; (b) grids that nest are exact: a 125 m raster on our CRS = the 2 x 2 pixel
sums per cell, a 1 km raster = 1 / 16 of the pixel per cell (area-proportional split); (c) the 1 km block sums,
Spearman, the masked / BUI = 0 shares = by hand; (d) masked cells are NaN in the density (drawn grey: the colour map's
`bad` colour), zero cells inside the mask stay 0; (e) end to end on a synthetic prediction / BUI / product: box from
lon / lat, PNG + summary CSV, product totals = what lands in the box, `--check` with a missing file stops.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "validation"))

import rasterio  # noqa: E402
import yaml  # noqa: E402
from matplotlib.colors import to_rgba  # noqa: E402
from pyproj import Transformer  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402

import external_city_maps as cm  # noqa: E402

OUR = "ESRI:102039"


def write(path: Path, a: np.ndarray, transform, crs, nodata):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=a.shape[1], height=a.shape[0], count=1, dtype="float32",
                      crs=crs, transform=transform, nodata=nodata) as d:
        d.write(a.astype("float32"), 1)


def test_conservation(tmp: Path):
    rng = np.random.default_rng(3)
    box_t = from_origin(500_000.0, 1_800_000.0, 250.0, 250.0)   # our box: 80 x 80 cells = 20 km
    shape = (80, 80)
    cx, cy = 510_000.0, 1_790_000.0
    # Mollweide 100 m, 60 x 60 pixels around the box centre (well inside the box)
    mx, my = Transformer.from_crs(OUR, "ESRI:54009", always_xy=True).transform(cx, cy)
    a = rng.uniform(0, 50, size=(60, 60))
    a[5, 5] = -200.0  # nodata: 0 people
    p = tmp / "moll.tif"
    write(p, a, from_origin(mx - 3000, my + 3000, 100.0, 100.0), "ESRI:54009", -200.0)
    g, info = cm.to_grid(p, box_t, shape, OUR, 25.0)
    want = a[a >= 0].sum()
    assert info["subpixels_per_side"] == 4 and info["nodata_pixels"] >= 1  # + the window padding off the raster
    assert abs(g.sum() - want) < 1e-6 * want, (g.sum(), want)
    # lon / lat 3 arc-sec, 40 x 50 pixels around the centre
    lon, lat = Transformer.from_crs(OUR, "EPSG:4326", always_xy=True).transform(cx, cy)
    r = 1 / 1200
    b = rng.uniform(0, 30, size=(40, 50))
    q = tmp / "geo.tif"
    write(q, b, from_origin(lon - 25 * r, lat + 20 * r, r, r), "EPSG:4326", -99999.0)
    g, info = cm.to_grid(q, box_t, shape, OUR, 25.0)
    assert info["subpixels_per_side"] == 4
    assert abs(g.sum() - b.sum()) < 1e-6 * b.sum(), (g.sum(), b.sum())
    # a raster reaching out of the box: only what lands inside is counted, never more than the source
    c = np.ones((400, 400))
    s = tmp / "big.tif"
    write(s, c, from_origin(mx - 20_000, my + 20_000, 100.0, 100.0), "ESRI:54009", -200.0)
    g, _ = cm.to_grid(s, box_t, shape, OUR, 25.0)
    assert g.sum() < c.sum() and abs(g.sum() - 80 * 80 * 6.25) < 0.02 * 80 * 80 * 6.25  # 6.25 pixels per cell
    print("ok: population kept (Mollweide 100 m, lon / lat 3 arc-sec), nodata = 0, box edge cuts")


def test_nested(tmp: Path):
    rng = np.random.default_rng(5)
    box_t = from_origin(500_000.0, 1_800_000.0, 250.0, 250.0)
    shape = (8, 12)
    a = rng.uniform(0, 10, size=(16, 24))   # 125 m on our grid, aligned
    p = tmp / "fine.tif"
    write(p, a, from_origin(500_000.0, 1_800_000.0, 125.0, 125.0), OUR, -1.0)
    g, info = cm.to_grid(p, box_t, shape, OUR, 25.0)
    assert info["subpixels_per_side"] == 5
    want = a.astype("float32").astype("float64").reshape(8, 2, 12, 2).sum(axis=(1, 3))
    assert np.allclose(g, want, rtol=1e-9, atol=1e-9)
    k = rng.uniform(0, 1000, size=(2, 3))   # 1 km on our grid, aligned: each 250 m cell = 1 / 16 of its pixel
    q = tmp / "coarse.tif"
    write(q, k, from_origin(500_000.0, 1_800_000.0, 1000.0, 1000.0), OUR, -1.0)
    g, info = cm.to_grid(q, box_t, shape, OUR, 25.0)
    assert info["subpixels_per_side"] == 40
    want = np.kron(k.astype("float32").astype("float64"), np.ones((4, 4))) / 16
    assert np.allclose(g, want, rtol=1e-9, atol=1e-9)
    print("ok: nested grids exact (125 m = 2 x 2 sums, 1 km = 1 / 16 per cell)")


def test_stats_and_mask():
    rng = np.random.default_rng(11)
    h = w = 8
    mask = np.ones((h, w), bool)
    mask[0, 0] = mask[5, 6] = False          # blocks (0, 0) and (1, 1) not full
    ref = np.where(mask, rng.uniform(0, 5, (h, w)), np.nan)
    pop = rng.uniform(0, 5, (h, w))
    pop[2, 2] = 0.0
    bui = rng.integers(0, 3, (h, w)).astype(float)
    s = cm.panel_stats(pop, mask, bui, ref, 4)
    tot = pop.sum()
    assert abs(s["total_pop_box"] - tot) < 1e-12
    assert abs(s["pop_share_masked"] - (pop[0, 0] + pop[5, 6]) / tot) < 1e-12
    assert abs(s["pop_share_bui0"] - pop[mask & (bui == 0)].sum() / tot) < 1e-12
    full = [(0, 1), (1, 0)]
    assert s["n_blocks_1km"] == 2
    # by hand: two blocks -> Spearman needs >= 3: NaN; with 2 x 2 cell blocks it is computed
    assert np.isnan(s["spearman_1km_vs_version"])
    s2 = cm.panel_stats(pop, mask, bui, ref, 2)
    pb, rb = [], []
    for bi in range(4):
        for bj in range(4):
            sl = (slice(2 * bi, 2 * bi + 2), slice(2 * bj, 2 * bj + 2))
            if mask[sl].all():
                pb.append(pop[sl].sum())
                rb.append(ref[sl].sum())
    assert s2["n_blocks_1km"] == len(pb) == 14
    rp, rr = pd.Series(pb).rank().to_numpy(), pd.Series(rb).rank().to_numpy()
    assert abs(s2["spearman_1km_vs_version"] - np.corrcoef(rp, rr)[0, 1]) < 1e-12
    assert full and cm.block_sums(np.arange(16.0).reshape(4, 4), 2).tolist() == [[10.0, 18.0], [42.0, 50.0]]
    # mask: NaN outside (drawn with the bad colour = grey), 0 inside stays 0
    d = cm.density(pop, mask)
    assert np.isnan(d[0, 0]) and np.isnan(d[5, 6]) and d[2, 2] == 0.0
    assert abs(d[3, 3] - pop[3, 3] / 0.0625) < 1e-12 and np.isfinite(d[mask]).all()
    cmap = cm.colormap()
    assert np.allclose(cmap(np.ma.masked_invalid([np.nan]))[0], to_rgba(cm.MASK_GREY))
    assert np.allclose(cmap.get_under(), to_rgba("#ffffff"))
    print("ok: 1 km blocks, Spearman, masked / BUI = 0 shares = by hand; mask NaN -> grey, 0 stays 0")


def test_end_to_end(tmp: Path):
    rng = np.random.default_rng(2)
    lon, lat = -104.9903, 39.7392
    cx, cy = Transformer.from_crs("EPSG:4326", OUR, always_xy=True).transform(lon, lat)
    x0, y1 = 250.0 * np.floor(cx / 250.0) - 30_000, 250.0 * np.floor(cy / 250.0) + 30_000
    n = 240  # 60 km of our cells; the box is 12 km
    gt = from_origin(x0, y1, 250.0, 250.0)
    pop = rng.uniform(0, 20, (n, n))
    pop[100:110, 100:140] = -9999.0         # water / no county inside the box
    bui = rng.integers(0, 4, (n, n)).astype(float)
    dasym, cut, data = tmp / "dasym", tmp / "cut", tmp / "data"
    write(dasym / "conus" / "V56" / "predictions" / "pop_2010.tif", pop, gt, OUR, -9999.0)
    write(cut / "conus" / "layers" / "BUI" / "2010_BUI.tif", bui, gt, OUR, -1.0)
    mx, my = Transformer.from_crs(OUR, "ESRI:54009", always_xy=True).transform(cx, cy)
    ghs = rng.uniform(0, 3, (300, 300))
    write(data / "ghs" / "ghs_2010.tif", ghs, from_origin(mx - 15_000, my + 15_000, 100.0, 100.0), "ESRI:54009",
          -200.0)
    cfg = {"reference": "V56", "products": {
        "ghs": {"label": "GHS test", "path": "ghs/ghs_{YEAR}.tif", "years": [2010], "input_unit": "x",
                "input_unit_class": "block", "input_unit_source": "https://example.org"}},
           "city_maps": {"version": "V56", "version_label": "v5.6", "box_km": 12, "block_km": 1, "subpixel_m": 25,
                         "years": {2010: ["ghs"]},
                         "cities": {"denver": {"label": "Denver, CO", "lon": lon, "lat": lat}}}}
    cp = tmp / "ext.yaml"
    cp.write_text(yaml.safe_dump(cfg))
    out = tmp / "maps"
    common = ["--config", str(cp), "--data-root", str(data), "--dasym-root", str(dasym), "--cutout-root", str(cut),
              "--out-dir", str(out)]
    cm.main(common + ["--check"])
    assert not out.exists()
    cm.main(common)
    assert (out / "denver_2010.png").exists()
    s = pd.read_csv(out / "city_maps_summary.csv").set_index("product")
    win = cm.box_window(gt, cx, cy, 12)
    assert win.width == win.height == 48
    r0, c0 = int(win.row_off), int(win.col_off)
    vb = pop[r0:r0 + 48, c0:c0 + 48]
    m = vb != -9999.0
    assert (~m).sum() > 0
    assert abs(s.loc["V56", "total_pop_box"] - vb[m].astype("float32").astype("float64").sum()) < 1e-3
    bb = bui[r0:r0 + 48, c0:c0 + 48]
    v = vb.astype("float32").astype("float64")
    assert abs(s.loc["V56", "pop_share_bui0"] - v[m & (bb == 0)].sum() / v[m].sum()) < 1e-9
    g, _ = cm.to_grid(data / "ghs" / "ghs_2010.tif", rasterio.open(dasym / "conus" / "V56" / "predictions" /
                                                                  "pop_2010.tif").window_transform(win), (48, 48),
                      OUR, 25.0)
    assert abs(s.loc["ghs", "total_pop_box"] - g.sum()) < 1e-6 * g.sum()
    assert abs(s.loc["ghs", "pop_share_masked"] - g[~m].sum() / g.sum()) < 1e-9
    assert s.loc["ghs", "input_unit_class"] == "block" and s.loc["V56", "spearman_1km_vs_version"] > 0.999
    assert (s["note"] == cm.NOTE).all()
    # a missing product file stops --check
    (data / "ghs" / "ghs_2010.tif").unlink()
    try:
        cm.main(common + ["--check"])
    except SystemExit as e:
        assert "inputs missing" in str(e)
    else:
        raise AssertionError("--check did not stop on a missing file")
    print("ok: end to end (box from lon / lat, PNG + CSV = by hand, --check)")


if __name__ == "__main__":
    for t in (test_conservation, test_nested, test_end_to_end):
        with tempfile.TemporaryDirectory() as d:
            t(Path(d))
    test_stats_and_mask()
    print("ALL OK")
