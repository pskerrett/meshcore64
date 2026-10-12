#!/usr/bin/env python3
"""s35: the node-fetch progress line (meshcore64.py) fits the screen width."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "."))
sys.path.insert(0, os.path.dirname(__file__))
from py65.devices.mpu6502 import MPU
import meshcore64, clksim_base as B
code, syms, prg, bit, half = meshcore64.build(13, "/tmp/ndl.prg", 0, meshcore64.PAL, 0, 125, 0)
E = meshcore64.EQU
bad = 0
def check(n, c):
    global bad
    bad += not c
    print("%-4s %s" % ("ok" if c else "FAIL", n))
for width in (39, 79):
    m = B.M(meshcore64, code, syms, prg)
    m.mem[0xFFD2] = 0x60
    m.mem[syms["KSEPW"]] = width
    m.mem[E["NCONT"]] = 98
    m.mem[E["MAXCON"]] = 120
    m.mem[syms["NSEEN"]] = 120; m.mem[syms["NSEENH"]] = 0
    m.mem[syms["NRECV"]] = 98; m.mem[syms["NTRUNC"]] = 0
    # the contact table base: whatever contptr uses
    t = 0x0300
    m.mem[t:t + 3] = [0x20, syms["contptr"] & 255, syms["contptr"] >> 8]
    cpu = MPU(memory=m.mem); cpu.pc, cpu.sp, cpu.a = t, 0xFF, 97
    while cpu.pc != t + 3: cpu.step()
    base = m.mem[0xFB] | m.mem[0xFC] << 8
    for i, c in enumerate(b"ORD-MPRVL-GRNVL-RPTR-NORT\0"): m.mem[base + i] = c
    out = []
    m.mem[t:t + 3] = [0x20, syms["ndline"] & 255, syms["ndline"] >> 8]
    cpu = MPU(memory=m.mem); cpu.pc, cpu.sp = t, 0xFF
    n = 0
    while cpu.pc != t + 3:
        if cpu.pc == 0xFFD2: out.append(cpu.a)
        cpu.step(); n += 1
        assert n < 500000
    line = bytes(c for c in out if c not in (145, 13))
    text = line.decode("latin1")
    print("   width %d: %r (%d)" % (width, text.rstrip(), len(line)))
    check("width %d: the line is exactly the screen width, then CR" % width, len(line) == width and out[-1] == 13 and out[0] == 145)
    if width == 39: check("40 columns: the name is cut at the edge", "ord-mprvl" in text.lower() and "nort" not in text.lower())
    else: check("80 columns: the whole name", "nort" in text.lower())
print("FAILURES:", bad); sys.exit(1 if bad else 0)
