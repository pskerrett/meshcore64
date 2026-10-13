#!/usr/bin/env python3
"""v2.0.2c: a GeoRAM round trip -- fetch a list, "reset" (RAM gone, GeoRAM kept), restore -- in py65 with a GeoRAM model."""
import sys, os, importlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "."))
sys.path.insert(0, os.path.dirname(__file__))
from py65.devices.mpu6502 import MPU
mod = importlib.import_module(sys.argv[1] if len(sys.argv) > 1 else "meshcore64")
import clksim_base as B
code, syms, prg, bit, half = mod.build(13, "/tmp/gr.prg", 0, mod.PAL, 0, 125, 0)
E = mod.EQU
def A(l): return syms[l] if l in syms else E[l]
bad = 0
def check(n, c, extra=""):
    global bad
    bad += not c
    print("%-4s %s %s" % ("ok" if c else "FAIL", n, extra))

class GeoRAM:
    """$DE00-$DEFF = the 256-byte window; $DFFE = page 0-63, $DFFF = 16K block."""
    def __init__(self, kb=2048):
        self.mem = bytearray(kb * 1024); self.page = 0; self.blk = 0
    def attach(self, m):
        m.mem.subscribe_to_read(range(0xDE00, 0xDF00), lambda a: self.mem[self.base() + (a - 0xDE00)])
        m.mem.subscribe_to_write(range(0xDE00, 0xDF00), lambda a, v: self.put(a, v))
        m.mem.subscribe_to_write(range(0xDFFE, 0xE000), lambda a, v: self.reg(a, v))
    def base(self): return ((self.blk * 64 + self.page) * 256) % len(self.mem)
    def put(self, a, v): self.mem[self.base() + (a - 0xDE00)] = v
    def reg(self, a, v):
        if a == 0xDFFE: self.page = v & 63
        else: self.blk = v

def machine(geo):
    m = B.M(mod, code, syms, prg)
    geo.attach(m)
    for n in ("sync", "ndview"): m.mem[A(n)] = 0x60
    m.mem[0xFFD2] = 0x60
    s2off = syms["s2img"] - mod.ORG
    m.mem[A("gsvh")] = prg[2 + s2off + (A("gsvh") - 0xA000)]
    m.mem[A("RU")] = 2; m.mem[A("GBLKS")] = 128; m.mem[A("LSHIFT")] = 9
    m.mem[A("CBASEH")] = 0x40; m.mem[A("MAXCON")] = 160
    return m
def run(m, label, limit=6000000):
    t = 0x0300
    m.mem[t:t + 3] = [0x20, A(label) & 255, A(label) >> 8]
    c = MPU(memory=m.mem); c.pc, c.sp = t, 0xFF
    for _ in range(limit):
        if c.pc == t + 3: return
        c.step()
    raise AssertionError(label + " hung")

geo = GeoRAM()
# session 1: 40 repeaters fetched, the fetch ends
m1 = machine(geo)
m1.mem[A("NCONT")] = 40; m1.mem[A("NTYPE")] = 2
for i in range(40):
    for j in range(64): m1.mem[0x4000 + 64 * i + j] = (i * 7 + j) & 255
run(m1, "ndfend")
# "reset": fresh RAM, same GeoRAM; the boot restore
m2 = machine(geo)
run(m2, "georest")
check("restored: a session was found", m2.mem[A("GREST")] == 1)
check("restored: the node count", m2.mem[A("NCONT")] == 40, m2.mem[A("NCONT")])
check("restored: the repeater list is still marked loaded", m2.mem[A("TLOAD") + 2] == 1, [m2.mem[A("TLOAD") + i] for i in range(5)])
same = all(m2.mem[0x4000 + 64 * i + j] == (i * 7 + j) & 255 for i in range(40) for j in range(64))
check("restored: every node record", same)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
