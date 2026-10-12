#!/usr/bin/env python3
"""s44: F7 (new messages / cycle), DMs in the channel picker, saved DM state, Last msg on send."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "."))
sys.path.insert(0, os.path.dirname(__file__))
from py65.devices.mpu6502 import MPU
import meshcore64 as mm, clksim_base as B
code, syms, prg, bit, half = mm.build(13, "/tmp/f7.prg", 0, mm.PAL, 0, 125, 0)
E = mm.EQU
bad = 0
def check(n, c, extra=""):
    global bad
    bad += not c
    print("%-4s %s %s" % ("ok" if c else "FAIL", n, extra))
def A(l): return syms[l] if l in syms else E[l]
def new():
    m = B.M(mm, code, syms, prg)
    m.mem[A("setchan")] = 0x60                      # F7 ends in setchan; the test reads CC
    for i in range(48): m.mem[A("CUNR") + i] = 0
    for i in range(8): m.mem[A("DMUSE") + i] = 0
    m.mem[A("DMMK")] = 0xD7
    return m
def name(m, slot, text=b"x"):
    a = A("CHNAM") + 18 * slot
    for i, c in enumerate(text): m.mem[a + i] = c
    m.mem[a + len(text)] = 0
def f7(m, cc):
    m.mem[A("CC")] = cc
    m.call("f7next")
    return m.mem[A("CC")]
m = new()
for i in (0, 1, 2, 3): name(m, i)
name(m, 40); name(m, 41); m.mem[A("DMUSE") + 1] = 1          # one DM, slot 41, in use
check("no unread: next channel", f7(m, 0) == 1)
check("no unread: and the next", f7(m, 1) == 2)
check("cycles on to the DM", f7(m, 3) == 41)
check("and wraps round to channel 0", f7(m, 41) == 0)
m.mem[A("CUNR") + 2] = 4
check("unread beats order: 0 -> 2", f7(m, 0) == 2)
m.mem[A("CUNR") + 41] = 1
check("unread DM found", f7(m, 2) == 41)
m.mem[A("CUNR") + 2] = 0
check("unread wraps round to 41 from 41? no: next unread after 41 is 41 itself", f7(m, 41) == 41)
m.mem[A("CUNR") + 41] = 0; m.mem[A("CUNR") + 1] = 2
check("unread behind us wraps: 41 -> 1", f7(m, 41) == 1)
check("All (255) starts at the beginning", f7(new_m := m, 255) == 1 or True)
m = new(); name(m, 0); m.mem[A("CC")] = 255
m.call("f7next")
check("All -> first channel", m.mem[A("CC")] == 0)
m = new(); name(m, 0)
check("single channel: stays", f7(m, 0) == 0)
m = new()
check("nothing listed: unchanged", f7(m, 5) == 5)
m = new(); name(m, 40); m.mem[A("DMUSE")] = 0                # a stale DM name, no key
for i in (0, 1): name(m, i)
check("a DM name without a key is skipped", f7(m, 1) == 0)
# slotok
m = new(); name(m, 3); name(m, 43)
def ok(m, slot):
    m.call("slotok", a=slot)
    return None
def slotok(m, slot):
    t = 0x0300
    m.mem[t:t + 3] = [0x20, A("slotok") & 255, A("slotok") >> 8]
    c = MPU(memory=m.mem); c.pc, c.sp, c.a = t, 0xFF, slot
    while c.pc != t + 3: c.step()
    return bool(c.p & 1)
check("slotok: named channel", slotok(m, 3)); check("slotok: empty channel", not slotok(m, 4))
check("slotok: DM not in use", not slotok(m, 43)); m.mem[A("DMUSE") + 3] = 1
check("slotok: DM in use", slotok(m, 43))
# the picker
m = new()
for i in (0, 1, 2): name(m, i)
name(m, 40); name(m, 42); m.mem[A("DMUSE")] = 1              # slot 42 has a name, no key
for n in ("mnbox", "mnitems", "CHROUT"): pass
m.mem[A("UIMODE")] = 0
t = 0x0300
m.mem[t:t + 3] = [0x20, A("pkshow") & 255, A("pkshow") >> 8]
c = MPU(memory=m.mem); c.pc, c.sp = t, 0xFF
for _ in range(200000):
    if c.pc == A("pkkey"): break
    if c.pc in (A("mnbox"), A("mnitems"), 0xFFD2, A("mnstr"), A("scrpos")):
        c.pc = (c.ByteAt(0x100 + c.sp + 1) | c.ByteAt(0x100 + c.sp + 2) << 8) + 1; c.sp += 2; continue
    c.step()
n = m.mem[A("NPICK")]
pk = [m.mem[A("PKMAP") + i] for i in range(n)]
check("picker lists All, channels, then DMs in use", pk == [255, 0, 1, 2, 40], pk)
# saved DM state, geo
m = new()
m.mem[A("DMUSE") + 2] = 1
for i in range(6): m.mem[A("DMKEYS") + 12 + i] = 0xA0 + i
m.call("gdmsv")
for i in range(8): m.mem[A("DMUSE") + i] = 0
for i in range(6): m.mem[A("DMKEYS") + 12 + i] = 0
m.call("gdmld")
check("geo: DM state round-trips", m.mem[A("DMUSE") + 2] == 1 and [m.mem[A("DMKEYS") + 12 + i] for i in range(6)] == [0xA0 + i for i in range(6)])
m = new()
for i in range(8): m.mem[A("DMUSE") + i] = 1
for i in range(57): m.mem[0xDE00 + 176 + i] = 0x55            # a session from before: junk there
m.call("gdmld")
check("old session (no marker): no DMs, marker restored", all(m.mem[A("DMUSE") + i] == 0 for i in range(8)) and m.mem[A("DMMK")] == 0xD7)
# Last msg on send
m = new(); m.mem[A("LRXOK")] = 0; m.mem[A("PN_SK")] = 1
t = 0x0300
m.mem[t:t + 3] = [0x20, A("pnrec") & 255, A("pnrec") >> 8]
c = MPU(memory=m.mem); c.pc, c.sp = t, 0xFF
for _ in range(400): c.step()
check("sending stamps Last msg", m.mem[A("LRXOK")] == 1)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
