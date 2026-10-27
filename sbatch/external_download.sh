#!/bin/bash
# Download the external gridded population products for the tract comparison (configs/external_grids.yaml;
# docs/data_sources.md; docs/conus_plan.md "External comparison") into $DATA_ROOT/raw/external/<product>/.
# Not a job: run it on a login node from the repo root (like sbatch/ntlv_download.sh; IO only, ~27 GB in all).
#   bash sbatch/external_download.sh                      # all products
#   PRODUCTS="worldpop fang_jawitz" bash sbatch/external_download.sh
#
# Public (no login): GHS-POP R2023A 100 m Mollweide, 1980 / 1990 / 2000 / 2010 (JRC's own AWS bucket, 4.2-5.1 GB
# each, size checked against the bucket listing recorded 2026-10-28); WorldPop USA 100 m unconstrained, 2000 / 2010
# (~4 GB each, size checked); Fang & Jawitz (2018) figshare .7z (602 MB, md5 checked; unpacked to grids/).
# NASA Earthdata login (~/.netrc entry for urs.earthdata.nasa.gov; docs/runbooks/Running_CONUS.md section 8):
# GPW v4.11 population count 30 arc-sec 2000 / 2010 (not UN-adjusted), GRUMP v1 population count 30 arc-sec
# 1990 / 2000 (global .bil), and the GPWv4 / GPWv3 documents (US input units). Without the .netrc entry these are
# skipped (the comparison runs without them). A product that fails does not stop the others; the summary at the
# end lists each one. Files already there with the right size / md5 are not downloaded again; a broken download
# resumes from its .part file. Exit code 1 only if a public product failed.
set -uo pipefail
cd "$(dirname "$0")/.."
source sbatch/cluster_env.sh

PRODUCTS=${PRODUCTS:-ghs_pop worldpop fang_jawitz gpw4 grump1}
OUT=$DATA_ROOT/raw/external
COOKIES=$HOME/.urs_cookies
mkdir -p "$OUT"
echo "== $(date -Is) host $(hostname) | products: $PRODUCTS -> $OUT"
df -h "$DATA_ROOT" | tail -1
command -v curc-quota >/dev/null && curc-quota 2>/dev/null | grep -E "projects|Filesystem" || true

declare -A STATUS
HAVE_NETRC=0
grep -qs "urs.earthdata.nasa.gov" "$HOME/.netrc" && HAVE_NETRC=1

fetch() {  # fetch <url> <dest> [auth]: download to <dest>.part (resumed), then rename
    local url=$1 dest=$2 auth=${3:-} opts=(-fsSL --retry 5 --retry-delay 15 --max-time 10800
                                                 -w '   %{size_download} bytes in %{time_total} s\n')  # -sS: no progress meter in the log
    [[ -n $auth ]] && opts+=(-n -b "$COOKIES" -c "$COOKIES")
    mkdir -p "$(dirname "$dest")"
    echo "   downloading $url"
    if ! curl "${opts[@]}" -C - -o "$dest.part" "$url"; then
        echo "   retrying from the start (no resume)"  # a server that ignores ranges, or a stale .part
        rm -f "$dest.part"
        curl "${opts[@]}" -o "$dest.part" "$url" || return 1
    fi
    mv "$dest.part" "$dest"
}

size_of() { stat -c %s "$1" 2>/dev/null || echo 0; }

by_size() {  # by_size <product> <url> <dest> <bytes>: download unless there with this size; check the size
    local p=$1 url=$2 dest=$3 bytes=$4
    if [[ $(size_of "$dest") == "$bytes" ]]; then
        echo "== $(basename "$dest"): already there, size ok ($bytes bytes)"
        return 0
    fi
    local now
    now=$(curl -sfIL --max-time 60 "$url" | grep -i '^content-length' | tail -1 | tr -dc '0-9')
    [[ -z $now || $now == "$bytes" ]] || echo "WARNING: $(basename "$dest") size changed since 2026-10-28 ($bytes -> $now bytes): the file was replaced at the source"
    fetch "$url" "$dest" || { echo "ERROR: $p: download of $url failed"; return 1; }
    local got
    got=$(size_of "$dest")
    [[ $got == "${now:-$bytes}" ]] || { echo "ERROR: $p: $(basename "$dest") has $got bytes, expected ${now:-$bytes}"; return 1; }
    echo "== $(basename "$dest"): size ok ($got bytes)"
}

ghs_pop() {
    # year bytes, from https://jrc-ghsl.s3.eu-central-1.amazonaws.com/?list-type=2&prefix=ghs-pop/r2023a/54009/100m/
    # (2026-10-28)
    local y b
    while read -r y b; do
        local f=GHS_POP_E${y}_GLOBE_R2023A_54009_100_V1_0.tif
        by_size ghs_pop "https://jrc-ghsl.s3.eu-central-1.amazonaws.com/ghs-pop/r2023a/54009/100m/$y/$f" \
            "$OUT/ghs_pop/$f" "$b" || return 1
    done <<< "1980 4189468816
1990 4542378023
2000 4742953518
2010 5121499452"
}

worldpop() {
    # data.worldpop.org does not serve byte ranges (2026-10-28): a broken download starts again from 0
    local y b
    while read -r y b; do
        by_size worldpop "https://data.worldpop.org/GIS/Population/Global_2000_2020/$y/USA/usa_ppp_$y.tif" \
            "$OUT/worldpop/usa_ppp_$y.tif" "$b" || return 1
    done <<< "2000 4006455556
2010 4012143985"
}

fang_jawitz() {
    # figshare article 5803110 (collection 3890191), file 10257111; md5 from the figshare API (2026-10-28)
    local md5=a7e869b0cd128721b1594151bd8f45d7 dest=$OUT/fang_jawitz/USA_HistoricalPopulationDataset.7z
    if [[ -f $dest && $(md5sum "$dest" | cut -d' ' -f1) == "$md5" ]]; then
        echo "== $(basename "$dest"): already there, md5 ok"
    else
        fetch https://ndownloader.figshare.com/files/10257111 "$dest" || { echo "ERROR: fang_jawitz: download failed"; return 1; }
        local got
        got=$(md5sum "$dest" | cut -d' ' -f1)
        [[ $got == "$md5" ]] || { echo "ERROR: fang_jawitz: md5 $got, expected $md5"; return 1; }
        echo "== $(basename "$dest"): md5 ok ($(du -h "$dest" | cut -f1))"
    fi
    local grids=$OUT/fang_jawitz/grids
    if [[ -f $grids/.unpacked_$md5 ]]; then
        echo "== grids/: already unpacked"
    else
        rm -rf "$grids"
        mkdir -p "$grids"
        echo "   unpacking (py7zr; Esri GRID folders pop_m<model>_<year>)"
        "$ENVS/hisdac/bin/python" -c "import py7zr, sys; py7zr.SevenZipFile(sys.argv[1]).extractall(sys.argv[2])" \
            "$dest" "$grids" || { echo "ERROR: fang_jawitz: unpacking failed (py7zr in the hisdac env? section 8 block 1a)"; return 1; }
        touch "$grids/.unpacked_$md5"
    fi
    echo "   $(find "$grids" -maxdepth 4 -type d -iname 'pop_m*' | wc -l) grid folders; M3 / M5:"
    find "$grids" -maxdepth 4 -type d \( -iname 'pop_m3_*' -o -iname 'pop_m5_*' \) | sort | sed 's/^/     /' | head -24
}

earthdata_zip() {  # earthdata_zip <product> <url> <zip dest> <unpack dir>
    local p=$1 url=$2 zip=$3 dir=$4
    if [[ -f $zip ]] && unzip -tq "$zip" >/dev/null 2>&1; then
        echo "== $(basename "$zip"): already there, zip ok"
    else
        rm -f "$zip"
        fetch "$url" "$zip" auth || { echo "ERROR: $p: download failed (Earthdata login: ~/.netrc, and the app authorized?)"; return 1; }
        unzip -tq "$zip" >/dev/null 2>&1 || { echo "ERROR: $p: $(basename "$zip") is not a valid zip (a login page? $(head -c 200 "$zip" | tr -d '\n'))"; rm -f "$zip"; return 1; }
        echo "== $(basename "$zip"): zip ok ($(du -h "$zip" | cut -f1))"
    fi
    rm -rf "$dir"
    mkdir -p "$dir"
    unzip -q -o "$zip" -d "$dir"
    find "$dir" -type f -printf '     %P %s bytes\n' | head -12
}

gpw4() {
    local base=https://data.earthdata.nasa.gov/nasa-earth/human-dimensions/sedac-root/downloads/data/gpw-v4/gpw-v4-population-count-rev11
    local y
    for y in 2000 2010; do
        earthdata_zip gpw4 "$base/gpw-v4-population-count-rev11_${y}_30_sec_tif.zip" \
            "$OUT/gpw4/gpw-v4-population-count-rev11_${y}_30_sec_tif.zip" "$OUT/gpw4/$y" || return 1
    done
    docs
}

grump1() {
    local base=https://data.earthdata.nasa.gov/nasa-earth/human-dimensions/sedac-root/gpw/app
    local y yy
    for y in 1990 2000; do
        yy=${y:2:2}
        earthdata_zip grump1 "$base/_region_Global_file_grumpv1_data_pcount_type_bil_level-scope_continent_resolut_30_year_$yy" \
            "$OUT/grump1/gl_grumpv1_pcount_${yy}_bil_30.zip" "$OUT/grump1/$y" || return 1
    done
    docs
}

DOCS_DONE=0
docs() {  # the GPWv4 / GPWv3 documents (US input units), once
    (( DOCS_DONE )) && return 0
    DOCS_DONE=1
    local base=https://data.earthdata.nasa.gov/nasa-earth/human-dimensions/sedac-root/downloads/docs-repo f
    for f in gpw-v4-rev11-documentation.pdf gpw-v4-rev11-country-level-summary-general-documentation.xlsx gpw-v3-documentation.pdf; do
        [[ -s $OUT/docs/$f ]] && { echo "== docs/$f: already there"; continue; }
        fetch "$base/$f" "$OUT/docs/$f" auth && echo "== docs/$f ($(du -h "$OUT/docs/$f" | cut -f1))" \
            || echo "WARNING: docs/$f not downloaded (input units stay unverified)"
    done
}

for p in $PRODUCTS; do
    echo "===== $p ($(date +%H:%M:%S))"
    if [[ $p == gpw4 || $p == grump1 ]] && (( ! HAVE_NETRC )); then
        echo "SKIPPED: no ~/.netrc entry for urs.earthdata.nasa.gov (docs/runbooks/Running_CONUS.md section 8); the comparison runs without $p"
        STATUS[$p]=skipped
        continue
    fi
    if "$p"; then STATUS[$p]=ok; else STATUS[$p]=FAILED; fi
done

echo "===== summary ($(date -Is))"
fail=0
for p in $PRODUCTS; do
    echo "   $p: ${STATUS[$p]}"
    [[ ${STATUS[$p]} == FAILED && $p != gpw4 && $p != grump1 ]] && fail=1
done
du -sh "$OUT"/* 2>/dev/null | sed 's/^/   /'
echo "== next: the inventory (headers only, login node): bash sbatch/external_compare.sh inventory"
exit $fail
