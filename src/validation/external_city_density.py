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

More versions (--extra-version V=LABEL, request docs/handoff/city_density_run_request.md: v5.7 + PLURAL pq5) get the
same class rows (column version) on their own mask, without the whole-box check (no earlier numbers; logged). They must
be on the grid of the main version.

Cell types (request docs/handoff/city_density_run_request.md; does PLURAL put people where GHS-POP / WorldPop, which use
block-level census input, also have people?): the 250 m cells of the full 1 km blocks inside the main version's mask
(the blocks above; cells of partial blocks are left out so that the classes add up to the box) are split into
  bui_gt0           BUI of the year > 0
  bui0_nobuilt_gt0  BUI = 0 and NobuiltYear > 0 (records without a built year only)
  bui0_no_record    BUI = 0 and NobuiltYear = 0 (no HISDAC record)
BUI = the cutout's layers/BUI/{YEAR}_BUI.tif; NobuiltYear = the source of external_city_meeting.py (cutout
layers/NobuiltYear/*.tif, else HISDAC FBUY/NobuiltYear.tif) or else the cutout layer NOBUILT/NOBUILT.tif, read onto the
box in the same way (nodata = 0). Per city x year x class (GHS-POP block class of the cell's block, + all) x cell type:
n_cells, share_<p> = people of p on those cells / people of p on all these cells of the box (so the three types of
`all` add up to 1 and the classes add up to `all`), share_class_<p> = the same within the class, pop_<p>; p = the
products of the year (ghs_pop, worldpop) and every version (column tag of its label: v57, v57pq5). An extra version's
people outside the main mask are left out (logged). Checks: n_cells of a class = 16 x its blocks; with the meeting
check the main version's gap / dense_not_gap blocks of the meeting maps are recomputed and their cell shares (BUI > 0,
BUI = 0 and NobuiltYear > 0, no record) must equal the meeting's gap_blocks.csv next to --check-with (the same BUI /
NobuiltYear reads). One bar figure per city and year (<city>_<year>_cell_types.png, one size): a panel per class (+
all), one stacked bar per product / version = the three type shares within the class, the class's share of the box
people above the bar.

Outputs (<out-dir>, default results/validation/conus/external/city_density_classes_<label>/):
density_class_summary.csv, cell_type_shares.csv + the PNGs. `--check` only lists the inputs.
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
    p.add_argument("--cutout-root", type=Path, required=True,
                   help="<cutout-root>/<name>/layers/BUI/{YEAR}_BUI.tif (+ NobuiltYear / NOBUILT layers if cut)")
    p.add_argument("--hisdac-dir", type=Path, default=None, help="HISDAC-US V2 folder: FBUY/NobuiltYear.tif")
    p.add_argument("--name", default="conus")
    p.add_argument("--version", default=VERSION)
    p.add_argument("--extra-version", action="append", default=[], metavar="VERSION=LABEL",
                   help="another version on the same grid: class rows + cell-type shares, no whole-box check")
    p.add_argument("--version-label", default=LABEL)
    p.add_argument("--out-dir", type=Path, help="default results/validation/conus/external/city_density_classes_<label>")
    p.add_argument("--check-with", type=Path, default=CHECK_WITH,
                   help="meeting_summary_<a>_<b>.csv with a column named --version-label (whole-box numbers)")
    p.add_argument("--no-check-with", action="store_true", help="no meeting table for this version (logged)")
    p.add_argument("--check", action="store_true", help="list the inputs only; exit 1 if one is missing")
    a = p.parse_args(argv)
    a.extra = []
    for e in a.extra_version:
        if "=" not in e:
            p.error(f"--extra-version {e!r}: VERSION=LABEL")
        a.extra.append(tuple(e.split("=", 1)))
    tags = [ecmt.tag(lab) for lab in [a.version_label, *(lab for _, lab in a.extra)]]
    if len(set(tags)) != len(tags):
        p.error(f"version labels give the same column tag: {tags}")
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


CELL_TYPES = ("bui_gt0", "bui0_nobuilt_gt0", "bui0_no_record")


def cell_types(bui: np.ndarray, nb: np.ndarray) -> np.ndarray:
    """0 = BUI > 0, 1 = BUI = 0 and NobuiltYear > 0, 2 = BUI = 0 and NobuiltYear = 0 (no record)."""
    return np.where(bui > 0, 0, np.where(nb > 0, 1, 2))


def cell_type_rows(pops: dict, ctype: np.ndarray, ccls: np.ndarray, sel: np.ndarray, classes) -> list[dict]:
    """Rows class x cell type over the cells `sel`: n_cells, share_<p> (of p's people on sel), share_class_<p>
    (within the class), pop_<p>; pops = {column tag: people per cell}, ccls = class index per cell."""
    tot = {k: float(v[sel].sum()) for k, v in pops.items()}
    rows = []
    for cname, cm in [*((c, ccls == i) for i, c in enumerate(classes)), ("all", np.ones_like(sel))]:
        cs = sel & cm
        ctot = {k: float(v[cs].sum()) for k, v in pops.items()}
        for t, tname in enumerate(CELL_TYPES):
            m = cs & (ctype == t)
            r = {"class": cname, "cell_type": tname, "n_cells": int(m.sum())}
            pp = {k: float(v[m].sum()) for k, v in pops.items()}
            r.update({f"share_{k}": pp[k] / tot[k] if tot[k] > 0 else np.nan for k in pops})
            r.update({f"share_class_{k}": pp[k] / ctot[k] if ctot[k] > 0 else np.nan for k in pops})
            r.update({f"pop_{k}": pp[k] for k in pops})
            rows.append(r)
    return rows


def nobuilt_path(args):
    """(path, how) of NobuiltYear: external_city_meeting.py's source, else the cutout layer NOBUILT/NOBUILT.tif."""
    path, how = ecmt.nobuilt_source(args)
    if path is not None:
        return path, how
    p = args.cutout_root / args.name / "layers" / "NOBUILT" / "NOBUILT.tif"
    return (p, "cutout NOBUILT") if p.exists() else (None, f"{how}; {p} not found")


# ---------------------------------------------------------------- one city and year

def version_rows(vpop, mask, grids, f, bkm2, dc, base, labels, cfg):
    """(class rows, scatter data, class grid, full-block flags) of one version over its own mask."""
    vb, _, full = ecmt.blocks(vpop, vpop, mask, f)
    cb = ecmt.blocks(grids[dc["class_product"]], vpop, mask, f)[0]
    basis = {"ghs_pop": cb[full] / bkm2, "version": vb[full] / bkm2}
    rows, scat = [], {}
    for prod, g in grids.items():
        st = ecm.panel_stats(g, mask, np.zeros_like(vpop), vpop, f)
        pb = ecmt.blocks(g, vpop, mask, f)[0]
        v, p = vb[full], pb[full]
        for b in BASES:
            for r in class_rows(v, p, basis[b], dc, bkm2):
                row = {**base, "product": prod, "product_label": labels.get(prod, cfg["products"][prod]["label"]),
                       "basis": b, **r}
                if r["class"] == "all":
                    row.update(total_pop_box_version=float(np.nansum(vpop)), total_pop_box_product=st["total_pop_box"])
                rows.append(row)
        scat[prod] = (v / bkm2, p / bkm2, classify(basis["ghs_pop"], dc["breaks"]))
        a = [r for r in rows if r["product"] == prod and r["basis"] == "ghs_pop"]
        log.info("  %-10s %-9s %s", base["version_label"], prod, " | ".join(
            f"{r['class']} {r['n_blocks']} blocks rho {r['spearman']:.3f} ratio {r['ratio_total']:.3f}" for r in a))
    cls_grid = np.full(full.shape, np.nan)
    cls_grid[full] = classify(basis["ghs_pop"], dc["breaks"])
    return rows, scat, cls_grid, full


def run_city(args, cfg, cm, mt, dc, key, year, nb_path):
    """(class rows, box rows for the check, figure arguments, cell-type rows, gap cell rows, bar figure arguments)
    of one city and year."""
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
    s0 = ecm.panel_stats(vpop, mask, np.zeros_like(vpop), vpop, f)
    box = [{"city": key, "year": year, "item": "model", "n_blocks_1km": s0["n_blocks_1km"],
            "total_pop_box": s0["total_pop_box"]}]
    for prod, g in grids.items():
        st = ecm.panel_stats(g, mask, np.zeros_like(vpop), vpop, f)
        box.append({"city": key, "year": year, "item": prod, "n_blocks_1km": st["n_blocks_1km"],
                    "total_pop_box": st["total_pop_box"], "spearman_1km_vs_version": st["spearman_1km_vs_version"]})
    base = {"city": key, "city_label": city["label"], "year": year, "class_product": cp}
    rows, scat, cls_grid, full = version_rows(vpop, mask, grids, f, bkm2, dc,
                                              {**base, "version": args.version, "version_label": args.version_label},
                                              labels, cfg)
    vers = {ecmt.tag(args.version_label): np.nan_to_num(vpop, nan=0.0)}
    for v, lab in args.extra:
        p = args.dasym_root / args.name / v / "predictions" / f"pop_{year}.tif"
        xpop, xmask, _ = ecm.read_box(p, win, grid_t)  # stops if not on the main version's grid
        xpop = np.where(xmask, xpop, np.nan)
        nd = int((xmask != mask).sum())
        if nd:
            log.warning("  %s: mask differs from %s's in %d cells (%.0f of its people outside the main mask; left "
                        "out of the cell types)", lab, args.version_label, nd, float(np.nansum(xpop[~mask])))
        rows += version_rows(xpop, xmask, grids, f, bkm2, dc, {**base, "version": v, "version_label": lab}, labels,
                             cfg)[0]
        vers[ecmt.tag(lab)] = np.where(mask, np.nan_to_num(xpop, nan=0.0), 0.0)
    # cell types on the cells of the main version's full blocks
    bui, bvalid, _ = ecm.read_box(args.cutout_root / args.name / "layers" / "BUI" / f"{year}_BUI.tif", win, grid_t)
    bui = np.where(bvalid, bui, -1.0)
    nb = ecmt.read_on_box(nb_path, bt, vpop.shape, crs)
    ctype = cell_types(bui, nb)
    up = np.ones((f, f))
    sel = np.kron(full, up).astype(bool)
    ccls = np.kron(np.nan_to_num(cls_grid, nan=-1), up).astype(int)
    pops = {k: np.where(sel, np.nan_to_num(g, nan=0.0), 0.0) for k, g in grids.items()} | vers
    crow = [{"city": key, "city_label": city["label"], "year": year, **r}
            for r in cell_type_rows(pops, ctype, ccls, sel, dc["classes"])]
    for r in crow:
        if r["class"] == "all":
            log.info("  cells %-16s %6d  %s", r["cell_type"], r["n_cells"],
                     "  ".join(f"{k} {100 * r[f'share_{k}']:.1f}%" for k in pops))
    gap = []
    gc = mt.get("gap", {})
    if gc and gc["product"] in grids:  # meeting gap blocks of the main version: check of the BUI / NobuiltYear reads
        vb = ecmt.blocks(vpop, vpop, mask, f)[0]
        gb = ecmt.blocks(grids[gc["product"]], vpop, mask, f)[0]
        g = ecmt.gap_blocks(vb, gb, full, bkm2, gc["ratio_max"], gc["min_density"])
        dense = full & (gb / bkm2 >= gc["min_density"]) & ~g
        for group, fl in (("gap", g), ("dense_not_gap", dense)):
            gap.append({"city": key, "year": year, "group": group, "n_cells": int(fl.sum()) * f * f,
                        "share_cells_bui_gt0": ecmt.cell_share(fl, ctype == 0, f),
                        "share_cells_nobuilt_gt0_bui0": ecmt.cell_share(fl, ctype == 1, f),
                        "share_cells_no_record": ecmt.cell_share(fl, ctype == 2, f)})
    draw_args = (args.out_dir / f"{key}_{year}.png", city["label"], year, cls_grid, cm["box_km"], f * grid_t.a / 1000,
                 scat, [r for r in rows if r["version"] == args.version], mt, labels, dc, args.version_label)
    vlabs = [args.version_label, *(lab for _, lab in args.extra)]
    cols = [*mt["products"], *(ecmt.tag(lab) for lab in vlabs)]
    names = {**{p: labels.get(p, cfg["products"][p]["label"]) for p in mt["products"]},
             **{ecmt.tag(lab): lab for lab in vlabs}}
    bar_args = (args.out_dir / f"{key}_{year}_cell_types.png", city["label"], year, crow, cols, names, dc)
    return rows, box, draw_args, crow, gap, bar_args


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


def check_cells(c: pd.DataFrame, t: pd.DataFrame, classes, version: str, f: int = 4):
    """Cell types: the three types of `all` add up to 1, the classes add up to `all`, n_cells = f^2 x blocks."""
    shares = [k for k in c.columns if k.startswith("share_") and not k.startswith("share_class_")]
    for (city, year), g in c.groupby(["city", "year"]):
        a = g[g["class"] == "all"]
        tot = a[shares].sum(min_count=1).dropna()
        if not np.allclose(tot, 1.0, atol=1e-9):
            sys.exit(f"ERROR: {city} {year}: cell-type shares of the box do not add up to 1: {tot.to_dict()}")
        cl = g[g["class"].isin(classes)].groupby("cell_type")[["n_cells", *shares]].sum(min_count=1)
        al = a.set_index("cell_type")[["n_cells", *shares]].loc[cl.index]
        if not np.allclose(cl.to_numpy(float), al.to_numpy(float), atol=1e-9, equal_nan=True):
            sys.exit(f"ERROR: {city} {year}: cell types of the classes do not add up to all")
        n = g[g["class"].isin(classes)].groupby("class")["n_cells"].sum()
        b = t[(t["city"] == city) & (t["year"] == year) & (t["version"] == version) & (t["basis"] == "ghs_pop")
              & (t["product"] == t["class_product"])].set_index("class")["n_blocks"]
        if not (n == f * f * b.loc[n.index]).all():
            sys.exit(f"ERROR: {city} {year}: cells per class != {f * f} x blocks ({n.to_dict()} vs {b.to_dict()})")
    log.info("  cell types add up: %d city-years (box shares = 1, classes = all, cells = %d x blocks)",
             c.groupby(["city", "year"]).ngroups, f * f)


def check_gap_cells(gap: pd.DataFrame, path: Path):
    """Cell shares of the main version's gap / dense_not_gap blocks = the meeting's gap_blocks.csv."""
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (gap table of the meeting maps next to --check-with)")
    ref = pd.read_csv(path)
    cols = ["n_cells", "share_cells_bui_gt0", "share_cells_nobuilt_gt0_bui0", "share_cells_no_record"]
    m = gap.merge(ref[["city", "year", "group", *cols]], on=["city", "year", "group"], how="outer",
                  suffixes=("", "_ref"), indicator=True)
    if (m["_merge"] != "both").any():
        sys.exit(f"ERROR: gap groups differ from {path}: "
                 f"{m.loc[m['_merge'] != 'both', ['city', 'year', 'group']].to_dict('records')}")
    for col in cols:
        if not np.allclose(m[col].to_numpy(float), m[col + "_ref"].to_numpy(float), rtol=1e-9, atol=1e-12,
                           equal_nan=True):
            sys.exit(f"ERROR: {col} of the gap blocks differs from {path}: "
                     f"{m[['city', 'year', 'group', col, col + '_ref']].to_dict('records')}")
    log.info("  MATCH %s: %d gap / dense_not_gap groups (cells, BUI > 0, BUI = 0 and NobuiltYear > 0, no record)",
             path, len(m))


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


TYPE_LABELS = {"bui_gt0": "BUI > 0", "bui0_nobuilt_gt0": "BUI = 0, NobuiltYear > 0 (undated records only)",
               "bui0_no_record": "BUI = 0, NobuiltYear = 0 (no record)"}
BAR_FIGSIZE = (15.0, 5.2)


def draw_cells(path: Path, city_label: str, year: int, crow: list, cols: list, names: dict, dc: dict,
               class_note: str = "GHS-POP 1 km block density"):
    """One panel per class (+ the whole box): a stacked bar per product / version = the cell-type shares within the
    class; above the bar the class's share of the box people. class_note: what the classes are (title)."""
    plots = ecm._plots()
    plt = plots.plt
    colors = plots.SERIES[:3]  # fixed order: BUI > 0, undated records only, no record
    panels = ["all", *dc["classes"]]
    pname = {"all": "whole box", "rural": "rural", "peri_urban": "peri-urban", "urban": "urban"}
    fig = plt.figure(figsize=BAR_FIGSIZE, dpi=150, layout="constrained")
    axes = fig.subplots(1, len(panels), sharey=True, squeeze=False)[0]
    x = np.arange(len(cols))
    for ax, cname in zip(axes, panels):
        g = {r["cell_type"]: r for r in crow if r["class"] == cname}
        ncell = sum(g[t]["n_cells"] for t in CELL_TYPES)
        bottom = np.zeros(len(cols))
        for t, col in zip(CELL_TYPES, colors):
            h = np.array([g[t].get(f"share_class_{k}", np.nan) for k in cols], float)
            ok = np.isfinite(h)
            ax.bar(x[ok], h[ok], bottom=bottom[ok], width=0.62, color=col, edgecolor="white", linewidth=1.0,
                   label=TYPE_LABELS[t])
            for xi, hi, bi in zip(x[ok], h[ok], bottom[ok]):
                if hi >= 0.05:
                    ax.text(xi, bi + hi / 2, f"{100 * hi:.0f}", ha="center", va="center", fontsize=7, color="white")
            bottom[ok] += h[ok]
        for xi, k in zip(x, cols):
            sv = np.array([g[t].get(f"share_{k}", np.nan) for t in CELL_TYPES], float)
            if np.isfinite(sv).all():
                ax.text(xi, 1.015, f"{100 * sv.sum():.0f}%", ha="center", va="bottom", fontsize=7, color=plots.MUTED)
            else:
                ax.text(xi, 0.5, f"no {year} grid", ha="center", va="center", rotation=90, fontsize=7,
                        color=plots.MUTED)
        ax.set_xticks(x, [names[k] for k in cols], rotation=30, ha="right", fontsize=7.5)
        ax.set_ylim(0, 1.08)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0", "25", "50", "75", "100"])
        ax.set_title(f"{pname.get(cname, cname)} ({ncell:,} cells)", fontsize=8.5, color=plots.INK)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(labelsize=7.5, colors=plots.INK)
        ax.grid(axis="y", color="#e6e6e3", lw=0.6)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("% of the class's people on cells of the type", fontsize=8, color=plots.INK)
    h, lab = axes[0].get_legend_handles_labels()
    fig.legend(h, lab, loc="outside lower center", ncol=3, fontsize=7.5, frameon=False)
    fig.suptitle(f"{city_label}, {year}: people by HISDAC record of their 250 m cell (classes = {class_note}; "
                 f"grey number above a bar = the class's share of the box people)", fontsize=9,
                 color=plots.INK)
    path.parent.mkdir(parents=True, exist_ok=True)
    from matplotlib.transforms import Bbox
    w, hh = BAR_FIGSIZE
    fig.savefig(path, facecolor="white", bbox_inches=Bbox([[-0.3, -0.3], [w + 0.3, hh + 0.3]]))
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
        for v in [args.version, *(v for v, _ in args.extra)]:
            p = args.dasym_root / args.name / v / "predictions" / f"pop_{year}.tif"
            log.info("  input %d version %-24s %s", year, v, p if p.exists() else "MISSING")
            miss += [] if p.exists() else [str(p)]
        p = args.cutout_root / args.name / "layers" / "BUI" / f"{year}_BUI.tif"
        log.info("  input %d BUI     %-24s %s", year, "", p if p.exists() else "MISSING")
        miss += [] if p.exists() else [str(p)]
        for prod in prods:
            path, note = resolve(args.data_root, cfg["products"][prod], year)
            log.info("  input %d product %-24s %s", year, prod, path if path is not None else "MISSING: " + note)
            miss += [] if path is not None else [f"{prod} {year}: {note}"]
    nb_path, nb_how = nobuilt_path(args)
    log.info("  input NobuiltYear %s", f"{nb_path} ({nb_how})" if nb_path is not None else "MISSING: " + nb_how)
    miss += [] if nb_path is not None else [f"NobuiltYear: {nb_how}"]
    gap_ref = args.check_with.parent / "gap_blocks.csv"
    if not args.no_check_with:
        for p in (args.check_with, gap_ref):
            log.info("  input meeting check %s %s", p, "" if p.exists() else "MISSING")
            miss += [] if p.exists() else [str(p)]
    for v, lab in args.extra:
        log.info("  extra version %s (%s): whole box NOT checked (no earlier numbers)", v, lab)
    if miss:
        sys.exit(f"ERROR: {len(miss)} inputs missing: {miss}")
    if args.check:
        log.info("CHECK OK: inputs for %d cities x %d years", len(mt["cities"]), len(mt["years"]))
        return 0
    rows, box, draws, cells, gaps, bars = [], [], [], [], [], []
    for year in mt["years"]:
        for key in mt["cities"]:
            r, b, d, c, g, br = run_city(args, cfg, cm, mt, dc, key, year, nb_path)
            rows += r
            box += b
            draws.append(d)
            cells += c
            gaps += g
            bars.append(br)
    t, bx, ct = pd.DataFrame(rows), pd.DataFrame(box), pd.DataFrame(cells)
    lead = ["city", "city_label", "year", "class", "cell_type", "n_cells"]
    ct = ct[lead + [k for k in ct.columns if k.startswith("share_") and not k.startswith("share_class_")]
            + [k for k in ct.columns if k.startswith("share_class_")] + [k for k in ct.columns if k.startswith("pop_")]]
    log.info("checks (a difference stops the run before writing):")
    for v in t["version"].unique():
        check_sums(t[t["version"] == v], dc["classes"])
    check_cells(ct, t, dc["classes"], args.version)
    if args.no_check_with:
        log.warning("  whole box NOT checked (--no-check-with)")
    else:
        check_box(bx, args.check_with, args.version_label)
        if gaps:
            check_gap_cells(pd.DataFrame(gaps), gap_ref)
    for v, lab in args.extra:
        log.warning("  %s (%s): whole box NOT checked (no earlier numbers; its classes add up, see above)", lab, v)
    for d in draws:
        draw(*d)
    for d in bars:
        draw_cells(*d)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    t.to_csv(args.out_dir / "density_class_summary.csv", index=False)
    ct.to_csv(args.out_dir / "cell_type_shares.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_rows", 200, "display.max_columns", 30):
        cols = ["version_label", "city", "year", "product", "class", "n_blocks", "spearman", "ratio_total", "ratio_p10",
                "ratio_median", "ratio_p90", "n_version_zero", "n_product_zero", "share_above", "share_below"]
        for b in BASES:
            log.info("SUMMARY classes by %s (%s):\n%s", "GHS-POP (main)" if b == "ghs_pop" else
                     "the version's own density (check)", b, t.loc[t["basis"] == b, cols].round(3).to_string(index=False))
        sc = [k for k in ct.columns if k.startswith("share_") and not k.startswith("share_class_")]
        log.info("SUMMARY cell types, share of the box people (%%):\n%s",
                 ct[["city", "year", "class", "cell_type", "n_cells", *sc]].assign(**{k: 100 * ct[k] for k in sc})
                 .round(1).to_string(index=False))
    log.info("wrote %s, %s", args.out_dir / "density_class_summary.csv", args.out_dir / "cell_type_shares.csv")
    log.info("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
