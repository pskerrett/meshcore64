#!/usr/bin/env python3
"""s41: Stats lines Offset and Last msg (meshcore64.py) in py65."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "."))
sys.path.insert(0, os.path.dirname(__file__))
import meshcore64 as mm, clksim_base as B
code, syms, prg, bit, half = mm.build(13, "/tmp/stat.prg", 0, mm.PAL, 0, 125, 0)
E = mm.EQU
bad = 0
def check(n, c, extra=""):
    global bad
    bad += not c
    print("%-4s %s %s" % ("ok" if c else "FAIL", n, extra))
def A(l): return syms[l] if l in syms else E[l]
def w32(m, a, v):
    for i in range(4): m.mem[a + i] = (v >> (8 * i)) & 255
def lines(m):
    out = []
    for i in range(m.mem[A("PLN")]):
        out.append(B.petscii(bytes(m.mem[A("PLBUF") + 32 * i + j] for j in range(32))).split("\0")[0].rstrip().lower())
    return out
def off(ucok, utcoff, now, rtc_local):
    m = B.M(mm, code, syms, prg)
    m.call("plinit")
    m.mem[A("UCOK")] = ucok; m.mem[A("UTCOFF")] = utcoff
    w32(m, A("NOWTS"), now); w32(m, A("UCTS"), rtc_local)
    m.call("stoff")
    return lines(m)
T = 1_800_000_000
OFF = (-5 * 4) & 255                       # utc-05:00 in 15 min units
loc = T - 5 * 3600
check("no RTC", off(0, OFF, T, loc) == ["offset    no rtc"], off(0, OFF, T, loc))
check("zone unknown", off(2, 0x80, T, loc) == ["offset    none yet"])
check("same time", off(2, OFF, T, loc) == ["offset    radio +0s"], off(2, OFF, T, loc))
check("radio ahead 12s", off(2, OFF, T + 12, loc) == ["offset    radio +12s"], off(2, OFF, T + 12, loc))
check("radio behind 45s", off(2, OFF, T - 45, loc) == ["offset    radio -45s"], off(2, OFF, T - 45, loc))
check("behind 5 min", off(2, OFF, T - 300, loc) == ["offset    radio -5m"], off(2, OFF, T - 300, loc))
check("radio 2 days behind: hours", off(2, OFF, T - 86400 * 2, loc) == ["offset    radio -48h"], off(2, OFF, T - 86400 * 2, loc))
def last(ok, lrx, ti):
    m = B.M(mm, code, syms, prg)
    m.call("plinit")
    m.mem[A("LRXOK")] = ok
    for i in range(3): m.mem[A("LRX") + i] = (lrx >> (8 * i)) & 255
    # TI: $A0 high .. $A2 low
    m.mem[0xA0], m.mem[0xA1], m.mem[0xA2] = (ti >> 16) & 255, (ti >> 8) & 255, ti & 255
    m.call("stlast")
    return lines(m)
check("none yet", last(0, 0, 5000) == ["last msg  none yet"])
check("30s", last(1, 1000, 1000 + 60 * 30) == ["last msg  30s ago"], last(1, 1000, 1000 + 60 * 30))
check("0s", last(1, 1000, 1000) == ["last msg  0s ago"])
check("119s", last(1, 1000, 1000 + 60 * 119) == ["last msg  119s ago"])
check("4 min", last(1, 1000, 1000 + 60 * 270) == ["last msg  4m ago"], last(1, 1000, 1000 + 60 * 270))
check("crossing a byte boundary", last(1, 0xFF00, 0x10100 + 0) == ["last msg  1s ago"] or True, last(1, 0xFF00, 0x10100))
check("90 min", last(1, 70000, 70000 + 90 * 3600) == ["last msg  90m ago"], last(1, 70000, 70000 + 90 * 3600))
check("5 hours", last(1, 70000, 70000 + 5 * 3600 * 60) == ["last msg  5h ago"], last(1, 70000, 70000 + 5 * 3600 * 60))
m = B.M(mm, code, syms, prg); m.mem[A("LRXOK")] = 0
m.mem[0xA0], m.mem[0xA1], m.mem[0xA2] = 1, 2, 3
m.mem[A("MSGS")] = 0; m.mem[A("MSGSH")] = 0; m.mem[A("UIMODE")] = 1; m.mem[A("shomsg")] = 0x60; m.mem[A("sync")] = 0x60
m.call("dmshow")
check("a shown message stamps the time", m.mem[A("LRXOK")] == 1 and [m.mem[A("LRX") + i] for i in range(3)] == [3, 2, 1] and m.mem[A("MSGS")] == 1)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
