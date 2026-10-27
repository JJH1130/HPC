#!/bin/bash
# Download the VIIRS-like night lights (Chen et al. 2021, Harvard Dataverse doi:10.7910/DVN/YGIVCD; docs/data_sources.md)
# for 2000 and 2010 into $DATA_ROOT/raw/ntl/viirs_like/v<VERSION>/ (docs/conus_plan.md "VIIRS-like NTL test").
# Not a job: run it on a login node from the repo root (two zip files of 60-160 MB; light IO).
#   bash sbatch/ntlv_download.sh                # Version1 (the 2021 paper: 2000-2012 DMSP converted, 2013-2018 VIIRS)
#   VERSION=2 bash sbatch/ntlv_download.sh      # Version2 (Chen et al. 2026, 1992-2025), kept in its own folder
#
# Per year: the file id and md5 come from the Dataverse API (dataset listing); if the API cannot be reached, the
# values recorded on 2026-10-28 (dataset version 10.1) are used. A zip already there with the right md5 is not
# downloaded again (also one copied from a laptop: see docs/runbooks/Running_CONUS.md, section 7). Each zip is
# unpacked into <year>/; the cutout config reads viirs_like/v1/<year>/*.tif (exactly one .tif per year).
# Then check the rasters with: sbatch --wait sbatch/ntlv_check.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source sbatch/cluster_env.sh

VERSION=${VERSION:-1}
YEARS=${YEARS:-2000 2010}
DOI=doi:10.7910/DVN/YGIVCD
API=https://dataverse.harvard.edu/api
OUT=$DATA_ROOT/raw/ntl/viirs_like/v$VERSION
PY=$ENVS/hisdac/bin/python  # python 3 for the JSON (bare python on a login node may be python 2)
mkdir -p "$OUT"
echo "== $(date -Is) host $(hostname) | VIIRS-like NTL Version$VERSION, years $YEARS -> $OUT"

# label id md5, recorded from $API/datasets/:persistentId/?persistentId=$DOI on 2026-10-28 (dataset version 10.1)
RECORDED="2000_Version1.zip 3986638 2a206d41905af713248ca37959110613
2010_Version1.zip 3987119 cb98449db9d4e2e38235e145394f2113
2000_Version2.zip 13295261 573fb3dc1b22744c83292fd4eca4a84d
2010_Version2.zip 13295266 c68bcd57d2fff2e5afca2c351f037d9f"

listing=$(curl -sSfL --max-time 60 "$API/datasets/:persistentId/?persistentId=$DOI" || true)
if [[ -n $listing ]]; then
    echo "== Dataverse API reached: $(printf '%s' "$listing" | $PY -c "import json,sys; d=json.load(sys.stdin)['data']['latestVersion']; print('dataset version', d['versionNumber'], d['versionMinorNumber'], '| license', (d.get('license') or {}).get('name'))")"
else
    echo "== Dataverse API not reachable: using the ids / md5 recorded on 2026-10-28"
fi

for y in $YEARS; do
    label=${y}_Version${VERSION}.zip
    if [[ -n $listing ]]; then
        read -r id md5 < <(printf '%s' "$listing" | $PY -c "
import json, sys
hits = [f['dataFile'] for f in json.load(sys.stdin)['data']['latestVersion']['files'] if f['label'] == '$label']
print(*(hits and (hits[0]['id'], hits[0]['md5']) or ('-', '-')))")
    else
        read -r _ id md5 < <(grep "^$label " <<< "$RECORDED" || echo "- - -")
    fi
    [[ $id != - ]] || { echo "ERROR: $label not in the dataset listing"; exit 1; }
    rec=$(grep "^$label " <<< "$RECORDED" | cut -d' ' -f3 || true)
    [[ -z $rec || $rec == "$md5" ]] || echo "WARNING: $label md5 changed since 2026-10-28 ($rec -> $md5): the file was replaced on Dataverse"
    zip=$OUT/$label
    if [[ -f $zip ]] && [[ $(md5sum "$zip" | cut -d' ' -f1) == "$md5" ]]; then
        echo "== $label: already there, md5 ok"
    else
        echo "== $label: downloading file id $id"
        curl -fL --retry 3 --max-time 1800 -o "$zip.part" "$API/access/datafile/$id"
        mv "$zip.part" "$zip"
        got=$(md5sum "$zip" | cut -d' ' -f1)
        [[ $got == "$md5" ]] || { echo "ERROR: $label md5 $got, expected $md5"; exit 1; }
        echo "== $label: md5 ok ($(du -h "$zip" | cut -f1))"
    fi
    rm -rf "$OUT/$y"
    mkdir -p "$OUT/$y"
    unzip -q -o -j "$zip" -d "$OUT/$y"  # -j: files flat in <year>/, whatever folders the zip has
    echo "== $y: unpacked:"
    find "$OUT/$y" -type f -printf '   %p %s bytes\n'
    n=$(find "$OUT/$y" -type f -name '*.tif' | wc -l)
    [[ $n == 1 ]] || echo "WARNING: $y has $n .tif files; the cutout config expects exactly one (send this log to Claude)"
done
echo "== done $(date -Is): next: sbatch --wait sbatch/ntlv_check.sh"
