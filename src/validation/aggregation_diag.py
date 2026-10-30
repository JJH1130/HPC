"""County feature aggregation: diagnosis only (Stefan item 5, meeting 2026-10-28; request
docs/handoff/aggregation_diagnosis_request.md; docs/conus_plan.md "County feature aggregation: diagnosis"). No training
and no prediction: reads the cutout, the version's county_features.csv and its allocated population rasters.

The models learn from county means of the cell features (mean over all unmasked cells, empty cells = 0 included) and
are applied to single cells (change of support). This script measures, for the years given (v5.6 =
Dasy_CONUS_RF_v3_u070; 1960 and 2010 by default):

1. Cells outside the training range. Range of a feature = min / max (and p01 / p99) of its county mean over the
   training counties of the era (split part train, not in `exclude_counties`, status in `train_status`, as train.py).
   Per feature: share of cells below / above and the share of the allocated population (predictions/pop_{YEAR}.tif) on
   them; share of cells (and population) with every feature inside, for all / built (BUI > 0) / empty (BUI = 0) cells;
   quantiles p01 p10 p50 p90 p99 max of the cells (all / built / empty) next to the training county means, with the
   share of zeros.
2. Other aggregates per county, on the same cells (the cells of county_features.py: used counties, water mask, strips):
   mean_<f> (the current mean; must equal county_features.csv, else the job stops), built_share (built cells / cells),
   bmean_<f> / bmed_<f> (mean / median over built cells; bui, bldg_size, mu_ratio, res_share, rent_share, elev, slope),
   med_<f> (median over all cells, every feature: shows where the median is 0), top10_share (share of the county BUI
   sum on its top 10 % built cells by BUI, k = ceil(n_built / 10)), gini_bui (Gini of BUI over built cells,
   G = 2 sum(i x_(i)) / (n sum x) - (n + 1) / n, x ascending, i = 1 ... n), oor_cell_share / oor_pop_share (cells /
   allocated people with any feature outside the min / max range; _p = outside p01 / p99).
3. Summaries: Spearman of every aggregate with y and between aggregates (training counties); per county tract MdAPE
   from the version's tract_errors_{YEAR}.csv (evaluated tracts by their 2010 county, counties with >= --min-tracts
   tracts) against top10_share / gini_bui / built_share / out-of-range shares (Spearman) and by quartile of the two
   concentration measures; a figure of the built cells' values against the training county means (log x).

Medians and quantiles use the cell values stored as float32 (means and sums are float64, as county_features.py).

A config with an `aggregation:` block (built-cell aggregation test, docs/conus_plan.md "Built-cell aggregation test")
is read with its own county values: a built_mean feature's training value (range, quantiles, figure, check against
county_features.csv) is bmean_<f> (0 without a built cell, as county_features.py), and built_local is a cell feature
like the others. extrapolation.csv has pop_share_of_total per subset (the empty row = people on BUI = 0 cells).

Writes to --out (results/aggregation/<name>/):
  county_aggregates_{YEAR}.csv      one row per used county: GISJOIN, set (train / test / excluded / not_trained),
                                    pop, area_km2, y, cells, the aggregates above
  extrapolation.csv                 year, range (minmax / p01_p99), feature (or all_features), subset (all / built /
                                    empty), lo, hi, cells, cell and population shares below / above / inside
  cell_vs_county_quantiles.csv      year, feature, sample (cells_all / cells_built / cells_empty / counties_train), n,
                                    zero_share, p01 p10 p50 p90 p99 max
  aggregate_correlations.csv        year, a, b, rho, n (Spearman over training counties, pairwise complete)
  tract_error_by_county_{YEAR}.csv  counties with >= --min-tracts evaluated tracts: tracts, tract MdAPE (model / areal
                                    weighting), the concentration / built share / out-of-range columns
  aggregate_vs_tract_error.csv      kind spearman (measure vs county tract MdAPE) and quartile (by top10_share /
                                    gini_bui: counties, tracts, median county MdAPE, pooled tract MdAPE)
  cell_vs_county_{PLOT_YEAR}.png    per feature: built cells vs training county means (dist_built: all cells)
Paths come from CLI flags (sbatch/aggregation_diag.sh).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import Window

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dasymetric"))
from common import (NODATA_OUT, built_local_setup, cell_features, county_selection, era_of, load_config,  # noqa: E402
                    log, log_args, out_dir, read_zones, setup_logging, strips, used_mask, water_mask)

YEARS = [1960, 2010]
BUILT_FEATURES = ["bui", "bldg_size", "mu_ratio", "res_share", "rent_share", "elev", "slope"]  # bmean / bmed
QUANTILES = [0.01, 0.10, 0.50, 0.90, 0.99]
TOP_PCT = 10  # top10_share: the top 10 % of the built cells by BUI
MIN_TRACTS = 5
MEAN_RTOL = 1e-9  # recomputed mean vs county_features.csv
POP_RTOL = 1e-5  # allocated pop on the cells vs census pop (logged only; float32 raster)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, required=True, help="configs/conus_rf_v3_u070.yaml (v5.6)")
    p.add_argument("--out-root", type=Path, required=True,
                   help="dasymetric outputs <out-root>/<name>/<version>/ (county_features.csv, predictions/)")
    p.add_argument("--cutout-root", type=Path, required=True, help="cutout is <cutout-root>/<name>/")
    p.add_argument("--years", type=int, nargs="+", default=YEARS)
    p.add_argument("--tracts-dir", type=Path, help="tract_errors_{YEAR}.csv (default results/validation/<name>/<version>)")
    p.add_argument("--out", type=Path, help="output folder (default results/aggregation/<name>)")
    p.add_argument("--min-tracts", type=int, default=MIN_TRACTS)
    p.add_argument("--plot-year", type=int, default=2010, help="year of the figure (skipped if not in --years)")
    return p.parse_args(argv)


def mdape(obs: np.ndarray, pred: np.ndarray) -> float:
    pos = obs > 0  # as tract_validate.mdape
    return float(np.median(np.abs(pred[pos] - obs[pos]) / obs[pos]) * 100) if pos.any() else np.nan


def top_share(x: np.ndarray, pct: int = TOP_PCT) -> float:
    """Share of sum(x) on the ceil(n x pct / 100) largest values (integer arithmetic: no 0.1 x 30 = 3.0000000004)."""
    if len(x) == 0 or x.sum() <= 0:
        return np.nan
    k = max(1, -(-len(x) * pct // 100))
    return float(np.sort(x)[::-1][:k].sum() / x.sum())


def gini(x: np.ndarray) -> float:
    """Gini of non-negative values: 2 sum(i x_(i)) / (n sum x) - (n + 1) / n, x ascending, i = 1 ... n."""
    n = len(x)
    if n == 0 or x.sum() <= 0:
        return np.nan
    s = np.sort(x)
    return float(2 * (np.arange(1, n + 1) * s).sum() / (n * s.sum()) - (n + 1) / n)


def county_sets(rows: pd.DataFrame, cfg: dict) -> pd.Series:
    """train / test (split part) / excluded (exclude_counties) / not_trained (status outside train_status), in
    train.py's order: train_status first, then the exclusions, then the split."""
    part = pd.Series("train", index=rows.index)
    if cfg.get("split"):
        sp = pd.read_csv(cfg["split"], dtype={"GISJOIN": str})
        part = rows["GISJOIN"].map(dict(zip(sp["GISJOIN"], sp["part"])))
    ex = set()
    if cfg.get("exclude_counties"):
        ex = set(pd.read_csv(cfg["exclude_counties"], dtype={"GISJOIN": str})["GISJOIN"])
    out = part.astype(object).copy()
    out[rows["GISJOIN"].isin(ex)] = "excluded"
    if cfg.get("train_status"):
        out[~rows["status"].isin(cfg["train_status"])] = "not_trained"
    if out.isna().any():
        sys.exit(f"ERROR: counties not in the split table: {sorted(rows.loc[out.isna(), 'GISJOIN'])[:20]}")
    return out


def model_col(cfg: dict, f: str) -> str:
    """The aggregates column that holds the county value the model trained on (mean_<f> or bmean_<f>)."""
    return f"bmean_{f}" if cfg.get("aggregation", {}).get(f) == "built_mean" else f"mean_{f}"


def model_values(rows: pd.DataFrame, cfg: dict, f: str) -> np.ndarray:
    return rows[model_col(cfg, f)].fillna(0.0).to_numpy()  # built_mean: 0 without a built cell (county_features.py)


def read_pop(path: Path, grid: dict, rows: slice | None):
    with rasterio.open(path) as src:
        if (src.height, src.width) != grid["shape"] or src.transform != grid["transform"]:
            sys.exit(f"ERROR: {path} is not on the zones grid")
        if rows is None:
            return src.read(1)
        return src.read(1, window=Window(0, rows.start, src.width, rows.stop - rows.start))


# ---------------------------------------------------------------- 1 + 2: one pass over the cells

def cell_pass(cutout: Path, year: int, feats: list, cfg: dict, pop_path: Path):
    """The cells of county_features.year_rows (same selection, water mask and strips): county table with float64
    sums (all cells / built cells) and the cell values (float32) + zone + allocated pop of every kept cell."""
    zones, table, grid = read_zones(cutout, year)
    used = county_selection(table, zones, cfg["use_status"], year, cfg["unusable"])
    ids = used["zone_id"].to_numpy()
    nz = int(max(zones.max(), ids.max())) + 1
    n, nb = np.zeros(nz, np.int64), np.zeros(nz, np.int64)
    sums = {f: np.zeros(nz) for f in feats}
    bsums = {f: np.zeros(nz) for f in feats if f in BUILT_FEATURES or model_col(cfg, f) != f"mean_{f}"}
    Z, P, V = [], [], {f: [] for f in feats}
    full = {}
    blocal = built_local_setup(cfg, zones, ids) if "built_local" in feats else None
    parts = strips(zones.shape, cfg.get("block_rows"))
    for k, rws in enumerate(parts):
        mask = used_mask(zones[rws], ids)
        if not mask.any():
            continue
        sub = None if len(parts) == 1 else rws
        X = cell_features(cutout, year, grid, mask, feats, sub, full, None, blocal)
        z = zones[rws][mask]
        keep = np.ones(len(z), bool)
        if cfg.get("water_mask"):
            keep = ~water_mask(cutout, year, grid, mask, cfg.get("water_mask"), sub)[0]
        pop = read_pop(pop_path, grid, sub)[mask]
        bad = keep & ((pop == NODATA_OUT) | ~np.isfinite(pop) | (pop < 0))
        if bad.any():
            sys.exit(f"ERROR: {pop_path}: {int(bad.sum())} kept cells of used counties without a valid population")
        built = X["bui"].to_numpy() > 0
        zk = z[keep]
        n += np.bincount(zk, minlength=nz)
        nb += np.bincount(z[keep & built], minlength=nz)
        for f in feats:
            v = X[f].to_numpy()
            sums[f] += np.bincount(zk, weights=v[keep], minlength=nz)
            if f in bsums:
                bsums[f] += np.bincount(z[keep & built], weights=v[keep & built], minlength=nz)
            V[f].append(v[keep].astype("float32"))
        Z.append(zk.astype("int32"))
        P.append(pop[keep].astype("float32"))
        if len(parts) > 1 and ((k + 1) % 20 == 0 or k + 1 == len(parts)):
            log.info("    %d: strip %d/%d (rows %d-%d)", year, k + 1, len(parts), rws.start, rws.stop)
    del full
    rows = used[["zone_id", "GISJOIN", "state", "name", "status", "pop"]].copy()
    rows = rows[n[rows["zone_id"].to_numpy()] > 0].reset_index(drop=True)  # unusable: skip (as county_features)
    zid = rows["zone_id"].to_numpy()
    rows["cells"], rows["n_built"] = n[zid], nb[zid]
    rows["built_share"] = rows["n_built"] / rows["cells"]
    for f in feats:
        rows[f"mean_{f}"] = sums[f][zid] / n[zid]
    with np.errstate(invalid="ignore", divide="ignore"):
        for f in bsums:
            rows[f"bmean_{f}"] = np.where(nb[zid] > 0, bsums[f][zid] / nb[zid], np.nan)
    cells = {"zone": np.concatenate(Z), "pop": np.concatenate(P)}
    del Z, P
    for f in feats:
        cells[f] = np.concatenate(V[f])
        V[f] = None
    log.info("  %d: %d counties, %d kept cells (%d built, %.3f)", year, len(rows), len(cells["zone"]),
             int(rows["n_built"].sum()), rows["n_built"].sum() / rows["cells"].sum())
    return rows, cells


def check_means(rows: pd.DataFrame, feats: list, path: Path, year: int, cfg: dict):
    """The model's county value of every feature (mean_<f>, or bmean_<f> for built_mean) must equal
    county_features.csv (same counties, same values within MEAN_RTOL), else stop."""
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (county_features.py of this version)")
    cf = pd.read_csv(path, dtype={"GISJOIN": str})
    cf = cf[cf["year"] == year]
    a, b = set(rows["GISJOIN"]), set(cf["GISJOIN"])
    if a != b:
        sys.exit(f"ERROR: {year}: counties differ from {path}: only here {sorted(a - b)[:10]}, only there "
                 f"{sorted(b - a)[:10]}")
    m = rows.merge(cf, on="GISJOIN", suffixes=("", "_cf"))
    worst = {}
    for f in feats:
        x, y = model_values(m, cfg, f), m[f].to_numpy()
        worst[f] = float(np.max(np.abs(x - y) / np.maximum(np.abs(y), 1e-12)))
    for c in ("pop", "area_km2", "y"):
        worst[c] = float(np.max(np.abs(m[c] - m[f"{c}_cf"]) / np.maximum(np.abs(m[f"{c}_cf"]), 1e-12)))
    bad = {f: w for f, w in worst.items() if w > MEAN_RTOL}
    if bad:
        sys.exit(f"ERROR: {year}: recomputed county means differ from {path} (max relative difference {bad})")
    log.info("  %d: recomputed means = county_features.csv for %d counties (max rel. diff %.1e)", year, len(m),
             max(worst.values()))


def county_medians(rows: pd.DataFrame, cells: dict, feats: list):
    """med_<f> (all cells), bmed_<f> (built cells), top10_share and gini_bui (BUI of built cells) per county."""
    order = np.argsort(cells["zone"], kind="stable")
    zs = cells["zone"][order]
    zid = rows["zone_id"].to_numpy()
    lo, hi = np.searchsorted(zs, zid, "left"), np.searchsorted(zs, zid, "right")
    built = (cells["bui"] > 0)[order]
    for f in feats:
        v = cells[f][order]
        med = np.empty(len(zid))
        bmed = np.full(len(zid), np.nan)
        for i, (a, b) in enumerate(zip(lo, hi)):
            seg = v[a:b]
            med[i] = np.median(seg)
            sb = seg[built[a:b]]
            if len(sb):
                bmed[i] = np.median(sb)
        rows[f"med_{f}"] = med
        if f in BUILT_FEATURES:
            rows[f"bmed_{f}"] = bmed
        if f == "bui":
            rows["top10_share"] = [top_share(v[a:b][built[a:b]].astype("float64")) for a, b in zip(lo, hi)]
            rows["gini_bui"] = [gini(v[a:b][built[a:b]].astype("float64")) for a, b in zip(lo, hi)]
        del v


def train_ranges(train: pd.DataFrame, feats: list, cfg: dict) -> dict:
    """{range kind: {feature: (lo, hi)}} from the training county values."""
    out = {"minmax": {}, "p01_p99": {}}
    for f in feats:
        v = model_values(train, cfg, f)
        out["minmax"][f] = (float(v.min()), float(v.max()))
        out["p01_p99"][f] = tuple(float(q) for q in np.quantile(v, [0.01, 0.99]))
    return out


def extrapolation(year: int, rows: pd.DataFrame, cells: dict, feats: list, ranges: dict) -> list[dict]:
    """Cell / population shares outside each range, per feature and for all features together; county columns
    oor_cell_share / oor_pop_share (min / max) and oor_p_* (p01 / p99)."""
    built = cells["bui"] > 0
    pop = cells["pop"].astype("float64")
    subsets = {"all": np.ones(len(pop), bool), "built": built, "empty": ~built}
    tot = {s: (int(m.sum()), float(pop[m].sum())) for s, m in subsets.items()}
    nz = int(cells["zone"].max()) + 1
    zid = rows["zone_id"].to_numpy()
    out = []

    def share(sel, s):
        m = sel & subsets[s]
        nc, npop = tot[s]
        return (m.sum() / nc if nc else np.nan, pop[m].sum() / npop if npop > 0 else np.nan)

    for kind, rng in ranges.items():
        inside = np.ones(len(pop), bool)
        for f in feats:
            lo, hi = rng[f]
            v = cells[f]
            below, above = v < lo, v > hi
            inside &= ~(below | above)
            for s in subsets:
                cb, pb = share(below, s)
                ca, pa = share(above, s)
                out.append({"year": year, "range": kind, "feature": f, "subset": s, "lo": lo, "hi": hi,
                            "cells": tot[s][0], "pop_share_of_total": tot[s][1] / tot["all"][1], "cell_share_below": cb, "cell_share_above": ca,
                            "cell_share_inside": 1 - cb - ca if tot[s][0] else np.nan, "pop_share_below": pb,
                            "pop_share_above": pa, "pop_share_inside": 1 - pb - pa if tot[s][1] > 0 else np.nan})
            del below, above
        for s in subsets:
            ci, pi = share(inside, s)
            out.append({"year": year, "range": kind, "feature": "all_features", "subset": s, "cells": tot[s][0],
                        "pop_share_of_total": tot[s][1] / tot["all"][1], "cell_share_inside": ci,
                        "pop_share_inside": pi})
        tag = "" if kind == "minmax" else "_p"
        oor = ~inside
        n_cells = np.bincount(cells["zone"], minlength=nz)[zid]
        cpop = np.bincount(cells["zone"], weights=pop, minlength=nz)[zid]
        rows[f"oor{tag}_cell_share"] = np.bincount(cells["zone"][oor], minlength=nz)[zid] / n_cells
        with np.errstate(invalid="ignore", divide="ignore"):
            rows[f"oor{tag}_pop_share"] = np.bincount(cells["zone"][oor], weights=pop[oor], minlength=nz)[zid] / cpop
        if kind == "minmax":
            rows["pop_alloc"] = cpop
    return out


def quantile_rows(year: int, cells: dict, train: pd.DataFrame, feats: list, cfg: dict) -> list[dict]:
    built = cells["bui"] > 0
    out = []
    for f in feats:
        samples = {"cells_all": cells[f], "cells_built": cells[f][built], "cells_empty": cells[f][~built],
                   "counties_train": model_values(train, cfg, f)}
        for s, v in samples.items():
            r = {"year": year, "feature": f, "sample": s, "n": len(v),
                 "zero_share": float((v == 0).mean()) if len(v) else np.nan}
            q = np.quantile(v, QUANTILES) if len(v) else [np.nan] * len(QUANTILES)
            r.update({f"p{int(round(p * 100)):02d}": float(x) for p, x in zip(QUANTILES, q)})
            r["max"] = float(v.max()) if len(v) else np.nan
            out.append(r)
    return out


def histograms(cells: dict, train: pd.DataFrame, feats: list, ranges: dict, cfg: dict) -> dict:
    """Per feature: log10 histograms (density) of the built cells' positive values (dist_built: all cells, built
    ones are 0) and of the positive training county means, on common bins; zero / non-positive shares."""
    built = cells["bui"] > 0
    out = {}
    for f in feats:
        c = cells[f] if f == "dist_built" else cells[f][built]
        m = model_values(train, cfg, f)
        cp, mp = c[c > 0].astype("float64"), m[m > 0]
        if not len(cp) or not len(mp):
            continue
        lo, hi = np.log10(min(cp.min(), mp.min())), np.log10(max(cp.max(), mp.max()))
        edges = np.linspace(lo, hi if hi > lo else lo + 1, 61)
        out[f] = {"edges": edges, "cells": np.histogram(np.log10(cp), edges, density=True)[0],
                  "counties": np.histogram(np.log10(mp), edges, density=True)[0],
                  "cells_nonpos": float(1 - len(cp) / len(c)), "counties_nonpos": float(1 - len(mp) / len(m)),
                  "sample": "all cells" if f == "dist_built" else "built cells", "range": ranges["minmax"][f]}
    return out


def plot(hists: dict, path: Path, version: str, year: int):
    import plots  # noqa: E402  (palette + style of the pipeline figures)
    plt = plots.plt
    feats = list(hists)
    ncol = 4
    nrow = -(-len(feats) // ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.4 * ncol, 2.9 * nrow), dpi=150, layout="constrained", squeeze=False)
    for ax, f in zip(axes.ravel(), feats):
        h = hists[f]
        x = 10 ** h["edges"]
        lo, hi = h["range"]
        if hi > 0:
            ax.axvspan(max(lo, x[0]), hi, color=plots.GRID, lw=0, zorder=0)
        ax.stairs(h["cells"], x, color=plots.SERIES[0], lw=1.6, label=h["sample"])
        ax.stairs(h["counties"], x, color=plots.SERIES[1], lw=1.6, label="training county means")
        ax.set_xscale("log")
        ax.xaxis.set_minor_formatter(plots.matplotlib.ticker.NullFormatter())  # narrow ranges: labels overlap
        ax.set_title(f"{f}\n{h['sample']} <= 0: {100 * h['cells_nonpos']:.0f} %, county means <= 0: "
                     f"{100 * h['counties_nonpos']:.0f} %", fontsize=8, color=plots.INK)
        ax.set_yticks([])
        plots._style(ax)
    for ax in axes.ravel()[len(feats):]:
        ax.axis("off")
    axes.ravel()[0].legend(fontsize=7, frameon=False, labelcolor=plots.INK2, loc="upper left")
    fig.suptitle(f"{version} {year}: cell values vs training county means (log x, density of log10 values; "
                 f"grey = county min-max range; values <= 0 left out)", fontsize=9, color=plots.INK)
    plots._save(fig, path)


# ---------------------------------------------------------------- 3: summaries

def correlations(year: int, train: pd.DataFrame, cols: list) -> pd.DataFrame:
    d = train[cols + ["y"]]
    rho = d.corr(method="spearman")
    ok = d.notna().astype(int)
    n = ok.T @ ok
    keys = cols + ["y"]
    out = [{"year": year, "a": a, "b": b, "rho": rho.at[a, b], "n": int(n.at[a, b])}
           for i, a in enumerate(keys) for b in keys[i + 1:]]
    return pd.DataFrame(out)


def tract_by_county(year: int, rows: pd.DataFrame, tracts_dir: Path, min_tracts: int):
    path = tracts_dir / f"tract_errors_{year}.csv"
    if not path.exists():
        log.warning("  %d: %s not found: no tract comparison for this year", year, path)
        return None
    t = pd.read_csv(path, dtype={"zone_gisjoin": str})
    t = t[t["flag"] == "ok"]
    g = t.groupby("zone_gisjoin")
    c = pd.DataFrame({"tracts": g.size(),
                      "tract_mdape": g[["pop_obs", "pop_model"]].apply(lambda d: mdape(*d.to_numpy().T)),
                      "baseline_mdape": g[["pop_obs", "pop_baseline"]].apply(lambda d: mdape(*d.to_numpy().T)),
                      "pop_obs": g["pop_obs"].sum()}).reset_index().rename(columns={"zone_gisjoin": "GISJOIN"})
    c = c[c["tracts"] >= min_tracts]
    keep = ["GISJOIN", "state", "name", "set", "pop", "cells", "built_share", "top10_share", "gini_bui",
            "oor_cell_share", "oor_pop_share", "oor_p_cell_share", "oor_p_pop_share", "mean_bui", "bmean_bui"]
    c = c.merge(rows[keep], on="GISJOIN", how="left")
    c["set"] = c["set"].fillna("not_used")  # tracts in a county without a used row this year (no aggregates)
    c.insert(0, "year", year)
    return c, t


MEASURES = ["top10_share", "gini_bui", "built_share", "oor_pop_share", "oor_cell_share", "oor_p_pop_share"]


def tract_summary(year: int, c: pd.DataFrame, t: pd.DataFrame) -> list[dict]:
    out = []
    for m in MEASURES:
        d = c[[m, "tract_mdape"]].dropna()
        out.append({"year": year, "kind": "spearman", "measure": m, "counties": len(d),
                    "rho": d[m].corr(d["tract_mdape"], method="spearman") if d[m].nunique() > 1 and len(d) > 2
                    else np.nan})  # constant (e.g. every cell out of range): no rho
    for m in ("top10_share", "gini_bui"):
        d = c.dropna(subset=[m]).copy()
        if len(d) < 4:
            continue
        d["q"] = pd.qcut(d[m], 4, labels=False, duplicates="drop") + 1
        for q, part in d.groupby("q"):
            tt = t[t["zone_gisjoin"].isin(part["GISJOIN"])]
            out.append({"year": year, "kind": "quartile", "measure": m, "quartile": int(q), "lo": part[m].min(),
                        "hi": part[m].max(), "counties": len(part), "tracts": int(part["tracts"].sum()),
                        "county_mdape_median": part["tract_mdape"].median(),
                        "tract_mdape_pooled": mdape(tt["pop_obs"].to_numpy(), tt["pop_model"].to_numpy()),
                        "baseline_mdape_pooled": mdape(tt["pop_obs"].to_numpy(), tt["pop_baseline"].to_numpy())})
    return out


def main(argv=None):
    setup_logging()
    args = parse_args(argv)
    log_args(args)
    cfg = load_config(args.config)
    cutout = args.cutout_root / cfg["name"]
    vdir = out_dir(cfg, args.out_root)
    tracts_dir = args.tracts_dir or Path("results") / "validation" / cfg["name"] / cfg["version"]
    out = args.out or Path("results") / "aggregation" / cfg["name"]
    bad = sorted(set(args.years) - set(cfg["years"]))
    if bad:
        sys.exit(f"ERROR: --years {bad} not in the config years {cfg['years']}")
    missing = [p for y in args.years for p in (vdir / "predictions" / f"pop_{y}.tif",
                                               vdir / era_of(cfg, y) / "features" / "county_features.csv")
               if not p.exists()]
    if missing:
        sys.exit("ERROR: missing inputs (predict / county_features of this version):\n" + "\n".join(map(str, missing)))
    if "bui" not in cfg["all_features"]:
        sys.exit("ERROR: the built-cell aggregates need the feature bui")
    out.mkdir(parents=True, exist_ok=True)
    log.info("%s %s | years %s | cutout %s | tracts %s -> %s", cfg["name"], cfg["version"], args.years, cutout,
             tracts_dir, out)

    ext, qua, cor, tsum = [], [], [], []
    for year in args.years:
        era = era_of(cfg, year)
        feats = cfg["eras"][era]["features"]
        log.info("== %d (era %s): features %s", year, era, feats)
        rows, cells = cell_pass(cutout, year, feats, cfg, vdir / "predictions" / f"pop_{year}.tif")
        rows["area_km2"] = rows["cells"] * 0.0625 if cfg.get("water_mask") else np.nan
        if not cfg.get("water_mask"):
            cf = pd.read_csv(vdir / era / "features" / "county_features.csv", dtype={"GISJOIN": str})
            rows["area_km2"] = rows["GISJOIN"].map(dict(zip(cf["GISJOIN"], cf["area_km2"])))
        rows["y"] = np.log(rows["pop"] / rows["area_km2"])
        check_means(rows, feats, vdir / era / "features" / "county_features.csv", year, cfg)
        rows.insert(rows.columns.get_loc("status") + 1, "set", county_sets(rows, cfg))
        log.info("  %d: county sets %s", year, rows["set"].value_counts().to_dict())
        county_medians(rows, cells, feats)
        train = rows[rows["set"] == "train"]
        ranges = train_ranges(train, feats, cfg)
        ext += extrapolation(year, rows, cells, feats, ranges)
        qua += quantile_rows(year, cells, train, feats, cfg)
        e = ext[-1] if ext[-1]["subset"] == "empty" else None
        log.info("  %d: allocated people on empty cells (BUI = 0): %.4f of the total", year,
                 e["pop_share_of_total"] if e else np.nan)
        rel = (rows["pop_alloc"] - rows["pop"]).abs() / rows["pop"]
        log.info("  %d: allocated pop on the kept cells vs census: max rel. diff %.1e%s", year, rel.max(),
                 "" if rel.max() < POP_RTOL else " (LARGER than expected)")
        for f in feats:
            z = int((rows[f"med_{f}"] == 0).sum())
            log.info("  %d: %-10s median over all cells = 0 in %d of %d counties; built-cell median = 0 in %d", year,
                     f, z, len(rows), int((rows.get(f"bmed_{f}", pd.Series(dtype=float)) == 0).sum()))
        if year == args.plot_year:
            hists = histograms(cells, train, feats, ranges, cfg)
        del cells
        train = rows[rows["set"] == "train"]  # with the medians / shares added
        aggs = [c for c in rows.columns if c.split("_", 1)[0] in ("mean", "bmean", "bmed", "med")]
        aggs += ["built_share", "top10_share", "gini_bui"]
        cor.append(correlations(year, train, aggs))
        rows.drop(columns=["zone_id"]).to_csv(out / f"county_aggregates_{year}.csv", index=False)
        log.info("  wrote %s", out / f"county_aggregates_{year}.csv")
        res = tract_by_county(year, rows, tracts_dir, args.min_tracts)
        if res is not None:
            c, t = res
            c.to_csv(out / f"tract_error_by_county_{year}.csv", index=False)
            log.info("  %d: %d counties with >= %d tracts (%s); wrote %s", year, len(c), args.min_tracts,
                     c["set"].value_counts().to_dict(), out / f"tract_error_by_county_{year}.csv")
            tsum += tract_summary(year, c, t)

    ext, qua, cor = pd.DataFrame(ext), pd.DataFrame(qua), pd.concat(cor, ignore_index=True)
    ext.to_csv(out / "extrapolation.csv", index=False)
    qua.to_csv(out / "cell_vs_county_quantiles.csv", index=False)
    cor.to_csv(out / "aggregate_correlations.csv", index=False)
    with pd.option_context("display.width", 220, "display.max_rows", 500):
        e = ext[ext["subset"] == "all"]
        log.info("cells / allocated people outside the training range (all cells; shares):\n%s",
                 e.pivot_table(index=["year", "feature"], columns="range",
                               values=["cell_share_below", "cell_share_above", "pop_share_below", "pop_share_above"],
                               sort=False).round(4).to_string())
        a = ext[ext["feature"] == "all_features"]
        log.info("every feature inside the range (shares of cells / people):\n%s",
                 a.pivot_table(index=["year", "range"], columns="subset", values=["cell_share_inside", "pop_share_inside"],
                               sort=False).round(4).to_string())
        log.info("cell quantiles vs training county means:\n%s", qua.round(4).to_string(index=False))
        y = cor[cor["b"] == "y"].pivot_table(index="a", columns="year", values="rho", sort=False)
        log.info("Spearman with y (training counties):\n%s", y.round(3).to_string())
        trio = ["bui", "bldg_size", "mu_ratio"]
        for pre in ("mean", "bmean", "bmed"):
            names = [f"{pre}_{f}" for f in trio]
            s = cor[cor["a"].isin(names) & cor["b"].isin(names)]
            log.info("Spearman among %s:\n%s", names, s.round(3).to_string(index=False))
        for f in trio + ["res_share", "elev"]:
            names = [f"mean_{f}", f"bmean_{f}", f"bmed_{f}", f"med_{f}", "built_share"]
            s = cor[cor["a"].isin(names) & cor["b"].isin(names)]
            log.info("Spearman, aggregates of %s:\n%s", f, s.round(3).to_string(index=False))
        if tsum:
            ts = pd.DataFrame(tsum)
            ts.to_csv(out / "aggregate_vs_tract_error.csv", index=False)
            log.info("county tract MdAPE vs aggregates:\n%s", ts.round(3).to_string(index=False))
    if args.plot_year in args.years and hists:
        plot(hists, out / f"cell_vs_county_{args.plot_year}.png", cfg["version"], args.plot_year)
    log.info("wrote %s", out)
    log.info("DONE")


if __name__ == "__main__":
    main()
