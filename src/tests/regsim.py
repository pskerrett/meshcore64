#!/usr/bin/env python3
"""v2.1: history regions handed out on demand to channels and DM conversations (meshcore64) in py65."""
import sys, os, importlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "."))
sys.path.insert(0, os.path.dirname(__file__))
mod = importlib.import_module(sys.argv[1] if len(sys.argv) > 1 else "meshcore64")
import clksim_base as B
code, syms, prg, bit, half = mod.build(13, "/tmp/reg21.prg", 0, mod.PAL, 0, 125, 0)
E = mod.EQU
bad = 0
def check(name, cond, info=""):
    global bad
    bad += not cond
    print("%-4s %s %s" % ("ok" if cond else "FAIL", name, info))
def A(n): return syms[n] if n in syms else E[n]
m = B.M(mod, code, syms, prg)
def reg(ch, write=True, ru=1):
    m.mem[A("RU")] = ru
    m.call("lregw" if write else "lreg", a=ch)
    return m.mem[A("REGION")]
def creg(ch): return m.mem[A("CREG") + ch]
check("segment 7 is loaded in the cassette buffer", A("lregw") >= 0x0340 and A("LRCH") < 0x0400)
check("no expansion: everything is the merged region 8", reg(3, ru=0) == 8 and reg(41, False, ru=0) == 8)
check("All is region 8", reg(255) == 8 and reg(255, False) == 8)
check("a channel never written to reads as the empty region 9", reg(12, False) == 9 and m.mem[A("LFL") + 9] == 0 and m.mem[A("LFH") + 9] == 0)
r12 = reg(12); r7 = reg(7); r0 = reg(0); r41 = reg(41)
check("channels 12, 7, 0 and DM 41 each get their own region", len({r12, r7, r0, r41}) == 4 and max(r12, r7, r0, r41) < 8, (r12, r7, r0, r41))
check("and keep it", reg(12) == r12 and reg(7, False) == r7 and reg(41, False) == r41)
check("the table points back", m.mem[A("ROWN") + r12] == 13 and creg(12) == r12 + 1)
# fill the rest; give each region some history
for ch in (20, 21, 22, 42):
    reg(ch)
for r in range(8):
    m.mem[A("LFL") + r] = 50 + r; m.mem[A("LWL") + r] = 50 + r
check("eight regions taken", all(m.mem[A("ROWN") + r] for r in range(8)))
# 0 and 12 stay busy; channel 7 is the quietest
for _ in range(5):
    reg(0); reg(12); reg(20); reg(21); reg(22); reg(41); reg(42)
r30 = reg(30)
check("a ninth channel takes the region written to longest ago (channel 7's)", r30 == r7, (r30, r7))
check("...wiped: no history from channel 7 shows in channel 30", m.mem[A("LFL") + r30] == 0 and m.mem[A("LWL") + r30] == 0 and m.mem[A("LFH") + r30] == 0)
check("...and channel 7 now reads as empty", reg(7, False) == 9 and creg(7) == 0)
check("busy channels keep theirs", reg(0, False) == r0 and reg(12, False) == r12 and m.mem[A("LFL") + r0] == 50 + r0)
# a session saved by v2.0.2: channels 0-5 kept, the shared 6 and 7 wiped
for i in range(64): m.mem[A("CREG") + i] = (i * 37 + 11) & 255     # junk where the table goes
for r in range(8):
    m.mem[A("ROWN") + r] = 0; m.mem[A("LFL") + r] = 40 + r; m.mem[A("LWL") + r] = 40 + r
m.mem[A("NFMT")] = 0xB1; m.mem[A("DMMK")] = 0xD7; m.mem[A("RU")] = 1
m.call("dmfix")
check("dmfix only marks it; the names (and the junk) are restored after it", m.mem[A("LRMF")] == 1)
m.call("lrfix")
check("lrfix runs once", m.mem[A("LRMF")] == 0)
check("old session: channels 0-5 keep regions 0-5", all(creg(i) == i + 1 and m.mem[A("ROWN") + i] == i + 1 for i in range(6)) and m.mem[A("LFL") + 3] == 43)
check("old session: regions 6 and 7 (the mixes) wiped and free", all(m.mem[A("LFL") + r] == 0 and m.mem[A("LWL") + r] == 0 and m.mem[A("ROWN") + r] == 0 for r in (6, 7)))
check("old session: channel 9 and DMs start empty", reg(9, False) == 9 and reg(40, False) == 9)
m.mem[A("CREG") + 20] = 8; m.call("lrfix")
check("a current session's table is left alone", creg(20) == 8 and m.mem[A("ROWN") + 7] == 21)
check("the region table is saved with the channel names (928 bytes from $C400)", A("CREG") == 0xC760 and A("RAGE") + 8 <= 0xC400 + 928)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
