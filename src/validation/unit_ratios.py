"""Unit ratios: people per building record, per built cell and records per person by county, county class, region and
year (request docs/handoff/unit_ratios_request.md; Stefan 2026-11-25 points 4 + 6, docs/open_items.md; docs/conus_plan.md
"Unit ratios"). Descriptive only: no model change, no selection, no interpretation in the tables.

  local   (tracked files only, no cluster) every census year 1900-2020: per county census pop (v5.7 county features),
          BUPR_year (dated records built <= year, county_record_uncertainty.csv), ratios pop / BUPR_year (people per
          dated record), pop / (BUPR_year + NobuiltYear) (lower bound: every undated record assumed to exist), records
          per capita, people per built cell where the tracked cap-transfer table has the built cells (1940 / 1960 /
          1980 / 2010, v5.7 cells); summaries by year x county class / region; flags outside the 1-99 % range of the
          county's class and year -> county_ratios.csv, ratio_summary.csv, ratio_flags.csv, ratio_flag_summary.csv,
          ratio_by_year.png.
  job     (one job, v5.7 rasters) 1940 / 1960 / 1980 / 2010: per county the people v5.7 puts on built cells (BUI_year >
          0) per BUPR record on those cells and per built cell, on undated cells (BUI = 0, NobuiltYear > 0) per
          NobuiltYear record and per cell; next to the county's tract MdAPE (v5.7 tract_errors_<year>.csv, counties with
          >= min_tracts evaluated tracts): Spearman of |log(ratio / class median)| vs tract MdAPE by class ->
          allocated_ratios.csv, ratio_vs_tract.csv, ratio_vs_tract.png. `--check` = inputs only.

County class = the fixed DEGURBA level 1 labels of county_missed_1980.csv (1980 GHS-POP / GHS-SMOD) for every year
(column county_class_1980; counties without a label = "none"). Region = Census region by state FIPS
(rural_boxes.select.regions). Reference: US average population per household (Census Bureau HH-6,
configs/household_size_hh6.csv; 1940 census, 1950-2020 CPS; 1900-1930 empty: not in HH-6).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import Window
from rasterio.windows import transform as win_transform

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "dasymetric"))
import external_city_density as ecd  # noqa: E402
import external_city_maps as ecm  # noqa: E402
import external_city_meeting as ecmt  # noqa: E402
import missed_cells as mcm  # noqa: E402
import tract_validate as tv  # noqa: E402
from external_compare import load_config  # noqa: E402

log = logging.getLogger("unit_ratios")
OUT = Path("results/validation/conus/unit_ratios")
CLASSES = ("city", "town_suburb", "rural")
MEASURES = {   # measure -> (numerator, denominator) columns of county_ratios.csv
    "ratio_dated": ("pop", "bupr"),
    "ratio_lower": ("pop", "records_all"),
    "records_per_capita": ("bupr", "pop"),
    "pop_per_built_cell": ("pop", "n_cells_built"),
}
FLAG_MEASURES = ("ratio_dated", "ratio_lower")
ALLOC = {      # allocated measure -> (numerator, denominator) columns of allocated_ratios.csv
    "alloc_pop_per_record_built": ("pop_built", "bupr_built"),
    "alloc_pop_per_built_cell": ("pop_built", "n_cells_built"),
    "alloc_pop_per_record_undated": ("pop_undated", "nobuilt_undated"),
    "alloc_pop_per_undated_cell": ("pop_undated", "n_cells_undated"),
}
GROUPS = mcm.GROUPS
NT = mcm.NT
_SHARED: dict = {}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["local", "job"])
    p.add_argument("--config", type=Path, default=Path("configs/external_grids.yaml"))
    p.add_argument("--out-dir", type=Path, default=OUT)
    p.add_argument("--dasym-root", type=Path, help="job: <root>/<name>/<version>/predictions/pop_{YEAR}.tif")
    p.add_argument("--cutout-root", type=Path, help="job: <root>/<name>/{zones,layers}")
    p.add_argument("--hisdac-dir", type=Path, default=None, help="job: HISDAC-US V2 folder: FBUY/NobuiltYear.tif")
    p.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_ON_NODE", "1")))
    p.add_argument("--block-rows", type=int, default=None, help="override the model config's block_rows (tests)")
    p.add_argument("--check", action="store_true", help="job: list the inputs only; exit 1 if one is missing")
    return p.parse_args(argv)


def ur_config(cfg: dict) -> dict:
    u = cfg.get("unit_ratios")
    if not u:
        sys.exit("ERROR: no unit_ratios block in the config")
    for k in ("years", "county_features", "bupr", "county_class", "exclusions", "built_cells", "household",
              "flag_quantiles", "job_years", "tract_errors", "min_tracts", "model_config", "version"):
        if k not in u:
            sys.exit(f"ERROR: unit_ratios.{k} missing")
    u["years"] = sorted(int(y) for y in u["years"])
    u["job_years"] = sorted(int(y) for y in u["job_years"])
    q = [float(x) for x in u["flag_quantiles"]]
    if len(q) != 2 or not 0 <= q[0] < q[1] <= 1:
        sys.exit(f"ERROR: unit_ratios.flag_quantiles must be [low, high] within 0-1: {q}")
    u["flag_quantiles"] = q
    return u


def ypath(template, year: int) -> Path:
    return Path(str(template).replace("{YEAR}", str(year)))


def regions_of(cfg: dict) -> dict:
    """state FIPS -> Census region (rural_boxes.select.regions)."""
    reg = (cfg.get("rural_boxes") or {}).get("select", {}).get("regions") or {}
    if not reg:
        sys.exit("ERROR: rural_boxes.select.regions missing (Census regions by state FIPS)")
    return {str(f).zfill(2): r for r, fs in reg.items() for f in fs}


def safe_ratio(a, b) -> np.ndarray:
    a, b = np.asarray(a, float), np.asarray(b, float)
    return np.divide(a, b, out=np.full(len(a), np.nan), where=(b > 0) & np.isfinite(b) & np.isfinite(a))


# ---------------------------------------------------------------- part A

def county_ratios(cfs: dict, bupr: pd.DataFrame, cls: dict, excl: set, built: pd.DataFrame | None,
                  regions: dict) -> pd.DataFrame:
    """One row per county and year (the counties of the year's county features)."""
    need = {"GISJOIN", "nobuilt", "ratio_A_nby"}
    if not need <= set(bupr.columns) or bupr["GISJOIN"].duplicated().any():
        sys.exit(f"ERROR: bupr table: needs one row per GISJOIN with {sorted(need)} and bupr_<year>")
    rows = []
    for y, cf in sorted(cfs.items()):
        col = f"bupr_{y}"
        if col not in bupr.columns:
            sys.exit(f"ERROR: bupr table has no {col}")
        d = cf[["GISJOIN", "state", "name", "pop"]].copy()
        d.insert(0, "year", y)
        d = d.merge(bupr[["GISJOIN", col, "nobuilt", "ratio_A_nby"]].rename(columns={col: "bupr"}), on="GISJOIN",
                    how="left")
        if d["bupr"].isna().any():
            miss = d.loc[d["bupr"].isna(), "GISJOIN"].tolist()
            sys.exit(f"ERROR: bupr table: {len(miss)} counties of {y} missing: {miss[:20]}")
        d["region"] = d["GISJOIN"].str[1:3].map(regions).fillna("none")
        d["county_class_1980"] = d["GISJOIN"].map(cls).fillna("none")
        d["excluded_t070"] = d["GISJOIN"].isin(excl)
        d["records_all"] = d["bupr"] + d["nobuilt"]
        d["n_cells_built"] = np.nan
        if built is not None:
            b = built[built["year"] == y].set_index("GISJOIN")["n_cells_built"]
            if len(b):
                d["n_cells_built"] = d["GISJOIN"].map(b).to_numpy(float)
        for m, (a, b) in MEASURES.items():
            d[m] = safe_ratio(d[a], d[b])
        rows.append(d)
    cols = ["year", "GISJOIN", "state", "name", "region", "county_class_1980", "excluded_t070", "ratio_A_nby", "pop",
            "bupr", "nobuilt", "records_all", "n_cells_built", *MEASURES]
    return pd.concat(rows, ignore_index=True)[cols]


def summary(cr: pd.DataFrame, hh: dict) -> pd.DataFrame:
    """year x group (all / county class / region) x measure: n, median, p10, p90, pooled (sum num / sum den over the
    counties with a finite ratio)."""
    rows = []
    for y, dy in cr.groupby("year"):
        groups = [("all", "all", dy)]
        groups += [("county_class_1980", c, dy[dy["county_class_1980"] == c]) for c in (*CLASSES, "none")]
        groups += [("region", r, g) for r, g in dy.groupby("region")]
        for gtype, g, d in groups:
            for m, (a, b) in MEASURES.items():
                v = d[m].to_numpy(float)
                ok = np.isfinite(v)
                r = {"year": y, "group_type": gtype, "group": g, "measure": m, "n_counties": len(d),
                     "n": int(ok.sum()), "n_no_ratio": int((~ok).sum())}
                if ok.any():
                    q = np.quantile(v[ok], [0.1, 0.5, 0.9])
                    den = d[b].to_numpy(float)[ok].sum()
                    r.update(p10=q[0], median=q[1], p90=q[2],
                             pooled=float(d[a].to_numpy(float)[ok].sum() / den) if den > 0 else np.nan)
                else:
                    r.update(p10=np.nan, median=np.nan, p90=np.nan, pooled=np.nan)
                r["avg_pop_per_household_us"] = hh.get(y, np.nan)
                rows.append(r)
    t = pd.DataFrame(rows)
    t.insert(3, "county_class_note", "fixed 1980 GHS labels (county_missed_1980.csv)")
    return t


def flags(cr: pd.DataFrame, q: list) -> pd.DataFrame:
    """Counties outside the q[0]-q[1] quantile range of their class and year (per flag measure); a county with people
    but no denominator (no dated record) -> side no_records."""
    rows = []
    for (y, c), d in cr.groupby(["year", "county_class_1980"]):
        for m in FLAG_MEASURES:
            v = d[m].to_numpy(float)
            ok = np.isfinite(v)
            lo, hi = (np.quantile(v[ok], q) if ok.sum() else (np.nan, np.nan))
            side = np.where(~ok & (d["pop"].to_numpy(float) > 0), "no_records",
                            np.where(ok & (v < lo), "low", np.where(ok & (v > hi), "high", "")))
            f = d[side != ""].copy()
            if f.empty:
                continue
            f["measure"], f["value"], f["side"] = m, f[m], side[side != ""]
            f["q_low"], f["q_high"], f["n_in_group"] = lo, hi, len(d)
            rows.append(f)
    cols = ["year", "measure", "county_class_1980", "GISJOIN", "state", "name", "value", "side", "q_low", "q_high",
            "n_in_group", "pop", "bupr", "nobuilt", "ratio_A_nby", "excluded_t070"]
    return pd.concat(rows, ignore_index=True)[cols] if rows else pd.DataFrame(columns=cols)


def flag_summary(cr: pd.DataFrame, fl: pd.DataFrame) -> pd.DataFrame:
    """Per measure, year and side: flagged counties, their share excluded at t070 and median ratio_A_nby, next to the
    same numbers over all counties of the year."""
    rows = []
    for (m, y), f in fl.groupby(["measure", "year"]):
        a = cr[cr["year"] == y]
        base = {"measure": m, "year": y, "n_all": len(a), "excluded_share_all": float(a["excluded_t070"].mean()),
                "ratio_A_nby_median_all": float(a["ratio_A_nby"].median())}
        for side in ("low", "high", "no_records"):
            s = f[f["side"] == side]
            rows.append({**base, "side": side, "n_flagged": len(s),
                         "excluded_share_flagged": float(s["excluded_t070"].mean()) if len(s) else np.nan,
                         "ratio_A_nby_median_flagged": float(s["ratio_A_nby"].median()) if len(s) else np.nan})
    return pd.DataFrame(rows)


def draw_by_year(path: Path, sm: pd.DataFrame):
    plots = ecm._plots()
    plt = plots.plt
    ms = list(FLAG_MEASURES)
    titles = {"ratio_dated": "people per dated building record (pop / BUPR_year)",
              "ratio_lower": "people per record, all undated records counted (pop / (BUPR_year + NobuiltYear))"}
    fig = plt.figure(figsize=(13.0, 5.0), dpi=150, layout="constrained")
    axes = fig.subplots(1, len(ms), sharey=True)
    groups = ["all", *CLASSES]
    for ax, m in zip(axes, ms):
        for i, g in enumerate(groups):
            d = sm[(sm["measure"] == m) & (sm["group"] == g)
                   & sm["group_type"].isin(["all", "county_class_1980"])].sort_values("year")
            col = plots.MUTED if g == "all" else plots.SERIES[(i - 1) % len(plots.SERIES)]
            ax.plot(d["year"], d["pooled"], color=col, lw=2.0, marker="o", ms=3.5, label=f"{g.replace('_', ' / ')}: pooled")
            ax.plot(d["year"], d["median"], color=col, lw=1.2, ls="--", label=f"{g.replace('_', ' / ')}: county median")
        hh = sm[(sm["measure"] == m) & (sm["group"] == "all")].sort_values("year")
        hh = hh[hh["avg_pop_per_household_us"].notna()]
        if len(hh):
            ax.plot(hh["year"], hh["avg_pop_per_household_us"], color=plots.INK, lw=1.4, ls=":", marker="s", ms=3,
                    label="US people per household (HH-6)")
        ax.set_yscale("log")
        ax.set_title(titles[m], fontsize=9, color=plots.INK)
        ax.set_xlabel("census year", fontsize=8, color=plots.INK)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(color=plots.GRID, lw=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(labelsize=7.5, colors=plots.INK)
    axes[0].set_ylabel("people per record (log scale)", fontsize=8, color=plots.INK)
    h, lab = axes[0].get_legend_handles_labels()
    fig.legend(h, lab, loc="outside lower center", ncol=5, fontsize=7.5, frameon=False)
    fig.suptitle("Census people per HISDAC building record by county class (fixed 1980 DEGURBA labels); pooled = sum "
                 "of people / sum of records", fontsize=9.5, color=plots.INK)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    log.info("  wrote %s", path)


def read_tables(cfg: dict, u: dict) -> dict:
    tracked = {"bupr": Path(u["bupr"]), "county_class": Path(u["county_class"]), "exclusions": Path(u["exclusions"]),
               "household": Path(u["household"])}
    miss = [f"{k} {v}" for k, v in tracked.items() if not v.exists()]
    for k, v in tracked.items():
        log.info("  input %-15s %s%s", k, v, "" if v.exists() else "  MISSING")
    if miss:
        sys.exit(f"ERROR: inputs missing: {miss}")
    cls = pd.read_csv(tracked["county_class"])
    hh = pd.read_csv(tracked["household"], comment="#")
    return {"bupr": pd.read_csv(tracked["bupr"]), "cls": dict(zip(cls["GISJOIN"], cls["county_class"])),
            "excl": set(pd.read_csv(tracked["exclusions"])["GISJOIN"]),
            "hh": dict(zip(hh["year"].astype(int), hh["avg_pop_per_household"].astype(float))),
            "regions": regions_of(cfg)}


def run_local(args, cfg, u) -> int:
    t = read_tables(cfg, u)
    cfs = {}
    for y in u["years"]:
        p = ypath(u["county_features"], y)
        if not p.exists():
            sys.exit(f"ERROR: {p} not found")
        f = pd.read_csv(p)
        cfs[y] = f[f["year"] == y] if "year" in f else f
    bp = Path(u["built_cells"])
    built = None
    if bp.exists():
        b = pd.read_csv(bp)
        built = b[b["method"] == "v57"][["year", "GISJOIN", "n_cells_built"]]
        log.info("  built cells per county from %s (method v57 rows = v5.7 cells, BUI_year > 0): years %s", bp,
                 sorted(built["year"].unique().tolist()))
    else:
        log.info("  %s not found: no people per built cell in part A", bp)
    log.info("RULE ratios per county and year: ratio_dated = pop / BUPR_year, ratio_lower = pop / (BUPR_year + "
             "NobuiltYear), records_per_capita = BUPR_year / pop, pop_per_built_cell = pop / built cells (v5.7 cells); "
             "a zero denominator -> no ratio (counted); pooled = sum numerator / sum denominator over the counties with "
             "a ratio")
    log.info("RULE county class = fixed 1980 GHS labels of %s for every year; flags outside the %s quantiles of the "
             "county's class and year (+ people without a dated record)", u["county_class"], u["flag_quantiles"])
    cr = county_ratios(cfs, t["bupr"], t["cls"], t["excl"], built, t["regions"])
    sm = summary(cr, t["hh"])
    fl = flags(cr, u["flag_quantiles"])
    fs = flag_summary(cr, fl)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    cr.to_csv(out / "county_ratios.csv", index=False)
    sm.to_csv(out / "ratio_summary.csv", index=False)
    fl.to_csv(out / "ratio_flags.csv", index=False)
    fs.to_csv(out / "ratio_flag_summary.csv", index=False)
    draw_by_year(out / "ratio_by_year.png", sm)
    with pd.option_context("display.width", 250, "display.max_rows", 400, "display.max_columns", 30):
        a = sm[sm["group_type"].isin(["all", "county_class_1980"])]
        for m in MEASURES:
            log.info("SUMMARY %s (pooled / median) by year and class:\n%s", m,
                     a[a["measure"] == m].pivot_table(index="year", columns="group", values=["pooled", "median"])
                     .round(3).to_string())
        log.info("SUMMARY no ratio (zero denominator) per year: %s",
                 cr.groupby("year")["ratio_dated"].apply(lambda s: int(s.isna().sum())).to_dict())
        log.info("SUMMARY flags (share excluded at t070 / median ratio_A_nby, flagged vs all):\n%s",
                 fs.round(3).to_string(index=False))
    log.info("wrote %s (4 CSV + 1 PNG): %d county-years, %d flags", out, len(cr), len(fl))
    log.info("DONE")
    return 0


# ---------------------------------------------------------------- part B

def strip_work(task):
    try:
        return _strip_work(*task)
    except BaseException as e:   # sys.exit in a pool worker would hang the pool
        raise RuntimeError(f"strip {task[0]}-{task[1]}: {type(e).__name__}: {e}") from None


def _strip_work(r0: int, r1: int, ctx: dict) -> dict:
    gt, crs, W, n = ctx["grid_t"], ctx["crs"], ctx["width"], ctx["n_counties"]
    h = r1 - r0
    st = win_transform(Window(0, r0, W, h), gt)
    vm, mask = mcm.read_rows(ctx["v57"], r0, r1, gt, W)
    with rasterio.open(ctx["zones"]) as src:
        zones = src.read(1, window=Window(0, r0, W, h)).astype(np.int64)
    ci = ctx["lut"][zones]
    m = mask & (ci >= 0)
    v57 = np.where(mask, vm, 0.0)
    bui, bvalid = mcm.read_rows(ctx["bui"], r0, r1, gt, W)
    bupr, rvalid = mcm.read_rows(ctx["bupr"], r0, r1, gt, W)
    info = {"mask_cells_no_county": int((mask & (ci < 0)).sum()), "bui_nodata_in_mask": int((m & ~bvalid).sum()),
            "bupr_nodata_in_mask": int((m & ~rvalid).sum())}
    bui = np.where(bvalid, bui, -1.0)
    bupr = np.where(rvalid, bupr, 0.0)
    nb = ecmt.read_on_box(ctx["nobuilt"], st, (h, W), crs)
    ctype = ecd.cell_types(bui, nb)
    key = (ci * NT + ctype)[m]
    L = n * NT
    acc = {"cells": np.bincount(key, minlength=L).astype(np.int64), "pop": np.bincount(key, weights=v57[m], minlength=L),
           "bupr": np.bincount(key, weights=bupr[m], minlength=L), "nobuilt": np.bincount(key, weights=nb[m], minlength=L)}
    return {"rows": (r0, r1), "acc": acc, "info": info}


def run_strips(ctx: dict, rows: list, workers: int):
    tasks = [(r.start, r.stop, ctx) for r in rows]
    if workers <= 1:
        yield from map(strip_work, tasks)
        return
    import multiprocessing as mp
    with mp.get_context("fork").Pool(workers) as pool:
        yield from pool.imap(strip_work, tasks)


def county_tract_mdape(te: pd.DataFrame) -> pd.DataFrame:
    """Per county (zone_gisjoin of the evaluated tracts): number of evaluated tracts and their MdAPE (tract_validate)."""
    ok = te[te["flag"] == "ok"]
    rows = []
    for gj, d in ok.groupby("zone_gisjoin"):
        rows.append({"GISJOIN": gj, "n_tracts": len(d),
                     "tract_mdape": tv.mdape(d["pop_obs"].to_numpy(float), d["pop_model"].to_numpy(float))})
    return pd.DataFrame(rows, columns=["GISJOIN", "n_tracts", "tract_mdape"])


def ratio_vs_tract(al: pd.DataFrame, min_tracts: int) -> pd.DataFrame:
    """Per year, measure and class (+ all): Spearman of |log(ratio / class median)| vs county tract MdAPE over the
    counties with >= min_tracts evaluated tracts; the class median over all counties of the class and year with a
    ratio. Also the median MdAPE above / below the median deviation."""
    from scipy.stats import spearmanr
    rows = []
    for y, dy in al.groupby("year"):
        for m in ALLOC:
            med = dy.groupby("county_class_1980")[m].median()
            dev = np.abs(np.log(dy[m] / dy["county_class_1980"].map(med)))
            sel_t = (dy["n_tracts"].fillna(0) >= min_tracts) & dy["tract_mdape"].notna() & np.isfinite(dev)
            for c in ("all", *CLASSES):
                s = sel_t & ((dy["county_class_1980"] == c) if c != "all" else True)
                x, z = dev[s].to_numpy(float), dy.loc[s, "tract_mdape"].to_numpy(float)
                r = {"year": y, "measure": m, "county_class_1980": c, "n_counties": int(s.sum()),
                     "class_median_ratio": float(med.get(c, np.nan)) if c != "all" else np.nan}
                if len(x) >= 3 and np.ptp(x) > 0 and np.ptp(z) > 0:
                    rho, pv = spearmanr(x, z)
                    hi = x > np.median(x)
                    r.update(spearman=float(rho), p_value=float(pv),
                             mdape_median_dev_above=float(np.median(z[hi])) if hi.any() else np.nan,
                             mdape_median_dev_below=float(np.median(z[~hi])) if (~hi).any() else np.nan)
                else:
                    r.update(spearman=np.nan, p_value=np.nan, mdape_median_dev_above=np.nan,
                             mdape_median_dev_below=np.nan)
                rows.append(r)
    t = pd.DataFrame(rows)
    t.insert(3, "county_class_note", "fixed 1980 GHS labels")
    return t


def draw_vs_tract(path: Path, al: pd.DataFrame, years: list, min_tracts: int):
    plots = ecm._plots()
    plt = plots.plt
    m = "alloc_pop_per_record_built"
    fig = plt.figure(figsize=(4.0 * len(years), 4.4), dpi=150, layout="constrained")
    axes = np.atleast_1d(fig.subplots(1, len(years), sharey=True))
    for ax, y in zip(axes, years):
        d = al[(al["year"] == y) & (al["n_tracts"].fillna(0) >= min_tracts)]
        med = al[al["year"] == y].groupby("county_class_1980")[m].median()
        for i, c in enumerate(CLASSES):
            e = d[d["county_class_1980"] == c]
            dev = np.abs(np.log(e[m] / med.get(c, np.nan)))
            ax.scatter(dev, e["tract_mdape"], s=9, alpha=0.6, color=plots.SERIES[i % len(plots.SERIES)],
                       label=c.replace("_", " / "), linewidths=0)
        ax.set_title(f"{y}: {len(d)} counties with >= {min_tracts} tracts", fontsize=9, color=plots.INK)
        ax.set_xlabel("|log(people per dated record on built cells / class median)|", fontsize=7.5, color=plots.INK)
        ax.set_yscale("log")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(color=plots.GRID, lw=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(labelsize=7.5, colors=plots.INK)
    axes[0].set_ylabel("county tract MdAPE, % (log scale)", fontsize=8, color=plots.INK)
    h, lab = axes[0].get_legend_handles_labels()
    fig.legend(h, lab, loc="outside lower center", ncol=3, fontsize=8, frameon=False)
    fig.suptitle("v5.7: people per dated record on built cells (as allocated) vs county tract error; classes = fixed "
                 "1980 DEGURBA labels", fontsize=9.5, color=plots.INK)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    log.info("  wrote %s", path)


def run_job(args, cfg, u) -> int:
    import common
    t_start = time.time()
    model = mcm.model_settings(Path(u["model_config"]))
    if model["version"] != u["version"]:
        sys.exit(f"ERROR: {u['model_config']} is {model['version']}, unit_ratios.version is {u['version']}")
    args.name = model["name"]
    if args.dasym_root is None or args.cutout_root is None:
        sys.exit("ERROR: job needs --dasym-root and --cutout-root")
    cut = args.cutout_root / model["name"]
    ins, miss = {}, []
    for y in u["job_years"]:
        p = {"zones": cut / "zones" / f"zones_{y}.tif", "zones_csv": cut / "zones" / f"zones_{y}.csv",
             "bui": common.layer_path(cut, "BUI", y), "bupr": common.layer_path(cut, "BUPR", y),
             "v57": args.dasym_root / model["name"] / u["version"] / "predictions" / f"pop_{y}.tif",
             "tract_errors": ypath(u["tract_errors"], y)}
        for k, v in p.items():
            log.info("  input %d %-13s %s%s", y, k, v, "" if Path(v).exists() else "  MISSING")
        miss += [f"{y} {k} {v}" for k, v in p.items() if not Path(v).exists()]
        ins[y] = p
    nb, how = ecd.nobuilt_path(args)
    log.info("  input NobuiltYear source: %s (%s)", nb, how)
    if nb is None:
        miss.append(f"NobuiltYear: {how}")
    block_rows = int(args.block_rows or model.get("block_rows") or 0)
    if not block_rows:
        sys.exit("ERROR: no block_rows")
    t = read_tables(cfg, u)
    if miss:
        sys.exit(f"ERROR: {len(miss)} inputs missing: {miss}")
    if args.check:
        log.info("CHECK OK: inputs for %s, block_rows %d", u["job_years"], block_rows)
        return 0
    log.info("RULE allocated ratios per county: people of v5.7 on built cells (BUI_year > 0) / BUPR_year on those cells, "
             "/ built cells; on undated cells (BUI_year = 0, NobuiltYear > 0) / NobuiltYear on those cells, / undated "
             "cells; v5.7 cells only (mask = pop_year.tif not nodata, used counties)")
    log.info("RULE ratio vs tract: |log(ratio / median of the county's class and year)| vs county tract MdAPE (evaluated "
             "tracts of %s, counties with >= %d), Spearman by class (fixed 1980 labels) and all", u["tract_errors"],
             int(u["min_tracts"]))
    rows = []
    for y in u["job_years"]:
        ty = time.time()
        p = ins[y]
        used, lut = mcm.counties(p, model, y)
        n = len(used)
        with rasterio.open(p["v57"]) as src:
            grid_t, crs, (H, W) = src.transform, src.crs, src.shape
        with rasterio.open(p["zones"]) as src:
            if src.transform != grid_t or src.shape != (H, W):
                sys.exit(f"ERROR: {y}: zones are not on the grid of the v5.7 map")
        ctx = {"grid_t": grid_t, "crs": crs, "width": W, "n_counties": n, "lut": lut, "zones": p["zones"],
               "v57": p["v57"], "bui": p["bui"], "bupr": p["bupr"], "nobuilt": nb}
        acc, info = None, {}
        for res in run_strips(ctx, common.strips((H, W), block_rows), args.workers):
            acc = res["acc"] if acc is None else {k: acc[k] + v for k, v in res["acc"].items()}
            for k, v in res["info"].items():
                info[k] = info.get(k, 0) + v
        A = {k: v.reshape(n, NT) for k, v in acc.items()}
        ct = used[["GISJOIN", "state", "name"]].reset_index(drop=True).copy()
        ct[f"census_pop_{y}"] = used["pop"].to_numpy(float)
        ct["pop_v57"] = A["pop"].sum(axis=1)
        mcm.check_census(ct, y)
        d = ct[["GISJOIN", "state", "name"]].copy()
        d.insert(0, "year", y)
        d["region"] = d["GISJOIN"].str[1:3].map(t["regions"]).fillna("none")
        d["county_class_1980"] = d["GISJOIN"].map(t["cls"]).fillna("none")
        d["excluded_t070"] = d["GISJOIN"].isin(t["excl"])
        d["pop"] = ct[f"census_pop_{y}"]
        for i, g in enumerate(GROUPS):
            d[f"n_cells_{g}"] = A["cells"][:, i]
            d[f"pop_{g}"] = A["pop"][:, i]
        d["bupr_built"] = A["bupr"][:, 0]
        d["bupr_mask"] = A["bupr"].sum(axis=1)
        d["nobuilt_undated"] = A["nobuilt"][:, 1]
        for m, (a, b) in ALLOC.items():
            d[m] = safe_ratio(d[a], d[b])
        bt = t["bupr"].set_index("GISJOIN")[f"bupr_{y}"]
        d["bupr_county_table"] = d["GISJOIN"].map(bt).to_numpy(float)
        tm = county_tract_mdape(pd.read_csv(p["tract_errors"]))
        d = d.merge(tm, on="GISJOIN", how="left")
        rows.append(d)
        log.info("  %d: %d counties, %s; BUPR on the v5.7 cells %.0f of %.0f in the county table (%.4f); people on built "
                 "/ undated / no_record %.0f / %.0f / %.0f; counties with >= %d tracts %d (%.0f s)", y, n, info,
                 d["bupr_mask"].sum(), d["bupr_county_table"].sum(), d["bupr_mask"].sum() / d["bupr_county_table"].sum(),
                 *(d[f"pop_{g}"].sum() for g in GROUPS), int(u["min_tracts"]),
                 int((d["n_tracts"].fillna(0) >= int(u["min_tracts"])).sum()), time.time() - ty)
    al = pd.concat(rows, ignore_index=True)
    vt = ratio_vs_tract(al, int(u["min_tracts"]))
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    al.to_csv(out / "allocated_ratios.csv", index=False)
    vt.to_csv(out / "ratio_vs_tract.csv", index=False)
    draw_vs_tract(out / "ratio_vs_tract.png", al, u["job_years"], int(u["min_tracts"]))
    with pd.option_context("display.width", 250, "display.max_rows", 400, "display.max_columns", 30):
        for m in ALLOC:
            log.info("SUMMARY %s, county median by year and class:\n%s", m,
                     al.pivot_table(index="year", columns="county_class_1980", values=m, aggfunc="median").round(3)
                     .to_string())
        log.info("SUMMARY Spearman |log(ratio / class median)| vs county tract MdAPE:\n%s",
                 vt.pivot_table(index=["measure", "county_class_1980"], columns="year",
                                values=["spearman", "n_counties"]).round(3).to_string())
    log.info("wrote %s (2 CSV + 1 PNG), %.0f s", out, time.time() - t_start)
    log.info("DONE")
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stdout, force=True)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    cfg = load_config(args.config)
    u = ur_config(cfg)
    return run_local(args, cfg, u) if args.mode == "local" else run_job(args, cfg, u)


if __name__ == "__main__":
    sys.exit(main())
