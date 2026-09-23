#!/usr/bin/env python3
"""
Minimal two-pass 6502 assembler - just the opcodes the MeshCore 64 serial
poll routine needs. Emits raw bytes; no toolchain required.
"""

# opcode table: (mnemonic, mode) -> opcode byte
OPS = {
    ("lda", "imm"): 0xA9, ("lda", "abs"): 0xAD, ("lda", "indy"): 0xB1,
    ("lda", "absx"): 0xBD,
    ("sta", "abs"): 0x8D, ("sta", "absx"): 0x9D,
    ("stx", "abs"): 0x8E, ("sty", "abs"): 0x8C,
    ("ldx", "imm"): 0xA2, ("ldx", "abs"): 0xAE,
    ("ldy", "imm"): 0xA0, ("ldy", "abs"): 0xAC,
    ("cmp", "imm"): 0xC9, ("cmp", "abs"): 0xCD,
    ("cpx", "imm"): 0xE0, ("cpx", "abs"): 0xEC,
    ("cpy", "imm"): 0xC0, ("cpy", "abs"): 0xCC,
    ("inc", "abs"): 0xEE,
    ("inx", "imp"): 0xE8, ("dex", "imp"): 0xCA,
    ("iny", "imp"): 0xC8, ("dey", "imp"): 0x88,
    ("tax", "imp"): 0xAA, ("txa", "imp"): 0x8A,
    ("tay", "imp"): 0xA8, ("tya", "imp"): 0x98,
    ("rts", "imp"): 0x60, ("nop", "imp"): 0xEA,
    ("jsr", "abs"): 0x20, ("jmp", "abs"): 0x4C,
    ("sei", "imp"): 0x78, ("cli", "imp"): 0x58, ("cld", "imp"): 0xD8,
    ("txs", "imp"): 0x9A,
    ("sta", "indy"): 0x91, ("sta", "absy"): 0x99,
    ("lda", "absy"): 0xB9,
    ("ora", "imm"): 0x09, ("and", "imm"): 0x29,
    ("pha", "imp"): 0x48, ("pla", "imp"): 0x68,
    # --- added for the pure-ML client experiment ---
    ("adc", "imm"): 0x69, ("adc", "abs"): 0x6D, ("adc", "absx"): 0x7D,
    ("sbc", "imm"): 0xE9, ("sbc", "abs"): 0xED,
    ("clc", "imp"): 0x18, ("sec", "imp"): 0x38,
    ("clv", "imp"): 0xB8,
    ("and", "abs"): 0x2D, ("ora", "abs"): 0x0D,
    ("eor", "imm"): 0x49, ("eor", "abs"): 0x4D,
    ("bit", "abs"): 0x2C,
    ("asl", "imp"): 0x0A, ("lsr", "imp"): 0x4A,
    ("rol", "imp"): 0x2A, ("ror", "imp"): 0x6A,
    ("asl", "abs"): 0x0E, ("lsr", "abs"): 0x4E,
    ("rol", "abs"): 0x2E, ("ror", "abs"): 0x6E,
    ("ora", "absx"): 0x1D, ("and", "absx"): 0x3D, ("eor", "absx"): 0x5D,
    ("sbc", "absx"): 0xFD, ("adc", "absy"): 0x79, ("sbc", "absy"): 0xF9,
    ("ora", "absy"): 0x19, ("and", "absy"): 0x39,
    ("dec", "abs"): 0xCE, ("dec", "absx"): 0xDE,
    ("inc", "absx"): 0xFE,
    ("lda", "indx"): 0xA1, ("sta", "indx"): 0x81,
    ("ldx", "absy"): 0xBE, ("ldy", "absx"): 0xBC,
    ("stx", "absy"): 0x96, ("sty", "absx"): 0x94,
    ("cmp", "absx"): 0xDD, ("cmp", "absy"): 0xD9,
    ("cmp", "indy"): 0xD1,
    ("php", "imp"): 0x08, ("plp", "imp"): 0x28,
    ("rti", "imp"): 0x40, ("brk", "imp"): 0x00,
    ("tsx", "imp"): 0xBA,
    ("jmp", "ind"): 0x6C,
}
BRANCHES = {"beq": 0xF0, "bne": 0xD0, "bcc": 0x90, "bcs": 0xB0,
            "bpl": 0x10, "bmi": 0x30}

# Inverse of each branch, for automatic long-branch relaxation. A 6502
# branch only reaches +/-127; past that the assembler rewrites
#     bcs far          ->    bcc over
#                            jmp far
#                     over:
# which is what you would do by hand, minus the chance of getting it wrong
# and minus having to redo it every time a routine above it grows.
INVERSE = {"beq": "bne", "bne": "beq", "bcc": "bcs", "bcs": "bcc",
           "bpl": "bmi", "bmi": "bpl"}

SIZES = {"imm": 2, "abs": 3, "absx": 3, "absy": 3, "indy": 2, "indx": 2,
         "ind": 3, "imp": 1, "rel": 2}

# ".byte 1,2,3" emits raw bytes - needed for lookup tables. Its length is
# not fixed, so both passes size it from the operand rather than SIZES.
def datalen(operand, mnem=".byte"):
    if mnem == ".word":
        return 2 * len([t for t in operand.split(",") if t.strip()])
    if mnem == ".text":
        return len(_unquote(operand))
    return len([t for t in operand.split(",") if t.strip()])


def _unquote(operand):
    o = operand.strip()
    if len(o) >= 2 and o[0] == o[-1] and o[0] in "\"'":
        return o[1:-1]
    raise ValueError("expected a quoted string: %r" % operand)


def parse(line):
    line = line.split(";")[0].strip()
    if not line:
        return None
    label = None
    if ":" in line:
        label, _, line = line.partition(":")
        label = label.strip()
        line = line.strip()
    if not line:
        return (label, None, None, None)
    parts = line.split(None, 1)
    mnem = parts[0].lower()
    operand = parts[1].strip() if len(parts) > 1 else ""
    if mnem in (".byte", ".word", ".text"):
        return (label, mnem, "data", operand)
    if mnem in BRANCHES:
        return (label, mnem, "rel", operand)
    if not operand:
        return (label, mnem, "imp", operand)
    if operand.startswith("#"):
        return (label, mnem, "imm", operand[1:])
    if operand.startswith("(") and operand.lower().endswith("),y"):
        return (label, mnem, "indy", operand[1:operand.index(")")])
    if operand.startswith("(") and operand.lower().endswith(",x)"):
        return (label, mnem, "indx", operand[1:operand.lower().index(",x)")])
    if operand.startswith("(") and operand.endswith(")"):
        return (label, mnem, "ind", operand[1:-1])
    if operand.lower().endswith(",x"):
        return (label, mnem, "absx", operand[:-2])
    if operand.lower().endswith(",y"):
        return (label, mnem, "absy", operand[:-2])
    return (label, mnem, "abs", operand)


def _atom(tok, syms):
    tok = tok.strip()
    if tok.startswith("$"):
        return int(tok[1:], 16)
    if tok.startswith("%"):
        return int(tok[1:], 2)
    if tok.lstrip("-").isdigit():
        return int(tok)
    if tok in syms:
        return syms[tok]
    raise ValueError(f"unknown symbol: {tok!r}")


def value(tok, syms):
    """A symbol or number, optionally <lo / >hi, optionally label+n / label-n.

    The lo/hi operators are what make it practical to set up pointers from
    ML -- "lda #<buf" instead of hand-computing the halves and having them
    silently rot the next time the code above them changes length.
    """
    tok = tok.strip()
    op = None
    if tok[:1] in ("<", ">"):
        op, tok = tok[0], tok[1:].strip()
    # split on the LAST +/- that is not the leading sign, so "label-1" works
    total, i = None, 0
    parts, sign, cur = [], 1, ""
    for ch in tok:
        if ch in "+-" and cur.strip():
            parts.append((sign, cur))
            sign, cur = (1 if ch == "+" else -1), ""
        else:
            cur += ch
    parts.append((sign, cur))
    total = 0
    for sg, part in parts:
        total += sg * _atom(part, syms)
    if op == "<":
        return total & 0xFF
    if op == ">":
        return (total >> 8) & 0xFF
    return total


def assemble(src, org, equates=None):
    syms = dict(equates or {})
    lines = [parse(l) for l in src.splitlines()]
    lines = [l for l in lines if l]

    # Indices of branches that need relaxing to 5 bytes. Sizing and range
    # depend on each other, so iterate until the set stops growing.
    # **Refuse duplicate labels.** Silently letting the later definition win
    # means every jump to that name lands in the wrong routine, and the
    # symptom is a hang somewhere unrelated. Cost hours once; never again.
    seen = set()
    for label, mnem, mode, operand in lines:
        if label:
            if label in seen:
                raise ValueError("duplicate label: %r" % label)
            seen.add(label)

    longbr = set()
    for _ in range(64):
        syms = dict(equates or {})
        pc = org
        for i, (label, mnem, mode, operand) in enumerate(lines):
            if label:
                syms[label] = pc
            if mnem in (".byte", ".word", ".text"):
                pc += datalen(operand, mnem)
            elif mnem:
                pc += 5 if i in longbr else SIZES[mode]
        grew = False
        pc = org
        for i, (label, mnem, mode, operand) in enumerate(lines):
            if mnem in (".byte", ".word", ".text"):
                pc += datalen(operand, mnem)
                continue
            if not mnem:
                continue
            size = 5 if i in longbr else SIZES[mode]
            if mode == "rel" and i not in longbr:
                delta = value(operand, syms) - (pc + 2)
                if not -128 <= delta <= 127:
                    longbr.add(i)
                    grew = True
            pc += size
        if not grew:
            break

    # pass 1: assign addresses to labels
    pc = org
    for i, (label, mnem, mode, operand) in enumerate(lines):
        if label:
            syms[label] = pc
        if mnem in (".byte", ".word", ".text"):
            pc += datalen(operand, mnem)
        elif mnem:
            pc += 5 if i in longbr else SIZES[mode]

    # pass 2: emit
    out = bytearray()
    pc = org
    for i, (label, mnem, mode, operand) in enumerate(lines):
        if not mnem:
            continue
        if i in longbr:
            target = value(operand, syms)
            out += bytes([BRANCHES[INVERSE[mnem]], 3,
                          0x4C, target & 0xFF, (target >> 8) & 0xFF])
            pc += 5
            continue
        if mnem in (".byte", ".word", ".text"):
            if mnem == ".text":
                vals = [ord(c) for c in _unquote(operand)]
            elif mnem == ".word":
                vals = []
                for t in operand.split(","):
                    if t.strip():
                        v = value(t, syms)
                        vals += [v & 0xFF, (v >> 8) & 0xFF]
            else:
                vals = [value(t, syms) & 0xFF
                        for t in operand.split(",") if t.strip()]
            out += bytes(vals)
            pc += len(vals)
            continue
        if mode == "rel":
            target = value(operand, syms)
            delta = target - (pc + 2)
            if not -128 <= delta <= 127:
                raise ValueError(f"branch out of range: {mnem} {operand} ({delta})")
            out += bytes([BRANCHES[mnem], delta & 0xFF])
        elif mode == "imp":
            out += bytes([OPS[(mnem, mode)]])
        elif mode in ("imm", "indy", "indx"):
            out += bytes([OPS[(mnem, mode)], value(operand, syms) & 0xFF])
        else:
            v = value(operand, syms)
            out += bytes([OPS[(mnem, mode)], v & 0xFF, (v >> 8) & 0xFF])
        pc += SIZES[mode]
    return bytes(out), syms
