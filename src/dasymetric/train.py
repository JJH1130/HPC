"""Stage 2: train the county model (design: docs/dasymetric_v1.md, "Model training"; docs/dasymetric_v2.md).

Reads features/county_features.csv (stage 1) and writes to <out-root>/<name>/<version>/model/:
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
  compare_<version>.json          the `compare_with` version's CV recomputed on these folds

The model and its search space come from configs/model.yaml (`model:` picks the entry under
`models:`). RandomizedSearchCV with GroupKFold, groups = GISJOIN, so all years of a county stay
in one fold and CV measures performance on unseen counties.
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
from sklearn.model_selection import GroupKFold, RandomizedSearchCV, cross_validate

import plots
from common import add_common_args, load_config, log, log_args, out_dir, setup_logging


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


def compare_previous(cfg: dict, out_root: Path, folds: pd.DataFrame, s: dict, n_jobs: int, mdir: Path):
    """Recompute the `compare_with` version's CV (its own features + best params) on these folds."""
    prev = cfg.get("compare_with")
    if not prev:
        return None
    pdir = out_root / cfg["name"] / prev
    need = [pdir / "features" / "county_features.csv", pdir / "model" / "best_params.json",
            pdir / "model" / "metrics.json"]
    missing = [str(f) for f in need if not f.exists()]
    if missing:
        log.warning("compare_with %s skipped: missing %s", prev, missing)
        return None
    pdf = pd.read_csv(need[0])
    params = json.loads(need[1].read_text())
    pmet = json.loads(need[2].read_text())
    if pmet["model"] not in MODELS:
        log.warning("compare_with %s skipped: no builder for its model %r", prev, pmet["model"])
        return None
    est = MODELS[pmet["model"]](cfg["models"][pmet["model"]].get("fixed") or {}).set_params(**params)
    cv = splits_from_folds(pdf["GISJOIN"], folds, f"compare_with {prev}")
    r = cross_validate(est, pdf[pmet["features"]], pdf["y"], cv=cv, n_jobs=n_jobs,
                       scoring={"score": s["scoring"], "r2": "r2"}, error_score="raise")
    rmse = [-float(v) for v in r["test_score"]]
    r2 = [float(v) for v in r["test_r2"]]
    res = {"version": prev, "model": pmet["model"], "features": pmet["features"], "best_params": params,
           "n_rows": len(pdf), "folds": f"{cfg['version']}/model/folds.csv",
           "cv_rmse_mean": float(np.mean(rmse)), "cv_rmse_sd": float(np.std(rmse)), "cv_rmse_folds": rmse,
           "cv_r2_mean": float(np.mean(r2)), "cv_r2_sd": float(np.std(r2)), "cv_r2_folds": r2,
           "reported_cv_rmse_mean": pmet.get("cv_rmse_mean"), "reported_cv_r2_mean": pmet.get("cv_r2_mean")}
    (mdir / f"compare_{prev}.json").write_text(json.dumps(res, indent=2))
    log.info("%s recomputed on %s folds: CV RMSE %.4f +/- %.4f | CV R2 %.3f +/- %.3f "
             "(reported by %s: RMSE %s, R2 %s) | fold RMSE %s", prev, cfg["version"], res["cv_rmse_mean"],
             res["cv_rmse_sd"], res["cv_r2_mean"], res["cv_r2_sd"], prev, pmet.get("cv_rmse_mean"),
             pmet.get("cv_r2_mean"), " / ".join(f"{v:.3f}" for v in rmse))
    return res


# ---------------------------------------------------------------- SHAP

def shap_explain(model, X: pd.DataFrame, df: pd.DataFrame, pred: np.ndarray, cfg: dict, mdir: Path):
    """TreeExplainer SHAP on the training rows (docs/dasymetric_v2.md, "Explanation: SHAP")."""
    import shap
    sv = np.asarray(shap.TreeExplainer(model).shap_values(X))
    S = pd.DataFrame(sv, columns=cfg["features"], index=X.index)
    vals = df[["GISJOIN", "year", "y"]].copy()
    vals["y_hat"] = pred
    pd.concat([vals, S.add_prefix("shap_")], axis=1).to_csv(mdir / "shap_values.csv", index=False)

    imp = S.abs().mean().rename("mean_abs_shap").sort_values(ascending=False)
    imp.to_csv(mdir / "shap_importance.csv", index_label="feature")
    grouped = pd.Series({g: S[m].sum(axis=1).abs().mean() for g, m in cfg["feature_groups"].items()},
                        name="mean_abs_shap").sort_values(ascending=False)
    grouped.to_csv(mdir / "shap_importance_grouped.csv", index_label="group")
    by_year = S.abs().groupby(df["year"]).mean()
    by_year.to_csv(mdir / "shap_by_year.csv", index_label="year")
    log.info("mean |SHAP| per feature:\n%s", imp.round(4).to_string())
    log.info("grouped mean |SHAP|:\n%s", grouped.round(4).to_string())
    log.info("mean |SHAP| by year:\n%s", by_year.round(3).to_string())
    plots.shap_summary(sv, X, mdir / "shap_summary.png")
    plots.shap_by_year(by_year, mdir / "shap_by_year.png")


# ---------------------------------------------------------------- main

def main(argv=None):
    setup_logging()
    args = parse_args(argv)
    log_args(args)
    cfg = load_config(args.config)
    out = out_dir(cfg, args.out_root)
    path = out / "features" / "county_features.csv"
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (run stage 1, county_features.py, first)")
    df = pd.read_csv(path)
    missing = [f for f in cfg["features"] if f not in df.columns]
    if missing:
        sys.exit(f"ERROR: {path} lacks features {missing}; rerun stage 1 with the current config")
    X, y, groups = df[cfg["features"]], df["y"], df["GISJOIN"]
    log.info("training rows: %d county-years | %d counties (groups) | %d years | features %s",
             len(df), groups.nunique(), df["year"].nunique(), cfg["features"])

    estimator, space = build_model(cfg)
    s = cfg["search"]
    if groups.nunique() < s["cv_folds"]:
        sys.exit(f"ERROR: {groups.nunique()} counties < cv_folds {s['cv_folds']}")
    mdir = out / "model"
    mdir.mkdir(parents=True, exist_ok=True)
    folds = make_folds(groups, s["cv_folds"])
    folds.to_csv(mdir / "folds.csv", index=False)
    cv = splits_from_folds(groups, folds, "training rows")
    log.info("folds: counties per fold %s -> %s", folds["fold"].value_counts().sort_index().tolist(),
             mdir / "folds.csv")
    correlation_check(X, cfg.get("correlation_threshold", 0.8), mdir)
    n_cand = int(np.prod([len(v) for v in space.values()]))
    log.info("model %s | search %d of %d candidates | GroupKFold(%d) by GISJOIN | scoring %s | n_jobs %d",
             cfg["model"], min(s["n_iter"], n_cand), n_cand, s["cv_folds"], s["scoring"], args.n_jobs)
    search = RandomizedSearchCV(
        estimator, space, n_iter=s["n_iter"], random_state=s["random_state"],
        scoring={"score": s["scoring"], "r2": "r2"}, refit="score",
        cv=cv, n_jobs=args.n_jobs, error_score="raise")
    search.fit(X, y)

    res, best = search.cv_results_, search.best_index_
    rmse_folds = [-float(res[f"split{i}_test_score"][best]) for i in range(s["cv_folds"])]
    r2_folds = [float(res[f"split{i}_test_r2"][best]) for i in range(s["cv_folds"])]
    for i, (r, q) in enumerate(zip(rmse_folds, r2_folds)):
        log.info("  fold %d: CV RMSE %.4f | R2 %.3f", i, r, q)
    model = search.best_estimator_
    pred = model.predict(X)
    metrics = {
        "model": cfg["model"], "version": cfg["version"], "features": cfg["features"],
        "n_rows": len(df), "n_counties": int(groups.nunique()), "n_years": int(df["year"].nunique()),
        "cv": f"GroupKFold({s['cv_folds']}) by GISJOIN", "scoring": s["scoring"],
        "cv_rmse_mean": float(np.mean(rmse_folds)), "cv_rmse_sd": float(np.std(rmse_folds)),
        "cv_rmse_folds": rmse_folds,
        "cv_r2_mean": float(np.mean(r2_folds)), "cv_r2_sd": float(np.std(r2_folds)), "cv_r2_folds": r2_folds,
        "train_rmse": float(root_mean_squared_error(y, pred)), "train_r2": float(r2_score(y, pred)),
        "y_sd": float(y.std(ddof=0)),
    }
    log.info("best params %s", search.best_params_)
    log.info("CV RMSE %.4f +/- %.4f | CV R2 %.3f +/- %.3f | train RMSE %.4f | sd(y) %.4f",
             metrics["cv_rmse_mean"], metrics["cv_rmse_sd"], metrics["cv_r2_mean"], metrics["cv_r2_sd"],
             metrics["train_rmse"], metrics["y_sd"])

    p = cfg["permutation"]
    perm = permutation_importance(model, X, y, scoring=s["scoring"], n_repeats=p["n_repeats"],
                                  random_state=p["random_state"], n_jobs=args.n_jobs)
    imp = pd.DataFrame({"feature": cfg["features"],
                        "impurity": getattr(model, "feature_importances_", np.full(len(cfg["features"]), np.nan)),
                        "permutation_mean": perm.importances_mean, "permutation_sd": perm.importances_std})
    imp = imp.sort_values("permutation_mean", ascending=False)
    log.info("feature importance (permutation = increase in RMSE when shuffled):\n%s",
             imp.round(4).to_string(index=False))

    joblib.dump({"model": model, "features": cfg["features"], "name": cfg["model"], "version": cfg["version"],
                 "use_status": cfg["use_status"]}, mdir / f"{cfg['model']}.joblib")
    cv = pd.DataFrame(res)
    cv["params"] = cv["params"].astype(str)
    cv.sort_values("rank_test_score").to_csv(mdir / "cv_results.csv", index=False)
    (mdir / "best_params.json").write_text(json.dumps(search.best_params_, indent=2))
    (mdir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    imp.to_csv(mdir / "feature_importance.csv", index=False)

    shap_explain(model, X, df, pred, cfg, mdir)
    prev = compare_previous(cfg, args.out_root, folds, s, args.n_jobs, mdir)
    if prev:
        log.info("CV %s vs %s (same folds): RMSE %.4f vs %.4f | R2 %.3f vs %.3f", cfg["version"], prev["version"],
                 metrics["cv_rmse_mean"], prev["cv_rmse_mean"], metrics["cv_r2_mean"], prev["cv_r2_mean"])
    log.info("wrote %s", mdir)
    log.info("DONE")


if __name__ == "__main__":
    main()
