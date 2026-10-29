#!/bin/bash
# Download BUPR_contemp.tif (HISDAC-US BUPR record, Harvard Dataverse doi:10.7910/DVN/45B8IU; docs/data_sources.md) into
# $DATA_ROOT/raw/hisdac_extra/ (docs/conus_plan.md "HISDAC record uncertainty"). Not a job: run it on a login node from
# the repo root, inside tmux (the BUPR archive may be several GB):
#   tmux new -s hisdac_dl
#   bash sbatch/hisdac_extra_download.sh 2>&1 | tee logs/hisdac_extra_download.txt
#
# 1. Lists the dataset's files through the Dataverse API (label, folder, id, size, md5, restricted) into
#    results/hisdac_uncertainty/dataverse_45B8IU_files.tsv.
# 2. If BUPR_contemp.tif is a file of its own there, only it is downloaded (md5 checked).
#    Otherwise the archive holding it (a .tar.gz / .tgz / .tar / .zip whose label starts with BUPR) is downloaded to
#    scratch ($SCRATCH/hisdac_extra/, resumable with curl -C -, md5 checked), its member list is saved next to the TSV,
#    and only BUPR_contemp.tif is unpacked. The archive stays on scratch (purged after 90 days; delete it earlier with
#    rm -f $SCRATCH/hisdac_extra/<archive> once the tif is checked).
# 3. Writes BUPR_contemp.tif.md5 next to the tif and prints gdalinfo-like facts (CRS, size, transform) with rasterio.
# A tif already there with a matching .md5 is not downloaded again.
set -euo pipefail
cd "$(dirname "$0")/.."
source sbatch/cluster_env.sh

DOI=doi:10.7910/DVN/45B8IU
API=https://dataverse.harvard.edu/api
OUT=$DATA_ROOT/raw/hisdac_extra
TMP=$SCRATCH/hisdac_extra
RES=results/hisdac_uncertainty
PY=$ENVS/hisdac/bin/python  # python 3 (bare python on a login node may be python 2)
WANT=BUPR_contemp.tif
mkdir -p "$OUT" "$TMP" "$RES"
echo "== $(date -Is) host $(hostname) | $DOI -> $OUT/$WANT"

if [[ -f $OUT/$WANT && -f $OUT/$WANT.md5 ]] && (cd "$OUT" && md5sum -c --quiet "$WANT.md5"); then
    echo "== $WANT already there, md5 ok: nothing to do"
    echo "DOWNLOAD OK"
    exit 0
fi

listing=$(curl -sSfL --max-time 120 "$API/datasets/:persistentId/?persistentId=$DOI") \
    || { echo "ERROR: Dataverse API not reachable ($API)"; exit 1; }
printf '%s' "$listing" | $PY -c "
import json, sys
d = json.load(sys.stdin)['data']['latestVersion']
print('== dataset version', d['versionNumber'], d['versionMinorNumber'], '| license', (d.get('license') or {}).get('name'),
      '| terms', (d.get('termsOfUse') or '')[:200].replace(chr(10), ' '), file=sys.stderr)
print('label\tfolder\tid\tsize\tmd5\trestricted')
for f in d['files']:
    df = f['dataFile']
    print(f\"{f['label']}\t{f.get('directoryLabel', '')}\t{df['id']}\t{df.get('filesize', '')}\t{df.get('md5', '')}\t{f.get('restricted', False)}\")
" > "$RES/dataverse_45B8IU_files.tsv"
echo "== files in the dataset ($RES/dataverse_45B8IU_files.tsv):"
column -t -s $'\t' "$RES/dataverse_45B8IU_files.tsv"

pick() {  # pick <awk condition on the label $1> -> "label id size md5 restricted" of the first match
    awk -F'\t' -v OFS=' ' "NR > 1 && ($1) {print \$1, \$3, \$4, \$5, \$6; exit}" "$RES/dataverse_45B8IU_files.tsv"
}
read -r label id size md5 restricted < <(pick "\$1 == \"$WANT\"" || true) || true
if [[ -n ${id:-} ]]; then
    echo "== $WANT is a file of its own (id $id, $size bytes): downloading only it"
    [[ $restricted == False ]] || echo "WARNING: the file is marked restricted; the download may need a Dataverse API token"
    curl -fL --retry 3 -C - -o "$TMP/$WANT.part" "$API/access/datafile/$id"
    got=$(md5sum "$TMP/$WANT.part" | cut -d' ' -f1)
    [[ $got == "$md5" ]] || { echo "ERROR: $WANT md5 $got, expected $md5"; exit 1; }
    mv "$TMP/$WANT.part" "$OUT/$WANT"
else
    read -r label id size md5 restricted < <(pick "\$1 ~ /^BUPR/ && \$1 ~ /\\.(tar\\.gz|tgz|tar|zip)\$/" || true) || true
    [[ -n ${id:-} ]] || { echo "ERROR: neither $WANT nor a BUPR archive in the listing (see the TSV above)"; exit 1; }
    echo "== $WANT is not a file of its own: archive $label (id $id, $size bytes, $(numfmt --to=iec "$size" 2>/dev/null || echo ?))"
    [[ $restricted == False ]] || echo "WARNING: the archive is marked restricted; the download may need a Dataverse API token"
    arc=$TMP/$label
    if [[ -f $arc ]] && [[ $(md5sum "$arc" | cut -d' ' -f1) == "$md5" ]]; then
        echo "== $label already on scratch, md5 ok"
    else
        df -h "$TMP" | tail -1 | awk '{print "== scratch free:", $4}'
        curl -fL --retry 5 --retry-delay 30 -C - -o "$arc.part" "$API/access/datafile/$id"
        mv "$arc.part" "$arc"
        got=$(md5sum "$arc" | cut -d' ' -f1)
        [[ $got == "$md5" ]] || { echo "ERROR: $label md5 $got, expected $md5 (rm $arc and rerun)"; exit 1; }
        echo "== $label: md5 ok ($(du -h "$arc" | cut -f1))"
    fi
    case $label in
        *.zip) unzip -l "$arc" > "$RES/${label}_members.txt"
               member=$(awk '{print $4}' "$RES/${label}_members.txt" | grep -m1 "$WANT\$" || true) ;;
        *.tar) tar -tvf "$arc" > "$RES/${label}_members.txt"
               member=$(awk '{print $NF}' "$RES/${label}_members.txt" | grep -m1 "$WANT\$" || true) ;;
        *)     tar -tzvf "$arc" > "$RES/${label}_members.txt"
               member=$(awk '{print $NF}' "$RES/${label}_members.txt" | grep -m1 "$WANT\$" || true) ;;
    esac
    echo "== $(wc -l < "$RES/${label}_members.txt") members listed in $RES/${label}_members.txt"
    [[ -n $member ]] || { echo "ERROR: $WANT not in $label (see the member list)"; exit 1; }
    echo "== unpacking only $member"
    rm -rf "$TMP/unpack" && mkdir -p "$TMP/unpack"
    case $label in
        *.zip) unzip -q -j "$arc" "$member" -d "$TMP/unpack" ;;
        *.tar) tar -xf "$arc" -C "$TMP/unpack" "$member" ;;
        *)     tar -xzf "$arc" -C "$TMP/unpack" "$member" ;;
    esac
    mv "$(find "$TMP/unpack" -type f -name "$WANT" | head -1)" "$OUT/$WANT"
fi
(cd "$OUT" && md5sum "$WANT" > "$WANT.md5")
ls -la "$OUT"
$PY - "$OUT/$WANT" <<'PYEOF'
import sys
import rasterio
with rasterio.open(sys.argv[1]) as s:
    print("== raster:", s.width, "x", s.height, "| dtype", s.dtypes[0], "| nodata", s.nodata, "| CRS", s.crs)
    print("== transform:", tuple(s.transform)[:6])
PYEOF
echo "== done $(date -Is): next: sbatch sbatch/record_uncertainty.sh (or bash sbatch/submit_conus.sh uncertainty)"
echo "DOWNLOAD OK"
