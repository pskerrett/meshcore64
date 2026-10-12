#!/usr/bin/env python3
"""s41: F1 > Stats (meshcore64.py) with video standard, Ultimate clock, 16-bit frames."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "."))
sys.path.insert(0, os.path.dirname(__file__))
import meshcore64, clksim_base as B
code, syms, prg, bit, half = meshcore64.build(13, "/tmp/st2.prg", 0, meshcore64.PAL, 0, 125, 0)
E = meshcore64.EQU
bad = 0
def check(n, c):
    global bad
    bad += not c
    print("%-4s %s" % ("ok" if c else "FAIL", n))
def S(l): return syms[l]
def run(uci, ntsc):
    m = B.M(meshcore64, code, syms, prg, uci)
    for n in ("sendfr", "waitop", "plshow", "mmshut"): m.mem[S(n)] = 0x60
    for i, b in enumerate([12, 0x5A, 0x0F, 109, 0, 0, 0, 0, 0]): m.mem[E["BUF"] + i] = b   # 3930 mV, 109 KB
    m.mem[0xA0], m.mem[0xA1], m.mem[0xA2] = 0, 0x1C, 0x20         # 7200 jiffies = 2m
    m.mem[E["ISNTSC"]] = ntsc
    m.mem[E["NCONT"]] = 153; m.mem[E["NFRM"]] = 0x2C; m.mem[S("NFRMH")] = 1     # 300 frames
    m.mem[E["RJ"]] = 0; m.mem[E["UNK"]] = 2; m.mem[E["PBAD"]] = 0; m.mem[E["FRERR"]] = 0; m.mem[E["OVR"]] = 69
    m.mem[E["RU"]] = 1; m.mem[E["UKL"]] = 0; m.mem[E["UKH"]] = 8
    m.mem[E["MAXCON"]] = 96; m.mem[E["MAXL"]] = 0; m.mem[E["MAXH"]] = 2       # 512 lines a region
    for r in range(9):                                                        # 1567 of 4608 lines = 34%
        v = 174 if r < 8 else 175
        m.mem[E["LFL"] + r] = v & 255; m.mem[E["LFH"] + r] = v >> 8
    m.call("stat4")
    out = []
    for i in range(m.mem[E["PLN"]]):
        a = E["PLBUF"] + 32 * i; b = []
        while m.mem[a] and len(b) < 32: b.append(m.mem[a]); a += 1
        out.append(bytes(b).decode("latin1"))
    return out
l = run("2026/10/12 18:22:07", 0)
for x in l: print("   |" + x)
check("10 lines, each <= 28 wide", len(l) == 12 and max(map(len, l)) <= 28)
check("Video PAL", l[3] == "Video     PAL")
check("Clock read from the Ultimate", l[4] == "Clock     2026/10/12 18:22")
check("Link with the buffer peak", l[9] == "Link      5760 baud, peak 69")
check("Frames 16-bit, error total", l[10] == "Frames    300, errors 2")
check("Nodes of the maximum", l[8] == "Nodes     153 of 96")
check("Memory: REU and how full (34%%)", l[11] == "Memory    REU 2048K 34% full")
l = run(None, 1)
check("NTSC, and no RTC", l[3] == "Video     NTSC" and l[4] == "Clock     no RTC")
print("FAILURES:", bad); sys.exit(1 if bad else 0)
