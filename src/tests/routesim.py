#!/usr/bin/env python3
"""s38: DM flood fallback and wipe-route (meshcore64.py) in py65."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "."))
sys.path.insert(0, os.path.dirname(__file__))
from py65.devices.mpu6502 import MPU
import meshcore64, clksim_base as B
code, syms, prg, bit, half = meshcore64.build(13, "/tmp/purge2.prg", 0, meshcore64.PAL, 0, 125, 0)
E = meshcore64.EQU
bad = 0
def check(n, c):
    global bad
    bad += not c
    print("%-4s %s" % ("ok" if c else "FAIL", n))
def S(l): return syms[l]
KEY = bytes(range(0x40, 0x60))
def setup():
    m = B.M(meshcore64, code, syms, prg)
    m.mem[S("notice")] = 0x60
    m.mem[E["NCONT"]] = 2
    for slot, key in ((0, bytes(32)), (1, KEY)):
        m.mem[0xFB] = 0
        t = 0x0300
    return m
def frames_of(m, label):
    sent = []
    t = 0x0300
    m.mem[t:t + 3] = [0x20, S(label) & 255, S(label) >> 8]
    cpu = MPU(memory=m.mem); cpu.pc, cpu.sp = t, 0xFF
    n = 0
    while cpu.pc != t + 3:
        if cpu.pc == S("sendfr"):
            ln = m.mem[E["TXLEN"]]
            sent.append(bytes(m.mem[E["TXBUF"] + i] for i in range(ln)))
            cpu.pc = cpu.ByteAt(0x100 + cpu.sp + 1) | cpu.ByteAt(0x100 + cpu.sp + 2) << 8
            cpu.pc += 1; cpu.sp += 2
            continue
        cpu.step(); n += 1
        assert n < 500000
    return sent
def contact(m, i):
    t = 0x0300
    m.mem[t:t + 3] = [0x20, S("contptr") & 255, S("contptr") >> 8]
    cpu = MPU(memory=m.mem); cpu.pc, cpu.sp, cpu.a = t, 0xFF, i
    while cpu.pc != t + 3: cpu.step()
    return m.mem[0xFB] | m.mem[0xFC] << 8
def dm_pending(m, flood=0, age=3):
    for i in (0, 1):
        a = contact(m, i)
        for j in range(64): m.mem[a + j] = 0
        for j, b in enumerate(b"node%d" % i): m.mem[a + j] = b
        for j, b in enumerate(KEY if i == 1 else bytes([9] * 32)): m.mem[a + 26 + j] = b
        m.mem[a + 58] = 2; m.mem[a + 60] = 0x11; m.mem[a + 61] = 0x22
    for j, b in enumerate(b"hello there"): m.mem[E["INASC"] + j] = b
    for j in range(6): m.mem[E["DMKEY"] + j] = KEY[j]
    m.mem[S("PN_TL")] = 11
    m.call("dmsave")
    m.mem[S("PN_ST") + 1] = 1
    m.mem[S("DMFL")] = flood
    m.mem[0xA1] = 20
    m.mem[S("DMT")] = (20 - age) & 255
    m.mem[E["UIMODE"]] = 0
m = setup(); dm_pending(m)
sent = frames_of(m, "dmwd")
check("overdue direct DM: two frames (reset path, then the DM again)", len(sent) == 2)
check("CMD_RESET_PATH with the contact's full key", sent and sent[0] == bytes([13]) + KEY)
d = sent[1] if len(sent) > 1 else b""
check("DM again: attempt 1, same key prefix, same text", d[:3] == bytes([2, 0, 1]) and d[7:13] == KEY[:6] and d[13:] == b"hello there")
check("waits for the new ack tag; tried once", m.mem[S("PN_AW")] == 1 and m.mem[S("DMTRY")] == 1)
check("the C64's copy of the route forgotten", m.mem[contact(m, 1) + 58] == 255 and m.mem[contact(m, 0) + 58] == 2)
check("only once", frames_of(m, "dmwd") == [])
m = setup(); dm_pending(m, flood=1)
check("went by flood already: nothing", frames_of(m, "dmwd") == [])
m = setup(); dm_pending(m, age=1)
check("not overdue yet: nothing", frames_of(m, "dmwd") == [])
m = setup(); dm_pending(m); m.mem[S("PN_ST") + 1] = 2
check("acknowledged: nothing", frames_of(m, "dmwd") == [])
m = setup(); dm_pending(m); m.mem[E["UIMODE"]] = 1
check("menu open: waits", frames_of(m, "dmwd") == [])
# wipe route from the node menu
m = setup(); dm_pending(m)
for n in ("plshow", "mmshut"): m.mem[S(n)] = 0x60
m.mem[E["CIDX"]] = 1
sent = frames_of(m, "nawipe")
check("wipe route: reset sent, C64 copy forgotten, save queued", sent == [bytes([13]) + KEY] and m.mem[contact(m, 1) + 58] == 255 and m.mem[S("CDIRTY")] == 1)
# the radio's sent reply records direct / flood
m = setup(); dm_pending(m, flood=1)
m.mem[S("PN_AW")] = 1; m.mem[S("PN_AG") + 1] = 20; m.mem[0xA1] = 20
for i, b in enumerate([6, 0, 1, 2, 3, 4, 0, 0, 0, 0]): m.mem[E["BUF"] + i] = b
m.call("pnsent")
check("sent reply: went direct noted", m.mem[S("DMFL")] == 0 and m.mem[S("DMT")] == 20)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
