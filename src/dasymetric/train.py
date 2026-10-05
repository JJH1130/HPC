"""Stage 2: train the county model(s) (design: docs/dasymetric_v1.md, "Model training"; docs/dasymetric_v2.md;
eras: docs/dasymetric_v3.md).

For each era (one unnamed era without `eras:`), reads <version>/[<era>/]features/county_features.csv
(stage 1) and writes to <version>/[<era>/]model/:
  <model>.joblib                  fitted model + the feature list it expects (used by predict.py)
  folds.csv                       GISJOIN -> CV fold (used by the search and the comparison)
  feature_correlation.csv/.png    Spearman rho of the county features (before training)
  cv_results.csv                  every searched candidate
  best_params.json
  metrics.json                    best CV RMSE (mean, sd, per fold), CV R2, training RMSE / R2
  feature_importance.csv          impurity importance + permutation importance (training rows)
  shap_values.csv                 TreeExplainer SHAP per training row (shap_<feature>) + GISJOIN, year, y, y_hat
  shap_importance.csv             mean |SHAP| per feature
  shap_importance_grouped.csv     mean |sum of SHAP within a feature group| (feature_groups)
  shap_by_year.csv                mean |SHAP| per feature and year
  shap_summary.png, shap_by_year.png
  oof_predictions.csv             out-of-fold prediction per training row (+ the compare_with version's)
  compare_<version>.json          the `compare_with` version's CV on the same folds and rows
With eras, <version>/cv_summary.csv has one row per era (CV of the era model and of compare_with).

Folds: `folds_from: <version>` reuses that version's model/folds.csv (filtered to the era's counties);
otherwise GroupKFold(cv_folds) by GISJOIN, so all years of a county stay in one fold and CV measures
performance on unseen counties. The model and its search space come from configs/model.yaml.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import r2_score, root_mean_squared_error
from sklearn.base import clone
from sklearn.model_selection import GroupKFold, RandomizedSearchCV, cross_val_predict

import plots
from common import add_common_args, era_groups, load_config, log, log_args, out_dir, setup_logging


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(p)
    p.add_argument("--n-jobs", type=int, default=1, help="parallel search fits (sbatch: SLURM_CPUS_ON_NODE)")
    return p.parse_args(argv)


# ---------------------------------------------------------------- model registry

def make_rf(fixed: dict):
    from sklearn.ensemble import RandomForestRegressor
    return RandomForestRegressor(n_jobs=1, **fixed)  # parallelism is in the search


def not_in_v1(name):
    def build(fixed):
        sys.exit(f"ERROR: model {name!r} is a placeholder, not implemented in v1 (configs/model.yaml). "
                 "Use model: rf")
    return build


MODELS = {"rf": make_rf, "lgbm": not_in_v1("lgbm"), "xgb": not_in_v1("xgb"), "catboost": not_in_v1("catboost")}


def build_model(cfg: dict):
    name = cfg["model"]
    if name not in MODELS:
        sys.exit(f"ERROR: no builder for model {name!r}; known: {sorted(MODELS)}")
    entry = cfg["models"][name]
    estimator = MODELS[name](entry.get("fixed") or {})
    space = entry.get("space") or {}
    if not space:
        sys.exit(f"ERROR: models.{name}.space is empty in configs/model.yaml")
    return estimator, space


# ---------------------------------------------------------------- folds, correlation, comparison

def make_folds(groups: pd.Series, n_splits: int) -> pd.DataFrame:
    """GISJOIN -> fold from GroupKFold (deterministic for the same rows, so the same folds as v1)."""
    fold = np.full(len(groups), -1)
    for i, (_, test) in enumerate(GroupKFold(n_splits=n_splits).split(groups, groups=groups)):
        fold[test] = i
    return (pd.DataFrame({"GISJOIN": groups.to_numpy(), "fold": fold}).drop_duplicates()
            .sort_values(["fold", "GISJOIN"]).reset_index(drop=True))


def load_folds(cfg: dict, out_root: Path):
    """The `folds_from` version's GISJOIN -> fold table, or None (then each era gets GroupKFold folds)."""
    src = cfg.get("folds_from")
    if not src:
        return None
    path = out_root / cfg["name"] / src / "model" / "folds.csv"
    if not path.exists():
        sys.exit(f"ERROR: folds_from {src}: {path} not found (that version's train.py writes it)")
    folds = pd.read_csv(path)
    log.info("folds from %s: %d counties in %d folds", path, len(folds), folds["fold"].nunique())
    return folds


def splits_from_folds(groups: pd.Series, folds: pd.DataFrame, what: str):
    fold = groups.map(dict(zip(folds["GISJOIN"], folds["fold"])))
    if fold.isna().any():
        sys.exit(f"ERROR: {what}: counties without a fold: {sorted(groups[fold.isna()].unique())}")
    fold = fold.to_numpy()
    return [(np.where(fold != k)[0], np.where(fold == k)[0]) for k in sorted(np.unique(fold))]


def correlation_check(X: pd.DataFrame, threshold: float, mdir: Path):
    """Spearman rho over all training rows; logs pairs above the threshold, drops nothing."""
    rho = X.corr(method="spearman")
    rho.to_csv(mdir / "feature_correlation.csv", index_label="feature")
    log.info("Spearman rho of county features (all training rows):\n%s", rho.round(3).to_string())
    cols = list(rho.columns)
    pairs = [(a, b, rho.loc[a, b]) for i, a in enumerate(cols) for b in cols[i + 1:]
             if abs(rho.loc[a, b]) > threshold]
    for a, b, r in sorted(pairs, key=lambda t: -abs(t[2])):
        log.info("  |rho| > %.2f: %s - %s %.3f", threshold, a, b, r)
    if not pairs:
        log.info("  no pair with |rho| > %.2f", threshold)
    if {"age", "year"} <= set(cols):
        log.info("  age - year rho %.3f", rho.loc["age", "year"])
    plots.correlation_heatmap(rho, mdir / "feature_correlation.png")


def fold_metrics(df: pd.DataFrame, col: str) -> dict:
    """Fold-mean RMSE / R2 (as the search reports them) + pooled RMSE / R2 of the predictions in `col`."""
    rmse = [float(root_mean_squared_error(g["y"], g[col])) for _, g in df.groupby("fold")]
    r2 = [float(r2_score(g["y"], g[col])) for _, g in df.groupby("fold")]
    return {"cv_rmse_mean": float(np.mean(rmse)), "cv_rmse_sd": float(np.std(rmse)), "cv_rmse_folds": rmse,
            "cv_r2_mean": float(np.mean(r2)), "cv_r2_sd": float(np.std(r2)), "cv_r2_folds": r2,
            "pooled_rmse": float(root_mean_squared_error(df["y"], df[col])), "pooled_r2": float(r2_score(df["y"], df[col]))}


def compare_era(cfg: dict, prev: str, edir: Path, rows: pd.DataFrame, mdir: Path):
    """compare_with is a version with the same era: read its saved out-of-fold predictions (no refit). Each
    version is scored on its own target y (v3.1's y uses the unmasked cell area, v3's the polygon area)."""
    need = [edir / "model" / "oof_predictions.csv", edir / "model" / "metrics.json"]
    missing = [str(f) for f in need if not f.exists()]
    if missing:
        log.warning("compare_with %s skipped: missing %s", prev, missing)
        return None, None
    po = pd.read_csv(need[0]).rename(columns={"oof": f"oof_{prev}", "fold": "fold_prev"})
    pmet = json.loads(need[1].read_text())
    on = rows[["GISJOIN", "year", "fold"]].merge(po[["GISJOIN", "year", "fold_prev", "y", f"oof_{prev}"]],
                                                on=["GISJOIN", "year"], how="inner")
    if len(on) != len(rows):
        log.warning("compare_with %s: only %d of %d rows found in its predictions", prev, len(on), len(rows))
    if (on["fold"] != on["fold_prev"]).any():
        sys.exit(f"ERROR: compare_with {prev}: its folds differ from these ({int((on['fold'] != on['fold_prev']).sum())}"
                 " rows); use the same folds_from")
    res = {"version": prev, "model": pmet["model"], "features": pmet["features"], "n_rows_scored": len(on),
           "folds": "same as this model (checked)", "predictions": f"{prev}/{edir.name}/model/oof_predictions.csv",
           "target": f"{prev}'s own y", **fold_metrics(on, f"oof_{prev}"),
           "reported_cv_rmse_mean": pmet.get("cv_rmse_mean"), "reported_cv_r2_mean": pmet.get("cv_r2_mean")}
    (mdir / f"compare_{prev}.json").write_text(json.dumps(res, indent=2))
    log.info("%s (its saved out-of-fold predictions, same folds, %d rows, its own target): CV RMSE %.4f +/- %.4f | "
             "CV R2 %.3f +/- %.3f | pooled RMSE %.4f R2 %.3f (reported: RMSE %s, R2 %s)", prev, len(on),
             res["cv_rmse_mean"], res["cv_rmse_sd"], res["cv_r2_mean"], res["cv_r2_sd"], res["pooled_rmse"],
             res["pooled_r2"], pmet.get("cv_rmse_mean"), pmet.get("cv_r2_mean"))
    return res, on[["GISJOIN", "year", f"oof_{prev}"]].assign(**{f"y_{prev}": on["y"]})


def compare_previous(cfg: dict, out_root: Path, folds: pd.DataFrame, rows: pd.DataFrame, s: dict, n_jobs: int,
                     mdir: Path, era: str = ""):
    """The `compare_with` version scored on `rows` (GISJOIN, year, fold) only. If that version has the same
    era, its saved out-of-fold predictions are used (compare_era); otherwise (a pooled version) it is refit with
    its own features + best params on these folds over all its rows. Returns (summary, predictions)."""
    prev = cfg.get("compare_with")
    if not prev:
        return None, None
    pdir = out_root / cfg["name"] / prev
    if era and (pdir / era).is_dir():
        return compare_era(cfg, prev, pdir / era, rows, mdir)
    need = [pdir / "features" / "county_features.csv", pdir / "model" / "best_params.json",
            pdir / "model" / "metrics.json"]
    missing = [str(f) for f in need if not f.exists()]
    if missing:
        log.warning("compare_with %s skipped: missing %s", prev, missing)
        return None, None
    pdf = pd.read_csv(need[0])
    params = json.loads(need[1].read_text())
    pmet = json.loads(need[2].read_text())
    if pmet["model"] not in MODELS:
        log.warning("compare_with %s skipped: no builder for its model %r", prev, pmet["model"])
        return None, None
    est = MODELS[pmet["model"]](cfg["models"][pmet["model"]].get("fixed") or {}).set_params(**params)
    cv = splits_from_folds(pdf["GISJOIN"], folds, f"compare_with {prev}")
    pdf[f"oof_{prev}"] = cross_val_predict(est, pdf[pmet["features"]], pdf["y"], cv=cv, n_jobs=n_jobs)
    on = rows[["GISJOIN", "year", "fold"]].merge(pdf[["GISJOIN", "year", "y", f"oof_{prev}"]],
                                                on=["GISJOIN", "year"], how="inner")  # scored on its own y
    if len(on) != len(rows):
        log.warning("compare_with %s: only %d of %d rows found in its features", prev, len(on), len(rows))
    res = {"version": prev, "model": pmet["model"], "features": pmet["features"], "best_params": params,
           "n_rows_fit": len(pdf), "n_rows_scored": len(on), "folds": "same as this model (folds.csv)",
           **fold_metrics(on, f"oof_{prev}"), "all_rows_reported_cv_rmse_mean": pmet.get("cv_rmse_mean"),
           "all_rows_reported_cv_r2_mean": pmet.get("cv_r2_mean")}
    (mdir / f"compare_{prev}.json").write_text(json.dumps(res, indent=2))
    log.info("%s (refit on these folds, scored on these %d rows): CV RMSE %.4f +/- %.4f | CV R2 %.3f +/- %.3f | "
             "pooled RMSE %.4f R2 %.3f | fold RMSE %s (%s over all its rows as reported: RMSE %s, R2 %s)", prev,
             len(on), res["cv_rmse_mean"], res["cv_rmse_sd"], res["cv_r2_mean"], res["cv_r2_sd"],
             res["pooled_rmse"], res["pooled_r2"], " / ".join(f"{v:.3f}" for v in res["cv_rmse_folds"]), prev,
             pmet.get("cv_rmse_mean"), pmet.get("cv_r2_mean"))
    return res, on[["GISJOIN", "year", f"oof_{prev}"]].assign(**{f"y_{prev}": on["y"]})


# ---------------------------------------------------------------- SHAP

def shap_explain(model, X: pd.DataFrame, df: pd.DataFrame, pred: np.ndarray, cfg: dict, mdir: Path):
    """TreeExplainer SHAP on the training rows (docs/dasymetric_v2.md, "Explanation: SHAP")."""
    import shap
    sv = np.asarray(shap.TreeExplainer(model).shap_values(X))
    S = pd.DataFrame(sv, columns=list(X.columns), index=X.index)
    vals = df[["GISJOIN", "year", "y"]].copy()
    vals["y_hat"] = pred
    pd.concat([vals, S.add_prefix("shap_")], axis=1).to_csv(mdir / "shap_values.csv", index=False)

    imp = S.abs().mean().rename("mean_abs_shap").sort_values(ascending=False)
    imp.to_csv(mdir / "shap_importance.csv", index_label="feature")
    grouped = pd.Series({g: S[m].sum(axis=1).abs().mean() for g, m in era_groups(cfg, list(X.columns)).items()},
                        name="mean_abs_shap").sort_values(ascending=False)
    grouped.to_csv(mdir / "shap_importance_grouped.csv", index_label="group")
    by_year = S.abs().groupby(df["year"]).mean()
    by_year.to_csv(mdir / "shap_by_year.csv", index_label="year")
    log.info("mean |SHAP| per feature:\n%s", imp.round(4).to_string())
    log.info("grouped mean |SHAP|:\n%s", grouped.round(4).to_string())
    log.info("mean |SHAP| by year:\n%s", by_year.round(3).to_string())
    plots.shap_summary(sv, X, mdir / "shap_summary.png")
    plots.shap_by_year(by_year, mdir / "shap_by_year.png", cfg["all_features"])
    return grouped


# ---------------------------------------------------------------- main

def train_era(cfg: dict, era: str, args, all_folds) -> dict:
    out = out_dir(cfg, args.out_root, era)
    feats = cfg["eras"][era]["features"]
    tag = f"era {era}: " if era else ""
    path = out / "features" / "county_features.csv"
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (run stage 1, county_features.py, first)")
    df = pd.read_csv(path)
    missing = [f for f in feats if f not in df.columns]
    if missing:
        sys.exit(f"ERROR: {path} lacks features {missing}; rerun stage 1 with the current config")
    X, y, groups = df[feats], df["y"], df["GISJOIN"]
    log.info("%straining rows: %d county-years | %d counties (groups) | %d years %d-%d | features %s", tag,
             len(df), groups.nunique(), df["year"].nunique(), df["year"].min(), df["year"].max(), feats)

    estimator, space = build_model(cfg)
    s = cfg["search"]
    mdir = out / "model"
    mdir.mkdir(parents=True, exist_ok=True)
    if all_folds is None:
        if groups.nunique() < s["cv_folds"]:
            sys.exit(f"ERROR: {tag}{groups.nunique()} counties < cv_folds {s['cv_folds']}")
        all_folds = make_folds(groups, s["cv_folds"])
        source = f"GroupKFold({s['cv_folds']}) by GISJOIN"
    else:
        source = f"{cfg['folds_from']}/model/folds.csv by GISJOIN"
    folds = all_folds[all_folds["GISJOIN"].isin(groups)].reset_index(drop=True)
    cv = splits_from_folds(groups, folds, f"{tag}training rows")
    if len(cv) < 2:
        sys.exit(f"ERROR: {tag}only {len(cv)} fold among the counties")
    folds.to_csv(mdir / "folds.csv", index=False)
    log.info("%sfolds (%s): counties per fold %s -> %s", tag, source,
             folds["fold"].value_counts().sort_index().to_dict(), mdir / "folds.csv")
    correlation_check(X, cfg.get("correlation_threshold", 0.8), mdir)
    n_cand = int(np.prod([len(v) for v in space.values()]))
    log.info("%smodel %s | search %d of %d candidates | %d folds | scoring %s | n_jobs %d", tag, cfg["model"],
             min(s["n_iter"], n_cand), n_cand, len(cv), s["scoring"], args.n_jobs)
    search = RandomizedSearchCV(
        estimator, space, n_iter=s["n_iter"], random_state=s["random_state"],
        scoring={"score": s["scoring"], "r2": "r2"}, refit="score",
        cv=cv, n_jobs=args.n_jobs, error_score="raise")
    search.fit(X, y)

    res, best = search.cv_results_, search.best_index_
    rmse_folds = [-float(res[f"split{i}_test_score"][best]) for i in range(len(cv))]
    r2_folds = [float(res[f"split{i}_test_r2"][best]) for i in range(len(cv))]
    for i, (r, q) in enumerate(zip(rmse_folds, r2_folds)):
        log.info("  fold %d: CV RMSE %.4f | R2 %.3f", i, r, q)
    model = search.best_estimator_
    pred = model.predict(X)
    metrics = {
        "model": cfg["model"], "version": cfg["version"], "era": era or None, "features": feats,
        "n_rows": len(df), "n_counties": int(groups.nunique()), "n_years": int(df["year"].nunique()),
        "cv": f"{len(cv)} folds, {source}", "scoring": s["scoring"],
        "cv_rmse_mean": float(np.mean(rmse_folds)), "cv_rmse_sd": float(np.std(rmse_folds)),
        "cv_rmse_folds": rmse_folds,
        "cv_r2_mean": float(np.mean(r2_folds)), "cv_r2_sd": float(np.std(r2_folds)), "cv_r2_folds": r2_folds,
        "train_rmse": float(root_mean_squared_error(y, pred)), "train_r2": float(r2_score(y, pred)),
        "y_sd": float(y.std(ddof=0)),
        "target": ("log(pop / (0.0625 x unmasked cells))" if cfg.get("water_mask")
                   else "log(pop / polygon area_km2)"),
    }
    log.info("%sbest params %s", tag, search.best_params_)
    log.info("%sCV RMSE %.4f +/- %.4f | CV R2 %.3f +/- %.3f | train RMSE %.4f | sd(y) %.4f", tag,
             metrics["cv_rmse_mean"], metrics["cv_rmse_sd"], metrics["cv_r2_mean"], metrics["cv_r2_sd"],
             metrics["train_rmse"], metrics["y_sd"])

    p = cfg["permutation"]
    perm = permutation_importance(model, X, y, scoring=s["scoring"], n_repeats=p["n_repeats"],
                                  random_state=p["random_state"], n_jobs=args.n_jobs)
    imp = pd.DataFrame({"feature": feats,
                        "impurity": getattr(model, "feature_importances_", np.full(len(feats), np.nan)),
                        "permutation_mean": perm.importances_mean, "permutation_sd": perm.importances_std})
    imp = imp.sort_values("permutation_mean", ascending=False)
    log.info("feature importance (permutation = increase in RMSE when shuffled):\n%s",
             imp.round(4).to_string(index=False))

    joblib.dump({"model": model, "features": feats, "name": cfg["model"], "version": cfg["version"],
                 "era": era or None, "years": cfg["eras"][era]["years"], "use_status": cfg["use_status"],
                 "water_mask": bool(cfg.get("water_mask"))},
                mdir / f"{cfg['model']}.joblib")
    cvr = pd.DataFrame(res)
    cvr["params"] = cvr["params"].astype(str)
    cvr.sort_values("rank_test_score").to_csv(mdir / "cv_results.csv", index=False)
    (mdir / "best_params.json").write_text(json.dumps(search.best_params_, indent=2))
    imp.to_csv(mdir / "feature_importance.csv", index=False)
    grouped = shap_explain(model, X, df, pred, cfg, mdir)

    # out-of-fold predictions of the chosen parameters (same folds, so the fold scores equal the search's)
    oof = df[["GISJOIN", "year", "y"]].copy()
    oof["fold"] = groups.map(dict(zip(folds["GISJOIN"], folds["fold"]))).to_numpy()
    oof["oof"] = cross_val_predict(clone(model), X, y, cv=cv, n_jobs=args.n_jobs)
    metrics.update({f"oof_{k}": v for k, v in fold_metrics(oof, "oof").items() if k.startswith("pooled")})
    prev, prev_oof = compare_previous(cfg, args.out_root, all_folds, oof, s, args.n_jobs, mdir, era)
    if prev_oof is not None:
        oof = oof.merge(prev_oof, on=["GISJOIN", "year"], how="left")
    oof.to_csv(mdir / "oof_predictions.csv", index=False)
    (mdir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    row = {"era": era or None, "years": f"{int(df['year'].min())}-{int(df['year'].max())}", "n_rows": len(df),
           "n_counties": int(groups.nunique()), "n_folds": len(cv), "features": " ".join(feats),
           "cv_rmse": metrics["cv_rmse_mean"], "cv_r2": metrics["cv_r2_mean"],
           "pooled_rmse": metrics["oof_pooled_rmse"], "pooled_r2": metrics["oof_pooled_r2"]}
    row.update({f"shap_{g}": v for g, v in grouped.items()})
    if prev:
        log.info("%sCV %s vs %s (same folds and rows): RMSE %.4f vs %.4f | R2 %.3f vs %.3f | pooled RMSE %.4f vs "
                 "%.4f", tag, cfg["version"], prev["version"], metrics["cv_rmse_mean"], prev["cv_rmse_mean"],
                 metrics["cv_r2_mean"], prev["cv_r2_mean"], metrics["oof_pooled_rmse"], prev["pooled_rmse"])
        row.update({f"{prev['version']}_cv_rmse": prev["cv_rmse_mean"], f"{prev['version']}_cv_r2": prev["cv_r2_mean"],
                    f"{prev['version']}_pooled_rmse": prev["pooled_rmse"],
                    f"{prev['version']}_pooled_r2": prev["pooled_r2"]})
    log.info("wrote %s", mdir)
    return row


def main(argv=None):
    setup_logging()
    args = parse_args(argv)
    log_args(args)
    cfg = load_config(args.config)
    if cfg.get("compare_with") and not cfg.get("folds_from") and len(cfg["eras"]) > 1:
        sys.exit("ERROR: with several eras, compare_with needs folds_from (one fold table for all counties)")
    all_folds = load_folds(cfg, args.out_root)
    rows = [train_era(cfg, era, args, all_folds) for era in cfg["eras"]]
    if len(rows) > 1 or rows[0]["era"]:
        summary = pd.DataFrame(rows)
        path = out_dir(cfg, args.out_root) / "cv_summary.csv"
        summary.to_csv(path, index=False)
        log.info("CV by era:\n%s", summary.drop(columns="features").round(3).to_string(index=False))
        log.info("wrote %s", path)
    log.info("DONE")


if __name__ == "__main__":
    main()
