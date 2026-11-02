"""Meeting city maps (2010, 1980): v5.6 next to GHS-POP / WorldPop with 1 km block scatter plots (docs/conus_plan.md
"Meeting city maps"; requests docs/handoff/city_maps_meeting_request.md and city_maps_meeting_fix{,2,3}_request.md).
Message: GHS-POP / WorldPop use block-level census input in the US, so a tract check is not a fair contest; what is
compared here is the spatial pattern (rank agreement, not accuracy). No Fang & Jawitz panel.

Reuses src/validation/external_city_maps.py unchanged: the same box (`city_maps` block of
configs/external_grids.yaml: centre, box_km), the same move of a product to our 250 m cells (population kept), the
same mask (cells with a v5.6 prediction; grey outside) and the same 1 km blocks (4 x 4 cells, only blocks fully inside
the mask) as its Spearman. The `city_meeting` block of the same config picks the years (each with its products: 2010
GHS-POP + WorldPop, 1980 GHS-POP only), cities, short labels and the gap rule.

Per city and year, one figure, all of the same size and layout (FIGSIZE; a product without a grid that year leaves an
empty, labelled slot):
  top row     maps v5.6 | GHS-POP | WorldPop, people per km2, one log scale, masked cells grey, 0 people white, a
              10 km scale bar on a white box on every map; same size and spacing (maps and scatter plots are two
              sub-figures)
  bottom row  1 km block density, x = v5.6, y = product, one fixed square range in every figure (0.01 .. 30,000 per
              km2 on both axes, ticks 0.01 / 0.1 / 1 / 10 / 100 / 1,000 / 10,000); blocks with 0 people on a band
              "0 (n)" left / below (same width on x and y, vertical label on x, apart from the 0.01 tick; no band
              without them); 0 < v < 0.01 on the axis edge as triangles, "< 0.01 (n)" in the legend (> 30,000 the
              same, if any); 1:1 line, Spearman rho + number of blocks in the title; a text panel with the totals
Gap blocks, every city and year: 1 km blocks where v5.6 is far below GHS-POP (fixed rule: v5.6 / GHS < ratio_max and GHS
>= min_density people per km2) are outlined on the maps and coloured in the scatter plots; their HISDAC state goes to
gap_blocks.csv (city, year, group), next to the other dense blocks (GHS >= min_density, not gap): blocks, people (GHS-POP,
WorldPop, v5.6), share of their cells with BUI > 0 (the cutout's BUI of the year) and with NobuiltYear > 0 (records
without a built year, one present-day layer for every year; the cutout's NobuiltYear layer if it has one, else HISDAC's
FBUY/NobuiltYear.tif read onto the box; if neither exists those columns are NA and the log says so). The text panel
puts gap and other dense blocks side by side (BUI > 0; BUI = 0 but NobuiltYear > 0 = undated records only; no
record), from the same rows; "gap blocks: 0" when there are none.

The display may change, the numbers may not: before writing, rho / blocks / box totals are compared with the previous
meeting_summary.csv in the out dir and the `--compare-with` tables (city maps summary), the gap table with the
previous gap_blocks.csv and the older chicago_gap_blocks.csv (Chicago 2010 only; removed once matched); a difference
stops the run with nothing written.

Outputs (<out-dir>): {city}_{year}.png, meeting_summary.csv (city x panel: rho, blocks, people in the box),
gap_blocks.csv. `--check` only lists the inputs (exit 1 if one is missing; NobuiltYear is optional).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window

sys.path.insert(0, str(Path(__file__).resolve().parent))
import external_city_maps as ecm  # noqa: E402
from external_compare import load_config, resolve  # noqa: E402

log = logging.getLogger("external_city_meeting")
GAP_CSV = "gap_blocks.csv"                 # every city and year (city, year, group)
LEGACY_GAP_CSV = "chicago_gap_blocks.csv"  # Chicago 2010 only (runs of 2026-11-03); compared, then removed
HEADER = ("Spearman of 1 km block densities (rank agreement, not accuracy); GHS-POP / WorldPop use block-level census "
          "input in the US")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, default=Path("configs/external_grids.yaml"))
    p.add_argument("--data-root", type=Path, required=True, help="$DATA_ROOT/raw/external")
    p.add_argument("--dasym-root", type=Path, required=True,
                   help="<dasym-root>/<name>/<version>/predictions/pop_{YEAR}.tif")
    p.add_argument("--cutout-root", type=Path, required=True,
                   help="<cutout-root>/<name>/layers/BUI/{YEAR}_BUI.tif (+ layers/NobuiltYear/*.tif if cut)")
    p.add_argument("--hisdac-dir", type=Path, default=None, help="HISDAC-US V2 folder: FBUY/NobuiltYear.tif")
    p.add_argument("--name", default="conus")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--compare-with", type=Path, nargs="*",
                   help="earlier summary tables (city, year, product, spearman_1km_vs_version, n_blocks_1km, "
                        "total_pop_box) whose shared rows must come out the same")
    p.add_argument("--check", action="store_true", help="list the inputs only; exit 1 if one is missing")
    return p.parse_args(argv)


# ---------------------------------------------------------------- numbers

def blocks(pop: np.ndarray, ref: np.ndarray, mask: np.ndarray, f: int):
    """(panel block sums, version block sums, full-block flags): the blocks of ecm.panel_stats' Spearman."""
    full = ecm.block_sums(mask.astype(np.int64), f) == f * f
    pb = ecm.block_sums(np.where(mask, np.nan_to_num(pop, nan=0.0), 0.0), f)
    rb = ecm.block_sums(np.where(mask, np.nan_to_num(ref, nan=0.0), 0.0), f)
    return pb, rb, full


def gap_blocks(vb: np.ndarray, gb: np.ndarray, full: np.ndarray, block_km2: float, ratio_max: float,
               min_density: float) -> np.ndarray:
    """Blocks (inside the mask) with GHS >= min_density people per km2 and v5.6 / GHS < ratio_max."""
    gd, vd = gb / block_km2, vb / block_km2
    return full & (gd >= min_density) & (vd < ratio_max * gd)


def cell_share(flag_blocks: np.ndarray, cells: np.ndarray, f: int) -> float:
    """Share of the cells of the flagged blocks where `cells` is True."""
    n = int(flag_blocks.sum()) * f * f
    if n == 0:
        return np.nan
    return float(ecm.block_sums(cells.astype(np.int64), f)[flag_blocks].sum() / n)


def nobuilt_source(args):
    """(path, how) of NobuiltYear: the cutout layer if cut, else HISDAC's FBUY/NobuiltYear.tif, else (None, why)."""
    d = args.cutout_root / args.name / "layers" / "NobuiltYear"
    found = sorted(d.glob("*.tif")) if d.is_dir() else []
    if len(found) == 1:
        return found[0], "cutout"
    if len(found) > 1:
        sys.exit(f"ERROR: several NobuiltYear files in {d}: {[p.name for p in found]}")
    if args.hisdac_dir is not None:
        p = args.hisdac_dir / "FBUY" / "NobuiltYear.tif"
        if p.exists():
            return p, "hisdac"
        return None, f"no NobuiltYear layer in {d} and {p} not found"
    return None, f"no NobuiltYear layer in {d} and no --hisdac-dir"


def read_on_box(path: Path, box_t, shape, crs) -> np.ndarray:
    """A raster on our box cells (nodata / non-finite = 0): a window when it shares our cells, else WarpedVRT
    nearest."""
    h, w = shape
    with rasterio.open(path) as src:
        t = src.transform
        co, ro = (box_t.c - t.c) / t.a, (box_t.f - t.f) / t.e
        same = (src.crs == crs and abs(t.a - box_t.a) < 1e-9 and abs(t.e - box_t.e) < 1e-9
                and abs(co - round(co)) < 1e-6 and abs(ro - round(ro)) < 1e-6)
        if same:
            a = src.read(1, window=Window(round(co), round(ro), w, h), boundless=True,
                         fill_value=src.nodata if src.nodata is not None else 0).astype("float64")
        else:
            log.warning("  %s is not on our cells: read through WarpedVRT (nearest)", path)
            with WarpedVRT(src, crs=crs, transform=box_t, width=w, height=h, resampling=Resampling.nearest) as v:
                a = v.read(1).astype("float64")
        bad = ~np.isfinite(a)
        if src.nodata is not None:
            bad |= a == src.nodata
    a[bad] = 0.0
    return a


# ---------------------------------------------------------------- figure

def tick_label(t: float) -> str:
    """Log-axis tick: 0.01 / 0.1 / 1 / 10 / 1,000 (no integer format below 1)."""
    return f"{t:,.0f}" if t >= 1 else f"{t:g}"


SC_LO, SC_HI = 0.01, 30_000.0          # scatter range of every figure, people per km2 (both axes)
SC_TICKS = [0.01, 0.1, 1.0, 10.0, 100.0, 1_000.0, 10_000.0]
ZERO_BAND = (10 ** -3.55, 10 ** -3.2, 10 ** -2.85)   # band low, centre, high for 0-people blocks (same on x and y)
SC_LOW_LIMIT = 10 ** -3.75             # axis low limit (below the band)


def clamp(v: np.ndarray):
    """(plotted value, edge flag): 0 -> the zero band centre; 0 < v < SC_LO -> SC_LO and v > SC_HI -> SC_HI (axis
    edges, flagged); the rest unchanged."""
    below, above = (v > 0) & (v < SC_LO), v > SC_HI
    out = np.where(v == 0, ZERO_BAND[1], np.clip(v, SC_LO, SC_HI))
    return out, below, above


def _log_axis(ax, which: str, n0: int):
    """Fixed log axis SC_LOW_LIMIT .. SC_HI, ticks SC_TICKS; with n0 > 0 blocks of 0 people the zero band labelled
    "0 (n0)" (vertical on the x axis), without them no band."""
    from matplotlib.ticker import NullLocator
    (ax.set_xscale if which == "x" else ax.set_yscale)("log")
    (ax.set_xlim if which == "x" else ax.set_ylim)(SC_LOW_LIMIT, SC_HI)
    axis = ax.xaxis if which == "x" else ax.yaxis
    ticks, labels = list(SC_TICKS), [tick_label(t) for t in SC_TICKS]
    if n0:
        (ax.axvspan if which == "x" else ax.axhspan)(ZERO_BAND[0], ZERO_BAND[2], color=ecm._plots().GRID, lw=0,
                                                     zorder=0)
        ticks, labels = [ZERO_BAND[1]] + ticks, [f"0 ({n0})"] + labels
    axis.set_ticks(ticks)
    axis.set_ticklabels(labels)
    axis.set_minor_locator(NullLocator())
    if n0 and which == "x":
        lab = axis.get_ticklabels()[0]
        lab.set_rotation(90)
        lab.set_verticalalignment("top")


def scatter(ax, x: np.ndarray, y: np.ndarray, gap: np.ndarray | None, title: str, xlab: str, ylab: str):
    """Block densities on the fixed square range (0.01 .. 30,000 on both axes, same ticks in every figure): zeros on
    a band, 0 < v < 0.01 (and v > 30,000) on the axis edge as triangles, counted in the legend; 1:1 line; gap blocks
    orange."""
    plots = ecm._plots()
    xs, xb, xa = clamp(x)
    ys, yb, ya = clamp(y)
    edge = xb | yb | xa | ya
    g = np.zeros(len(x), bool) if gap is None else gap
    for sel, col, a, size, lab in ((~g, plots.SERIES[0], 0.45, 8, "1 km block"),
                                   (g, plots.SERIES[1], 0.85, 10, f"gap block ({int(g.sum())})")):
        if sel is g and not g.any():
            continue
        ax.scatter(xs[sel & ~edge], ys[sel & ~edge], s=size, color=col, alpha=a, lw=0, label=lab)
        ax.scatter(xs[sel & edge], ys[sel & edge], s=size + 8, color=col, alpha=a, lw=0, marker="^")
    for n_edge, sign, v in ((int((xb | yb).sum()), "<", SC_LO), (int((xa | ya).sum()), ">", SC_HI)):
        if n_edge:  # legend entry only (one grey triangle)
            ax.plot([], [], ls="none", marker="^", ms=5, color=plots.INK2, label=f"{sign} {tick_label(v)} ({n_edge})")
    _log_axis(ax, "x", int((x == 0).sum()))
    _log_axis(ax, "y", int((y == 0).sum()))
    ax.plot([SC_LO, SC_HI], [SC_LO, SC_HI], color=plots.INK2, lw=1, ls="--", label="1:1")
    ax.set_aspect("equal")
    ax.set_xlabel(xlab, fontsize=8, color=plots.INK2)
    ax.set_ylabel(ylab, fontsize=8, color=plots.INK2)
    ax.set_title(title, fontsize=8.5, color=plots.INK)
    ax.tick_params(labelsize=7, colors=plots.INK2)
    for sp in ax.spines.values():
        sp.set_color(plots.AXIS)
    ax.legend(fontsize=7, frameon=False, loc="upper left")


def scale_bar(ax, half: float):
    """Bar in the lower-left corner on a white, half-transparent box (readable on dark cells): 10 km in boxes of
    30 km and more, else about a quarter of the box. The map limits stay the box."""
    from matplotlib.patches import Rectangle
    plots = ecm._plots()
    km = 10.0 if 2 * half >= 30 else max(1.0, round(half / 2))
    u = 2 * half / 40                                    # padding unit: 1 km in the 40 km box
    x0, y0 = -half + u, -half + u
    ax.add_patch(Rectangle((x0, y0), km + 2 * u, 4.2 * u, facecolor="white", alpha=0.8, edgecolor="none", zorder=3))
    ax.plot([x0 + u, x0 + u + km], [y0 + 1.1 * u, y0 + 1.1 * u], color=plots.INK, lw=2, zorder=4,
            solid_capstyle="butt")
    ax.text(x0 + u + km / 2, y0 + 1.7 * u, f"{km:.0f} km", ha="center", va="bottom", fontsize=7, color=plots.INK,
            zorder=4)
    ax.set_xlim(-half, half)
    ax.set_ylim(-half, half)


FIGSIZE = (14.0, 10.4)  # every meeting figure: same size, 3 map slots + 2 scatter slots + the text panel
MARGIN_IN = 0.3         # white margin added on every side when saving (same for every figure)
SLOTS = 3


def placeholder(ax, text: str):
    """An empty slot (a product without a grid that year), so every figure keeps the same layout."""
    plots = ecm._plots()
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_color(plots.GRID)
    ax.set_aspect("equal")
    ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=8.5, color=plots.MUTED, transform=ax.transAxes)


def draw(path: Path, title: str, maps: list, mask: np.ndarray, box_km: float, block_km: float,
         gap: np.ndarray | None, full: np.ndarray, scatters: list, text: str, missing: tuple = ()):
    """maps: [(title, pop on our cells)]; scatters: [(title, x density, y density, ylabel)] over the `full` blocks
    (row-major); gap: block flags (or None); missing: texts of the empty map / scatter slots. Maps and scatter plots
    in two sub-figures (the maps keep one size and spacing), always SLOTS map slots and SLOTS - 1 scatter slots in a
    figure of FIGSIZE, saved without cropping (the constrained layout keeps every label inside)."""
    from matplotlib.colors import LogNorm
    from matplotlib.patches import Rectangle
    plots = ecm._plots()
    plt = plots.plt

    dens = [ecm.density(p, mask) for _, p in maps]
    pos = np.concatenate([d[np.isfinite(d) & (d > 0)] for d in dens])
    vmax = float(np.percentile(pos, 99.9)) if pos.size else 10.0
    vmin = max(float(np.percentile(pos, 2)) if pos.size else 1.0, 1.0, vmax / 1e5)
    norm = LogNorm(vmin=vmin, vmax=max(vmax, vmin * 10), clip=False)
    cmap = ecm.colormap()
    half = box_km / 2
    if len(maps) + len(missing) != SLOTS or len(scatters) + len(missing) != SLOTS - 1:
        sys.exit(f"ERROR: {path.name}: {len(maps)} maps, {len(scatters)} scatter plots, {len(missing)} empty slots")
    fig = plt.figure(figsize=FIGSIZE, dpi=150, layout="constrained")
    fig.get_layout_engine().set(w_pad=0.08, h_pad=0.08)
    sub_top, sub_bot = fig.subfigures(2, 1, height_ratios=[1.0, 1.08])
    top = sub_top.subplots(1, SLOTS, squeeze=False)[0]
    for ax, t in zip(top[len(maps):], missing):
        placeholder(ax, t)
    for ax, (t, _), d in zip(top, maps, dens):
        im = ax.imshow(ecm.for_imshow(d, norm.vmin), cmap=cmap, norm=norm, extent=[-half, half, -half, half],
                       interpolation="nearest")
        if gap is not None:
            for bi, bj in zip(*np.nonzero(gap)):
                ax.add_patch(Rectangle((-half + bj * block_km, half - (bi + 1) * block_km), block_km, block_km,
                                       fill=False, edgecolor=plots.SERIES[1], lw=0.6))
        scale_bar(ax, half)
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color(plots.AXIS)
        ax.set_title(t, fontsize=8.5, color=plots.INK)
    cb = sub_top.colorbar(im, ax=list(top), shrink=0.8, extend="both")  # all slots: same map size in every figure
    cb.set_label("people per km2 (log)", fontsize=7.5, color=plots.INK2)
    cb.ax.tick_params(which="both", labelsize=7, colors=plots.INK2)
    bot = sub_bot.subplots(1, SLOTS, squeeze=False)[0]
    for ax, (t, x, y, ylab) in zip(bot, scatters):
        scatter(ax, x, y, gap[full] if gap is not None else None, t, "v5.6, people per km2 (1 km block)", ylab)
    for ax, t in zip(bot[len(scatters):-1], missing):
        placeholder(ax, t)
    tx = bot[-1]
    tx.axis("off")
    tx.text(0.0, 1.0, text, va="top", ha="left", fontsize=8, color=plots.INK, family="monospace",
            transform=tx.transAxes)
    fig.suptitle(f"{title}\n{HEADER}", fontsize=9.5, color=plots.INK)
    path.parent.mkdir(parents=True, exist_ok=True)
    from matplotlib.transforms import Bbox
    w, h = FIGSIZE  # fixed box = the figure + MARGIN_IN on every side: same size for every figure, nothing cut
    fig.savefig(path, facecolor="white", bbox_inches=Bbox([[-MARGIN_IN, -MARGIN_IN], [w + MARGIN_IN, h + MARGIN_IN]]))
    plt.close(fig)
    log.info("  wrote %s", path)


def pct(v: float) -> str:
    return "NA" if v is None or not np.isfinite(v) else f"{100 * v:.0f} %"


def gap_text(gap_rows: list, glab: str, vlab: str, gc: dict) -> list:
    """Text-panel lines of one city and year: gap vs the other dense blocks, side by side (values of the gap
    table); "gap blocks: 0" when there are none."""
    g, d = (next(r for r in gap_rows if r["group"] == k) for k in ("gap", "dense_not_gap"))
    head = ["", f"gap blocks (orange): {vlab} / {glab} < {gc['ratio_max']}",
            f"  and {glab} >= {gc['min_density']:,.0f} per km2"]
    if g["n_blocks"] == 0:
        return head + ["gap blocks: 0", f"  (other dense blocks: {d['n_blocks']})"]
    return head + [
            f"gap vs other dense blocks ({glab} >= {gc['min_density']:,.0f}):",
            f"  blocks: {g['n_blocks']} vs {d['n_blocks']}",
            f"  people {glab}: {g['pop_' + gc['product']] / 1e3:,.0f}k vs {d['pop_' + gc['product']] / 1e3:,.0f}k",
            f"  people {vlab}: {g['pop_v56'] / 1e3:,.0f}k vs {d['pop_v56'] / 1e3:,.0f}k",
            f"  BUI > 0: {pct(g['share_cells_bui_gt0'])} vs {pct(d['share_cells_bui_gt0'])}",
            "  BUI = 0 but NobuiltYear > 0",
            f"   (undated records only): {pct(g['share_cells_nobuilt_gt0_bui0'])} vs "
            f"{pct(d['share_cells_nobuilt_gt0_bui0'])}",
            f"  no record: {pct(g['share_cells_no_record'])} vs {pct(d['share_cells_no_record'])}",
            "  (shares of the blocks' 250 m cells)"]


# ---------------------------------------------------------------- run

def inputs(args, cfg, cm, mt):
    """[(year, kind, name, path or None, note)]: the files the meeting maps read."""
    v = cm["version"]
    out = []
    for year, prods in mt["years"].items():
        for kind, name, p in (("version", v, args.dasym_root / args.name / v / "predictions" / f"pop_{year}.tif"),
                              ("bui", "BUI", args.cutout_root / args.name / "layers" / "BUI" / f"{year}_BUI.tif")):
            out.append((year, kind, name, p if p.exists() else None, "" if p.exists() else f"missing {p}"))
        for prod in prods:
            path, note = resolve(args.data_root, cfg["products"][prod], year)
            out.append((year, "product", prod, path, note))
    return out


def run_city(args, cfg, cm, mt, key, year, nb_path, nb_how):
    """(summary rows, gap rows, draw arguments) of one city and year; drawn by main after the check."""
    city = cm["cities"][key]
    v, vlab = cm["version"], cm.get("version_label", cm["version"])
    labels = mt.get("labels", {})
    vpath = args.dasym_root / args.name / v / "predictions" / f"pop_{year}.tif"
    with rasterio.open(vpath) as src:
        grid_t, crs = src.transform, src.crs
    cx, cy = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(city["lon"], city["lat"])
    win = ecm.box_window(grid_t, cx, cy, cm["box_km"])
    vpop, mask, bt = ecm.read_box(vpath, win, grid_t)
    vpop = np.where(mask, vpop, np.nan)
    bui, bvalid, _ = ecm.read_box(args.cutout_root / args.name / "layers" / "BUI" / f"{year}_BUI.tif", win, grid_t)
    bui = np.where(bvalid, bui, -1.0)
    f = int(round(cm.get("block_km", 1) * 1000 / grid_t.a))
    if vpop.shape[0] % f or vpop.shape[1] % f:
        sys.exit(f"ERROR: box of {vpop.shape} cells is not a multiple of {f}-cell blocks")
    bkm2 = f * f * ecm.CELL_KM2
    block_km = f * grid_t.a / 1000
    log.info("===== %s %d: centre (%.0f, %.0f), window %s, %d of %d cells in our mask", city["label"], year, cx, cy,
             win, int(mask.sum()), mask.size)
    base = {"city": key, "city_label": city["label"], "year": year, "box_km": cm["box_km"], "note": HEADER}
    s = ecm.panel_stats(vpop, mask, bui, vpop, f)
    rows = [{**base, "product": v, "label": vlab, "input_unit_class": "county", "spearman_1km_vs_version": 1.0,
             "n_blocks_1km": s["n_blocks_1km"], "total_pop_box": s["total_pop_box"]}]
    maps = [(f"{vlab} (county input)\ntotal {s['total_pop_box'] / 1e3:,.0f}k", vpop)]
    grids, scat = {}, []
    for prod in mt["years"][year]:
        spec = cfg["products"][prod]
        lab = labels.get(prod, spec["label"])
        path, note = resolve(args.data_root, spec, year)
        if path is None:
            sys.exit(f"ERROR: {prod} {year}: {note}")
        g, info = ecm.to_grid(path, bt, vpop.shape, crs, cm["subpixel_m"])
        grids[prod] = g
        st = ecm.panel_stats(g, mask, bui, vpop, f)
        pb, rb, full = blocks(g, vpop, mask, f)
        rho = ecm.spearman(pb[full], rb[full])
        if not np.allclose(rho, st["spearman_1km_vs_version"], rtol=0, atol=1e-12, equal_nan=True):
            sys.exit(f"ERROR: scatter blocks differ from the Spearman blocks ({rho} vs {st['spearman_1km_vs_version']})")
        rows.append({**base, "product": prod, "label": spec["label"], "input_unit_class": spec["input_unit_class"],
                     "spearman_1km_vs_version": rho, "n_blocks_1km": int(full.sum()),
                     "total_pop_box": st["total_pop_box"]})
        log.info("  %-9s k = %d: %.0f people in the box | Spearman 1 km vs %s %.3f on %d blocks", prod,
                 info["subpixels_per_side"], st["total_pop_box"], vlab, rho, int(full.sum()))
        maps.append((f"{lab} ({spec['input_unit_class']} input)\ntotal {st['total_pop_box'] / 1e3:,.0f}k", g))
        scat.append((f"{lab} vs {vlab}: rho {rho:.2f}, {int(full.sum())} blocks", rb[full] / bkm2,
                     pb[full] / bkm2, f"{lab}, people per km2 (1 km block)"))
    _, _, full = blocks(vpop, vpop, mask, f)
    text = [f"{city['label']}, {year}, {cm['box_km']:.0f} x {cm['box_km']:.0f} km",
            f"1 km blocks inside our mask: {int(full.sum())}", "",
            "maps: grey = outside our mask (water,", "  no county); white = 0 people", "", "people in the box:"]
    text += [f"  {labels.get(r['product'], r['label'])[:14]:<14} {r['total_pop_box'] / 1e6:6.2f} M" for r in rows]
    gap, gap_rows = None, []
    gc = mt.get("gap", {})
    if gc and gc["product"] in grids:      # every city and year with the gap product
        gb = blocks(grids[gc["product"]], vpop, mask, f)[0]
        vb = blocks(vpop, vpop, mask, f)[0]
        gap = gap_blocks(vb, gb, full, bkm2, gc["ratio_max"], gc["min_density"])
        dense = full & (gb / bkm2 >= gc["min_density"]) & ~gap
        nb = read_on_box(nb_path, bt, vpop.shape, crs) if nb_path is not None else None
        rule = (f"{vlab} / {gc['product']} < {gc['ratio_max']} and {gc['product']} >= {gc['min_density']:,.0f} "
                f"people per km2, 1 km blocks inside our mask")
        for group, fl in (("gap", gap), ("dense_not_gap", dense)):
            r = {"city": key, "year": year, "group": group, "rule": rule, "n_blocks": int(fl.sum()),
                 "n_cells": int(fl.sum()) * f * f, "pop_v56": float(vb[fl].sum())}
            for prod, g in grids.items():
                r[f"pop_{prod}"] = float(blocks(g, vpop, mask, f)[0][fl].sum())
            r["share_cells_bui_gt0"] = cell_share(fl, bui > 0, f)
            r["share_cells_nobuilt_gt0"] = cell_share(fl, nb > 0, f) if nb is not None else np.nan
            r["share_cells_nobuilt_gt0_bui0"] = cell_share(fl, (nb > 0) & (bui <= 0), f) if nb is not None else np.nan
            r["share_cells_no_record"] = cell_share(fl, (nb <= 0) & (bui <= 0), f) if nb is not None else np.nan
            r["nobuilt_source"] = str(nb_path) if nb is not None else "NA: " + nb_how
            gap_rows.append(r)
            log.info("  %-13s %4d blocks, %s %.0f, %s %.0f people; cells BUI > 0 %.3f, NobuiltYear > 0 %s", group,
                     r["n_blocks"], gc["product"], r[f"pop_{gc['product']}"], vlab, r["pop_v56"],
                     r["share_cells_bui_gt0"],
                     f"{r['share_cells_nobuilt_gt0']:.3f}" if nb is not None else "NA (" + nb_how + ")")
        glab = labels.get(gc["product"], cfg["products"][gc["product"]]["label"])
        text += gap_text(gap_rows, glab, vlab, gc)
    prods = [labels.get(p, cfg["products"][p]["label"]) for p in mt["years"][year]]
    missing = tuple(f"{labels.get(p, cfg['products'][p]['label'])}: no {year} grid\n"
                    f"(from {min(cfg['products'][p]['years'])})" for p in mt["products"] if p not in mt["years"][year])
    draw_args = (args.out_dir / f"{key}_{year}.png", f"{city['label']}, {year}: {vlab} vs {' / '.join(prods)} on our "
                 f"250 m grid ({cm['box_km']:.0f} x {cm['box_km']:.0f} km)", maps, mask, cm["box_km"], block_km, gap,
                 full, scat, "\n".join(text), missing)
    return rows, gap_rows, draw_args


def check_previous(new: pd.DataFrame, refs: list, keys: list, cols: list) -> int:
    """Rows of `new` that also are in a previous table (on `keys`) must have the same `cols` (integers equal, floats
    to 1e-9 relative); stops on a difference. Returns the number of rows compared."""
    n = 0
    for path in refs:
        if path is None or not Path(path).exists():
            log.info("  previous %s: not there, nothing to compare", path)
            continue
        old = pd.read_csv(path)
        m = new.merge(old[keys + [c for c in cols if c in old]], on=keys, suffixes=("", "__old"))
        for c in cols:
            if c + "__old" not in m:
                continue
            a, b = m[c].to_numpy(dtype=float), m[c + "__old"].to_numpy(dtype=float)
            bad = ~np.isclose(a, b, rtol=1e-9, atol=1e-12, equal_nan=True)
            if bad.any():
                sys.exit(f"ERROR: {c} differs from {path} for {m.loc[bad, keys].to_dict('records')}: "
                         f"{a[bad].tolist()} vs {b[bad].tolist()}")
        log.info("  MATCH %s: %d rows (%s)", path, len(m), ", ".join(cols))
        n += len(m)
    return n


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    cm, mt = cfg["city_maps"], cfg["city_meeting"]
    mt["years"] = {int(y): p for y, p in mt["years"].items()}
    mt["products"] = list(dict.fromkeys(p for ps in mt["years"].values() for p in ps))   # slot order
    bad = [c for c in mt["cities"] if c not in cm["cities"]] + [p for ps in mt["years"].values() for p in ps
                                                               if p not in cfg["products"]]
    if bad:
        sys.exit(f"ERROR: city_meeting names not in the config: {bad}")
    ins = inputs(args, cfg, cm, mt)
    for y, kind, name, p, note in ins:
        log.info("  input %d %-8s %-22s %s", y, kind, name, p if p is not None else "MISSING: " + note)
    nb_path, nb_how = nobuilt_source(args)
    if nb_path is None:
        log.warning("  input NobuiltYear: %s -> the NobuiltYear columns of the gap table are NA", nb_how)
    else:
        log.info("  input %-8s %-22s %s (%s)", "nobuilt", "NobuiltYear", nb_path, nb_how)
    miss = [r for r in ins if r[3] is None]
    if miss:
        sys.exit(f"ERROR: {len(miss)} inputs missing")
    if args.check:
        log.info("CHECK OK: %d inputs for %d cities x %d years; NobuiltYear %s", len(ins), len(mt["cities"]),
                 len(mt["years"]), nb_how if nb_path is not None else "NA")
        return
    rows, gap_rows, draws = [], [], []
    for year in mt["years"]:
        for key in mt["cities"]:
            r, g, d = run_city(args, cfg, cm, mt, key, year, nb_path, nb_how)
            rows += r
            gap_rows += g
            draws.append(d)
    out = pd.DataFrame(rows)
    gp = pd.DataFrame(gap_rows)
    gap_csv = args.out_dir / GAP_CSV if gap_rows else None
    # numbers must not change with the display: compare with the previous outputs before writing anything
    log.info("check against the previous outputs:")
    check_previous(out, [args.out_dir / "meeting_summary.csv"] + (args.compare_with or []),
                   ["city", "year", "product"], ["spearman_1km_vs_version", "n_blocks_1km", "total_pop_box"])
    if gap_csv is not None:
        num = [c for c in gp.columns if c.startswith(("n_", "pop_", "share_"))]
        check_previous(gp, [gap_csv, args.out_dir / LEGACY_GAP_CSV], ["city", "year", "group"], num)
    for d in draws:
        draw(*d)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out_dir / "meeting_summary.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 20):
        log.info("summary:\n%s", out[["city", "year", "product", "spearman_1km_vs_version", "n_blocks_1km",
                                      "total_pop_box"]].round(3).to_string(index=False))
        if gap_csv is not None:
            gp.to_csv(gap_csv, index=False)
            log.info("gap blocks:\n%s", gp.drop(columns=["rule", "nobuilt_source"]).round(3).to_string(index=False))
            log.info("wrote %s", gap_csv)
            legacy = args.out_dir / LEGACY_GAP_CSV
            if legacy.exists():   # its Chicago 2010 rows matched above and are in gap_blocks.csv
                legacy.unlink()
                log.info("removed %s (Chicago 2010 only; now part of %s)", legacy, GAP_CSV)
    log.info("wrote %s", args.out_dir / "meeting_summary.csv")
    log.info("DONE")


if __name__ == "__main__":
    main()
