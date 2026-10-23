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


def main(argv=None):
    args = parse_args(argv)
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
