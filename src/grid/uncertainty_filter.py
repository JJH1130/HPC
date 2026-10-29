"""County sets left out of training and testing for the uncertainty-filter sensitivity runs (request 2026-10-30,
docs/handoff/uncertainty_filter_request.md part 1; docs/conus_plan.md "Uncertainty filter"). One fixed set per
threshold on the 2010 county polygons, the same for every census year.

A county is excluded for any of three reasons:
  ratio    ratio_A_nby >= t (NobuiltYear / (BUPR_2015 + NobuiltYear), record_uncertainty.py), t from --thresholds
  records  (BUPR_2015 + NobuiltYear) / pop_<pop-year> < --share x the median over counties (records missing)
  area     BUI_2015 / BUPR_2015 (county sums, sq ft per dated record) < --share x the median (floor area missing)
The two fixed rules are not tuned and apply at every threshold. A county without pop in <pop-year> or without
BUPR_2015 has no value for that rule (not excluded by it; counted). BUI_2015 is summed per 2010 county from the raw
HISDAC layer (the cutout holds census years only; cells above the CONUS BUI cap are counted, not changed: an outlier
raises BUI per record and cannot exclude a county).

Inputs (CLI flags, sbatch/uncertainty_filter.sh):
  --uncertainty     results/hisdac_uncertainty/county_record_uncertainty.csv (sums, ratio_A_nby, pop_<year>, gap_<year>,
                    split part)
  --bui             $HISDAC_DIR/BUI/2015_BUI.tif
  --cutout          zones/zones_2010.tif + .csv
  --nobuilt-values  results/hisdac_uncertainty/nobuilt_values.csv (even / odd values logged only)

Writes to --out-dir (results/hisdac_uncertainty/):
  county_filter_inputs.csv          every 2010 county: records per person, BUI per record, ratio_A_nby, rule flags
  excluded_counties_t{090,070,050}.csv   the excluded counties and why (reason_ratio / _records / _area, reasons)
  filter_summary.csv                per threshold: excluded by reason, kept, pop share kept per year, train / test,
                                    gap counties excluded
  filter_by_state.csv               per threshold and state
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record_uncertainty import Layer, read_zones, strips  # noqa: E402

log = logging.getLogger("uncertainty_filter")

THRESHOLDS = [0.9, 0.7, 0.5]
POP_YEARS = [1920, 1960, 2010, 2020]
BUI_CAP = 3.0e7  # bui_cap.max of configs/conus_study_area.yaml (counted only)


def label(t: float) -> str:
    return f"t{int(round(100 * t)):03d}"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--uncertainty", type=Path, required=True, help="county_record_uncertainty.csv")
    p.add_argument("--bui", type=Path, required=True, help="HISDAC BUI 2015 raster")
    p.add_argument("--cutout", type=Path, required=True, help="CONUS cutout folder (zones/)")
    p.add_argument("--zone-year", type=int, default=2010)
    p.add_argument("--nobuilt-values", type=Path, default=None, help="nobuilt_values.csv (even / odd log line)")
    p.add_argument("--thresholds", type=float, nargs="+", default=THRESHOLDS)
    p.add_argument("--share", type=float, default=0.05, help="fixed rules: below this share of the national median")
    p.add_argument("--pop-year", type=int, default=2010, help="pop of the records-per-person rule")
    p.add_argument("--years", type=int, nargs="+", default=POP_YEARS, help="years of the pop shares in the summary")
    p.add_argument("--gap-year", type=int, default=2010)
    p.add_argument("--block-rows", type=int, default=1024)
    p.add_argument("--out-dir", type=Path, required=True)
    return p.parse_args(argv)


def bui_sums(args, zpath: Path, nz: int):
    """BUI 2015 per zone id and the cells above the cap per zone id."""
    with rasterio.open(zpath) as z:
        grid = {"crs": z.crs, "transform": z.transform, "shape": z.shape}
    lay = Layer("BUI_2015", args.bui, grid)
    tot, cap = np.zeros(nz), np.zeros(nz)
    zsrc = rasterio.open(zpath)
    for rows in strips(grid["shape"][0], args.block_rows):
        z = read_zones(zsrc, rows, nz, zpath)
        b = lay.read(rows)
        s = z > 0
        tot += np.bincount(z[s], weights=b[s], minlength=nz)
        cap += np.bincount(z[s], weights=(b[s] > BUI_CAP).astype(float), minlength=nz)
    zsrc.close()
    log.info("BUI_2015: %s | nodata cells read as 0: %d | max %.3g | cells above %.0e in counties: %d",
             lay.info["read_as"], lay.n_nodata, lay.vmax, BUI_CAP, int(cap.sum()))
    return tot, cap


def even_odd_log(path):
    if path is None or not Path(path).exists():
        return
    nv = pd.read_csv(path)
    v = nv[(nv["value"] >= 1) & (nv["value"] < nv["value"].max())]  # last bin = "100 and more"
    even, odd = int(v.loc[v["value"] % 2 == 0, "cells_study"].sum()), int(v.loc[v["value"] % 2 == 1, "cells_study"].sum())
    ev3 = int(v.loc[(v["value"] >= 2) & (v["value"] % 2 == 0), "cells_study"].sum())
    od3 = int(v.loc[(v["value"] >= 3) & (v["value"] % 2 == 1), "cells_study"].sum())
    log.info("NOTE NobuiltYear values 1-99 (study cells): even %d vs odd %d cells (2+: even %d vs odd 3+ %d) -> "
             "records may be counted twice; used as they are (not corrected), as requested", even, odd, ev3, od3)


def county_inputs(args, u: pd.DataFrame, bui: np.ndarray, cap: np.ndarray) -> pd.DataFrame:
    pop = u[f"pop_{args.pop_year}"]
    rec = u["bupr_2015"] + u["nobuilt"]
    c = u[["zone_id", "GISJOIN", "state", "name", "part"]].copy()
    c["pop_" + str(args.pop_year)] = pop
    c["records_2015"] = rec
    c["records_per_person"] = rec / pop.where(pop > 0)
    c["bui_2015"] = bui[u["zone_id"].to_numpy()]
    c["bui_cells_above_cap"] = cap[u["zone_id"].to_numpy()].astype(int)
    c["bupr_2015"] = u["bupr_2015"]
    c["bui_per_record"] = c["bui_2015"] / u["bupr_2015"].where(u["bupr_2015"] > 0)
    c["ratio_A_nby"] = u["ratio_A_nby"]
    med_r, med_a = float(c["records_per_person"].median()), float(c["bui_per_record"].median())
    c["flag_records"] = c["records_per_person"] < args.share * med_r
    c["flag_area"] = c["bui_per_record"] < args.share * med_a
    log.info("records rule: median records per person (2015 records / %d pop) %.3f over %d counties -> limit %.4f; "
             "%d counties below, %d without a value (no %d pop)", args.pop_year, med_r,
             int(c["records_per_person"].notna().sum()), args.share * med_r, int(c["flag_records"].sum()),
             int(c["records_per_person"].isna().sum()), args.pop_year)
    log.info("area rule: median BUI_2015 per dated record %.0f sq ft over %d counties -> limit %.1f; %d counties below, "
             "%d without a value (BUPR_2015 = 0)", med_a, int(c["bui_per_record"].notna().sum()), args.share * med_a,
             int(c["flag_area"].sum()), int(c["bui_per_record"].isna().sum()))
    cols = ["GISJOIN", "state", "name", "part", f"pop_{args.pop_year}", "records_per_person", "bui_per_record",
            "ratio_A_nby", "bui_cells_above_cap"]
    with pd.option_context("display.width", 200):
        for f in ("flag_records", "flag_area"):
            log.info("  %s counties:\n%s", f, c.loc[c[f], cols].round(4).to_string(index=False))
    c.attrs.update({"median_records_per_person": med_r, "median_bui_per_record": med_a})
    return c


def excluded_set(c: pd.DataFrame, t: float) -> pd.DataFrame:
    e = c.copy()
    e["reason_ratio"] = e["ratio_A_nby"] >= t
    e["reason_records"] = e["flag_records"]
    e["reason_area"] = e["flag_area"]
    r = e[["reason_ratio", "reason_records", "reason_area"]]
    e["reasons"] = r.apply(lambda s: ";".join(n.removeprefix("reason_") for n, v in s.items() if v), axis=1)
    return e[r.any(axis=1)].reset_index(drop=True)


def summarise(args, c: pd.DataFrame, u: pd.DataFrame, t: float, e: pd.DataFrame):
    ex = c["GISJOIN"].isin(e["GISJOIN"])
    gap = u[f"gap_{args.gap_year}"].fillna(False).astype(bool) if f"gap_{args.gap_year}" in u else pd.Series(False, index=u.index)
    row = {"threshold": t, "label": label(t), "counties": len(c), "excluded": int(ex.sum()), "kept": int((~ex).sum()),
           "by_ratio": int(e["reason_ratio"].sum()), "by_records": int(e["reason_records"].sum()),
           "by_area": int(e["reason_area"].sum()),
           "fixed_rules_only": int((~e["reason_ratio"] & (e["reason_records"] | e["reason_area"])).sum()),
           "train_excluded": int((ex & (c["part"] == "train")).sum()), "test_excluded": int((ex & (c["part"] == "test")).sum()),
           "train_kept": int((~ex & (c["part"] == "train")).sum()), "test_kept": int((~ex & (c["part"] == "test")).sum()),
           f"gap_{args.gap_year}_counties": int(gap.sum()), f"gap_{args.gap_year}_excluded": int((gap & ex).sum())}
    for y in args.years:
        col = f"pop_{y}"
        if col in u:
            p = u[col].fillna(0)
            row[f"pop_share_kept_{y}"] = float(p[~ex].sum() / p.sum()) if p.sum() else np.nan
    st = c.assign(excluded=ex, pop=u[f"pop_{args.pop_year}"].fillna(0)).groupby("state").agg(
        counties=("GISJOIN", "size"), excluded=("excluded", "sum"),
        pop=("pop", "sum"), pop_excluded=("pop", lambda s: float(s[ex.loc[s.index]].sum())))
    st["pop_share_excluded"] = st["pop_excluded"] / st["pop"].where(st["pop"] > 0)
    st.insert(0, "threshold", t)
    return row, st.reset_index()


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    args = parse_args(argv)
    for flag, value in vars(args).items():
        log.info("arg %s = %s", flag, value)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    zpath, zcsv = args.cutout / "zones" / f"zones_{args.zone_year}.tif", args.cutout / "zones" / f"zones_{args.zone_year}.csv"
    for f in (zpath, zcsv, args.uncertainty):
        if not f.exists():
            sys.exit(f"ERROR: {f} not found")
    u = pd.read_csv(args.uncertainty)
    need = {"zone_id", "GISJOIN", "bupr_2015", "nobuilt", "ratio_A_nby", f"pop_{args.pop_year}", "part"}
    if need - set(u.columns):
        sys.exit(f"ERROR: {args.uncertainty} lacks {sorted(need - set(u.columns))} (rerun record_uncertainty.py)")
    zt = pd.read_csv(zcsv)
    if set(zt["GISJOIN"]) != set(u["GISJOIN"]):
        sys.exit(f"ERROR: {zcsv} and {args.uncertainty} hold different counties")
    even_odd_log(args.nobuilt_values)
    bui, cap = bui_sums(args, zpath, int(zt["zone_id"].max()) + 1)
    c = county_inputs(args, u, bui, cap)
    c.to_csv(out / "county_filter_inputs.csv", index=False)
    rows, states = [], []
    for t in args.thresholds:
        e = excluded_set(c, t)
        cols = ["GISJOIN", "state", "name", "part", "ratio_A_nby", "records_per_person", "bui_per_record",
                "reason_ratio", "reason_records", "reason_area", "reasons", f"pop_{args.pop_year}"]
        g = f"gap_{args.gap_year}"
        e = e.assign(**{g: e["GISJOIN"].map(dict(zip(u["GISJOIN"], u[g])))}) if g in u else e
        e[cols + ([g] if g in e else [])].to_csv(out / f"excluded_counties_{label(t)}.csv", index=False)
        row, st = summarise(args, c, u, t, e)
        rows.append(row)
        states.append(st)
        log.info("t = %.1f (%s): %d of %d counties excluded (ratio %d, records %d, area %d; fixed rules only %d) | "
                 "train / test excluded %d / %d | pop kept %s | gap counties excluded %d of %d", t, label(t),
                 row["excluded"], row["counties"], row["by_ratio"], row["by_records"], row["by_area"],
                 row["fixed_rules_only"], row["train_excluded"], row["test_excluded"],
                 {y: round(row[f"pop_share_kept_{y}"], 3) for y in args.years if f"pop_share_kept_{y}" in row},
                 row[f"gap_{args.gap_year}_excluded"], row[f"gap_{args.gap_year}_counties"])
    summ = pd.DataFrame(rows)
    summ.to_csv(out / "filter_summary.csv", index=False)
    pd.concat(states, ignore_index=True).to_csv(out / "filter_by_state.csv", index=False)
    sets = [set(pd.read_csv(out / f"excluded_counties_{label(t)}.csv")["GISJOIN"]) for t in sorted(args.thresholds, reverse=True)]
    nested = all(a <= b for a, b in zip(sets, sets[1:]))
    log.info("sets nested (a larger t excludes a subset of a smaller t's set): %s", nested)
    with pd.option_context("display.width", 250):
        log.info("summary:\n%s", summ.round(3).to_string(index=False))
    log.info("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
