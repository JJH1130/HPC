"""NobuiltYear feature test: v5.6 (Dasy_CONUS_RF_v3_u070) vs v5.6 + nby (Dasy_CONUS_RF_v3_u070_nby) and v5.6 + nby_age
(Dasy_CONUS_RF_v3_u070_nbya) on the same tracts, TEST counties and cells (request 2026-11-04,
docs/handoff/nobuiltyear_feature_request.md; docs/conus_plan.md "NobuiltYear feature test"). No selection rule: both
variants are reported, the user decides; tracts are not used for tuning.

Three parts; the first two read rasters on scratch (cluster job, sbatch/nobuilt_compare.sh), the last only small files in
git (runs locally too). Without the raster flags the CSVs of an earlier run in --out-dir are read again.
  cells  (--dasym-root + --cutout-root)  per version and year, over the cells with a prediction: people on BUI = 0 cells
         (BUI of the year, the cutout's) / all people, and of those the share on cells with NobuiltYear > 0 (cutout
         layer NOBUILT) -> nobuilt_cells.csv
  city   (+ --ext-config + --data-root)  the gap blocks of external_city_meeting.py with its rule unchanged (city_meeting
         gap block of configs/external_grids.yaml: version / GHS-POP < 0.25 and GHS-POP >= 1,000 per km2, 1 km blocks
         inside v5.6's mask), Boston / Denver / Chicago, 1980 / 2010 (GHS-POP starts in 1975; 1910 / 1940 / 1960 none):
         per version, set gap_own (its own gap blocks) and gap_v56 (v5.6's gap blocks, the same blocks for every
         version): blocks, people of the version and of GHS-POP, version / GHS. v5.6's own gap blocks must equal
         results/validation/conus/external/city_maps_meeting/gap_blocks.csv (blocks, people), else the run stops.
         -> nobuilt_city_gaps.csv
  tables tract / county rows as plural_compare.py (same functions): tract MdAPE / MAPE (>= --mape-min people) for all,
         kept / excluded t070, no_gap / gap, the four observed density classes, + areal weighting; TEST counties (the
         same set in every version, checked) before allocation: MdAPE, MAPE, CV RMSE / R2, TEST RMSE / R2, rank of nby /
         nby_age by permutation importance and mean |SHAP|; + the cells and city rows above.

Writes to --out-dir (results/validation/conus/nobuilt/):
  nobuilt_comparison.csv     version, variant, year, level (tract / county / cells / city_gap), set, city, n,
                             counties, mdape, mape, mape_n, d_mdape (vs v5.6), cv_rmse, cv_r2, test_rmse, test_r2, ranks,
                             share (cells: the share named by set; city_gap: version people / GHS-POP people)
  nobuilt_cells.csv          version, variant, year, cells / people on all, BUI = 0, BUI = 0 and NobuiltYear > 0 cells
  nobuilt_city_gaps.csv      city, year, version, variant, set, n_blocks, pop_version, pop_ghs, ratio
  nobuilt_feature_ranks.csv  version, variant, year, feature, permutation / mean |SHAP| value and rank
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import builtcell_compare as bc  # noqa: E402  (feature rank table)
import plural_compare as pc  # noqa: E402  (tract / county rows)

log = logging.getLogger("nobuilt_compare")

YEARS = [1910, 1940, 1960, 1980, 2010]
CITY_YEARS = [1980, 2010]
BASE = "Dasy_CONUS_RF_v3_u070"
VARIANTS = ["nby", "nbya"]  # version = <base>_<variant>
RANK_FEATURES = ("nby", "nby_age")
NOBUILT = "NOBUILT"  # cutout layer layers/NOBUILT/NOBUILT.tif
GAP_CSV = Path("results/validation/conus/external/city_maps_meeting/gap_blocks.csv")
BLOCK_ROWS = 512


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default=BASE, help="v5.6")
    p.add_argument("--variants", nargs="+", default=VARIANTS, help="suffixes: version = <base>_<variant>")
    p.add_argument("--years", type=int, nargs="+", default=YEARS)
    p.add_argument("--city-years", type=int, nargs="+", default=CITY_YEARS)
    p.add_argument("--name", default="conus")
    p.add_argument("--results-root", type=Path, default=Path("results"))
    p.add_argument("--exclusions", type=Path, default=Path("results/hisdac_uncertainty/excluded_counties_t070.csv"))
    p.add_argument("--mape-min", type=float, default=10)
    p.add_argument("--out-dir", type=Path, default=Path("results/validation/conus/nobuilt"))
    p.add_argument("--dasym-root", type=Path, help="<root>/<name>/<version>/predictions/pop_{YEAR}.tif (cells, city)")
    p.add_argument("--cutout-root", type=Path, help="<root>/<name>/layers/{BUI,NOBUILT}/ (cells)")
    p.add_argument("--ext-config", type=Path, help="configs/external_grids.yaml (city)")
    p.add_argument("--data-root", type=Path, help="$DATA_ROOT/raw/external (city: GHS-POP)")
    p.add_argument("--gap-csv", type=Path, default=GAP_CSV, help="v5.6's gap blocks of the meeting maps (city check)")
    return p.parse_args(argv)


# ---------------------------------------------------------------- cells

def cell_sums(pop_path: Path, bui_path: Path, nb_path: Path, block_rows: int = BLOCK_ROWS) -> dict:
    """People and cells over the cells with a prediction (not NoData): all, BUI = 0, BUI = 0 and NobuiltYear > 0.
    The three rasters must share one grid. BUI / NobuiltYear nodata count as 0 (no record)."""
    import rasterio
    from rasterio.windows import Window
    out = {k: 0.0 for k in ("cells", "cells_bui0", "cells_bui0_nb", "pop", "pop_bui0", "pop_bui0_nb", "pop_nb")}
    with rasterio.open(pop_path) as sp, rasterio.open(bui_path) as sb, rasterio.open(nb_path) as sn:
        for s in (sb, sn):
            if (s.height, s.width) != (sp.height, sp.width) or s.transform != sp.transform:
                sys.exit(f"ERROR: {s.name} is not on the grid of {pop_path}")
        for r0 in range(0, sp.height, block_rows):
            w = Window(0, r0, sp.width, min(block_rows, sp.height - r0))
            p = sp.read(1, window=w).astype("float64")
            ok = np.isfinite(p) if sp.nodata is None else (p != sp.nodata) & np.isfinite(p)

            def rd(src):
                a = src.read(1, window=w).astype("float64")
                bad = ~np.isfinite(a) | ((a == src.nodata) if src.nodata is not None else False)
                return np.where(bad, 0.0, a)
            b, n = rd(sb), rd(sn)
            b0 = ok & (b <= 0)
            b0n = b0 & (n > 0)
            out["cells"] += int(ok.sum())
            out["cells_bui0"] += int(b0.sum())
            out["cells_bui0_nb"] += int(b0n.sum())
            out["pop"] += float(p[ok].sum())
            out["pop_bui0"] += float(p[b0].sum())
            out["pop_bui0_nb"] += float(p[b0n].sum())
            out["pop_nb"] += float(p[ok & (n > 0)].sum())
    out["share_bui0"] = out["pop_bui0"] / out["pop"] if out["pop"] else np.nan
    out["share_nb_of_bui0"] = out["pop_bui0_nb"] / out["pop_bui0"] if out["pop_bui0"] else np.nan
    out["share_bui0_nb"] = out["pop_bui0_nb"] / out["pop"] if out["pop"] else np.nan
    return out


def cells_table(args, versions: dict) -> pd.DataFrame:
    cut = args.cutout_root / args.name / "layers"
    nb = cut / NOBUILT / f"{NOBUILT}.tif"
    if not nb.exists():
        sys.exit(f"ERROR: {nb} not found (grid_cutout.sh --layers NOBUILT)")
    rows = []
    for y in args.years:
        bui = cut / "BUI" / f"{y}_BUI.tif"
        for var, v in versions.items():
            pop = args.dasym_root / args.name / v / "predictions" / f"pop_{y}.tif"
            if not pop.exists():
                log.warning("%d %s: %s missing; no cell row", y, v, pop)
                continue
            s = cell_sums(pop, bui, nb)
            rows.append({"version": v, "variant": var, "year": y, **s})
            log.info("  cells %d %-5s: people on BUI = 0 cells %.4f of %.0f | of those on NobuiltYear > 0 cells %.4f",
                     y, var, s["share_bui0"], s["pop"], s["share_nb_of_bui0"])
    return pd.DataFrame(rows)


def cell_rows(cells: pd.DataFrame) -> list[dict]:
    rows = []
    for r in cells.itertuples():
        for s in ("share_bui0", "share_nb_of_bui0", "share_bui0_nb"):
            rows.append({"version": r.version, "variant": r.variant, "year": int(r.year), "level": "cells", "set": s,
                         "n": int(r.cells), "share": float(getattr(r, s))})
    return rows


# ---------------------------------------------------------------- city gap blocks

def city_table(args, versions: dict) -> pd.DataFrame:
    """Gap blocks per city, year and version (the rule of external_city_meeting.py)."""
    import rasterio
    from pyproj import Transformer
    import external_city_maps as ecm
    import external_city_meeting as ecmt
    from external_compare import load_config, resolve
    cfg = load_config(args.ext_config)
    cm, mt = cfg["city_maps"], cfg["city_meeting"]
    gc = mt["gap"]
    prod = gc["product"]
    rows = []
    for year in args.city_years:
        if year not in args.years:
            log.warning("city year %d is not a test year; skipped", year)
            continue
        if year not in {int(k) for k in mt["years"]}:
            log.warning("city year %d is not a city_meeting year; skipped", year)
            continue
        path, note = resolve(args.data_root, cfg["products"][prod], year)
        if path is None:
            sys.exit(f"ERROR: {prod} {year}: {note}")
        for key in mt["cities"]:
            city = cm["cities"][key]
            bpath = args.dasym_root / args.name / args.base / "predictions" / f"pop_{year}.tif"
            with rasterio.open(bpath) as src:
                grid_t, crs = src.transform, src.crs
            cx, cy = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(city["lon"], city["lat"])
            win = ecm.box_window(grid_t, cx, cy, cm["box_km"])
            bpop, mask, bt = ecm.read_box(bpath, win, grid_t)
            bpop = np.where(mask, bpop, np.nan)
            f = int(round(cm.get("block_km", 1) * 1000 / grid_t.a))
            bkm2 = f * f * ecm.CELL_KM2
            g, _ = ecm.to_grid(path, bt, bpop.shape, crs, cm["subpixel_m"])
            gb, vb0, full = ecmt.blocks(g, bpop, mask, f)
            gap0 = ecmt.gap_blocks(vb0, gb, full, bkm2, gc["ratio_max"], gc["min_density"])
            for var, v in versions.items():
                vpath = args.dasym_root / args.name / v / "predictions" / f"pop_{year}.tif"
                if not vpath.exists():
                    log.warning("%s %d %s: %s missing; no city row", key, year, v, vpath)
                    continue
                vpop, vmask, _ = ecm.read_box(vpath, win, grid_t)
                if not np.array_equal(vmask, mask):
                    sys.exit(f"ERROR: {key} {year}: the cells with a prediction of {v} differ from {args.base} "
                             f"({int((vmask != mask).sum())} cells)")
                vb = ecmt.blocks(np.where(mask, vpop, np.nan), bpop, mask, f)[0]
                own = ecmt.gap_blocks(vb, gb, full, bkm2, gc["ratio_max"], gc["min_density"])
                for s, fl in (("gap_own", own), ("gap_v56", gap0)):
                    pv, pg = float(vb[fl].sum()), float(gb[fl].sum())
                    rows.append({"city": key, "year": year, "version": v, "variant": var, "set": s,
                                 "n_blocks": int(fl.sum()), "pop_version": pv, f"pop_{prod}": pg,
                                 "ratio": pv / pg if pg else np.nan})
                log.info("  %-8s %d %-5s: own gap blocks %3d (%s / GHS %.3f) | on v5.6's %3d gap blocks %s / GHS %.3f",
                         key, year, var, rows[-2]["n_blocks"], var, rows[-2]["ratio"], rows[-1]["n_blocks"], var,
                         rows[-1]["ratio"])
    t = pd.DataFrame(rows)
    if len(t):  # v5.6's own gap blocks = the meeting maps' gap table (same rule, same inputs)
        b = t[(t["variant"] == "base") & (t["set"] == "gap_own")].rename(
            columns={"pop_version": "pop_v56"}).assign(group="gap")
        ecmt.check_previous(b, [args.gap_csv], ["city", "year", "group"], ["n_blocks", "pop_v56", f"pop_{prod}"])
        if not Path(args.gap_csv).exists():
            log.warning("no %s: v5.6's gap blocks not checked against the meeting maps", args.gap_csv)
    return t


def city_rows(city: pd.DataFrame) -> list[dict]:
    return [{"version": r.version, "variant": r.variant, "year": int(r.year), "level": "city_gap", "set": r.set,
             "city": r.city, "n": int(r.n_blocks), "share": float(r.ratio)} for r in city.itertuples()]


# ---------------------------------------------------------------- main

def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    if not args.exclusions.exists():
        sys.exit(f"ERROR: {args.exclusions} not found (src/grid/uncertainty_filter.py)")
    excl = set(pd.read_csv(args.exclusions)["GISJOIN"])
    versions = {"base": args.base, **{v: f"{args.base}_{v}" for v in args.variants}}
    log.info("versions %s | years %s | no selection rule (both variants reported; the user decides)", versions,
             args.years)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    if args.dasym_root and args.cutout_root:
        log.info("== cells: people on BUI = 0 cells and on NobuiltYear > 0 among them")
        cells = cells_table(args, versions)
        cells.to_csv(out / "nobuilt_cells.csv", index=False)
    elif (out / "nobuilt_cells.csv").exists():
        log.info("== cells: read again from %s (no --dasym-root / --cutout-root)", out / "nobuilt_cells.csv")
        cells = pd.read_csv(out / "nobuilt_cells.csv")
    else:
        log.warning("== cells: no rasters given and no %s; no cell rows", out / "nobuilt_cells.csv")
        cells = pd.DataFrame()
    if args.dasym_root and args.ext_config and args.data_root:
        log.info("== city gap blocks (rule of external_city_meeting.py)")
        city = city_table(args, versions)
        city.to_csv(out / "nobuilt_city_gaps.csv", index=False)
    elif (out / "nobuilt_city_gaps.csv").exists():
        log.info("== city: read again from %s", out / "nobuilt_city_gaps.csv")
        city = pd.read_csv(out / "nobuilt_city_gaps.csv")
    else:
        log.warning("== city: no rasters / config given and no %s; no city rows", out / "nobuilt_city_gaps.csv")
        city = pd.DataFrame()

    rows = []
    for y in args.years:
        rows += pc.tract_rows(args, y, versions, excl)
        rows += pc.county_rows(args, y, versions, rank_features=RANK_FEATURES)
    if len(cells):
        rows += cell_rows(cells)
    if len(city):
        rows += city_rows(city)
    cmp = pd.DataFrame(rows)
    if cmp.empty or not cmp["level"].isin(["tract", "county"]).any():
        sys.exit("ERROR: no tract / county result files found for any version / year")
    if "city" not in cmp:
        cmp["city"] = np.nan
    cmp.insert(cmp.columns.get_loc("set") + 1, "city", cmp.pop("city"))
    key = ["year", "level", "set", "city"]
    base = cmp.loc[cmp["variant"] == "base", key + ["mdape"]].rename(columns={"mdape": "base_mdape"})
    cmp = cmp.merge(base, on=key, how="left")
    cmp.insert(cmp.columns.get_loc("mape_n") + 1, "d_mdape", cmp["mdape"] - cmp.pop("base_mdape"))
    cmp.to_csv(out / "nobuilt_comparison.csv", index=False)
    ranks = bc.rank_table(args.results_root / "dasymetric" / args.name, versions, args.years)
    ranks.to_csv(out / "nobuilt_feature_ranks.csv", index=False)

    order = ["base"] + list(args.variants)
    with pd.option_context("display.width", 220, "display.max_rows", 500, "display.max_columns", 30):
        tr = cmp[cmp["level"] == "tract"]
        log.info("SUMMARY tract MdAPE (%%) by set, year and variant (areal_weighting = area-proportional):\n%s",
                 tr.pivot_table(index=["set", "year"], columns="variant", values="mdape", sort=False).round(2).to_string())
        log.info("SUMMARY tract MAPE (%%, tracts >= %g people):\n%s", args.mape_min,
                 tr.pivot_table(index=["set", "year"], columns="variant", values="mape", sort=False).round(2).to_string())
        c = cmp[cmp["level"] == "county"]
        cols = [k for k in ("variant", "year", "n", "mdape", "mape", "cv_rmse", "cv_r2", "test_rmse", "test_r2",
                            "nby_perm_rank", "nby_shap_rank", "nby_age_perm_rank", "nby_age_shap_rank", "n_features")
                if k in c]
        log.info("SUMMARY TEST counties (before allocation; same set in every version) + CV / TEST + ranks of nby / "
                 "nby_age (1 = most important):\n%s", c[cols].round(4).to_string(index=False))
        ce = cmp[cmp["level"] == "cells"]
        if len(ce):
            log.info("SUMMARY people on cells (share_bui0 = on BUI = 0 cells / all; share_nb_of_bui0 = of those, on "
                     "NobuiltYear > 0 cells; share_bui0_nb = BUI = 0 and NobuiltYear > 0 / all):\n%s",
                     ce.pivot_table(index=["set", "year"], columns="variant", values="share",
                                    sort=False).reindex(columns=order).round(4).to_string())
        if len(city):
            log.info("SUMMARY city gap blocks (blocks / version people / GHS-POP people per set; gap_v56 = the same "
                     "blocks for every version):\n%s",
                     city.pivot_table(index=["city", "year", "set"], columns="variant",
                                      values=["n_blocks", "ratio"], sort=False).round(3).to_string())
        if len(ranks):
            log.info("SUMMARY feature ranks (permutation / SHAP):\n%s",
                     ranks.pivot_table(index=["year", "feature"], columns="variant", values=["perm_rank", "shap_rank"],
                                       sort=False).to_string())
    log.info("wrote %s", out)
    log.info("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
