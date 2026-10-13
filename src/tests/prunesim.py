#!/usr/bin/env python3
"""v2.0.2e: 255-node table (two blocks), last-heard times, the newest nodes kept, saved-format marker (meshcore64) in py65."""
import sys, os, importlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".")); sys.path.insert(0, os.path.dirname(__file__))
from py65.devices.mpu6502 import MPU
mod = importlib.import_module(sys.argv[1] if len(sys.argv) > 1 else "meshcore64")
import clksim_base as B
code, syms, prg, bit, half = mod.build(13, "/tmp/pr.prg", 0, mod.PAL, 0, 125, 0)
E = mod.EQU
A = lambda l: syms[l] if l in syms else E[l]
bad = 0
def check(n, c, extra=""):
    global bad
    bad += not c
    print("%-4s %s %s" % ("ok" if c else "FAIL", n, extra))
BASE = 1_750_000_000
def T(units): return BASE + 4096 * units + 17           # a last_advert that rxts turns into `units`
def new(cbase=0x40, maxcon=255):
    m = B.M(mod, code, syms, prg)
    for n in ("gsvk", "sync", "notice"): m.mem[A(n)] = 0x60
    m.mem[A("CBASEH")] = cbase; m.mem[A("MAXCON")] = maxcon
    return m
def rec(i, cbase=0x40):
    return (cbase << 8) + 64 * i if i < 160 else 0x8000 + 64 * (i - 160)
def call(m, label, a=0, x=0, y=0, limit=2000000):
    t = 0x0300; m.mem[t:t + 3] = [0x20, A(label) & 255, A(label) >> 8]
    c = MPU(memory=m.mem); c.pc, c.sp, c.a, c.x, c.y = t, 0xFF, a, x, y
    for _ in range(limit):
        if c.pc == t + 3: return c
        c.step()
    raise AssertionError(label + " hung")
def frame(m, typ, ts, name=b"newnode", flen=148, key=1):
    f = bytearray(148); f[0] = 3; f[1:33] = bytes((key * 7 + i) & 255 for i in range(32)); f[33] = typ
    f[35] = 2; f[36:40] = b"\x11\x22\x33\x44"; f[100:100 + len(name)] = name
    f[132:136] = ts.to_bytes(4, "little")
    for i, b in enumerate(f): m.mem[A("BUF") + i] = b
    m.mem[A("FLEN")] = flen
def times(m, n): return [m.mem[rec(i) + 24] | m.mem[rec(i) + 25] << 8 for i in range(n)]
# --- contptr
m = new()
for i, want in ((0, 0x4000), (1, 0x4040), (3, 0x40C0), (4, 0x4100), (159, 0x4000 + 159 * 64), (160, 0x8000), (161, 0x8040), (254, 0x8000 + 94 * 64)):
    c = call(m, "contptr", a=i, x=9, y=7)
    check("contptr(%d) = $%04X" % (i, want), (m.mem[0xFB] | m.mem[0xFC] << 8) == want or (m.mem[A("PTR")] | m.mem[A("PTRH")] << 8) == want, hex(m.mem[A("PTR")] | m.mem[A("PTRH")] << 8))
    if i == 0: check("contptr keeps X and Y", c.x == 9 and c.y == 7)
m = new(cbase=0x80, maxcon=96)
call(m, "contptr", a=5)
check("no expansion: slot 5 = $8140", (m.mem[A("PTR")] | m.mem[A("PTRH")] << 8) == 0x8140)
# --- rxts
m = new()
for lab, ts, flen, want in (("short frame", T(9), 120, 0), ("before the base", BASE - 5, 148, 0), ("exactly the base", BASE, 148, 0),
                             ("5 units", T(5), 148, 5), ("1000 units", T(1000), 148, 1000), ("too new", BASE + 4096 * 70000, 148, 65535)):
    frame(m, 2, ts, flen=flen); call(m, "rxts")
    got = m.mem[A("RXT")] | m.mem[A("RXT") + 1] << 8
    check("rxts: " + lab, got == want, got)
# --- append: name cut to 23 characters, time and key stored, counted
m = new(); m.mem[A("NTYPE")] = 2; m.mem[A("NCONT")] = 0
frame(m, 2, T(42), name=b"abcdefghijklmnopqrstuvwxyz")
call(m, "rxcont")
r = rec(0)
nm = bytes(m.mem[r + i] for i in range(26))
check("append: name is 23 characters and ends", nm[:23] == b"abcdefghijklmnopqrstuvw" and nm[23] == 0, nm)
check("append: time at 24-25", m.mem[r + 24] | m.mem[r + 25] << 8 == 42)
check("append: key, type, route intact", bytes(m.mem[r + 26 + i] for i in range(32)) == bytes((7 + i) & 255 for i in range(32)) and m.mem[r + 59] == 2 and m.mem[r + 58] == 2 and m.mem[r + 60] == 0x11)
check("append: counted", m.mem[A("NCONT")] == 1)
m.mem[A("NTYPE")] = 3; frame(m, 2, T(1)); call(m, "rxcont")
check("another type is not kept while fetching type 3", m.mem[A("NCONT")] == 1)
m.mem[A("NTYPE")] = 0; frame(m, 4, T(1), key=2); call(m, "rxcont")
check("NTYPE 0 keeps every type", m.mem[A("NCONT")] == 2)
# --- a full table keeps the newest
m = new(maxcon=5); m.mem[A("NTYPE")] = 0
for i, t in enumerate([10, 3, 7, 3, 9]):
    frame(m, 1, T(t), name=b"n%d" % i, key=i + 10); call(m, "rxcont")
check("filled", m.mem[A("NCONT")] == 5 and times(m, 5) == [10, 3, 7, 3, 9])
frame(m, 1, T(5), name=b"fresh", key=50); call(m, "rxcont")
t = times(m, 5)
check("newer than the oldest: replaces it (the first of two equal), count unchanged", m.mem[A("NCONT")] == 5 and t == [10, 5, 7, 3, 9], t)
check("the replaced record is complete", bytes(m.mem[rec(1) + i] for i in range(5)) == b"fresh" and m.mem[rec(1) + 26] == (50 * 7) & 255)
frame(m, 1, T(2), name=b"stale", key=51); call(m, "rxcont")
check("older than the oldest: dropped", times(m, 5) == [10, 5, 7, 3, 9] and bytes(m.mem[rec(3) + i] for i in range(2)) == b"n3")
frame(m, 1, T(3), name=b"equal", key=52); call(m, "rxcont")
check("same time as the oldest: dropped", times(m, 5) == [10, 5, 7, 3, 9])
# unknown time (0) counts as the oldest of all
m = new(maxcon=4); m.mem[A("NTYPE")] = 0
for i, t in enumerate([6, 0, 8, 4]):
    frame(m, 1, T(t) if t else 0, name=b"u%d" % i, key=i + 20); call(m, "rxcont")
frame(m, 1, T(1), name=b"new", key=60); call(m, "rxcont")
check("an unknown time is the first to go", times(m, 4) == [6, 1, 8, 4], times(m, 4))
# --- the second block: 255 slots, the oldest in block B is replaced there
m = new(); m.mem[A("NTYPE")] = 0
for i in range(255):
    frame(m, 1 + i % 4, T(1000 + i), name=b"n%03d" % i, key=(i % 250) + 1)
    m.mem[A("BUF") + 1] = i & 255; m.mem[A("BUF") + 2] = i >> 8 if i > 255 else 0
    call(m, "rxcont")
check("255 nodes held, two blocks", m.mem[A("NCONT")] == 255)
check("slot 160 is at $8000 and 254 at $9780", bytes(m.mem[0x8000 + i] for i in range(4)) == b"n160" and bytes(m.mem[0x8000 + 94 * 64 + i] for i in range(4)) == b"n254")
frame(m, 2, T(5000), name=b"hot", key=77); call(m, "rxcont")
check("a 256th node (newest) replaces the oldest: slot 0", bytes(m.mem[rec(0) + i] for i in range(3)) == b"hot" and m.mem[A("NCONT")] == 255)
m.mem[rec(200) + 24] = 0; m.mem[rec(200) + 25] = 0      # slot 200 (second block) becomes the oldest
frame(m, 2, T(6000), name=b"hot2", key=78); call(m, "rxcont")
check("the oldest in the second block is the one replaced", bytes(m.mem[rec(200) + i] for i in range(4)) == b"hot2" and bytes(m.mem[rec(0) + i] for i in range(3)) == b"hot")
# --- the node-format marker
m = new(); m.mem[A("NCONT")] = 5; m.mem[A("NFMT")] = 0
for i in range(5): m.mem[A("TLOAD") + i] = 1
m.mem[A("DMMK")] = 0xD7; m.mem[A("DMUSE")] = 1
call(m, "dmfix")
check("old node format: table dropped, lists reload, history untouched, marker set", m.mem[A("NCONT")] == 0 and all(m.mem[A("TLOAD") + i] == 0 for i in range(5)) and m.mem[A("NFMT")] == 0xB1 and m.mem[A("DMUSE")] == 1)
m.mem[A("NCONT")] = 9; m.mem[A("TLOAD") + 2] = 1
call(m, "dmfix")
check("current format: nothing touched", m.mem[A("NCONT")] == 9 and m.mem[A("TLOAD") + 2] == 1)
# --- the title says "newest" for a full table
m = new(maxcon=160); m.mem[A("NTYPE")] = 2; m.mem[A("NVIS")] = 12; m.mem[A("NCONT")] = 160
call(m, "ndtit")
def title():
    a = A("NTBUF"); b = []
    while m.mem[a]: b.append(m.mem[a]); a += 1
    return "".join(chr(x + 32 if 65 <= x <= 90 else x) for x in b)
check("full table: ' repeaters (12) newest '", title() == " repeaters (12) newest ", title())
m.mem[A("NCONT")] = 159; call(m, "ndtit")
check("a table with room: no suffix", title() == " repeaters (12) ", title())
print("FAILURES:", bad); sys.exit(1 if bad else 0)
