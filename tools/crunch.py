#!/usr/bin/env python3
"""
Strip comments from a tokenised C64 BASIC .prg.

Why this exists: meshcore64.bas is heavily commented on purpose - the
comments are where the hard-won platform knowledge lives - but compiled
with the comments intact it is ~36KB, which leaves under 2.5KB for
variables and dies with ?OUT OF MEMORY. Crunched it is ~10KB.

So the source stays commented forever and the *build* is stripped. This
tool does that on the compiled .prg, with no dependencies, so anyone can
edit the commented source and produce a runnable build themselves.

What it does:
  - removes REM text (everything from the REM token to end of line)
  - drops lines that become empty, UNLESS something branches to them
  - relinks the line pointers

What it deliberately does not do: renumber. Line numbers stay as they
are, so GOTO/GOSUB targets keep working and the ?ERROR IN nnn you see on
a crunched build still matches the map file from the compiler.

Usage:  crunch.py in.prg out.prg
"""
import sys

T_REM, T_GOTO, T_GOSUB, T_THEN, T_RUN, T_GO = 0x8F, 0x89, 0x8D, 0xA7, 0x8A, 0xCB
BRANCH = (T_GOTO, T_GOSUB, T_THEN, T_RUN, T_GO)


def parse(data):
    """[(line_number, token_bytes)] from the body of a .prg."""
    out, i = [], 0
    while i + 1 < len(data):
        nxt = data[i] | (data[i + 1] << 8)
        if nxt == 0:
            break
        num = data[i + 2] | (data[i + 3] << 8)
        j = i + 4
        while j < len(data) and data[j] != 0:
            j += 1
        out.append((num, data[i + 4:j]))
        i = j + 1
    return out


def referenced(lines):
    """Line numbers something branches to. Quoted text is skipped, so a
    string containing digits can never be mistaken for a target."""
    refs, in_str, armed, digits = set(), False, False, ""
    for _, toks in lines:
        in_str = False
        armed = False
        digits = ""
        for b in toks:
            if b == 0x22:                      # quote
                in_str = not in_str
                continue
            if in_str:
                continue
            if 0x30 <= b <= 0x39 and armed:    # digit while armed
                digits += chr(b)
                continue
            if digits:
                refs.add(int(digits))
                digits = ""
            if b in BRANCH:
                armed = True
            elif b in (0x2C, 0x20):            # comma / space keep it armed
                pass
            else:
                armed = False
        if digits:
            refs.add(int(digits))
    return refs


def strip_rem(toks):
    """Drop the REM and everything after it, plus a trailing ':' separator."""
    in_str = False
    for i, b in enumerate(toks):
        if b == 0x22:
            in_str = not in_str
        elif b == T_REM and not in_str:
            out = toks[:i]
            while out and out[-1] in (0x20, 0x3A):   # trailing space/colon
                out = out[:-1]
            return out
    return toks


def crunch(src, dst):
    raw = open(src, "rb").read()
    load = raw[0] | (raw[1] << 8)
    lines = parse(raw[2:])
    keep_nums = referenced(lines)

    out, dropped = [], 0
    for num, toks in lines:
        toks = strip_rem(toks)
        if not toks and num not in keep_nums:
            dropped += 1
            continue
        out.append((num, toks))

    body, addr = bytearray(), load
    for num, toks in out:
        nxt = addr + 4 + len(toks) + 1
        body += bytes([nxt & 0xFF, nxt >> 8, num & 0xFF, num >> 8]) + bytes(toks) + b"\x00"
        addr = nxt
    body += b"\x00\x00"
    open(dst, "wb").write(bytes([load & 0xFF, load >> 8]) + body)

    print("%s: %d bytes, %d lines" % (src, len(raw), len(lines)))
    print("%s: %d bytes, %d lines  (%d comment-only lines dropped, %d kept as branch targets)"
          % (dst, len(body) + 2, len(out), dropped, len(keep_nums & {n for n, t in out if not t})))
    print("saved %d bytes" % (len(raw) - len(body) - 2))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    crunch(sys.argv[1], sys.argv[2])
