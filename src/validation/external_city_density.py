"""City boxes by density class: our version vs GHS-POP / WorldPop in rural, peri-urban and urban 1 km blocks (Stefan
2026-11-17 item 4; request docs/handoff/v57_plural_density_request.md part B; docs/conus_plan.md "City boxes by
density class"). Rank and level agreement, not accuracy (GHS-POP / WorldPop use block-level census input in the US).

The boxes, the move of a product to our 250 m cells (population kept), the mask (cells with a prediction of the
version) and the 1 km blocks (4 x 4 cells, only blocks fully inside the mask) are those of external_city_meeting.py
(same functions; city_maps + city_meeting blocks of configs/external_grids.yaml): Boston / Denver / Chicago, 2010
(GHS-POP, WorldPop) and 1980 (GHS-POP).

Classes (`city_density:` block of the same config, fixed before any result): the block density of class_product
(GHS-POP of the same year) - rural < 100, peri_urban 100 - 1,000, urban >= 1,000 people per km2; a block on a break goes
to the upper class (100 -> peri_urban, 1,000 -> urban). The main basis is ghs_pop; WorldPop is compared on the same
GHS-POP classes (the same blocks). As a check the same breaks are applied to our version's block density (basis
`version`): splitting by the product alone could lean the classes towards the product.

Per city x year x product x basis x class (and `all` = every block):
  n_blocks, spearman (block people; NaN below 3 blocks), pop_version / pop_product (sums over the class's blocks) and
  ratio_total = their ratio; block ratio our / product over the blocks with product > 0 (0 where ours is 0):
  ratio_p10 / ratio_median / ratio_p90 (numpy linear quantiles); n_version_zero / n_product_zero / n_both_zero;
  share_above / share_below = share of the blocks that are not 0 in both with our > ratio_band x product (a product-0
  block with our > 0 counts as above) / our < product / ratio_band (our 0 with product > 0 counts as below), i.e.
  |log10 ratio| > log10(ratio_band) split up and down.
Rows of class `all` also carry total_pop_box_version / total_pop_box_product (the whole box, as the meeting summary).

The whole box must equal the meeting maps of the same version (--check-with meeting_summary_<a>_<b>.csv, column =
--version-label): Spearman, blocks and people in the box per product, blocks and people of the version (item model);
the class rows must add up to the `all` row (blocks, people). A difference stops the run before anything is written.

Figure per city and year (<city>_<year>.png, one size): column 1 = the class map (blocks coloured by their GHS-POP
class, grey = outside the mask or not a full block) and a text panel; columns 2-4 = one scatter plot per class (GHS-POP
classes) and one row per product of the year slot (2010: GHS-POP, WorldPop; 1980: GHS-POP + an empty WorldPop row),
on the fixed axes of the meeting scatter plots (0.01 - 30,000 per km2), 1:1 line + x4 / / 4 lines. The meeting map
folders are not touched.

Outputs (<out-dir>, default results/validation/conus/external/city_density_classes_<label>/):
density_class_summary.csv + the PNGs. `--check` only lists the inputs.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import external_city_maps as ecm  # noqa: E402
import external_city_meeting as ecmt  # noqa: E402
from external_compare import load_config, resolve  # noqa: E402

log = logging.getLogger("external_city_density")
VERSION, LABEL = "Dasy_CONUS_RF_v3_all_nby", "v5.7"
CHECK_WITH = Path("results/validation/conus/external/city_maps_meeting_v57/meeting_summary_v56_v57.csv")
EXT = Path("results/validation/conus/external")
BASES = ("ghs_pop", "version")  # class basis: the class product (main), our version (check)
FIGSIZE = (16.0, 8.8)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, default=Path("configs/external_grids.yaml"))
    p.add_argument("--data-root", type=Path, required=True, help="$DATA_ROOT/raw/external")
    p.add_argument("--dasym-root", type=Path, required=True,
                   help="<dasym-root>/<name>/<version>/predictions/pop_{YEAR}.tif")
    p.add_argument("--name", default="conus")
    p.add_argument("--version", default=VERSION)
    p.add_argument("--version-label", default=LABEL)
    p.add_argument("--out-dir", type=Path, help="default results/validation/conus/external/city_density_classes_<label>")
    p.add_argument("--check-with", type=Path, default=CHECK_WITH,
                   help="meeting_summary_<a>_<b>.csv with a column named --version-label (whole-box numbers)")
    p.add_argument("--no-check-with", action="store_true", help="no meeting table for this version (logged)")
    p.add_argument("--check", action="store_true", help="list the inputs only; exit 1 if one is missing")
    a = p.parse_args(argv)
    if a.out_dir is None:
        a.out_dir = EXT / f"city_density_classes_{ecmt.tag(a.version_label)}"
    return a


# ---------------------------------------------------------------- numbers

def classify(dens: np.ndarray, breaks) -> np.ndarray:
    """Class index 0 .. len(breaks) of each block density; a value on a break goes to the upper class."""
    return np.digitize(dens, np.asarray(breaks, float), right=False)


def class_metrics(v: np.ndarray, p: np.ndarray, band: float) -> dict:
    """Metrics of one class: v / p = people of our version / the product per block (the class's blocks)."""
    n = len(v)
    pos = p > 0
    r = v[pos] / p[pos]
    q = np.quantile(r, [0.1, 0.5, 0.9]) if len(r) else [np.nan] * 3
    both0 = (v == 0) & (p == 0)
    d = ~both0
    above = (v > band * p) & d
    below = (v * band < p) & d
    nd = int(d.sum())
    pv, pp = float(v.sum()), float(p.sum())
    return {"n_blocks": n, "spearman": ecm.spearman(v, p), "pop_version": pv, "pop_product": pp,
            "ratio_total": pv / pp if pp > 0 else np.nan, "ratio_p10": q[0], "ratio_median": q[1], "ratio_p90": q[2],
            "n_ratio_blocks": int(pos.sum()), "n_version_zero": int((v == 0).sum()),
            "n_product_zero": int((p == 0).sum()), "n_both_zero": int(both0.sum()), "n_not_both_zero": nd,
            "share_above": above.sum() / nd if nd else np.nan, "share_below": below.sum() / nd if nd else np.nan}


def class_rows(v: np.ndarray, p: np.ndarray, basis_dens: np.ndarray, dc: dict, bkm2: float) -> list[dict]:
    """Rows of every class + `all` for one product and basis (v, p, basis_dens over the full blocks)."""
    cls = classify(basis_dens, dc["breaks"])
    edges = [0.0, *map(float, dc["breaks"]), np.inf]
    rows = []
    for i, name in enumerate(dc["classes"]):
        m = cls == i
        rows.append({"class": name, "dens_lo": edges[i], "dens_hi": edges[i + 1],
                     **class_metrics(v[m], p[m], dc["ratio_band"])})
    rows.append({"class": "all", "dens_lo": 0.0, "dens_hi": np.inf, **class_metrics(v, p, dc["ratio_band"])})
    return rows


# ---------------------------------------------------------------- one city and year

def run_city(args, cfg, cm, mt, dc, key, year):
    """(rows, box rows for the check, figure arguments) of one city and year."""
    city = cm["cities"][key]
    vpath = args.dasym_root / args.name / args.version / "predictions" / f"pop_{year}.tif"
    with rasterio.open(vpath) as src:
        grid_t, crs = src.transform, src.crs
    cx, cy = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(city["lon"], city["lat"])
    win = ecm.box_window(grid_t, cx, cy, cm["box_km"])
    vpop, mask, bt = ecm.read_box(vpath, win, grid_t)
    vpop = np.where(mask, vpop, np.nan)
    f = int(round(cm.get("block_km", 1) * 1000 / grid_t.a))
    if vpop.shape[0] % f or vpop.shape[1] % f:
        sys.exit(f"ERROR: box of {vpop.shape} cells is not a multiple of {f}-cell blocks")
    bkm2 = f * f * ecm.CELL_KM2
    labels = mt.get("labels", {})
    log.info("===== %s %d: window %s, %d of %d cells in the mask of %s", city["label"], year, win, int(mask.sum()),
             mask.size, args.version)
    grids = {}
    for prod in mt["years"][year]:
        path, note = resolve(args.data_root, cfg["products"][prod], year)
        if path is None:
            sys.exit(f"ERROR: {prod} {year}: {note}")
        grids[prod], info = ecm.to_grid(path, bt, vpop.shape, crs, cm["subpixel_m"])
    cp = dc["class_product"]
    if cp not in grids:
        sys.exit(f"ERROR: {year}: class product {cp} is not a product of the year ({list(grids)})")
    vb, _, full = ecmt.blocks(vpop, vpop, mask, f)
    cb = ecmt.blocks(grids[cp], vpop, mask, f)[0]
    basis = {"ghs_pop": cb[full] / bkm2, "version": vb[full] / bkm2}
    s0 = ecm.panel_stats(vpop, mask, np.zeros_like(vpop), vpop, f)
    box = [{"city": key, "year": year, "item": "model", "n_blocks_1km": s0["n_blocks_1km"],
            "total_pop_box": s0["total_pop_box"]}]
    rows, scat = [], {}
    base = {"city": key, "city_label": city["label"], "year": year, "version": args.version,
            "version_label": args.version_label, "class_product": cp}
    for prod, g in grids.items():
        st = ecm.panel_stats(g, mask, np.zeros_like(vpop), vpop, f)
        pb = ecmt.blocks(g, vpop, mask, f)[0]
        v, p = vb[full], pb[full]
        box.append({"city": key, "year": year, "item": prod, "n_blocks_1km": st["n_blocks_1km"],
                    "total_pop_box": st["total_pop_box"], "spearman_1km_vs_version": st["spearman_1km_vs_version"]})
        for b in BASES:
            for r in class_rows(v, p, basis[b], dc, bkm2):
                row = {**base, "product": prod, "product_label": labels.get(prod, cfg["products"][prod]["label"]),
                       "basis": b, **r}
                if r["class"] == "all":
                    row.update(total_pop_box_version=s0["total_pop_box"], total_pop_box_product=st["total_pop_box"])
                rows.append(row)
        scat[prod] = (v / bkm2, p / bkm2, classify(basis["ghs_pop"], dc["breaks"]))
        a = [r for r in rows if r["product"] == prod and r["basis"] == "ghs_pop"]
        log.info("  %-9s %s", prod, " | ".join(f"{r['class']} {r['n_blocks']} blocks rho {r['spearman']:.3f} ratio "
                                                 f"{r['ratio_total']:.3f}" for r in a))
    cls_grid = np.full(full.shape, np.nan)
    cls_grid[full] = classify(basis["ghs_pop"], dc["breaks"])
    draw_args = (args.out_dir / f"{key}_{year}.png", city["label"], year, cls_grid, cm["box_km"], f * grid_t.a / 1000,
                 scat, rows, mt, labels, dc, args.version_label)
    return rows, box, draw_args


# ---------------------------------------------------------------- checks

def check_box(box: pd.DataFrame, path: Path, label: str):
    """Whole-box numbers = the meeting maps' (side-by-side table, column `label`); stops on a difference."""
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (--check-with; or --no-check-with for a version without meeting maps)")
    side = pd.read_csv(path)
    if label not in side:
        sys.exit(f"ERROR: {path} has no column {label!r} (columns {list(side.columns)})")
    s = side[side["table"] == "summary"]
    long = box.melt(id_vars=["city", "year", "item"], value_vars=["n_blocks_1km", "total_pop_box",
                                                                 "spearman_1km_vs_version"], var_name="measure").dropna()
    m = long.merge(s[["city", "year", "item", "measure", label]], on=["city", "year", "item", "measure"], how="left")
    if m[label].isna().any():
        lost = m.loc[m[label].isna(), ["city", "year", "item", "measure"]].to_dict("records")
        sys.exit(f"ERROR: whole-box rows not in {path}: {lost}")
    bad = ~np.isclose(m["value"].to_numpy(float), m[label].to_numpy(float), rtol=1e-9, atol=1e-12)
    if bad.any():
        sys.exit(f"ERROR: whole box differs from {path} ({label}): "
                 f"{m.loc[bad, ['city', 'year', 'item', 'measure', 'value', label]].to_dict('records')}")
    log.info("  MATCH %s: %d whole-box numbers of %s (Spearman, blocks, people in the box)", path, len(m), label)


def check_sums(t: pd.DataFrame, classes):
    """The classes add up to `all` (blocks, people) for every city / year / product / basis."""
    keys = ["city", "year", "product", "basis"]
    a = t[t["class"] == "all"].set_index(keys)
    c = t[t["class"].isin(classes)].groupby(keys)[["n_blocks", "pop_version", "pop_product"]].sum()
    for col in c.columns:
        if not np.allclose(c[col], a.loc[c.index, col], rtol=1e-9, atol=1e-6):
            sys.exit(f"ERROR: the classes do not add up to all ({col})")
    log.info("  classes add up to all: %d groups (blocks, people)", len(c))


# ---------------------------------------------------------------- figure

def draw(path: Path, city_label: str, year: int, cls_grid: np.ndarray, box_km: float, block_km: float, scat: dict,
         rows: list, mt: dict, labels: dict, dc: dict, vlab: str):
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
    plots = ecm._plots()
    plt = plots.plt
    colors = [plots.BLUES[1], plots.BLUES[4], plots.BLUES[7]]  # sequential: rural light ... urban dark
    names = {"rural": "rural", "peri_urban": "peri-urban", "urban": "urban"}
    br = dc["breaks"]
    ranges = [f"< {br[0]:,.0f}", f"{br[0]:,.0f} - {br[1]:,.0f}", f">= {br[1]:,.0f}"]
    band = dc["ratio_band"]
    fig = plt.figure(figsize=FIGSIZE, dpi=150, layout="constrained")
    axes = fig.subplots(2, 4, squeeze=False)
    half = box_km / 2
    ax = axes[0][0]
    cmap = ListedColormap(colors)
    cmap.set_bad(ecm.MASK_GREY)
    ax.imshow(np.ma.masked_invalid(cls_grid), cmap=cmap, vmin=-0.5, vmax=2.5, extent=[-half, half, -half, half],
              interpolation="nearest")
    ecmt.scale_bar(ax, half)
    ax.set_xticks([])
    ax.set_yticks([])
    cp = labels.get(dc["class_product"], dc["class_product"])
    n = [int((cls_grid == i).sum()) for i in range(3)]
    ax.legend(handles=[Patch(color=c, label=f"{names[k]} {r} ({m})") for c, k, r, m in
                       zip(colors, dc["classes"], ranges, n)] + [Patch(color=ecm.MASK_GREY, label="outside the mask")],
              fontsize=6.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=2,
              title=f"{cp} per km2 (1 km blocks)", title_fontsize=6.5)  # below the map: no block hidden
    ax.set_title(f"classes by {cp} {year}", fontsize=8.5, color=plots.INK)
    prods = mt["products"]
    for i, prod in enumerate(prods):
        lab = labels.get(prod, prod)
        for j, cname in enumerate(dc["classes"]):
            a = axes[i][j + 1]
            if prod not in scat:
                ecmt.placeholder(a, f"{lab}: no {year} grid")
                continue
            x, y, cls = scat[prod]
            m = cls == j
            r = next(r for r in rows if r["product"] == prod and r["basis"] == "ghs_pop" and r["class"] == cname)
            rho = "NA" if not np.isfinite(r["spearman"]) else f"{r['spearman']:.2f}"
            ecmt.scatter(a, x[m], y[m], None, f"{names[cname]} ({ranges[j]}): {lab} vs {vlab}\nrho {rho}, "
                         f"{int(m.sum())} blocks, total {vlab} / {lab} {r['ratio_total']:.2f}",
                         f"{vlab}, people per km2", f"{lab}, people per km2")
            lo, hi = ecmt.SC_LO, ecmt.SC_HI
            # product = our / band and our x band: the lines of the above / below counts
            a.plot([lo, hi], [lo / band, hi / band], color=plots.MUTED, lw=0.8, ls=":")
            a.plot([lo, hi], [lo * band, hi * band], color=plots.MUTED, lw=0.8, ls=":", label=f"x{band:g} / /{band:g}")
            a.set_xlim(ecmt.SC_LOW_LIMIT, hi)
            a.set_ylim(ecmt.SC_LOW_LIMIT, hi)
            a.legend(fontsize=6.5, frameon=False, loc="upper left")
    tx = axes[1][0]
    tx.axis("off")
    lines = [f"{city_label}, {year}, {box_km:.0f} x {box_km:.0f} km", f"classes by {cp} block density", "",
             f"{'':<11}{'blocks':>7}{'rho':>7}{'ratio':>7}{'>x' + format(band, 'g'):>6}{'</' + format(band, 'g'):>6}"]
    for prod in prods:
        if prod not in scat:
            continue
        lines.append(labels.get(prod, prod))
        for cname in [*dc["classes"], "all"]:
            r = next(r for r in rows if r["product"] == prod and r["basis"] == "ghs_pop" and r["class"] == cname)
            rho = "NA" if not np.isfinite(r["spearman"]) else f"{r['spearman']:.2f}"
            lines.append(f" {names.get(cname, cname):<10}{r['n_blocks']:>7}{rho:>7}{r['ratio_total']:>7.2f}"
                         f"{100 * r['share_above']:>5.0f}%{100 * r['share_below']:>5.0f}%")
    lines += ["", f"ratio = {vlab} / product (people)", f">x{band:g} / </{band:g}: share of blocks", "rank and level agreement,",
              "not accuracy"]
    tx.text(0.0, 1.0, "\n".join(lines), va="top", ha="left", fontsize=7.5, color=plots.INK, family="monospace",
            transform=tx.transAxes)
    fig.suptitle(f"{city_label}, {year}: {vlab} vs {' / '.join(labels.get(p, p) for p in scat)} by density class "
                 f"({cp} 1 km blocks; rural < {br[0]:,.0f}, peri-urban {br[0]:,.0f} - {br[1]:,.0f}, urban >= "
                 f"{br[1]:,.0f} per km2)", fontsize=9.5, color=plots.INK)
    path.parent.mkdir(parents=True, exist_ok=True)
    from matplotlib.transforms import Bbox
    w, h = FIGSIZE
    fig.savefig(path, facecolor="white", bbox_inches=Bbox([[-0.3, -0.3], [w + 0.3, h + 0.3]]))
    plt.close(fig)
    log.info("  wrote %s", path)


# ---------------------------------------------------------------- main

def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    cm, mt, dc = cfg["city_maps"], cfg["city_meeting"], cfg.get("city_density")
    if not dc:
        sys.exit(f"ERROR: no city_density block in {args.config}")
    if len(dc["classes"]) != len(dc["breaks"]) + 1 or list(dc["breaks"]) != sorted(dc["breaks"]):
        sys.exit(f"ERROR: city_density: {len(dc['classes'])} classes for breaks {dc['breaks']}")
    mt["years"] = {int(y): p for y, p in mt["years"].items()}
    mt["products"] = list(dict.fromkeys(p for ps in mt["years"].values() for p in ps))
    log.info("RULE (fixed before the results): classes by %s block density of the year, breaks %s (on a break = the "
             "upper class) -> %s; check basis = %s's density; ratio band x%g", dc["class_product"], dc["breaks"],
             dc["classes"], args.version_label, dc["ratio_band"])
    miss = []
    for year, prods in mt["years"].items():
        p = args.dasym_root / args.name / args.version / "predictions" / f"pop_{year}.tif"
        log.info("  input %d version %-24s %s", year, args.version, p if p.exists() else "MISSING")
        miss += [] if p.exists() else [str(p)]
        for prod in prods:
            path, note = resolve(args.data_root, cfg["products"][prod], year)
            log.info("  input %d product %-24s %s", year, prod, path if path is not None else "MISSING: " + note)
            miss += [] if path is not None else [f"{prod} {year}: {note}"]
    if not args.no_check_with:
        log.info("  input whole-box check %s %s", args.check_with, "" if args.check_with.exists() else "MISSING")
        miss += [] if args.check_with.exists() else [str(args.check_with)]
    if miss:
        sys.exit(f"ERROR: {len(miss)} inputs missing: {miss}")
    if args.check:
        log.info("CHECK OK: inputs for %d cities x %d years", len(mt["cities"]), len(mt["years"]))
        return 0
    rows, box, draws = [], [], []
    for year in mt["years"]:
        for key in mt["cities"]:
            r, b, d = run_city(args, cfg, cm, mt, dc, key, year)
            rows += r
            box += b
            draws.append(d)
    t, bx = pd.DataFrame(rows), pd.DataFrame(box)
    log.info("checks (a difference stops the run before writing):")
    check_sums(t, dc["classes"])
    if args.no_check_with:
        log.warning("  whole box NOT checked (--no-check-with)")
    else:
        check_box(bx, args.check_with, args.version_label)
    for d in draws:
        draw(*d)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    t.to_csv(args.out_dir / "density_class_summary.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_rows", 200, "display.max_columns", 30):
        cols = ["city", "year", "product", "class", "n_blocks", "spearman", "ratio_total", "ratio_p10", "ratio_median",
                "ratio_p90", "n_version_zero", "n_product_zero", "share_above", "share_below"]
        for b in BASES:
            log.info("SUMMARY classes by %s (%s):\n%s", "GHS-POP (main)" if b == "ghs_pop" else
                     f"{args.version_label} (check)", b, t.loc[t["basis"] == b, cols].round(3).to_string(index=False))
    log.info("wrote %s", args.out_dir / "density_class_summary.csv")
    log.info("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
