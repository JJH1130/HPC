"""County train/test split + CV folds for the CONUS models (docs/conus_plan.md, "Train / test"). Run ONCE, before
any tuning; the output is tracked in git and reused by every year and every version (Dasy_CONUS_RF_v1, v2, ...).

    python src/dasymetric/make_split.py --std-csv data/census_std/all_county_census_MSA_full.csv \
        --out configs/conus_split.csv

Counties = the CSV's rows outside Alaska and Hawaii (2010 FIPS; GISJOIN as in std_county_check.py). A county
without a value in some year is simply absent in that year's model.
  1. Test: within each state (CSV STNAME), round(0.2 x n) counties drawn at random (n = 1, DC: none); the rest
     are train. One numpy Generator(seed), states in sorted order, so the table is reproducible.
  2. Folds: the train counties in random order (same generator) get fold = position mod `folds` (a GroupKFold
     with one group per county: fold sizes differ by at most one county). Test counties get fold -1.
Writes GISJOIN, fips, state, name, part (train/test), fold.

--append-train CSV (GISJOIN, fips, state, name) adds counties to the EXISTING table as train without touching its
rows: in GISJOIN order, each goes to the fold with the fewest train counties (ties: lowest fold). Used 2026-10-24
for the four 2010 polygons without a CSV row (filled from NHGIS, src/census/conus_counties.py).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DROP_STATES = ("02", "15")  # Alaska, Hawaii


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--std-csv", type=Path, required=True, help="data/census_std/all_county_census_MSA_full.csv")
    p.add_argument("--out", type=Path, required=True, help="configs/conus_split.csv")
    p.add_argument("--test-share", type=float, default=0.2)
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--force", action="store_true", help="overwrite an existing table (changes every comparison)")
    p.add_argument("--append-train", type=Path, metavar="CSV",
                   help="add these counties (GISJOIN, fips, state, name) to the existing --out table as train")
    return p.parse_args(argv)


def read_counties(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    fips = raw["FIPS"].str.strip().str.zfill(5)
    df = pd.DataFrame({"GISJOIN": "G" + fips.str[:2] + "0" + fips.str[2:] + "0", "fips": fips,
                       "state": raw["STNAME"].str.strip(), "name": raw["CTYNAME"].str.strip()})
    df = df[~df["fips"].str[:2].isin(DROP_STATES)]
    if df["fips"].duplicated().any():
        sys.exit(f"ERROR: duplicate FIPS in {path}")
    return df.sort_values("GISJOIN").reset_index(drop=True)


def make_split(df: pd.DataFrame, test_share: float, folds: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = df.copy()
    out["part"] = "train"
    for _, g in sorted(out.groupby("state"), key=lambda kv: kv[0]):
        n_test = int(np.floor(test_share * len(g) + 0.5))
        if n_test:
            out.loc[rng.choice(g.index.to_numpy(), size=n_test, replace=False), "part"] = "test"
    out["fold"] = -1
    train = out.index[out["part"] == "train"].to_numpy()
    out.loc[rng.permutation(train), "fold"] = np.arange(len(train)) % folds
    return out[["GISJOIN", "fips", "state", "name", "part", "fold"]]


def append_train(split: pd.DataFrame, extra: pd.DataFrame) -> pd.DataFrame:
    """split + extra counties as train; existing rows unchanged. Each new county (GISJOIN order) goes to the fold
    with the fewest train counties, ties to the lowest fold."""
    dup = sorted(set(extra["GISJOIN"]) & set(split["GISJOIN"]))
    if dup:
        sys.exit(f"ERROR: already in the split table: {dup}")
    counts = split.loc[split["part"] == "train", "fold"].value_counts().to_dict()
    folds = sorted(counts)
    rows = []
    for r in extra.sort_values("GISJOIN").itertuples():
        f = min(folds, key=lambda k: (counts[k], k))
        counts[f] += 1
        rows.append({"GISJOIN": r.GISJOIN, "fips": str(r.fips).zfill(5), "state": r.state, "name": r.name,
                     "part": "train", "fold": f})
    return pd.concat([split, pd.DataFrame(rows)], ignore_index=True)


def main(argv=None):
    args = parse_args(argv)
    if args.append_train:
        split = pd.read_csv(args.out, dtype={"fips": str})
        out = append_train(split, pd.read_csv(args.append_train, dtype={"fips": str}))
        if not out.iloc[:len(split)].equals(split):
            sys.exit("ERROR: existing rows changed")
        out.to_csv(args.out, index=False, lineterminator="\n")
        print(f"appended {len(out) - len(split)} train counties to {args.out}:")
        print(out.iloc[len(split):].to_string(index=False))
        print("train counties per fold:", out[out["part"] == "train"]["fold"].value_counts().sort_index().to_dict())
        return
    if args.out.exists() and not args.force:
        sys.exit(f"ERROR: {args.out} exists; the split is made once (use --force only to deliberately redo it)")
    split = make_split(read_counties(args.std_csv), args.test_share, args.folds, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    split.to_csv(args.out, index=False, lineterminator="\n")
    by_state = split.groupby("state")["part"].value_counts().unstack(fill_value=0)
    print(f"wrote {args.out}: {len(split)} counties, {int((split['part'] == 'train').sum())} train / "
          f"{int((split['part'] == 'test').sum())} test, {split['state'].nunique()} states (seed {args.seed})")
    print("train counties per fold:", split[split["part"] == "train"]["fold"].value_counts().sort_index().to_dict())
    print("states without a test county:", sorted(by_state.index[by_state.get("test", 0) == 0]))


if __name__ == "__main__":
    main()
