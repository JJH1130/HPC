"""City maps: v5.6 next to external population grids on our 250 m grid (docs/conus_plan.md "External comparison with
v5.6", part 2; request docs/handoff/external_v56_request.md; Noi et al. draft, Figure 10). Qualitative: the numbers
measure agreement with v5.6, not accuracy (GHS-POP / WorldPop use finer census input than ours in the US).

Per city (centre lon / lat in the `city_maps` block of configs/external_grids.yaml) and year: a box_km x box_km box
around the centre on the v5.6 prediction grid (ESRI:102039, 250 m cells, box snapped to whole cells). Every product
is moved to those cells with its population kept: each product pixel is split into k x k sub-points (k = pixel size /
subpixel_m, rounded up; 100 m GHS-POP / WorldPop: k = 4, 1 km Fang & Jawitz: k = 40), each carrying 1 / k^2 of the
pixel's people, the sub-points are projected to our CRS and binned into our cells. That is an area-weighted sum for
pixels smaller than our cells and an area-proportional split for larger ones (exact when the grids nest). Product
nodata / negative pixels count as 0 people.

Our mask = the cells with a v5.6 prediction (not water, inside a used county); cells outside it are grey on every
panel (not 0). Colours: people per km2, one log scale per city x year shared by all panels.

Per map (title + <out-dir>/city_maps_summary.csv, one row per city x year x panel):
  total_pop_box             people in the box (v5.6: its cells; a product: all its people that land in the box,
                            also on our masked cells)
  pop_share_masked          share of those people on cells outside our mask (water, no county)
  pop_share_bui0            share on cells inside our mask with BUI = 0 (the request asks it for v5.6; given for all)
  spearman_1km_vs_version   Spearman of the 1 km block density (4 x 4 cells, only blocks fully inside our mask) of
                            the panel vs v5.6 (rank based: the same for the log density)
Outputs: <out-dir>/{city}_{year}.png + city_maps_summary.csv. `--check` only lists the input files (exit 1 if one is
missing; the submit script runs it on the login node).
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.windows import Window

sys.path.insert(0, str(Path(__file__).resolve().parent))
from external_compare import load_config, resolve  # noqa: E402

log = logging.getLogger("external_city_maps")
CELL_KM2 = 0.0625
NOTE = "agreement with v5.6, not accuracy"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, default=Path("configs/external_grids.yaml"))
    p.add_argument("--data-root", type=Path, required=True, help="$DATA_ROOT/raw/external")
    p.add_argument("--dasym-root", type=Path, required=True,
                   help="<dasym-root>/<name>/<version>/predictions/pop_{YEAR}.tif")
    p.add_argument("--cutout-root", type=Path, required=True, help="<cutout-root>/<name>/layers/BUI/{YEAR}_BUI.tif")
    p.add_argument("--name", default="conus")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--cities", nargs="+", help="these cities only (default all of the config)")
    p.add_argument("--years", type=int, nargs="+", help="these years only (default all of the config)")
    p.add_argument("--check", action="store_true", help="list the inputs only; exit 1 if one is missing")
    return p.parse_args(argv)


# ---------------------------------------------------------------- grids

def box_window(transform, cx: float, cy: float, box_km: float) -> Window:
    """Whole-cell window of box_km x box_km around (cx, cy) on a north-up grid."""
    n = int(round(box_km * 1000 / transform.a))
    c = math.floor((cx - transform.c) / transform.a)
    r = math.floor((cy - transform.f) / transform.e)
    return Window(c - n // 2, r - n // 2, n, n)


def read_box(path: Path, win: Window, transform=None):
    """(float64 array, valid mask, window transform) of a window (boundless: outside = nodata)."""
    with rasterio.open(path) as src:
        if transform is not None and src.transform != transform:
            sys.exit(f"ERROR: {path} is not on the grid of the v5.6 prediction")
        nd = src.nodata
        a = src.read(1, window=win, boundless=True, fill_value=nd if nd is not None else 0).astype("float64")
        valid = np.isfinite(a) if nd is None else (a != nd) & np.isfinite(a)
        return a, valid, src.window_transform(win)


def pixel_size_m(src) -> float:
    """Larger side of a pixel in metres (degrees: 111.32 km per degree of latitude)."""
    res = max(abs(src.res[0]), abs(src.res[1]))
    return res * 111_320.0 if src.crs and src.crs.is_geographic else res


def to_grid(path: Path, box_t, shape, dst_crs, subpixel_m: float):
    """Product people on our box cells (float64, shape), population kept: each pixel -> k x k sub-points of
    pop / k^2, projected to dst_crs, binned by cell. Returns (grid, info)."""
    h, w = shape
    x0, y1 = box_t.c, box_t.f
    x1, y0 = x0 + w * box_t.a, y1 + h * box_t.e
    with rasterio.open(path) as src:
        crs = src.crs
        if crs is None:
            sys.exit(f"ERROR: {path} has no CRS")
        k = max(1, math.ceil(pixel_size_m(src) / subpixel_m - 1e-9))
        to_src = Transformer.from_crs(dst_crs, crs, always_xy=True)
        ex = np.concatenate([np.linspace(x0, x1, 41), np.full(41, x1), np.linspace(x1, x0, 41), np.full(41, x0)])
        ey = np.concatenate([np.full(41, y0), np.linspace(y0, y1, 41), np.full(41, y1), np.linspace(y1, y0, 41)])
        sx, sy = to_src.transform(ex, ey)
        inv = ~src.transform
        cs, rs = inv * (np.asarray(sx), np.asarray(sy))
        c0, c1 = math.floor(np.min(cs)) - 2, math.ceil(np.max(cs)) + 2
        r0, r1 = math.floor(np.min(rs)) - 2, math.ceil(np.max(rs)) + 2
        win = Window(c0, r0, c1 - c0, r1 - r0)
        nd = src.nodata
        a = src.read(1, window=win, boundless=True, fill_value=nd if nd is not None else 0).astype("float64")
        wt = src.window_transform(win)
    bad = ~np.isfinite(a) | (a < 0) | ((a == nd) if nd is not None else False)
    a[bad] = 0.0
    rr, cc = np.nonzero(a > 0)
    vals = a[rr, cc] / (k * k)
    off = (np.arange(k) + 0.5) / k
    grid = np.zeros(h * w)
    to_dst = Transformer.from_crs(crs, dst_crs, always_xy=True)
    step = max(1, 2_000_000 // (k * k))  # pixels per chunk: <= ~2 M sub-points at a time
    for i in range(0, len(rr), step):
        r, c, v = rr[i:i + step], cc[i:i + step], vals[i:i + step]
        sc = (c[:, None, None] + off[None, None, :]).repeat(k, axis=1).ravel()
        sr = (r[:, None, None] + off[None, :, None]).repeat(k, axis=2).ravel()
        px, py = wt * (sc, sr)
        X, Y = to_dst.transform(np.asarray(px), np.asarray(py))
        col = np.floor((np.asarray(X) - x0) / box_t.a).astype(np.int64)
        row = np.floor((np.asarray(Y) - y1) / box_t.e).astype(np.int64)
        ok = (col >= 0) & (col < w) & (row >= 0) & (row < h)
        grid += np.bincount(row[ok] * w + col[ok], weights=np.repeat(v, k * k)[ok], minlength=h * w)
    info = {"subpixels_per_side": k, "source_pop_read_window": float(a.sum()), "nodata_pixels": int(bad.sum())}  # incl. read-window cells off the raster
    return grid.reshape(h, w), info


def block_sums(a: np.ndarray, f: int) -> np.ndarray:
    """f x f block sums (shape divisible by f)."""
    h, w = a.shape
    return a.reshape(h // f, f, w // f, f).sum(axis=(1, 3))


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return np.nan
    rx, ry = pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy()
    if rx.std() == 0 or ry.std() == 0:
        return np.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def panel_stats(pop: np.ndarray, mask: np.ndarray, bui: np.ndarray, ref: np.ndarray, f: int) -> dict:
    """Numbers of one panel (pop on our cells; NaN outside the mask for the version, numbers anywhere for a
    product) against the version `ref` (NaN outside the mask)."""
    p = np.nan_to_num(pop, nan=0.0)
    tot = float(p.sum())
    full = block_sums(mask.astype(np.int64), f) == f * f
    pb = block_sums(np.where(mask, p, 0.0), f)[full]
    rb = block_sums(np.where(mask, np.nan_to_num(ref, nan=0.0), 0.0), f)[full]
    return {"total_pop_box": tot,
            "pop_share_masked": float(p[~mask].sum() / tot) if tot > 0 else np.nan,
            "pop_share_bui0": float(p[mask & (bui == 0)].sum() / tot) if tot > 0 else np.nan,
            "spearman_1km_vs_version": spearman(pb, rb), "n_blocks_1km": int(full.sum())}


# ---------------------------------------------------------------- inputs

def inputs(args, cfg, cm, years):
    """[(year, kind, name, path or None, note)]: the files the maps of these years read."""
    out = []
    v = cm["version"]
    for year in years:
        for kind, name, p in (("version", v, args.dasym_root / args.name / v / "predictions" / f"pop_{year}.tif"),
                              ("bui", "BUI", args.cutout_root / args.name / "layers" / "BUI" / f"{year}_BUI.tif")):
            out.append((year, kind, name, p if p.exists() else None, "" if p.exists() else f"missing {p}"))
        for prod in cm["years"][year]:
            spec = cfg["products"][prod]
            path, note = resolve(args.data_root, spec, year)
            out.append((year, "product", prod, path, note))
    return out


# ---------------------------------------------------------------- maps

MASK_GREY = "#b5b4ad"  # cells outside our mask on every panel


def density(pop: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """People per km2 of a panel: NaN outside our mask (drawn grey), 0 stays 0 inside it (drawn as the lowest)."""
    return np.where(mask, np.nan_to_num(pop, nan=0.0), np.nan) / CELL_KM2


def _plots():
    import matplotlib
    matplotlib.use("Agg")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dasymetric"))
    import plots  # noqa: E402  (palette of the dasymetric step)
    return plots


def colormap():
    """Blue ramp; under (0 people) white, bad (NaN = outside our mask) grey."""
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("blues", ["#f4f4f1"] + _plots().BLUES)
    cmap.set_under("#ffffff")
    cmap.set_bad(MASK_GREY)
    return cmap


def draw(path: Path, city_label: str, year: int, panels: list, mask: np.ndarray, box_km: float):
    """panels: [(title, pop on our cells)]. People per km2, shared log scale, masked cells grey."""
    from matplotlib.colors import LogNorm
    plots = _plots()
    plt = plots.plt

    dens = [density(p, mask) for _, p in panels]
    pos = np.concatenate([d[np.isfinite(d) & (d > 0)] for d in dens])
    vmax = float(np.percentile(pos, 99.9)) if pos.size else 10.0
    vmin = max(float(np.percentile(pos, 2)) if pos.size else 1.0, 1.0, vmax / 1e5)
    norm = LogNorm(vmin=vmin, vmax=max(vmax, vmin * 10), clip=False)
    cmap = colormap()
    n = len(panels)
    half = box_km / 2
    fig, axes = plt.subplots(1, n, figsize=(4.0 * n, 4.9), dpi=150, layout="constrained", squeeze=False)
    for ax, (title, _), d in zip(axes[0], panels, dens):
        im = ax.imshow(np.ma.masked_invalid(d), cmap=cmap, norm=norm, extent=[-half, half, -half, half],
                       interpolation="nearest")
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color(plots.AXIS)
        ax.set_title(title, fontsize=8.5, color=plots.INK)
    ax = axes[0][0]
    ax.plot([-half + 2, -half + 12], [-half + 2, -half + 2], color=plots.INK, lw=2)
    ax.text(-half + 7, -half + 3, "10 km", ha="center", va="bottom", fontsize=7, color=plots.INK)
    cb = fig.colorbar(im, ax=axes[0].tolist(), shrink=0.8, extend="both")
    cb.set_label("people per km2 (log); grey = outside our mask (water, no county)", fontsize=7.5, color=plots.INK2)
    cb.ax.tick_params(which="both", labelsize=7, colors=plots.INK2)
    fig.suptitle(f"{city_label}, {year}: people per km2 on our 250 m grid ({box_km:.0f} x {box_km:.0f} km, ESRI:102039)"
                 f"\n{NOTE}; GHS-POP / WorldPop use finer census input (blocks) in the US", fontsize=9.5,
                 color=plots.INK)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    log.info("  wrote %s", path)


def run_city(args, cfg, cm, key, city, year):
    v, vlab = cm["version"], cm.get("version_label", cm["version"])
    vpath = args.dasym_root / args.name / v / "predictions" / f"pop_{year}.tif"
    with rasterio.open(vpath) as src:
        grid_t, crs = src.transform, src.crs
    cx, cy = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(city["lon"], city["lat"])
    win = box_window(grid_t, cx, cy, cm["box_km"])
    vpop, mask, bt = read_box(vpath, win, grid_t)
    vpop = np.where(mask, vpop, np.nan)
    bui, bvalid, _ = read_box(args.cutout_root / args.name / "layers" / "BUI" / f"{year}_BUI.tif", win, grid_t)
    bui = np.where(bvalid, bui, -1.0)
    f = int(round(cm.get("block_km", 1) * 1000 / grid_t.a))
    if vpop.shape[0] % f or vpop.shape[1] % f:
        sys.exit(f"ERROR: box of {vpop.shape} cells is not a multiple of {f}-cell blocks")
    log.info("===== %s %d: centre (%.0f, %.0f) in %s, window %s, %d of %d cells in our mask", city["label"], year,
             cx, cy, crs.to_string(), win, int(mask.sum()), mask.size)
    rows, panels = [], []
    base = {"city": key, "city_label": city["label"], "year": year, "center_x": cx, "center_y": cy,
            "box_km": cm["box_km"], "note": NOTE}
    s = panel_stats(vpop, mask, bui, vpop, f)
    rows.append({**base, "product": v, "label": vlab, "input_unit_class": "county", **s})
    panels.append((f"{vlab} (county input)\ntotal {s['total_pop_box'] / 1e3:,.0f}k | on BUI = 0 "
                   f"{100 * s['pop_share_bui0']:.1f} %", vpop))
    for prod in cm["years"][year]:
        spec = cfg["products"][prod]
        path, note = resolve(args.data_root, spec, year)
        if path is None:
            sys.exit(f"ERROR: {prod} {year}: {note}")
        g, info = to_grid(path, bt, vpop.shape, crs, cm["subpixel_m"])
        s = panel_stats(g, mask, bui, vpop, f)
        rows.append({**base, "product": prod, "label": spec["label"], "input_unit_class": spec["input_unit_class"],
                     **s, **info})
        log.info("  %-9s k = %d: %.0f people in the box (%.1f %% on masked cells), %.0f in the read window, %d "
                 "nodata pixels | Spearman 1 km vs %s %.3f on %d blocks", prod, info["subpixels_per_side"],
                 s["total_pop_box"], 100 * s["pop_share_masked"], info["source_pop_read_window"],
                 info["nodata_pixels"], vlab, s["spearman_1km_vs_version"], s["n_blocks_1km"])
        panels.append((f"{spec['label']} ({spec['input_unit_class']} input)\ntotal {s['total_pop_box'] / 1e3:,.0f}k"
                       f" | rho 1 km vs {vlab} {s['spearman_1km_vs_version']:.2f}", g))
    log.info("  %s: %.0f people in the box, %.1f %% on BUI = 0 cells", vlab, rows[0]["total_pop_box"],
             100 * rows[0]["pop_share_bui0"])
    draw(args.out_dir / f"{key}_{year}.png", city["label"], year, panels, mask, cm["box_km"])
    return rows


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    cm = cfg["city_maps"]
    cm["years"] = {int(y): p for y, p in cm["years"].items()}
    cities = {k: c for k, c in cm["cities"].items() if not args.cities or k in args.cities}
    years = [y for y in cm["years"] if not args.years or y in args.years]
    if args.cities and len(cities) < len(args.cities):
        sys.exit(f"ERROR: cities not in the config: {sorted(set(args.cities) - set(cities))}")
    ins = inputs(args, cfg, cm, years)
    miss = [r for r in ins if r[3] is None]
    for y, kind, name, p, note in ins:
        log.info("  input %d %-8s %-22s %s", y, kind, name, p if p is not None else "MISSING: " + note)
    if miss:
        sys.exit(f"ERROR: {len(miss)} inputs missing")
    if args.check:
        log.info("CHECK OK: %d inputs for %d cities x %d years", len(ins), len(cities), len(years))
        return
    rows = []
    for year in years:
        for key, city in cities.items():
            rows += run_city(args, cfg, cm, key, city, year)
    out = pd.DataFrame(rows)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out_dir / "city_maps_summary.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 20):
        log.info("summary (%s):\n%s", NOTE, out[["city", "year", "product", "input_unit_class", "total_pop_box",
                                                 "pop_share_masked", "pop_share_bui0", "spearman_1km_vs_version",
                                                 "n_blocks_1km"]].round(3).to_string(index=False))
    log.info("wrote %s", args.out_dir / "city_maps_summary.csv")
    log.info("DONE")


if __name__ == "__main__":
    main()
