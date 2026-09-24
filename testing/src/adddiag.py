#!/usr/bin/env python3
"""
Add the two counters that split a dead link three ways, to any variant.

F3 gains  n<NN> b<NN>:
  n  start bits seen on the FLAG line -- the radio's line physically
     moving, counted before any decoding
  b  bytes that made it into the receive ring

  n00 b00   nothing is arriving electrically. Not a timing problem.
  n>0 b00   edges arrive, no byte assembles. Sampling is wrong.
  n>0 b>0   bytes arrive. If frames stay 00 they are arriving garbled.

Both saturate at 255 rather than wrapping: the handler runs once per BIT,
so a plain counter wraps many times over and tells you nothing. Counting
start bits only is one per byte, and is the number that matters.
"""
import io, sys


def patch(src, dst):
    s = io.open(src, encoding="utf-8").read()

    s = s.replace('    "LEDLST":  0xCFF9,',
                  '    "LEDLST":  0xCFF9,\n'
                  '    "NMIC":    0xCFFB,   # DIAGNOSTIC: start bits seen\n'
                  '    "RXC":     0xCFFC,   # DIAGNOSTIC: bytes received')

    old = "; --- start bit seen ---\n        lda hblo"
    assert s.count(old) == 1, "start bit branch"
    s = s.replace(old, """; --- start bit seen ---
        lda NMIC            ; DIAGNOSTIC, saturating
        cmp #255
        beq nmnos
        inc NMIC
nmnos:  lda hblo""")

    old = """        lda RBUF,y
        inc RTAIL"""
    assert s.count(old) == 1, "ring drain"
    s = s.replace(old, """        lda RBUF,y
        inc RTAIL
        pha                 ; DIAGNOSTIC, saturating
        lda RXC
        cmp #255
        beq nmnob
        inc RXC
nmnob:  pla""")

    old = """        lda OVR
        jsr hexout
        jsr shoprm
        rts"""
    assert s.count(old) == 1, "status line"
    s = s.replace(old, """        lda OVR
        jsr hexout
        lda #32
        jsr CHROUT
        lda #110            ; 'n' = start bits seen on the flag line
        jsr CHROUT
        lda NMIC
        jsr hexout
        lda #32
        jsr CHROUT
        lda #98             ; 'b' = bytes into the ring
        jsr CHROUT
        lda RXC
        jsr hexout
        jsr shoprm
        rts""")

    io.open(dst, "w", encoding="utf-8").write(s)
    print("wrote %s" % dst)


if __name__ == "__main__":
    patch(sys.argv[1], sys.argv[2])
