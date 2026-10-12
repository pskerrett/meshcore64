#!/usr/bin/env bash
# Build every MeshCore 64 artifact from source.
#   ./build.sh [outdir]          -> outdir/meshcore64-v2.0.{prg,crt,bin,d64}
# Needs python3 (+ Pillow only for mksplash.py), and VICE's cartconv and c1541.
set -eu
cd "$(dirname "$0")"
OUT=${1:-../release}
N=meshcore64-v2.0
mkdir -p "$OUT"
# args: baud-code(13 = 5760) out blank testkeys latadj [nogeo]
python3 meshcore64.py 13 "$OUT/$N.prg" 0 0 125
# the cartridge build never probes GeoRAM at boot (a cart cannot trust it): last arg 1
python3 meshcore64.py 13 "$OUT/cart.prg" 0 0 125 1
python3 mkcart.py "$OUT/cart.prg" "$OUT/$N.crt"      # also writes $N.bin (flat 64K, 27C512)
rm -f "$OUT/cart.prg"
rm -f "$OUT/$N.d64"
c1541 -format "meshcore 64,mc" d64 "$OUT/$N.d64" -write "$OUT/$N.prg" "meshcore64" >/dev/null
( cd "$OUT" && md5sum "$N".prg "$N".crt "$N".bin "$N".d64 | tee md5.txt )
