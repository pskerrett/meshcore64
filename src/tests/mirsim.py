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
m.mem[0x0326], m.mem[0x0327] = syms["k80out"] & 255, syms["k80out"] >> 8
for a in range(0x1000, 0x17D0): k.v[a] = ord("x")
m.call("k40m")
check("menu: 80 column display stays on", k.r[0xD037] & 16 == 16 and m.mem[syms["K40"]] == 1)
check("80 column screen blanked for the menu", row(0) == b" " * 80 and row(24) == b" " * 80)
for i, c in enumerate(b"MENU BOX"): m.mem[0x0400 + 5 * 40 + 3 + i] = c - 64 if c > 64 else c
for i in range(40): m.mem[0xD800 + 5 * 40 + i] = 14
m.mem[0x0400 + 24 * 40 + 39] = 0x81   # a reverse 'a' in the last cell
for z in range(0xF7, 0xFF): m.mem[z] = 0x11 * (z - 0xF0)
from py65.devices.mpu6502 import MPU
t = 0x0300
m.mem[t:t + 3] = [0x20, syms["kmir"] & 255, syms["kmir"] >> 8]
cpu = MPU(memory=m.mem); cpu.pc, cpu.sp, cpu.x, cpu.y = t, 0xFF, 0x42, 0x24
while cpu.pc != t + 3: cpu.step()
check("registers X/Y kept", cpu.x == 0x42 and cpu.y == 0x24)
check("zero page untouched", all(m.mem[z] == 0x11 * (z - 0xF0) for z in range(0xF7, 0xFF)))
check("menu row copied, centred (columns 20-59)", row(5)[23:31] == bytes(c - 64 if c > 64 else c for c in b"MENU BOX") and row(5)[:20] == b" " * 20 and row(5)[60:] == b" " * 20)
check("its colours, second character set", crow(5)[20] == (14 | 0x80) and crow(5)[59] == (14 | 0x80))
check("last cell copied too (reverse glyph code kept)", row(24)[59] == 0x81)
before = bytes(k.v[0x1000:0x17D0])
m.mem[0x0400 + 5 * 40 + 3] = 1
cpu = MPU(memory=m.mem); cpu.pc, cpu.sp = t, 0xFF
while cpu.pc != t + 3: cpu.step()
check("throttled: a second call straight after copies nothing", bytes(k.v[0x1000:0x17D0]) == before)
m.call("k80c")
check("back to the chat: menu flag off, still 80 columns", m.mem[syms["K40"]] == 0 and k.r[0xD037] & 16 == 16)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
