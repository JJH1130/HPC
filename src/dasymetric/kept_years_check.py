"""Years that a --years run must leave as they are (v5.7 all years, docs/conus_plan.md "v5.7 all years"; request
docs/handoff/v57_all_years_request.md): a snapshot of their files before the run, checked again after it.

  snapshot  (login node, before submitting; seconds) per kept year: sha256 of the small era files on scratch
            (<dasym>/<version>/Y<year>/model/metrics.json, .../features/county_features.csv) and of every *.json /
            *.csv copied to <results>/dasymetric/<name>/<version>/Y<year>/; size + mtime of the big ones (the fitted
            model *.joblib, predictions/pop_<year>.tif: a rewrite changes the mtime); the year's rows of cv_summary.csv,
            qa/water_mask_by_year.csv, qa/reallocation_qa.csv (scratch) and, with --validation-dir, tract_errors_<year>.csv
            and the year's rows of metrics_by_year.csv (a rerun of the tract validation must give the same numbers) ->
            --out JSON.
  check     (a job after the run) recomputes every item of the JSON: `MATCH <item>` or `DIFFERS <item>: before ... |
            after ...` per item, then one line `KEPT YEARS OK: n items` or `KEPT YEARS DIFFERS: k of n items`; exit 1 on a
            difference or a missing file (nothing depends on the job).

CSV rows are compared on a canonical form (numeric columns as float64, the rest as text, rows sorted, only the columns
of the snapshot), so a column the run adds for the new years or an int column that becomes float does not count as a
change; a changed value does.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["snapshot", "check"])
    p.add_argument("--json", type=Path, required=True, help="snapshot: written; check: read")
    p.add_argument("--version-dir", type=Path, help="snapshot: <dasym-root>/<name>/<version> (scratch)")
    p.add_argument("--results-dir", type=Path, help="snapshot: results/dasymetric/<name>/<version>")
    p.add_argument("--validation-dir", type=Path, help="snapshot: results/validation/<name>/<version> (optional)")
    p.add_argument("--years", type=int, nargs="+", help="snapshot: the years that must stay")
    return p.parse_args(argv)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stat(path: Path) -> str:
    s = path.stat()
    return f"size {s.st_size} mtime_ns {s.st_mtime_ns}"


def canonical(df: pd.DataFrame, cols: list) -> str:
    """sha256 of the rows on `cols`: numeric columns as float64 (repr), the rest as text, rows sorted."""
    out = pd.DataFrame(index=df.index)
    for c in cols:
        s = df[c]
        if s.dtype == bool:
            s = s.astype(float)
        if pd.api.types.is_numeric_dtype(s):
            out[c] = [repr(float(v)) for v in s.to_numpy(dtype=float)]
        else:
            out[c] = s.astype(str)
    out = out.sort_values(cols, kind="stable")
    return hashlib.sha256(out.to_csv(index=False).encode()).hexdigest()


def rows_item(path: Path, col: str, value, cols=None) -> dict:
    """{'kind': 'rows', ...} of the rows of `path` where `col` == value (value None = every row; cols = the columns
    to compare, default all)."""
    df = pd.read_csv(path)
    if value is not None and col not in df:
        raise KeyError(f"{path} has no column {col}")
    sub = df if value is None else df[df[col].astype(str) == str(value)]
    cols = cols or list(df.columns)
    missing = [c for c in cols if c not in df]
    if missing:
        raise KeyError(f"{path} lacks columns {missing}")
    return {"kind": "rows", "path": str(path), "col": col, "value": value, "cols": cols, "n": len(sub),
            "hash": canonical(sub, cols)}


def file_item(path: Path, how: str) -> dict:
    return {"kind": how, "path": str(path), "value": sha(path) if how == "sha256" else stat(path)}


def snapshot(args) -> dict:
    items = {}
    v, r = args.version_dir, args.results_dir

    def add(name, fn, *a):
        try:
            items[name] = fn(*a)
        except (OSError, KeyError) as e:
            sys.exit(f"ERROR: snapshot {name}: {e}")

    for y in args.years:
        e = f"Y{y}"
        add(f"{y} scratch metrics.json", file_item, v / e / "model" / "metrics.json", "sha256")
        add(f"{y} scratch county_features.csv", file_item, v / e / "features" / "county_features.csv", "sha256")
        models = sorted((v / e / "model").glob("*.joblib"))
        if len(models) != 1:
            sys.exit(f"ERROR: {v / e / 'model'}: {len(models)} *.joblib files (one expected)")
        add(f"{y} scratch {models[0].name}", file_item, models[0], "stat")
        add(f"{y} scratch pop_{y}.tif", file_item, v / "predictions" / f"pop_{y}.tif", "stat")
        res = sorted(list((r / e).glob("*.json")) + list((r / e).glob("*.csv")))
        if not res:
            sys.exit(f"ERROR: no *.json / *.csv in {r / e}")
        for f in res:
            add(f"{y} results {e}/{f.name}", file_item, f, "sha256")
        add(f"{y} cv_summary.csv rows", rows_item, v / "cv_summary.csv", "era", e)
        add(f"{y} water_mask_by_year.csv rows", rows_item, v / "qa" / "water_mask_by_year.csv", "year", y)
        add(f"{y} reallocation_qa.csv rows", rows_item, v / "qa" / "reallocation_qa.csv", "year", y)
        if args.validation_dir:
            te = args.validation_dir / f"tract_errors_{y}.csv"
            if te.exists():  # every row
                add(f"{y} tract_errors_{y}.csv", rows_item, te, None, None)
            add(f"{y} metrics_by_year.csv rows", rows_item, args.validation_dir / "metrics_by_year.csv", "year", y)
    return items


def recompute(item: dict) -> str:
    """The item's current value (a hash / stat) or 'MISSING ...'."""
    p = Path(item["path"])
    if not p.exists():
        return f"MISSING {p}"
    if item["kind"] == "sha256":
        return sha(p)
    if item["kind"] == "stat":
        return stat(p)
    df = pd.read_csv(p)
    lacking = [c for c in item["cols"] if c not in df]
    if lacking:
        return f"columns missing {lacking}"
    sub = df if item["value"] is None else df[df[item["col"]].astype(str) == str(item["value"])]
    return f"{len(sub)} rows {canonical(sub, item['cols'])}"


def before(item: dict) -> str:
    return f"{item['n']} rows {item['hash']}" if item["kind"] == "rows" else item["value"]


def main(argv=None):
    args = parse_args(argv)
    if args.step == "snapshot":
        if not (args.version_dir and args.results_dir and args.years):
            sys.exit("ERROR: snapshot needs --version-dir, --results-dir and --years")
        items = snapshot(args)
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"years": args.years, "items": items}, indent=1))
        print(f"SNAPSHOT {len(items)} items of years {args.years} -> {args.json}")
        return 0
    if not args.json.exists():
        sys.exit(f"ERROR: {args.json} not found (snapshot before the run)")
    snap = json.loads(args.json.read_text())
    bad = 0
    for name, it in snap["items"].items():
        now, was = recompute(it), before(it)
        if now == was:
            print(f"MATCH {name}")
        else:
            bad += 1
            print(f"DIFFERS {name}: before {was} | after {now}")
    n = len(snap["items"])
    if bad:
        print(f"KEPT YEARS DIFFERS: {bad} of {n} items (years {snap['years']})")
        return 1
    print(f"KEPT YEARS OK: {n} items (years {snap['years']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
