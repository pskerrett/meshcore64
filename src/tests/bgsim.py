#!/usr/bin/env python3
"""v2.0.2d: node lists loaded in the background at start (meshcore64) in py65."""
import sys, os, importlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".")); sys.path.insert(0, os.path.dirname(__file__))
from py65.devices.mpu6502 import MPU
mod = importlib.import_module(sys.argv[1] if len(sys.argv) > 1 else "meshcore64")
import clksim_base as B
code, syms, prg, bit, half = mod.build(13, "/tmp/bg.prg", 0, mod.PAL, 0, 125, 0)
E = mod.EQU
A = lambda l: syms[l] if l in syms else E[l]
bad = 0
def check(n, c, extra=""):
    global bad
    bad += not c
    print("%-4s %s %s" % ("ok" if c else "FAIL", n, extra))
class Sim:
    def __init__(self):
        self.m = B.M(mod, code, syms, prg)
        self.sent = []; self.calls = []
        for n in ("gsvk", "sync", "notice", "plinit", "plshow", "stl", "stend", "stnum", "mmshut"): self.m.mem[A(n)] = 0x60
        self.m.mem[0xFFD2] = 0x60
        self.m.mem[A("CBASEH")] = 0x40; self.m.mem[A("MAXCON")] = 160
    def run(self, label, a=0, setup=None):
        m = self.m; t = 0x0300
        m.mem[t:t + 3] = [0x20, A(label) & 255, A(label) >> 8]
        c = MPU(memory=m.mem); c.pc, c.sp, c.a = t, 0xFF, a
        names = {A(n): n for n in ("gsvk", "sync", "notice", "plshow")}
        for _ in range(400000):
            if c.pc == t + 3: break
            if c.pc == A("sendfr"):
                self.sent.append(bytes(m.mem[A("TXBUF") + i] for i in range(m.mem[A("TXLEN")]))); c.pc = (c.ByteAt(0x100 + c.sp + 1) | c.ByteAt(0x100 + c.sp + 2) << 8) + 1; c.sp += 2; continue
            if c.pc in names: self.calls.append(names[c.pc])
            c.step()
        else: raise AssertionError(label + " hung")
        return c
    def mem(self, n, v=None, off=0):
        if v is None: return self.m.mem[A(n) + off]
        self.m.mem[A(n) + off] = v
def frame(sim, typ, op=3):
    f = bytearray(148); f[0] = op; f[1:33] = bytes((typ * 9 + i) & 255 for i in range(32)); f[33] = typ
    f[100:104] = b"nodz"
    for i, b in enumerate(f): sim.m.mem[A("BUF") + i] = b
    sim.m.mem[A("FLEN")] = 148
# --- start: waits, then loads when a list is missing
s = Sim(); s.mem("BGST", 0); s.mem("UIMODE", 0); s.mem("SCBUSY", 0)
for i in range(5): s.mem("TLOAD", 0, i)
s.m.mem[0xA1] = 100; s.run("bgtick")
check("first call: waiting, time noted", s.mem("BGST") == 4 and s.mem("BGT") == 100 and s.sent == [])
s.m.mem[0xA1] = 101; s.run("bgtick")
check("too early: still waiting", s.mem("BGST") == 4 and s.sent == [])
s.mem("UIMODE", 1); s.m.mem[0xA1] = 110; s.run("bgtick")
check("a menu is up: waits", s.mem("BGST") == 4 and s.sent == [])
s.mem("UIMODE", 0); s.mem("NCONT", 7); s.mem("TLOAD", 1, 2); s.run("bgtick")
check("starts: GET_CONTACTS sent for everything", s.sent == [bytes([4])])
check("starts: table emptied, flags cleared, every type kept, link owned", s.mem("NCONT") == 0 and all(s.mem("TLOAD", off=i) == 0 for i in range(5)) and s.mem("NTYPE") == 0 and s.mem("SCBUSY") == 1 and s.mem("BGST") == 1)
# --- frames of every type are kept while it runs (dispat -> rxcont)
for typ in (1, 2, 3, 4, 2):
    frame(s, typ); s.run("dispat")
check("five nodes of four types kept", s.mem("NCONT") == 5)
# --- the end
frame(s, 0, op=4); s.run("dispat")
check("END: every list marked loaded", all(s.mem("TLOAD", off=i) == 1 for i in range(1, 5)))
check("END: link released, saved, notice shown", s.mem("SCBUSY") == 0 and s.mem("BGST") == 3 and "gsvk" in s.calls and "notice" in s.calls)
n = s.calls.count("gsvk"); frame(s, 0, op=4); s.run("dispat")
check("a later END frame does nothing", s.calls.count("gsvk") == n)
# --- a node table already there (restored from the REU / GeoRAM): every list loaded, nothing sent
s = Sim(); s.mem("BGST", 0); s.mem("NCONT", 40)
for i in range(5): s.mem("TLOAD", 0, i)
s.run("bgtick")
check("restored table: every list marked loaded, nothing sent, off", s.sent == [] and s.mem("BGST") == 3 and all(s.mem("TLOAD", off=i) == 1 for i in range(1, 5)))
# --- the table is full at END: the lists are still loaded (the newest were kept)
s = Sim(); s.mem("BGST", 1); s.mem("NCONT", 160); s.mem("SCBUSY", 1); s.mem("BGT", 5); s.mem("MAXCON", 160)
frame(s, 0, op=4); s.run("dispat")
check("table full at END: lists marked loaded all the same", all(s.mem("TLOAD", off=i) == 1 for i in range(1, 5)) and s.mem("BGST") == 3)
# --- timeout
s = Sim(); s.mem("BGST", 1); s.mem("SCBUSY", 1); s.mem("NCONT", 30); s.mem("BGT", 10)
s.m.mem[0xA1] = 40; s.run("bgtick")
check("not yet timed out", s.mem("BGST") == 1)
s.m.mem[0xA1] = 10 + 42; s.run("bgtick")
check("timed out: given up, link released, lists not marked", s.mem("BGST") == 3 and s.mem("SCBUSY") == 0 and all(s.mem("TLOAD", off=i) == 0 for i in range(5)))
# --- the guard
s = Sim(); s.mem("BGST", 1)
c = s.run("bgguard", a=2)
check("guard while running: carry set, panel shown", c.p & 1 and "plshow" in s.calls)
s = Sim(); s.mem("BGST", 4)
c = s.run("bgguard", a=2)
check("guard before it started: carry clear, A kept, background load switched off", not (c.p & 1) and c.a == 2 and s.mem("BGST") == 3)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
