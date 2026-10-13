#!/usr/bin/env python3
"""v2.0.2c: the saved GeoRAM session says "loaded" for the list just fetched (ndfend) in py65."""
import sys, os, importlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "."))
sys.path.insert(0, os.path.dirname(__file__))
from py65.devices.mpu6502 import MPU
mod = importlib.import_module(sys.argv[1] if len(sys.argv) > 1 else "meshcore64")
import clksim_base as B
code, syms, prg, bit, half = mod.build(13, "/tmp/ld.prg", 0, mod.PAL, 0, 125, 0)
E = mod.EQU
def A(l): return syms[l] if l in syms else E[l]
bad = 0
def check(n, c, extra=""):
    global bad
    bad += not c
    print("%-4s %s %s" % ("ok" if c else "FAIL", n, extra))
m = B.M(mod, code, syms, prg)
for n in ("ndview", "sync"): m.mem[A(n)] = 0x60
# the harness stubs gsvh out; put the real first byte back (this test is about what it saves)
s2off = syms["s2img"] - mod.ORG
m.mem[A("gsvh")] = prg[2 + s2off + (A("gsvh") - 0xA000)]
m.mem[0xFFD2] = 0x60
m.mem[A("RU")] = 2                      # a GeoRAM
m.mem[A("GBLKS")] = 128
m.mem[A("CBASEH")] = 0x40; m.mem[A("MAXCON")] = 160
m.mem[A("NCONT")] = 3
for i in range(3 * 64): m.mem[0x4000 + i] = 7
m.mem[A("NTYPE")] = 2                   # repeaters
for i in range(5): m.mem[A("TLOAD") + i] = 0
m.mem[A("SYNCP")] = 0
t = 0x0300
m.mem[t:t + 3] = [0x20, A("ndfend") & 255, A("ndfend") >> 8]
c = MPU(memory=m.mem); c.pc, c.sp = t, 0xFF
for _ in range(3000000):
    if c.pc == t + 3: break
    c.step()
else:
    raise AssertionError("ndfend hung")
check("in memory: this list is marked loaded", m.mem[A("TLOAD") + 2] == 1)
check("in the SAVED header (GeoRAM): this list is marked loaded", m.mem[0xDE00 + 10 + 2] == 1, [m.mem[0xDE00 + 10 + i] for i in range(5)])
check("the saved header carries the node count", m.mem[0xDE00 + 7] == 3)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
