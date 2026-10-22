#!/usr/bin/env python3
"""s39: Radio actions > Purge old nodes (meshcore64.py) in py65."""
import sys, os, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "."))
sys.path.insert(0, os.path.dirname(__file__))
from py65.devices.mpu6502 import MPU
import meshcore64, clksim_base as B
code, syms, prg, bit, half = meshcore64.build(13, "/tmp/purge.prg", 0, meshcore64.PAL, 0, 125, 0)
E = meshcore64.EQU
bad = 0
def check(n, c):
    global bad
    bad += not c
    print("%-4s %s" % ("ok" if c else "FAIL", n))
def A(l): return syms[l] if l in syms else E[l]
NOW = 1_800_000_000
DAY = 86400
def contact(key, adv, mod, fav=0, flen=148):
    f = bytearray(148)
    f[0] = 3; f[1:33] = key; f[33] = 2; f[34] = fav
    f[100:104] = b"node"
    f[132:136] = struct.pack("<I", adv); f[144:148] = struct.pack("<I", mod)
    return bytes(f[:flen])
def run(days_text, contacts, replies, tsok=1, maxcon=160):
    m = B.M(meshcore64, code, syms, prg)
    for n in ("inpget", "mmshut", "k80c", "gsvk", "sync", "dispat", "plshow", "poll"):
        m.mem[A(n)] = 0x60
    m.mem[0xFFD2] = 0x60
    m.mem[A("CBASEH")] = 0x40; m.mem[A("MAXCON")] = maxcon
    m.mem[A("TSOK")] = tsok
    for i in range(4): m.mem[A("NOWTS") + i] = (NOW >> (8 * i)) & 255
    m.mem[A("INPOK")] = 1; m.mem[A("INPLEN")] = len(days_text)
    for i, c in enumerate(days_text.encode()): m.mem[A("INPASC") + i] = c
    m.mem[A("NCONT")] = 50
    sent, queue, rq = [], [], list(replies)
    t = 0x0300
    m.mem[t:t + 3] = [0x20, A("purge4") & 255, A("purge4") >> 8]
    cpu = MPU(memory=m.mem); cpu.pc, cpu.sp = t, 0xFF
    def ret():
        cpu.pc = (cpu.ByteAt(0x100 + cpu.sp + 1) | cpu.ByteAt(0x100 + cpu.sp + 2) << 8) + 1
        cpu.sp += 2
    n = 0
    while cpu.pc != t + 3:
        if cpu.pc == A("sendfr"):
            f = bytes(m.mem[A("TXBUF") + i] for i in range(m.mem[A("TXLEN")]))
            sent.append(f)
            if f[0] == 4: queue[:] = [bytes([2, 0, 0, 0, 0])] + contacts + [bytes([4, 0, 0, 0, 0])]
            elif f[0] == 15: queue[:] = rq.pop(0)
            ret(); continue
        if cpu.pc == A("pgw"):
            if queue:
                f = queue.pop(0)
                for i, b in enumerate(f): m.mem[A("BUF") + i] = b
                m.mem[A("FLEN")] = len(f); m.mem[A("READY")] = 1
                cpu.p &= ~1
            else:
                cpu.p |= 1               # 13 s of silence
            ret(); continue
        cpu.step(); n += 1
        assert n < 5000000, "hung"
    lines = []
    for i in range(m.mem[A("PLN")]):
        lines.append(B.petscii(bytes(m.mem[A("PLBUF") + 32 * i + j] for j in range(32))).split("\0")[0].rstrip().lower())
    return m, sent, lines
K = [bytes([0x10 * k + j for j in range(32)]) for k in range(9)]
old, new, cut = NOW - 60 * DAY, NOW - 2 * DAY, NOW - 30 * DAY
cs = [contact(K[0], old, old),            # A old -> removed
      contact(K[1], old, new),            # B lastmod recent -> kept
      contact(K[2], old, old, fav=1),     # C favourite -> kept
      contact(K[3], new, old),            # D advert recent -> kept
      contact(K[4], old, old),            # E old -> radio says ERR
      contact(K[5], old, old),            # F old -> no answer
      contact(K[6], cut, cut),            # G exactly at the cutoff -> kept
      contact(K[7], old, old, flen=100)]  # H short frame -> ignored
replies = [[bytes([0x88, 1, 2, 3]), bytes([0])], [bytes([1, 2])], []]
m, sent, lines = run("30", cs, replies)
check("first frame: CMD_GET_CONTACTS", sent[:1] == [bytes([4])])
check("three removals, A E F, full keys", sent[1:] == [bytes([15]) + K[0], bytes([15]) + K[4], bytes([15]) + K[5]])
check("counts: checked 8, old 3, removed 1", (m.mem[A("PGCH")], m.mem[A("PGN")], m.mem[A("PGRM")]) == (8, 3, 1))
check("days 30", m.mem[A("PGD")] == 30)
cutv = sum(m.mem[A("PGCUT") + i] << (8 * i) for i in range(4))
check("cutoff = now - 30 days", cutv == cut)
check("node table emptied, lists reload", m.mem[A("NCONT")] == 0 and all(m.mem[A("TLOAD") + i] == 0 for i in range(5)))
check("scan flag cleared", m.mem[A("SCBUSY")] == 0)
print("   panel:", lines)
check("panel lines", lines[:4] == ["checked   8", "removed   1 of 3", "older than 30 days", "favourites kept"])
m, sent, lines = run("0", cs, [])
check("0 days: nothing sent", sent == [])
m, sent, lines = run("", cs, [])
check("nothing typed: nothing sent", sent == [])
m, sent, lines = run("30", cs, [], tsok=0)
check("radio clock not known: nothing sent", sent == [])
m, sent, lines = run("1000", cs, [[bytes([0])]] * 8)
check("1000 days: parsed, nothing that old", m.mem[A("PGD")] + 256 * m.mem[A("PGD") + 1] == 1000 and sent == [bytes([4])])
m, sent, lines = run("12345", cs, [])
check("5 digits: first 4 used", m.mem[A("PGD")] + 256 * m.mem[A("PGD") + 1] == 1234)
m, sent, lines = run("7x", cs, [[bytes([0])]] * 8)
check("'7x' = 7 days", m.mem[A("PGD")] == 7)
many = [contact(bytes([k] * 32), old, old) for k in range(1, 30)]
m, sent, lines = run("30", many, [[bytes([0])]] * 40, maxcon=10)
check("key store capped at MAXCON*2 = 20", m.mem[A("PGN")] == 20 and len(sent) == 21 and m.mem[A("PGCH")] == 29)
check("removals keep their keys", sent[1] == bytes([15]) + bytes([1] * 32) and sent[20] == bytes([15]) + bytes([20] * 32))
print("FAILURES:", bad); sys.exit(1 if bad else 0)
