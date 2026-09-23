#!/usr/bin/env python3
"""
MeshCore 64 -- FULL client in machine language, with our own RS-232.

Why
---
mlclient.py removed BASIC and 1200 was still corrupt, with the receive
buffer never more than 4% full. That pinned the fault on the KERNAL's
receiver rather than on client speed. This replaces the receiver.

What the KERNAL does badly, and what this does instead:

  * **One NMI handler shared between transmit and receive.** The KERNAL
    services Timer A (send) and Timer B (receive) from the same handler,
    so a byte going out disturbs the timing of a byte coming in. Our
    protocol is request/response -- a sync after every single message --
    which is close to the worst case for that. Here, transmit masks the
    receiver for the duration of the frame and restores it afterwards.
    Deliberately half duplex, which is what the protocol actually is.

  * **A bloated per-bit handler.** The KERNAL's NMI does a lot of work on
    every single bit. Latency there becomes sampling error: the receiver
    takes ONE sample per bit at an estimated centre, and the error
    accumulates across all 10 bits of a frame. This handler does the
    minimum and nothing else.

  * **Transmit timing exposed to badline DMA.** Here the bit clock comes
    from CIA2 Timer A, polled. The timer is hardware, so the VIC-II
    stealing cycles cannot stretch a bit.

Hardware (unchanged -- this is all software, no cartridge modification):
  user port PB0 = RXD, and CIA2's FLAG line follows it, so the falling
  edge of a start bit raises an NMI.  PA2 = TXD.

Build:  python3 mlown.py [ctrl] [out.prg] [blank]
        ctrl 7=600  8=1200  10=2400   blank 1 = blank the display
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from asm import assemble

ORG = 0x0801
OUT = os.path.join(HERE, "mlfull.prg")
PAL = 985248                      # x64sc default machine

EQU = {
    "CHROUT":  0xFFD2,
    "GETIN":   0xFFE4,
    "VICCTL":  0xD011,
    "JIFFY":   0x00A2,
    "NMIVEC":  0x0318,
    "PTR":     0x00FB,
    "PTRH":    0x00FC,
    # ---- CIA 2 ----
    "C2PRA":   0xDD00,   # bit 2 = TXD out  (bits 0-1 are the VIC bank!)
    "C2PRB":   0xDD01,   # bit 0 = RXD in
    "C2DDRA":  0xDD02,
    "C2DDRB":  0xDD03,
    "C2TALO":  0xDD04,
    "C2TAHI":  0xDD05,
    "C2TBLO":  0xDD06,
    "C2TBHI":  0xDD07,
    "C2ICR":   0xDD0D,
    "C2CRA":   0xDD0E,
    "C2CRB":   0xDD0F,
    # ---- our receive ring ----
    "RBUF":    0xCA00,
    "TXBUF":   0xCB00,
    "CBUF":    0xCD00,
    "BUF":     0xCE00,
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
    "TICK":    0xCF13,
    "TOL":     0xCF14,
    "WANT":    0xCF16,
    "TXLEN":   0xCF17,
    "OVR":     0xCF18,
    "LASTJ":   0xCF19,
    "WJ":      0xCF1A,
    "MSGSH":   0xCF1C,
    "STGBIT":  0xCF1D,
    # ---- private to the receiver ----
    "RHEAD":   0xCF20,   # written by the NMI
    "RTAIL":   0xCF21,   # advanced by the foreground
    "BITCNT":  0xCF22,
    "SHIFT":   0xCF23,
    "ICRSV":   0xCF24,
    "FRERR":   0xCF25,   # framing errors: stop bit was not high
    "TXB":     0xCF26,
    # ---- channels / ui ----
    "CHNAM":   0xC000,   # 40 channel names, 18 bytes each (720)
    "CUNR":    0xC2D0,   # 40 unread counters
    "PKMAP":   0xC300,   # picker slot -> channel index
    "INBUF":   0xC310,   # the line being typed (petscii, for the screen)
    "INASC":   0xC360,   # the same line in ascii, for the wire
    "PROMPT":  0xC3B0,   # rendered prompt text
    "CC":      0xCF30,   # current channel (255 = All)
    "CO":      0xCF31,   # previous channel
    "INLEN":   0xCF32,
    "PRLEN":   0xCF33,
    "UT":      0xCF34,   # unread on OTHER channels
    "NPICK":   0xCF35,
    "CKED":    0xCF36,   # channel list has been scanned
    "SCANI":   0xCF37,
    "BLANKS":  0xCF38,
    "TMP":     0xCF39,
    "TMP2":    0xCF3A,
    "CF":      0xCF3E,   # full 40-slot sweep
    "OLDT":    0xCF3F,
    "DECBUF":  0xCF3B,
    "SBUF":    0xCC00,   # up to two 40-byte screen-code lines
    # ---- REU controller ----
    "RCMD":    0xDF01,
    "RC64L":   0xDF02,
    "RC64H":   0xDF03,
    "RREUL":   0xDF04,
    "RREUM":   0xDF05,
    "RREUB":   0xDF06,
    "RLENL":   0xDF07,
    "RLENH":   0xDF08,
    "RCTL":    0xDF0A,
    "BORDER":  0xD020,
    "TAPEBUF": 0x033C,
    # ---- archive ----
    "RU":      0xCF40,   # 1 = an REU is present
    "UKL":     0xCF41,   # size in KB, 16-bit
    "UKH":     0xCF42,
    "LSHIFT":  0xCF43,   # log2(lines per region): 7, 8 or 9
    "STRL":    0xCF44,   # region stride, 24-bit
    "STRM":    0xCF45,
    "STRH":    0xCF46,
    "ADRL":    0xCF47,   # computed REU address, 24-bit
    "ADRM":    0xCF48,
    "ADRH":    0xCF49,
    "SLOTL":   0xCF4A,
    "SLOTH":   0xCF4B,
    "REGION":  0xCF4C,
    "SLEN":    0xCF4D,
    "SOFF":    0xCF4E,
    "UB":      0xCF4F,
    "LWL":     0xCF50,   # 9 regions: write pointer, lo/hi
    "LWH":     0xCF60,
    "LFL":     0xCF70,   # 9 regions: fill count, lo/hi
    "LFH":     0xCF80,
    "ZYL":     0xCF90,
    "ZYH":     0xCF91,
    "NLINE":   0xCF92,
    "SD":      0xCF93,   # scrollback depth
    "OLDB":    0xCF94,
    "MAXL":    0xCF95,   # lines per region, 16-bit
    "MAXH":    0xCF96,
    "CNT":     0xCF97,
    "CNT2":    0xCF98,
    "LEDON":   0xCF99,
    "LEDPAT":  0xCF9A,
    "LEDIX":   0xCF9B,
    "LEDJ":    0xCF9C,
    "TKJ":     0xCF9D,
    "TKC":     0xCF9E,
    # ---- non-REU replay ring: 24 messages, 40 bytes each ----
    "HRTX":    0xC400,
    "HRCH":    0xC7C0,   # channel each ring entry arrived on
    "HRH":     0xCFA0,   # write index
    "HRN":     0xCFA1,   # how many are valid
    "HOLD":    0xCFA2,   # index of the oldest entry
    "ISNTSC":  0xCFA3,
    "RAWHI":   0xCFA4,
    "RASTER":  0xD012,
    "VICCTL2": 0xD011,
    "KBUF":    0x0277,   # kernal keyboard buffer
    "KCNT":    0x00C6,   # 3 bytes, byte -> decimal
}

SRC = r"""
        .byte 11,8,10,0,158,50,48,54,49,0,0,0

main:
        lda blankb
        beq noblnk
        lda VICCTL
        and #239
        sta VICCTL
noblnk: lda #147
        jsr CHROUT
        lda #14
        jsr CHROUT
        lda #<banner
        sta PTR
        lda #>banner
        sta PTRH
        jsr prtstr

        lda #0
        sta STATE
        sta READY
        sta NFRM
        sta HSTAGE
        sta RJ
        sta MSGS
        sta MSGSH
        sta STGBIT
        sta TICK
        sta OVR
        sta FIDX
        sta RHEAD
        sta RTAIL
        sta FRERR

; **Zero everything before it is read.** cc came up as 255 ("All"), the
; archive fill counts as $ffff, and the lamp animation stepped a garbage
; table index -- all because this page is just RAM at power-on.
        lda #0
        ldx #0
zst:    sta STATE,x
        inx
        bne zst
        ldx #0
zch:    sta CHNAM,x
        sta CHNAM+256,x
        sta CHNAM+512,x
        inx
        bne zch
        ldx #0
zcu:    sta CUNR,x
        inx
        cpx #40
        bcc zcu
        lda #0
        sta CC
        lda #255
        sta CO              ; force the first setchan to paint
        jsr detpal
        jsr ledboot
        jsr reudet
        jsr serini

        lda #<msgcon
        sta PTR
        lda #>msgcon
        sta PTRH
        jsr prtstr
        jsr handshk

loop:   jsr poll
        jsr kbd
        jsr ledstep
        jsr tkey
        jsr chktik
        lda READY
        beq loop
        jsr dispat
        lda #0
        sta READY
        jmp loop

; ===== PAL or NTSC? ====================================================
; Time one whole frame with a CIA timer. PAL is 312 lines x 63 cycles =
; 19656; NTSC is 263 x 65 = 17095. The timer counts DOWN from $ffff, so
; PAL leaves a SMALLER value behind. Anything below the midpoint is PAL.
; Raster line 0 happens twice per frame as far as $d012 is concerned --
; lines 256+ wrap its low byte -- so bit 7 of $d011 has to be checked too.
; **Start the timer AFTER reaching line 0, not before.** Starting it first
; measured "however long it took to reach line 0, PLUS one frame", which
; varies from boot to boot -- so PAL sometimes measured as NTSC, the bit
; period came out 3.8% wrong, and frames were rejected intermittently.
detpal: sei
; **Read $d012 BEFORE $d011, never the other way round.** They are two
; separate reads and the raster moves between them: catch it at the 255 ->
; 256 boundary and you see bit 8 clear (from line 255) together with a low
; byte of 0 (from line 256), which looks exactly like line 0. That false
; hit ended the frame measurement after ~8 lines.
dp1:    lda RASTER
        bne dp1
        lda VICCTL2
        and #128
        bne dp1             ; line 0, top of a frame
        lda #255
        sta C2TALO
        sta C2TAHI
        lda #17             ; force load, start, continuous -- NOW
        sta C2CRA
dp2:    lda RASTER
        beq dp2             ; leave it
dp3:    lda RASTER
        bne dp3
        lda VICCTL2
        and #128
        bne dp3             ; line 0 again: exactly one frame later
        lda C2TAHI
        sta TMP
        sta RAWHI
        lda #0
        sta C2CRA
        cli
; PAL leaves about $B3xx, NTSC about $BDxx. $B8 splits them.
        lda TMP
        cmp #184
        bcs dpntsc
        lda #0
        sta ISNTSC
        jmp dpset
dpntsc: lda #1
        sta ISNTSC
dpset:  ldx #0
        lda ISNTSC
        beq dpcp
        ldx #4
dpcp:   lda bitpal,x
        sta btlo
        lda bitpal+1,x
        sta bthi
        lda bitpal+2,x
        sta hblo
        lda bitpal+3,x
        sta hbhi
        rts

; ===== bring up our own rs-232 =========================================
serini: sei
; PA2 is TXD. bits 0-1 of this port select the VIC bank, so every touch
; of it is read-modify-write -- writing a whole byte here blanks the
; screen in a very confusing way.
        lda C2DDRA
        ora #4
        sta C2DDRA
        lda C2PRA
        ora #4              ; idle high = mark
        sta C2PRA
; **DDRB is set absolutely, not read-modify-write.** The boot lamp sweep
; leaves DDRB at 126, which makes PB1 and PB2 OUTPUTS and drives RTS and
; DTR low -- and a flow-controlled radio then stops transmitting. Symptom:
; transmit works perfectly, every handshake command goes out and is
; answered, and not one byte ever comes back. 120 = PB3-PB6 out for the
; lamps, everything else input, which hands RTS/DTR back.
        lda #120
        sta C2DDRB

; install our nmi handler. the kernal's entry does SEI then JMP ($0318),
; so this gets in ahead of it.
        lda #<nmih
        sta NMIVEC
        lda #>nmih
        sta NMIVEC+1

        lda #127            ; disable every cia2 interrupt source
        sta C2ICR
        lda C2ICR           ; reading clears whatever was pending
        lda #144            ; enable FLAG: the start-bit edge
        sta C2ICR
        cli
        rts

; ===== the receiver ====================================================
; FLAG fires on the falling edge of a start bit. We then wait ONE AND A
; HALF bit times, which lands the first sample in the middle of data bit
; 0, and one bit time between samples after that. rs-232 is lsb first, so
; each sampled bit rotates in from the top and ends up in the right place
; after eight of them.
nmih:   pha
        txa
        pha
        tya
        pha
        lda C2ICR           ; read = acknowledge
        sta ICRSV
        and #16             ; FLAG?
        beq nmtb

; --- start bit seen ---
        lda hblo
        sta C2TBLO
        lda hbhi
        sta C2TBHI
        lda #25             ; one-shot, force load, start
        sta C2CRB
        lda #127
        sta C2ICR
        lda #130            ; now interrupt on timer B instead
        sta C2ICR
        lda #9              ; 8 data bits + the stop bit
        sta BITCNT
        jmp nmx

nmtb:   lda ICRSV
        and #2              ; timer B?
        beq nmx
        lda BITCNT
        cmp #1
        beq nmstop          ; the last one is the stop bit, not data
        lda C2PRB
        lsr                 ; PB0 -> carry
        ror SHIFT
        jmp nmcl
; **The stop bit must be high.** If it is not, the byte was framed wrong --
; which is what mis-sampled bits look like from in here, and it is the only
; way to tell "the link is noisy" apart from "the data really said that".
nmstop: lda C2PRB
        and #1
        bne nmcl
        inc FRERR
nmcl:   lda BITCNT
; **After the first sample, switch to a FREE-RUNNING one-bit clock.**
; Reloading a one-shot timer inside the handler adds the handler's own
; latency to every bit, and that error accumulates across the byte until
; the last samples land outside their bits. In continuous mode the
; underflows are exactly one bit apart in hardware, so nmi latency shifts
; where we sample within a bit but never where the bit boundaries are.
        cmp #9
        bne nmnorl
        lda btlo
        sta C2TBLO
        lda bthi
        sta C2TBHI
        lda #17             ; force load, start, CONTINUOUS
        sta C2CRB
nmnorl: dec BITCNT
        beq nmbyte
        jmp nmx

; --- eighth bit sampled: store it and re-arm on the next start bit ---
nmbyte: lda #0
        sta C2CRB           ; stop the bit clock
        lda SHIFT
        ldx RHEAD
        sta RBUF,x
        inc RHEAD
; the line is in its stop bit now, which is high, so the next falling edge
; is a real start bit. clear anything latched before unmasking or we take
; an immediate false trigger.
        lda #127
        sta C2ICR
        lda C2ICR
        lda #144
        sta C2ICR
nmx:    pla
        tay
        pla
        tax
        pla
        rti

; ===== transmit ========================================================
; Bit clock from timer A, polled. The timer is hardware, so badline DMA
; cannot stretch a bit the way it can stretch a counted delay loop.
; Reading the ICR to poll it also clears FLAG and timer B, so the receiver
; has to be masked for the duration -- which is fine, the radio does not
; answer until it has the whole frame.
txbyte: sta TXB
        lda C2PRA
        and #251            ; start bit: low
        sta C2PRA
        jsr txwait
        ldx #8
txbl:   lsr TXB
        bcc txb0
        lda C2PRA
        ora #4
        jmp txbs
txb0:   lda C2PRA
        and #251
txbs:   sta C2PRA
        jsr txwait
        dex
        bne txbl
        lda C2PRA
        ora #4              ; stop bit: high
        sta C2PRA
        jsr txwait
        rts

; Wait for the next timer A underflow. The timer runs CONTINUOUSLY and is
; started once per frame, so the period is exact however long our per-bit
; work takes. Reloading a one-shot here added ~30 cycles to every bit --
; 3.7% at 1200 baud, a third of a bit across a 10-bit frame, which is how
; the first version put garbage on the wire.
txwait: lda C2ICR
        and #1
        beq txwait
        rts

; mask the receiver, send the framed payload, re-arm the receiver
sendfr: sei
        lda #127
        sta C2ICR           ; receiver off for the duration: half duplex,
                            ; which is what this protocol actually is
        lda btlo
        sta C2TALO
        lda bthi
        sta C2TAHI
        lda #17             ; force load, start, CONTINUOUS
        sta C2CRA
        lda C2ICR           ; clear anything already pending
        lda #60             ; '<'
        jsr txbyte
        lda TXLEN
        jsr txbyte
        lda #0
        jsr txbyte
        lda #0
        sta SFY
sfl:    lda SFY
        cmp TXLEN
        bcs sfd
        tay
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
        lda #144
        sta C2ICR
        rts
SFY:    .byte 0

; ===== drain our ring and reassemble frames ============================
poll:   lda READY
        bne pdone
        lda RHEAD
        sec
        sbc RTAIL
        cmp OVR
        bcc pnohw
        sta OVR
pnohw:
ploop:  ldy RTAIL
        cpy RHEAD
        beq pdone
        lda RBUF,y
        inc RTAIL

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

pidle:  cmp #62
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

; ===== everything below is unchanged from mlclient.py ==================
wait1:  lda JIFFY
w1l:    cmp JIFFY
        beq w1l
        rts

prtstr: ldy #0
psl:    lda (PTR),y
        beq psd
        jsr CHROUT
        iny
        bne psl
psd:    rts

setpay: sta TXLEN
        ldy #0
cpl:    cpy TXLEN
        bcs cpd
        lda (PTR),y
        sta TXBUF,y
        iny
        jmp cpl
cpd:    rts

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

handshk:
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
        lda RHEAD
        sta RTAIL

        lda #<pyastart
        sta PTR
        lda #>pyastart
        sta PTRH
        lda #11
        jsr setpay
        jsr sendfr
        lda #1
        sta STGBIT
        lda #5
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
        lda #13
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
        lda #18
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
        lda #9
        jsr waitop

        lda #<msgrdy
        sta PTR
        lda #>msgrdy
        sta PTRH
        jsr prtstr
        jsr setprm
        jsr shoprm
        jsr sync
        rts

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
        cmp #7
        bcs wotmo
wonew:  lda JIFFY
        sta WJ
        jmp wol
wotmo:  rts
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

dispat: lda BUF
        cmp #17
        beq dmsg
        cmp #131
        beq dwait
        cmp #18
        beq dchan
        rts
dchan:  jmp rxchan
dwait:  jmp sync
dmsg:   lda BUF+4
        cmp #40
        bcs dbad
        lda FLEN
        cmp #12
        bcc dbad
        lda BUF+6
        cmp #3
        bcs dbad
        lda BUF+4
        sta TMP             ; the channel this message arrived on
        jsr ledrx
        jsr arcmsg
        jsr hput
; **Filtered for display, never for delivery.** The radio holds one queue
; shared by every channel, so a message for a channel we are not watching
; still has to be collected -- skipping it would strand it and back the
; queue up. It just is not printed.
        lda CC
        cmp #255
        beq dmshow          ; "All" shows everything
        lda TMP
        cmp CC
        beq dmshow
        ldx TMP
        lda CUNR,x
        cmp #255
        beq dmsy
        inc CUNR,x
        lda UT
        cmp #255
        beq dmsy
        inc UT
dmsy:   jsr refprm          ; so the +N counter updates in place
        jmp sync
dmshow: inc MSGS
        bne dmnc
        inc MSGSH
dmnc:   jsr shomsg
        jmp sync
dbad:   inc RJ
        jmp sync

; **Reuse the prompt's own row for the message.** Back up over
; prompt+typed text to column 0, write the message there, pad out whatever
; the longer prompt left behind, then redraw the prompt underneath. The
; messages flow, the prompt stays at the bottom, and nothing half-typed is
; lost -- it moves down with the prompt.
shomsg: lda blankb
        bne smrt            ; nothing to look at with the screen off
        jsr bkprm
        ldx #11
        ldy #0
sml:    cpx CLEN
        bcs smpad
        lda CBUF,x
        jsr CHROUT
        inx
        iny
        jmp sml
smpad:  sty TMP
        lda PRLEN
        clc
        adc INLEN
        cmp TMP
        bcc smnp
        sec
        sbc TMP
        beq smnp
        tax
smpl:   lda #32
        jsr CHROUT
        dex
        bne smpl
smnp:   jsr shoprm
smrt:   rts

; ===== prompt ==========================================================
; The prompt doubles as the "which channel am i in" indicator. A status bar
; on a fixed row would be wiped by every scroll and need repainting through
; screen ram; the prompt is redrawn constantly anyway, so it costs nothing.
setprm: ldx #0
        lda CC
        cmp #255
        bne spnamed
        lda #65             ; "All"
        sta PROMPT
        lda #76
        sta PROMPT+1
        sta PROMPT+2
        ldx #3
        jmp spunr
spnamed:
        jsr chnptr
        ldy #0
spnl:   cpy #12
        bcs spunr
        lda (PTR),y
        beq spunr
        sta PROMPT,x
        inx
        iny
        jmp spnl
; "+3" means 3 waiting on OTHER channels -- never this one. "(3)" read as
; "this channel has 3 unread", which is exactly the wrong impression.
spunr:  lda UT
        beq spgt
        lda #32
        sta PROMPT,x
        inx
        lda #43             ; '+'
        sta PROMPT,x
        inx
        lda UT
        jsr dec8
        sta TMP
        lda #3
        sec
        sbc TMP
        tay
spul:   lda DECBUF,y
        sta PROMPT,x
        inx
        iny
        cpy #3
        bcc spul
spgt:   lda #62             ; '>'
        sta PROMPT,x
        inx
        lda #32
        sta PROMPT,x
        inx
        stx PRLEN
        rts

shoprm: lda #13
        jsr CHROUT
        ldx #0
shpl:   cpx PRLEN
        bcs shpl2
        lda PROMPT,x
        jsr CHROUT
        inx
        jmp shpl
shpl2:  ldx #0
shpl3:  cpx INLEN
        bcs shprt
        lda INBUF,x
        jsr CHROUT
        inx
        jmp shpl3
shprt:  rts

; cursor back to column 0 of the prompt row
bkprm:  lda PRLEN
        clc
        adc INLEN
        tax
        beq bkrt
bkl:    lda #157
        jsr CHROUT
        dex
        bne bkl
bkrt:   rts

; ===== byte -> decimal, no leading zeros ===============================
; DECBUF holds hundreds/tens/units; returns the significant digit count in
; A, so the caller reads from DECBUF + (3 - A).
dec8:   ldy #0
d8h:    cmp #100
        bcc d8h2
        sec
        sbc #100
        iny
        jmp d8h
d8h2:   sty TMP2
        ldy #0
d8t:    cmp #10
        bcc d8t2
        sec
        sbc #10
        iny
        jmp d8t
d8t2:   clc
        adc #48
        sta DECBUF+2
        tya
        clc
        adc #48
        sta DECBUF+1
        lda TMP2
        clc
        adc #48
        sta DECBUF
        lda TMP2
        beq d8nh
        lda #3
        rts
d8nh:   tya
        beq d8nt
        lda #2
        rts
d8nt:   lda #1
        rts

; ===== PTR -> channel name slot, index in A ============================
; 18 bytes per slot: x18 is x16 + x2, which is four shifts and one add.
chnptr: sta PTR
        lda #0
        sta PTRH
        asl PTR
        rol PTRH            ; x2
        lda PTR
        sta TMP
        lda PTRH
        sta TMP2
        asl PTR
        rol PTRH            ; x4
        asl PTR
        rol PTRH            ; x8
        asl PTR
        rol PTRH            ; x16
        lda PTR
        clc
        adc TMP
        sta PTR
        lda PTRH
        adc TMP2
        sta PTRH
        lda PTR
        clc
        adc #<CHNAM
        sta PTR
        lda PTRH
        adc #>CHNAM
        sta PTRH
        rts

; ===== resp_code_channel_info: remember the name =======================
; layout: op, chan_idx, name(2..33), secret(34..49)
rxchan: lda BUF+1
        cmp #40
        bcs rcrt
        jsr chnptr
        ldy #0
rcl:    cpy #17
        bcs rcend
        lda CBUF+2,y
        beq rcend
        sta (PTR),y
        iny
        jmp rcl
rcend:  lda #0
        sta (PTR),y
rcrt:   rts

; ===== keyboard ========================================================
kbd:    jsr GETIN
        cmp #0
        beq kbrt
        cmp #13
        beq kbret
        cmp #20
        beq kbdel
; function keys MUST be caught before the printable test: f1/f3/f5/f7 are
; 133/134/135/136, all inside the 32..218 range, and would otherwise be
; appended to the typed line as garbage.
        cmp #133
        beq kbf1
        cmp #134
        beq kbf3
        cmp #135
        beq kbf5
        cmp #136
        beq kbf7
        cmp #32
        bcc kbrt
        cmp #219
        bcs kbrt
        ldx INLEN
        cpx #36             ; keep prompt+text on one 40-column row
        bcs kbrt
        sta INBUF,x
        pha
        jsr CHROUT          ; echo as typed
        pla
; keep TWO copies: petscii for the screen, ascii for the wire. converting
; one character per keystroke is invisible; converting a whole line at send
; time froze the old basic build for over a second.
        cmp #65
        bcc kbst
        cmp #91
        bcc kbup
        cmp #193
        bcc kbst
        cmp #219
        bcs kbst
        sec
        sbc #128
        jmp kbst
kbup:   clc
        adc #32
kbst:   ldx INLEN
        sta INASC,x
        inc INLEN
kbrt:   rts

kbdel:  lda INLEN
        beq kbrt
        dec INLEN
        lda #20
        jsr CHROUT
        rts

kbret:  jsr sendmsg
        lda #0
        sta INLEN
        jsr shoprm
        rts

kbf1:   jmp picker
kbf3:   jmp status
kbf5:   jmp scrollb
kbf7:   lda #0
        sta CC
        jmp setchan

; ===== send ============================================================
sendmsg:
        lda INLEN
        beq smsrt
        lda CC
        cmp #255
        beq smsall
        lda #3              ; cmd_send_channel_txt_msg
        sta TXBUF
        lda #0
        sta TXBUF+1         ; txt_type plain
        lda CC
        sta TXBUF+2
        lda #0
        sta TXBUF+3
        sta TXBUF+4
        sta TXBUF+5
        sta TXBUF+6
        ldx #0
smscp:  cpx INLEN
        bcs smsgo
        lda INASC,x
        sta TXBUF+7,x
        inx
        jmp smscp
smsgo:  txa
        clc
        adc #7
        sta TXLEN
        jsr ledtx
        jsr sendfr
        jsr arcown
smsrt:  rts
; "All" is a read-only monitor: there is no single channel to send to, and
; quietly defaulting to Public would post to the wrong place.
smsall: lda #<msgpick
        sta PTR
        lda #>msgpick
        sta PTRH
        jsr prtstr
        rts

sync:   lda #10
        sta TXBUF
        lda #1
        sta TXLEN
        jsr sendfr
        rts

report: lda #3
        sta TXBUF
        lda #0
        sta TXBUF+1
        sta TXBUF+2
        sta TXBUF+3
        sta TXBUF+4
        sta TXBUF+5
        sta TXBUF+6
        ldx #7
        lda #110
        sta TXBUF,x
        inx
        lda NFRM
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #114
        sta TXBUF,x
        inx
        lda RJ
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #109
        sta TXBUF,x
        inx
        lda MSGSH
        jsr apphex
        lda MSGS
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #104
        sta TXBUF,x
        inx
        lda HSTAGE
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #111
        sta TXBUF,x
        inx
        lda OVR
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #101            ; 'e' = framing errors
        sta TXBUF,x
        inx
        lda FRERR
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #118            ; 'v' = video standard, 00 pal / 01 ntsc
        sta TXBUF,x
        inx
        lda ISNTSC
        jsr apphex
        lda #119            ; 'w' = the RAW frame measurement it decided on
        sta TXBUF,x
        inx
        lda RAWHI
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #117            ; 'u' = reu present + lines-per-region shift
        sta TXBUF,x
        inx
        lda RU
        jsr apphex
        lda LSHIFT
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #99             ; 'c' = current channel
        sta TXBUF,x
        inx
        lda CC
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #108            ; 'l' = lines archived in the All region
        sta TXBUF,x
        inx
        lda LFH+8
        jsr apphex
        lda LFL+8
        jsr apphex
        stx TXLEN
        jsr sendfr
        rts

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

; ===== TEST ONLY: scripted keypresses ==================================
; Stuffed into the kernal's own keyboard buffer, so GETIN cannot tell them
; from real ones -- and they survive into the picker's own GETIN loop,
; which is how "f1 then pick" works with no test hook inside the picker.
; Keys go in as BATCHES, not one at a time. The picker and the scrollback
; both run their own GETIN loops, so this routine stops being called the
; moment one of them opens -- anything they need has to already be sitting
; in the buffer. A single key per tick left the picker waiting forever.
tkey:   lda testk
        beq tkrt
        lda JIFFY
        cmp TKJ
        bcs tkrt                ; only on a wrap, so ~4.3s apart
        ldx TKC
        lda tktab,x
        beq tkrt                ; table exhausted
        ldy #0
tkl:    lda tktab,x
        beq tkdone
        sta KBUF,y
        inx
        iny
        cpy #8
        bcc tkl
tkdone: sty KCNT
        inx                     ; step over the batch terminator
        stx TKC
tkrt:   lda JIFFY
        sta TKJ
        rts
; f1+pick Test | type "hi"+RETURN | f5 then a key to leave | f7 | f1+pick
tktab:  .byte 133,50,0
        .byte 104,105,13,0
        .byte 135,32,0
        .byte 136,0
        .byte 133,49,0
        .byte 0

; ===== cartridge LEDs ==================================================
; PB3-PB6 drive the lamps. Unlike the kernal's rs-232 we never touch PB1 or
; PB2 (RTS/DTR), so there is nothing to collide with -- the constraint that
; forced the old build to hand those pins back does not apply here.
ledrx:  lda #0                  ; a ripple: the mesh is talking
        sta LEDPAT
        lda #0
        sta LEDIX
        lda #1
        sta LEDON
        rts
ledtx:  lda #5                  ; all four at once: that one was ours
        sta LEDPAT
        lda #0
        sta LEDIX
        lda #1
        sta LEDON
        rts

; stepped once per jiffy from the main loop, so the animation is visible
; without costing anything measurable
ledstep:
        lda LEDON
        beq lsrt
        lda JIFFY
        cmp LEDJ
        beq lsrt
        sta LEDJ
        lda LEDPAT
        clc
        adc LEDIX
        tax
        lda ledtab,x
        cmp #255
        beq lsend
        sta C2PRB
        inc LEDIX
        rts
lsend:  lda #0
        sta LEDON
        sta C2PRB
lsrt:   rts

ledtab: .byte 48,72,48,0,255
        .byte 120,120,0,120,120,0,255

; ===== boot lamp sweep =================================================
ledboot:
        lda #126
        sta C2DDRB
        ldx #24
        lda #2
        sta TMP
lbl:    lda TMP
        sta C2PRB
        asl TMP
        lda TMP
        cmp #128
        bcc lbn
        lda #2
        sta TMP
lbn:    ldy #6
lbw:    jsr wait1
        dey
        bne lbw
        dex
        bne lbl
        lda #0
        sta C2PRB
        lda #120            ; lamps off, rts/dtr handed straight back
        sta C2DDRB
        rts

; ===== is there an REU, and how big? ===================================
; The 8726 lives at $df00. A transfer does NOT autoload, so every base
; register is rewritten before each one.
reudet: lda #0
        sta RU
        sta UKL
        sta UKH
        lda #86
        sta TAPEBUF
        lda #171
        sta TAPEBUF+1
        lda #12
        sta TAPEBUF+2
        lda #241
        sta TAPEBUF+3
        lda #0
        sta UB
        jsr reustash
        lda #0                  ; wipe it, then pull it back. with no reu
        sta TAPEBUF             ; the registers are open bus, nothing is
        sta TAPEBUF+1           ; transferred, and the buffer stays wiped
        sta TAPEBUF+2
        sta TAPEBUF+3
        lda #0
        sta UB
        jsr reufetch
        lda TAPEBUF
        cmp #86
        bne rdno
        lda TAPEBUF+1
        cmp #171
        bne rdno
        lda TAPEBUF+2
        cmp #12
        bne rdno
        lda TAPEBUF+3
        cmp #241
        bne rdno
        lda #1
        sta RU
        lda #64
        sta UKL
        lda #0
        sta UKH
; size: bank 0 holds 86. write a different marker to bank 1, 2, 4, 8... and
; re-read bank 0. when bank 0 has changed, the bank register has wrapped
; and we know the real size. the marker is UB itself -- 200+UB overflows a
; byte at bank 128 and that was an illegal quantity error on 4MB units.
        lda #1
        sta UB
rdsl:   lda UB
        cmp #129
        bcs rddone
        lda UB
        sta TAPEBUF
        jsr reustash
        lda #0
        sta TAPEBUF
        lda UB
        pha
        lda #0
        sta UB
        jsr reufetch
        pla
        sta UB
        lda TAPEBUF
        cmp #86
        bne rddone
        lda UB                  ; uk = ub * 128
        sta UKL
        lda #0
        sta UKH
        ldx #7
rdml:   asl UKL
        rol UKH
        dex
        bne rdml
        asl UB
        jmp rdsl
rddone:
; lines per region: 512 if we have the room, else 256, else 128. Regions
; are a power of two so the address maths is shifts, not a 24-bit multiply.
        lda UKH
        bne rd512
        lda UKL
        cmp #255
        bcs rd512
        cmp #128
        bcs rd256
        lda #7
        jmp rdset
rd256:  lda #8
        jmp rdset
rd512:  lda #9
rdset:  sta LSHIFT
; stride = 1 << (LSHIFT+6); lines = 1 << LSHIFT
        lda #0
        sta STRL
        sta STRM
        sta STRH
        sta MAXL
        sta MAXH
        lda #1
        sta MAXL
        ldx LSHIFT
rdxl:   asl MAXL
        rol MAXH
        dex
        bne rdxl
; region stride = lines * 64, as a 24-bit shift
        lda MAXL
        sta STRL
        lda MAXH
        sta STRM
        lda #0
        sta STRH
        ldx #6
rdsh:   asl STRL
        rol STRM
        rol STRH
        dex
        bne rdsh
        rts
rdno:   lda #0
        sta RU
        rts

; 4 bytes, tape buffer <-> reu bank UB offset 0
reustash:
        jsr reubase
        lda #144                ; $90 execute now, c64 -> reu
        sta RCMD
        rts
reufetch:
        jsr reubase
        lda #145                ; $91 execute now, reu -> c64
        sta RCMD
        rts
reubase:
        lda #60
        sta RC64L
        lda #3
        sta RC64H
        lda #0
        sta RREUL
        sta RREUM
        lda UB
        sta RREUB
        lda #4
        sta RLENL
        lda #0
        sta RLENH
        sta RCTL
        rts

; ===== REU address for REGION / SLOT ===================================
; addr = region*stride + slot*64. Both are shifts; region is at most 8, so
; the region term is a short add loop rather than a multiply.
reuaddr:
        lda SLOTL
        sta ADRL
        lda SLOTH
        sta ADRM
        lda #0
        sta ADRH
        ldx #6
rasl:   asl ADRL
        rol ADRM
        rol ADRH
        dex
        bne rasl
        ldx REGION
        beq radone
ralp:   lda ADRL
        clc
        adc STRL
        sta ADRL
        lda ADRM
        adc STRM
        sta ADRM
        lda ADRH
        adc STRH
        sta ADRH
        dex
        bne ralp
radone: rts

; set up a transfer of CNT*40 bytes between c64 PTR and the computed slot
reuxfer:
        jsr reuaddr
        lda PTR
        sta RC64L
        lda PTRH
        sta RC64H
        lda ADRL
        sta RREUL
        lda ADRM
        sta RREUM
        lda ADRH
        sta RREUB
        lda #0
        sta RLENH
        lda CNT
        sta RLENL
        lda #0
        sta RCTL
        rts

; ===== petscii -> screen codes, CBUF[SOFF..CLEN) -> SBUF ===============
scrn:   ldx SOFF
        ldy #0
snl:    cpx CLEN
        bcs spad
        lda CBUF,x
        cmp #32
        bcc sctl
        cmp #64
        bcc sput
        cmp #96
        bcc sm191
        cmp #128
        bcc sm223
        cmp #192
        bcc sput
        and #127
        jmp sput
sm191:  and #191
        jmp sput
sm223:  and #223
        jmp sput
sctl:   lda #32
sput:   sta SBUF,y
        inx
        iny
        cpy #80
        bcc snl
        lda #2
        sta SLEN
        rts
spad:   cpy #41
        bcs sp80
        lda #32
sp40:   cpy #40
        bcs sp40d
        sta SBUF,y
        iny
        jmp sp40
sp40d:  lda #1
        sta SLEN
        rts
sp80:   lda #32
sp8l:   cpy #80
        bcs sp8d
        sta SBUF,y
        iny
        jmp sp8l
sp8d:   lda #2
        sta SLEN
        rts

; ===== which region belongs to a channel ===============================
; 0-7 get their own, anything higher shares 7, "All" gets 8.
lreg:   cmp #255
        bne lrn
        lda #8
        sta REGION
        rts
lrn:    cmp #8
        bcc lrok
        lda #7
lrok:   sta REGION
        rts

; ===== append SLEN lines from SBUF to REGION ===========================
lput:   lda SLEN
        sta CNT
        ldx #0
lpl:    cpx CNT
        bcs lpdone
        txa
        pha
; slot = LW[region]
        ldx REGION
        lda LWL,x
        sta SLOTL
        lda LWH,x
        sta SLOTH
        pla
        pha
        asl                     ; line index * 40
        sta TMP
        asl
        asl
        clc
        adc TMP
        clc
        adc #<SBUF
        sta PTR
        lda #>SBUF
        adc #0
        sta PTRH
        lda #40
        sta CNT
        jsr reuxfer
        lda #144                ; c64 -> reu
        sta RCMD
        lda SLEN
        sta CNT
; advance the write pointer, wrapping at the region size
        ldx REGION
        inc LWL,x
        bne lpnw
        inc LWH,x
lpnw:   lda LWH,x
        cmp MAXH
        bcc lpnf
        lda LWL,x
        cmp MAXL
        bcc lpnf
        lda #0
        sta LWL,x
        sta LWH,x
; fill count grows to the region size and then stops
lpnf:   lda LFH,x
        cmp MAXH
        bcc lpinc
        lda LFL,x
        cmp MAXL
        bcs lpskip
lpinc:  inc LFL,x
        bne lpskip
        inc LFH,x
lpskip: pla
        tax
        inx
        jmp lpl
lpdone: rts

; ===== archive one received message ====================================
; Twice: plain into its own channel's region, and prefixed into "All" so
; that scrolling the merged feed still says where each line came from.
arcmsg: lda RU
        beq amrt
        lda #11
        sta SOFF
        jsr scrn
        lda TMP                 ; the channel it arrived on
        jsr lreg
        jsr lput
; The prefix has to END at cbuf byte 10 so it butts against the text at
; 11, and it is variable length -- so build it in SBUF first (free now,
; lput has already consumed it) and copy it in at 11 minus its length.
; Writing into cbuf 0..10 is safe: those bytes are the frame's binary
; header, and the opcode and channel index are read from the RAW buffer.
        ldx #0
        lda #91                 ; '['
        sta SBUF,x
        inx
        lda TMP
        jsr chnptr
        ldy #0
        lda (PTR),y
        bne ampl
; never scanned, so no name yet -- fall back to the index rather than
; showing empty brackets
        lda #99                 ; 'c'
        sta SBUF,x
        inx
        lda #104                ; 'h'
        sta SBUF,x
        inx
        lda TMP
        jsr dec8
        sta TMP2
        lda #3
        sec
        sbc TMP2
        tay
amnl:   lda DECBUF,y
        sta SBUF,x
        inx
        iny
        cpy #3
        bcc amnl
        jmp ampd
ampl:   cpy #8
        bcs ampd
        lda (PTR),y
        beq ampd
        sta SBUF,x
        inx
        iny
        jmp ampl
ampd:   lda #93                 ; ']'
        sta SBUF,x
        inx
        lda #32
        sta SBUF,x
        inx
        stx TMP2                ; prefix length, 3..11
        lda #11
        sec
        sbc TMP2
        sta SOFF
        ldy SOFF
        ldx #0
amcp:   cpx TMP2
        bcs amcd
        lda SBUF,x
        sta CBUF,y
        inx
        iny
        jmp amcp
amcd:   jsr scrn
        lda #8
        sta REGION
        jsr lput
amrt:   rts

; ===== archive what we just sent =======================================
; The radio never echoes our own messages back, so without this the
; scrollback shows one side of the conversation.
arcown: lda RU
        beq aort
        lda #62                 ; '>'
        sta CBUF+11
        lda #32
        sta CBUF+12
        ldx #0
aocl:   cpx INLEN
        bcs aocd
        lda INBUF,x
        sta CBUF+13,x
        inx
        jmp aocl
aocd:   txa
        clc
        adc #13
        sta CLEN
        lda #11
        sta SOFF
        jsr scrn
        lda CC
        jsr lreg
        jsr lput
        lda #8
        sta REGION
        jsr lput
aort:   rts

; ===== paint a page from the archive ===================================
; 24 lines, NOT 25: the bottom row belongs to the prompt. Painting all 25
; put the newest message where the prompt then overwrote it.
arcpage:
        lda RU
        beq aprt
        lda CC
        jsr lreg
        ldx REGION
        lda LFL,x
        ora LFH,x
        beq aprt                ; nothing archived yet
; newest slot = LW - 1, wrapping
        lda LWL,x
        sta ZYL
        lda LWH,x
        sta ZYH
        lda ZYL
        bne apdec
        lda ZYH
        beq apwrap
        dec ZYH
apdec:  dec ZYL
        jmp apn
apwrap: lda MAXL
        sta ZYL
        lda MAXH
        sta ZYH
        lda ZYL
        bne apd2
        dec ZYH
apd2:   dec ZYL
apn:    lda #0
        sta SD
        jsr appage
aprt:   rts

; paint 24 lines ending at slot ZY
appage: ldx REGION
        lda LFH,x
        bne ap24
        lda LFL,x
        cmp #24
        bcs ap24
        sta NLINE
        lda #147                ; short page: clear first so nothing older
        jsr CHROUT              ; is left on screen behind it
        jmp apgo
ap24:   lda #24
        sta NLINE
apgo:   lda NLINE
        beq aprt2
; walk back NLINE-1 slots from ZY, then paint forward
        lda ZYL
        sta SLOTL
        lda ZYH
        sta SLOTH
        lda NLINE
        sec
        sbc #1
        sta CNT
apbk:   lda CNT
        beq apfw
        lda SLOTL
        bne apb2
        lda SLOTH
        bne apb3
        lda MAXL
        sta SLOTL
        lda MAXH
        sta SLOTH
apb3:   dec SLOTH
apb2:   dec SLOTL
        dec CNT
        jmp apbk
; paint forward into rows 24-NLINE .. 23
apfw:   lda #24
        sec
        sbc NLINE
        sta TMP                 ; first screen row
        lda #0
        sta CNT
apfl:   lda CNT
        cmp NLINE
        bcs aprt2
; c64 screen address = 1024 + row*40
        lda TMP
        clc
        adc CNT
        sta TMP2
        lda #0
        sta PTRH
        lda TMP2
        sta PTR
        asl PTR
        rol PTRH
        asl PTR
        rol PTRH
        asl PTR
        rol PTRH                ; x8
        lda PTR
        sta TMP2
        lda PTRH
        sta BLANKS
        asl PTR
        rol PTRH
        asl PTR
        rol PTRH                ; x32
        lda PTR
        clc
        adc TMP2
        sta PTR
        lda PTRH
        adc BLANKS
        sta PTRH                ; x40
        lda PTR
        clc
        adc #0
        sta PTR
        lda PTRH
        adc #4                  ; + $0400
        sta PTRH
        lda #40
        sta CNT2
        jsr apxfer
        inc CNT
        jsr apnext
        jmp apfl
aprt2:  rts

apxfer: lda CNT2
        pha
        jsr reuaddr
        lda PTR
        sta RC64L
        lda PTRH
        sta RC64H
        lda ADRL
        sta RREUL
        lda ADRM
        sta RREUM
        lda ADRH
        sta RREUB
        pla
        sta RLENL
        lda #0
        sta RLENH
        sta RCTL
        lda #145                ; reu -> c64
        sta RCMD
        rts

apnext: inc SLOTL
        bne apnx2
        inc SLOTH
apnx2:  lda SLOTH
        cmp MAXH
        bcc apnx3
        lda SLOTL
        cmp MAXL
        bcc apnx3
        lda #0
        sta SLOTL
        sta SLOTH
apnx3:  rts

; ===== f5 scrollback ===================================================
scrollb:
        lda RU
        beq sbrt
        lda CC
        jsr lreg
        ldx REGION
        lda LFL,x
        ora LFH,x
        beq sbrt
        lda BORDER
        sta OLDB
        lda #2                  ; red border: you are looking at history
        sta BORDER
        lda #0
        sta SD
sbkey:  jsr poll                ; keep draining, same rule as the picker
        lda READY
        beq sbnk
        jsr dispat
        lda #0
        sta READY
sbnk:   jsr GETIN
        cmp #0
        beq sbkey
        cmp #135                ; f5 = older
        beq sbold
        cmp #136                ; f7 = newer
        beq sbnew
        jmp sbexit
sbold:  lda SD
        clc
        adc #24
        sta TMP
        ldx REGION
        lda LFH,x
        bne sbok
        lda LFL,x
        cmp TMP
        bcc sbkey               ; stop at the oldest line we still hold
sbok:   lda TMP
        sta SD
        ldx #24
sbol:   jsr sbdec
        dex
        bne sbol
        jsr appage
        jmp sbkey
sbnew:  lda SD
        beq sbkey
        sec
        sbc #24
        sta SD
        ldx #24
sbnl:   jsr sbinc
        dex
        bne sbnl
        jsr appage
        jmp sbkey
sbexit: lda #0
        sta SD
        jsr arcpage
        lda OLDB
        sta BORDER
        jsr shoprm
sbrt:   rts

sbdec:  lda ZYL
        bne sbd2
        lda ZYH
        bne sbd3
        lda MAXL
        sta ZYL
        lda MAXH
        sta ZYH
sbd3:   dec ZYH
sbd2:   dec ZYL
        rts
sbinc:  inc ZYL
        bne sbi2
        inc ZYH
sbi2:   rts

; ===== refresh the prompt in place =====================================
; Called when a message lands on another channel: the +N counter has to
; change without scrolling a new prompt onto the screen.
refprm: lda PRLEN
        clc
        adc INLEN
        sta OLDT
        jsr bkprm
        jsr setprm
        ldx #0
rfl:    cpx PRLEN
        bcs rfl2
        lda PROMPT,x
        jsr CHROUT
        inx
        jmp rfl
rfl2:   ldx #0
rfl3:   cpx INLEN
        bcs rfpad
        lda INBUF,x
        jsr CHROUT
        inx
        jmp rfl3
; a shorter prompt leaves debris from the longer one behind it
rfpad:  lda PRLEN
        clc
        adc INLEN
        sta TMP
        lda OLDT
        cmp TMP
        bcc rfrt
        sec
        sbc TMP
        beq rfrt
        tax
        txa
        pha
rfp1:   lda #32
        jsr CHROUT
        dex
        bne rfp1
        pla
        tax
rfp2:   lda #157
        jsr CHROUT
        dex
        bne rfp2
rfrt:   rts

; ===== scan the radio's channel list ===================================
; The quick scan stops after three blank slots in a row, which is fast but
; misses a channel sitting above a gap -- a real setup had them at 0, 1 and
; 5. CF forces the full 40-slot sweep, which is what "R" in the picker does.
chscan: lda #0
        sta SCANI
        sta BLANKS
cslp:   lda SCANI
        cmp #40
        bcs csdone
        lda #31             ; cmd_get_channel
        sta TXBUF
        lda SCANI
        sta TXBUF+1
        lda #2
        sta TXLEN
        jsr sendfr
        lda #0
        sta STGBIT          ; not a handshake stage
        lda #18
        jsr waitop
        lda SCANI
        jsr chnptr
        ldy #0
        lda (PTR),y
        bne csnb
        inc BLANKS
        lda CF
        bne csnext
        lda BLANKS
        cmp #3
        bcs csdone
        jmp csnext
csnb:   lda #0
        sta BLANKS
csnext: inc SCANI
        jmp cslp
csdone: lda #1
        sta CKED
        rts

; ===== the picker ======================================================
; *** MESSAGES KEEP ARRIVING BEHIND THIS SCREEN. *** We must not stop
; polling while it is up: at 1200 the ring fills in seconds and an overrun
; does not merely lose bytes, it desyncs the frame parser. "Paused" here
; means paused from the DISPLAY only.
picker: lda #147
        jsr CHROUT
        lda #<msgchan
        sta PTR
        lda #>msgchan
        sta PTRH
        jsr prtstr
        lda CKED
        bne pkshow
        lda #<msgscan
        sta PTR
        lda #>msgscan
        sta PTRH
        jsr prtstr
        jsr chscan
pkshow: lda #147
        jsr CHROUT
        lda #<msgchan
        sta PTR
        lda #>msgchan
        sta PTRH
        jsr prtstr
; build the menu: map digits onto whatever slots actually have names, so a
; sparse setup still gets a dense list. "All" is synthetic, always first.
        lda #255
        sta PKMAP
        lda #1
        sta NPICK
        lda #0
        sta SCANI
pkbl:   lda SCANI
        cmp #40
        bcs pkbd
        lda NPICK
        cmp #10
        bcs pkbd
        lda SCANI
        jsr chnptr
        ldy #0
        lda (PTR),y
        beq pkbn
        ldx NPICK
        lda SCANI
        sta PKMAP,x
        inc NPICK
pkbn:   inc SCANI
        jmp pkbl
pkbd:   lda #0
        sta SCANI
pkdl:   lda SCANI
        cmp NPICK
        bcs pkdd
        lda #32
        jsr CHROUT
        lda SCANI
        clc
        adc #48
        jsr CHROUT
        lda #32
        jsr CHROUT
        lda #32
        jsr CHROUT
        ldx SCANI
        lda PKMAP,x
        cmp #255
        bne pkdnm
        lda #65
        jsr CHROUT
        lda #76
        jsr CHROUT
        lda #76
        jsr CHROUT
        jmp pkdmk
pkdnm:  jsr chnptr
        ldy #0
pkdnl:  lda (PTR),y
        beq pkdcn
        jsr CHROUT
        iny
        cpy #18
        bcc pkdnl
pkdcn:  ldx SCANI
        lda PKMAP,x
        tax
        lda CUNR,x
        beq pkdmk
        pha
        lda #32
        jsr CHROUT
        lda #40             ; '('
        jsr CHROUT
        pla
        jsr dec8
        sta TMP
        lda #3
        sec
        sbc TMP
        tay
pkdcl:  lda DECBUF,y
        jsr CHROUT
        iny
        cpy #3
        bcc pkdcl
        lda #41             ; ')'
        jsr CHROUT
pkdmk:  ldx SCANI
        lda PKMAP,x
        cmp CC
        bne pkdnx
        lda #32
        jsr CHROUT
        lda #42             ; '*' marks where you are
        jsr CHROUT
pkdnx:  lda #13
        jsr CHROUT
        inc SCANI
        jmp pkdl
pkdd:   lda #13
        jsr CHROUT
        lda #<msgfoot
        sta PTR
        lda #>msgfoot
        sta PTRH
        jsr prtstr
pkkey:  jsr poll
        lda READY
        beq pknk
        jsr dispat
        lda #0
        sta READY
pknk:   jsr GETIN
        cmp #0
        beq pkkey
        cmp #133
        beq pkend
        cmp #82             ; 'r'
        beq pkres
        cmp #210            ; shift-r
        beq pkres
        cmp #48
        bcc pkkey
        cmp #58
        bcs pkkey
        sec
        sbc #48
        cmp NPICK
        bcs pkkey
        tax
        lda PKMAP,x
        sta CC
pkend:  lda #147
        jsr CHROUT
        jmp setchan
pkres:  lda #1
        sta CF
        jsr chscan
        lda #0
        sta CF
        jmp pkshow

; ===== switch channel ==================================================
setchan:
        lda CC
        cmp CO
        beq screp2           ; same channel: still have to repaint, the
                            ; picker cleared the screen on its way out
        sta CO
        cmp #255
        beq scall
        tax
        lda CUNR,x
        sta TMP
        sta TMP2            ; how many to replay without an REU
        lda UT
        sec
        sbc TMP
        bcs scst
        lda #0
scst:   sta UT
        lda #0
        ldx CC
        sta CUNR,x
        jmp screp
scall:  lda #0
        sta UT
        sta TMP2
        jmp screp
; Cancelling the picker, or re-picking the channel you are already on,
; lands here -- nothing to replay, but the screen still needs painting.
screp2: lda #0
        sta TMP2
screp:  lda RU
        beq scnoreu
        jsr arcpage
        jmp scprm
; No archive to paint from, so at least say where we are -- the picker
; cleared the screen on its way out and a bare prompt looks like the
; channel lost its history.
scnoreu:
        lda #13
        jsr CHROUT
        lda #45
        jsr CHROUT
        lda #45
        jsr CHROUT
        lda #32
        jsr CHROUT
        ldx #0
scnl:   cpx PRLEN
        bcs scnd
        lda PROMPT,x
        cmp #62             ; stop at the '>' -- name only
        beq scnd
        jsr CHROUT
        inx
        jmp scnl
scnd:   lda #13
        jsr CHROUT
        jsr hreplay
scprm:  jsr setprm
        jsr shoprm
        rts

; ===== non-REU replay ring =============================================
; With no REU there is no archive, so keep the last 24 messages in RAM and
; replay the ones for a channel when you switch to it. Only the UNREAD
; ones: anything you were already watching has been on screen once.

; PTR -> ring slot Y (40 bytes each: x32 + x8)
hraddr: tya
        sta CNT2
        lda #0
        sta PTRH
        lda CNT2
        sta PTR
        asl PTR
        rol PTRH
        asl PTR
        rol PTRH
        asl PTR
        rol PTRH            ; x8
        lda PTR
        sta CNT2
        lda PTRH
        sta BLANKS
        asl PTR
        rol PTRH
        asl PTR
        rol PTRH            ; x32
        lda PTR
        clc
        adc CNT2
        sta PTR
        lda PTRH
        adc BLANKS
        sta PTRH            ; x40
        lda PTR
        clc
        adc #<HRTX
        sta PTR
        lda PTRH
        adc #>HRTX
        sta PTRH
        rts

hput:   lda RU
        bne hprt            ; the archive already covers this
        ldy HRH
        jsr hraddr
        ldx #11
        ldy #0
hpsl:   cpx CLEN
        bcs hpsd
        cpy #39
        bcs hpsd
        lda CBUF,x
        sta (PTR),y
        inx
        iny
        jmp hpsl
hpsd:   lda #0
        sta (PTR),y         ; terminate, so trailing spaces are not printed
        ldy HRH
        lda TMP
        sta HRCH,y
        inc HRH
        lda HRH
        cmp #24
        bcc hpn
        lda #0
        sta HRH
hpn:    lda HRN
        cmp #24
        bcs hprt
        inc HRN
hprt:   rts

; oldest = (HRH + 24 - HRN) mod 24
holdest:
        lda HRH
        clc
        adc #24
        sec
        sbc HRN
hol1:   cmp #24
        bcc hol2
        sec
        sbc #24
        jmp hol1
hol2:   sta HOLD
        rts

; slot for ring position X
hslot:  txa
        clc
        adc HOLD
hsl1:   cmp #24
        bcc hsl2
        sec
        sbc #24
        jmp hsl1
hsl2:   rts

hreplay:
        lda RU
        bne hrrt
        lda TMP2
        beq hrrt
        lda HRN
        beq hrrt
        jsr holdest
; count how many entries belong to this channel. the ring may have rolled
; over and dropped some of what we counted, so never print more than we
; actually still hold.
        lda #0
        sta CNT
        ldx #0
hrc:    cpx HRN
        bcs hrc2
        jsr hslot
        tay
        lda HRCH,y
        cmp CC
        bne hrcn
        inc CNT
hrcn:   inx
        jmp hrc
hrc2:   lda CNT
        sec
        sbc TMP2
        bcs hrs
        lda #0
hrs:    sta TMP             ; how many of the matches to skip
        ldx #0
hrp:    cpx HRN
        bcs hrrt
        jsr hslot
        tay
        lda HRCH,y
        cmp CC
        bne hrpn
        lda TMP
        beq hrpp
        dec TMP
        jmp hrpn
hrpp:   txa
        pha
        jsr hprint
        pla
        tax
hrpn:   inx
        jmp hrp
hrrt:   rts

hprint: jsr hraddr
        ldy #0
hpl:    cpy #40
        bcs hpd
        lda (PTR),y
        beq hpd
        jsr CHROUT
        iny
        jmp hpl
hpd:    lda #13
        jsr CHROUT
        rts

; ===== f3 status =======================================================
status: lda #13
        jsr CHROUT
        lda #<msgstat
        sta PTR
        lda #>msgstat
        sta PTRH
        jsr prtstr
        lda NFRM
        jsr hexout
        lda #32
        jsr CHROUT
        lda RJ
        jsr hexout
        lda #32
        jsr CHROUT
        lda OVR
        jsr hexout
        jsr shoprm
        rts

hexout: pha
        lsr
        lsr
        lsr
        lsr
        jsr hexdig
        jsr CHROUT
        pla
        and #15
        jsr hexdig
        jsr CHROUT
        rts

; ===== data ============================================================
; bit period and one-and-a-half bit periods, in cpu cycles, patched by the
; build for the requested baud rate
btlo:   .byte 0
bthi:   .byte 0
hblo:   .byte 0
hbhi:   .byte 0
; bit period and first-sample delay, PAL then NTSC, filled in by the build
bitpal: .byte 0,0,0,0
bitntsc: .byte 0,0,0,0
blankb: .byte 0
testk:  .byte 0             ; nonzero = run the scripted keypresses
pyastart: .byte 1,0,0,0,0,0,0,0,67,54,52
pyquery:  .byte 22,3
pychan:   .byte 31,0
pytime:   .byte 5
banner: .text "meshcore 64  v2.01"
        .byte 13,0
msgcon: .text "connecting..."
        .byte 13,0
msgrdy: .text "connected."
        .byte 13,13,0
msgpick: .text "pick a channel to send"
        .byte 13,0
msgchan: .text "channels"
        .byte 13,13,0
msgscan: .text "scanning..."
        .byte 13,0
msgfoot: .text "0-9 select   r rescan   f1 cancel"
        .byte 13,0
msgstat: .text "frames/rej/hw "
        .byte 0
"""

RATES = {7: 600, 8: 1200, 10: 2400, 11: 4800, 12: 9600}


NTSC = 1022727


def build(ctrl=7, out=OUT, blank=0, clock=PAL, testk=0, latadj=275):
    baud = RATES[ctrl]
    bit = int(round(clock / float(baud)))
    # 1.5 bit times to reach the centre of data bit 0, less a rough
    # allowance for NMI entry (7 cycles) plus the kernal's SEI/JMP and our
    # own register saves -- about 40 cycles before the first store lands.
    # Cycles from the start-bit edge to the timer actually starting:
    #   ~7 nmi sequence + ~7 finishing the current instruction
    #   + 7  kernal $fe43 SEI + JMP ($0318)
    #   + 13 our register saves
    #   + 12 reading/testing the ICR
    #   + 22 loading and starting timer B
    # ~68 nominal, up to ~110 if a badline lands in the middle of it.
    # Subtracting the average puts the first sample near the bit centre;
    # LATADJ lets that be swept, because getting it wrong shows up as
    # samples drifting toward a bit edge where badline jitter tips them over.
    half = int(round(bit * 1.5)) - latadj
    code, syms = assemble(SRC, ORG, EQU)
    code = bytearray(code)
    nbit = int(round(NTSC / float(baud)))
    nhalf = int(round(nbit * 1.5)) - latadj
    vals = [("btlo", bit & 0xFF), ("bthi", bit >> 8),
            ("hblo", half & 0xFF), ("hbhi", half >> 8),
            ("blankb", blank), ("testk", testk)]
    # the runtime table: PAL quad then NTSC quad, contiguous
    for i, v in enumerate([bit & 0xFF, bit >> 8, half & 0xFF, half >> 8,
                           nbit & 0xFF, nbit >> 8, nhalf & 0xFF, nhalf >> 8]):
        code[syms["bitpal"] - ORG + i] = v
    for name, val in vals:
        code[syms[name] - ORG] = val
    prg = bytes([ORG & 0xFF, ORG >> 8]) + bytes(code)
    with open(out, "wb") as f:
        f.write(prg)
    return code, syms, prg, bit, half


if __name__ == "__main__":
    ctrl = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    out = sys.argv[2] if len(sys.argv) > 2 else OUT
    blank = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    testk = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    latadj = int(sys.argv[5]) if len(sys.argv) > 5 else 275
    code, syms, prg, bit, half = build(ctrl, out, blank, PAL, testk, latadj)
    print("; %d baud: PAL %d cycles/bit (sample %d), NTSC %d (%d)"
          % (RATES[ctrl], bit, half, int(round(NTSC / float(RATES[ctrl]))),
             int(round(NTSC / float(RATES[ctrl])) * 1.5) - latadj))
    print("; assembled %d bytes at $%04X" % (len(code), ORG))
    for n in ("main", "serini", "nmih", "txbyte", "sendfr", "poll", "handshk"):
        print(";   %-8s = $%04X" % (n, syms[n]))
    print("; wrote %s (%d bytes)" % (out, len(prg)))
