"""Synthetic test of src/grid/bui_fix.py (BUI cap: cells above the cap -> median of the 3 x 3 neighbours):

    python tests/test_bui_fix.py        (needs the hisdac env: numpy, pandas, rasterio, pyproj)

Builds a small cutout (40 x 30 cells, two years, BUI with NaN nodata, BUPL, zones) in a temporary folder and checks
(a) an isolated large value, (b) neighbours above the cap left out (a cell surrounded only by them -> 0), (c) cells on
the window edge and across a strip boundary, (d) strips of 1, 7 and 512 rows = whole window = a brute-force loop;
also: the rerun gives the same file, BUI_raw keeps the original, --check changes nothing, no bui_cap -> error, the
raw-HISDAC check over an offset window.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "grid"))

import rasterio  # noqa: E402
import yaml  # noqa: E402
from affine import Affine  # noqa: E402
from pyproj import CRS  # noqa: E402

import bui_fix  # noqa: E402
from make_cutout import write_tif  # noqa: E402

CAP = 3e7
H, W = 40, 30
YEARS = [1920, 2010]
CUT_CRS = CRS.from_user_input("ESRI:102039")
TRANSFORM = Affine(250.0, 0, 1_500_000.0, 0, -250.0, 2_000_000.0)


def synthetic_bui(year: int) -> np.ndarray:
    rng = np.random.default_rng(year)
    a = rng.integers(0, 50_000, size=(H, W)).astype("float32")
    a[rng.random((H, W)) < 0.3] = 0
    a[0:2, 25:30] = np.nan                    # nodata
    a[10, 10] = 5e8                           # (a) isolated
    a[10, 11] = np.nan                        #     with a nodata neighbour (left out)
    a[20, 20], a[20, 21] = 4e7, 6e7           # (b) two neighbours above the cap
    a[30:33, 5:8] = 7e7                       # (b) 3 x 3 block: the centre has no usable neighbour -> 0
    a[0, 0] = 1e9                             # (c) corner: 3 neighbours
    a[H - 1, 15] = 2e8                        # (c) bottom edge
    a[6, 3], a[7, 3] = 5e7, 9e7               # (c) across the boundary of 7-row strips (rows 6 | 7)
    if year == 2010:
        a[15, W - 1] = 3.5e7                  # (c) right edge
        a[25, 12] = CAP                       # exactly the cap: kept
    return a


def brute(a: np.ndarray) -> np.ndarray:
    valid = np.isfinite(a)
    over = valid & (a > CAP)
    out = a.astype("float64").copy()
    for r, c in zip(*np.nonzero(over)):
        vals = [a[i, j] for i in range(r - 1, r + 2) for j in range(c - 1, c + 2)
                if (i, j) != (r, c) and 0 <= i < H and 0 <= j < W and valid[i, j] and not over[i, j]]
        out[r, c] = np.median(vals) if vals else 0.0
    return out


def make_cutout(tmp: Path, cap: bool = True) -> tuple[Path, Path]:
    cut = tmp / "cutouts" / "synthetic"
    for y in YEARS:
        write_tif(cut / "layers" / "BUI" / f"{y}_BUI.tif", synthetic_bui(y), TRANSFORM, CUT_CRS, float("nan"))
        write_tif(cut / "layers" / "BUPL" / f"{y}_BUPL.tif", np.full((H, W), 3, "int32"), TRANSFORM, CUT_CRS, None)
        z = np.zeros((H, W), "int32")
        z[:, :15], z[:, 15:] = 1, 2
        write_tif(cut / "zones" / f"zones_{y}.tif", z, TRANSFORM, CUT_CRS, 0)
        pd.DataFrame({"zone_id": [1, 2], "GISJOIN": ["G01", "G02"], "state": ["A", "A"], "name": ["West", "East"],
                      "pop": [100, 200], "status": "ok", "area_km2": [1.0, 1.0]}).to_csv(
            cut / "zones" / f"zones_{y}.csv", index=False)
    cfg = {"name": "synthetic", "states": "all", "years": YEARS, "grid_reference": "BUI",
           "layers": [{"name": "BUI", "path": "BUI/{YEAR}_BUI.tif", "years": "all", "resampling": "none",
                       "dtype": "float32"}]}
    if cap:
        cfg["bui_cap"] = {"max": CAP, "replace": "neighbour_median"}
    path = tmp / "study.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return path, cut


def read(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1).astype("float64")


def same(a, b) -> bool:
    return np.array_equal(a, b, equal_nan=True)


def run(cfg: Path, tmp: Path, qa: str, *extra):
    bui_fix.main(["--config", str(cfg), "--cutout-root", str(tmp / "cutouts"), "--qa-dir", str(tmp / qa), *extra])


def test_fix():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        cfg, cut = make_cutout(tmp)
        out = {}
        for rows in (512, 7, 1):  # 512 >= H: the whole window in one strip
            run(cfg, tmp, f"qa{rows}", "--block-rows", str(rows))
            out[rows] = {y: read(cut / "layers" / "BUI" / f"{y}_BUI.tif") for y in YEARS}
        for y in YEARS:
            raw = read(cut / "layers" / "BUI_raw" / f"{y}_BUI.tif")
            assert same(raw, synthetic_bui(y).astype("float64")), "BUI_raw is not the original"
            ref = brute(synthetic_bui(y)).astype("float32").astype("float64")
            for rows in out:
                assert same(out[rows][y], ref), f"{y}: strips of {rows} rows differ from the brute force"
            f = out[512][y]
            a = synthetic_bui(y)
            # (a) isolated: median of the 7 valid neighbours (the NaN one left out)
            nb = [a[i, j] for i in (9, 10, 11) for j in (9, 10, 11) if (i, j) not in ((10, 10), (10, 11))]
            assert f[10, 10] == np.float32(np.median(nb))
            # (b) the other cell above the cap is left out; the centre of the block has none left -> 0
            nb = [a[i, j] for i in (19, 20, 21) for j in (19, 20, 21) if (i, j) not in ((20, 20), (20, 21))]
            assert f[20, 20] == np.float32(np.median(nb))
            assert f[31, 6] == 0 and f[30, 5] <= CAP
            # (c) corner: 3 neighbours
            assert f[0, 0] == np.float32(np.median([a[0, 1], a[1, 0], a[1, 1]]))
            assert np.nanmax(f) <= CAP
            assert np.isnan(f[0, 27]), "nodata must stay nodata"
            q = pd.read_csv(tmp / "qa512" / f"bui_fixed_{y}.csv")
            assert len(q) == int((np.nan_to_num(a) > CAP).sum())
            assert (q["BUI_before"] > CAP).all() and (q["BUI_after"] <= CAP).all()
            assert set(q["name"]) <= {"West", "East"} and (q["BUPL"] == 3).all()
            corner = q[(q["row"] == 0) & (q["col"] == 0)].iloc[0]
            assert corner["nb_in_window"] == 3 and corner["nb_used"] == 3
            centre = q[(q["row"] == 31) & (q["col"] == 6)].iloc[0]
            assert centre["nb_used"] == 0 and centre["nb_over_cap"] == 8 and centre["BUI_after"] == 0
        assert out[512][2010][25, 12] == CAP, "a cell exactly at the cap is kept"
        s = pd.read_csv(tmp / "qa512" / "bui_fix_summary.csv")
        assert s["applied"].all() and (s["max_after"] <= CAP).all() and (s["max_before"] > CAP).all()
        assert (s["n_set_to_0"] >= 1).all()
        # rerun: same file; --check on the fixed cutout counts from BUI_raw and changes nothing
        before = read(cut / "layers" / "BUI" / "2010_BUI.tif")
        run(cfg, tmp, "qa_rerun")
        assert same(read(cut / "layers" / "BUI" / "2010_BUI.tif"), before)
        run(cfg, tmp, "qa_check", "--check")
        assert same(read(cut / "layers" / "BUI" / "2010_BUI.tif"), before)
        c = pd.read_csv(tmp / "qa_check" / "bui_check_summary.csv")
        assert (~c["applied"]).all() and (c["n_over_cap"].to_numpy() == s["n_over_cap"].to_numpy()).all()
    print("ok fix: isolated, neighbours above the cap, edges, strips 1/7/512 = whole window = brute force, rerun")


def test_no_cap_block():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        cfg, cut = make_cutout(tmp, cap=False)
        orig = read(cut / "layers" / "BUI" / "1920_BUI.tif")
        try:
            run(cfg, tmp, "qa")
        except SystemExit as e:
            assert "no bui_cap block" in str(e), e
        else:
            raise AssertionError("expected SystemExit without bui_cap")
        run(cfg, tmp, "qa", "--check")  # counts with the default cap, writes nothing in the cutout
        assert same(read(cut / "layers" / "BUI" / "1920_BUI.tif"), orig)
        assert not (cut / "layers" / "BUI_raw").exists()
        c = pd.read_csv(tmp / "qa" / "bui_check_summary.csv")
        assert c.loc[c["year"] == 1920, "n_over_cap"].item() == int((np.nan_to_num(synthetic_bui(1920)) > CAP).sum())
    print("ok no bui_cap: fix refused, --check counts only")


def test_check_raw_window():
    """--check --hisdac-dir: the raw BUI over an offset window (as the Massachusetts window of the HISDAC raster)."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        cfg, cut = make_cutout(tmp, cap=False)
        hisdac = tmp / "hisdac"
        big = np.zeros((H + 10, W + 8), "float32")
        big[5:5 + H, 3:3 + W] = synthetic_bui(1920)
        big[0, 0] = 9e9  # outside the window: not counted
        write_tif(hisdac / "BUI" / "1920_BUI.tif", big, TRANSFORM, CUT_CRS, float("nan"))
        win = tmp / "window.json"
        win.write_text(json.dumps({"col_off": 3, "row_off": 5, "width": W, "height": H}))
        run(cfg, tmp, "qa", "--check", "--hisdac-dir", str(hisdac), "--window-json", str(win), "--block-rows", "7")
        c = pd.read_csv(tmp / "qa" / "bui_check_summary.csv")
        assert c["year"].tolist() == [1920], "2010 has no raw file and is skipped"
        assert c["n_over_cap"].item() == int((np.nan_to_num(synthetic_bui(1920)) > CAP).sum())
        q = pd.read_csv(tmp / "qa" / "bui_check_1920.csv")
        assert set(zip(q["row"], q["col"])) >= {(0, 0), (10, 10)}, "rows / cols are relative to the window"
    print("ok check over a raw window")


if __name__ == "__main__":
    test_fix()
    test_no_cap_block()
    test_check_raw_window()
    print("ALL OK")
