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

m.call("mmsel2")
check("no Kawari yet: the usual 6 items", m.mem[E["MNN"]] == 6)
m.call("kwboot")
check("Kawari detected: KWOK set, 80 columns on", m.mem[syms["KWOK"]] == 1 and m.mem[syms["K80"]] == 1)
def items():
    tab = m.mem[E["MNPTR"]] | m.mem[E["MNPTR"] + 1] << 8
    out = []
    for i in range(m.mem[E["MNN"]]):
        a = m.mem[tab + 2 * i] | m.mem[tab + 2 * i + 1] << 8
        b = []
        while m.mem[a]: b.append(m.mem[a]); a += 1
        out.append(bytes(b).decode())
    return out
m.call("mmsel2")
check("80: '40 column mode' above close", items()[5:] == ["40 column mode", "Close"])
m.mem[syms["mmshut"]] = 0x60
m.call("mmcol")
check("item 5 in 80 -> 40 columns", m.mem[syms["K80"]] == 0 and k.r[0xD037] & 16 == 0)
m.call("mmsel2")
check("40 with a Kawari: '80 column mode' above close", items()[5:] == ["80 column mode", "Close"])
m.call("mmcol")
vec = m.mem[0x0326] | m.mem[0x0327] << 8
check("item 5 in 40 -> 80 columns again, hooked", m.mem[syms["K80"]] == 1 and k.r[0xD037] & 16 == 16 and vec == syms["k80out"])
check("the KERNAL vector kept for later", (m.mem[syms["KOLDV"]] | m.mem[syms["KOLDV"] + 1] << 8) == KOUT)
m.call("mmsel2")
check("and the menu offers 40 again", items()[5:] == ["40 column mode", "Close"])
m.mem[syms["KWOK"]] = 0; m.call("mmcol")
m.call("mmsel2")
check("without a Kawari: 6 items in 40", m.mem[E["MNN"]] == 6 and m.mem[syms["K80"]] == 0)
# ---- F3 ----
m.mem[syms["KWOK"]] = 1
k80 = m.mem[syms["K80"]]
m.call("kf3")
check("F3 toggles the columns", m.mem[syms["K80"]] != k80)
m.call("kf3")
check("F3 again toggles back", m.mem[syms["K80"]] == k80)
m.mem[syms["KWOK"]] = 0; k80 = m.mem[syms["K80"]]
m.call("kf3")
check("no Kawari: F3 does nothing", m.mem[syms["K80"]] == k80)
m.call("kkeys"); a0 = m.mem[0xFB] | m.mem[0xFC] << 8
m.mem[syms["KWOK"]] = 1; m.call("kkeys"); a1 = m.mem[0xFB] | m.mem[0xFC] << 8
txt = bytes(c for c in bytes(m.mem[a1:a1 + 60]).split(b"\r")[0] if 32 <= c < 127).decode()
check("key line with F3 (%r, %d wide)" % (txt, len(txt)), a0 == syms["skeys2"] and a1 == syms["skeys3"] and len(txt) <= 39)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
