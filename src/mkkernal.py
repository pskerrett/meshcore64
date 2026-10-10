#!/usr/bin/env python3
"""
Turn mlfull.py into the PURE KERNAL build: no bit-banged RS-232 at all.

Our own driver transmits correctly on real hardware but will not receive
(see ftproot/archive/NOTES.md). The KERNAL's RS-232 is proven on this
cartridge -- v1.2d shipped on it -- so this build hands the whole serial
layer back to it and keeps every feature above that line untouched.

600 baud only. The KERNAL cannot do better on a C64, and the whole reason
for writing our own driver was to go faster; without it there is no
reason to offer another rate.
"""
import io, sys


def patch(src, dst):
    s = io.open(src, encoding="utf-8").read()

    # ---- zero page: give the kernal its rs232 buffers back ----
    # $f7-$fa ARE RIBUF and ROBUF. The client only ever had them because
    # it replaced the kernal's rs232; it does not any more.
    s = s.replace('    "PTR2":    0x00F7,', '    "PTR2":    0x0022,')
    s = s.replace('    "PTR2H":   0x00F8,', '    "PTR2H":   0x0023,')
    s = s.replace('    "MNPTR":   0x00F9,   # -> table of string pointers; MUST be zero page',
                  '    "MNPTR":   0x0024,   # -> table of string pointers; MUST be zero page')
    s = s.replace('    "MNPTRH":  0x00FA,', '    "MNPTRH":  0x0025,')

    s = s.replace('    "CHROUT":  0xFFD2,', '''    "CHROUT":  0xFFD2,
    "SETLFS":  0xFFBA,
    "SETNAM":  0xFFBD,
    "KOPEN":   0xFFC0,
    "CHKIN":   0xFFC6,
    "CHKOUT":  0xFFC9,
    "CLRCHN":  0xFFCC,
    "RIBUF":   0x00F7,   # -> kernal rs232 receive buffer
    "RIDBE":   0x029B,   # write index
    "RIDBS":   0x029C,   # read index''')

    # ---- serini -> the kernal's own OPEN ----
    start = s.index("serini: sei")
    end = s.index("; ===== ", start)
    s = s[:start] + '''serini:
; The kernal's rs232, opened exactly as v1.2d opens it -- that build is
; proven on this cartridge and there is no reason to differ from it.
        lda #2              ; logical file 2
        ldx #2              ; device 2 = rs232
        ldy #3              ; secondary 3, as v1.2d uses
        jsr SETLFS
        lda #1              ; one control byte as the "filename"
        ldx #<rsctl
        ldy #>rsctl
        jsr SETNAM
        jsr KOPEN
; **OPEN does not arm the receiver. CHKIN does.** Nothing in the manual
; says so and it cost two runs to find.
        ldx #2
        jsr CHKIN
; **Then hand the input channel straight back.** CHKIN arms the receiver
; and CLRCHN does not disarm it -- but while file 2 is the input channel,
; GETIN reads the RADIO instead of the keyboard, so incoming traffic gets
; typed into the input line and every byte that happens to be 13 sends it
; straight back out as a chat message. poll() reads the kernal's buffer
; directly, so nothing needs the channel held open.
        jsr CLRCHN
; **Two seconds before trusting the link.** v1.2d records this as a
; kernal quirk: bytes moved before the nmi engine is armed come out
; corrupted. Skipping it put garbage on the wire.
        ldx #120
srwait: jsr wait1
        dex
        bne srwait
        rts

; m51ctr: low nibble 7 = 600 baud, bits 5-6 clear = 8 data bits, bit 7
; clear = 1 stop bit.
rsctl:  .byte 7

''' + s[end:]

    # ---- receive: drain the kernal's ring ----
    old = """        lda RHEAD
        sec
        sbc RTAIL
        cmp OVR
        bcc pnohw
        sta OVR"""
    assert s.count(old) == 1, "poll high water"
    s = s.replace(old, """        lda RIDBE
        sec
        sbc RIDBS
        cmp OVR
        bcc pnohw
        sta OVR""")

    old = """ploop:  ldy RTAIL
        cpy RHEAD
        beq pdone
        lda RBUF,y
        inc RTAIL"""
    assert s.count(old) == 1, "poll drain"
    s = s.replace(old, """ploop:  lda RIDBS           ; kernal ring: RIDBS reads, RIDBE writes
        cmp RIDBE
        beq pdone
        ldy RIDBS
        lda (RIBUF),y
        inc RIDBS""")

    # ---- delete the bit-banged driver outright ----
    # Once serini and sendfr are replaced nothing calls nmih or txbyte,
    # and no NMI vector points at them, but they were still being
    # assembled in -- about 170 lines of dead weight, which is what
    # pushed this build past the splash bitmap at $4000.
    #
    # "No custom RS232 code" should mean the code is not there. This runs
    # BEFORE the sendfr rewrite below, because that inserts the new sendfr
    # where the old one stood, which is inside the transmit section.
    start = s.index("; ===== the receiver =")
    end = s.index("sendfr: sei")          # keep sendfr; drop txbyte/txwait
    s = s[:start] + s[end:]

    # ---- transmit: CHKOUT and CHROUT ----
    start = s.index("sendfr: sei")
    end = s.index("; ===== ", start)
    s = s[:start] + '''sendfr:
; CHKOUT, then plain CHROUT per byte -- the kernal buffers it and its own
; NMI clocks it out. No timers, no masking the receiver: half duplex was
; our driver's constraint, not the kernal's.
        ldx #2
        jsr CHKOUT
        lda #60             ; '<'
        jsr CHROUT
        lda TXLEN
        jsr CHROUT
        lda #0
        jsr CHROUT
        lda #0
        sta SFY
sfl:    lda SFY
        cmp TXLEN
        bcs sfd
        tay
        lda TXBUF,y
        jsr CHROUT
        inc SFY
        jmp sfl
sfd:    jsr CLRCHN          ; back to screen out, keyboard in
        rts
SFY:    .byte 0

''' + s[end:]

    # ---- the lamps stay OFF at runtime ----
    # Under the kernal PB1 and PB2 are DRIVEN OUTPUTS (RTS/DTR). Every
    # lamp write puts a whole byte into $dd01, and a zero in those bits
    # drives RTS low, which tells the radio to stop sending and kills
    # reception -- recorded twice on this project already.
    #
    # Masking each write with ora #6 keeps them high and ought to be
    # correct, but VICE models RTS/DTR as live handshake lines and
    # throttles the link whenever they are driven: the masked build
    # scored 5 messages against 40. That makes it untestable here, and
    # the configuration ALREADY PROVEN on real hardware -- the kernal
    # build that connected -- had the lamps off. Reproduce that exactly
    # rather than ship something no one has run.
    #
    # The boot sweep is kept: it runs before OPEN, when the pins are
    # still ours. Only the runtime animation goes.
    # The whole animation is unreachable now, so delete it rather than
    # leave ~75 lines of it sitting in the image behind three rts's. The
    # boot sweep is NOT touched: it runs before OPEN, while the pins are
    # still ours.
    start = s.index("ledrx:  lda #0")
    end = s.index("; ===== boot lamp sweep")
    s = s[:start] + """ledrx:  rts
ledtx:  rts
ledstep:
        rts

""" + s[end:]

    # the summary line still named the routines we just deleted
    s = s.replace('for n in ("main", "serini", "nmih", "txbyte", "sendfr", '
                  '"poll", "handshk"):',
                  'for n in ("main", "serini", "sendfr", "poll", "handshk"):')

    # ---- 600 only ----
    s = s.replace("DEFAULT_CTRL = 10               # 2400 baud",
                  "DEFAULT_CTRL = 7                # 600 baud: the kernal's ceiling")
    s = s.replace('sbaud:  .text "link 2400 baud"', 'sbaud:  .text "link 600 baud"')
    old = 'banner: .text "meshcore 64  v2.4b"'
    assert s.count(old) == 1, "banner"
    s = s.replace(old, 'banner: .text "meshcore 64  v2.4b-600k"')

    io.open(dst, "w", encoding="utf-8").write(s)
    print("wrote %s" % dst)


if __name__ == "__main__":
    patch(sys.argv[1], sys.argv[2])
