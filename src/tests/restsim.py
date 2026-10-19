#!/usr/bin/env python3
"""v2.1: the history-region table across restarts ("restored, but no history"), through a GeoRAM and an REU (meshcore64) in py65."""
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
    m.mem[A("CBASEH")] = cbase; m.mem[A("MAXCON")] = 234
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
def call(m, label, a=0):
    t = 0x0300; m.mem[t:t + 3] = [0x20, A(label) & 255, A(label) >> 8]
    c = MPU(memory=m.mem); c.pc, c.sp, c.a = t, 0xFF, a
    n = 0
    while c.pc != t + 3:
        c.step(); n += 1
        assert n < 40000000, label + " hung"
    return m.mem[A("REGION")]
def creg(m): return [m.mem[A("CREG") + i] for i in range(48)]
def lf(m, r): return m.mem[A("LFL") + r] | m.mem[A("LFH") + r] << 8
for kind in ("geo", "reu"):
    store = GeoRAM() if kind == "geo" else REU()
    new = lambda: machine(kind, store)
    # 1. a v2.0.2 session: no table (junk where it goes), history in regions 0-7
    m1 = new()
    for i, n in enumerate((b"Public", b"#test")): m1.mem[A("CHNAM") + 18 * i: A("CHNAM") + 18 * i + len(n)] = list(n)
    for r, n in enumerate((30, 0, 0, 10, 0, 0, 20, 5)):
        m1.mem[A("LFL") + r] = n; m1.mem[A("LWL") + r] = n
    for i in range(64): m1.mem[A("CREG") + i] = (i * 37 + 11) & 255
    m1.mem[A("NFMT")] = 0xB1; m1.mem[A("DMMK")] = 0xD7
    call(m1, "gsvc")
    m2 = new(); call(m2, "georest")
    check("%s: old session restored, channels 0-5 keep regions 0-5" % kind, m2.mem[A("GREST")] == 1 and creg(m2)[:6] == [1, 2, 3, 4, 5, 6] and all(v == 0 for v in creg(m2)[6:]), creg(m2)[:8])
    check("%s: Public's 30 lines; the mixed regions 6, 7 start over" % kind, call(m2, "lreg", 0) == 0 and lf(m2, 0) == 30 and lf(m2, 6) == 0 and lf(m2, 7) == 0)
    # 2. the restart after that: the table was saved
    m3 = new(); call(m3, "georest")
    check("%s: second restart: table and Public's history still there" % kind, creg(m3)[:6] == [1, 2, 3, 4, 5, 6] and call(m3, "lreg", 0) == 0 and lf(m3, 0) == 30, creg(m3)[:8])
    # 3. a channel's first message during a session: its region survives a restart
    r9 = call(m3, "lregw", 9)
    m3.mem[A("LFL") + r9] = 4; m3.mem[A("LWL") + r9] = 4
    call(m3, "gsvh")
    m4 = new(); call(m4, "georest")
    check("%s: channel 9 keeps region %d and its 4 lines after a restart" % (kind, r9), 6 <= r9 < 8 and call(m4, "lreg", 9) == r9 and lf(m4, r9) == 4)
    check("%s: a DM conversation with no messages has none" % kind, call(m4, "lreg", 41) == 9)
    # 4. a session saved by a test build (v2.1a $B2, the first v2.1 copy $B3): its regions may hold
    #    any channel's lines, so every channel starts over; "All" (labelled lines) is kept
    for marker in (0xB2, 0xB3):
        m4.mem[A("NFMT")] = marker; m4.mem[A("LFL") + 8] = 77; m4.mem[A("LWL") + 8] = 77
        for r in range(8): m4.mem[A("LFL") + r] = 9; m4.mem[A("LWL") + r] = 9
        for i in range(48): m4.mem[A("CREG") + i] = 0
        m4.mem[A("CREG")] = 8; m4.mem[A("CREG") + 3] = 2
        call(m4, "gsvc")
        m5 = new(); call(m5, "georest")
        check("%s: test-build session ($%02X): every channel region wiped, the table empty, All kept" % (kind, marker),
              all(lf(m5, r) == 0 and m5.mem[A("LWL") + r] == 0 for r in range(8)) and all(v == 0 for v in creg(m5)) and lf(m5, 8) == 77 and m5.mem[A("NFMT")] == 0xB4)
        m6 = new(); call(m6, "georest")
        check("%s: ...and it stays that way after the next restart" % kind, all(v == 0 for v in creg(m6)) and lf(m6, 8) == 77 and all(lf(m6, r) == 0 for r in range(8)))
        m4 = m6
    for r, n in enumerate((30, 0, 0, 10, 0, 0, 20, 5)):
        m4.mem[A("LFL") + r] = n; m4.mem[A("LWL") + r] = n
    m5 = m4
    # 5. a current session whose table came back empty
    for i in range(48): m5.mem[A("CREG") + i] = 0
    call(m5, "gsvc")
    m6 = new(); call(m6, "georest")
    check("%s: an empty table in a current session stays empty (nothing guessed)" % kind, all(v == 0 for v in creg(m6)) and lf(m6, 0) == 30)
    m6.mem[A("CREG")] = 1
    # 6. bad entries dropped, the owners rebuilt
    m6.mem[A("CREG") + 20] = 12; m6.mem[A("CREG") + 21] = 1
    call(m6, "gsvc")
    m7 = new(); call(m7, "georest")
    check("%s: bad entries dropped, owners rebuilt" % kind, creg(m7)[20] == 0 and creg(m7)[21] == 0 and creg(m7)[0] == 1 and m7.mem[A("ROWN")] == 1)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
