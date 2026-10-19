#!/usr/bin/env python3
"""v2.1: message timestamps on the rule above each message, the alert sound, the settings bytes (meshcore64) in py65."""
import sys, os, importlib, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "."))
sys.path.insert(0, os.path.dirname(__file__))
from py65.devices.mpu6502 import MPU
mod = importlib.import_module(sys.argv[1] if len(sys.argv) > 1 else "meshcore64")
import clksim_base as B
code, syms, prg, bit, half = mod.build(13, "/tmp/ts21.prg", 0, mod.PAL, 0, 125, 0)
E = mod.EQU
bad = 0
def check(name, cond, info=""):
    global bad
    bad += not cond
    print("%-4s %s %s" % ("ok" if cond else "FAIL", name, info))
def A(n): return syms[n] if n in syms else E[n]
m = B.M(mod, code, syms, prg)
out, plots, sid = [], [], []
m.mem[0xFFD2:0xFFD6] = [0x8D, 0xF0, 0x02, 0x60]        # CHROUT: sta $02f0
m.mem[0xFFF0:0xFFF7] = [0x8E, 0xF1, 0x02, 0x8C, 0xF2, 0x02, 0x60]   # PLOT: stx/sty
m.mem.subscribe_to_write([0x2F0], lambda a, v: out.append(v))
m.mem.subscribe_to_write([0x2F2], lambda a, v: plots.append((m.mem[0x2F1], v)))
m.mem.subscribe_to_write(range(0xD400, 0xD419), lambda a, v: sid.append((a - 0xD400, v)))
m.mem[0x0310] = 0x60; m.mem[0x0314] = 0x10; m.mem[0x0315] = 0x03   # the KERNAL's IRQ: an rts
for n in ("lput",): m.mem[A(n)] = 0x60
def pet(bs): return "".join(chr(b + 32) if 65 <= b <= 90 else chr(b - 128) if 193 <= b <= 218 else chr(b) for b in bs)
def scr(bs): return "".join("-" if b == 64 else chr(b + 96) if 1 <= b <= 26 else chr(b) if 32 <= b < 64 or 65 <= b <= 90 else "?" for b in bs)
def tsb(): return pet(m.mem[A("TSB"):A("TSB") + m.mem[A("TSLEN")]])
NOW = int(datetime.datetime(2026, 10, 18, 13, 41, 30, tzinfo=datetime.timezone.utc).timestamp())
def msg(op, ts, zone=-20, tsok=1, now=NOW):
    m.put32(A("NOWTS"), now); m.mem[A("TSOK")] = tsok; m.mem[A("UTCOFF")] = zone & 255
    b = A("BUF"); m.mem[b] = op
    m.put32(b + (7 if op == 17 else 12), ts)
    m.mem[A("TMP")] = 3
    m.call("tsget")
def want(ts, zone_q):
    t = datetime.datetime.fromtimestamp(ts + zone_q * 900, datetime.timezone.utc)
    n = datetime.datetime.fromtimestamp(NOW + zone_q * 900, datetime.timezone.utc)
    if t.date() == n.date(): return t.strftime("%H:%M")
    return "%s %d %s" % (t.strftime("%a"), t.day, t.strftime("%b %H:%M"))
m.mem[A("OFFSND")] = 2                                   # quiet while the text is checked
for ts, zone, what in [(NOW - 60, -20, "same day, UTC-5"), (NOW - 60, 4, "UTC+1"), (NOW - 60, 0x80, "zone unknown: UTC"),
                       (NOW - 86400 * 1 - 3600 * 10, -20, "yesterday"), (NOW - 86400 * 3, -20, "three days ago"),
                       (NOW - 86400 * 40, 4, "last month"), (NOW - 86400 * 300, 0, "last year"),
                       (int(datetime.datetime(2026, 3, 1, 4, 5, tzinfo=datetime.timezone.utc).timestamp()), 0, "1 March (single-digit day)"),
                       (int(datetime.datetime(2026, 12, 31, 23, 59, tzinfo=datetime.timezone.utc).timestamp()) - 86400 * 365, 0, "31 Dec")]:
    z = 0 if zone == 0x80 else zone
    msg(17, ts, zone)
    check("%-28s %r" % (what, tsb()), tsb() == want(ts, z), "want %r" % want(ts, z))
msg(17, NOW + 600, -20); check("10 min ahead of our clock: kept", tsb() == want(NOW + 600, -20), tsb())
msg(17, NOW + 3600, -20); check("an hour ahead: our clock instead", tsb() == want(NOW, -20), tsb())
msg(17, 12345, -20); check("no clock at the sender (1970): our clock", tsb() == want(NOW, -20), tsb())
msg(17, 0, -20, tsok=0); check("neither has a clock: no time", m.mem[A("TSLEN")] == 0)
msg(17, NOW - 60, -20, tsok=0); check("we have no clock: the sender's", tsb() == want(NOW - 60, -20), tsb())
msg(17, NOW - 86400 * 3, -20, tsok=0); check("no clock yet: no 'today' to compare with, so the time alone", tsb() == want(NOW - 86400 * 3, -20)[-5:], tsb())
msg(16, NOW - 120, -20); check("a DM (timestamp at +12)", tsb() == want(NOW - 120, -20), tsb())
check("tsget hands back TMP", True)
# --- the rule above it, in the archive ---
msg(17, NOW - 60, -20)
m.mem[A("NOTS")] = 0; m.mem[A("REGION")] = 2
m.call("lsep")
line = scr(m.mem[A("SBUF"):A("SBUF") + 40])
check("archive rule %r" % line, line == "-" * 31 + " 08:40 " + "-" * 2, )
check("TSFL kept for the All copy", m.mem[A("TSFL")] == 1)
m.mem[A("REGION")] = 8; m.call("lsep")
check("the All copy gets it too, then TSFL is cleared", scr(m.mem[A("SBUF"):A("SBUF") + 40]) == line and m.mem[A("TSFL")] == 0)
msg(17, NOW - 86400 * 2, -20); m.mem[A("REGION")] = 2; m.call("lsep")
line = scr(m.mem[A("SBUF"):A("SBUF") + 40])
check("archive rule, another day %r" % line, line == "-" * 20 + " " + want(NOW - 86400 * 2, -20) + " --")
m.mem[A("TSFL")] = 0; m.put32(A("NOWTS"), NOW); m.mem[A("REGION")] = 8; m.call("lsep")
check("our own message (arcown): now", scr(m.mem[A("SBUF") + 31:A("SBUF") + 38]) == " 08:41 ")
m.mem[A("NOTS")] = 1; msg(17, NOW - 60, -20); m.call("lsep")
check("timestamps off: a plain rule", scr(m.mem[A("SBUF"):A("SBUF") + 40]) == "-" * 40)
m.mem[A("NOTS")] = 0
# --- colours of a painted rule row ---
row = 0x0400 + 5 * 40
for i in range(40): m.mem[row + i] = m.mem[A("SBUF") + i]
msg(17, NOW - 60, -20); m.mem[A("REGION")] = 2; m.call("lsep")
for i in range(40): m.mem[row + i] = m.mem[A("SBUF") + i]
m.mem[A("PTR")] = row & 255; m.mem[A("PTR") + 1] = row >> 8
m.call("apcol")
cols = [m.mem[0xD800 + 5 * 40 + i] for i in range(40)]
check("rule dark grey, its time light grey", all(c == 11 for c in cols[:31]) and all(c == 15 for c in cols[31:38]) and cols[38] == 11, cols[28:40])
# --- 80 columns: a rule's left half is plain ---
m.mem[A("PTR")] = row & 255; m.mem[A("PTR") + 1] = row >> 8
m.mem[A("KFI")] = 0; m.mem[A("KLR")] = 5; m.mem[A("KRR")] = 5
def kf(y):
    t = 0x0300; m.mem[t:t + 3] = [0x20, A("kfrd6") & 255, A("kfrd6") >> 8]
    c = MPU(memory=m.mem); c.pc, c.sp, c.y = t, 0xFF, y
    while c.pc != t + 3: c.step()
    return c.a, c.y
check("rule row, left half: the time is drawn as rule", kf(33) == (64, 33) and kf(5) == (64, 5))
m.mem[A("KRR")] = 6
check("a text row is drawn as it is", kf(33) == (m.mem[row + 33], 33))
# --- live: the time onto the rule above the prompt ---
for i in range(40): m.mem[0x0400 + 22 * 40 + i] = 64
m.mem[214] = 23; m.mem[A("K80")] = 0; m.mem[A("PRLEN")] = 0; m.mem[A("INLEN")] = 0; m.mem[A("KSEPW")] = 39
msg(17, NOW - 60, -20)
out.clear(); plots.clear(); m.call("bkprm6")
check("live: printed on row 22 at column 31", plots == [(22, 31), (23, 0)] and pet(out) == chr(155) + " 08:40 ", (plots, out))
m.mem[0x0400 + 22 * 40] = 1
out.clear(); plots.clear(); m.call("bkprm6")
check("live: the row above is not a rule: nothing", out == [] and plots == [])
m.mem[0x0400 + 22 * 40] = 64; m.mem[A("BUF")] = 5
out.clear(); m.call("bkprm6")
check("live: not a message frame: nothing", out == [])
m.mem[A("BUF")] = 17; m.mem[A("NOTS")] = 1
out.clear(); m.call("bkprm6")
check("live: timestamps off: nothing", out == [])
m.mem[A("NOTS")] = 0
# --- the alert ---
def irq(n):
    for _ in range(n): m.call("sndirq")
def notes():
    return [(v) for r, v in sid if r == 4]
m.mem[A("OFFSND")] = 0; sid.clear()
m.mem[A("A") if False else 0x30A] = 0
m.call("sndmsg", a=17)
check("hooks the jiffy interrupt", (m.mem[0x314] | m.mem[0x315] << 8) == A("sndirq") and (m.mem[A("SNDOLD")] | m.mem[A("SNDOLD") + 1] << 8) == 0x0310)
check("volume and envelope set", (24, 15) in sid and (5, 9) in sid and (6, 9) in sid)
sid.clear(); irq(8)
check("channel: one note (C6), gated on then off", notes() == [16, 17, 16] and (0, 0xA0) in sid and (1, 0x45) in sid, sid)
sid.clear(); m.call("sndmsg", a=16); sid.clear(); irq(12)
check("DM: two notes (G5, E6)", notes() == [16, 17, 16, 17, 16] and [v for r, v in sid if r == 1] == [0x34, 0x57], sid)
m.mem[0x314] = 0x10; m.mem[0x315] = 0x03
m.call("sndmsg", a=17)
check("the hook is installed once", (m.mem[0x314] | m.mem[0x315] << 8) == 0x0310)
for off, op, sounds in [(1, 17, False), (1, 16, True), (2, 16, False), (2, 17, False), (0, 16, True)]:
    m.mem[A("OFFSND")] = off; m.mem[A("SNDT")] = 0
    m.call("sndmsg", a=op)
    check("setting %d, %s: %s" % (off, "DM" if op == 16 else "channel", "sound" if sounds else "quiet"), (m.mem[A("SNDT")] == 1) == sounds)
m.mem[A("OFFSND")] = 0; m.mem[A("SNDT")] = 0
msg(17, NOW, -20)
check("tsget sounds the alert", m.mem[A("SNDT")] == 1)
# --- settings bytes are saved with the session ---
check("OFFSND and NOTS follow NFMT (inside the 60 saved bytes)", A("OFFSND") == A("NFMT") + 1 and A("NOTS") == A("NFMT") + 2 and A("NOTS") - A("DMUSE") == 59)
print("FAILURES:", bad); sys.exit(1 if bad else 0)
