#!/usr/bin/env python3
"""
v2.3.5d: do not lose the first start bit of the radio's reply.

Real-hardware result (speed/reports/2026-10-10-s3.1): at 2400 baud the
receiver now works, except that every reply's FIRST start bit is missed,
which turns 3E 42 00 05 into 12 01 05 (two framing errors) and the frame
is lost. A missed first start edge reproduces that output bit for bit.

Cause: the radio answers within a fraction of a bit of our last stop bit
-- an ESP32 UART decodes our last byte at the MIDDLE of the stop bit -- and
we were deaf for that: sendfr kept the receiver off for the whole frame,
txwait read (and so cleared) the ICR every ~10 cycles, and the exit did
`lda C2ICR` which discards a FLAG latch before re-arming.

Fix, touching only the LAST stop bit of a frame (the ICR-polled timing of
every other bit is hardware-proven):
  * at the start of that stop bit, clear the ICR once and arm FLAG;
  * wait out the stop bit by watching timer A's counter (no ICR reads);
  * sendfr's exit no longer clears or re-arms anything.
An edge that arrives during the stop bit now takes the NMI at once, with
exact timing.
"""
import io, sys

SRC_FILE = sys.argv[1] if len(sys.argv) > 1 else "mlfull.py"
KFILE = sys.argv[2] if len(sys.argv) > 2 else "mkkernal.py"
s = io.open(SRC_FILE, encoding="utf-8").read()


def rep(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, "anchor found %d times, wanted %d: %r" % (n, count, old[:70])
    s = s.replace(old, new)


rep('banner: .text "meshcore 64  v2.3.4d"', 'banner: .text "meshcore 64  v2.3.5d"')
rep('''    "NMIEN":   0xCF08,''', '''    "NMIEN":   0xCF08,
    "TXW":     0xCFFD,   # last timer-A high byte seen by txwaitc
    "TXLST":   0xCFFE,   # nonzero while the LAST byte of a frame is going out''')

# the last stop bit: arm the receiver, then wait without touching the ICR
rep('''        lda C2PRA
        ora #4              ; stop bit: high
        sta C2PRA
        jsr txwait
        rts
''', '''        lda C2PRA
        ora #4              ; stop bit: high
        sta C2PRA
        lda TXLST
        bne txlast
        jsr txwait
        rts
; **The last stop bit of a frame is where the radio's reply can begin.** It
; decodes our final byte at the middle of that stop bit and can answer
; within a fraction of a bit. A receiver that is still off, or that reads
; (and so clears) the ICR, loses the first start bit of the reply -- the
; whole first frame with it. So arm FLAG now and wait by watching timer A's
; counter, which has no side effects.
txlast: lda #127
        sta C2ICR
        lda C2ICR           ; nothing real can be here yet: clear the stale
        lda #16
        sta NMIEN
        lda #144
        sta C2ICR           ; FLAG on: a start edge now takes the NMI itself
txwaitc: lda C2TAHI
        sta TXW
txwcl:  lda C2TAHI
        cmp TXW
        beq txwcl           ; unchanged: still counting within this byte
        bcs txwcd           ; went UP = the timer reloaded = underflow
        sta TXW             ; went down, as expected; keep watching
        jmp txwcl
txwcd:  rts
''')

rep('''sendfr: sei
        lda #127
        sta C2ICR           ; receiver off for the duration: half duplex,''',
    '''sendfr: sei
        lda #0
        sta TXLST
        lda #127
        sta C2ICR           ; receiver off for the duration: half duplex,''')

rep('''        tay
        lda TXBUF,y
        jsr txbyte
        inc SFY
        jmp sfl
sfd:    lda #0
        sta C2CRA           ; stop the bit clock
        sta STATE           ; nothing was listening; start clean
        cli
        lda #127
        sta C2ICR
        lda C2ICR
        lda #16
        sta NMIEN
        lda #144
        sta C2ICR
        rts''', '''        tay
        iny
        cpy TXLEN
        bne sfn
        pha
        lda #1
        sta TXLST           ; this is the last byte: its stop bit arms the receiver
        pla
sfn:    dey
        lda TXBUF,y
        jsr txbyte
        inc SFY
        jmp sfl
; the receiver was armed inside the last stop bit, and may already be in
; the middle of the reply: do NOT clear or re-arm anything here.
sfd:    lda #0
        sta C2CRA           ; stop the bit clock
        sta STATE           ; the foreground parser starts clean
        sta TXLST
        cli
        rts''')

io.open(SRC_FILE, "w", encoding="utf-8").write(s)

k = io.open(KFILE, encoding="utf-8").read()
for old, new in (('banner: .text "meshcore 64  v2.3.4d"', 'banner: .text "meshcore 64  v2.3.5d"'),
                 ("'banner: .text \"meshcore 64  v2.3.4\"'", "'banner: .text \"meshcore 64  v2.3.5\"'")):
    assert k.count(old) == 1, old
    k = k.replace(old, new)
io.open(KFILE, "w", encoding="utf-8").write(k)
print("patched", SRC_FILE, KFILE)
