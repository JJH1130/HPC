"""SHAP bar + summary (beeswarm) figures for one or more versions and years, from tracked files only.

Stefan (meeting 2026-11-17, docs/open_items.md item 3) asked for feature importance. train.py already writes, per era,
`shap_values.csv` (TreeExplainer SHAP per training county: shap_<feature>, GISJOIN, year) and `county_features.csv`
(the county feature values). This script reads those two from results/dasymetric/conus/<version>/Y<year>/ and draws,
per year, one figure with a row per version: left = mean |SHAP| per feature (bar), right = SHAP value per county
(beeswarm, colour = the county's feature value as a percentile within that feature, low blue -> high red). No model
is loaded and nothing is recomputed: the bars equal the era's `shap_importance.csv` (checked; a difference stops).

Usage (runs locally, no cluster):
    python src/validation/shap_figures.py --versions Dasy_CONUS_RF_v3_all_nby=v5.7 Dasy_CONUS_RF_v3_all_nby_pq5="v5.7 + PLURAL (pq5)" \
        --years 1940 1980 2010 --out results/validation/conus/shap_figures
Outputs: shap_<year>.png per year + shap_importance_by_version.csv (version, year, feature, mean_abs_shap, rank).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "results" / "dasymetric" / "conus"

LABELS = {
    "bui": "BUI (built-up intensity)", "bldg_size": "building size", "mu_ratio": "multi-unit ratio",
    "dist_built": "distance to built", "res_share": "residential share", "rent_share": "rental share",
    "elev": "elevation", "slope": "slope", "nby": "NobuiltYear (undated records)", "plural": "PLURAL rurality (high = rural)",
}


def load(version: str, year: int):
    d = BASE / version / f"Y{year}"
    sv = pd.read_csv(d / "shap_values.csv")
    feats = [c[5:] for c in sv.columns if c.startswith("shap_")]
    cf = pd.read_csv(d / "county_features.csv")
    cf = cf[cf["year"] == year] if "year" in cf else cf
    x = sv[["GISJOIN"]].merge(cf[["GISJOIN"] + feats], on="GISJOIN", how="left")
    if x[feats].isna().any().any():
        raise SystemExit(f"{version} {year}: county features missing for some SHAP rows")
    S = sv[[f"shap_{f}" for f in feats]].to_numpy()
    imp = pd.Series(np.abs(S).mean(axis=0), index=feats).sort_values(ascending=False)
    ref = pd.read_csv(d / "shap_importance.csv").set_index("feature")["mean_abs_shap"]
    if not np.allclose(imp.reindex(ref.index).to_numpy(), ref.to_numpy(), rtol=1e-9, atol=1e-12):
        raise SystemExit(f"{version} {year}: mean |SHAP| differs from shap_importance.csv")
    return feats, S, x[feats].to_numpy(dtype=float), imp


def beeswarm_y(vals: np.ndarray, width: float = 0.38, nbins: int = 60, rng=None) -> np.ndarray:
    """Vertical offsets: points spread in proportion to the local density of SHAP values (like shap's summary plot)."""
    rng = rng or np.random.default_rng(0)
    if vals.size < 2 or np.ptp(vals) == 0:
        return rng.uniform(-width, width, vals.size) * 0.3
    edges = np.linspace(vals.min(), vals.max(), nbins + 1)
    idx = np.clip(np.digitize(vals, edges) - 1, 0, nbins - 1)
    counts = np.bincount(idx, minlength=nbins)
    dens = counts[idx] / counts.max()
    return rng.uniform(-1, 1, vals.size) * width * dens


def draw(year: int, rows, out: Path):
    nmax = max(len(r[1]) for r in rows)
    fig, axes = plt.subplots(len(rows), 2, figsize=(13, 0.42 * nmax * len(rows) + 1.6),
                             gridspec_kw={"width_ratios": [1, 1.6], "wspace": 0.75}, squeeze=False)
    xmax = max(r[4].max() for r in rows) * 1.22
    smin = min(r[2].min() for r in rows)
    smax = max(r[2].max() for r in rows)
    sc = None
    for i, (label, feats, S, X, imp) in enumerate(rows):
        order = list(imp.index)            # most important on top
        ypos = np.arange(len(order))[::-1]
        axb, axs = axes[i]
        colors = ["#c44e52" if f in ("nby", "plural") else "#4c72b0" for f in order]
        axb.barh(ypos, imp.values, color=colors)
        for yy, v in zip(ypos, imp.values):
            axb.text(v + xmax * 0.01, yy, f"{v:.3f}", va="center", fontsize=8)
        axb.set_yticks(ypos, [LABELS.get(f, f) for f in order], fontsize=9)
        axb.set_xlim(0, xmax)
        axb.set_xlabel("mean |SHAP| (log density)", fontsize=9)
        axb.set_title(f"{label}: importance", fontsize=10, loc="left")
        rng = np.random.default_rng(0)
        for yy, f in zip(ypos, order):
            j = feats.index(f)
            v = S[:, j]
            pct = pd.Series(X[:, j]).rank(pct=True).to_numpy()
            sc = axs.scatter(v, yy + beeswarm_y(v, rng=rng), c=pct, cmap="coolwarm", vmin=0, vmax=1, s=5,
                             alpha=0.7, linewidths=0, rasterized=True)
        axs.axvline(0, color="0.5", lw=0.8)
        axs.set_yticks(ypos, [LABELS.get(f, f) for f in order], fontsize=9)
        axs.set_xlim(smin - 0.05 * (smax - smin), smax + 0.05 * (smax - smin))
        axs.set_xlabel("SHAP value per county (effect on log density)", fontsize=9)
        axs.set_title(f"{label}: summary ({S.shape[0]:,} training counties)", fontsize=10, loc="left")
        for ax in (axb, axs):
            ax.spines[["top", "right"]].set_visible(False)
    cb = fig.colorbar(sc, ax=axes[:, 1].tolist(), shrink=0.6, pad=0.01)
    cb.set_label("feature value (percentile within feature)", fontsize=9)
    cb.set_ticks([0, 1], labels=["low", "high"])
    fig.suptitle(f"County RF, {year}: SHAP feature importance (TreeExplainer, training counties)", fontsize=11)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--versions", nargs="+", required=True, help="VERSION=LABEL")
    ap.add_argument("--years", nargs="+", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    recs = []
    for year in a.years:
        rows = []
        for vl in a.versions:
            v, _, lab = vl.partition("=")
            feats, S, X, imp = load(v, year)
            rows.append((lab or v, feats, S, X, imp))
            for r, (f, m) in enumerate(imp.items(), 1):
                recs.append({"version": v, "label": lab or v, "year": year, "feature": f, "mean_abs_shap": m, "rank": r})
        draw(year, rows, a.out / f"shap_{year}.png")
        print(f"wrote {a.out / f'shap_{year}.png'}")
    pd.DataFrame(recs).to_csv(a.out / "shap_importance_by_version.csv", index=False)


if __name__ == "__main__":
    main()
