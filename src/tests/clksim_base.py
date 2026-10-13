"""py65 harness shared by clksim/gapsim."""
from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory


def petscii(bs):
    # .text lowercase -> what the assembler emits; decode back for checks
    return "".join(chr(b + 32) if 65 <= b <= 90 else chr(b) for b in bs)


class M:
    def __init__(self, mod, code, syms, prg, uci_text=None):
        global E
        E = mod.EQU
        s2off = syms["s2img"] - mod.ORG
        code2 = prg[2 + s2off: 2 + s2off + (0xC2D0 - 0xA000)]
        self.syms = syms
        self.mem = ObservableMemory()
        for i, b in enumerate(code):
            self.mem[mod.ORG + i] = b
        for i, b in enumerate(code2):
            self.mem[0xA000 + i] = b
        if hasattr(mod, "S3ORG"):
            for i, b in enumerate(prg[2 + (mod.S3ORG - mod.ORG):]):
                self.mem[mod.S3ORG + i] = b
        if hasattr(mod, "S4ORG"):        # segment 4: as main copies it after the splash
            tail4 = prg[2 + (mod.S4IMG - mod.ORG):]
            if hasattr(mod, "SEG5"):     # the last 512 bytes are segment 5's pages
                tail4 = tail4[:-(getattr(mod, 'S5IMGEND', getattr(mod, 'S5MAX', 0x9B00)) - 0x9900)]
            for i, b in enumerate(tail4):
                self.mem[mod.S4ORG + i] = b
        if getattr(mod, "SEG5", b""):    # segment 5, as main copies it to $9960
            for i, b in enumerate(mod.SEG5):
                self.mem[mod.S5ORG + i] = b
        self.uci = uci_text
        self.mem.subscribe_to_read(range(0xDF1C, 0xDF20), self.rd)
        self.mem.subscribe_to_write(range(0xDF1C, 0xDF20), self.wr)
        self.data, self.state = [], 0
        # stub out things with side effects: notice/gsvh -> rts
        for n in ("notice", "gsvh"):
            self.mem[self.syms[n]] = 0x60
        self.notices = 0

    def rd(self, a):
        if self.uci is None:
            return 0
        if a == 0xDF1D: return 0xC9
        if a == 0xDF1C: return (self.state << 4) | (0x80 if self.data else 0)
        if a == 0xDF1E: return self.data.pop(0) if self.data else 0
        return 0

    def wr(self, a, v):
        if a == 0xDF1C:
            if v & 1: self.state, self.data = 2, list(self.uci.encode())
            if v & 6: self.state, self.data = 0, []

    def call(self, label, a=0, x=0, y=0):
        t = 0x0300
        self.mem[t:t + 3] = [0x20, self.syms[label] & 0xFF, self.syms[label] >> 8]
        mpu = MPU(memory=self.mem)
        mpu.pc, mpu.sp, mpu.a, mpu.x, mpu.y = t, 0xFF, a, x, y
        n = 0
        while mpu.pc != t + 3:
            mpu.step(); n += 1
            assert n < 2000000, "hung in " + label

    def put32(self, addr, v):
        for i in range(4): self.mem[addr + i] = (v >> (8 * i)) & 0xFF

    def get32(self, addr):
        return sum(self.mem[addr + i] << (8 * i) for i in range(4))

    def tstr(self):
        b = []
        a = E["TSTR"]
        while self.mem[a] and len(b) < 40:
            b.append(self.mem[a]); a += 1
        return petscii(b)


