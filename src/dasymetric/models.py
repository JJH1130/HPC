"""Model registry and search spaces for train.py / predict.py (CONUS model family: docs/conus_plan.md, "Model family").

Builders take the config's `models.<name>.fixed` constructor arguments. Every model runs single-threaded and quiet;
the parallelism is in the search (RandomizedSearchCV n_jobs), as for RF since v1. No early stopping: every model
goes through the same CV procedure.

A search space (`models.<name>.space`) maps a hyperparameter to either a list of candidates (one is drawn) or a
distribution:
    {dist: loguniform, low: a, high: b}   scipy.stats.loguniform(a, b)
    {dist: uniform, low: a, high: b}      scipy.stats.uniform(a, b - a)
    {dist: randint, low: a, high: b}      scipy.stats.randint(a, b + 1)   (b included)
"""
from __future__ import annotations

import math
import sys

import numpy as np
from scipy import stats


def make_rf(fixed: dict):
    from sklearn.ensemble import RandomForestRegressor
    return RandomForestRegressor(**{"n_jobs": 1, **fixed})  # parallelism is in the search


def make_lgbm(fixed: dict):
    from lightgbm import LGBMRegressor
    return LGBMRegressor(**{"n_jobs": 1, "verbose": -1, **fixed})


def make_xgb(fixed: dict):
    from xgboost import XGBRegressor
    return XGBRegressor(**{"n_jobs": 1, "verbosity": 0, "tree_method": "hist", **fixed})


def make_catboost(fixed: dict):
    from catboost import CatBoostRegressor
    return CatBoostRegressor(**{"thread_count": 1, "verbose": 0, "allow_writing_files": False, **fixed})


MODELS = {"rf": make_rf, "lgbm": make_lgbm, "xgb": make_xgb, "catboost": make_catboost}
DISTS = ("loguniform", "uniform", "randint")


def set_threads(model, n: int):
    """Prediction threads of a loaded model (predict.py). CatBoost predicts on all cores by default."""
    if type(model).__name__ == "CatBoostRegressor":
        return
    if hasattr(model, "n_jobs"):
        try:
            model.set_params(n_jobs=n)  # XGBoost / LightGBM pass it to the booster at predict time
        except (ValueError, TypeError):
            model.n_jobs = n


def distribution(key: str, d: dict):
    dist, lo, hi = d.get("dist"), d.get("low"), d.get("high")
    if dist not in DISTS or lo is None or hi is None:
        sys.exit(f"ERROR: space.{key}: {d} must be {{dist: {'|'.join(DISTS)}, low: .., high: ..}}")
    lo, hi = float(lo), float(hi)
    if dist == "randint":
        if lo != int(lo) or hi != int(hi) or lo > hi:
            sys.exit(f"ERROR: space.{key}: randint needs whole numbers low <= high, got {d}")
        return stats.randint(int(lo), int(hi) + 1)
    if not lo < hi or (dist == "loguniform" and lo <= 0):
        sys.exit(f"ERROR: space.{key}: {dist} needs low < high{' and low > 0' if dist == 'loguniform' else ''}, got {d}")
    return stats.loguniform(lo, hi) if dist == "loguniform" else stats.uniform(lo, hi - lo)


def parse_space(space: dict) -> tuple[dict, int | None]:
    """(space for RandomizedSearchCV, number of distinct candidates or None when a distribution is in it)."""
    out, finite = {}, True
    for key, v in space.items():
        if isinstance(v, dict):
            out[key] = distribution(key, v)
            finite = False
        elif isinstance(v, (list, tuple)) and len(v):
            out[key] = list(v)
        else:
            sys.exit(f"ERROR: space.{key}: {v!r} must be a non-empty list or a distribution {{dist, low, high}}")
    return out, (math.prod(len(v) for v in out.values()) if finite else None)


def plain(value):
    """numpy scalars -> Python (best_params from scipy distributions hold numpy ints / floats) for JSON."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value
