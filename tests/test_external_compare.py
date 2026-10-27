"""Synthetic test of src/validation/external_compare.py (external gridded products vs v5.4 on the same tracts):

    python tests/test_external_compare.py        (needs the hisdac env: exactextract, rasterio, geopandas)

Builds, in a temporary folder, a projected product raster (with a nodata block) and a lon / lat one, tracts (whole
pixels, partial pixels, a tract over nodata, one partly outside the raster, a tract not evaluated by the reference)
and a reference tract_errors_{YEAR}.csv, then checks (a) the tract sums = brute force (pixel square x polygon
intersection area x value, in the raster's own CRS), one process and several chunks; (b) the tract over nodata and the
one partly outside are left out, the not-evaluated one is never read; (c) on the kept subset the product, the
reference (pop_model) and areal weighting (pop_baseline) metrics = the same metrics computed by hand on that subset;
(d) a product without files is a `missing` row and `inventory --available` leaves it out; (e) path resolution: the
case-insensitive fallback, `exclude`, an ambiguous glob.
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "validation"))

import geopandas as gpd  # noqa: E402
import rasterio  # noqa: E402
import yaml  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from shapely.geometry import Polygon, box  # noqa: E402

import external_compare as ec  # noqa: E402
from tract_validate import mdape  # noqa: E402

YEAR = 2000
TRACT_CRS = "ESRI:102039"
PRJ_CRS = "ESRI:54009"  # Mollweide, as GHS-POP
ND = -200.0


def write(path: Path, a: np.ndarray, transform, crs, nodata):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=a.shape[1], height=a.shape[0], count=1, dtype="float32",
                      crs=crs, transform=transform, nodata=nodata) as d:
        d.write(a.astype("float32"), 1)


def brute(path: Path, geoms) -> list[tuple[float, float, float]]:
    """(sum, valid coverage, all coverage) per geometry: each pixel square intersected with the polygon."""
    with rasterio.open(path) as src:
        a, t, nd = src.read(1), src.transform, src.nodata
    out = []
    for g in geoms:
        s = n = na = 0.0
        for i in range(a.shape[0]):
            for j in range(a.shape[1]):
                x0, y1 = t * (j, i)
                x1, y0 = t * (j + 1, i + 1)
                f = box(x0, y0, x1, y1).intersection(g).area / abs(t.a * t.e)
                if f <= 0:
                    continue
                na += f
                if a[i, j] != nd:
                    s += f * a[i, j]
                    n += f
        out.append((s, n, na))
    return out


def test_sums_brute_force(tmp: Path):
    rng = np.random.default_rng(1)
    a = rng.uniform(0, 100, size=(12, 15))
    a[0:3, 0:3] = ND
    tr = from_origin(-9_000_000.0, 4_600_000.0, 100.0, 100.0)
    p = tmp / "prj.tif"
    write(p, a, tr, PRJ_CRS, ND)
    x0, y0 = -9_000_000.0, 4_600_000.0
    geoms = [box(x0 + 300, y0 - 900, x0 + 700, y0 - 500),                                   # whole pixels
             Polygon([(x0 + 420, y0 - 130), (x0 + 1210, y0 - 380), (x0 + 760, y0 - 1110)]),  # partial pixels
             box(x0 + 50, y0 - 250, x0 + 450, y0 - 150),                                     # over nodata
             box(x0 + 1350, y0 - 600, x0 + 1700, y0 - 300)]                                  # partly outside
    gdf = gpd.GeoDataFrame({"GISJOIN": ["G1", "G2", "G3", "G4"]}, geometry=geoms, crs=PRJ_CRS).to_crs(TRACT_CRS)
    for workers, chunks in ((1, 8), (2, 2)):
        s = ec.tract_sums(p, gdf, workers=workers, chunks_per_worker=chunks)
        back = gdf.to_crs(PRJ_CRS).geometry  # the polygons as exactextract sees them
        for k, (bs, bn, bna) in enumerate(brute(p, back)):
            assert abs(s["pop"][k] - bs) < 1e-3 * max(1, bs), (k, s["pop"][k], bs)
            assert abs(s["cells"][k] - bn) < 1e-6 + 1e-6 * bn and abs(s["cells_all"][k] - bna) < 1e-6 + 1e-6 * bna
        kept, outside, nodata = ec.keep_mask(s, 0.0)
        assert kept.tolist() == [True, True, False, False], s
        assert outside.tolist() == [False, False, False, True] and nodata.tolist() == [False, False, True, False]
        assert abs(s["cells_poly"][1] - back.iloc[1].area / 1e4) < 1e-9
    # a nodata share allowance keeps the nodata tract, never the one outside
    assert ec.keep_mask(s, 0.9)[0].tolist() == [True, True, True, False]

    # lon / lat raster (as GPW / WorldPop): coverage in degrees, same brute force
    g = from_origin(-100.0, 41.0, 0.01, 0.01)
    q = tmp / "geo.tif"
    write(q, rng.uniform(0, 50, size=(30, 40)), g, "EPSG:4326", -9999.0)
    ll = [Polygon([(-99.93, 40.97), (-99.71, 40.91), (-99.85, 40.79)]), box(-99.995, 40.995, -99.705, 40.905)]
    gl = gpd.GeoDataFrame({"GISJOIN": ["L1", "L2"]}, geometry=ll, crs="EPSG:4326").to_crs(TRACT_CRS)
    s = ec.tract_sums(q, gl)
    for k, (bs, bn, bna) in enumerate(brute(q, gl.to_crs("EPSG:4326").geometry)):
        assert abs(s["pop"][k] - bs) < 1e-3 * max(1, bs), (k, s["pop"][k], bs)
    assert ec.keep_mask(s, 0.0)[0].all()
    print("ok: tract sums = brute force (projected and lon / lat raster, 1 process and chunks); nodata / outside out")


def test_extract_evaluate(tmp: Path):
    data, res, tracts, work = tmp / "data", tmp / "results", tmp / "tracts", tmp / "work"
    rng = np.random.default_rng(7)
    # product raster in Mollweide; tracts are 4 x 4 pixel blocks (+ odd shapes) in the tract CRS
    a = rng.uniform(0, 30, size=(40, 40))
    a[0:4, 36:40] = ND
    x0, y0 = -9_000_000.0, 4_600_000.0
    write(data / "prod" / f"pop_{YEAR}.TIF", a, from_origin(x0, y0, 100.0, 100.0), PRJ_CRS, ND)
    geoms, ids = [], []
    for r in range(8):
        for c in range(8):
            geoms.append(box(x0 + 40 + c * 430, y0 - 40 - (r + 1) * 430, x0 + 40 + (c + 1) * 430, y0 - 40 - r * 430))
            ids.append(f"G{r:02d}{c:02d}")
    geoms.append(box(x0 + 3700, y0 - 300, x0 + 3950, y0 - 50))     # over the nodata block
    ids.append("GND")
    geoms.append(box(x0 + 3900, y0 - 2000, x0 + 4300, y0 - 1600))  # partly outside the raster
    ids.append("GOUT")
    geoms.append(box(x0 + 100, y0 - 300, x0 + 200, y0 - 200))      # not evaluated by the reference
    ids.append("GBAD")
    t = gpd.GeoDataFrame({"GISJOIN": ids}, geometry=geoms, crs=PRJ_CRS).to_crs(TRACT_CRS)
    tracts.mkdir()
    t.to_file(tracts / f"tracts_{YEAR}.gpkg", engine="pyogrio")
    n = len(ids)
    obs = rng.integers(0, 4000, n).astype(float)
    obs[3] = 5.0   # below the MAPE floor
    obs[4] = 0.0   # no APE
    te = pd.DataFrame({"GISJOIN": ids, "flag": ["ok"] * (n - 1) + ["multi_county"],
                       "n_cells": rng.integers(1, 200, n), "pop_obs": obs,
                       "pop_model": obs * rng.uniform(0.5, 1.6, n), "pop_baseline": obs * rng.uniform(0.1, 3.0, n),
                       "gap": rng.random(n) < 0.2})
    ref = "Dasy_REF"
    (res / "validation" / "conus" / ref).mkdir(parents=True)
    te.to_csv(res / "validation" / "conus" / ref / f"tract_errors_{YEAR}.csv", index=False)
    cfg = {"reference": ref, "reference_label": "v5.4 (test)",
           "products": {"prod": {"label": "Product", "path": "prod/pop_{YEAR}.tif", "years": [YEAR],
                                 "input_unit": "block", "input_unit_source": "https://example.org/a"},
                        "gone": {"label": "Missing", "path": "gone/*{YY}.tif", "years": [YEAR],
                                 "input_unit": "county", "input_unit_source": "https://example.org/b"}}}
    cp = tmp / "external.yaml"
    cp.write_text(yaml.safe_dump(cfg))
    common = ["--config", str(cp), "--data-root", str(data), "--results-root", str(res), "--work-dir", str(work)]

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ec.main(["inventory", "--available"] + common)
    assert buf.getvalue().split() == ["prod"], buf.getvalue()   # found through the case-insensitive fallback

    ec.main(["extract", "--product", "prod", "--tract-dir", str(tracts), "--workers", "1"] + common)
    s = pd.read_csv(work / "sums" / f"prod_{YEAR}.csv")
    assert "GBAD" not in set(s["GISJOIN"]) and len(s) == n - 1
    out = tmp / "ext.csv"
    ec.main(["evaluate", "--out", str(out), "--plot", str(tmp / "ext.png")] + common)
    df = pd.read_csv(out)
    assert (tmp / "ext.png").exists()

    ev = te[te["flag"] == "ok"].merge(s, on="GISJOIN")
    sub = ev[~ev["GISJOIN"].isin(["GND", "GOUT"])]
    assert len(sub) == 64
    rows = df[(df["year"] == YEAR) & (df["product"] == "prod")].set_index("method")
    assert set(rows.index) == {"prod", ref, "areal_weighting"}
    assert int(rows.loc["prod", "n_outside"]) == 1 and int(rows.loc["prod", "n_nodata"]) == 1
    assert int(rows.loc[ref, "n_tracts"]) == 64 and int(rows.loc[ref, "n_eval"]) == n - 1
    assert abs(rows.loc[ref, "tract_share"] - 64 / (n - 1)) < 1e-12
    assert abs(rows.loc[ref, "pop_share"] - sub["pop_obs"].sum() / ev["pop_obs"].sum()) < 1e-12
    o = sub["pop_obs"].to_numpy()
    for method, col in (("prod", "pop"), (ref, "pop_model"), ("areal_weighting", "pop_baseline")):
        p = sub[col].to_numpy()
        pos, big = o > 0, o >= 10
        assert abs(rows.loc[method, "mdape"] - mdape(o, p)) < 1e-9, method
        assert abs(rows.loc[method, "mape"] - np.mean(np.abs(p[big] - o[big]) / o[big]) * 100) < 1e-9
        assert abs(rows.loc[method, "p90_ape"] - np.percentile(np.abs(p[pos] - o[pos]) / o[pos] * 100, 90)) < 1e-9
        assert abs(rows.loc[method, "total_ratio"] - p.sum() / o.sum()) < 1e-12
        g = sub["gap"].to_numpy()
        assert abs(rows.loc[method, "mdape_gap"] - mdape(o[g], p[g])) < 1e-9
        assert abs(rows.loc[method, "mdape_no_gap"] - mdape(o[~g], p[~g])) < 1e-9
        d = o / (sub["n_cells"].to_numpy() * 0.0625)
        sel = (d >= 50) & (d < 500)
        assert np.isclose(rows.loc[method, "mdape_dens_50_500"], mdape(o[sel], p[sel]), equal_nan=True)
    # the product sum: exact pixel coverage (tract 0 = G0000)
    b = brute(data / "prod" / f"pop_{YEAR}.TIF", t[t["GISJOIN"] == "G0000"].to_crs(PRJ_CRS).geometry)[0][0]
    assert abs(sub.set_index("GISJOIN").loc["G0000", "pop"] - b) < 1e-3 * b
    assert rows.loc["prod", "input_unit"] == "block"
    # all evaluated tracts: the reference and areal weighting on everything flagged ok
    allt = df[(df["year"] == YEAR) & (df["product"] == "all_tracts")].set_index("method")
    assert abs(allt.loc[ref, "mdape"] - mdape(ev["pop_obs"].to_numpy(), ev["pop_model"].to_numpy())) < 1e-9
    # missing product: a row per year, status missing
    miss = df[df["product"] == "gone"]
    assert miss["status"].tolist() == ["missing"] and miss["n_tracts"].tolist() == [0]
    print("ok: extract -> evaluate: kept subset, product / reference / areal weighting metrics = by hand, missing row")


def test_resolve(tmp: Path):
    root = tmp / "res"
    for f in ("grump1/1990/a/glup90g.bil", "grump1/1990/a/glup90ag.bil", "fj/grids/x/POP_M3_2010/hdr.adf",
              "two/a_2000.tif", "two/b_2000.tif"):
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        (root / f).write_text("x")
    p, _ = ec.resolve(root, {"path": "grump1/{YEAR}/**/*.bil", "exclude": "ag\\.bil$"}, 1990)
    assert p is not None and p.name == "glup90g.bil"
    p, note = ec.resolve(root, {"path": "grump1/{YEAR}/**/*.bil"}, 1990)
    assert p is None and "2 matches" in note
    p, _ = ec.resolve(root, {"path": "fj/grids/**/pop_m3_{YEAR}"}, 2010)
    assert p is not None and p.name == "POP_M3_2010"
    p, note = ec.resolve(root, {"path": "two/*_{YEAR}.tif"}, 2000)
    assert p is None and "2 matches" in note
    p, note = ec.resolve(root, {"path": "none/{YY}.tif"}, 2000)
    assert p is None and "nothing matches" in note and "00.tif" in note
    print("ok: resolve (exclude, case-insensitive fallback, ambiguous, missing)")


def test_real_config():
    cfg = ec.load_config(REPO / "configs" / "external_grids.yaml")
    assert cfg["reference"] == "Dasy_CONUS_RF_v3_all"
    assert set(cfg["products"]) == {"ghs_pop", "worldpop", "gpw4", "grump1", "fj_m3", "fj_m5"}
    yrs = {k: v["years"] for k, v in cfg["products"].items()}
    assert yrs["ghs_pop"] == [1980, 1990, 2000, 2010] and yrs["grump1"] == [1990, 2000]
    assert 1960 not in yrs["fj_m3"] and yrs["fj_m3"] == yrs["fj_m5"] and min(yrs["fj_m3"]) == 1910
    assert all(1910 <= y <= 2010 for v in yrs.values() for y in v)
    print("ok: configs/external_grids.yaml")


if __name__ == "__main__":
    test_real_config()
    with tempfile.TemporaryDirectory() as d:
        test_resolve(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_sums_brute_force(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_extract_evaluate(Path(d))
    print("ALL OK")
