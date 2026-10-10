#!/usr/bin/env python3
"""Run sha256_6502.py's hashch under py65 and compare with hashlib.
   venv/bin/python -I test_sha256.py"""
import hashlib, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True
from asm import assemble
import sha256_6502
from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

ORG, CHNAME, SECBUF = 0x2000, 0x0400, 0x0500
res = assemble(sha256_6502.source(), ORG, {"CHNAME": CHNAME, "SECBUF": SECBUF})
code, syms = res[0], res[1]
print("module: %d bytes, hashch at $%04X" % (len(code), syms["hashch"]))


def run(name):
    ram = [0] * 65536
    ram[ORG:ORG + len(code)] = list(code)
    for i, b in enumerate(name[:32]):
        ram[CHNAME + i] = b
    stub = 0x1000
    ram[stub:stub + 6] = [0x20, syms["hashch"] & 255, syms["hashch"] >> 8, 0x4C, 3, 0x10]
    m = MPU(memory=ObservableMemory(subject=ram))
    m.pc = stub
    m.sp = 0xFF
    n = 0
    while m.pc != stub + 3:
        m.step()
        n += 1
        assert n < 3000000, "runaway"
    return bytes(m.memory[SECBUF:SECBUF + 16]), m.processorCycles


rng = random.Random(1)
names = [b"#test", b"#", b"#a", b"#public", b"#meshcore64", b"#c64",
         b"#" + b"x" * 31, b"#" + b"y" * 30, b"#Test", b"#hello world"]
names += [b"#" + bytes(rng.randrange(33, 127) for _ in range(rng.randrange(0, 32))) for _ in range(60)]
bad = 0
for nm in names:
    got, cyc = run(nm)
    want = hashlib.sha256(nm).digest()[:16]
    ok = got == want
    bad += not ok
    if not ok or nm in (b"#test", b"#" + b"x" * 31):
        print("%-36r %s %s (%d cycles)" % (nm, got.hex(), "OK" if ok else "BAD want " + want.hex(), cyc))
print("%d/%d names match hashlib" % (len(names) - bad, len(names)))
sys.exit(1 if bad else 0)
