"""Synthetic test of src/grid/record_uncertainty.py (HISDAC record uncertainty, docs/conus_plan.md), runnable without
the cluster:

    python tests/test_record_uncertainty.py      (needs the hisdac env: numpy, pandas, rasterio, matplotlib)

Builds 3 counties on a 20 x 30 zone grid, BUPR 2000 / 2010 / 2015 and NobuiltYear (counts) on the same grid, and
BUPR_contemp on a larger grid shifted by whole cells (read through the WarpedVRT); checks against brute force:
  - the shifted contemp is aligned exactly (grid_check: not on the zone grid, read by WarpedVRT)
  - county sums, A = (contemp - BUPR_2015) / contemp clipped at 0 (a negative county counted), B_year
  - cell checks: d == NobuiltYear, d < 0 cells; NobuiltYear recognised as a count
  - threshold table: counties / pop kept, train / test kept, gap counties kept; gap overlap; strips (2 rows) ==
    one strip
  - a 0/1 NobuiltYear: flag, no B_year
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from affine import Affine

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "grid"))
import record_uncertainty as ru  # noqa: E402

CRS = "EPSG:5070"
T = Affine(250, 0, 100000, 0, -250, 2000000)
H, W = 20, 30


def write(path: Path, arr, transform=T, nodata=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1, dtype=arr.dtype,
                       crs=CRS, transform=transform, nodata=nodata) as dst:
        dst.write(arr, 1)


def build(tmp: Path, nobuilt_flag=False):
    rng = np.random.default_rng(7)
    z = np.zeros((H, W), "uint16")
    z[1:19, 1:10], z[1:19, 10:20], z[1:19, 20:29] = 1, 2, 3
    cut = tmp / "cut"
    write(cut / "zones" / "zones_2010.tif", z, nodata=0)
    pd.DataFrame({"zone_id": [1, 2, 3], "GISJOIN": ["G01", "G02", "G03"], "state": ["X", "X", "Y"],
                  "name": ["a", "b", "c"], "pop": 1.0, "status": "ok", "area_km2": 1.0}).to_csv(
        cut / "zones" / "zones_2010.csv", index=False)
    hd = tmp / "hisdac"
    b = {y: rng.integers(0, 5, (H, W)).astype("int32") for y in (2000,)}
    b[2010] = b[2000] + rng.integers(0, 3, (H, W)).astype("int32")
    b[2015] = b[2010] + rng.integers(0, 2, (H, W)).astype("int32")
    nb = rng.integers(0, 4, (H, W)).astype("int32")
    if nobuilt_flag:
        nb = (nb > 0).astype("int32")
    contemp = b[2015] + nb
    contemp[3:6, 2:5] -= 2  # some cells with contemp < BUPR_2015 (d < 0 or d < nb)
    contemp = np.clip(contemp, 0, None)
    contemp[:, 20:29] = 0  # county 3: contemp far below BUPR_2015 -> negative A
    contemp[1:19, 20:29] = b[2015][1:19, 20:29] // 3
    for y, a in b.items():
        write(hd / "BUPR" / f"{y}_BUPR.tif", a)
    write(hd / "FBUY" / "NobuiltYear.tif", nb)
    big = np.zeros((H + 5, W + 4), "int32")  # contemp on a larger grid: zone cell (0, 0) = big cell (3, 2)
    big[3:3 + H, 2:2 + W] = contemp
    write(tmp / "extra" / "BUPR_contemp.tif", big, transform=T * Affine.translation(-2, -3))
    feats = tmp / "feat"
    for y, pops, bui in ((2000, [100.0, 50.0, 10.0], [5.0, 5.0, 0.0001]), (2010, [200.0, 80.0, 20.0], [6.0, 6.0, 6.0])):
        (feats / f"Y{y}").mkdir(parents=True)
        pd.DataFrame({"year": y, "GISJOIN": ["G01", "G02", "G03"], "pop": pops, "bui": bui, "n_cells": 162,
                      "n_masked": 0}).to_csv(feats / f"Y{y}" / "county_features.csv", index=False)
    pd.DataFrame({"GISJOIN": ["G01", "G02", "G03"], "part": ["train", "test", "train"], "fold": [0, -1, 1]}).to_csv(
        tmp / "split.csv", index=False)
    return z, b, nb, contemp


def run(tmp: Path, out: str, block=1024):
    ru.main(["--contemp", str(tmp / "extra" / "BUPR_contemp.tif"), "--hisdac-dir", str(tmp / "hisdac"),
             "--cutout", str(tmp / "cut"), "--features", str(tmp / "feat"), "--split", str(tmp / "split.csv"),
             "--years", "2000", "2010", "--thresholds", "0.2", "0.5", "0.8", "--block-rows", str(block),
             "--out-dir", str(tmp / out)])
    return tmp / out


def test_record_uncertainty():
    tmp = Path(tempfile.mkdtemp())
    try:
        z, b, nb, contemp = build(tmp)
        out = run(tmp, "res")
        gc = pd.read_csv(out / "grid_check.csv").set_index("raster")
        assert not gc.at["BUPR_contemp", "on_zone_grid"] and gc.at["BUPR_2015", "on_zone_grid"]
        c = pd.read_csv(out / "county_record_uncertainty.csv").set_index("GISJOIN")
        for k, gj in ((1, "G01"), (2, "G02"), (3, "G03")):
            m = z == k
            C, B15, NB = contemp[m].sum(), b[2015][m].sum(), nb[m].sum()
            assert c.at[gj, "contemp"] == C and c.at[gj, "bupr_2015"] == B15 and c.at[gj, "nobuilt"] == NB, gj
            assert np.isclose(c.at[gj, "a"], max((C - B15) / C, 0)), gj
            assert c.at[gj, "a_negative"] == ((C - B15) / C < 0), gj
            for y in (2000, 2010):
                assert np.isclose(c.at[gj, f"b_{y}"], NB / (b[y][m].sum() + NB)), (gj, y)
        assert c.at["G03", "a_negative"] and c.at["G03", "a"] == 0
        cell = pd.read_csv(out / "cell_check.csv").set_index("item")["value"]
        d = contemp.astype(float) - b[2015]
        rec = (contemp > 0) | (b[2015] > 0) | (nb > 0)
        assert int(cell["d_eq_nobuilt"]) == (rec & (d == nb)).sum()
        assert int(cell["d_negative"]) == (rec & (d < 0)).sum()
        assert cell["nobuilt_is_count"] in ("True", True)
        # thresholds: brute force on the 2010 pop
        tt = pd.read_csv(out / "threshold_table.csv")
        for _, r in tt.iterrows():
            ratio = c["a"] if r["measure"] == "A" else c[f"b_{int(r['year'])}"]
            pops = pd.read_csv(tmp / "feat" / f"Y{int(r['year'])}" / "county_features.csv").set_index("GISJOIN")["pop"]
            keep = ~(ratio > r["threshold"])
            assert r["counties_kept"] == keep.sum()
            assert np.isclose(r["pop_share"], pops[keep[keep].index].sum() / pops.sum())
            assert r["train_kept"] == int((keep & (c["part"] == "train")).sum())
            assert r["test_kept"] == int((keep & (c["part"] == "test")).sum())
        # gap: 2000 G03 has bui 1e-4 -> gap; 2010 none (all bui equal per pop... G03 floor 6*162/20 > 5 % of median)
        assert not c["gap_2010"].astype(bool).any() and c.at["G03", "gap_2000"] in (True, "True")
        ov = pd.read_csv(out / "gap_overlap.csv")
        assert (ov["gap_counties"] == 0).all() and (ov["both"] == 0).all()
        assert (out / "threshold_counties.png").exists() and (out / "threshold_by_state.csv").exists()
        # strips of 2 rows == one strip
        out2 = run(tmp, "res2", block=2)
        pd.testing.assert_frame_equal(pd.read_csv(out / "county_record_uncertainty.csv"),
                                      pd.read_csv(out2 / "county_record_uncertainty.csv"))
        pd.testing.assert_frame_equal(pd.read_csv(out / "cell_check.csv"), pd.read_csv(out2 / "cell_check.csv"))
        print("ok record_uncertainty: shifted contemp aligned, county A / B_year, cell checks, thresholds, gap "
              "overlap, strips == one strip")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_nobuilt_flag():
    tmp = Path(tempfile.mkdtemp())
    try:
        build(tmp, nobuilt_flag=True)
        out = run(tmp, "res")
        cell = pd.read_csv(out / "cell_check.csv").set_index("item")["value"]
        assert cell["nobuilt_is_count"] in ("False", False)
        c = pd.read_csv(out / "county_record_uncertainty.csv")
        assert c["b_2010"].isna().all() and c["a"].notna().all()
        assert set(pd.read_csv(out / "threshold_table.csv")["measure"]) == {"A"}
        print("ok record_uncertainty: a 0/1 NobuiltYear is a flag, no B_year")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_record_uncertainty()
    test_nobuilt_flag()
    print("ALL OK")
