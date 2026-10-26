"""Test of src/dasymetric/models.py (model registry + search spaces), runnable without the cluster:

    python tests/test_models.py        (needs the hisdac env: numpy, scipy, scikit-learn, lightgbm, xgboost, catboost)

Checks: list spaces as before (the Massachusetts configs/model.yaml RF space: 400 candidates, values unchanged);
loguniform / uniform / randint (both ends included) draw inside their bounds; bad definitions stop; numpy values
become plain Python for JSON; every builder is single-threaded, quiet and takes the config's fixed arguments; each
model runs RandomizedSearchCV with distributions, survives a pickle round trip and set_threads.
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "dasymetric"))

import models  # noqa: E402


def stops(fn, *a):
    try:
        fn(*a)
    except SystemExit as e:
        return str(e)
    raise AssertionError(f"expected SystemExit from {fn.__name__}{a}")


def test_lists():
    cfg = yaml.safe_load((REPO / "configs" / "model.yaml").read_text(encoding="utf-8"))
    space = cfg["models"]["rf"]["space"]
    out, n = models.parse_space(space)
    assert n == 400 and out == space, (n, out)
    _, n = models.parse_space({"a": [1], "b": [None, 5]})
    assert n == 2
    print("ok lists: Massachusetts RF space unchanged (400 candidates)")


def test_distributions():
    out, n = models.parse_space({"lr": {"dist": "loguniform", "low": 0.01, "high": 0.2},
                                 "sub": {"dist": "uniform", "low": 0.5, "high": 1.0},
                                 "k": {"dist": "randint", "low": 3, "high": 8},
                                 "depth": [None, 5]})
    assert n is None, "a distribution makes the space continuous"
    rng = np.random.default_rng(0)
    lr = out["lr"].rvs(5000, random_state=rng)
    sub = out["sub"].rvs(5000, random_state=rng)
    k = out["k"].rvs(5000, random_state=rng)
    assert lr.min() >= 0.01 and lr.max() <= 0.2 and abs(np.median(np.log(lr)) - np.log(np.sqrt(0.01 * 0.2))) < 0.1
    assert sub.min() >= 0.5 and sub.max() <= 1.0
    assert k.min() == 3 and k.max() == 8, "randint includes both ends"
    assert out["depth"] == [None, 5]
    assert "randint" in stops(models.parse_space, {"k": {"dist": "randint", "low": 1.5, "high": 4}})
    assert "low > 0" in stops(models.parse_space, {"lr": {"dist": "loguniform", "low": 0, "high": 1}})
    assert "low < high" in stops(models.parse_space, {"s": {"dist": "uniform", "low": 1, "high": 1}})
    assert "must be" in stops(models.parse_space, {"s": {"dist": "normal", "low": 0, "high": 1}})
    assert "non-empty list" in stops(models.parse_space, {"s": []})
    assert "non-empty list" in stops(models.parse_space, {"s": 3})
    best = {"n_estimators": np.int64(300), "learning_rate": np.float64(0.05), "max_depth": None}
    assert json.loads(json.dumps(models.plain(best))) == {"n_estimators": 300, "learning_rate": 0.05, "max_depth": None}
    print("ok distributions: bounds, randint ends included, bad definitions stop, plain JSON")


def test_builders():
    from sklearn.model_selection import RandomizedSearchCV
    rng = np.random.default_rng(1)
    X = pd.DataFrame(rng.standard_normal((300, 4)), columns=list("abcd"))
    y = 2 * X["a"] - X["b"] + 0.1 * rng.standard_normal(300)
    spaces = {
        "rf": ({"random_state": 42}, {"n_estimators": {"dist": "randint", "low": 20, "high": 40},
                                      "max_features": [0.5, 1.0]}),
        "lgbm": ({"random_state": 42, "subsample_freq": 1},
                 {"n_estimators": {"dist": "randint", "low": 20, "high": 40},
                  "learning_rate": {"dist": "loguniform", "low": 0.05, "high": 0.2},
                  "subsample": {"dist": "uniform", "low": 0.6, "high": 1.0}}),
        "xgb": ({"random_state": 42}, {"n_estimators": {"dist": "randint", "low": 20, "high": 40},
                                       "max_depth": {"dist": "randint", "low": 2, "high": 4}}),
        "catboost": ({"random_seed": 42, "bootstrap_type": "Bernoulli"},
                     {"iterations": {"dist": "randint", "low": 20, "high": 40},
                      "subsample": {"dist": "uniform", "low": 0.6, "high": 1.0}}),
    }
    threads = {"rf": ("n_jobs", 1), "lgbm": ("n_jobs", 1), "xgb": ("n_jobs", 1), "catboost": ("thread_count", 1)}
    for name, (fixed, space) in spaces.items():
        est = models.MODELS[name](fixed)
        params = est.get_params()
        key, val = threads[name]
        assert params[key] == val, (name, key, params[key])
        assert all(params[k] == v for k, v in fixed.items()), name
        if name == "lgbm":
            assert params["verbose"] == -1
        if name == "xgb":
            assert params["verbosity"] == 0 and params["tree_method"] == "hist"
        if name == "catboost":
            assert params["verbose"] == 0 and params["allow_writing_files"] is False
        sp, n = models.parse_space(space)
        s = RandomizedSearchCV(est, sp, n_iter=3, cv=3, n_jobs=2, random_state=0,
                               scoring="neg_root_mean_squared_error").fit(X, y)
        assert len(s.cv_results_["params"]) == 3
        best = models.plain(s.best_params_)
        lo, hi = (space.get("n_estimators") or space["iterations"])["low"], (space.get("n_estimators") or space["iterations"])["high"]
        assert lo <= best.get("n_estimators", best.get("iterations")) <= hi and json.dumps(best)
        m = pickle.loads(pickle.dumps(s.best_estimator_))
        models.set_threads(m, 4)
        p = m.predict(X)
        assert np.allclose(p, s.best_estimator_.predict(X), atol=1e-6) and 1 - ((p - y) ** 2).sum() / ((y - y.mean()) ** 2).sum() > 0.6, name
        print(f"ok {name}: single-threaded and quiet, search with distributions {best}, pickle, set_threads")


if __name__ == "__main__":
    test_lists()
    test_distributions()
    test_builders()
    print("ALL OK")
