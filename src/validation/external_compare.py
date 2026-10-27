"""External gridded population products vs CONUS v5.4 on the same census tracts (docs/conus_plan.md "External
comparison"; request docs/handoff/external_grids_request.md; products and paths in configs/external_grids.yaml,
data registered in docs/data_sources.md).

Three steps (sbatch/external_compare.sh; chain by `bash sbatch/submit_conus.sh external`):

  inventory  (login node, headers only) per product and year: the file the config path finds (or why none), CRS,
             cell size, size, dtype, nodata, bounds -> <out>; the USA rows of the GPWv4.11 country summary (US input
             units) when that document was downloaded. `--available` prints only the products whose files are all
             there (used by the submit script).
  extract    one product, its years: the tracts evaluated for the reference version that year (flag ok in its
             tract_errors_{YEAR}.csv = the same tracts and filter as our tract validation) are reprojected to the
             product's own CRS (vector only: the raster is not reprojected or resampled) and the product's pixel
             population is summed per tract with exactextract (each pixel times the share of it inside the tract).
             Per tract: pop, cells (coverage of valid pixels), cells_all (incl. nodata pixels), cells_poly (tract
             area / pixel area: less coverage = tract partly outside the raster), vmin (lowest pixel value) ->
             <work-dir>/sums/<product>_<year>.csv.
  evaluate   per year and product: the tracts the product covers without nodata (cells_all = cells_poly, nodata
             share <= --max-nodata-share, default 0, no negative pixel) and on that same subset the product, the
             reference version (pop_model of its tract_errors) and areal weighting (pop_baseline): MdAPE, MAPE
             (tracts >= 10 people), p90 APE, total ratio, MdAPE per observed density class (people per km2 of the
             tract's 250 m cells, as tract_validate.py), MdAPE in / outside BUI gap counties, tract count and share of
             the evaluated tracts and their population. Rows `all_tracts` = the reference and areal weighting on all
             evaluated tracts. A product or year without sums is a row with status `missing` (logged, not an error).
             -> <out> + figure (tract MdAPE by year).
"""
from __future__ import annotations

import argparse
import fnmatch
import logging
import multiprocessing as mp
import os
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tract_validate import CELL_KM2, DENSITY_CLASSES, density_label, mdape  # noqa: E402

COVER_TOL = 1e-4  # cells_all >= cells_poly x (1 - tol): the tract lies inside the raster
MAPE_MIN_POP = 10
SUM_COLS = ["GISJOIN", "pop", "cells", "cells_all", "cells_poly", "vmin"]
OUT_COLS = ["year", "product", "label", "method", "status", "input_unit", "input_unit_source", "n_tracts",
            "n_eval", "tract_share", "pop_share", "n_outside", "n_nodata", "mdape", "mape", "p90_ape", "total_ratio"] \
    + [f"mdape_{density_label(lo, hi)}" for lo, hi in DENSITY_CLASSES] + ["mdape_no_gap", "mdape_gap", "n_gap"]

log = logging.getLogger("external_compare")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["inventory", "extract", "evaluate"])
    p.add_argument("--config", type=Path, default=Path("configs/external_grids.yaml"))
    p.add_argument("--data-root", type=Path, required=True, help="$DATA_ROOT/raw/external")
    p.add_argument("--name", default="conus", help="study area name (results/validation/<name>/)")
    p.add_argument("--results-root", type=Path, default=Path("results"))
    p.add_argument("--tract-dir", type=Path, help="folder with tracts_{YEAR}.gpkg (extract)")
    p.add_argument("--work-dir", type=Path, help="tract sums go to <work-dir>/sums/ (extract, evaluate)")
    p.add_argument("--product", help="extract: one product of the config")
    p.add_argument("--products", nargs="+", help="evaluate / inventory: these products only (default all)")
    p.add_argument("--years", type=int, nargs="+", help="these years only (default: each product's years)")
    p.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_ON_NODE", 1)))
    p.add_argument("--chunks-per-worker", type=int, default=8)
    p.add_argument("--max-nodata-share", type=float, default=0.0,
                   help="evaluate: largest share of a tract's pixel coverage that may be nodata (default 0)")
    p.add_argument("--available", action="store_true", help="inventory: print the products with all files, nothing else")
    p.add_argument("--out", type=Path, help="inventory / evaluate CSV")
    p.add_argument("--plot", type=Path, help="evaluate: figure of tract MdAPE by year")
    return p.parse_args(argv)


def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text())
    for name, spec in cfg["products"].items():
        missing = {"label", "path", "years", "input_unit", "input_unit_source"} - set(spec)
        if missing:
            sys.exit(f"ERROR: {path}: product {name} lacks {sorted(missing)}")
    return cfg


# ---------------------------------------------------------------- files

def resolve(data_root: Path, spec: dict, year: int):
    """(path, note): the one file / Esri GRID folder the product's path finds for `year`, or (None, why)."""
    pat = spec["path"].replace("{YEAR}", str(year)).replace("{YY}", f"{year % 100:02d}")
    hits = sorted(data_root.glob(pat))
    if not hits and data_root.exists():  # case-insensitive fallback (Esri GRID names, zip folders)
        low = pat.lower()
        hits = sorted(p for p in data_root.rglob("*")
                      if fnmatch.fnmatch(p.relative_to(data_root).as_posix().lower(), low))
    if spec.get("exclude"):
        hits = [h for h in hits if not re.search(spec["exclude"], h.name)]
    if len(hits) == 1:
        return hits[0], ""
    if not hits:
        return None, f"nothing matches {data_root / pat}"
    return None, f"{len(hits)} matches for {data_root / pat}: " + ", ".join(h.name for h in hits[:6])


def raster_info(path: Path) -> dict:
    import rasterio
    with rasterio.open(path) as src:
        crs = src.crs
        return {"driver": src.driver, "crs": crs.to_string() if crs else "", "geographic": bool(crs and crs.is_geographic),
                "width": src.width, "height": src.height, "res_x": src.res[0], "res_y": src.res[1],
                "dtype": src.dtypes[0], "nodata": src.nodata, "west": src.bounds.left, "south": src.bounds.bottom,
                "east": src.bounds.right, "north": src.bounds.top}


def inventory(args, cfg):
    rows, avail = [], []
    for name, spec in cfg["products"].items():
        if args.products and name not in args.products:
            continue
        ok = True
        for year in spec["years"]:
            if args.years and year not in args.years:
                continue
            path, note = resolve(args.data_root, spec, year)
            row = {"product": name, "year": year, "file": str(path or ""), "note": note}
            if path is None:
                ok = False
            else:
                try:
                    row.update(raster_info(path))
                    row["size_mb"] = round(sum(f.stat().st_size for f in ([path] if path.is_file() else path.rglob("*"))
                                               if f.is_file()) / 1e6, 1)
                except Exception as e:  # noqa: BLE001  (an unreadable file is reported, not fatal here)
                    ok = False
                    row["note"] = f"cannot open: {e}"
            rows.append(row)
        if ok:
            avail.append(name)
    if args.available:
        print(" ".join(avail))
        return
    df = pd.DataFrame(rows)
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 70):
        log.info("inventory (%s):\n%s", args.data_root, df.drop(columns=["file"]).to_string(index=False))
    for r in rows:
        log.info("  %-9s %d %s", r["product"], r["year"], r["file"] or "MISSING: " + r["note"])
    log.info("products with all files: %s", " ".join(avail) or "none")
    gpw_us_units(args.data_root / "docs" / "gpw-v4-rev11-country-level-summary-general-documentation.xlsx")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.out, index=False)
        log.info("wrote %s", args.out)


def gpw_us_units(xlsx: Path):
    """Log the USA rows of the GPWv4.11 country-level summary (input unit level, unit count, census year)."""
    if not xlsx.exists():
        log.info("GPWv4 country summary not downloaded (%s): US input units stay unverified", xlsx)
        return
    sheets = pd.read_excel(xlsx, sheet_name=None, header=None)
    for sheet, df in sheets.items():
        hit = df.apply(lambda r: r.astype(str).str.fullmatch(r"USA|United States( of America)?").any(), axis=1)
        if not hit.any():
            continue
        head = df.iloc[: min(5, len(df))]
        log.info("GPWv4.11 country summary, sheet %r, first rows (headers):\n%s\nUSA rows:\n%s", sheet,
                 head.to_string(), df[hit].to_string())


# ---------------------------------------------------------------- extract

def reference_tracts(args, ref: str, year: int) -> pd.DataFrame:
    path = args.results_root / "validation" / args.name / ref / f"tract_errors_{year}.csv"
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (tract validation of {ref} for {year})")
    te = pd.read_csv(path)
    return te[te["flag"] == "ok"].reset_index(drop=True)


def tract_geoms(tract_dir: Path, year: int, gisjoins) -> "gpd.GeoDataFrame":
    import geopandas as gpd
    t = gpd.read_file(tract_dir / f"tracts_{year}.gpkg", engine="pyogrio", columns=["GISJOIN"])
    t = t[t["GISJOIN"].isin(set(gisjoins))].drop_duplicates("GISJOIN")
    return t.sort_values("GISJOIN").reset_index(drop=True)


_CHUNK = {}  # fork workers read the tracts from here (inherited, not pickled)


def _extract(raster: str, gdf) -> pd.DataFrame:
    from exactextract import exact_extract
    if len(gdf) == 0:
        return pd.DataFrame(columns=["GISJOIN", "pop", "cells", "cells_all", "vmin"])
    return exact_extract(raster, gdf, ["pop=sum", "cells=count", "cells_all=count(default_value=0)", "vmin=min"],
                         include_cols=["GISJOIN"], output="pandas")


def _extract_slice(task):
    raster, lo, hi = task
    return _extract(raster, _CHUNK["gdf"].iloc[lo:hi])


def tract_sums(raster: Path, gdf, workers: int = 1, chunks_per_worker: int = 8) -> pd.DataFrame:
    """Per tract: product pop (pixel x covered share), coverage of valid / all pixels, tract area in pixels, lowest
    pixel value. gdf: GISJOIN + geometry in any CRS; reprojected to the raster's CRS here."""
    import rasterio
    with rasterio.open(raster) as src:
        crs, pix = src.crs, abs(src.transform.a * src.transform.e)
        bounds = src.bounds
    if crs is None:  # e.g. a .bil without .prj: lon / lat if the bounds say so
        if -180.5 <= bounds.left and bounds.right <= 180.5 and -90.5 <= bounds.bottom and bounds.top <= 90.5:
            log.warning("  %s has no CRS; bounds are lon / lat: taking EPSG:4326", raster)
            crs = "EPSG:4326"
        else:
            sys.exit(f"ERROR: {raster} has no CRS")
    g = gdf[["GISJOIN", "geometry"]].to_crs(crs).reset_index(drop=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # area in degrees on a lon / lat raster: compared with pixels in degrees
        cells_poly = g.geometry.area.to_numpy() / pix
    n_chunks = max(1, workers * chunks_per_worker) if workers > 1 else 1
    bounds_i = np.linspace(0, len(g), min(n_chunks, max(len(g), 1)) + 1).astype(int)
    tasks = [(str(raster), lo, hi) for lo, hi in zip(bounds_i[:-1], bounds_i[1:])]
    _CHUNK["gdf"] = g
    if workers > 1 and "fork" in mp.get_all_start_methods():
        with mp.get_context("fork").Pool(workers) as pool:
            parts = pool.map(_extract_slice, tasks, chunksize=1)
    else:
        parts = [_extract_slice(t) for t in tasks]
    _CHUNK.clear()
    out = pd.concat(parts, ignore_index=True)
    if len(out) != len(g) or not (out["GISJOIN"].to_numpy() == g["GISJOIN"].to_numpy()).all():
        sys.exit(f"ERROR: {raster}: exactextract returned {len(out)} rows for {len(g)} tracts / out of order")
    out["cells_poly"] = cells_poly
    return out[SUM_COLS]


def extract(args, cfg):
    spec = cfg["products"].get(args.product)
    if spec is None:
        sys.exit(f"ERROR: product {args.product} not in {args.config} ({', '.join(cfg['products'])})")
    years = [y for y in spec["years"] if not args.years or y in args.years]
    out_dir = args.work_dir / "sums"
    out_dir.mkdir(parents=True, exist_ok=True)
    for year in years:
        path, note = resolve(args.data_root, spec, year)
        if path is None:
            sys.exit(f"ERROR: {args.product} {year}: {note}")
        log.info("===== %s %d: %s | %s", args.product, year, path, raster_info(path))
        te = reference_tracts(args, cfg["reference"], year)
        gdf = tract_geoms(args.tract_dir, year, te["GISJOIN"])
        if len(gdf) != len(te):
            log.warning("  %d evaluated tracts, %d found in tracts_%d.gpkg", len(te), len(gdf), year)
        s = tract_sums(path, gdf, args.workers, args.chunks_per_worker)
        out = out_dir / f"{args.product}_{year}.csv"
        s.to_csv(out, index=False)
        inside = s["cells_all"] >= s["cells_poly"] * (1 - COVER_TOL)
        nd = (s["cells_all"] - s["cells"]) > 1e-9 * s["cells_all"]
        log.info("  %d tracts: %d fully inside the raster, %d with nodata pixels, %d with a negative pixel | product "
                 "pop in the tracts %.0f vs census %.0f | wrote %s", len(s), int(inside.sum()), int(nd.sum()),
                 int((s["vmin"] < 0).sum()), s["pop"].sum(), te["pop_obs"].sum(), out)


# ---------------------------------------------------------------- evaluate

def ape(obs: np.ndarray, pred: np.ndarray) -> np.ndarray:
    pos = obs > 0
    return np.abs(pred[pos] - obs[pos]) / obs[pos] * 100


def subset_metrics(t: pd.DataFrame, pred: np.ndarray) -> dict:
    """Metrics of `pred` against t.pop_obs; t has n_cells and (optionally) gap."""
    obs = t["pop_obs"].to_numpy(float)
    a = ape(obs, pred)
    big = obs >= MAPE_MIN_POP
    m = {"mdape": mdape(obs, pred),
         "mape": float(np.mean(np.abs(pred[big] - obs[big]) / obs[big]) * 100) if big.any() else np.nan,
         "p90_ape": float(np.percentile(a, 90)) if len(a) else np.nan,
         "total_ratio": float(pred.sum() / obs.sum()) if obs.sum() > 0 else np.nan}
    dens = obs / (t["n_cells"].to_numpy(float) * CELL_KM2)
    for lo, hi in DENSITY_CLASSES:
        sel = (dens >= lo) & (dens < (np.inf if hi is None else hi))
        m[f"mdape_{density_label(lo, hi)}"] = mdape(obs[sel], pred[sel])
    if "gap" in t:
        gap = t["gap"].astype(bool).to_numpy()
        m.update({"mdape_no_gap": mdape(obs[~gap], pred[~gap]), "mdape_gap": mdape(obs[gap], pred[gap]),
                  "n_gap": int(gap.sum())})
    return m


def keep_mask(s: pd.DataFrame, max_nodata_share: float):
    """(kept, outside, nodata): tracts fully inside the raster, without (more than the allowed share of) nodata
    pixels and without negative pixels."""
    outside = (s["cells_all"] < s["cells_poly"] * (1 - COVER_TOL)) | (s["cells_all"] <= 0)
    share = (s["cells_all"] - s["cells"]) / s["cells_all"].where(s["cells_all"] > 0)
    nodata = ~outside & ((share > max_nodata_share + 1e-9) | (s["vmin"] < 0))
    return ~outside & ~nodata, outside, nodata


def evaluate_year(year, te, products, cfg, args):
    ref = cfg["reference"]
    n_eval, pop_eval = len(te), te["pop_obs"].sum()
    rows = []

    def row(product, label, method, sub, pred, status="ok", **extra):
        r = {"year": year, "product": product, "label": label, "method": method, "status": status,
             "n_tracts": len(sub), "n_eval": n_eval, "tract_share": len(sub) / n_eval if n_eval else np.nan,
             "pop_share": sub["pop_obs"].sum() / pop_eval if pop_eval else np.nan, **extra}
        if len(sub):
            r.update(subset_metrics(sub, pred))
        rows.append(r)

    row("all_tracts", "all evaluated tracts", ref, te, te["pop_model"].to_numpy(float))
    row("all_tracts", "all evaluated tracts", "areal_weighting", te, te["pop_baseline"].to_numpy(float))
    for name, spec in products.items():
        if year not in spec["years"]:
            continue
        unit = {"input_unit": spec["input_unit"], "input_unit_source": spec["input_unit_source"]}
        path = args.work_dir / "sums" / f"{name}_{year}.csv"
        if not path.exists():
            log.warning("  %-9s %d: no tract sums (%s): skipped (product not downloaded or its extract job failed)",
                        name, year, path)
            row(name, spec["label"], name, te.iloc[:0], np.array([]), status="missing", **unit)
            continue
        s = pd.read_csv(path)
        m = te.merge(s, on="GISJOIN", how="left", validate="one_to_one")
        lost = m["cells_all"].isna()
        m.loc[lost, ["cells", "cells_all", "pop"]] = 0.0  # tract not in the sums (no geometry): outside
        m.loc[lost, "cells_poly"] = 1.0
        kept, outside, nodata = keep_mask(m, args.max_nodata_share)
        sub = m[kept]
        cnt = {"n_outside": int(outside.sum()), "n_nodata": int(nodata.sum())}
        log.info("  %-9s %d: %d of %d tracts (%.1f %% of the population) | left out: %d outside the raster, %d with "
                 "nodata pixels (%.1f %% of the population)", name, year, len(sub), n_eval,
                 100 * sub["pop_obs"].sum() / pop_eval, cnt["n_outside"], cnt["n_nodata"],
                 100 * m.loc[nodata, "pop_obs"].sum() / pop_eval)
        row(name, spec["label"], name, sub, sub["pop"].to_numpy(float), **unit, **cnt)
        row(name, spec["label"], ref, sub, sub["pop_model"].to_numpy(float), **cnt)
        row(name, spec["label"], "areal_weighting", sub, sub["pop_baseline"].to_numpy(float), **cnt)
    return rows


def evaluate(args, cfg):
    products = {k: v for k, v in cfg["products"].items() if not args.products or k in args.products}
    years = sorted({y for s in products.values() for y in s["years"] if not args.years or y in args.years})
    rows = []
    for year in years:
        log.info("===== %d", year)
        rows += evaluate_year(year, reference_tracts(args, cfg["reference"], year), products, cfg, args)
    df = pd.DataFrame(rows).reindex(columns=OUT_COLS)
    out = args.out or args.results_root / "validation" / args.name / "external" / "external_comparison.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    ref = cfg["reference"]
    ok = df[df["status"] == "ok"]
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 40):
        piv = ok.pivot_table(index=["year", "product"], columns="method", values="mdape", sort=False)
        cols = [c for c in piv.columns if c not in (ref, "areal_weighting")] + [ref, "areal_weighting"]
        piv = piv[[c for c in cols if c in piv]]
        piv["product_mdape"] = [ok[(ok["year"] == y) & (ok["product"] == p) & (ok["method"] == p)]["mdape"].max()
                                for y, p in piv.index]
        piv = piv.join(ok[ok["method"] == ref].set_index(["year", "product"])[["n_tracts", "tract_share"]])
        log.info("tract MdAPE (%%) on each product's tracts (%s and areal weighting on the same tracts):\n%s", ref,
                 piv[["product_mdape", ref, "areal_weighting", "n_tracts", "tract_share"]].round(3).to_string())
        ext = ok[ok["method"] == ok["product"]]
        log.info("products: MAPE (tracts >= %d people), p90 APE, total ratio, gap / no_gap, density classes:\n%s",
                 MAPE_MIN_POP, ext[["year", "product", "mape", "p90_ape", "total_ratio", "mdape_no_gap", "mdape_gap"]
                                   + [c for c in OUT_COLS if c.startswith("mdape_dens_")]].round(2).to_string(index=False))
        miss = df[df["status"] == "missing"]
        if len(miss):
            log.warning("missing (skipped): %s", ", ".join(f"{p} {y}" for p, y in zip(miss["product"], miss["year"])))
    log.info("wrote %s", out)
    if args.plot:
        plot_years(df, args.plot, ref, cfg.get("reference_label", ref))


def plot_years(df: pd.DataFrame, path: Path, ref: str, ref_label: str):
    """Tract MdAPE by year: the reference and areal weighting on all evaluated tracts (lines), each product on the
    tracts it covers (markers + lines)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ok = df[df["status"] == "ok"]
    allt = ok[ok["product"] == "all_tracts"].sort_values("year")
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for method, label, color, ls in ((ref, ref_label + ", all evaluated tracts", "#0b0b0b", "-"),
                                     ("areal_weighting", "areal weighting, all evaluated tracts", "#898781", "--")):
        d = allt[allt["method"] == method]
        ax.plot(d["year"], d["mdape"], ls, color=color, lw=2.2, marker="o", ms=5, label=label, zorder=3)
    colors = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
    markers = ["s", "^", "D", "v", "P", "X", "o", "*"]
    ext = ok[(ok["method"] == ok["product"])]
    for i, (name, d) in enumerate(ext.groupby("product", sort=False)):
        d = d.sort_values("year")
        ax.plot(d["year"], d["mdape"], "-", color=colors[i % 8], lw=1.4, marker=markers[i % 8], ms=7,
                label=d["label"].iloc[0])
    ax.set_ylabel("tract MdAPE (%)")
    ax.set_xlabel("census year")
    ax.set_ylim(bottom=0)
    ax.set_xticks(sorted(ok["year"].unique()))
    ax.grid(axis="y", color="#e1e0d9", lw=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title("Tract MdAPE by year: products on the tracts each covers without nodata\n"
                 f"({ref} on each product's tracts: external_comparison.csv)", fontsize=10)
    ax.legend(frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1))
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("wrote %s", path)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.WARNING if args.available else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stderr if args.available else sys.stdout, force=True)  # --available: stdout = names
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    if args.step == "inventory":
        inventory(args, cfg)
    elif args.step == "extract":
        if not (args.product and args.tract_dir and args.work_dir):
            sys.exit("ERROR: extract needs --product, --tract-dir and --work-dir")
        extract(args, cfg)
    else:
        if not args.work_dir:
            sys.exit("ERROR: evaluate needs --work-dir")
        evaluate(args, cfg)
    log.info("DONE")


if __name__ == "__main__":
    main()
