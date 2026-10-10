#!/usr/bin/env python3
"""
rxsim.py -- run OUR bit-banged receiver (serini + nmih from mlfull.py or a
patched copy) against a CIA2 model that behaves like real silicon.

Why: VICE fires FLAG exactly ONCE per byte (rsuser.c start_bit_trigger), so
bugs that depend on FLAG latching on every falling data edge are invisible
there. This model latches FLAG on EVERY falling edge of RXD, as the hardware
does, and applies the real 6526 ICR rules:

  * ICR data bits latch whether or not the source is enabled in the mask.
  * A read returns the data bits (bit 7 = "some enabled source is set") and
    clears them.
  * The NMI line is active while (data & mask) != 0. The 6502 NMI is edge
    triggered: only an inactive->active transition produces an NMI.
  * Timer B: N+1 cycle period, one-shot or continuous, force load, start bit.

CPU timing: py65 instruction cycle counts, plus NMI entry (7) and the KERNAL
stub at $FE43 (SEI = 2, JMP ($0318) = 5), plus optional badline stalls.

Usage:
  python3 rxsim.py --src ml/mlfull.py --baud 600 [--runs 50] [--nbytes 90]
                   [--latadj 275] [--badlines 1] [--err 0.01] [--seed 1]
Exit status 0 = every run received the bytes byte-exact; 1 otherwise.
"""
import argparse, importlib.util, os, random, sys, tempfile

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

NTSC_CLK = 1022727
LINE_CYC = 65          # NTSC cycles per raster line
LINES = 263


def load_src(path):
    spec = importlib.util.spec_from_file_location("srcmod", path)
    m = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
    spec.loader.exec_module(m)
    return m


def frame_bytes(rng, n):
    """A reply-like frame: '>' len_lo len_hi opcode payload. Includes nulls
    and dense edge patterns (0x55, 0xAA) because those are the worst cases."""
    payload = [5] + [rng.choice([0, 0, 0x55, 0xAA, 0xFF, 0x0F, 0xF0])
                     if rng.random() < 0.3 else rng.randrange(256)
                     for _ in range(n - 4)]
    return [0x3E, len(payload) & 255, len(payload) >> 8] + payload


def waveform(data, bit, t0, err, rng):
    """List of (cycle, level) transitions for back-to-back 8N1 bytes.
    Idle = 1. The sender's clock is off by `err` (fractional)."""
    b = bit * (1.0 + err)
    edges = []
    level = 1
    t = float(t0)
    for byte in data:
        bits = [0] + [(byte >> i) & 1 for i in range(8)] + [1]   # start,data LSB first,stop
        for i0, v in enumerate(bits):
            if v != level:
                edges.append((int(round(t)), v, i0 == 0))
                level = v
            t += b
    return edges


class Sim:
    def __init__(self, mod, ctrl, latadj, badlines, seed, flagmode="edge"):
        self.flagmode = flagmode
        self.rng = random.Random(seed)
        self.badlines = badlines
        out = os.path.join(tempfile.gettempdir(), "rxsim-%d.prg" % os.getpid())
        code, syms, prg, bit, half = mod.build(ctrl, out, 0, NTSC_CLK, 0, latadj)
        self.syms, self.bit, self.half = syms, bit, half
        self.EQU = mod.EQU
        self.org = mod.ORG
        self.code = code
        self.baud = mod.RATES[ctrl]

    # ---- CIA2 model ----
    def reset_cia(self):
        self.icr_data = 0
        self.icr_mask = 0
        self.line = 0
        self.nmi_at = None           # time of a pending NMI edge
        # timers: A = bit 0 of ICR, B = bit 1
        self.T = {"A": dict(bit=1, latch=0xFFFF, run=False, cont=False, next=None, remain=0xFFFF),
                  "B": dict(bit=2, latch=0xFFFF, run=False, cont=False, next=None, remain=0xFFFF)}
        self.pra_log = []
        self.ddrb = 0
        self.edge_i = 0
        self.rxd = 1
        self.t_ev = 0                # time up to which events are processed
        self.regs = {}
        self.trace = []

    def update_line(self, t):
        new = 1 if (self.icr_data & self.icr_mask & 0x1F) else 0
        if new and not self.line:
            if self.nmi_at is None:
                self.nmi_at = t
        self.line = new

    def advance(self, t):
        while True:
            te = self.edges[self.edge_i][0] if self.edge_i < len(self.edges) else None
            tus = [(tm["next"], k) for k, tm in self.T.items()
                   if tm["run"] and tm["next"] is not None]
            tu = min(tus)[0] if tus else None
            cands = [x for x in (te, tu) if x is not None and x <= t]
            if not cands:
                break
            tn = min(cands)
            if te is not None and te == tn:
                lvl = self.edges[self.edge_i][1]
                is_start = self.edges[self.edge_i][2]
                self.edge_i += 1
                if lvl == 0 and self.rxd == 1 and (is_start or self.flagmode == "edge"):
                    self.icr_data |= 0x10        # FLAG on EVERY falling edge
                    self.update_line(tn)
                self.rxd = lvl
            else:
                for k, tm in self.T.items():
                    if tm["run"] and tm["next"] == tn:
                        self.icr_data |= tm["bit"]
                        if tm["cont"]:
                            tm["next"] = tn + tm["latch"] + 1
                        else:
                            tm["run"] = False
                            tm["next"] = None
                            tm["remain"] = tm["latch"]
                self.update_line(tn)
        self.t_ev = max(self.t_ev, t)

    def tnow(self):
        return self.mpu.processorCycles + self.acc_off

    def rd(self, addr):
        t = self.tnow()
        self.advance(t)
        r = addr & 15
        if addr in (0xDD0D,):
            v = self.icr_data & 0x1F
            if v & self.icr_mask:
                v |= 0x80
            self.icr_data = 0
            self.update_line(t)
            return v
        if addr == 0xDD01:                    # PRB: PB0 = RXD
            return 0xFE | self.rxd
        if addr in (0xDD0E, 0xDD0F):
            return 0x01 if self.T["A" if addr == 0xDD0E else "B"]["run"] else 0x00
        if addr in (0xDD04, 0xDD05, 0xDD06, 0xDD07):
            tm = self.T["A" if addr < 0xDD06 else "B"]
            c = max(0, tm["next"] - t - 1) if tm["run"] and tm["next"] else tm["remain"]
            return (c >> 8) & 255 if addr & 1 else c & 255
        return self.regs.get(addr, 0)

    def wr(self, addr, v):
        t = self.tnow()
        self.advance(t)
        self.regs[addr] = v
        if addr == 0xDD0D:
            if v & 0x80:
                self.icr_mask |= v & 0x1F
            else:
                self.icr_mask &= ~(v & 0x1F)
            self.update_line(t)
        elif addr == 0xDD00:
            self.pra_log.append((t, v))
        elif addr in (0xDD04, 0xDD05, 0xDD06, 0xDD07):
            tm = self.T["A" if addr < 0xDD06 else "B"]
            if addr & 1:
                tm["latch"] = (tm["latch"] & 0x00FF) | (v << 8)
            else:
                tm["latch"] = (tm["latch"] & 0xFF00) | v
        elif addr in (0xDD0E, 0xDD0F):
            tm = self.T["A" if addr == 0xDD0E else "B"]
            if v & 0x10:
                tm["remain"] = tm["latch"]
            tm["cont"] = not (v & 0x08)
            if v & 0x01:
                tm["run"] = True
                tm["next"] = t + tm["remain"] + 1
            else:
                if tm["run"] and tm["next"] is not None:
                    tm["remain"] = max(0, tm["next"] - t - 1)
                tm["run"] = False
                tm["next"] = None

    # ---- run one reception ----
    def run(self, data, err, nbytes_limit=None):
        self.reset_cia()
        self.acc_off = 0
        self.phase = 0
        # RAM image
        ram = bytearray(65536)
        o = self.org
        ram[o:o + len(self.code)] = self.code
        # KERNAL NMI stub at $FE43: SEI ; JMP ($0318)  (we jump straight)
        # vector table: NMI -> $FE43 (unused by the model, which dispatches itself)
        ram[0xFFFA] = 0x43; ram[0xFFFB] = 0xFE
        # driver: JSR serini ; JMP *
        stub = 0x0334
        s = self.syms["serini"]
        ram[stub:stub + 6] = bytes([0x20, s & 255, s >> 8, 0x4C, (stub + 3) & 255, (stub + 3) >> 8])
        mem = ObservableMemory(subject=list(ram))
        self.mem = mem
        self.mpu = MPU(memory=mem)
        raw = mem
        for a in range(0xDD00, 0xDD10):
            mem.subscribe_to_read([a], lambda addr, self=self: self.rd(addr))
            mem.subscribe_to_write([a], lambda addr, v, self=self: self.wr(addr, v))
        self.mpu.pc = stub
        self.mpu.sp = 0xFF
        # run serini first (ensures the mask/vector setup is exercised)
        self.edges = []
        start_t = self.mpu.processorCycles
        guard = 0
        while self.mpu.pc != stub + 3 and guard < 200:
            self.step_one()
            guard += 1
        t0 = self.mpu.processorCycles + 20000       # idle line for a while first
        self.edges = waveform(data, self.bit, t0, err, self.rng)
        t_end = t0 + int(len(data) * 10 * self.bit * (1 + abs(err))) + 4 * self.bit
        phase = self.rng.randrange(LINE_CYC * LINES)
        self.phase = phase
        while self.mpu.processorCycles < t_end:
            self.step_one()
        head = raw[self.EQU["RHEAD"]]
        buf = bytes(raw[self.EQU["RBUF"] + i] for i in range(head))
        return buf, raw[self.EQU["FRERR"]]

    # ---- transmit + answer experiment ----
    def _boot(self, stub_calls):
        """Fresh RAM image with serini, then the given JSR targets, then JMP *."""
        self.reset_cia()
        self.acc_off = 0
        self.phase = 0
        ram = bytearray(65536)
        o = self.org
        ram[o:o + len(self.code)] = self.code
        ram[0xFFFA] = 0x43; ram[0xFFFB] = 0xFE
        stub = 0x0334
        p = stub
        for name in ["serini"] + stub_calls:
            a = self.syms[name]
            ram[p:p + 3] = bytes([0x20, a & 255, a >> 8]); p += 3
        ram[p:p + 3] = bytes([0x4C, p & 255, p >> 8])
        self.stub_end = p
        # APP_START payload, as pyastart in the client
        pay = [1, 0, 0, 0, 0, 0, 0, 0, 67, 54, 52]
        ram[self.EQU["TXLEN"]] = len(pay)
        for i, b in enumerate(pay):
            ram[self.EQU["TXBUF"] + i] = b
        mem = ObservableMemory(subject=list(ram))
        self.mem = mem
        self.mpu = MPU(memory=mem)
        for a in range(0xDD00, 0xDD10):
            mem.subscribe_to_read([a], lambda addr, self=self: self.rd(addr))
            mem.subscribe_to_write([a], lambda addr, v, self=self: self.wr(addr, v))
        self.mpu.pc = stub
        self.mpu.sp = 0xFF
        self.edges = []

    def run_tx(self, delta, reply, err=0.0):
        """Send APP_START with sendfr, and have the 'radio' start its reply
        `delta` cycles after OUR last stop bit ENDS (negative = it starts
        while our stop bit is still going out, which a UART that decodes at
        the middle of the stop bit can do)."""
        # pass 0: find when our last stop bit starts (deterministic)
        self._boot(["sendfr"])
        while self.mpu.pc != self.stub_end and self.mpu.processorCycles < 5000000:
            self.step_one()
        t_sb = self.pra_log[-1][0]
        # pass 1: same run, with the reply on the wire
        self._boot(["sendfr"])
        t_reply = t_sb + self.bit + delta
        self.edges = waveform(reply, self.bit, t_reply, err, self.rng)
        t_end = t_reply + int(len(reply) * 10 * self.bit * 1.02) + 4 * self.bit
        while self.mpu.processorCycles < t_end:
            self.step_one()
        raw = self.mem
        head = raw[self.EQU["RHEAD"]]
        buf = bytes(raw[self.EQU["RBUF"] + i] for i in range(head))
        return buf, raw[self.EQU["FRERR"]]

    def step_one(self):
        m = self.mpu
        self.acc_off = 2
        t = m.processorCycles
        self.advance(t)
        if self.nmi_at is not None and self.nmi_at <= t:
            self.nmi_at = None
            # push PC, P (B clear), set I
            pc = m.pc
            m.stPush(pc >> 8); m.stPush(pc & 255)
            m.stPush(m.p & ~0x10 | 0x20)
            m.p |= 0x04
            vec = m.memory[0x0318] | (m.memory[0x0319] << 8)
            m.pc = vec
            m.processorCycles += 7 + 2 + 5
            return
        if self.badlines:
            tt = t + self.phase
            line = (tt // LINE_CYC) % LINES
            col = tt % LINE_CYC
            if 51 <= line < 251 and (line - 51) % 8 == 0 and 12 <= col < 54:
                m.processorCycles += 54 - col      # CPU held off by VIC DMA
        m.step()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "mlfull.py"))
    ap.add_argument("--baud", type=int, default=600)
    ap.add_argument("--latadj", type=int, default=275)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--nbytes", type=int, default=90)
    ap.add_argument("--badlines", type=int, default=1)
    ap.add_argument("--err", type=float, default=0.01, help="sender clock error (fraction)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--flag", default="edge", choices=["edge", "byte"],
                    help="edge = real silicon (FLAG on every falling edge); byte = VICE (start bit only)")
    ap.add_argument("--tx", action="store_true",
                    help="experiment: send APP_START with sendfr and sweep when the reply starts")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    mod = load_src(a.src)
    ctrl = [k for k, v in mod.RATES.items() if v == a.baud][0]
    sim = Sim(mod, ctrl, a.latadj, a.badlines, a.seed, a.flag)
    rng = random.Random(a.seed * 7919)
    if a.tx:
        reply = frame_bytes(rng, 66)          # 3E 42 00 05 ... = 69 bytes
        bit = sim.bit
        lo, hi, step = -int(bit * 1.0), int(bit * 2.0), max(8, bit // 53)
        bad = 0
        row = []
        for d in range(lo, hi + 1, step):
            got, fe = sim.run_tx(d, reply)
            ok = list(got) == reply
            bad += (not ok)
            row.append((d, ok, len(got), got[:4].hex(" "), fe))
        print("tx/answer sweep, baud=%d bit=%d: reply start relative to END of our stop bit" % (a.baud, bit))
        for d, ok, n, h, fe in row:
            print("  delta %+5d (%+.2f bit): %s n=%d first=%s fe=%d" % (d, d / bit, "ok  " if ok else "LOST", n, h, fe))
        print("failures: %d of %d reply start times" % (bad, len(row)))
        sys.exit(0 if not bad else 1)
    ok = 0
    tot_bytes = 0
    tot_good = 0
    for r in range(a.runs):
        data = frame_bytes(rng, a.nbytes)
        err = rng.uniform(-a.err, a.err)
        got, frerr = sim.run(data, err)
        exact = list(got[:len(data)]) == data and len(got) == len(data)
        nmatch = sum(1 for x, y in zip(got, data) if x == y)
        tot_bytes += len(data); tot_good += nmatch
        ok += exact
        if a.v or not exact:
            print("run %3d err=%+.4f sent=%d got=%d match=%d frerr=%d %s" %
                  (r, err, len(data), len(got), nmatch, frerr, "OK" if exact else "FAIL"))
            if not exact and a.v:
                print("  sent:", bytes(data[:24]).hex(" "))
                print("  got :", got[:24].hex(" "))
    print("flag=%s baud=%d latadj=%d badlines=%d: %d/%d runs byte-exact, %d/%d bytes matched"
          % (a.flag, a.baud, a.latadj, a.badlines, ok, a.runs, tot_good, tot_bytes))
    sys.exit(0 if ok == a.runs else 1)


if __name__ == "__main__":
    main()
