"""Shared pieces of the dasymetric pipeline (design: docs/dasymetric_v1.md, changes in docs/dasymetric_v2.md,
docs/dasymetric_v3.md and docs/dasymetric_v3_1.md).

Stages (each runs on its own):
  county_features.py  cutout -> [<era>/]features/county_features.csv
  train.py            county_features.csv -> [<era>/]model/
  predict.py          model(s) + cutout -> predictions/pop_{YEAR}.tif, qa/reallocation_qa.csv, maps/

Settings: configs/model.yaml (version, statuses, eras or one feature list, feature groups, model +
search space). With `eras:`, each era has its own years, features and model under <version>/<era>/;
without it, one pooled model sits directly under <version>/ (v1, v2). `water_mask: true` (v3.1) drops the
cells that are all water and have no building in that year (water_frac == 1 and BUI == 0): county area and
features use the other cells only, and masked cells get no people. The study area name and years
come from the study-area config it points to (configs/study_area.yaml).
Paths come from CLI flags (the sbatch scripts fill them from sbatch/cluster_env.sh).
"""
from __future__ import annotations

import logging
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import yaml
from scipy import ndimage

log = logging.getLogger("dasymetric")

# Cell features (docs/dasymetric_v1.md, "Cell features"; v2 adds bldg_size, dist_built; v3 adds res_share,
# rent_share, ntl). County feature = mean over the county's cells. Which ones are used is set in
# configs/model.yaml.
LAYER_FEATURES = {"bui": "BUI", "bupl": "BUPL", "bupr": "BUPR", "bua": "BUA", "ntl": "NTL"}
DERIVED_FEATURES = {"bldg_size", "mu_ratio", "age", "dist_built", "year", "res_share", "rent_share"}
FEATURES = set(LAYER_FEATURES) | DERIVED_FEATURES
LAND_USE = ["A", "C", "GV", "I", "RC", "RI", "RO", "VL"]  # cutout layers/Land_Use/{CLASS}/{YEAR}_{CLASS}.tif
WATER_LAYER = "water_frac"  # cutout layers/water_frac/water_frac.tif (static)
NODATA_OUT = -9999.0
CELL_KM = 0.25  # HISDAC cell size


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
    cfg["eras"] = load_eras(cfg, path)
    used = list(dict.fromkeys(f for e in cfg["eras"].values() for f in e["features"]))  # first-use order
    cfg["all_features"] = used
    groups = cfg.get("feature_groups") or {}
    grouped = [f for members in groups.values() for f in members]
    unknown = sorted({f for f in used + grouped if f not in FEATURES})
    if unknown:
        sys.exit(f"ERROR: {path}: unknown features {unknown}; known: {sorted(FEATURES)}")
    twice = sorted(f for f, n in Counter(grouped).items() if n > 1)
    ungrouped = [f for f in used if f not in grouped]
    if twice or ungrouped:
        sys.exit(f"ERROR: {path}: feature_groups must list every feature exactly once; "
                 f"in no group {ungrouped}, in several groups {twice}")
    if cfg["model"] not in cfg["models"]:
        sys.exit(f"ERROR: {path}: model {cfg['model']!r} has no entry under models: {sorted(cfg['models'])}")
    return cfg


def load_eras(cfg: dict, path: Path) -> dict:
    """{era name: {years, features}}. Without `eras:` there is one unnamed era ("") with all years and the
    top-level `features` (v1, v2). With eras, every study year must be in exactly one era."""
    eras = cfg.get("eras")
    if not eras:
        return {"": {"years": list(cfg["years"]), "features": list(cfg["features"])}}
    if "features" in cfg:
        sys.exit(f"ERROR: {path}: give either `features` or `eras`, not both")
    out = {}
    for name, e in eras.items():
        years = [y for y in parse_years(e["years"]) if y in cfg["years"]]
        if not years:
            sys.exit(f"ERROR: {path}: era {name} has no study year")
        out[str(name)] = {"years": years, "features": list(e["features"])}
    n = Counter(y for e in out.values() for y in e["years"])
    missing = [y for y in cfg["years"] if not n[y]]
    twice = sorted(y for y, k in n.items() if k > 1)
    if missing or twice:
        sys.exit(f"ERROR: {path}: every study year must be in exactly one era; in none {missing}, in several {twice}")
    return out


def out_dir(cfg: dict, out_root: Path, era: str = "") -> Path:
    """<out-root>/<name>/<version>[/<era>]"""
    return out_root / cfg["name"] / cfg["version"] / era


def era_of(cfg: dict, year: int) -> str:
    return next(name for name, e in cfg["eras"].items() if year in e["years"])


def era_groups(cfg: dict, features) -> dict:
    """feature_groups restricted to `features` (groups with none of them are left out)."""
    groups = {g: [f for f in m if f in features] for g, m in (cfg.get("feature_groups") or {}).items()}
    return {g: m for g, m in groups.items() if m}


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
    if year is not None:  # layers/BUI/{YEAR}_BUI.tif; Land_Use/RO -> layers/Land_Use/RO/{YEAR}_RO.tif
        return cutout / "layers" / layer / f"{year}_{Path(layer).name}.tif"
    hits = sorted((cutout / "layers" / layer).glob("*.tif"))  # single-file layer (FBUY)
    if len(hits) != 1:
        sys.exit(f"ERROR: expected exactly one .tif in {cutout / 'layers' / layer}, found {[h.name for h in hits]}")
    return hits[0]


def read_layer_full(cutout: Path, layer: str, year: int | None, grid: dict):
    """Whole-window layer array (float64) + its nodata mask. The layer must be on the zones grid."""
    path = layer_path(cutout, layer, year)
    if not path.exists():
        sys.exit(f"ERROR: {path} not found (run grid_cutout first)")
    with rasterio.open(path) as src:
        if (src.height, src.width) != grid["shape"] or src.transform != grid["transform"]:
            sys.exit(f"ERROR: {path} is not on the zones grid ({src.width}x{src.height} {src.transform})")
        arr = src.read(1).astype("float64")
        nodata = src.nodata
    bad = ~np.isfinite(arr)
    if nodata is not None:
        bad |= arr == nodata
    return arr, bad, path


def read_layer(cutout: Path, layer: str, year: int | None, grid: dict, mask: np.ndarray) -> np.ndarray:
    """Layer values at the masked cells (float64). The masked cells must not be nodata
    (0 is a value: "no building")."""
    arr, bad, path = read_layer_full(cutout, layer, year, grid)
    if bad[mask].any():
        sys.exit(f"ERROR: {path}: {int(bad[mask].sum())} nodata cells inside the used counties")
    return arr[mask]


def dist_built(cutout: Path, year: int, grid: dict) -> np.ndarray:
    """Whole-window distance (km) from each cell centre to the nearest cell with BUA_Y = 1; 0 on built
    cells (docs/dasymetric_v2.md). Uses the full window, so built cells outside the study counties count.
    Nodata cells count as unbuilt."""
    bua, bad, path = read_layer_full(cutout, "BUA", year, grid)
    built = (bua == 1) & ~bad
    if not built.any():
        sys.exit(f"ERROR: {path}: no built cell (BUA = 1) in the window for {year}; dist_built undefined")
    if bad.any():
        log.info("  %d: BUA has %d nodata cells in the window (treated as unbuilt for dist_built)",
                 year, int(bad.sum()))
    return ndimage.distance_transform_edt(~built) * CELL_KM


def water_mask(cutout: Path, year: int, grid: dict, mask: np.ndarray):
    """Year-specific water mask of the masked cells (docs/dasymetric_v3_1.md): True where the cell is all
    permanent water (water_frac == 1, layers/water_frac/ from src/grid/water_frac.py) and has no building in
    that year (BUI == 0). Cells with buildings are never masked. Returns (masked, n_water_built), the second
    being the all-water cells kept because BUI > 0 (QA). Water is never a feature."""
    wf = read_layer(cutout, WATER_LAYER, None, grid, mask)
    if wf.size and (wf.min() < 0 or wf.max() > 1):
        sys.exit(f"ERROR: water_frac outside 0-1 ({wf.min()}..{wf.max()}); rerun src/grid/water_frac.py")
    bui = read_layer(cutout, "BUI", year, grid, mask)
    full = wf >= 1
    return full & (bui == 0), int((full & (bui > 0)).sum())


def cell_features(cutout: Path, year: int, grid: dict, mask: np.ndarray, names) -> pd.DataFrame:
    """Cell features (docs/dasymetric_v1.md, v2) for the masked cells, columns in `names` order."""
    cache = {}

    def layer(name, y=year):
        if (name, y) not in cache:
            cache[(name, y)] = read_layer(cutout, name, y, grid, mask)
        return cache[(name, y)]

    out = {}
    for f in names:
        if f in LAYER_FEATURES:
            out[f] = layer(LAYER_FEATURES[f])
        elif f == "bldg_size":  # BUI / BUPL where BUPL > 0, else 0 (mean building size)
            ui, pl = layer("BUI"), layer("BUPL")
            out[f] = np.divide(ui, pl, out=np.zeros_like(pl), where=pl > 0)
        elif f == "mu_ratio":  # BUPR / BUPL where BUPL > 0, else 0 (multi-unit proxy)
            pl, pr = layer("BUPL"), layer("BUPR")
            out[f] = np.divide(pr, pl, out=np.zeros_like(pl), where=pl > 0)
        elif f == "age":  # Y - FBUY where 0 < FBUY <= Y, else 0 (years since first settlement)
            fbuy = layer("FBUY", None)
            out[f] = np.where((fbuy > 0) & (fbuy <= year), year - fbuy, 0.0)
        elif f in ("res_share", "rent_share"):  # Land_Use shares (docs/dasymetric_v3.md)
            ro, ri = layer("Land_Use/RO"), layer("Land_Use/RI")
            if f == "res_share":  # (RO + RI) / all eight classes
                total = sum(layer(f"Land_Use/{c}") for c in LAND_USE)
                out[f] = np.divide(ro + ri, total, out=np.zeros_like(total), where=total > 0)
            else:  # RI / (RO + RI)
                out[f] = np.divide(ri, ro + ri, out=np.zeros_like(ri), where=(ro + ri) > 0)
        elif f == "dist_built":  # km to the nearest built cell (whole window), 0 for built cells
            out[f] = dist_built(cutout, year, grid)[mask]
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
    # sbatch helpers: `python src/dasymetric/common.py --print-name-version configs/model.yaml`,
    # `... --print-eras configs/model.yaml` (era names, space separated; empty line without eras)
    if len(sys.argv) != 3 or sys.argv[1] not in ("--print-name-version", "--print-eras"):
        sys.exit("usage: common.py --print-name-version|--print-eras <configs/model.yaml>")
    c = load_config(Path(sys.argv[2]))
    print(" ".join(c["eras"]) if sys.argv[1] == "--print-eras" else f"{c['name']} {c['version']}")
