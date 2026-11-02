"""Meeting city maps (2010): v5.6 next to GHS-POP / WorldPop with 1 km block scatter plots (docs/conus_plan.md
"External comparison with v5.6: result"; request docs/handoff/city_maps_meeting_request.md). Message: GHS-POP /
WorldPop use block-level census input in the US, so a tract check is not a fair contest; what is compared here is
the spatial pattern (rank agreement, not accuracy). No Fang & Jawitz panel.

Reuses src/validation/external_city_maps.py unchanged: the same box (`city_maps` block of
configs/external_grids.yaml: centre, box_km), the same move of a product to our 250 m cells (population kept), the
same mask (cells with a v5.6 prediction; grey outside) and the same 1 km blocks (4 x 4 cells, only blocks fully inside
the mask) as its Spearman. The `city_meeting` block of the same config picks the year, cities, products and the gap
rule.

Per city, one figure:
  top row     maps v5.6 | GHS-POP | WorldPop, people per km2, one log scale, masked cells grey, 10 km scale bar
  bottom row  1 km block density, x = v5.6, y = product, log axes (blocks with 0 people on a band below / left of
              the axes, counted), 1:1 line, Spearman rho + number of blocks in the title; a text panel with the totals
Gap city (Chicago): 1 km blocks where v5.6 is far below GHS-POP (fixed rule: v5.6 / GHS < ratio_max and GHS >=
min_density people per km2) are outlined on the maps and coloured in the scatter plots; their HISDAC state goes to
<gap_city>_gap_blocks.csv, next to the other dense blocks (GHS >= min_density, not gap): blocks, people (GHS-POP,
WorldPop, v5.6), share of their cells with BUI > 0 (the cutout's BUI of the year) and with NobuiltYear > 0 (records
without a built year; the cutout's NobuiltYear layer if it has one, else HISDAC's FBUY/NobuiltYear.tif read onto the
box; if neither exists those columns are NA and the log says so).

Outputs (<out-dir>): {city}_{year}.png, meeting_summary.csv (city x panel: rho, blocks, people in the box),
<gap_city>_gap_blocks.csv. `--check` only lists the inputs (exit 1 if one is missing; NobuiltYear is optional).
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

def _zero_axis(ax, which: str, lo: float, hi: float, n0: int):
    """Log axis from lo / 6 to hi x 2 with a band at lo / 3 for the blocks with 0 people."""
    from matplotlib.ticker import NullLocator
    span = ax.axvspan if which == "x" else ax.axhspan
    span(lo / 6, lo / 1.6, color=ecm._plots().GRID, lw=0, zorder=0)
    (ax.set_xscale if which == "x" else ax.set_yscale)("log")
    (ax.set_xlim if which == "x" else ax.set_ylim)(lo / 6, hi * 2)
    axis = ax.xaxis if which == "x" else ax.yaxis
    ticks = [t for t in 10.0 ** np.arange(np.ceil(np.log10(lo)), np.floor(np.log10(hi * 2)) + 1)]
    axis.set_ticks([lo / 3] + ticks)
    axis.set_ticklabels([f"0 ({n0})"] + [f"{t:,.0f}" for t in ticks])
    axis.set_minor_locator(NullLocator())


def scatter(ax, x: np.ndarray, y: np.ndarray, gap: np.ndarray | None, title: str, xlab: str, ylab: str):
    """Block densities, log axes, zeros on a band, 1:1 line; gap blocks coloured."""
    plots = ecm._plots()
    pos = np.concatenate([x[x > 0], y[y > 0]])
    lo = 10.0 ** np.floor(np.log10(pos.min())) if pos.size else 1.0
    hi = float(pos.max()) if pos.size else 10.0
    xs, ys = np.where(x > 0, x, lo / 3), np.where(y > 0, y, lo / 3)
    g = np.zeros(len(x), bool) if gap is None else gap
    ax.scatter(xs[~g], ys[~g], s=8, color=plots.SERIES[0], alpha=0.45, lw=0, label="1 km block")
    if g.any():
        ax.scatter(xs[g], ys[g], s=10, color=plots.SERIES[1], alpha=0.85, lw=0, label=f"gap block ({int(g.sum())})")
    _zero_axis(ax, "x", lo, hi, int((x == 0).sum()))
    _zero_axis(ax, "y", lo, hi, int((y == 0).sum()))
    ax.plot([lo, hi * 2], [lo, hi * 2], color=plots.INK2, lw=1, ls="--", label="1:1")
    ax.set_aspect("equal")
    ax.set_xlabel(xlab, fontsize=8, color=plots.INK2)
    ax.set_ylabel(ylab, fontsize=8, color=plots.INK2)
    ax.set_title(title, fontsize=8.5, color=plots.INK)
    ax.tick_params(labelsize=7, colors=plots.INK2)
    for s in ax.spines.values():
        s.set_color(plots.AXIS)
    ax.legend(fontsize=7, frameon=False, loc="upper left")


def draw(path: Path, title: str, maps: list, mask: np.ndarray, box_km: float, block_km: float,
         gap: np.ndarray | None, full: np.ndarray, scatters: list, text: str):
    """maps: [(title, pop on our cells)]; scatters: [(title, x density, y density, ylabel)] over the `full` blocks
    (row-major); gap: block flags (or None)."""
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
    fig = plt.figure(figsize=(13.0, 9.4), dpi=150, layout="constrained")
    gs = fig.add_gridspec(2, 3, height_ratios=[1, 1])
    top = [fig.add_subplot(gs[0, i]) for i in range(3)]
    for ax, (t, _), d in zip(top, maps, dens):
        im = ax.imshow(ecm.for_imshow(d, norm.vmin), cmap=cmap, norm=norm, extent=[-half, half, -half, half],
                       interpolation="nearest")
        if gap is not None:
            for bi, bj in zip(*np.nonzero(gap)):
                ax.add_patch(Rectangle((-half + bj * block_km, half - (bi + 1) * block_km), block_km, block_km,
                                       fill=False, edgecolor=plots.SERIES[1], lw=0.6))
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color(plots.AXIS)
        ax.set_title(t, fontsize=8.5, color=plots.INK)
    ax = top[0]
    ax.plot([-half + 2, -half + 12], [-half + 2, -half + 2], color=plots.INK, lw=2)
    ax.text(-half + 7, -half + 3, "10 km", ha="center", va="bottom", fontsize=7, color=plots.INK)
    cb = fig.colorbar(im, ax=top, shrink=0.8, extend="both")
    cb.set_label("people per km2 (log)", fontsize=7.5, color=plots.INK2)
    cb.ax.tick_params(which="both", labelsize=7, colors=plots.INK2)
    for i, (t, x, y, ylab) in enumerate(scatters):
        scatter(fig.add_subplot(gs[1, i]), x, y, gap[full] if gap is not None else None, t,
                "v5.6, people per km2 (1 km block)", ylab)
    tx = fig.add_subplot(gs[1, 2])
    tx.axis("off")
    tx.text(0.0, 1.0, text, va="top", ha="left", fontsize=8, color=plots.INK, family="monospace",
            transform=tx.transAxes)
    fig.suptitle(f"{title}\n{HEADER}", fontsize=9.5, color=plots.INK)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    log.info("  wrote %s", path)


# ---------------------------------------------------------------- run

def inputs(args, cfg, cm, mt):
    """[(kind, name, path or None, note)]: the files the meeting maps read."""
    v, year = cm["version"], mt["year"]
    out = []
    for kind, name, p in (("version", v, args.dasym_root / args.name / v / "predictions" / f"pop_{year}.tif"),
                          ("bui", "BUI", args.cutout_root / args.name / "layers" / "BUI" / f"{year}_BUI.tif")):
        out.append((kind, name, p if p.exists() else None, "" if p.exists() else f"missing {p}"))
    for prod in mt["products"]:
        path, note = resolve(args.data_root, cfg["products"][prod], year)
        out.append(("product", prod, path, note))
    return out


def run_city(args, cfg, cm, mt, key, nb_path, nb_how):
    city, year = cm["cities"][key], mt["year"]
    v, vlab = cm["version"], cm.get("version_label", cm["version"])
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
    for prod in mt["products"]:
        spec = cfg["products"][prod]
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
        maps.append((f"{spec['label']} ({spec['input_unit_class']} input)\ntotal {st['total_pop_box'] / 1e3:,.0f}k",
                     g))
        scat.append((f"{spec['label']} vs {vlab}: rho {rho:.2f}, {int(full.sum())} blocks", rb[full] / bkm2,
                     pb[full] / bkm2, f"{spec['label']}, people per km2 (1 km block)"))
    _, _, full = blocks(vpop, vpop, mask, f)
    text = [f"{city['label']}, {year}, {cm['box_km']:.0f} x {cm['box_km']:.0f} km",
            f"1 km blocks inside our mask: {int(full.sum())}", "",
            "maps: grey = outside our mask (water,", "  no county); white = 0 people", "", "people in the box:"]
    text += [f"  {r['label'][:22]:<22} {r['total_pop_box'] / 1e6:6.2f} M" for r in rows]
    gap, gap_rows = None, []
    gc = mt.get("gap", {})
    if key == gc.get("city"):
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
        g0 = gap_rows[0]
        glab = cfg["products"][gc["product"]]["label"]
        text += ["", f"gap blocks, orange ({vlab} / {glab}", f"  < {gc['ratio_max']}, {glab} >= {gc['min_density']:,.0f}"
                 " per km2):",
                 f"  blocks                {g0['n_blocks']}",
                 f"  {glab[:12]:<12} people {g0['pop_' + gc['product']] / 1e3:,.0f}k",
                 f"  {vlab[:12]:<12} people {g0['pop_v56'] / 1e3:,.0f}k",
                 f"  cells BUI > 0         {100 * g0['share_cells_bui_gt0']:.1f} %",
                 "  cells NobuiltYear > 0 " + (f"{100 * g0['share_cells_nobuilt_gt0']:.1f} %"
                                               if nb is not None else "NA"),
                 "  cells with no record  " + (f"{100 * g0['share_cells_no_record']:.1f} %"
                                               if nb is not None else "NA")]
    draw(args.out_dir / f"{key}_{year}.png", f"{city['label']}, {year}: {vlab} vs block-input grids on our 250 m "
         f"grid ({cm['box_km']:.0f} x {cm['box_km']:.0f} km)", maps, mask, cm["box_km"], block_km, gap, full, scat,
         "\n".join(text))
    return rows, gap_rows


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    cm, mt = cfg["city_maps"], cfg["city_meeting"]
    mt["year"] = int(mt["year"])
    bad = [c for c in mt["cities"] if c not in cm["cities"]] + [p for p in mt["products"] if p not in cfg["products"]]
    if bad:
        sys.exit(f"ERROR: city_meeting names not in the config: {bad}")
    ins = inputs(args, cfg, cm, mt)
    for kind, name, p, note in ins:
        log.info("  input %-8s %-22s %s", kind, name, p if p is not None else "MISSING: " + note)
    nb_path, nb_how = nobuilt_source(args)
    if nb_path is None:
        log.warning("  input NobuiltYear: %s -> the NobuiltYear columns of the gap table are NA", nb_how)
    else:
        log.info("  input %-8s %-22s %s (%s)", "nobuilt", "NobuiltYear", nb_path, nb_how)
    miss = [r for r in ins if r[2] is None]
    if miss:
        sys.exit(f"ERROR: {len(miss)} inputs missing")
    if args.check:
        log.info("CHECK OK: %d inputs for %d cities, %d; NobuiltYear %s", len(ins), len(mt["cities"]), mt["year"],
                 nb_how if nb_path is not None else "NA")
        return
    rows, gap_rows = [], []
    for key in mt["cities"]:
        r, g = run_city(args, cfg, cm, mt, key, nb_path, nb_how)
        rows += r
        gap_rows += g
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(rows)
    out.to_csv(args.out_dir / "meeting_summary.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 20):
        log.info("summary:\n%s", out[["city", "product", "spearman_1km_vs_version", "n_blocks_1km",
                                      "total_pop_box"]].round(3).to_string(index=False))
        if gap_rows:
            gp = pd.DataFrame(gap_rows)
            gp.to_csv(args.out_dir / f"{mt['gap']['city']}_gap_blocks.csv", index=False)
            log.info("gap blocks:\n%s", gp.drop(columns=["rule"]).round(3).to_string(index=False))
            log.info("wrote %s", args.out_dir / f"{mt['gap']['city']}_gap_blocks.csv")
    log.info("wrote %s", args.out_dir / "meeting_summary.csv")
    log.info("DONE")


if __name__ == "__main__":
    main()
