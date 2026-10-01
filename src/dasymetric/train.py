"""Stage 2: train the county model (design: docs/dasymetric_v1.md, "Model training").

Reads features/county_features.csv (stage 1) and writes to <out-root>/<name>/<version>/model/:
  <model>.joblib            fitted model + the feature list it expects (used by predict.py)
  cv_results.csv            every searched candidate
  best_params.json
  metrics.json              best CV RMSE (mean, sd, per fold), CV R2, training RMSE / R2
  feature_importance.csv    impurity importance + permutation importance (training rows)

The model and its search space come from configs/model.yaml (`model:` picks the entry under
`models:`). RandomizedSearchCV with GroupKFold, groups = GISJOIN, so all years of a county stay
in one fold and CV measures performance on unseen counties.
"""
from __future__ import annotations

import argparse
import json
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import r2_score, root_mean_squared_error
from sklearn.model_selection import GroupKFold, RandomizedSearchCV

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
    n_cand = int(np.prod([len(v) for v in space.values()]))
    log.info("model %s | search %d of %d candidates | GroupKFold(%d) by GISJOIN | scoring %s | n_jobs %d",
             cfg["model"], min(s["n_iter"], n_cand), n_cand, s["cv_folds"], s["scoring"], args.n_jobs)
    search = RandomizedSearchCV(
        estimator, space, n_iter=s["n_iter"], random_state=s["random_state"],
        scoring={"score": s["scoring"], "r2": "r2"}, refit="score",
        cv=GroupKFold(n_splits=s["cv_folds"]), n_jobs=args.n_jobs, error_score="raise")
    search.fit(X, y, groups=groups)

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

    mdir = out / "model"
    mdir.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": cfg["features"], "name": cfg["model"], "version": cfg["version"],
                 "use_status": cfg["use_status"]}, mdir / f"{cfg['model']}.joblib")
    cv = pd.DataFrame(res)
    cv["params"] = cv["params"].astype(str)
    cv.sort_values("rank_test_score").to_csv(mdir / "cv_results.csv", index=False)
    (mdir / "best_params.json").write_text(json.dumps(search.best_params_, indent=2))
    (mdir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    imp.to_csv(mdir / "feature_importance.csv", index=False)
    log.info("wrote %s", mdir)
    log.info("DONE")


if __name__ == "__main__":
    main()
