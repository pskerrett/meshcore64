#!/usr/bin/env python3
"""
v2.3.4d: the bit-banged receiver masks ICR by the sources it has enabled.

Root cause of "our receiver never works on real hardware" (see
c64-0.9/path to higher speeds.md, s1.1/s1.2): on a real 6526 the ICR data
bits LATCH whether or not that source is enabled in the mask. FLAG is wired
to RXD, so every falling edge INSIDE a data byte sets ICR bit 4 even while
only Timer B is enabled. nmih read the ICR and tested FLAG first without
masking, so a Timer-B sample interrupt that followed a 1->0 data transition
looked like a new start bit and restarted the byte. VICE raises FLAG once
per byte (rsuser.c), so it can never show this.

The KERNAL does it right: $FE73 is AND $02A1 (ENABL). NMIEN is our ENABL.

Also: timers are loaded with N-1 (a CIA counts N..0 = N+1 cycles).
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


rep('banner: .text "meshcore 64  v2.3.3d"', 'banner: .text "meshcore 64  v2.3.4d"')

rep('''    "TXB":     0xCF26,''',
    '''    "TXB":     0xCF26,
    "NMIEN":   0xCF08,   # CIA2 NMI sources currently enabled (mirror of the mask)''')

# serini: FLAG is the only source enabled at idle
rep('''        lda #144            ; enable FLAG: the start-bit edge
        sta C2ICR
        cli
        rts''',
    '''        lda #16
        sta NMIEN           ; what the handler will believe is enabled
        lda #144            ; enable FLAG: the start-bit edge
        sta C2ICR
        cli
        rts''')

# the fix itself: ignore latched-but-disabled sources, like KERNAL $FE73
rep('''        lda C2ICR           ; read = acknowledge
        sta ICRSV
        and #16             ; FLAG?''',
    '''        lda C2ICR           ; read = acknowledge
; **Mask by what is ENABLED.** The 6526 latches every source's flag whether
; or not it is enabled, and FLAG follows RXD, so each falling data edge sets
; bit 4 while we only want Timer B. The KERNAL does this at $FE73
; (AND ENABL). Without it a sample tick that follows a 1->0 data bit looks
; like a start bit and the byte restarts: all-zero garbage on real silicon,
; perfect in VICE (which pulses FLAG once per byte).
        and NMIEN
        sta ICRSV
        and #16             ; FLAG?''')

# start bit seen: now Timer B only
rep('''        lda #130            ; now interrupt on timer B instead
        sta C2ICR
''',
    '''        lda #130            ; now interrupt on timer B instead
        sta C2ICR
        lda #2
        sta NMIEN
''')

# byte complete: back to FLAG only
rep('''        lda #127
        sta C2ICR
        lda C2ICR
        lda #144
        sta C2ICR
nmx:''',
    '''        lda #127
        sta C2ICR
        lda C2ICR
        lda #16
        sta NMIEN
        lda #144
        sta C2ICR
nmx:''')

# transmit: receiver off
rep('''        sta C2ICR           ; receiver off for the duration: half duplex,
                            ; which is what this protocol actually is''',
    '''        sta C2ICR           ; receiver off for the duration: half duplex,
                            ; which is what this protocol actually is
        lda #0
        sta NMIEN''')

# transmit done: receiver back on
rep('''        lda C2ICR
        lda #144
        sta C2ICR
        rts
SFY:''',
    '''        lda C2ICR
        lda #16
        sta NMIEN
        lda #144
        sta C2ICR
        rts
SFY:''')

# timers count N..0, which is N+1 cycles
rep('''    vals = [("btlo", bit & 0xFF), ("bthi", bit >> 8),''',
    '''    vals = [("btlo", (bit - 1) & 0xFF), ("bthi", (bit - 1) >> 8),''')
rep('''    for i, v in enumerate([bit & 0xFF, bit >> 8, half & 0xFF, half >> 8,
                           nbit & 0xFF, nbit >> 8, nhalf & 0xFF, nhalf >> 8]):''',
    '''    for i, v in enumerate([(bit - 1) & 0xFF, (bit - 1) >> 8, half & 0xFF, half >> 8,
                           (nbit - 1) & 0xFF, (nbit - 1) >> 8, nhalf & 0xFF, nhalf >> 8]):''')

io.open(SRC_FILE, "w", encoding="utf-8").write(s)

# the KERNAL build maps the driver banner to the plain one
k = io.open(KFILE, encoding="utf-8").read()
for old, new in (('banner: .text "meshcore 64  v2.3.3d"', 'banner: .text "meshcore 64  v2.3.4d"'),
                 ("'banner: .text \"meshcore 64  v2.3.3\"'", "'banner: .text \"meshcore 64  v2.3.4\"'")):
    assert k.count(old) == 1, old
    k = k.replace(old, new)
io.open(KFILE, "w", encoding="utf-8").write(k)
print("patched", SRC_FILE, KFILE)
