"""Figures of the dasymetric pipeline (docs/dasymetric_v2.md): correlation heatmap, SHAP plots
(train.py) and quick-look population maps (predict.py). PNG only, no web tiles."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, LogNorm  # noqa: E402

from common import log  # noqa: E402

# Dataviz reference palette: sequential blue ramp (steps 100-700), categorical slots in fixed order,
# diverging blue <-> gray <-> red, chart ink.
BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#1c5cab", "#104281", "#0d366b"]
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
DIVERGING = ["#2a78d6", "#f0efec", "#e34948"]
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
STATE_FILL, STATE_EDGE = "#f4f4f1", "#b5b4ad"


def _style(ax):
    ax.tick_params(labelsize=8, colors=INK2)
    for s in ax.spines.values():
        s.set_color(AXIS)


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    log.info("  plot %s", path)


# ---------------------------------------------------------------- training

def correlation_heatmap(rho, path: Path):
    n = len(rho)
    fig, ax = plt.subplots(figsize=(1.0 * n + 2, 0.9 * n + 1.2), dpi=150)
    im = ax.imshow(rho.to_numpy(), cmap=LinearSegmentedColormap.from_list("div", DIVERGING), vmin=-1, vmax=1)
    ax.set_xticks(range(n), rho.columns, rotation=45, ha="right")
    ax.set_yticks(range(n), rho.index)
    for i in range(n):
        for j in range(n):
            ax.text(j, i, f"{rho.iat[i, j]:.2f}", ha="center", va="center", fontsize=8, color=INK)
    ax.set_title("Spearman correlation of county features", fontsize=11, color=INK)
    _style(ax)
    cb = fig.colorbar(im, ax=ax, shrink=0.8)
    cb.set_label("Spearman rho", fontsize=9, color=INK2)
    cb.ax.tick_params(labelsize=8, colors=INK2)
    _save(fig, path)


def shap_summary(sv: np.ndarray, X, path: Path):
    import shap
    shap.summary_plot(sv, X, show=False, plot_size=(8, 0.5 * X.shape[1] + 1.5))
    fig = plt.gcf()
    fig.axes[0].set_title("SHAP values per county-year (training rows)", fontsize=11, color=INK)
    fig.axes[0].set_xlabel("SHAP value (effect on log people per km²)", fontsize=9, color=INK2)
    _save(fig, path)


def shap_by_year(by_year, path: Path, order=None):
    """order: all features of the config, so a feature keeps its colour in every era's chart."""
    order = list(order or by_year.columns)
    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=150)
    for f in by_year.columns:  # fixed slot per feature = its position in the config
        ax.plot(by_year.index, by_year[f], color=SERIES[order.index(f) % len(SERIES)], lw=2, marker="o", ms=4,
                label=f)
    if len(by_year) <= 13:  # tick the census years themselves (no 2002.5 in a 3-year era)
        ax.set_xticks(by_year.index, [str(int(y)) for y in by_year.index])
    ax.set_title("Mean |SHAP| per feature by census year", fontsize=11, color=INK)
    ax.set_xlabel("census year", fontsize=9, color=INK2)
    ax.set_ylabel("mean |SHAP| (log people per km²)", fontsize=9, color=INK2)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_ylim(bottom=0)
    _style(ax)
    ax.legend(fontsize=8, frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1), labelcolor=INK2)
    _save(fig, path)


# ---------------------------------------------------------------- maps

def read_states(gpkg: Path, bounds, crs):
    """State polygons (counties dissolved by `state`) intersecting `bounds` (minx, miny, maxx, maxy)."""
    import geopandas as gpd
    gdf = gpd.read_file(gpkg, columns=["state"])
    if gdf.crs != crs:
        gdf = gdf.to_crs(crs)
    gdf = gdf.cx[bounds[0]:bounds[2], bounds[1]:bounds[3]]
    return gdf.dissolve(by="state")


def map_bounds(mask: np.ndarray, grid: dict, pad: float = 0.06):
    """Projected bounds (m) of the masked cells, padded so neighbouring states show."""
    rows, cols = np.where(mask)
    t = grid["transform"]
    x0, x1 = t.c + cols.min() * t.a, t.c + (cols.max() + 1) * t.a
    y1, y0 = t.f + rows.min() * t.e, t.f + (rows.max() + 1) * t.e
    p = pad * max(x1 - x0, y1 - y0)
    return x0 - p, y0 - p, x1 + p, y1 + p


def _scale_bar(ax, bounds):
    x0, y0, x1, y1 = bounds
    target = (x1 - x0) / 5 / 1e3
    km = max(k for k in (1, 2, 5, 10, 20, 50, 100, 200, 500) if k <= max(target, 1))
    bx, by = x0 + 0.04 * (x1 - x0), y0 + 0.05 * (y1 - y0)
    ax.plot([bx, bx + km * 1e3], [by, by], color=INK, lw=2, solid_capstyle="butt")
    ax.text(bx + km * 5e2, by + 0.012 * (y1 - y0), f"{km} km", ha="center", va="bottom", fontsize=8, color=INK)


def pop_maps(path: Path, panels, grid: dict, states, bounds, title: str):
    """One or more population maps on a shared log colour scale. panels: [(label, arr, mask)].
    The value is people per 250 m cell; log scale is for display only."""
    vals = np.concatenate([a[m] for _, a, m in panels])
    pos = vals[vals > 0]
    vmin = max(float(np.percentile(pos, 1)) if pos.size else 1e-3, 1e-3)
    norm = LogNorm(vmin=vmin, vmax=max(float(vals.max()), vmin * 10), clip=True)
    cmap = LinearSegmentedColormap.from_list("blues", BLUES)
    cmap.set_bad((0, 0, 0, 0))
    t = grid["transform"]
    h, w = grid["shape"]
    extent = [t.c, t.c + w * t.a, t.f + h * t.e, t.f]
    x0, y0, x1, y1 = bounds
    aspect = (y1 - y0) / (x1 - x0)
    fig, axes = plt.subplots(1, len(panels), figsize=(7 * len(panels) + 1.5, 7 * aspect + 0.6), dpi=150,
                             squeeze=False, layout="constrained")
    for ax, (label, arr, mask) in zip(axes[0], panels):
        if states is not None and len(states):
            states.plot(ax=ax, facecolor=STATE_FILL, edgecolor=STATE_EDGE, lw=0.6, zorder=1)
        im = ax.imshow(np.ma.masked_where(~mask, arr), cmap=cmap, norm=norm, extent=extent,
                       interpolation="nearest", zorder=2)
        if states is not None and len(states):
            states.boundary.plot(ax=ax, color=STATE_EDGE, lw=0.5, zorder=3)
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_axis_off()
        ax.set_title(f"{title}, {label}\ntotal {arr[mask].sum():,.0f} people", fontsize=10, color=INK)
        _scale_bar(ax, bounds)
    cb = fig.colorbar(im, ax=axes[0].tolist(), shrink=0.7)
    cb.set_label("people per 250 m cell (log scale)", fontsize=9, color=INK2)
    cb.ax.tick_params(which="both", labelsize=8, colors=INK2)
    _save(fig, path)
