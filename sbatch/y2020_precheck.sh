#!/bin/bash
# Pre-check for adding 2020 to Dasy_CONUS_RF_v3_all (docs/conus_plan.md "2020"; request 2026-10-30, part B). Not a job:
# run it on a login node from the repo root (file listings + md5 of 16 Land_Use files, a few minutes):
#   bash sbatch/y2020_precheck.sh 2>&1 | tee logs/y2020_precheck.txt
# Checks, without writing anything else:
#   - NHGIS 2020 county input (counties_2020.gpkg of prepare_census.py) and the 2010 polygons (counties_std_2010.gpkg)
#   - tracts_2020.gpkg (prepare_tracts.py) for the 2020 tract validation
#   - HISDAC 2020 layers: BUI, BUPL, BUPR, BUA, Land_Use (8 classes); Land_Use 2020 vs 2015 (md5: a copy or not; the
#     LU README says 1940-2015)
#   - water inputs (JRC tiles, GDW) and the static DEM layer of the cutout
#   - the v3_all outputs on scratch that the 2020 run adds to (models, predictions, features, QA files)
# Ends with PRECHECK OK, or PRECHECK FAILED and the list of what is missing.
set -uo pipefail
cd "$(dirname "$0")/.."
source sbatch/cluster_env.sh
V=Dasy_CONUS_RF_v3_all
D=$HISDAC_SCRATCH/dasymetric/conus/$V
CUT=$HISDAC_SCRATCH/cutouts/conus
PY=$ENVS/hisdac/bin/python
miss=()
echo "== $(date -Is) host $(hostname) git $(git rev-parse --short HEAD)"

need() { if [[ -e $1 ]]; then echo "  ok   $1"; else echo "  MISSING $1"; miss+=("$1"); fi; }

echo "== census and tracts"
need "$DATA_ROOT/processed/census/counties_2020.gpkg"
need "$DATA_ROOT/processed/census/counties_std_2010.gpkg"
need "$DATA_ROOT/processed/tract/tracts_2020.gpkg"
[[ -f $DATA_ROOT/processed/census/counties_2020.gpkg ]] && $PY - "$DATA_ROOT/processed/census/counties_2020.gpkg" <<'PYEOF'
import sys
import pyogrio
t = pyogrio.read_dataframe(sys.argv[1], columns=["GISJOIN", "state", "name", "pop", "status"], read_geometry=False)
print(f"  NHGIS 2020: {len(t)} counties, pop {t['pop'].sum():,.0f}, statuses {t['status'].value_counts().to_dict()}")
ct = t[t["GISJOIN"].str.startswith("G090")]
print(f"  Connecticut: {len(ct)} units: {list(zip(ct['GISJOIN'], ct['name']))}")
for g in ("G4601020", "G4601130", "G5100190", "G5105150", "G1200860", "G0800140"):
    r = t[t["GISJOIN"] == g]
    print(f"  {g}: {'not in 2020' if r.empty else (r['name'].iloc[0], float(r['pop'].iloc[0]), r['status'].iloc[0])}")
PYEOF

echo "== HISDAC 2020 layers ($HISDAC_DIR, read only)"
for l in BUI BUPL BUPR BUA; do need "$HISDAC_DIR/$l/2020_$l.tif"; done
for c in A C GV I RC RI RO VL; do
    f20=$HISDAC_DIR/Land_Use/$c/Count_2020_$c.tif
    f15=$HISDAC_DIR/Land_Use/$c/Count_2015_$c.tif
    need "$f20"
    if [[ -f $f20 && -f $f15 ]]; then
        m20=$(md5sum "$f20" | cut -d' ' -f1); m15=$(md5sum "$f15" | cut -d' ' -f1)
        echo "       $c: 2020 $(stat -c %s "$f20") bytes, 2015 $(stat -c %s "$f15") bytes -> $([[ $m20 == "$m15" ]] && echo 'IDENTICAL to 2015' || echo 'differs from 2015')"
    fi
done
ls "$HISDAC_DIR/Land_Use/RO/" | grep -E "20(10|15|20)" | sed 's/^/       RO folder: /'

echo "== water, DEM"
n=$(compgen -G "/projects/jaju1407/data/raw/water/jrc_occurrence/occurrence_*.tif" | wc -l)
echo "  JRC occurrence tiles: $n (CONUS needs 21)"; (( n >= 21 )) || miss+=("JRC tiles ($n of 21)")
need /projects/jaju1407/data/raw/water/gdw/GDW_v1_0_shp/GDW_reservoirs_v1_0.shp
need "$CUT/layers/DEM/DEM.tif"
need "$CUT/window.json"

echo "== v3_all outputs on scratch that 2020 is added to"
for y in 1900 1910 1920 1930 1940 1950 1960 1970 1980 1990 2000 2010; do
    need "$D/Y$y/model/rf.joblib"
    need "$D/predictions/pop_$y.tif"
    need "$CUT/zones/zones_$y.tif"
    need "$DATA_ROOT/processed/census_conus/counties_$y.gpkg"
done
need "$D/qa/reallocation_qa.csv"
need "$D/qa/water_mask_by_year.csv"
need "$D/cv_summary.csv"
need "$CUT/layers/BUI_raw"
[[ -e $D/Y2020 ]] && echo "  NOTE $D/Y2020 exists already (an earlier 2020 run): it is overwritten"
find "$D" -maxdepth 1 -printf '  %TY-%Tm-%Td %p\n' 2>/dev/null | sort | head -20
echo "== scratch use: $(du -sh "$HISDAC_SCRATCH" 2>/dev/null | cut -f1)"

if (( ${#miss[@]} )); then
    printf 'MISSING %s\n' "${miss[@]}"
    echo "PRECHECK FAILED (${#miss[@]} missing)"
    exit 1
fi
echo "PRECHECK OK"
