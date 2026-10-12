#!/usr/bin/env python3
"""s23: node list filter routines (mlfind.py) in py65."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "."))
sys.path.insert(0, os.path.dirname(__file__))
import meshcore64 as mlfind, clksim_base as B
code, syms, prg, bit, half = mlfind.build(13, "/tmp/find.prg", 0, mlfind.PAL, 0, 125, 0)
E = mlfind.EQU
m = B.M(mlfind, code, syms, prg)
bad = 0


def check(name, cond):
    global bad
    bad += not cond
    print("%-4s %s" % ("ok" if cond else "FAIL", name))


def S(l): return syms[l]


def setname(n):
    base = E["PLBUF"] + 0x100          # any scratch RAM
    for i, b in enumerate(n.encode() + b"\0"): m.mem[base + i] = b
    m.mem[E["PTR"]] = base & 255; m.mem[E["PTR"] + 1] = base >> 8 if False else 0
    m.mem[0xFB] = base & 255; m.mem[0xFC] = base >> 8


def setfilter(t):
    for i, b in enumerate(t.encode()): m.mem[S("NFB") + i] = b
    m.mem[S("NFLEN")] = len(t); m.mem[S("NFTL")] = len(t)


def matches(name, filt):
    setname(name); setfilter(filt)
    m.mem[S("NTOT")] = 0
    # carry flag after the call: run and read processor status
    t = 0x0300
    m.mem[t:t + 3] = [0x20, S("nfmatch") & 255, S("nfmatch") >> 8]
    from py65.devices.mpu6502 import MPU
    cpu = MPU(memory=m.mem); cpu.pc, cpu.sp = t, 0xFF
    while cpu.pc != t + 3: cpu.step()
    return (cpu.p & 1) == 0, m.mem[S("NTOT")]


for name, f, want in [("Hilltop Relay", "hill", True), ("Hilltop Relay", "TOP", True),   # filter is stored lower case
                      ("hilltop-relay", "relay", True), ("hilltop-relay", "layer", False),
                      ("ORD-MPRVL-GRNVL-RPTR", "grnvl", True), ("Tower East", "east", True),
                      ("depot-node", "ode", True), ("depot-node", "depot-node", True),
                      ("depot-node", "depot-nodes", False), ("a", "ab", False), ("", "x", False),
                      ("Ghostrider Tophat", "r t", True), ("Ghostrider Tophat", "r tophatx", False),
                      ("Ghost rider", "t r", True)]:
    got, tot = matches(name, f.lower() if f != "TOP" else "top")
    ok = got == want and tot == 1
    bad += not ok
    print("%-4s %-22r filter %-14r keep=%s" % ("ok" if ok else "FAIL", name, f, got))
m.mem[S("NFLEN")] = 0
setname("anything"); m.mem[S("NTOT")] = 5
got, tot = matches("anything", "")
check("no filter keeps everything and counts it", got and tot == 1)

# hint line
def hint():
    m.call("nfhint")
    a = m.mem[E["SPL"]] | m.mem[E["SPH"]] << 8
    b = []
    while m.mem[a]: b.append(m.mem[a]); a += 1
    return "".join(chr(x) for x in b)
m.mem[S("NFLEN")] = 0; m.mem[S("NFMS")] = 0
check("hint, no filter", hint() == "RET pick / find  R refresh  F1 back")
setfilter("tower")
for a in (0xF7, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC): m.mem[a] = 0x40 + a - 0xF7
h0 = hint()
check("hint leaves every menu pointer alone", all(m.mem[a] == 0x40 + a - 0xF7 for a in (0xF7, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC)))
setfilter("tower")
check("hint, filter on", hint() == "Find: tower  / edit  F1 back")
m.mem[S("NFLEN")] = 0; m.mem[S("NFMS")] = 1
h = hint()
check("hint, no match", h == "No match: tower - all shown" and m.mem[S("NFMS")] == 0)
check("hint after that is the plain one", hint() == "RET pick / find  R refresh  F1 back")

# title: " repeaters (3/12) "
m.mem[S("NTYPE")] = 2
for nv, tot, flt, want in [(3, 12, 1, " repeaters (3/12) "), (12, 12, 0, " repeaters (12) "),
                           (1, 100, 1, " repeaters (1/100) "), (0, 7, 1, None)]:
    m.mem[S("NVIS")] = nv; m.mem[S("NTOT")] = tot; m.mem[S("NFLEN")] = flt
    m.call("ndtit")
    a = S("NTBUF"); b = []
    while m.mem[a]: b.append(m.mem[a]); a += 1
    got = "".join(chr(x + 32 if 65 <= x <= 90 else x) for x in b)
    if want: check("title %r" % want, got == want)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
