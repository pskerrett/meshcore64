#!/usr/bin/env python3
"""s27: the Kawari 80 column chat driver (ml80.py) in py65, against an
emulated Kawari (ports, index, auto-increment, DMA copy/fill)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "."))
sys.path.insert(0, os.path.dirname(__file__))
from py65.devices.mpu6502 import MPU
import meshcore64 as ml80, clksim_base as B
code, syms, prg, bit, half = ml80.build(13, "/tmp/k80.prg", 0, ml80.PAL, 0, 125, 0)
E = ml80.EQU
bad = 0


def check(name, cond):
    global bad
    bad += not cond
    print("%-4s %s" % ("ok" if cond else "FAIL", name))


class Kawari:
    def __init__(self):
        self.seq, self.active = [], False
        self.v = bytearray(65536)
        self.r = {0xD035: 0, 0xD036: 0, 0xD039: 0, 0xD03A: 0, 0xD03C: 0, 0xD03D: 0, 0xD037: 0, 0xD038: 0}
        self.flags = 0
        self.dmas = 0

    def a(self): return self.r[0xD039] | self.r[0xD03A] << 8

    def wr(self, ad, val):
        if ad == 0xD03F:
            if not self.active:
                self.seq = (self.seq + [val])[-4:]
                self.active = self.seq == [86, 73, 67, 50]
            else:
                self.flags = val
            return
        if not self.active: return
        if ad == 0xD03B:
            if self.flags == 15:
                n = self.r[0xD035] | self.r[0xD036] << 8
                dst, src = self.a(), self.r[0xD03C] | self.r[0xD03D] << 8
                if val == 1:
                    for i in range(n): self.v[(dst + i) & 0xFFFF] = self.v[(src + i) & 0xFFFF]
                elif val == 4:
                    for i in range(n): self.v[(dst + i) & 0xFFFF] = self.r[0xD03C]
                self.r[0xD035] = self.r[0xD036] = 0
                self.dmas += 1
                return
            self.v[(self.a() + self.r[0xD035]) & 0xFFFF] = val
            if self.flags & 3 == 1:
                x = (self.a() + 1) & 0xFFFF
                self.r[0xD039], self.r[0xD03A] = x & 255, x >> 8
            return
        self.r[ad] = val

    def rd(self, ad):
        if not self.active: return 0xFF
        if ad == 0xD03B: return self.v[(self.a() + self.r[0xD035]) & 0xFFFF]
        return self.r.get(ad, 0)


m = B.M(ml80, code, syms, prg)
k = Kawari()
CHARGEN = bytes((i * 5 + 1) & 255 for i in range(4096))
jif = [0]
def rdj(a):
    jif[0] += 1
    return (jif[0] // 30) & 255
m.mem.subscribe_to_read([0xA2], rdj)
def rdio(a):
    if (m.mem[1] & 4) == 0: return CHARGEN[a - 0xD000]
    if 0xD035 <= a <= 0xD03F: return k.rd(a)
    return m.mem._subject[a]
m.mem.subscribe_to_read(range(0xD000, 0xE000), rdio)
m.mem.subscribe_to_write(range(0xD035, 0xD040), lambda a, v: k.wr(a, v))
# KERNAL: CHROUT jumps through $0326; the "40 column" output just counts
KOUT = 0x0340
kernal40 = []
m.mem[0xFFD2:0xFFD5] = [0x6C, 0x26, 0x03]
m.mem[KOUT] = 0x60
m.mem.subscribe_to_read([KOUT], lambda a: 0x60 if not kernal40.append(m.mem[0x0100 + 0]) else 0x60)
m.mem[0x0326], m.mem[0x0327] = KOUT & 255, KOUT >> 8
m.mem[0xFFE4:0xFFE7] = [0xA9, 0x00, 0x60]     # GETIN: nothing
m.mem[0xFFF0] = 0x60                           # PLOT
m.mem[1] = 0x36
m.mem[0x9A] = 3
m.mem[E["NMIEN"]] = 0x10
m.mem[E["TXTCOL"]] = 5
# a boot screen in 40 columns
for i in range(1000): m.mem[0x0400 + i] = 32
for i, c in enumerate(b"MESHCORE"): m.mem[0x0400 + i] = c - 64
for i in range(1000): m.mem[0xD800 + i] = 14
m.mem[214] = 6

m.call("kwboot")
def row(r, n=80): return bytes(k.v[0x1000 + r * 80: 0x1000 + r * 80 + n])
def crow(r, n=80): return bytes(k.v[0x1800 + r * 80: 0x1800 + r * 80 + n])
def put40(r, text, colour=5, first=False):
    t = text.ljust(40)[:40]
    for i, c in enumerate(t): m.mem[0x0400 + r * 40 + i] = ord(c)
    if first: m.mem[0x0400 + r * 40 + 39] |= 0x80
    for i in range(40): m.mem[0xD800 + r * 40 + i] = colour
# a page: rule, a 3-row message, rule, a 1-row message, rule, a 2-row message
page = [("@" * 40, 11, False, 2), ("A" * 40, 5, True, 0), ("B" * 40, 5, False, 1), ("C" * 10, 5, False, 1),
        ("@" * 40, 11, False, 2), ("short one", 7, True, 0), ("@" * 40, 11, False, 2),
        ("D" * 40, 5, True, 0), ("E" * 5, 5, False, 1)]
first = 24 - len(page)
for i in range(25):
    for j in range(80): k.v[0x1000 + i * 80 + j] = ord("x")
for i, (t, c, f, ty) in enumerate(page):
    put40(first + i, t, c, f)
    m.mem[E["TMP"]] = first; m.mem[E["CNT"]] = i
    m.mem[0xFB] = (0x0400 + (first + i) * 40) & 255; m.mem[0xFC] = (0x0400 + (first + i) * 40) >> 8
    m.call("k80typ")
    m.mem[0x0400 + (first + i) * 40 + 39] &= 0x7F
m.mem[E["TMP"]] = first
m.call("k80flow")
types = [m.mem[syms["KTYP"] + first + i] for i in range(len(page))]
check("row types noted", types == [p[3] for p in page])
M = m.mem[syms["KM"]]
check("9 rows -> 7 lines", M == 7)
# lines bottom-aligned at rows 17..23
check("rule stretched across", row(17) == bytes([64]) * 80 and row(20) == bytes([64]) * 80)
check("message rows 1|2 side by side", row(18) == b"A" * 40 + b"B" * 40)
check("row 3 alone on the next line", row(19)[:10] == b"C" * 10 and row(19)[40:] == b" " * 40)
check("1-row message", row(21)[:9] == b"short one" and row(21)[40:] == b" " * 40)
check("2-row message on one line", row(23) == b"D" * 40 + b"E" * 5 + b" " * 35)
check("colours follow, second set", crow(21)[0] == (7 | 0x80) and crow(23)[45] == (5 | 0x80) and crow(23)[79] == (5 | 0x80))
check("rows above the page blanked, nothing higher touched", row(first) == b" " * 80 and row(16) == b" " * 80 and row(first - 1) == b"x" * 80)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
