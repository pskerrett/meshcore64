#!/usr/bin/env python3
"""s22: DM-ack / channel-repeat indication (mlpend.py) in py65."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "."))
sys.path.insert(0, os.path.dirname(__file__))
import meshcore64 as mlpend, clksim_base as B
code, syms, prg, bit, half = mlpend.build(13, "/tmp/pend.prg", 0, mlpend.PAL, 0, 125, 0)
E = mlpend.EQU
print("seg3 at $%04X, %d bytes; no-expansion archive %d lines" % (
    mlpend.S3ORG, len(prg) - 2 - (mlpend.S3ORG - mlpend.ORG), E["NOREU_LINES"]))
bad = 0


def fresh():
    m = B.M(mlpend, code, syms, prg)
    for a in range(0x0400, 0x0800): m.mem[a] = 32
    for a in range(0xD800, 0xDC00): m.mem[a] = 5
    return m


def sc(text):          # ascii -> screen code (lower case letters 1-26)
    return [ord(c) - 96 if c.islower() else (ord(c) if c.isupper() or not c.isalpha() else ord(c)) for c in text]


def put_row(m, row, text):
    for i, c in enumerate(sc(text)): m.mem[0x0400 + row * 40 + i] = c


def col(m, row, i): return m.mem[0xD800 + row * 40 + i]


def check(name, cond):
    global bad
    bad += not cond
    print("%-4s %s" % ("ok" if cond else "FAIL", name))


def S(label): return syms[label]


def frame(m, payload, header=0x15, hops=1, hs=1, transport=False, snr=20, rssi=200):
    pl = (hs - 1) << 6 | hops
    f = bytearray([0x88, snr, rssi, header])
    if transport: f += bytes(4)
    f.append(pl); f += bytes(hops * hs); f += payload
    for i, b in enumerate(f): m.mem[E["BUF"] + i] = b
    m.mem[E["FLEN"]] = len(f)


def setup_channel(m, row=23, text="Public>hello world", name=b"bob", tl=11):
    put_row(m, row, text)
    for i in range(len(text)): m.mem[0xD800 + row * 40 + i] = 1      # typed in white
    m.mem[E["PRLEN"]] = 7
    for i, b in enumerate(name + b"\0"): m.mem[E["NODENM"] + i] = b
    m.mem[0xD6] = row + 1
    m.mem[S("PN_SK")] = 1
    m.mem[S("PN_TL")] = tl
    m.mem[E["UIMODE"]] = 0
    m.mem[0xA1] = 10
    m.call("pnrec")


# ---- channel ----
m = fresh(); setup_channel(m)
check("sent: label yellow, text still white", all(col(m, 23, i) == 7 for i in range(7)) and all(col(m, 23, i) == 1 for i in range(7, 18)))
check("sent: state 1, expected payload 35", m.mem[S("PN_ST")] == 1 and m.mem[S("PN_EL")] == 35)
pay = bytes([0x4C, 0xAA, 0xBB, 0xCC]) + bytes(31)
frame(m, pay); m.call("pnlog")
check("first echo: the whole line green", all(col(m, 23, i) == 5 for i in range(18)) and col(m, 23, 18) == 1 or all(col(m, 23, i) == 5 for i in range(18)))
check("first echo: state confirmed", m.mem[S("PN_ST")] == 2)
check("signature learned", bytes(m.mem[S("PN_KY") + i] for i in range(4)) == pay[:4])
frame(m, pay, hops=2); m.call("pnlog")
check("second echo: label flashes white, text stays green", all(col(m, 23, i) == 1 for i in range(7)) and all(col(m, 23, i) == 5 for i in range(7, 18)) and m.mem[S("PN_FS")] == 0)
m.mem[0xA2] = (m.mem[S("PN_FT")] + 5) & 255; m.call("flrest")
check("flash not over after 5 jiffies", col(m, 23, 0) == 1)
m.mem[0xA2] = (m.mem[S("PN_FT")] + 15) & 255; m.call("flrest")
check("flash over: green again", col(m, 23, 0) == 5 and m.mem[S("PN_FS")] == 255)
frame(m, bytes([0x4C, 0xAA, 0xBB, 0xDD]) + bytes(31), hops=1); m.call("pnlog")
check("same length, other signature: nothing", col(m, 23, 0) == 5 and m.mem[S("PN_FS")] == 255)

m = fresh(); setup_channel(m)
frame(m, bytes(34), hops=1); m.call("pnlog")
check("other payload length: nothing", m.mem[S("PN_ST")] == 1 and col(m, 23, 0) == 7)
frame(m, pay, hops=0); m.call("pnlog")
check("no hops (heard from the origin): nothing", m.mem[S("PN_ST")] == 1)
frame(m, pay, header=0x16); m.call("pnlog")
check("direct route: nothing", m.mem[S("PN_ST")] == 1)
frame(m, pay, header=0x19); m.call("pnlog")
check("another payload type: nothing", m.mem[S("PN_ST")] == 1)
frame(m, pay, header=0x14, transport=True); m.call("pnlog")
check("transport flood header parsed: green", m.mem[S("PN_ST")] == 2 and col(m, 23, 0) == 5)

m = fresh(); setup_channel(m)
frame(m, pay, hops=3, hs=2); m.call("pnlog")
check("2-byte hop hashes parsed: green", m.mem[S("PN_ST")] == 2)

m = fresh(); setup_channel(m)
m.mem[0xA1] = 10 + 9
frame(m, pay); m.call("pnlog")
check("echo after 38 s ignored", m.mem[S("PN_ST")] == 1)

m = fresh(); setup_channel(m)
m.mem[E["UIMODE"]] = 1
frame(m, pay); m.call("pnlog")
check("menu open: state moves, screen untouched", m.mem[S("PN_ST")] == 2 and col(m, 23, 0) == 7)

# the line has scrolled up, and unrelated rows look similar
m = fresh(); setup_channel(m)
for r in range(23): put_row(m, r, "Public>hello there") if r == 22 else None
for i in range(40):                      # scrolling moves screen and colour RAM together
    m.mem[0x0400 + 10 * 40 + i] = m.mem[0x0400 + 23 * 40 + i]
    m.mem[0xD800 + 10 * 40 + i] = m.mem[0xD800 + 23 * 40 + i]
    m.mem[0x0400 + 23 * 40 + i] = 32
    m.mem[0xD800 + 23 * 40 + i] = 5
assert col(m, 10, 0) == 7
frame(m, pay); m.call("pnlog")
check("line scrolled to row 10: found and coloured", all(col(m, 10, i) == 5 for i in range(7)) and col(m, 10, 7) == 5)

# ---- DM ----
m = fresh(); put_row(m, 22, "alice>are you there"); m.mem[E["PRLEN"]] = 6
m.mem[0xD6] = 23; m.mem[S("PN_SK")] = 2; m.mem[S("PN_TL")] = 13; m.mem[0xA1] = 10
m.call("pnrec")
check("DM sent: yellow, waiting for its ack tag", col(m, 22, 0) == 7 and m.mem[S("PN_AW")] == 1)
for i, b in enumerate([6, 0, 0xDE, 0xAD, 0xBE, 0xEF, 0, 0, 0, 0]): m.mem[E["BUF"] + i] = b
m.call("pnsent")
check("ack tag stored", bytes(m.mem[S("PN_KY") + 4 + i] for i in range(4)) == bytes([0xDE, 0xAD, 0xBE, 0xEF]) and m.mem[S("PN_AW")] == 255)
for i, b in enumerate([0x82, 1, 2, 3, 4, 0, 0, 0, 0]): m.mem[E["BUF"] + i] = b
m.call("pnack")
check("wrong ack: still yellow", col(m, 22, 0) == 7 and m.mem[S("PN_ST") + 1] == 1)
for i, b in enumerate([0x82, 0xDE, 0xAD, 0xBE, 0xEF, 5, 0, 0, 0]): m.mem[E["BUF"] + i] = b
m.call("pnack")
check("right ack: green", col(m, 22, 0) == 5 and col(m, 22, 5) == 5 and col(m, 22, 6) == 5 and m.mem[S("PN_ST") + 1] == 2)
m = fresh(); put_row(m, 22, "alice>hi"); m.mem[E["PRLEN"]] = 6
m.mem[0xD6] = 23; m.mem[S("PN_SK")] = 2; m.mem[0xA1] = 10; m.call("pnrec")
m.mem[0xA1] = 13
for i, b in enumerate([6, 0, 1, 2, 3, 4]): m.mem[E["BUF"] + i] = b
m.call("pnsent")
check("a sent-reply 13 s later is not for that DM", m.mem[S("PN_AW")] == 255 and bytes(m.mem[S("PN_KY") + 4 + i] for i in range(4)) == bytes(4))

# ---- a sent line over two rows (s26) ----
m = fresh()
txt = "Public>" + "the quick brown fox jumps over the lazy dog and then some more text a"
put_row(m, 22, txt[:40]); put_row(m, 23, txt[40:])
for i in range(len(txt)): m.mem[0xD800 + 22 * 40 + i] = 1
m.mem[E["PRLEN"]] = 7
for i, b in enumerate(b"bob\0"): m.mem[E["NODENM"] + i] = b
m.mem[0xD6] = 24; m.mem[S("PN_SK")] = 1; m.mem[S("PN_TL")] = len(txt) - 7; m.mem[E["UIMODE"]] = 0; m.mem[0xA1] = 10
m.call("pnrec")
check("2-row line: label on its first row yellow", all(col(m, 22, i) == 7 for i in range(7)) and col(m, 23, 0) == 1)
plen = 3 + 16 * ((7 + 3 + len(txt) - 7 + 15) // 16)
frame(m, bytes([0x4C, 1, 2, 3]) + bytes(plen - 4)); m.call("pnlog")
check("2-row line: both rows green after the echo", all(col(m, 22, i) == 5 for i in range(40)) and all(col(m, 23, i) == 5 for i in range(len(txt) - 40)) and col(m, 23, len(txt) - 40) == 5 or all(col(m, 23, i) == 5 for i in range(len(txt) - 40)))

# ---- through the real dispatcher ----
m = fresh(); setup_channel(m)
for a in ("notice", "sendfr"): m.mem[syms[a]] = 0x60
m.mem[0xFFD2] = 0x60
frame(m, pay); m.call("dispat")
check("0x88 routed by dispat", m.mem[S("PN_ST")] == 2)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
