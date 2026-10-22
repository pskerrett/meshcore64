#!/usr/bin/env python3
"""Live dump (F1 > Live dump) in py65: packets in, the screen text out."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "."))
sys.path.insert(0, os.path.dirname(__file__))
import meshcore64 as mm, clksim_base as B
code, syms, prg, bit, half = mm.build(13, "/tmp/ld.prg", 0, mm.PAL, 0, 125, 0)
E = mm.EQU
bad = 0
SHOW = "-v" in sys.argv
def check(n, c, extra=""):
    global bad
    bad += not c
    print("%-4s %s" % ("ok" if c else "FAIL", n) + ("" if c else "\n     " + repr(extra)))
def A(l): return syms[l] if l in syms else E[l]

def machine(width=80):
    m = B.M(mm, code, syms, prg)
    for i, b in enumerate(mm.SEG8):          # segment 8, as main copies it
        m.mem[mm.S8ORG + i] = b
    m.mem[A("KWID")] = width
    m.mem[A("TSOK")] = 0
    return m

# contacts: name, key (32 bytes)
def key(first, n=32): return bytes(first) + bytes(range(100, 100 + n - len(first)))
NODES = [("Hilltop", key([0x4F, 0x21])), ("W9PDS-rpt", key([0x11, 0xD2])),
         ("KC9ABC", key([0x7F, 0x19, 0xC2, 0x01, 0x02, 0x03])), ("Twin A", key([0x55, 0x01])),
         ("Twin B", key([0x55, 0x02]))]
def contacts(m, nodes=NODES):
    m.mem[A("NCONT")] = len(nodes)
    for i, (nm, k) in enumerate(nodes):
        m.call("contptr", a=i)
        p = m.mem[A("PTR")] | m.mem[A("PTR") + 1] << 8
        rec = nm.encode()[:25].ljust(26, b"\0") + k + bytes(6)
        for j, b in enumerate(rec): m.mem[p + j] = b
def channel(m, idx, name):                    # CHNAM is PETSCII
    pet = bytes(c - 32 if 97 <= c <= 122 else c + 128 if 65 <= c <= 90 else c for c in name.encode())
    for j, b in enumerate(pet.ljust(18, b"\0")): m.mem[A("CHNAM") + 18 * idx + j] = b

def frame(m, bs):
    for i, b in enumerate(bs): m.mem[A("BUF") + i] = b
    m.mem[A("FLEN")] = len(bs)
def screen(m):
    out, p = [], A("LDBUF")
    while m.mem[p]:
        c = m.mem[p]; p += 1
        if c == 13: out.append("\n")
        elif 65 <= c <= 90: out.append(chr(c + 32))
        elif 193 <= c <= 218: out.append(chr(c - 128))
        elif 32 <= c < 64 or 91 <= c <= 95: out.append(chr(c))
        # colours and other controls take no column
    return "".join(out)
def pkt(m, raw, snr4=26, rssi=-97, flat=True, dup=False):
    if not dup:                                   # unrelated tests: forget earlier packets
        for i in range(8): m.mem[A("DRC") + i] = 0
    frame(m, bytes([0x88, snr4 & 255, rssi & 255]) + raw)
    m.call("ldpkt")
    s = screen(m)
    if SHOW: print(s, end="")
    return s.replace("\n  ", " ") if flat else s   # wrapped fields, read as one line
def msg(m, bs):
    frame(m, bs)
    m.call("ldtxt")
    s = screen(m)
    if SHOW: print(s, end="")
    return s

def hdr(route, ptype): return bytes([route | ptype << 2])
def plen(hops, size=1): return bytes([hops | (size - 1) << 6])

m = machine(80)
contacts(m)
channel(m, 0, "Public")
# a channel message, flood, 3 hops: Hilltop, an unknown repeater, W9PDS-rpt
grp = hdr(1, 5) + plen(3) + bytes([0x4F, 0x9C, 0x11]) + bytes([0xA3, 0x12, 0x34]) + bytes(range(32))
s = pkt(m, grp, snr4=-10, rssi=-112)
check("channel msg in words", s.startswith("--:--:-- Channel msg flood, 3 hops -112 dBm SNR -2.5 40 bytes channel A3"), s)
check("path by name, unknown as hex", "via Hilltop > 9C > W9PDS-rpt" in s, s)
s = msg(m, bytes([17, 26, 0, 0, 0, 3, 0, 1, 2, 3, 4]) + b"KC9ABC: hello there")
check("decrypted channel text", s == "  [Public] KC9ABC: hello there\n", s)
# SNR decimals: .0 .25 .5 .75
for q, t in ((24, "SNR 6.0"), (25, "SNR 6.3"), (26, "SNR 6.5"), (27, "SNR 6.8")):
    s = pkt(m, grp, snr4=q)
    check("SNR %d/4 -> %s" % (q, t), t + " " in s, s)
s = pkt(m, hdr(1, 5) + plen(1) + bytes([0x11]) + bytes([0xA3]) + bytes(20))
check("one hop", "flood, 1 hop " in s, s)
# advert, zero hop: repeater "W9PDS-rpt"
adv = hdr(1, 4) + plen(0) + key([0x3A, 0x7F, 0x19, 0xC2]) + bytes(4) + bytes(64) + bytes([0x82]) + b"W9PDS-rpt"
s = pkt(m, adv)
check("advert: kind, name, key", "Advert flood, 0 hops" in s and 'repeater "W9PDS-rpt" key 3A7F19C2' in s, s)
# a DM, direct, the route ahead through Hilltop: to KC9ABC from W9PDS-rpt
dm = hdr(2, 2) + plen(1) + bytes([0x4F]) + bytes([0x7F, 0x11]) + bytes(18)
s = pkt(m, dm)
check("DM: to/from by name, direct", "DM direct" in s and "to KC9ABC from W9PDS-rpt via Hilltop" in s, s)
# two nodes share the hash: the bytes, not a guess
s = pkt(m, hdr(2, 2) + plen(0) + bytes([0x55, 0x99]) + bytes(18))
check("ambiguous hash stays hex", "to 55 from 99" in s, s)
s = msg(m, bytes([16, 26, 0, 0, 0x7F, 0x19, 0xC2, 0x01, 0x02, 0x03, 2, 0, 1, 2, 3, 4]) + b"see you at 6")
check("decrypted DM", s == "  DM from KC9ABC: see you at 6\n", s)
s = msg(m, bytes([16, 26, 0, 0, 1, 1, 1, 1, 1, 1, 2, 0, 1, 2, 3, 4]) + b"hi")
check("DM from an unknown node: its key prefix", s == "  DM from 010101010101: hi\n", s)
s = pkt(m, hdr(1, 3) + plen(2) + bytes([0x4F, 0x11]) + bytes([0xDE, 0xAD, 0xBE, 0xEF]))
check("ack", "Ack flood, 2 hops" in s and "ack code DEADBEEF via Hilltop > W9PDS-rpt" in s, s)
# 2-byte path hashes
s = pkt(m, hdr(1, 5) + plen(2, 2) + bytes([0x4F, 0x21, 0x9C, 0x0E]) + bytes([0xA3]) + bytes(20))
check("2-byte path hashes", "via Hilltop > 9C0E" in s, s)
# transport flood: region code before the path length
s = pkt(m, hdr(0, 5) + bytes([0x34, 0x12, 0, 0]) + plen(0) + bytes([0xA3]) + bytes(20))
check("region code", "region 1234" in s, s)
# P on: the encrypted payload as hex only; an advert's still has its text
m.mem[A("LDHEX")] = 1
s = pkt(m, grp, flat=False)
check("encrypted payload: labelled, no text column", "encrypted:" in s and "A3 12 34 00" in s and "..." not in s, s)
s = pkt(m, adv, flat=False)
check("advert payload keeps its text column", "...defghijklmno" in s, s)
m.mem[A("LDHEX")] = 0
# T: all shown to start; choose types to hide with 1-5, any other key done
def press(m, k):
    m.call("ldkey", y=k)
    s = screen(m)
    if SHOW: print(s, end="")
    return s
mt = machine(80); contacts(mt); channel(mt, 0, "Public")
mt.call("ldini")
check("every type shown on entry", mt.mem[A("LDHID")] == 0)
s = press(mt, 84)                                # T
check("T lists the types, all on", "1 adverts:on 2 channel:on 3 direct:on 4 acks:on 5 other:on" in s, s)
check("T: packets wait while choosing", pkt(mt, grp) == "" and mt.mem[A("LDSKP")] == 1)
s = press(mt, 50)                                # 2: channel off
check("2 hides channel", "2 channel:off" in s and "1 adverts:on" in s, s)
s = press(mt, 51)                                # 3: direct off
check("3 hides direct too", "2 channel:off 3 direct:off" in s, s)
s = press(mt, 13)                                # RETURN: done
check("done: running again, skipped counted", "running, skipped 1" in s, s)
check("hidden: channel packets", pkt(mt, grp) == "")
check("hidden: channel text", msg(mt, bytes([17, 26, 0, 0, 0, 3, 0, 1, 2, 3, 4]) + b"a: b") == "")
check("hidden: DMs and their text", pkt(mt, dm) == "" and msg(mt, bytes([16, 26, 0, 0, 0x7F, 0x19, 0xC2, 1, 2, 3, 0, 0, 1, 2, 3, 4]) + b"x") == "")
check("still shown: adverts", pkt(mt, adv).startswith("--:--:-- Advert"))
press(mt, 84); press(mt, 50); press(mt, 32)          # T, 2 back on, SPACE done
check("2 again shows channel", pkt(mt, grp).startswith("--:--:-- Channel msg"))
check("F1 while choosing only ends choosing", (press(mt, 84), press(mt, 133), mt.mem[A("LDEXIT")])[2] == 0 and mt.mem[A("LDCHO")] == 0)
mt.call("ldini")
check("hidden types reset on the next visit", mt.mem[A("LDHID")] == 0)
# paused: counted, not shown
m.mem[A("LDPAU")] = 1; m.mem[A("LDSKP")] = 0
check("paused: skipped", msg(m, bytes([17, 26, 0, 0, 0, 3, 0, 1, 2, 3, 4]) + b"a: b") == "" and m.mem[A("LDSKP")] == 1)
m.mem[A("LDPAU")] = 0
# a long path: twelve hops, every one named (the limit is 14 hashes)
m12 = machine(80)
contacts(m12, [("Rpt%02d" % i, key([0xA0 + i, 0x01])) for i in range(16)])
s = pkt(m12, hdr(1, 5) + plen(12) + bytes(0xA0 + i for i in range(12)) + bytes([0xA3]) + bytes(20))
check("12 hops, all named", "via " + " > ".join("Rpt%02d" % i for i in range(12)) in s, s)
s = pkt(m12, hdr(1, 5) + plen(16) + bytes(0xA0 + i for i in range(16)) + bytes([0xA3]) + bytes(20))
check("past 14 hashes: hex", "Rpt13 > AE > AF" in s, s)
# a node past slot 138 (the table's second block, at $8000)
mb = machine(80)
mb.mem[A("CBASEH")] = 64                     # with an REU: slots 0-137 at $4000 (s2init)
contacts(mb, [("Filler%d" % i, key([i, 0xEE])) for i in range(200)] + [("FarNode", key([0xF7, 0x01]))])
s = pkt(mb, hdr(1, 5) + plen(2) + bytes([0xF7, 0x05]) + bytes([0xA3]) + bytes(20))
check("a node in the second block is found", "via FarNode > Filler5" in s, s)
# 40 columns: fields move to a new line whole, indented two
m40 = machine(40); contacts(m40); channel(m40, 0, "Public")
s = pkt(m40, grp, snr4=-10, rssi=-112, flat=False)
check("40 columns: no line longer than 39", all(len(l) <= 39 for l in s.split("\n")), s)
check("40 columns: words not split", "Channel msg" in s and "-112 dBm" in s and "W9PDS-rpt" in s, s)
check("40 columns: via stays with its name", "via Hilltop" in s, s)
s = msg(m40, bytes([17, 26, 0, 0, 0, 3, 0, 1, 2, 3, 4]) + b"KC9ABC: a much longer message that will need to wrap")
check("40 columns: long text wraps", all(len(l) <= 39 for l in s.split("\n")) and s.count("\n") >= 2, s)
# ---- P: hex off whenever the dump opens ----
mh = machine(80); mh.mem[A("LDHEX")] = 1; mh.mem[A("LDEXIT")] = 1; mh.mem[A("LDSKP")] = 9; mh.call("ldini")
check("payload hex is off on entry", mh.mem[A("LDHEX")] == 0)
check("entry: not leaving, nothing skipped", mh.mem[A("LDEXIT")] == 0 and mh.mem[A("LDSKP")] == 0)

# ---- the same packet heard again within ten seconds: one short line ----
md = machine(80); contacts(md); channel(md, 0, "Public"); md.call("ldini")
def jiffy(m, t): m.mem[0xA1], m.mem[0xA2] = (t >> 8) & 255, t & 255
jiffy(md, 1000)
body = bytes([0xA3, 0x12, 0x34]) + bytes(range(32))
s = pkt(md, hdr(1, 5) + plen(3) + bytes([0x4F, 0x9C, 0x11]) + body, dup=True)
check("first time: the full block", s.startswith("--:--:-- Channel msg flood, 3 hops"), s)
jiffy(md, 1100)
s = pkt(md, hdr(1, 5) + plen(4) + bytes([0x4F, 0x9C, 0x11, 0x4F]) + body, rssi=-52, dup=True)
check("again, through another repeater: one line", s == "  heard x2 via Hilltop -52 dBm\n", s)
jiffy(md, 1500)
s = pkt(md, hdr(1, 5) + plen(5) + bytes([0x4F, 0x9C, 0x11, 0x4F, 0x11]) + body, dup=True)
check("and again: x3, via the newest hop", s == "  heard x3 via W9PDS-rpt -97 dBm\n", s)
s = pkt(md, hdr(1, 5) + plen(3) + bytes([0x4F, 0x9C, 0x11]) + bytes([0xA3, 0x12, 0x35]) + bytes(range(32)), dup=True)
check("a different payload is a new packet", s.startswith("--:--:-- Channel msg"), s)
s = pkt(md, hdr(2, 2) + plen(0) + bytes([0x7F, 0x11]) + bytes(18), dup=True)
s2 = pkt(md, hdr(2, 2) + plen(0) + bytes([0x7F, 0x11]) + bytes(18), dup=True)
check("a direct repeat: no via", s2 == "  heard x2 -97 dBm\n", s2)
jiffy(md, 1500 + 601)
s = pkt(md, hdr(1, 5) + plen(3) + bytes([0x4F, 0x9C, 0x11]) + body, dup=True)
check("ten seconds on: the full block again", s.startswith("--:--:-- Channel msg"), s)
jiffy(md, 0x10010)                                 # the jiffy clock's low 16 bits wrap
pkt(md, hdr(1, 5) + plen(0) + bytes([0xA3, 9, 9]) + bytes(16), dup=True)
jiffy(md, 0x10020 + 65536 - 0x10010 - 0x10)        # 16 jiffies later, across the wrap
jiffy(md, (0x10010 + 16) & 0xFFFF)
s = pkt(md, hdr(1, 5) + plen(0) + bytes([0xA3, 9, 9]) + bytes(16), dup=True)
check("repeat across the jiffy wrap", s.startswith("  heard x2"), s)

# ---- channel hashes: the secret kept at the scan, hashed on the first visit ----
import hashlib
SEC = {0: bytes.fromhex("8b3387e9c5cdea6ac9e5edbaa115cd72"),   # Public's well-known key
       1: hashlib.sha256(b"#bot").digest()[:16]}
HASH = {k: hashlib.sha256(v).digest()[0] for k, v in SEC.items()}
check("#bot's hash byte is CA (as seen on the air)", HASH[1] == 0xCA)
class Geo:                                          # GeoRAM: a 256-byte window, page / block selects
    def __init__(self, m):
        self.pg = self.bk = 0; self.mem = {}
        m.mem.subscribe_to_write([0xDFFE], lambda a, v: setattr(self, "pg", v))
        m.mem.subscribe_to_write([0xDFFF], lambda a, v: setattr(self, "bk", v))
        m.mem.subscribe_to_write(range(0xDE00, 0xDF00), self.wr)
        m.mem.subscribe_to_read(range(0xDE00, 0xDF00), self.rd)
    def wr(self, a, v): self.mem[(self.bk, self.pg, a - 0xDE00)] = v
    def rd(self, a): return self.mem.get((self.bk, self.pg, a - 0xDE00), 0)
def scan(m, idx, name):                             # CHANNEL_INFO through the real handler
    channel(m, idx, name)
    frame(m, bytes([18, idx]) + name.encode().ljust(32, b"\0") + SEC[idx])
    m.call("chsv")
for ru, label in ((0, "main RAM"), (2, "GeoRAM")):
    mc = machine(80); contacts(mc)
    mc.mem[A("RU")] = ru
    geo = Geo(mc) if ru == 2 else None
    scan(mc, 0, "Public"); scan(mc, 1, "#bot")
    for slot in range(2, 40):                        # the rest of the scan: empty slots, zero keys
        SEC[slot] = bytes(16)
        frame(mc, bytes([18, slot]) + bytes(32) + SEC[slot]); mc.call("chsv")
    if ru == 2:
        kept = bytes(geo.mem.get((0, 5, 16 + i), 0) for i in range(16))
        check("GeoRAM: #bot's secret in block 0 page 5 (after the names)", kept == SEC[1], kept.hex())
        kept33 = bytes(geo.mem.get((0, 7, 16 + i), 0) for i in range(16))
        check("GeoRAM: slot 33 has its own place (page 7), not slot 1's", kept33 == bytes(16) and kept == SEC[1])
        check("GeoRAM: main RAM's table untouched", all(mc.mem[A("CHSECR") + 16 + i] == 0 for i in range(16)))
    else:
        check("main RAM: #bot's secret at CHSECR + 16", bytes(mc.mem[A("CHSECR") + 16 + i] for i in range(16)) == SEC[1])
    mc.call("ldini")
    check(label + ": hashes wanted on entry", mc.mem[A("LDHMORE")] == 1)
    for i in range(16): mc.mem[A("SECBUF") + i] = 0x50 + i
    s1 = (mc.call("ldhsh"), screen(mc))[1]
    s2 = (mc.call("ldhsh"), screen(mc))[1]
    s3 = (mc.call("ldhsh"), screen(mc))[1]
    check(label + ": one channel a pass, named", s1 == "-- [Public] is channel %02X --\n" % HASH[0] and s2 == "-- [#bot] is channel CA --\n", (s1, s2))
    check(label + ": then done", s3 == "" and mc.mem[A("LDHMORE")] == 0, s3)
    check(label + ": hashes kept", mc.mem[A("CHHASH") + 1] == 0xCA and mc.mem[A("CHHASH")] == HASH[0])
    check(label + ": SECBUF left as it was", all(mc.mem[A("SECBUF") + i] == 0x50 + i for i in range(16)))
# packets by channel name, and C
s = pkt(mc, hdr(1, 5) + plen(0) + bytes([0xCA, 1, 2]) + bytes(32))
check("a #bot packet says [#bot]", "Channel msg flood, 0 hops" in s and "[#bot]" in s and "channel CA" not in s, s)
s = pkt(mc, hdr(1, 5) + plen(0) + bytes([0x77, 1, 2]) + bytes(32))
check("an unknown channel keeps its hash", "channel 77" in s, s)
def cpress(m):
    m.call("ldkey", y=67); return screen(m)
check("C: only the first channel", cpress(mc) == "-- channels: only [Public] --\n")
check("only Public: #bot packets hidden", pkt(mc, hdr(1, 5) + plen(0) + bytes([0xCA, 1, 2]) + bytes(32)) == "")
check("only Public: Public packets shown", "[Public]" in pkt(mc, hdr(1, 5) + plen(0) + bytes([HASH[0], 1, 2]) + bytes(32)))
check("only Public: other types still shown", pkt(mc, adv).startswith("--:--:-- Advert"))
check("C again: only #bot", cpress(mc) == "-- channels: only [#bot] --\n")
check("only #bot: Public's text hidden", msg(mc, bytes([17, 26, 0, 0, 0, 3, 0, 1, 2, 3, 4]) + b"a: b") == "")
check("only #bot: #bot's text shown", msg(mc, bytes([17, 26, 0, 0, 1, 3, 0, 1, 2, 3, 4]) + b"bot: hi") == "  [#bot] bot: hi\n")
check("only #bot: unknown channels hidden", pkt(mc, hdr(1, 5) + plen(0) + bytes([0x77, 1, 2]) + bytes(32)) == "")
check("C again: all", cpress(mc) == "-- channels: all --\n" and mc.mem[A("LDCSEL")] == 255)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
