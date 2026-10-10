#!/usr/bin/env python3
"""
v2.4b: the release that standardises on 2400 baud with our own RS-232.

Nothing functional beyond v2.3.6d (patch234 ICR mask, patch235 first
start bit, patch236 hashtag keys -- all confirmed on real hardware). The
banner drops the "d" (driver) suffix: the driver build IS the release now.
The splash credit is art, not code (mksplash.py -> logo.bin).
The KERNAL build (mkkernal.py) remains a 600-baud fallback, banner v2.4b-600k.
"""
import io, sys

SRC_FILE = sys.argv[1] if len(sys.argv) > 1 else "mlfull.py"
KFILE = sys.argv[2] if len(sys.argv) > 2 else "mkkernal.py"
s = io.open(SRC_FILE, encoding="utf-8").read()
old = 'banner: .text "meshcore 64  v2.3.6d"'
assert s.count(old) == 1, old
s = s.replace(old, 'banner: .text "meshcore 64  v2.4b"')
io.open(SRC_FILE, "w", encoding="utf-8").write(s)

k = io.open(KFILE, encoding="utf-8").read()
for o, n in (('banner: .text "meshcore 64  v2.3.6d"', 'banner: .text "meshcore 64  v2.4b"'),
             ("'banner: .text \"meshcore 64  v2.3.6\"'", "'banner: .text \"meshcore 64  v2.4b-600k\"'")):
    assert k.count(o) == 1, o
    k = k.replace(o, n)
io.open(KFILE, "w", encoding="utf-8").write(k)
print("patched", SRC_FILE, KFILE)
