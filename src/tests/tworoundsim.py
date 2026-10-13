#!/usr/bin/env python3
"""v2.0.2e: save and restore the node table in two blocks through a GeoRAM and through an REU (meshcore64) in py65."""
import sys, os, importlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".")); sys.path.insert(0, os.path.dirname(__file__))
from py65.devices.mpu6502 import MPU
mod = importlib.import_module(sys.argv[1] if len(sys.argv) > 1 else "meshcore64")
import clksim_base as B
code, syms, prg, bit, half = mod.build(13, "/tmp/tr.prg", 0, mod.PAL, 0, 125, 0)
E = mod.EQU
A = lambda l: syms[l] if l in syms else E[l]
bad = 0
def check(n, c, extra=""):
    global bad
    bad += not c
    print("%-4s %s %s" % ("ok" if c else "FAIL", n, extra))
class GeoRAM:
    def __init__(self, kb=2048): self.mem = bytearray(kb * 1024); self.page = 0; self.blk = 0
    def attach(self, m):
        m.mem.subscribe_to_read(range(0xDE00, 0xDF00), lambda a: self.mem[self.base() + (a - 0xDE00)])
        m.mem.subscribe_to_write(range(0xDE00, 0xDF00), lambda a, v: self.put(a, v))
        m.mem.subscribe_to_write(range(0xDFFE, 0xE000), lambda a, v: self.reg(a, v))
    def base(self): return ((self.blk * 64 + self.page) * 256) % len(self.mem)
    def put(self, a, v): self.mem[self.base() + (a - 0xDE00)] = v
    def reg(self, a, v):
        if a == 0xDFFE: self.page = v & 63
        else: self.blk = v
class REU:
    """$DF01 command, $DF02/3 C64 address, $DF04-6 REU address, $DF07/8 length: stash ($x0) and fetch ($x1)."""
    def __init__(self, kb=2048): self.mem = bytearray(kb * 1024)
    def attach(self, m):
        self.m = m
        m.mem.subscribe_to_write(range(0xDF01, 0xDF02), lambda a, v: self.cmd(v))
    def cmd(self, v):
        mm = self.m.mem
        if not v & 0x80: return
        c64 = mm[0xDF02] | mm[0xDF03] << 8
        reu = mm[0xDF04] | mm[0xDF05] << 8 | (mm[0xDF06] & 0x1F) << 16
        n = mm[0xDF07] | mm[0xDF08] << 8 or 65536
        for i in range(n):
            if v & 3 == 0: self.mem[reu + i] = mm[(c64 + i) & 0xFFFF]
            elif v & 3 == 1: mm[(c64 + i) & 0xFFFF] = self.mem[reu + i]
        # the registers keep advancing as on the real chip
        mm[0xDF02], mm[0xDF03] = (c64 + n) & 255, ((c64 + n) >> 8) & 255
def machine(kind, store, cbase=0x40):
    m = B.M(mod, code, syms, prg)
    store.attach(m)
    for n in ("sync", "ndview"): m.mem[A(n)] = 0x60
    m.mem[0xFFD2] = 0x60
    s2off = syms["s2img"] - mod.ORG
    m.mem[A("gsvh")] = prg[2 + s2off + (A("gsvh") - 0xA000)]
    m.mem[A("RU")] = 2 if kind == "geo" else 1
    m.mem[A("GBLKS")] = 128; m.mem[A("LSHIFT")] = 9; m.mem[A("UKH")] = 8
    m.mem[A("CBASEH")] = cbase; m.mem[A("MAXCON")] = 255
    if kind == "reu":
        t = 0x0300; m.mem[t:t + 3] = [0x20, A("rdset") & 255, A("rdset") >> 8]
        c = MPU(memory=m.mem); c.pc, c.sp, c.a = t, 0xFF, 9
        while c.pc != t + 3: c.step()
    return m
def run(m, label, limit=40000000):
    t = 0x0300; m.mem[t:t + 3] = [0x20, A(label) & 255, A(label) >> 8]
    c = MPU(memory=m.mem); c.pc, c.sp = t, 0xFF
    for _ in range(limit):
        if c.pc == t + 3: return
        c.step()
    raise AssertionError(label + " hung")
def rec(i): return 0x4000 + 64 * i if i < 160 else 0x8000 + 64 * (i - 160)
for kind, store in (("geo", GeoRAM()), ("reu", REU())):
    for n in (40, 160, 161, 255):
        m1 = machine(kind, store)
        m1.mem[A("NCONT")] = n; m1.mem[A("NTYPE")] = 2
        for i in range(n):
            for j in range(64): m1.mem[rec(i) + j] = (i * 11 + j * 3 + 5) & 255
        run(m1, "ndfend")                       # fetch ended: table and header saved, the list marked loaded
        m2 = machine(kind, store)               # reset: fresh RAM, same expansion memory
        run(m2, "georest")
        ok = all(m2.mem[rec(i) + j] == (i * 11 + j * 3 + 5) & 255 for i in range(n) for j in range(64))
        check("%s %d nodes: restored (count %d, loaded %s) every record %s" % (kind, n, m2.mem[A("NCONT")], m2.mem[A("TLOAD") + 2] == 1, "ok" if ok else "BAD"),
              m2.mem[A("GREST")] == 1 and m2.mem[A("NCONT")] == n and m2.mem[A("TLOAD") + 2] == 1 and ok)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
