#!/usr/bin/env bash
# Build every MeshCore 64 artifact from source.
#   ./build.sh [outdir]          -> outdir/meshcore64-v2.0.2.{prg,crt,bin,d64} and meshcore64-ez-v2.0.2.crt
# Needs python3 (+ Pillow only for mksplash.py), and VICE's cartconv and c1541.
set -eu
cd "$(dirname "$0")"
OUT=${1:-../release}
N=meshcore64-v2.0.2
mkdir -p "$OUT"
# args: baud-code(13 = 5760) out blank testkeys latadj
# ONE program for every format: the cartridges, the EasyFlash image and the disk all carry exactly this PRG.
python3 meshcore64.py 13 "$OUT/$N.prg" 0 0 125
python3 mkcart.py "$OUT/$N.prg" "$OUT/$N.crt"      # also writes $N.bin (flat 64K, 27C512)
python3 mkcart_ez.py "$OUT/$N.prg" "$OUT/meshcore64-ez-v2.0.2.crt"   # the same program on an EasyFlash cartridge
rm -f "$OUT/$N.d64"
c1541 -format "meshcore 64,mc" d64 "$OUT/$N.d64" -write "$OUT/$N.prg" "meshcore64" >/dev/null
( cd "$OUT" && md5sum "$N".prg "$N".crt "$N".bin "$N".d64 meshcore64-ez-v2.0.2.crt | tee md5.txt )
