#!/usr/bin/env python3
"""
MeshCore 64 -- pure machine-language client (EXPERIMENT).

Why this exists
---------------
The BASIC client tops out at 600 baud. The 22 Sep 2026 link tests showed
1200 losing 10-33 of 55 messages with 4-8 frames rejected as corrupt,
while the TRANSMIT path stayed byte-perfect at every rate including 2400.
Only receive fails.

That leaves two candidate causes, and they call for different fixes:

  A. The KERNAL mis-samples bits at 1200. The receiver bit-bangs RS-232 in
     an NMI, guessing where each bit centre falls; at 1200 a bit is 0.83ms
     instead of 1.67ms. If this is it, no amount of client speed helps and
     the only fix is replacing the receiver outright (UP9600-style).

  B. The KERNAL's 256-byte receive buffer OVERRUNS because the client is
     too slow to drain it. At 1200 that buffer fills in ~2.1s. A BASIC
     mainLoop pass that renders a message, scrolls the screen and runs an
     REU DMA can plausibly take that long. An overrun does not merely lose
     bytes -- it desyncs the frame parser, which then locks onto a '>'
     inside payload data and hands the client garbage. That is exactly the
     signature the rj counter was picking up.

This client removes BASIC entirely so that B can be tested in isolation.
It is deliberately NOT feature-complete: no channel picker, no REU
scrollback, no send-from-keyboard. It does the load-bearing receive path --
handshake, sync loop, display -- because that is what the baud question
turns on. If it fixes 1200, the rewrite is worth finishing. If it does
not, cause A is proven and the answer is "600 forever, short of new
hardware".

Build:  python3 mlclient.py   ->  mlclient.prg
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from asm import assemble

ORG = 0x0801
OUT = os.path.join(HERE, "mlclient.prg")

EQU = {
    # ---- KERNAL ----
    "CHROUT":  0xFFD2,
    "CHKOUT":  0xFFC9,
    "CLRCHN":  0xFFCC,
    "SETNAM":  0xFFBD,
    "SETLFS":  0xFFBA,
    "OPEN":    0xFFC0,
    "CHKIN":   0xFFC6,
    "CLOSE":   0xFFC3,
    "SCNKEY":  0xFF9F,
    "GETIN":   0xFFE4,
    # ---- KERNAL RS-232 state ----
    "RIBUF":   0x00F7,   # pointer to the 256-byte receive buffer
    "RIDBE":   0x029B,   # write index (filled by the NMI)
    "RIDBS":   0x029C,   # read index  (ours to advance)
    "JIFFY":   0x00A2,   # low byte of the jiffy clock
    # ---- our pointers (free zero page with BASIC out of the way) ----
    "PTR":     0x00FB,
    "PTRH":    0x00FC,
    # ---- buffers ----
    "TXBUF":   0xCB00,   # payload we are sending
    "SBUF":    0xCC00,   # scratch
    "CBUF":    0xCD00,   # payload, ascii->petscii converted
    "BUF":     0xCE00,   # payload, RAW
    # ---- state ----
    "STATE":   0xCF00,
    "FLEN":    0xCF01,
    "FIDX":    0xCF02,
    "READY":   0xCF03,
    "NFRM":    0xCF04,
    "CLEN":    0xCF07,
    "HSTAGE":  0xCF10,
    "RJ":      0xCF11,
    "MSGS":    0xCF12,
    "MSGSH":   0xCF1C,  # high byte: load tests run past 255
    "STGBIT":  0xCF1D,
    "SAW5":    0xCF1E,  # frames seen with opcode 5  # which handshake stage we are on, as a bit
    "TICK":    0xCF13,
    "TOL":     0xCF14,   # timeout counter lo
    "TOH":     0xCF15,   # timeout counter hi
    "WANT":    0xCF16,   # opcode waitop is waiting for
    "TXLEN":   0xCF17,
    "OVR":     0xCF18,   # receive-buffer high-water mark
    "LASTJ":   0xCF19,   # last jiffy seen, for wrap detection
    "WJ":      0xCF1A,   # same, private to waitop
    "OPENST":  0xCF1B,   # what OPEN returned
    # ---- kernal rs-232 diagnostics ----
    "RSSTAT":  0x0297,   # bit1 framing, bit2 overrun, bit3 empty,
                         # bit4 cts missing, bit6 dsr missing
    "M51CTR":  0x0293,   # control register the kernal actually stored
    "M51CDR":  0x0294,   # command register
    "CI2DDRB": 0xDD03,
    "CI2ICR":  0xDD0D
}

SRC = r"""
; ===== BASIC stub: 10 SYS2061 ==========================================
        .byte 11,8,10,0,158,50,48,54,49,0,0,0

; ===== entry ($080D = 2061) ============================================
main:   lda #147            ; clear screen
        jsr CHROUT
        lda #14             ; switch to lower case
        jsr CHROUT
        lda #<banner
        sta PTR
        lda #>banner
        sta PTRH
        jsr prtstr

        ; zero our state
        lda #0
        sta STATE
        sta READY
        sta NFRM
        sta HSTAGE
        sta RJ
        sta MSGS
        sta TICK
        sta OVR
        sta MSGSH
        sta STGBIT
        sta SAW5
        sta FIDX

        jsr openser

        ; the kernal's rs-232 receiver needs a moment after OPEN before
        ; its nmi timing is trustworthy -- same ~2s settle the basic
        ; client uses, for the same reason.
        lda #<msgarm
        sta PTR
        lda #>msgarm
        sta PTRH
        jsr prtstr
        ldx #120
armw:   jsr wait1
        dex
        bne armw

        lda #<msgcon
        sta PTR
        lda #>msgcon
        sta PTRH
        jsr prtstr

        jsr handshk

; ===== main loop =======================================================
; The whole point: this gets back to poll far more often than a BASIC
; mainLoop pass ever could.
loop:   jsr poll
        jsr chktik
        lda READY
        beq loop
        jsr dispat
        lda #0
        sta READY
        jmp loop

; ===== periodic report =================================================
; Driven by the jiffy clock, NOT by frames arriving -- at 2400 nothing
; arrives at all and that is precisely the run we need numbers from.
; JIFFY is the low byte of the clock, so it wraps every 256 jiffies
; (~4.3s); three wraps is a report roughly every 13 seconds.
chktik: lda JIFFY
        cmp LASTJ
        bcs ctnew
        inc TICK
        lda TICK
        cmp #3
        bcc ctnew
        lda #0
        sta TICK
        jsr report
ctnew:  lda JIFFY
        sta LASTJ
        rts

; ===== rs-232 open =====================================================
; equivalent of  OPEN 2,2,3,CHR$(7)
openser:
        lda #1              ; filename length 1
        ldx #<ctrlb
        ldy #>ctrlb
        jsr SETNAM
        lda #2              ; logical file 2
        ldx #2              ; device 2 = rs-232
        ldy #3              ; secondary 3
        jsr SETLFS
        lda #0
        sta OPENST
        jsr OPEN
        bcc opok
        sta OPENST          ; carry set: A holds the kernal error code
opok:
; **OPEN alone does not arm the receiver.** The kernal enables the CIA2
; FLAG NMI -- the thing that spots an incoming start bit -- inside CHKIN,
; not inside OPEN. Without this the port is configured, M51CTR holds the
; right baud rate, DDRB is set for RTS/DTR, and not one byte ever arrives:
; RIDBE and RIDBS both sit at 0 forever. CLRCHN afterwards only restores
; default I/O, it does not disarm the receiver.
        ldx #2
        jsr CHKIN
        jsr CLRCHN
        rts

; ===== wait one jiffy ==================================================
wait1:  lda JIFFY
w1l:    cmp JIFFY
        beq w1l
        rts

; ===== print null-terminated string at PTR =============================
prtstr: ldy #0
psl:    lda (PTR),y
        beq psd
        jsr CHROUT
        iny
        bne psl
psd:    rts

; ===== send a frame ====================================================
; payload in TXBUF, length in TXLEN. Wraps it as '<' len_lo len_hi body.
sendfr: ldx #2
        jsr CHKOUT
        lda #60             ; '<'
        jsr CHROUT
        lda TXLEN
        jsr CHROUT
        lda #0              ; high byte: frames are always < 256
        jsr CHROUT
        ldy #0
sfl:    cpy TXLEN
        bcs sfd
        lda TXBUF,y
        jsr CHROUT
        iny
        jmp sfl
sfd:    jsr CLRCHN
        rts

; ===== copy a fixed payload into TXBUF =================================
; source in PTR, length in A
setpay: sta TXLEN
        ldy #0
cpl:    cpy TXLEN
        bcs cpd
        lda (PTR),y
        sta TXBUF,y
        iny
        jmp cpl
cpd:    rts

; ===== handshake =======================================================
; Same four commands, in the same order, as the BASIC client. app_start
; first because that is what the reference meshcore_py client sends;
; device_query after it because that is what gates the v3 (opcode 17)
; channel-message format we parse.
handshk:
; **Discard anything received before we introduced ourselves.**
; We open the port mid-stream, so the first bytes in the buffer are the tail
; of whatever the radio was already transmitting. The parser locks onto a
; '>' inside that debris and is out of step for a frame or two -- exactly
; long enough to swallow the app_start reply. Symptom: handshake bit 1 never
; sets while bits 2/4/8 all do.
        lda RIDBE
        sta RIDBS
        lda #0
        sta STATE
        sta READY
; Flushing the BUFFER is not enough: the radio can be mid-frame on the
; WIRE, so the next bytes in are the tail of a frame we never saw the start
; of. The parser then locks onto a '>' inside that tail and stays out of
; step long enough to swallow the app_start reply -- which showed up as
; "zero opcode-5 frames ever assembled" while later stages matched fine.
; So spend a second resyncing on real frame boundaries, discarding whatever
; turns up, before we say anything we expect an answer to.
        ldx #60
rsyncw: jsr poll
        lda #0
        sta READY
        jsr wait1
        dex
        bne rsyncw
        lda #0
        sta STATE
        sta READY
        lda #<pyastart
        sta PTR
        lda #>pyastart
        sta PTRH
        lda #11
        jsr setpay
        jsr sendfr
        lda #1
        sta STGBIT
        lda #5              ; resp_code_self_info
        jsr waitop

        lda #<pyquery
        sta PTR
        lda #>pyquery
        sta PTRH
        lda #2
        jsr setpay
        jsr sendfr
        lda #2
        sta STGBIT
        lda #13             ; resp_code_device_info
        jsr waitop

        lda #<pychan
        sta PTR
        lda #>pychan
        sta PTRH
        lda #2
        jsr setpay
        jsr sendfr
        lda #4
        sta STGBIT
        lda #18             ; resp_code_channel_info
        jsr waitop

        lda #<pytime
        sta PTR
        lda #>pytime
        sta PTRH
        lda #1
        jsr setpay
        jsr sendfr
        lda #8
        sta STGBIT
        lda #9              ; resp_code_curr_time
        jsr waitop

        lda #<msgrdy
        sta PTR
        lda #>msgrdy
        sta PTRH
        jsr prtstr
        jsr sync            ; kick off the drain
        rts

; ===== wait for opcode A, dispatching anything else =====================
; Times out rather than hanging, so an automated run always terminates
; with something to report instead of a frozen screen.
waitop: sta WANT
        lda #0
        sta TOL
        lda JIFFY
        sta WJ
wol:    jsr poll
        lda READY
        bne wogot
        lda JIFFY
        cmp WJ
        bcs wonew
        inc TOL
        lda TOL
        cmp #7              ; ~30s, then give up on this stage
        bcs wotmo
wonew:  lda JIFFY
        sta WJ
        jmp wol
wotmo:  rts                 ; HSTAGE deliberately NOT advanced
wogot:  lda BUF
        cmp WANT
        beq wohit
        jsr dispat
        lda #0
        sta READY
        jmp wol
wohit:  lda HSTAGE
        ora STGBIT
        sta HSTAGE
        jsr dispat
        lda #0
        sta READY
        rts

; ===== dispatch a completed frame ======================================
dispat: lda BUF
; count self_info sightings. handshake bit 1 never sets while 2/4/8 do, and
; this separates "the frame never arrived intact" from "our matching logic
; is wrong" -- which are different bugs with different fixes.
        cmp #5
        bne dn5
        inc SAW5
dn5:    lda BUF
        cmp #17
        beq dmsg
        cmp #131            ; push_code_msg_waiting
        beq dwait
        rts
dwait:  jmp sync
dmsg:
; --- the same three plausibility tests the basic client uses ---
; a desynced parser hands us a frame built from random bytes; if byte 0
; happens to be 17 it lands here. channel index above 39 cannot be real,
; a channel message always has at least one byte of text after its
; 11-byte header, and txt_type is only ever 0/1/2.
        lda BUF+4
        cmp #40
        bcs dbad
        lda FLEN
        cmp #12
        bcc dbad
        lda BUF+6
        cmp #3
        bcs dbad
        inc MSGS
        bne dmnc
        inc MSGSH
dmnc:   jsr shomsg
        jmp sync
dbad:   inc RJ
        jmp sync

; ===== show the message text ===========================================
shomsg: ldx #11
sml:    cpx CLEN
        bcs smd
        lda CBUF,x
        jsr CHROUT
        inx
        jmp sml
smd:    lda #13
        jsr CHROUT
        rts

; ===== ask for the next queued message =================================
sync:   lda #10
        sta TXBUF
        lda #1
        sta TXLEN
        jsr sendfr
        rts

; ===== report counters over the link ===================================
; Sent as a channel message so the fake radio logs it, exactly like the
; BASIC test build does. Hex, because a decimal routine is not worth the
; bytes here and the log is read by machine anyway.
report: lda #3              ; cmd_send_channel_txt_msg
        sta TXBUF
        lda #0
        sta TXBUF+1         ; txt_type plain
        sta TXBUF+2         ; channel 0
        sta TXBUF+3
        sta TXBUF+4
        sta TXBUF+5
        sta TXBUF+6         ; timestamp: zeros are fine for a test
        ldx #7
        lda #110            ; 'n'
        sta TXBUF,x
        inx
        lda NFRM
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #114            ; 'r'
        sta TXBUF,x
        inx
        lda RJ
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #109            ; 'm'
        sta TXBUF,x
        inx
        lda MSGSH
        jsr apphex
        lda MSGS
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #104            ; 'h'
        sta TXBUF,x
        inx
        lda HSTAGE
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #111            ; 'o'
        sta TXBUF,x
        inx
        lda OVR
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #115            ; 's' = rsstat
        sta TXBUF,x
        inx
        lda RSSTAT
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #101            ; 'e' = ridbe
        sta TXBUF,x
        inx
        lda RIDBE
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #98             ; 'b' = ridbs
        sta TXBUF,x
        inx
        lda RIDBS
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #99             ; 'c' = m51ctr
        sta TXBUF,x
        inx
        lda M51CTR
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #100            ; 'd' = cia2 ddrb
        sta TXBUF,x
        inx
        lda CI2DDRB
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #112            ; 'p' = open status
        sta TXBUF,x
        inx
        lda OPENST
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #102            ; 'f' = opcode-5 frames seen
        sta TXBUF,x
        inx
        lda SAW5
        jsr apphex
        stx TXLEN
        jsr sendfr
        rts

; append A to TXBUF,x as two ascii hex digits
apphex: pha
        lsr
        lsr
        lsr
        lsr
        jsr hexdig
        sta TXBUF,x
        inx
        pla
        and #15
        jsr hexdig
        sta TXBUF,x
        inx
        rts
hexdig: cmp #10
        bcc hd0
        clc
        adc #55
        rts
hd0:    clc
        adc #48
        rts

; =======================================================================
; Frame assembly -- same state machine as the BASIC client's $C000
; routine, which is proven. Drains the KERNAL buffer and reassembles
; '>' + len_lo + len_hi + payload.
; =======================================================================
poll:   lda READY
        bne pdone

; --- track how full the kernal buffer got. this is the whole experiment:
; --- if OVR climbs toward 255 the buffer is overrunning and the parser is
; --- desyncing; if it stays low, bytes are being lost or mis-sampled
; --- somewhere we cannot see from here.
        lda RIDBE
        sec
        sbc RIDBS
        cmp OVR
        bcc pnohw
        sta OVR
pnohw:

ploop:  ldy RIDBS
        cpy RIDBE
        beq pdone
        lda (RIBUF),y
        inc RIDBS

        ldx STATE
        beq pidle
        dex
        beq plo
        dex
        beq phi
        ldx FIDX
        sta BUF,x
        inc FIDX
        inx
        cpx FLEN
        bcc ploop
        jsr conv
        lda #1
        sta READY
        inc NFRM
        lda #0
        sta STATE
        beq pdone

pidle:  cmp #62             ; '>'
        bne ploop
        lda #1
        sta STATE
        bne ploop

plo:    sta FLEN
        lda #2
        sta STATE
        bne ploop

phi:    cmp #0
        bne pbad
        lda FLEN
        beq pbad
        cmp #177
        bcs pbad
        lda #0
        sta FIDX
        lda #3
        sta STATE
        bne ploop

pbad:   lda #0
        sta STATE
        beq ploop

pdone:  rts

; ===== ascii -> petscii, BUF -> CBUF ===================================
; strictly 1:1 -- collapsing utf-8 here shifts every later offset and
; corrupts text that follows any binary field containing $e2.
conv:   ldx #0
        ldy #0
cvl:    cpx FLEN
        bcs cvdone
        lda BUF,x
        beq cvst
        cmp #9
        beq cvspc
        cmp #10
        beq cvspc
        cmp #13
        beq cvspc
        cmp #32
        bcc cvdot
        cmp #127
        bcs cvdot
        cmp #65
        bcc cvst
        cmp #91
        bcc cvup
        cmp #97
        bcc cvst
        cmp #123
        bcs cvst
        and #223
        bne cvst
cvup:   ora #128
        bne cvst
cvspc:  lda #32
        bne cvst
cvdot:  lda #46
cvst:   sta CBUF,y
        inx
        iny
        jmp cvl
cvdone: sty CLEN
        rts

; ===== data ============================================================
ctrlb:  .byte 7             ; 600 baud, patched by the build for other rates
pyastart: .byte 1,0,0,0,0,0,0,0,67,54,52
pyquery:  .byte 22,3
pychan:   .byte 31,0
pytime:   .byte 5
banner: .text "meshcore 64 - pure ml build"
        .byte 13,0
msgarm: .text "arming rs-232..."
        .byte 13,0
msgcon: .text "connecting..."
        .byte 13,0
msgrdy: .text "connected."
        .byte 13,13,0
"""


def build(ctrl=7, out=OUT):
    code, syms = assemble(SRC, ORG, EQU)
    # patch the baud control byte in place
    off = syms["ctrlb"] - ORG
    code = bytearray(code)
    code[off] = ctrl
    prg = bytes([ORG & 0xFF, ORG >> 8]) + bytes(code)
    with open(out, "wb") as f:
        f.write(prg)
    return code, syms, prg


if __name__ == "__main__":
    ctrl = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    out = sys.argv[2] if len(sys.argv) > 2 else OUT
    code, syms, prg = build(ctrl, out)
    print("; assembled %d bytes at $%04X (ctrl byte %d)" % (len(code), ORG, ctrl))
    for n in ("main", "loop", "handshk", "waitop", "dispat", "poll", "conv",
              "report", "sendfr", "ctrlb"):
        print(";   %-8s = $%04X" % (n, syms[n]))
    print("; wrote %s (%d bytes)" % (out, len(prg)))
