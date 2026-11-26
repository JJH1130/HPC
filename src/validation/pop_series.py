"""National population maps of one version, 1900-2020 every 10 years (figures for talks / the paper).

Two steps, so the map style can be tuned on the laptop without the cluster:
  export  (cluster) reads <dasym-root>/conus/<version>/predictions/pop_<YEAR>.tif (250 m, NoData = -9999), sums 4 x 4
          cells to 1 km (a block is NoData only when all 16 cells are), checks the 1 km total = the 250 m total, and
          writes results/validation/conus/pop_series/pop1km_<YEAR>.npz: `v` = float16 log10(people per 1 km cell),
          -9 for 0 people, NaN outside; transform / crs. Also states.geojson (2010 counties dissolved by state,
          simplified 1 km) once.
  render  (laptop or cluster) draws pop_<YEAR>.png from those files, one fixed colour scale for every year.

Usage:
  python src/validation/pop_series.py export --version Dasy_CONUS_RF_v3_all_nby --years 1900 \
      --dasym-root $HISDAC_SCRATCH/dasymetric --counties-gpkg $DATA_ROOT/processed/census/counties_2010.gpkg
  python src/validation/pop_series.py render --years 1900
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "validation" / "conus" / "pop_series"
NODATA = -9999.0
ZERO = -9.0


def block_sum(a: np.ndarray, valid: np.ndarray, k: int = 4):
    """Sum k x k cells (NoData cells count 0); a block is valid when any of its cells is. Edge blocks are padded."""
    h, w = a.shape
    H, W = -(-h // k), -(-w // k)
    pad = np.zeros((H * k, W * k))
    pv = np.zeros((H * k, W * k), bool)
    pad[:h, :w] = np.where(valid, a, 0.0)
    pv[:h, :w] = valid
    return pad.reshape(H, k, W, k).sum(axis=(1, 3)), pv.reshape(H, k, W, k).any(axis=(1, 3))


def export(args):
    import rasterio
    OUT.mkdir(parents=True, exist_ok=True)
    for year in args.years:
        src = Path(args.dasym_root) / "conus" / args.version / "predictions" / f"pop_{year}.tif"
        with rasterio.open(src) as r:
            a = r.read(1).astype(np.float64)
            t, crs = r.transform, r.crs.to_wkt()
        valid = a != NODATA
        s, any_valid = block_sum(a, valid)
        H, W = s.shape
        tot250, tot1k = a[valid].sum(), s[any_valid].sum()
        if abs(tot1k - tot250) > 1e-6 * max(tot250, 1):
            raise SystemExit(f"{year}: 1 km total {tot1k:,.1f} != 250 m total {tot250:,.1f}")
        v = np.full((H, W), np.nan, np.float32)
        pos = any_valid & (s > 0)
        v[pos] = np.log10(s[pos])
        v[any_valid & (s <= 0)] = ZERO
        t1 = [t.a * 4, t.b, t.c, t.d, t.e * 4, t.f]
        np.savez_compressed(OUT / f"pop1km_{year}.npz", v=v.astype(np.float16), transform=np.array(t1), crs=crs,
                            total=tot250)
        print(f"{year}: {H} x {W} blocks, total {tot250:,.0f} people, wrote pop1km_{year}.npz")
    states = OUT / "states.geojson"
    if args.counties_gpkg and not states.exists():
        import geopandas as gpd
        g = gpd.read_file(args.counties_gpkg)
        col = next(c for c in ("state", "STATE", "STATEFP", "statefp") if c in g.columns)
        g = g.to_crs(crs).dissolve(by=col)[["geometry"]]
        g["geometry"] = g.geometry.simplify(1000)
        g.to_file(states, driver="GeoJSON")
        print(f"wrote {states} ({len(g)} states)")


def render(args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    gpd = None
    try:
        import geopandas as gpd
    except ImportError:
        pass
    states = None
    if gpd is not None and (OUT / "states.geojson").exists():
        states = gpd.read_file(OUT / "states.geojson")
    # one sequential ramp, light (few people) -> dark (many); fixed range for every year
    cmap = LinearSegmentedColormap.from_list(
        "pop", ["#f3efe6", "#f2d9a6", "#e8a96a", "#d36d45", "#a83a3c", "#6b1f3a", "#2b0f2a"])
    cmap.set_bad((0, 0, 0, 0))
    vmin, vmax = -1.0, 4.0           # 0.1 to 10,000 people per km2
    for year in args.years:
        f = np.load(OUT / f"pop1km_{year}.npz", allow_pickle=False)
        v = f["v"].astype(np.float32)
        t = f["transform"]
        h, w = v.shape
        extent = [t[2], t[2] + w * t[0], t[5] + h * t[4], t[5]]
        land = np.isfinite(v)
        rows, cols = np.where(land)
        x0, x1 = t[2] + cols.min() * t[0], t[2] + (cols.max() + 1) * t[0]
        y1, y0 = t[5] + rows.min() * t[4], t[5] + (rows.max() + 1) * t[4]
        px, py = 0.02 * (x1 - x0), 0.03 * (y1 - y0)
        fig, ax = plt.subplots(figsize=(12, 12 * (y1 - y0 + 2 * py) / (x1 - x0 + 2 * px) + 0.9), dpi=200)
        fig.patch.set_facecolor("white")
        zero = np.where(v <= ZERO + 0.5, 1.0, np.nan)
        ax.imshow(zero, cmap=LinearSegmentedColormap.from_list("z", ["#e9e7e1", "#e9e7e1"]), extent=extent,
                  interpolation="nearest", zorder=1)
        vv = np.where(v > ZERO + 0.5, v, np.nan)
        im = ax.imshow(vv, cmap=cmap, norm=Normalize(vmin, vmax, clip=True), extent=extent,
                       interpolation="nearest", zorder=2)
        if states is not None:
            states.boundary.plot(ax=ax, color="white", lw=0.35, alpha=0.9, zorder=3)
        ax.set_xlim(x0 - px, x1 + px)
        ax.set_ylim(y0 - py, y1 + py)
        ax.set_axis_off()
        ax.text(0.015, 0.06, str(year), transform=ax.transAxes, fontsize=34, fontweight="bold", color="#2b2a27")
        ax.text(0.015, 0.025, f"{float(f['total']) / 1e6:,.1f} million people", transform=ax.transAxes,
                fontsize=12, color="#52514e")
        cax = fig.add_axes([0.70, 0.075, 0.25, 0.018])
        cb = fig.colorbar(im, cax=cax, orientation="horizontal")
        ticks = [-1, 0, 1, 2, 3, 4]
        cb.set_ticks(ticks, labels=["0.1", "1", "10", "100", "1k", "10k+"])
        cb.ax.tick_params(labelsize=9, colors="#52514e", length=0)
        cb.outline.set_visible(False)
        cb.set_label("people per km² (1 km cells)", fontsize=9, color="#52514e")
        out = OUT / f"pop_{year}.png"
        fig.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"wrote {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--version", default="Dasy_CONUS_RF_v3_all_nby")
    e.add_argument("--years", nargs="+", type=int, required=True)
    e.add_argument("--dasym-root", required=True)
    e.add_argument("--counties-gpkg")
    r = sub.add_parser("render")
    r.add_argument("--years", nargs="+", type=int, required=True)
    a = ap.parse_args()
    export(a) if a.cmd == "export" else render(a)


if __name__ == "__main__":
    main()
