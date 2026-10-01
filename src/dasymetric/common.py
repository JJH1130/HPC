"""Shared pieces of the dasymetric pipeline (design: docs/dasymetric_v1.md).

Stages (each runs on its own):
  county_features.py  cutout -> features/county_features.csv
  train.py            county_features.csv -> model/
  predict.py          model + cutout -> predictions/pop_{YEAR}.tif, qa/reallocation_qa.csv

Settings: configs/model.yaml (version, statuses, features, model + search space). The study
area name and years come from the study-area config it points to (configs/study_area.yaml).
Paths come from CLI flags (the sbatch scripts fill them from sbatch/cluster_env.sh).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import yaml

log = logging.getLogger("dasymetric")

# Cell features (docs/dasymetric_v1.md, "Cell features"). County feature = mean over the county's cells.
LAYER_FEATURES = {"bui": "BUI", "bupl": "BUPL", "bupr": "BUPR", "bua": "BUA"}
DERIVED_FEATURES = {"mu_ratio", "age", "year"}
FEATURES = set(LAYER_FEATURES) | DERIVED_FEATURES
NODATA_OUT = -9999.0


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)


def add_common_args(p):
    p.add_argument("--config", type=Path, required=True, help="configs/model.yaml")
    p.add_argument("--out-root", type=Path, required=True,
                   help="outputs go to <out-root>/<study name>/<version>/")


def parse_years(y):
    if isinstance(y, dict):
        return list(range(y["start"], y["stop"] + 1, y.get("step", 1)))
    return sorted(int(v) for v in y)


def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    study_path = Path(cfg["study_area"])
    if not study_path.is_absolute():
        study_path = path.parent.parent / study_path  # relative to the repo root
    study = yaml.safe_load(study_path.read_text(encoding="utf-8"))
    cfg["name"] = study["name"]
    cfg["years"] = parse_years(study["years"])
    unknown = [f for f in cfg["features"] if f not in FEATURES]
    if unknown:
        sys.exit(f"ERROR: {path}: unknown features {unknown}; known: {sorted(FEATURES)}")
    if cfg["model"] not in cfg["models"]:
        sys.exit(f"ERROR: {path}: model {cfg['model']!r} has no entry under models: {sorted(cfg['models'])}")
    return cfg


def out_dir(cfg: dict, out_root: Path) -> Path:
    return out_root / cfg["name"] / cfg["version"]


def log_args(args):
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)


# ---------------------------------------------------------------- cutout inputs

def read_zones(cutout: Path, year: int):
    """zones_{YEAR}.tif (0 = outside the selected counties) + its table + grid profile."""
    tif, csv = cutout / "zones" / f"zones_{year}.tif", cutout / "zones" / f"zones_{year}.csv"
    for f in (tif, csv):
        if not f.exists():
            sys.exit(f"ERROR: {f} not found (run grid_cutout for {year} first)")
    with rasterio.open(tif) as src:
        zones = src.read(1)
        grid = {"transform": src.transform, "crs": src.crs, "shape": zones.shape}
    table = pd.read_csv(csv)
    return zones, table, grid


def county_selection(table: pd.DataFrame, zones: np.ndarray, use_status, year: int) -> pd.DataFrame:
    """Counties whose status is used, with n_cells. Stops if a used county has no cells or no pop:
    its population could not be reallocated (docs/cutout.md, Open items)."""
    ids, counts = np.unique(zones[zones > 0], return_counts=True)
    t = table.copy()
    t["n_cells"] = t["zone_id"].map(dict(zip(ids.tolist(), counts.tolist()))).fillna(0).astype(int)
    used = t[t["status"].isin(use_status)].copy()
    bad = used[(used["n_cells"] == 0) | ~(used["pop"] > 0) | ~(used["area_km2"] > 0)]
    if len(bad):
        sys.exit(f"ERROR: {year}: used counties with 0 cells, pop <= 0 or area <= 0 "
                 f"(needs a decision before modeling):\n{bad.to_string()}")
    return used


def layer_path(cutout: Path, layer: str, year: int | None) -> Path:
    if year is not None:
        return cutout / "layers" / layer / f"{year}_{layer}.tif"
    hits = sorted((cutout / "layers" / layer).glob("*.tif"))  # single-file layer (FBUY)
    if len(hits) != 1:
        sys.exit(f"ERROR: expected exactly one .tif in {cutout / 'layers' / layer}, found {[h.name for h in hits]}")
    return hits[0]


def read_layer(cutout: Path, layer: str, year: int | None, grid: dict, mask: np.ndarray) -> np.ndarray:
    """Layer values at the masked cells (float64). The layer must be on the zones grid, and the
    masked cells must not be nodata (0 is a value: "no building")."""
    path = layer_path(cutout, layer, year)
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (run grid_cutout first)")
    with rasterio.open(path) as src:
        if (src.height, src.width) != grid["shape"] or src.transform != grid["transform"]:
            sys.exit(f"ERROR: {path} is not on the zones grid ({src.width}x{src.height} {src.transform})")
        arr = src.read(1)
        nodata = src.nodata
    vals = arr[mask].astype("float64")
    bad = ~np.isfinite(vals)
    if nodata is not None:
        bad |= vals == nodata
    if bad.any():
        sys.exit(f"ERROR: {path}: {int(bad.sum())} nodata cells inside the used counties")
    return vals


def cell_features(cutout: Path, year: int, grid: dict, mask: np.ndarray, names) -> pd.DataFrame:
    """Cell features (docs/dasymetric_v1.md) for the masked cells, columns in `names` order."""
    cache = {}

    def layer(name, y=year):
        if (name, y) not in cache:
            cache[(name, y)] = read_layer(cutout, name, y, grid, mask)
        return cache[(name, y)]

    out = {}
    for f in names:
        if f in LAYER_FEATURES:
            out[f] = layer(LAYER_FEATURES[f])
        elif f == "mu_ratio":  # BUPR / BUPL where BUPL > 0, else 0 (multi-unit proxy)
            pl, pr = layer("BUPL"), layer("BUPR")
            out[f] = np.divide(pr, pl, out=np.zeros_like(pl), where=pl > 0)
        elif f == "age":  # Y - FBUY where 0 < FBUY <= Y, else 0 (years since first settlement)
            fbuy = layer("FBUY", None)
            out[f] = np.where((fbuy > 0) & (fbuy <= year), year - fbuy, 0.0)
        elif f == "year":
            out[f] = np.full(int(mask.sum()), float(year))
    return pd.DataFrame(out, columns=list(names))


# ---------------------------------------------------------------- outputs

def write_tif(path: Path, arr, transform, crs, nodata):
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    predictor = 3 if np.issubdtype(arr.dtype, np.floating) else 2
    profile = dict(driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1, dtype=arr.dtype,
                   crs=crs, transform=transform, nodata=nodata, compress="deflate", predictor=predictor,
                   tiled=True, blockxsize=256, blockysize=256, BIGTIFF="IF_SAFER")
    with rasterio.open(part, "w", **profile) as dst:
        dst.write(arr, 1)
    os.replace(part, path)  # the final name only ever holds a complete file


if __name__ == "__main__":
    # sbatch helper: `python src/dasymetric/common.py --print-name-version configs/model.yaml`
    if len(sys.argv) != 3 or sys.argv[1] != "--print-name-version":
        sys.exit("usage: common.py --print-name-version <configs/model.yaml>")
    c = load_config(Path(sys.argv[2]))
    print(c["name"], c["version"])
