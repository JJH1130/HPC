"""DEGURBA boxes: rural / peri-urban / urban by the EU / UN Degree of Urbanisation, in the city boxes and in new rural and
peri-urban boxes (request docs/handoff/rural_boxes_request.md, user decision 2026-11-21; docs/conus_plan.md "DEGURBA
boxes"; `rural_boxes:` block of configs/external_grids.yaml). Rank and level agreement with GHS-POP / WorldPop, not
accuracy (both use block-level census input in the US).

  select   (once) choose 4 rural + 4 peri-urban boxes, one per Census region and type, from the GHS-SMOD 2010 classes
           of the 2010 counties (rule in the config, fixed before any result) and write them into the config's
           `boxes` (refused while it is filled) + <out-dir>/boxes_selected.csv (county, state, density, candidates,
           SMOD class shares in the box, v5.7 people 1980 / 2010 in the box, share of box cells outside the mask)
  run      the 8 boxes + the city boxes (Boston / Denver / Chicago), 1980 (GHS-POP) / 2010 (GHS-POP, WorldPop), v5.7
           (main) + extra versions (v5.7 + PLURAL pq5) on the same blocks
  status   prints BOXES SET n / BOXES EMPTY (for the submit script)

Boxes, product move to our 250 m cells (population kept), mask (cells with a v5.7 prediction) and 1 km blocks (4 x 4
cells fully inside the mask) are those of external_city_meeting.py / external_city_density.py (their functions).

Block classes, two schemes, both written:
  A (main)  GHS-SMOD R2023A of the year: each 250 m cell gets the code of the SMOD 1 km cell its centre falls in; a
            block gets the most frequent code of its 16 cells (a tie -> the higher, more urban code); urban = 30,
            peri_urban = 21-23, rural = 11-13, excluded = water (10) / nodata (kept as a class so the classes add up).
            A code not in the config's code table stops the run (codes found are logged per box).
  B (check) the stage I rules on v5.7's block density of the year: urban centre = 4-connected blocks >= 1,500 per km2
            with >= 50,000 people, holes filled (`hole_fill: four_sides`: a block whose four side neighbours all belong
            to one centre joins it, one pass; the manual's gap rule could not be read, logged; no edge smoothing);
            urban cluster = 8-connected blocks >= 300 per km2 with >= 5,000 people, minus the centres; the rest rural.
            Computed on the box + margin_km on every side (masked cells = 0 people), then cut to the box.
Per box x year x scheme x version x product x class (+ all): the metrics of external_city_density.class_metrics
(blocks, Spearman, people and their ratio, block-ratio quantiles, zero blocks, x4 / / 4 shares); pooled rows per
box_type (box = all_<type>: the blocks of all boxes of that type together). Cell types (BUI > 0 / BUI = 0 and
NobuiltYear > 0 / no record) per class as external_city_density.cell_type_rows, per box and pooled per box_type.
Totals side by side: our / product people per A class, per B class, over all full blocks and over the whole box.

Checks (a difference stops the run before writing): classes add up to all; cell-type shares of a box add up to 1,
classes to all, cells = 16 x blocks; city boxes: whole-box blocks / people / Spearman of v5.7 = the meeting maps
(meeting_summary_v56_v57.csv, column v5.7).

Outputs (<out-dir>, default results/validation/conus/external/degurba_boxes_v57/): density_class_summary.csv,
cell_type_shares.csv, totals_side_by_side.csv, box_classes.csv, <box>_<year>.png (meeting-map form, new boxes),
<box>_<year>_cell_types.png (scheme A, every box). `--check` only lists the inputs.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import yaml
from pyproj import Transformer
from rasterio.windows import Window

sys.path.insert(0, str(Path(__file__).resolve().parent))
import external_city_density as ecd  # noqa: E402
import external_city_maps as ecm  # noqa: E402
import external_city_meeting as ecmt  # noqa: E402
from external_compare import load_config, resolve  # noqa: E402

log = logging.getLogger("degurba_boxes")
EXT = Path("results/validation/conus/external")
CHECK_WITH = EXT / "city_maps_meeting_v57" / "meeting_summary_v56_v57.csv"
OUR_CRS = "ESRI:102039"
NODATA = -1                                   # SMOD nodata / outside the raster on our cells
CLASSES = ("rural", "peri_urban", "urban")
A_CLASSES = (*CLASSES, "excluded")            # excluded = water (10) / nodata
SCHEMES = {"A": "GHS-SMOD R2023A (main)", "B": "own density, stage I rules (check)"}
TYPES = ("city", "peri_urban", "rural")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["select", "run", "status"])
    p.add_argument("--config", type=Path, default=Path("configs/external_grids.yaml"))
    p.add_argument("--data-root", type=Path, help="$DATA_ROOT/raw/external (products + ghs_smod/)")
    p.add_argument("--dasym-root", type=Path, help="<dasym-root>/<name>/<version>/predictions/pop_{YEAR}.tif")
    p.add_argument("--cutout-root", type=Path, help="<cutout-root>/<name>/layers/BUI/{YEAR}_BUI.tif")
    p.add_argument("--hisdac-dir", type=Path, default=None, help="HISDAC-US V2 folder: FBUY/NobuiltYear.tif")
    p.add_argument("--census-dir", type=Path, help="select: $DATA_ROOT/processed/census_conus (counties_2010.gpkg)")
    p.add_argument("--name", default="conus")
    p.add_argument("--out-dir", type=Path, default=None, help="default results/validation/conus/external/"
                                                              "degurba_boxes_<label>")
    p.add_argument("--check-with", type=Path, default=CHECK_WITH, help="meeting_summary_<a>_<b>.csv (city boxes)")
    p.add_argument("--check", action="store_true", help="list the inputs only; exit 1 if one is missing")
    a = p.parse_args(argv)
    if a.mode != "status":
        for k in ("data_root", "dasym_root") + (("census_dir",) if a.mode == "select" else ("cutout_root",)):
            if getattr(a, k) is None:
                p.error(f"{a.mode} needs --{k.replace('_', '-')}")
    return a


# ---------------------------------------------------------------- scheme A: GHS-SMOD on our cells

def smod_on_cells(path: Path, box_t, shape, dst_crs) -> np.ndarray:
    """SMOD code of the SMOD cell each of our cell centres falls in (int64; nodata / off the raster = NODATA)."""
    h, w = shape
    xs = box_t.c + (np.arange(w) + 0.5) * box_t.a
    ys = box_t.f + (np.arange(h) + 0.5) * box_t.e
    X, Y = np.meshgrid(xs, ys)
    with rasterio.open(path) as src:
        sx, sy = Transformer.from_crs(dst_crs, src.crs, always_xy=True).transform(X.ravel(), Y.ravel())
        c, r = ~src.transform * (np.asarray(sx), np.asarray(sy))
        c, r = np.floor(c).astype(np.int64), np.floor(r).astype(np.int64)
        c0, r0 = int(c.min()), int(r.min())
        win = Window(c0, r0, int(c.max()) - c0 + 1, int(r.max()) - r0 + 1)
        nd = src.nodata
        a = src.read(1, window=win, boundless=True, fill_value=nd if nd is not None else NODATA)
    v = a[r - r0, c - c0].astype(np.int64)
    if nd is not None:
        v[a[r - r0, c - c0] == nd] = NODATA
    return v.reshape(h, w)


def block_majority(codes: np.ndarray, f: int) -> np.ndarray:
    """Most frequent code of each f x f block; a tie -> the higher code (more urban)."""
    h, w = codes.shape
    b = codes.reshape(h // f, f, w // f, f).transpose(0, 2, 1, 3).reshape(h // f, w // f, f * f)
    vals = np.unique(codes)
    counts = np.stack([(b == v).sum(-1) for v in vals], -1)
    return vals[len(vals) - 1 - np.argmax(counts[..., ::-1], axis=-1)]


def scheme_a(block_codes: np.ndarray, mapping: dict) -> np.ndarray:
    """Class index of A_CLASSES per block (3 = excluded: water / nodata / anything not mapped)."""
    out = np.full(block_codes.shape, 3, np.int64)
    for i, name in enumerate(CLASSES):
        out[np.isin(block_codes, list(mapping[name]))] = i
    return out


def check_codes(codes: np.ndarray, table: dict, where: str) -> dict:
    """Counts of the codes found; a code outside the table (and not nodata) stops the run."""
    vals, n = np.unique(codes, return_counts=True)
    bad = [int(v) for v in vals if v != NODATA and int(v) not in table]
    if bad:
        sys.exit(f"ERROR: {where}: SMOD codes {bad} not in the config's code table {sorted(table)}")
    return {int(v): int(k) for v, k in zip(vals, n)}


# ---------------------------------------------------------------- scheme B: stage I rules on our blocks

def _clusters(flag: np.ndarray, pop: np.ndarray, connectivity: int, min_pop: float):
    """(kept flag, labels of the kept clusters (0 elsewhere)) of the connected `flag` blocks with >= min_pop."""
    from scipy import ndimage
    st = ndimage.generate_binary_structure(2, 1 if connectivity == 4 else 2)
    lab, n = ndimage.label(flag, structure=st)
    if n == 0:
        return np.zeros(flag.shape, bool), lab
    s = np.asarray(ndimage.sum(pop, lab, index=np.arange(1, n + 1)))
    keep = np.concatenate([[False], s >= min_pop])
    return keep[lab], np.where(keep[lab], lab, 0)


def fill_four_sides(lab: np.ndarray) -> np.ndarray:
    """Labels after one pass: a 0 block whose four side neighbours carry the same label > 0 gets that label."""
    p = np.pad(lab, 1)
    up, down, left, right = p[:-2, 1:-1], p[2:, 1:-1], p[1:-1, :-2], p[1:-1, 2:]
    hole = (lab == 0) & (up > 0) & (up == down) & (up == left) & (up == right)
    return np.where(hole, up, lab)


def own_classes(pop_blocks: np.ndarray, block_km2: float, rules: dict):
    """(class index of CLASSES per block, info) by the stage I rules on block people."""
    dens = pop_blocks / block_km2
    c, u = rules["centre"], rules["cluster"]
    _, lab = _clusters(dens >= c["min_density"], pop_blocks, c["connectivity"], c["min_pop"])
    if rules.get("hole_fill", "four_sides") != "four_sides":
        sys.exit(f"ERROR: hole_fill {rules['hole_fill']!r}: only four_sides is implemented")
    filled = fill_four_sides(lab)
    uc = filled > 0
    ucl, _ = _clusters(dens >= u["min_density"], pop_blocks, u["connectivity"], u["min_pop"])
    cls = np.where(uc, 2, np.where(ucl, 1, 0))
    return cls, {"n_centres": int(len(np.unique(lab[lab > 0]))), "holes_filled": int((filled != lab).sum())}


def own_classes_box(vpath: Path, win: Window, grid_t, f: int, rules: dict):
    """Scheme B classes of the box blocks, computed on the box + margin (whole blocks) and cut to the box."""
    m = int(round(rules["margin_km"] * 1000 / grid_t.a))
    if m % f:
        sys.exit(f"ERROR: margin of {m} cells is not a multiple of {f}-cell blocks")
    ew = Window(win.col_off - m, win.row_off - m, win.width + 2 * m, win.height + 2 * m)
    a, valid, _ = ecm.read_box(vpath, ew, grid_t)
    pb = ecm.block_sums(np.where(valid, a, 0.0), f)
    cls, info = own_classes(pb, f * f * ecm.CELL_KM2, rules)
    mb = m // f
    return cls[mb:mb + win.height // f, mb:mb + win.width // f], info


# ---------------------------------------------------------------- config

def rb_config(cfg: dict) -> dict:
    rb = cfg.get("rural_boxes")
    if not rb:
        sys.exit("ERROR: no rural_boxes block in the config")
    rb["years"] = {int(y): p for y, p in rb["years"].items()}
    rb["smod"]["codes"] = {int(k): v for k, v in rb["smod"]["codes"].items()}
    rb["boxes"] = rb.get("boxes") or {}
    return rb


def all_boxes(cfg: dict, rb: dict) -> dict:
    """{key: spec with label, box_type, centre (x, y) in our CRS}: the city boxes first, then the chosen boxes."""
    tr = Transformer.from_crs("EPSG:4326", OUR_CRS, always_xy=True)
    out = {}
    for k in rb["cities"]:
        c = cfg["city_maps"]["cities"][k]
        x, y = tr.transform(c["lon"], c["lat"])
        out[k] = {"label": c["label"], "box_type": "city", "x": x, "y": y}
    for k, b in rb["boxes"].items():
        if b.get("crs", OUR_CRS) != OUR_CRS:
            sys.exit(f"ERROR: box {k}: crs {b['crs']} (expected {OUR_CRS})")
        out[k] = {**b}
    return out


def write_boxes(config: Path, boxes: dict, note: str):
    """Replace the `  boxes:` entry (the last of the file) by the chosen boxes; check that yaml reads them back."""
    text = config.read_text()
    i = text.rfind("\n  boxes:")
    if i < 0 or text.rfind("\nrural_boxes:") > i or any(ln and not ln.startswith(" ") and not ln.startswith("#")
                                                         for ln in text[i + 1:].splitlines()[1:]):
        sys.exit(f"ERROR: {config}: `  boxes:` is not the last entry of the rural_boxes block")
    lines = [f"  boxes:   # written by degurba_boxes.py select {note}; do not edit by hand"]
    for k, b in boxes.items():
        lines.append(f"    {k}: " + yaml.safe_dump(b, default_flow_style=True, sort_keys=False, width=10_000).strip())
    config.write_text(text[:i + 1] + "\n".join(lines) + "\n")
    back = yaml.safe_load(config.read_text())["rural_boxes"]["boxes"]
    if back != boxes:
        sys.exit(f"ERROR: {config}: boxes read back differ: {back} vs {boxes}")


# ---------------------------------------------------------------- select

def region_of(state: str, regions: dict):
    return next((r for r, ss in regions.items() if state in ss), None)


def candidate_order(t: pd.DataFrame) -> pd.DataFrame:
    """Candidates ordered: the median (sorted by density then GISJOIN; even count -> lower middle; same density as the
    median -> smaller GISJOIN), then by |density - median|, a tie -> lower density, then GISJOIN."""
    s = t.sort_values(["density", "GISJOIN"]).reset_index(drop=True)
    med = float(s["density"].iloc[(len(s) - 1) // 2])
    s = s.assign(dist=(s["density"] - med).abs()).sort_values(["dist", "density", "GISJOIN"]).reset_index(drop=True)
    return s.assign(median_density=med, n_candidates=len(s), order=np.arange(len(s)))


def county_smod(counties, smod_path: Path, codes: dict):
    """Per county (row order): SMOD cells by code group (centre in the polygon, SMOD grid)."""
    from rasterio import features
    with rasterio.open(smod_path) as src:
        cm = counties.to_crs(src.crs)
        x0, y0, x1, y1 = cm.total_bounds
        inv = ~src.transform
        cs, rs = zip(inv * (x0, y1), inv * (x1, y0))
        c0, r0 = int(np.floor(min(cs))) - 2, int(np.floor(min(rs))) - 2
        win = Window(c0, r0, int(np.ceil(max(cs))) + 2 - c0, int(np.ceil(max(rs))) + 2 - r0)
        nd = src.nodata
        a = src.read(1, window=win, boundless=True, fill_value=nd if nd is not None else NODATA).astype(np.int64)
        wt = src.window_transform(win)
        tags = src.tags()
    if nd is not None:
        a[a == nd] = NODATA
    zone = features.rasterize(((g, i + 1) for i, g in enumerate(cm.geometry)), out_shape=a.shape, transform=wt,
                              fill=0, dtype="int32")
    found = check_codes(a[zone > 0], codes, f"{smod_path} over the counties")
    log.info("  SMOD tags: %s", tags)
    log.info("  SMOD codes in the counties (cells): %s", {f"{k} {codes.get(k, 'nodata')}": v for k, v in found.items()})
    n = len(cm)
    out = {}
    for name, sel in (("n_land", (a >= 11) & (a <= 30)), ("n_cluster", np.isin(a, [21, 22, 23])), ("n_centre", a == 30)):
        out[name] = np.bincount(zone[sel & (zone > 0)], minlength=n + 1)[1:]
    return pd.DataFrame(out)


def box_shares(path_codes: np.ndarray, codes: dict) -> dict:
    vals, n = np.unique(path_codes, return_counts=True)
    tot = n.sum()
    d = {f"smod_share_{c}": 0.0 for c in sorted(codes)}
    d["smod_share_nodata"] = 0.0
    for v, k in zip(vals, n):
        d["smod_share_nodata" if v == NODATA else f"smod_share_{int(v)}"] = k / tot
    return d


def select(args, cfg, rb):
    import geopandas as gpd
    from shapely.geometry import box as sbox
    from shapely.ops import unary_union
    if rb["boxes"]:
        sys.exit(f"ERROR: {args.config}: rural_boxes.boxes is filled already ({list(rb['boxes'])}); the boxes are "
                 "chosen once (remove them by hand only for a deliberate new choice)")
    sel, sm = rb["select"], rb["smod"]
    year = int(sm["select_year"])
    smod_path, note = resolve(args.data_root, sm, year)
    cpath = args.census_dir / sel["counties"]
    vpaths = {y: args.dasym_root / args.name / rb["version"] / "predictions" / f"pop_{y}.tif" for y in rb["years"]}
    miss = ([] if smod_path else [f"SMOD {year}: {note}"]) + ([] if cpath.exists() else [str(cpath)]) + \
        [str(p) for p in vpaths.values() if not p.exists()]
    for x in [f"SMOD {year} {smod_path or note}", f"counties {cpath}", *(f"version {p}" for p in vpaths.values())]:
        log.info("  input %s", x)
    if miss:
        sys.exit(f"ERROR: {len(miss)} inputs missing: {miss}")
    if args.check:
        log.info("CHECK OK: select inputs")
        return 0
    log.info("RULE (fixed 2026-11-21 before any result): rural = no SMOD %d cell of 21-23 / 30 in the county; "
             "peri_urban = a 21-23 cell, no 30 cell; train_status %s; per region the median 2010 density (pop / "
             "area_km2; even -> lower middle; tie -> smaller GISJOIN), else the next by |density - median|; refused "
             "if < %s km from a city / chosen box centre or more than %.1f %% of the box outside the 2010 counties",
             year, sel["train_status"], sel["min_dist_km"], 100 * sel.get("outside_tol", 0.001))
    c = gpd.read_file(cpath)
    if c.crs is None:
        sys.exit(f"ERROR: {cpath} has no CRS")
    c = c.to_crs(OUR_CRS)
    c["state_fips"] = c["GISJOIN"].str[1:3]
    c["region"] = [region_of(s, sel["regions"]) for s in c["state_fips"]]
    c = pd.concat([c.reset_index(drop=True), county_smod(c, smod_path, sm["codes"])], axis=1)
    c["density"] = c["pop"] / c["area_km2"]
    c["type"] = np.where(c["n_centre"] > 0, "urban", np.where(c["n_cluster"] > 0, "peri_urban", "rural"))
    ok = c["status"].isin(sel["train_status"]) & c["region"].notna() & (c["n_land"] > 0) & c["density"].notna()
    log.info("  counties: %d, candidates (train status, a region, a land cell): %d; no land cell: %d", len(c),
             int(ok.sum()), int((c["n_land"] == 0).sum()))
    log.info("  candidates by region x type:\n%s", c[ok].groupby(["region", "type"]).size().unstack(fill_value=0))
    union = unary_union(list(c.geometry))
    with rasterio.open(vpaths[year]) as src:
        grid_t = src.transform
    centres = [(k, b["x"], b["y"]) for k, b in all_boxes(cfg, {**rb, "boxes": {}}).items()]
    tol = float(sel.get("outside_tol", 0.001))
    chosen, rows = {}, []
    for region in sel["regions"]:
        for typ in ("rural", "peri_urban"):
            cand = candidate_order(c[ok & (c["region"] == region) & (c["type"] == typ)])
            if cand.empty:
                sys.exit(f"ERROR: no {typ} candidate in {region}")
            pick = None
            for _, r in cand.iterrows():
                g = c.loc[c["GISJOIN"] == r["GISJOIN"], "geometry"].iloc[0]
                cx, cy = g.centroid.x, g.centroid.y
                win = ecm.box_window(grid_t, cx, cy, rb["box_km"])
                bx0, by1 = grid_t * (win.col_off, win.row_off)
                bx1, by0 = grid_t * (win.col_off + win.width, win.row_off + win.height)
                bpoly = sbox(bx0, by0, bx1, by1)
                near = [(k, np.hypot(cx - x, cy - y) / 1000) for k, x, y in centres]
                near = [(k, d) for k, d in near if d < sel["min_dist_km"]]
                outside = bpoly.difference(union).area / bpoly.area
                why = ([f"{d:.1f} km from {k}" for k, d in near]
                       + ([f"{100 * outside:.2f} % of the box outside the counties"] if outside > tol else []))
                log.info("  %-9s %-10s #%d %s %s, %s: density %.2f (median %.2f, %d candidates) -> %s", region, typ,
                         r["order"], r["GISJOIN"], r["name"], r["state_fips"], r["density"], r["median_density"],
                         r["n_candidates"], "REFUSED: " + "; ".join(why) if why else "CHOSEN")
                if not why:
                    pick = (r, cx, cy, win)
                    break
            if pick is None:
                sys.exit(f"ERROR: every {typ} candidate in {region} refused")
            r, cx, cy, win = pick
            key = f"{typ}_{region.lower()}"
            chosen[key] = {"label": f"{r['name']}, {r['state_fips']} ({typ.replace('_', '-')}, {region})",
                           "box_type": typ, "region": region, "gisjoin": r["GISJOIN"], "county": str(r["name"]),
                           "state_fips": r["state_fips"], "density_2010": round(float(r["density"]), 4),
                           "x": round(float(cx), 3), "y": round(float(cy), 3), "crs": OUR_CRS}
            centres.append((key, cx, cy))
            row = {"box": key, "box_type": typ, "region": region, "GISJOIN": r["GISJOIN"], "county": r["name"],
                   "state_fips": r["state_fips"], "density_2010": r["density"], "median_density": r["median_density"],
                   "n_candidates": r["n_candidates"], "candidate_order": r["order"], "x": cx, "y": cy,
                   "n_smod_land": r["n_land"], "n_smod_cluster": r["n_cluster"], "n_smod_centre": r["n_centre"]}
            bt = rasterio.windows.transform(win, grid_t)
            row.update(box_shares(smod_on_cells(smod_path, bt, (win.height, win.width), OUR_CRS), sm["codes"]))
            for y, p in vpaths.items():
                a, valid, _ = ecm.read_box(p, win, grid_t)
                row[f"pop_{ecmt.tag(rb['version_label'])}_{y}"] = float(a[valid].sum())
                if y == year:
                    row["share_cells_outside_mask"] = float(1 - valid.mean())
            rows.append(row)
    t = pd.DataFrame(rows)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "boxes_selected.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 40):
        log.info("SELECTED:\n%s", t.round(3).to_string(index=False))
    write_boxes(args.config, chosen, f"{date.today().isoformat()} (SMOD {year}, {Path(str(smod_path)).name})")
    log.info("wrote %s and the %d boxes into %s (commit both)", out / "boxes_selected.csv", len(chosen), args.config)
    log.info("SELECT OK")
    return 0


# ---------------------------------------------------------------- run: one box and year

def class_block_rows(v, p, cls, classes, band):
    rows = []
    for i, name in enumerate(classes):
        m = cls == i
        rows.append({"class": name, **ecd.class_metrics(v[m], p[m], band)})
    rows.append({"class": "all", **ecd.class_metrics(v, p, band)})
    return rows


def run_box(args, cfg, rb, key, spec, year, nb_path, smod_path):
    labels = cfg["city_meeting"].get("labels", {})
    band = cfg["city_density"]["ratio_band"]
    vpath = args.dasym_root / args.name / rb["version"] / "predictions" / f"pop_{year}.tif"
    with rasterio.open(vpath) as src:
        grid_t, crs = src.transform, src.crs
    win = ecm.box_window(grid_t, spec["x"], spec["y"], rb["box_km"])
    vpop, mask, bt = ecm.read_box(vpath, win, grid_t)
    vpop = np.where(mask, vpop, np.nan)
    f = int(round(1000 / grid_t.a))
    if vpop.shape[0] % f or vpop.shape[1] % f:
        sys.exit(f"ERROR: box of {vpop.shape} cells is not a multiple of {f}-cell blocks")
    bkm2 = f * f * ecm.CELL_KM2
    vtag = ecmt.tag(rb["version_label"])
    log.info("===== %s (%s) %d: window %s, %d of %d cells in the mask", spec["label"], spec["box_type"], year, win,
             int(mask.sum()), mask.size)
    grids = {}
    for prod in rb["years"][year]:
        path, note = resolve(args.data_root, cfg["products"][prod], year)
        if path is None:
            sys.exit(f"ERROR: {prod} {year}: {note}")
        grids[prod], _ = ecm.to_grid(path, bt, vpop.shape, crs, cfg["city_maps"]["subpixel_m"])
    vb, _, full = ecmt.blocks(vpop, vpop, mask, f)
    vers = {vtag: np.nan_to_num(vpop, nan=0.0)}
    for v, lab in rb.get("extra_versions", {}).items():
        xpop, xmask, _ = ecm.read_box(args.dasym_root / args.name / v / "predictions" / f"pop_{year}.tif", win, grid_t)
        nd = int((xmask != mask).sum())
        if nd:
            log.warning("  %s: mask differs from %s's in %d cells (%.0f of its people outside the main mask left out)",
                        lab, rb["version_label"], nd, float(np.nansum(np.where(xmask & ~mask, xpop, 0.0))))
        vers[ecmt.tag(lab)] = np.where(mask & xmask, xpop, 0.0)
    vlabels = {vtag: (rb["version"], rb["version_label"]),
               **{ecmt.tag(lab): (v, lab) for v, lab in rb.get("extra_versions", {}).items()}}
    # scheme A
    codes = smod_on_cells(smod_path, bt, vpop.shape, crs)
    found = check_codes(codes, rb["smod"]["codes"], f"{spec['label']} {year}")
    log.info("  SMOD %d codes on the box cells: %s", year, found)
    bcode = block_majority(codes, f)
    cls_a = scheme_a(bcode, rb["smod"]["scheme_a"])
    # scheme B
    cls_b, info = own_classes_box(vpath, win, grid_t, f, rb["own_rules"])
    log.info("  scheme B: %d urban centres in the box + margin, %d hole blocks filled", info["n_centres"],
             info["holes_filled"])
    base = {"box": key, "box_label": spec["label"], "box_type": spec["box_type"], "year": year}
    schemes = {"A": (cls_a, A_CLASSES), "B": (cls_b, CLASSES)}
    rows, pool = [], []
    for sch, (cls, classes) in schemes.items():
        c = cls[full]
        for vt, vp in vers.items():
            v = ecm.block_sums(vp, f)[full]
            for prod, g in grids.items():
                p = ecmt.blocks(g, vpop, mask, f)[0][full]
                for r in class_block_rows(v, p, c, classes, band):
                    row = {**base, "scheme": sch, "version": vlabels[vt][0], "version_label": vlabels[vt][1],
                           "product": prod, **r}
                    if r["class"] == "all":
                        row.update(total_pop_box_version=float(vp.sum()), total_pop_box_product=float(g.sum()))
                    rows.append(row)
                pool.append({"box_type": spec["box_type"], "year": year, "scheme": sch, "version": vlabels[vt][0],
                             "version_label": vlabels[vt][1], "product": prod, "v": v, "p": p, "cls": c,
                             "classes": classes, "tot_v": float(vp.sum()), "tot_p": float(g.sum())})
        n = {k: int((c == i).sum()) for i, k in enumerate(classes)}
        log.info("  scheme %s blocks: %s (of %d full blocks)", sch, n, int(full.sum()))
    a_ghs = [r for r in rows if r["scheme"] == "A" and r["version"] == rb["version"] and r["product"] == "ghs_pop"]
    log.info("  A, %s vs GHS-POP: %s", rb["version_label"], " | ".join(
        f"{r['class']} {r['n_blocks']} rho {r['spearman']:.3f} ratio {r['ratio_total']:.3f}" for r in a_ghs))
    # cell types
    bui, bvalid, _ = ecm.read_box(args.cutout_root / args.name / "layers" / "BUI" / f"{year}_BUI.tif", win, grid_t)
    bui = np.where(bvalid, bui, -1.0)
    nb = ecmt.read_on_box(nb_path, bt, vpop.shape, crs)
    ctype = ecd.cell_types(bui, nb)
    up = np.ones((f, f))
    sel = np.kron(full, up).astype(bool)
    pops = {k: np.where(sel, np.nan_to_num(g, nan=0.0), 0.0) for k, g in grids.items()} | \
        {k: np.where(sel, a, 0.0) for k, a in vers.items()}
    crow = []
    for sch, (cls, classes) in schemes.items():
        ccls = np.kron(np.where(full, cls, -1), up).astype(int)
        crow += [{**base, "scheme": sch, **r} for r in ecd.cell_type_rows(pops, ctype, ccls, sel, classes)]
    # whole box (city boxes: checked against the meeting maps)
    s0 = ecm.panel_stats(vpop, mask, np.zeros_like(vpop), vpop, f)
    box = [{"city": key, "year": year, "item": "model", "n_blocks_1km": s0["n_blocks_1km"],
            "total_pop_box": s0["total_pop_box"]}]
    for prod, g in grids.items():
        st = ecm.panel_stats(g, mask, np.zeros_like(vpop), vpop, f)
        box.append({"city": key, "year": year, "item": prod, "n_blocks_1km": st["n_blocks_1km"],
                    "total_pop_box": st["total_pop_box"], "spearman_1km_vs_version": st["spearman_1km_vs_version"]})
    shares = box_shares(codes, rb["smod"]["codes"])
    bc = {**base, **{k: spec.get(k) for k in ("gisjoin", "county", "state_fips", "region", "density_2010")},
          "n_cells": int(mask.size), "share_cells_outside_mask": float(1 - mask.mean()), "n_full_blocks": int(full.sum()),
          **{f"blocks_{s}_{k}": int((cl[full] == i).sum()) for s, (cl, ks) in schemes.items() for i, k in enumerate(ks)},
          **shares, **info}
    # figures
    figs = []
    if spec["box_type"] != "city":
        figs.append(("map", meeting_figure_args(args, cfg, rb, key, spec, year, vpop, mask, grids, full, vb, bkm2, f,
                                                grid_t, labels, bc)))
    cols = [*rb["products"], *vlabels]
    names = {**{p: labels.get(p, cfg["products"][p]["label"]) for p in rb["products"]},
             **{k: lab for k, (_, lab) in vlabels.items()}}
    figs.append(("bars", (args.out_dir / f"{key}_{year}_cell_types.png", spec["label"], year,
                          [r for r in crow if r["scheme"] == "A"], cols, names, {"classes": list(CLASSES)},
                          "GHS-SMOD 1 km block class (DEGURBA)")))
    return rows, pool, crow, box, bc, figs


def meeting_figure_args(args, cfg, rb, key, spec, year, vpop, mask, grids, full, vb, bkm2, f, grid_t, labels, bc):
    """Arguments of external_city_meeting.draw: v5.7 | GHS-POP | WorldPop maps + block scatter plots, no gap blocks."""
    vlab = rb["version_label"]
    maps = [(f"{vlab} (county input)\ntotal {np.nansum(vpop) / 1e3:,.1f}k", vpop)]
    scat = []
    for prod, g in grids.items():
        lab = labels.get(prod, prod)
        pb = ecmt.blocks(g, vpop, mask, f)[0]
        rho = ecm.spearman(pb[full], vb[full])
        maps.append((f"{lab} ({cfg['products'][prod]['input_unit_class']} input)\ntotal {g.sum() / 1e3:,.1f}k", g))
        scat.append((f"{lab} vs {vlab}: rho {rho:.2f}, {int(full.sum())} blocks", vb[full] / bkm2, pb[full] / bkm2,
                     f"{lab}, people per km2 (1 km block)"))
    missing = tuple(f"{labels.get(p, p)}: no {year} grid\n(from {min(cfg['products'][p]['years'])})"
                    for p in rb["products"] if p not in grids)
    text = [f"{spec['label']}", f"{year}, {rb['box_km']:.0f} x {rb['box_km']:.0f} km",
            f"county {spec.get('county')} ({spec.get('gisjoin')})", f"2010 density {spec.get('density_2010')} per km2",
            f"1 km blocks inside our mask: {int(full.sum())}", "",
            "maps: grey = outside our mask (water,", "  no county); white = 0 people", "",
            "blocks by class (A = GHS-SMOD, B = own):"]
    for k in CLASSES:
        text.append(f"  {k:<11} A {bc[f'blocks_A_{k}']:>5}   B {bc[f'blocks_B_{k}']:>5}")
    text.append(f"  {'excluded':<11} A {bc['blocks_A_excluded']:>5}")
    text += ["", "people in the box:"] + [f"  {m[0].split(' (')[0][:14]:<14} {np.nansum(m[1]) / 1e3:8.1f}k"
                                          for m in maps]
    prods = " / ".join(labels.get(p, p) for p in grids)
    title = (f"{spec['label']}, {year}: {vlab} vs {prods} on our 250 m grid ({rb['box_km']:.0f} x "
             f"{rb['box_km']:.0f} km)")
    return (args.out_dir / f"{key}_{year}.png", title, maps, mask, rb["box_km"], f * grid_t.a / 1000, None, full, scat,
            "\n".join(text), missing, vlab)


# ---------------------------------------------------------------- pooled rows, checks, tables

def pooled_rows(pool: list, band: float) -> list:
    """Rows per box_type: the blocks of all boxes of that type together (box = all_<type>)."""
    rows = []
    df = pd.DataFrame(pool)
    for (bt, year, sch, ver, prod), g in df.groupby(["box_type", "year", "scheme", "version", "product"], sort=False):
        v, p, c = (np.concatenate(g[k].to_list()) for k in ("v", "p", "cls"))
        base = {"box": f"all_{bt}", "box_label": f"all {bt} boxes ({len(g)})", "box_type": bt, "year": year,
                "scheme": sch, "version": ver, "version_label": g["version_label"].iloc[0], "product": prod}
        for r in class_block_rows(v, p, c, g["classes"].iloc[0], band):
            row = {**base, **r}
            if r["class"] == "all":
                row.update(total_pop_box_version=float(g["tot_v"].sum()), total_pop_box_product=float(g["tot_p"].sum()))
            rows.append(row)
    return rows


def pooled_cells(ct: pd.DataFrame, boxes: dict) -> pd.DataFrame:
    """Cell-type rows per box_type from the per-box people (shares recomputed from the summed pop_ columns)."""
    pc = [k for k in ct.columns if k.startswith("pop_")]
    out = []
    for (bt, year, sch), g in ct.groupby(["box_type", "year", "scheme"], sort=False):
        s = g.groupby(["class", "cell_type"], sort=False)[["n_cells", *pc]].sum(min_count=1).reset_index()
        tot = s[s["class"] == "all"][pc].sum(min_count=1)
        for _, r in s.iterrows():
            ctot = s[s["class"] == r["class"]][pc].sum(min_count=1)
            row = {"box": f"all_{bt}", "box_label": f"all {bt} boxes ({g['box'].nunique()})", "box_type": bt,
                   "year": year, "scheme": sch, "class": r["class"], "cell_type": r["cell_type"],
                   "n_cells": int(r["n_cells"])}
            for k in pc:
                q = k[4:]
                row[f"share_{q}"] = r[k] / tot[k] if tot[k] > 0 else np.nan
                row[f"share_class_{q}"] = r[k] / ctot[k] if ctot[k] > 0 else np.nan
                row[k] = r[k]
            out.append(row)
    return pd.DataFrame(out)


def check_sums(t: pd.DataFrame):
    keys = ["box", "year", "scheme", "version", "product"]
    a = t[t["class"] == "all"].set_index(keys)
    c = t[t["class"] != "all"].groupby(keys)[["n_blocks", "pop_version", "pop_product"]].sum()
    for col in c.columns:
        if not np.allclose(c[col], a.loc[c.index, col], rtol=1e-9, atol=1e-6):
            sys.exit(f"ERROR: the classes do not add up to all ({col})")
    log.info("  classes add up to all: %d groups (box x year x scheme x version x product; blocks, people)", len(c))


def check_cells(ct: pd.DataFrame, t: pd.DataFrame, version: str, f: int = 4):
    shares = [k for k in ct.columns if k.startswith("share_") and not k.startswith("share_class_")]
    for (box, year, sch), g in ct.groupby(["box", "year", "scheme"]):
        a = g[g["class"] == "all"]
        tot = a[shares].sum(min_count=1).dropna()
        if not np.allclose(tot, 1.0, atol=1e-9):
            sys.exit(f"ERROR: {box} {year} {sch}: cell-type shares of the box do not add up to 1: {tot.to_dict()}")
        cl = g[g["class"] != "all"].groupby("cell_type")[["n_cells", *shares]].sum(min_count=1)
        al = a.set_index("cell_type")[["n_cells", *shares]].loc[cl.index]
        if not np.allclose(cl.to_numpy(float), al.to_numpy(float), atol=1e-9, equal_nan=True):
            sys.exit(f"ERROR: {box} {year} {sch}: cell types of the classes do not add up to all")
        n = g[g["class"] != "all"].groupby("class")["n_cells"].sum()
        b = t[(t["box"] == box) & (t["year"] == year) & (t["scheme"] == sch) & (t["version"] == version)
              & (t["product"] == "ghs_pop")].set_index("class")["n_blocks"]
        if not (n == f * f * b.loc[n.index]).all():
            sys.exit(f"ERROR: {box} {year} {sch}: cells per class != {f * f} x blocks")
    log.info("  cell types add up: %d box-year-schemes (box shares = 1, classes = all, cells = %d x blocks)",
             ct.groupby(["box", "year", "scheme"]).ngroups, f * f)


def totals_side_by_side(t: pd.DataFrame) -> pd.DataFrame:
    """Our / product people per A class, per B class, over all full blocks and over the whole box."""
    keys = ["box", "box_type", "year", "version_label", "product"]
    w = t[t["class"] != "all"].set_index([*keys, "scheme", "class"])["ratio_total"].unstack(["scheme", "class"])
    # (unstack keeps a row whose ratios are all NaN, e.g. a product without people in the box)
    w.columns = [f"ratio_{s}_{c}" for s, c in w.columns]
    a = t[(t["class"] == "all") & (t["scheme"] == "A")].set_index(keys)
    w["ratio_full_blocks"] = a["ratio_total"]
    w["ratio_whole_box"] = a["total_pop_box_version"] / a["total_pop_box_product"]
    order = [f"ratio_{s}_{c}" for s, cs in (("A", A_CLASSES), ("B", CLASSES)) for c in cs]
    w = w[[c for c in order if c in w] + ["ratio_full_blocks", "ratio_whole_box"]].reset_index()
    w["box_type"] = pd.Categorical(w["box_type"], TYPES, ordered=True)
    return w.sort_values(["year", "product", "version_label", "box_type", "box"]).reset_index(drop=True)


# ---------------------------------------------------------------- run

def run(args, cfg, rb):
    nb_path, nb_how = ecd.nobuilt_path(args)
    boxes = all_boxes(cfg, rb)
    if rb["box_km"] != cfg["city_maps"]["box_km"]:
        sys.exit(f"ERROR: rural_boxes.box_km {rb['box_km']} != city_maps.box_km {cfg['city_maps']['box_km']}")
    rb["products"] = list(dict.fromkeys(p for ps in rb["years"].values() for p in ps))
    miss, smod = [], {}
    for year, prods in rb["years"].items():
        for v in [rb["version"], *rb.get("extra_versions", {})]:
            p = args.dasym_root / args.name / v / "predictions" / f"pop_{year}.tif"
            log.info("  input %d version %-30s %s", year, v, p if p.exists() else "MISSING")
            miss += [] if p.exists() else [str(p)]
        p = args.cutout_root / args.name / "layers" / "BUI" / f"{year}_BUI.tif"
        log.info("  input %d BUI %s", year, p if p.exists() else "MISSING")
        miss += [] if p.exists() else [str(p)]
        for prod in prods:
            path, note = resolve(args.data_root, cfg["products"][prod], year)
            log.info("  input %d product %-9s %s", year, prod, path if path is not None else "MISSING: " + note)
            miss += [] if path is not None else [f"{prod} {year}: {note}"]
        smod[year], note = resolve(args.data_root, rb["smod"], year)
        log.info("  input %d SMOD %s", year, smod[year] if smod[year] is not None else "MISSING: " + note)
        miss += [] if smod[year] is not None else [f"SMOD {year}: {note}"]
    log.info("  input NobuiltYear %s", f"{nb_path} ({nb_how})" if nb_path is not None else "MISSING: " + nb_how)
    miss += [] if nb_path is not None else [f"NobuiltYear: {nb_how}"]
    log.info("  input meeting check %s %s", args.check_with, "" if args.check_with.exists() else "MISSING")
    miss += [] if args.check_with.exists() else [str(args.check_with)]
    log.info("  boxes: %d city + %d chosen %s", len(rb["cities"]), len(rb["boxes"]),
             list(rb["boxes"]) if rb["boxes"] else "(none yet: the select job runs first)")
    if miss:
        sys.exit(f"ERROR: {len(miss)} inputs missing: {miss}")
    if args.check:
        log.info("CHECK OK: inputs for %d years; boxes %s", len(rb["years"]), "SET" if rb["boxes"] else "EMPTY")
        return 0
    if not rb["boxes"]:
        sys.exit(f"ERROR: {args.config}: rural_boxes.boxes is empty (run `degurba_boxes.py select` first)")
    log.info("SMOD code table (config, from the GHSL documentation; checked against the codes found): %s",
             rb["smod"]["codes"])
    for year, p in smod.items():
        with rasterio.open(p) as src:
            log.info("  SMOD %d: %s, %s, %d x %d, res %s, nodata %s, dtype %s, tags %s", year, p.name, src.crs,
                     src.width, src.height, src.res, src.nodata, src.dtypes[0], src.tags())
    log.info("RULE A: block = most frequent SMOD code of its 16 cells (tie -> higher code); %s; 10 / nodata -> "
             "excluded", rb["smod"]["scheme_a"])
    o = rb["own_rules"]
    log.info("RULE B: urban centre = %d-connected blocks >= %s per km2, >= %s people; holes: %s (a block whose four side "
             "neighbours all belong to one centre joins it, one pass; the manual's gap rule NOT verified); edge "
             "smoothing: NOT applied; urban cluster = %d-connected blocks >= %s per km2, >= %s people, minus centres; "
             "computed on the box + %s km", o["centre"]["connectivity"], o["centre"]["min_density"],
             o["centre"]["min_pop"], o["hole_fill"], o["cluster"]["connectivity"], o["cluster"]["min_density"],
             o["cluster"]["min_pop"], o["margin_km"])
    band = cfg["city_density"]["ratio_band"]
    rows, pool, cells, bx, bcs, figs = [], [], [], [], [], []
    for year in rb["years"]:
        for key, spec in boxes.items():
            r, pl, c, b, bc, fg = run_box(args, cfg, rb, key, spec, year, nb_path, smod[year])
            rows += r
            pool += pl
            cells += c
            bcs.append(bc)
            figs += fg
            if spec["box_type"] == "city":
                bx += b
    t = pd.DataFrame(rows + pooled_rows(pool, band))
    ct = pd.DataFrame(cells)
    ct = pd.concat([ct, pooled_cells(ct, boxes)], ignore_index=True)
    lead = ["box", "box_label", "box_type", "year", "scheme", "class", "cell_type", "n_cells"]
    ct = ct[lead + [k for k in ct.columns if k.startswith("share_") and not k.startswith("share_class_")]
            + [k for k in ct.columns if k.startswith("share_class_")] + [k for k in ct.columns if k.startswith("pop_")]]
    log.info("checks (a difference stops the run before writing):")
    check_sums(t)
    check_cells(ct[~ct["box"].str.startswith("all_")], t, rb["version"])
    ecd.check_box(pd.DataFrame(bx), args.check_with, rb["version_label"])
    for kind, a in figs:
        (ecmt.draw if kind == "map" else ecd.draw_cells)(*a)
    side = totals_side_by_side(t)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "density_class_summary.csv", index=False)
    ct.to_csv(out / "cell_type_shares.csv", index=False)
    side.to_csv(out / "totals_side_by_side.csv", index=False)
    pd.DataFrame(bcs).to_csv(out / "box_classes.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_rows", 500, "display.max_columns", 40):
        log.info("SUMMARY totals our / product: A classes | B classes | all full blocks | whole box:\n%s",
                 side.round(3).to_string(index=False))
        m = t[(t["version"] == rb["version"]) & t["box"].str.startswith("all_")]
        log.info("SUMMARY per box type (%s; pooled blocks):\n%s", rb["version_label"],
                 m[["box_type", "year", "scheme", "product", "class", "n_blocks", "spearman", "ratio_total",
                    "ratio_median", "share_above", "share_below"]].round(3).to_string(index=False))
        sc = [k for k in ct.columns if k.startswith("share_class_")]
        c = ct[(ct["scheme"] == "A") & ct["box"].str.startswith("all_")]
        log.info("SUMMARY cell types per box type, scheme A (%% of the class's people):\n%s",
                 c[["box_type", "year", "class", "cell_type", "n_cells", *sc]].assign(**{k: 100 * c[k] for k in sc})
                 .round(1).to_string(index=False))
    log.info("wrote %s (4 CSV + %d PNG)", out, len(figs))
    log.info("DONE")
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    rb = rb_config(cfg)
    if args.out_dir is None:
        args.out_dir = EXT / f"degurba_boxes_{ecmt.tag(rb['version_label'])}"
    if args.mode == "status":
        print(f"BOXES SET {len(rb['boxes'])}" if rb["boxes"] else "BOXES EMPTY")
        return 0
    return select(args, cfg, rb) if args.mode == "select" else run(args, cfg, rb)


if __name__ == "__main__":
    sys.exit(main())
