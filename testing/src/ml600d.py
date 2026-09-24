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
    "TXW":     0xCFFD,
    "hvlo":    0x0000,
    "hvhi":    0x0000,   # last timer-A high byte seen by txwait
    "TMP2":    0xCF3A,
    "CF":      0xCF3E,   # full 40-slot sweep
    "OLDT":    0xCF3F,
    "DECBUF":  0xC860,   # 12 bytes
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
    "HOLD":    0xCFA2,   # index of the oldest entry
    "ISNTSC":  0xCFA3,
    "RAWHI":   0xCFA4,
    "UNK":     0xCFA5,   # frames with an opcode outside the protocol
    "PBAD":    0xCFA6,   # frames rejected at the length header
    "SPL":     0x00FD,   # splash unpack destination -- MUST be zero page
    "SPH":     0x00FE,
    # The kernal's rs-232 buffers are at $f7-$fa and we do not use them --
    # we have our own receiver -- so that pair is free for a second pointer.
    "PTR2":    0x00F7,
    "PTR2H":   0x00F8,
    "COLRAM":  0xD800,
    # ---- menu state ----
    "MNX":     0xCFB0,
    "MNY":     0xCFB1,
    "MNW":     0xCFB2,
    "MNN":     0xCFB3,
    "MNSEL":   0xCFB4,
    "MNPTR":   0x00F9,   # -> table of string pointers; MUST be zero page
    "MNPTRH":  0x00FA,
    "MNTIT":   0xCFB7,   # -> title string
    "MNTITH":  0xCFB8,
    "MNI":     0xCFB9,
    "MNJ":     0xCFBA,
    "MNJ2":    0xCFBB,
    "MNSELI":  0xCFBC,
    "SPH2":    0xCFBD,
    "MNROW":   0xCFBE,   # screen row scrpos works on
    "MNIDX":   0xCFBF,   # which item we are drawing
    "MNCOL":   0xCFC0,   # column within the box
    "MNTMP":   0xCFC1,
    "UIMODE":  0xCFC2,
    "MNCLR":   0xCFC3,   # colour mnput paints with
    # ---- contacts ----
    # 32 slots of 64 bytes, so one (PTR),y reaches every field:
    #   0-16 name, 17-48 public key, 49 out_path_len, 50-57 route, 58 type
    # 96 slots with an REU (where the archive lives in the REU and main
    # RAM is idle), 32 without (where it competes with the archive).
    "CONTACTS": 0x8000,
    "MAXCON":  0xCFF4,
    "NODETAB": 0x9B00,   # runtime table of name pointers, 96 x 2
    "NDOFF":   0xCFF5,   # first visible entry, for scrolling
    "SMC":     0xCFF6,   # index of the colon that ends the sender name
    "SMH":     0xCFF7,   # name hash, picks the sender colour
    "SMX":     0xCFF8,
    "LEDLST":  0xCFF9,
    "HSRTY":   0xCFFE,   # app_start attempts
    "WTMO":    0xCFFF,   # waitop timeout, in jiffy wraps   # count the lamps are currently showing
    "NCONT":   0xCFC4,
    "CIDX":    0xCFC5,   # which contact is selected
    "DMON":    0xCFC6,   # 1 = typing goes to a contact, not a channel
    "DMKEY":   0xCFC7,   # 6-byte key prefix of that contact
    "CTMP":    0xCFCE,
    # ---- info panel ----
    "PLBUF":   0xC900,   # eight rendered lines, 32 bytes each -- $c900..$c9ff, full
    "PLTAB":   0xC840,   # pointer table -- must NOT sit inside PLBUF
    "PLBASE":  0xCFF0,   # which buffer plnew fills (2 bytes)
    # ---- archive in main RAM, when there is no REU ----
    # The splash bitmap's 16K, reclaimed the moment the splash is done.
    # 409 lines of 40 bytes, one merged feed rather than nine regions:
    # nine would be 28 lines each, barely better than the 24-line ring
    # this replaces.
    "ARCRAM":  0x4000,
    "ARCTL":   0xCFF2,   # scratch for the slot x40 multiply
    "ARCTH":   0xCFF3,
    "PKBUF":   0x9800,   # the picker's own lines: 10 x 32
    "PLN":     0xCFCF,   # how many lines are in use
    "PLCOL":   0xCFD0,   # write cursor within the current line
    "NUML":    0xCFD1,   # 16-bit working value for decimal output
    "NUMH":    0xCFD2,
    "NUM2":    0xCFE4,
    "NUM3":    0xCFE5,
    "REM":     0xCFD3,
    "DECN":    0xCFD4,
    "FWVER":   0xC880,   # firmware version string from DEVICE_INFO
    "NODENM":  0x9A00,   # node's own name, from SELF_INFO (20 bytes)
    # ---- radio parameters, as reported by SELF_INFO ----
    "RFREQ":   0xCFD5,   # 4 bytes, kHz
    "RBW":     0xCFD9,   # 4 bytes, Hz
    "RSF":     0xCFDD,
    "RCR":     0xCFDE,
    "RPWR":    0xCFDF,
    "RMAXP":   0xCFE0,
    "RIDX":    0xCFE1,   # which preset each cycling field is on
    "RBIDX":   0xCFE2,
    "RPIDX":   0xCFE3,
    # ---- text input ----
    # ONE copy, in ascii. The chat input keeps a second petscii copy
    # because it echoes with CHROUT; this field draws through a2s, which
    # wants ascii, so a petscii copy would only ever be converted twice --
    # which is exactly what made a typed "c64" display as "C64".
    "INPASC":  0xC8C0,
    "INPLEN":  0xCFE6,
    "INPOK":   0xCFE7,
    # ---- channel editing ----
    "CHNAME":  0x9940,   # 32-byte name, staged away from INPASC
    "SECBUF":  0xC8E0,   # 16-byte channel secret
    "CHIDX":   0xCFE8,
    # ---- telemetry decoding ----
    "LPPI":    0xCFE9,   # read position in the received frame
    "LPPC":    0xCFEA,   # lpp channel
    "LPPT":    0xCFEB,   # lpp type
    "DECS":    0xCFEC,   # decimal places for plfix
    "FRAC1":   0xCFED,
    "FRAC2":   0xCFEE,
    "LSIGN":   0xCFEF,   # a menu is on screen: drain, but do not print
    "VICD018": 0xD018,
    "VICBG":   0xD021,
    "TXTCOL":  0x0286,   # kernal current text colour
    "SCRRAM":  0x0400,
    "BMCOL":   0x6400,   # splash colour map, in VIC bank 1
    "BMBASE":  0x4000,   # splash bitmap, in VIC bank 1
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
noblnk: lda #0              ; black ground and border: this is a terminal,
        sta VICBG           ; not a BASIC prompt
        sta BORDER
        lda #5              ; green text, the classic terminal look
        sta TXTCOL
        lda #147
        jsr CHROUT
        lda #14
        jsr CHROUT
        jsr splash              ; logo first, then the text banner
        lda #159                ; cyan, as the wordmark on the splash
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
; The boot screen prints the node name and firmware version, and both are
; only ever written by their handlers. A handshake that misses SELF_INFO
; or DEVICE_INFO -- which happens, see the known fault -- would otherwise
; print whatever this RAM held at power-on.
        lda #63             ; '?'
        sta NODENM
        sta FWVER
        lda #0
        sta NODENM+1
        sta FWVER+1
        sta CC
        lda #255
        sta CO              ; force the first setchan to paint
        jsr detpal
        jsr ledboot
        jsr reudet
        jsr serini

        jsr bootinf
        lda #158                ; yellow: still working
        jsr CHROUT
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

; ===== what this machine is ===========================================
; Printed after detpal and reudet, before the link is opened: everything
; here is known without the radio.
bootinf:
        lda #155                ; grey labels, white values
        jsr CHROUT
        lda #<svideo
        sta PTR
        lda #>svideo
        sta PTRH
        jsr prtstr
        lda #5
        jsr CHROUT
        lda ISNTSC
        beq bipal
        lda #<sntsc
        sta PTR
        lda #>sntsc
        sta PTRH
        jmp bivd
bipal:  lda #<spal
        sta PTR
        lda #>spal
        sta PTRH
bivd:   jsr prtstr
        lda #13
        jsr CHROUT
; the REU, and how big
        lda #155
        jsr CHROUT
        lda #<sreu
        sta PTR
        lda #>sreu
        sta PTRH
        jsr prtstr
        lda #5
        jsr CHROUT
        lda RU
        beq bino
        lda UKL
        sta NUML
        lda UKH
        sta NUMH
        jsr prdec
        lda #<skb
        sta PTR
        lda #>skb
        sta PTRH
        jmp birt
bino:   lda #<snone
        sta PTR
        lda #>snone
        sta PTRH
birt:   jsr prtstr
        lda #13
        jsr CHROUT
        rts

; ===== what the radio is ==============================================
; Only callable after the handshake: both of these arrive in it.
radinf: lda #155
        jsr CHROUT
        lda #<sradio
        sta PTR
        lda #>sradio
        sta PTRH
        jsr prtstr
        lda #5
        jsr CHROUT
        lda #<NODENM
        sta PTR
        lda #>NODENM
        sta PTRH
        jsr prtstr
        lda #13
        jsr CHROUT
        lda #155
        jsr CHROUT
        lda #<sfwv
        sta PTR
        lda #>sfwv
        sta PTRH
        jsr prtstr
        lda #5
        jsr CHROUT
        lda #<FWVER
        sta PTR
        lda #>FWVER
        sta PTRH
        jsr prtstr
        lda #13
        jsr CHROUT
        rts

; ===== the function keys ==============================================
keyhelp:
        lda #13
        jsr CHROUT
        lda #154                ; light blue, matching the menu frames
        jsr CHROUT
        lda #<skeys
        sta PTR
        lda #>skeys
        sta PTRH
        jsr prtstr
        lda #30                 ; back to green for the chat
        jsr CHROUT
        rts

; NUMH:NUML as decimal, straight to the screen. pldec builds into the
; panel buffer, which is not what the boot screen wants.
prdec:  lda #0
        sta DECN
prdl:   lda NUML
        ora NUMH
        beq prd2
        jsr div10
        clc
        adc #48
        ldx DECN
        sta DECBUF,x
        inc DECN
        lda DECN
        cmp #5
        bcc prdl
prd2:   lda DECN
        bne prd3
        lda #48
        jsr CHROUT
        rts
prd3:   ldx DECN
prd4:   dex
        lda DECBUF,x
        jsr CHROUT
        cpx #0
        bne prd4
        rts

; ===== screen plumbing =================================================
; The menu is poked straight into screen RAM. Printing it with CHROUT
; would scroll the chat underneath and could never be lifted off again.
; Colour RAM sits exactly $d400 above screen RAM, so one computed address
; serves both.
scrpos: ldy MNROW
        lda rowlo,y
        clc
        adc MNX
        sta PTR
        sta PTR2
        lda rowhi,y
        adc #0              ; carry from the column add
        sta PTRH
        clc
        adc #212            ; +$d400 -> the matching colour cell
        sta PTR2H
        rts

; store A as a screen code at (PTR),y and light the colour cell
mnput:  sta (PTR),y
        pha
        lda MNCLR
        sta (PTR2),y
        pla
        rts

; ascii -> screen code. lowercase becomes 1-26, which the lowercase
; charset draws as lowercase; everything else is already correct.
a2s:    cmp #97
        bcc a2srt
        cmp #123
        bcs a2srt
        sec
        sbc #96
a2srt:  rts

; write the null-terminated string at SPL into the current row, starting
; at column MNCOL
mnstr:  ldy #0
mnsl:   lda (SPL),y
        beq mnsrt
        jsr a2s
        sty MNTMP
        ldy MNCOL
        jsr mnput
        inc MNCOL
        ldy MNTMP
        iny
        jmp mnsl
mnsrt:  rts

; ===== draw the frame ==================================================
mnbox:  lda #14             ; light blue frame
        sta MNCLR
        lda MNY
        sta MNROW
        jsr scrpos
        ldy #0
        lda #112            ; top-left
        jsr mnput
        ldy #1
mnbt:   cpy MNW
        bcs mnbt2
        lda #64             ; horizontal
        jsr mnput
        iny
        jmp mnbt
mnbt2:  lda #110            ; top-right
        jsr mnput
; one pair of verticals per item row
        lda #0
        sta MNIDX
mnsd:   lda MNIDX
        cmp MNN
        bcs mnbot
        lda MNY
        clc
        adc MNIDX
        adc #1
        sta MNROW
        jsr scrpos
        ldy #0
        lda #93             ; vertical
        jsr mnput
        ldy MNW
        lda #93
        jsr mnput
        inc MNIDX
        jmp mnsd
mnbot:  lda MNY
        clc
        adc MNN
        adc #1
        sta MNROW
        jsr scrpos
        ldy #0
        lda #109            ; bottom-left
        jsr mnput
        ldy #1
mnbb:   cpy MNW
        bcs mnbb2
        lda #64
        jsr mnput
        iny
        jmp mnbb
mnbb2:  lda #125            ; bottom-right
        jsr mnput
; the title sits in the top edge
        lda MNY
        sta MNROW
        jsr scrpos
        lda MNTIT
        sta SPL
        lda MNTITH
        sta SPH
        lda #7              ; yellow title
        sta MNCLR
        lda #2
        sta MNCOL
        jsr mnstr
        rts

; ===== draw the items, highlighting the selection ======================
mnitems:
        lda #0
        sta MNIDX
mnil:   lda MNIDX
        cmp MNN
        bcs mnirt
        lda MNY
        clc
        adc MNIDX
        adc #1
        sta MNROW
        jsr scrpos
; clear the row first, so a shorter item leaves no debris behind it
        lda #0
        sta MNCLR
        ldy #1
mnib:   cpy MNW
        bcs mnib2
        lda #32
        jsr mnput
        iny
        jmp mnib
mnib2:  ldy MNIDX           ; each entry its own colour, BBS style
        lda mnclrs,y
        sta MNCLR
        lda MNIDX
        asl
        tay
        lda (MNPTR),y
        sta SPL
        iny
        lda (MNPTR),y
        sta SPH
        lda #2
        sta MNCOL
        jsr mnstr
        lda MNIDX
        cmp MNSEL
        bne mnin
        jsr mninv
mnin:   inc MNIDX
        jmp mnil
mnirt:  rts

; reverse video across the row: bit 7 of a screen code
mninv:  ldy #1
mnvl:   cpy MNW
        bcs mnvrt
        lda (PTR),y
        ora #128
        sta (PTR),y
        iny
        jmp mnvl
mnvrt:  rts

; ===== run the menu ====================================================
; in:  MNX MNY MNW MNN MNPTR MNTIT     out: MNSEL, or 255 if cancelled
menu:   lda #1
        sta UIMODE
        jsr mnbox
        jsr mnitems
mnkey:  jsr tkey            ; test only; a no-op in a real build
        jsr poll            ; *** the link keeps running behind the menu ***
        lda READY
        beq mnk2
        jsr dispat
        lda #0
        sta READY
mnk2:   jsr GETIN
        cmp #0
        beq mnkey
        cmp #17             ; cursor down
        beq mndn
        cmp #145            ; cursor up
        beq mnup
        cmp #13
        beq mnrt
        cmp #133            ; f1 closes it again
        beq mncan
        jmp mnkey
mndn:   lda MNSEL
        clc
        adc #1
        cmp MNN
        bcc mndn2
        lda #0
mndn2:  sta MNSEL
        jsr mnitems
        jmp mnkey
mnup:   lda MNSEL
        bne mnup2
        lda MNN
mnup2:  sec
        sbc #1
        sta MNSEL
        jsr mnitems
        jmp mnkey
mncan:  lda #255
        sta MNSEL
mnrt:   lda #0
        sta UIMODE
        rts

; ===== splash screen ===================================================
; The wordmark as a hires bitmap. Hires wants $2000-$3f3f, and the packed
; logo is the last thing in the program -- which lands inside that region
; once the client grows. So stage the packed data up at $4000 first and
; unpack from there; the bitmap then overwrites the original copy, which
; by that point nothing needs. Afterwards $2000-$3fff is free again.
splash: lda blankb
        bne sprt                ; nothing to look at with the screen off

; VIC bank 1 ($4000-$7fff). Bits 0-1 of $dd00 pick the bank and are
; INVERTED, so %10 selects bank 1. Bit 2 of that port is our TXD, hence
; read-modify-write.
        lda C2PRA
        and #252
        ora #2
        sta C2PRA

; clear the bitmap
        lda #0
        sta SPL
        lda #64                 ; $4000
        sta SPH
        ldx #32
spclr:  ldy #0
        lda #0
spclr2: sta (SPL),y
        iny
        bne spclr2
        inc SPH
        dex
        bne spclr

; unpack straight out of the program -- no staging needed now that the
; bitmap is nowhere near it
        lda #<logodat
        sta PTR
        lda #>logodat
        sta PTRH
        lda #0
        sta SPL
        lda #64
        sta SPH
spunl:  ldy #0
        lda (PTR),y
        beq spudn
        sta CNT
        jsr spinc
        ldy #0
        lda (PTR),y
        sta TMP
        jsr spinc
        ldx CNT
spwr:   ldy #0
        lda TMP
        sta (SPL),y
        inc SPL
        bne spw2
        inc SPH
spw2:   dex
        bne spwr
        jmp spunl
spinc:  inc PTR
        bne spi2
        inc PTRH
spi2:   rts

; In hires the colour comes from the video matrix: high nibble is the
; 1-bits, low nibble the 0-bits.
spudn:
; In hires the colour comes from the video matrix: high nibble is the
; 1-bits, low nibble the 0-bits. The splash is horizontal bands, so the
; generator emits one byte per row and this fans each out across its 40
; cells -- 25 bytes of data instead of 1000.
        lda #<BMCOL
        sta SPL
        lda #>BMCOL
        sta SPH
        ldx #0
spcr:   lda logocol,x
        ldy #0
spcr2:  sta (SPL),y
        iny
        cpy #40
        bcc spcr2
        lda SPL
        clc
        adc #40
        sta SPL
        bcc spcr3
        inc SPH
spcr3:  inx
        cpx #25
        bcc spcr
        lda #0
        sta BORDER
        lda #59                 ; $3b: bitmap on, display on
        sta VICCTL2
        lda #144                ; $90: screen $6400, bitmap $4000
        sta VICD018
        ldx #140
sphold: jsr wait1
        dex
        bne sphold
; back to a normal text screen in bank 0
        lda C2PRA
        and #252
        ora #3                  ; %11 -> bank 0
        sta C2PRA
        lda #27                 ; $1b
        sta VICCTL2
; $17, not $15: CB=3 is the LOWERCASE charset at $1800. $15 is the
; uppercase/graphics set, in which lowercase ascii renders as line noise.
        lda #23                 ; $17
        sta VICD018
        lda #0
        sta VICBG
        sta BORDER
        lda #5
        sta TXTCOL
        lda #147
        jsr CHROUT
sprt:   rts

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
        ldx #6
dpcp:   lda bitpal,x
        sta btlo
        lda bitpal+1,x
        sta bthi
        lda bitpal+2,x
        sta hblo
        lda bitpal+3,x
        sta hbhi
        lda bitpal+4,x
        sta hvlo
        lda bitpal+5,x
        sta hvhi
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

; --- an edge: a start bit, or a glitch ---
; Aim HALF a bit in, not one and a half, so the start bit itself can be
; checked before committing to the byte.
        lda hvlo
        sta C2TBLO
        lda hvhi
        sta C2TBHI
        lda #25             ; one-shot, force load, start
        sta C2CRB
        lda #127
        sta C2ICR
        lda #130            ; now interrupt on timer B instead
        sta C2ICR
        lda #10             ; 10 = still verifying the start bit
        sta BITCNT
        jmp nmx

nmtb:   lda ICRSV
        and #2              ; timer B?
        beq nmx
        lda BITCNT
        cmp #10
        beq nmvfy           ; the start-bit check
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
nmnorl: dec BITCNT
        beq nmbyte
        jmp nmx

; **Verify the start bit, which is what the kernal does and we did not.**
;
; Half a bit in, a real start bit is still low. If the line has gone high
; this edge was a glitch, or the tail of a byte we already mis-read.
; Committing to nine more samples turns one bad edge into a bad byte --
; and that byte's own 1->0 transitions produce more false starts, which
; produce more bad bytes. The cascade is what "Nff Bff frames 00" looks
; like on real hardware: edges and bytes saturated, not one valid frame.
nmvfy:  lda C2PRB
        and #1
        beq nmvok           ; still low: a real start bit
; glitch. Drop it and wait for the next edge rather than reading rubbish.
        lda #0
        sta C2CRB
        lda #127
        sta C2ICR
        lda C2ICR
        lda #144
        sta C2ICR
        jmp nmx
; Genuine. A full bit period, continuous, so the next interrupt lands one
; and a half bits from the edge -- the centre of data bit 0 -- and every
; one after it on the centre of its own bit.
nmvok:  lda btlo
        sta C2TBLO
        lda bthi
        sta C2TBHI
        lda #17             ; force load, start, CONTINUOUS
        sta C2CRB
        lda #9
        sta BITCNT
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
; **Never read the interrupt register to time a bit.**
;
; Reading $dd0d CLEARS it. On a real 6526, a read landing in the same
; cycle the timer sets its underflow flag loses that flag -- a documented
; hazard, and one VICE does not reproduce. Polling every ~8 cycles against
; a 1642-cycle bit gives each bit roughly a 1-in-200 chance of missing its
; underflow and running on to DOUBLE length. Across a 110-bit frame that
; is near certain, so the radio sees a malformed frame, never gets a valid
; APP_START, and never answers. Every emulator test passed regardless.
;
; Reading the COUNTER has no side effects. Timer A stays continuous, so
; there is still no per-bit reload and no accumulating error: watch the
; high byte count down and return the moment it jumps back up, which only
; happens on reload.
txwait: lda C2TAHI
        sta TXW
txwl:   lda C2TAHI
        cmp TXW
        beq txwl            ; unchanged, still counting within this byte
        bcs txwrt           ; went UP = the timer reloaded = underflow
        sta TXW             ; went down, as expected; keep watching
        jmp txwl
txwrt:  rts

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
; **Clear the latch only when the line is idle.**
;
; FLAG is wired to the INCOMING line, so nothing we transmit can latch a
; false edge. Two things can: a radio push that arrived mid-transmit (its
; data bits are full of 1->0 edges, and acting on one mid-byte gives
; garbage), or the radio starting its reply in the gap between our last
; stop bit and here. The old code cleared unconditionally and so threw
; away every reply that landed in that gap.
;
; The line itself tells them apart. Idle high means nothing is in flight
; and any latched edge is stale, so clear it. Low means a start bit is
; under way right now -- keep it, and take the interrupt a few cycles
; late, which at 600 baud costs nothing.
        lda C2PRB
        and #1
        beq sfkeep          ; line low: a start bit is happening, keep it
        lda #127
        sta C2ICR
        lda C2ICR           ; idle: discard anything stale
sfkeep: lda #144
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
; a length byte that cannot be real means we locked onto a '>' sitting
; inside payload data -- count it, it is the other half of the same story
pbad:   inc PBAD
        lda #0
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

; The periodic status broadcast is TEST INSTRUMENTATION. It posts the
; client's counters to the Public channel so the regression harness can
; read them, and on a real mesh that is thirteen seconds of noise, forever,
; for everyone in range. It rides on the same flag as the scripted keys:
; a release build has testk = 0 and says nothing it was not asked to.
chktik: lda testk
        beq ctrt
        lda JIFFY
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
ctrt:   rts

handshk:
        lda #7              ; the normal, patient timeout
        sta WTMO
; **Three seconds before saying anything.** The C64 boots from cartridge
; in about two; the radio has bluetooth, a display and a LoRa front end to
; bring up and takes longer. The kernal build waits this long by accident
; and connects; this one waited 1.2s and did not.
        ldx #150
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

; Four tries at eight seconds rather than one at thirty.
        lda #0
        sta HSRTY
        lda #2
        sta WTMO
hsrty:  lda #<pyastart
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
        lda BUF
        cmp #5              ; did SELF_INFO actually arrive?
        beq hsgot
        inc HSRTY
        lda HSRTY
        cmp #4
        bcc hsrty
hsgot:  lda #7
        sta WTMO

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

        lda #153                ; light green: we are up
        jsr CHROUT
        lda #<msgrdy
        sta PTR
        lda #>msgrdy
        sta PTRH
        jsr prtstr
        jsr radinf
        jsr keyhelp
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
        cmp WTMO
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
        cmp #3                  ; RESP_CODE_CONTACT
        beq dcont
        cmp #13                 ; RESP_CODE_DEVICE_INFO
        beq dinfo
        cmp #5                  ; RESP_CODE_SELF_INFO
        beq dself
        cmp #133                ; 0x85, push_code_login_success
        beq dlogin
; Not one we act on -- but is it one we RECOGNISE? An opcode outside the
; protocol's set is the signature of a desynced parser handing us a frame
; that started in the middle of another one. Until now those were dropped
; in silence with no counter at all, which is precisely why r00/e00 could
; read clean while a handshake reply went missing.
        cmp #0
        beq dkn
        cmp #2                  ; contacts start
        beq dkn
        cmp #4                  ; end of contacts
        beq dkn
        cmp #5
        beq dkn
        cmp #9
        beq dkn
        cmp #10
        beq dkn
        cmp #13
        beq dkn
        cmp #136
        beq dkn
        cmp #138
        beq dkn
        inc UNK
dkn:    rts
dchan:  jmp rxchan
dcont:  jmp rxcont
; fw_version is 20 bytes at offset 60 of the device-info frame
; SELF_INFO: 2 tx_power, 3 max_power, 48-51 freq(kHz), 52-55 bw(Hz),
; 56 sf, 57 cr
; Same rule as an incoming message: printing while a menu or panel is up
; would scroll it off the top.
dlogin: lda UIMODE
        bne dlgrt
        lda #<tlogok
        sta SPL
        lda #>tlogok
        sta SPH
        jmp prtsp
dlgrt:  rts

dself:  lda BUF+2
        sta RPWR
        lda BUF+3
        sta RMAXP
        ldx #0
dsl:    cpx #4
        bcs dsl2
        lda BUF+48,x
        sta RFREQ,x
        lda BUF+52,x
        sta RBW,x
        inx
        jmp dsl
dsl2:   lda BUF+56
        sta RSF
        lda BUF+57
        sta RCR
; the node's own name runs from offset 58 to the end of the frame
        ldx #0
dsnl:   cpx #19
        bcs dsnd
        txa
        clc
        adc #58
        tay
        cpy FLEN
        bcs dsnd
        lda BUF,y
        beq dsnd
        sta NODENM,x
        inx
        jmp dsnl
dsnd:   lda #0
        sta NODENM,x
        rts

dinfo:  ldx #0
dinf2:  cpx #19
        bcs dinf3
        lda CBUF+60,x
        beq dinf3
        sta FWVER,x
        inx
        jmp dinf2
dinf3:  lda #0
        sta FWVER,x
        rts
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
; refprm prints, and printing at the bottom of the screen scrolls it --
; which drags an open menu off the top. The counter is redrawn when the
; menu closes anyway.
dmsy:   lda UIMODE
        bne dmsy2
        jsr refprm          ; so the +N counter updates in place
dmsy2:  jmp sync
dmshow: inc MSGS
        bne dmnc
        inc MSGSH
; **Do not print while a menu is up.** The message is still collected and
; archived -- it has to be, the radio has one shared queue -- but printing
; it would scroll the screen and drag the menu off the top. This is the
; same rule the picker has always needed; it just never had a flag.
dmnc:   lda UIMODE
        bne dmnp
        jsr shomsg
dmnp:   jmp sync
dbad:   inc RJ
        jmp sync

; **Reuse the prompt's own row for the message.** Back up over
; prompt+typed text to column 0, write the message there, pad out whatever
; the longer prompt left behind, then redraw the prompt underneath. The
; messages flow, the prompt stays at the bottom, and nothing half-typed is
; lost -- it moves down with the prompt.
; A line is "[room] sender: message", or just "sender: message" outside
; the merged view. Each part gets its own colour, and the sender's is
; derived from their own name so it is the same from one line to the next.
;
; Colour codes go through CHROUT without moving the cursor, so the count
; used for padding is simply CLEN-11 -- counting printed bytes would
; include them and pad short.
shomsg: lda blankb
        bne smrt            ; nothing to look at with the screen off
        jsr bkprm
        lda #255
        sta SMC
        ldx #11
smfl:   cpx CLEN
        bcs smfd
        lda CBUF,x
        cmp #58             ; ':'
        beq smfg
        inx
        jmp smfl
smfg:   stx SMC
smfd:   ldx #11
        lda SMC
        cmp #255
        beq smbody          ; no sender field: a system line, left plain
; the room, when the merged view has prefixed one
        lda CBUF+11
        cmp #91             ; '['
        bne smname
        lda #159            ; cyan
        jsr CHROUT
smrl:   cpx CLEN
        bcs smname
        lda CBUF,x
        jsr CHROUT
        inx
        cmp #93             ; ']'
        bne smrl
        lda #32             ; the space the prefix ends with
        jsr CHROUT
        inx
; the sender: sum the name and index a small palette
smname: stx SMX
        lda #0
        sta SMH
smhl:   cpx SMC
        bcs smhd
        lda SMH
        clc
        adc CBUF,x
        sta SMH
        inx
        jmp smhl
smhd:   lda SMH
        and #7
        tay
        lda smpal,y
        jsr CHROUT
        ldx SMX
smnl:   cpx SMC
        bcs smbody
        lda CBUF,x
        jsr CHROUT
        inx
        jmp smnl
; the message itself
smbody: lda #30             ; green
        jsr CHROUT
sml:    cpx CLEN
        bcs smpad
        lda CBUF,x
        jsr CHROUT
        inx
        jmp sml
smpad:  lda CLEN
        sec
        sbc #11
        sta TMP
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

kbf1:   jmp mainmnu
kbf3:   jmp status
kbf5:   jmp scrollb
kbf7:   lda #0
        sta CC
        jmp setchan

; ===== text input ======================================================
; A one-line field in a menu frame. The text is kept in ASCII only: it
; goes to the wire as-is, and the menu drawer converts to screen codes
; through a2s, which is an ascii mapping. Storing petscii as well -- which
; is what the chat input does, because it echoes with CHROUT -- meant the
; field displayed "C64" for a typed "c64" while sending the lowercase
; form. What you saw was not what went out.
inpdraw:
        lda MNY
        clc
        adc #1
        sta MNROW
        jsr scrpos
        lda #1
        sta MNCLR
        ldy #1
inpd1:  cpy MNW
        bcs inpd2
        lda #32
        jsr mnput
        iny
        jmp inpd1
inpd2:  ldx #0
inpd3:  cpx INPLEN
        bcs inpd4
        stx CTMP
        lda INPASC,x
        jsr a2s
        ldy CTMP
        iny
        jsr mnput
        ldx CTMP
        inx
        jmp inpd3
inpd4:  ldy INPLEN          ; a reverse space for the cursor
        iny
        cpy MNW
        bcs inpd5
        lda #160
        jsr mnput
inpd5:  rts

; in: MNTIT = the prompt. out: INPOK = 1 if accepted, INPASC/INPLEN
inpget: lda #1
        sta UIMODE
        lda #0
        sta INPLEN
        lda #147
        jsr CHROUT
        lda #4
        sta MNX
        lda #8
        sta MNY
        lda #34             ; wide enough for a 32 digit key plus frame
        sta MNW
        lda #1
        sta MNN
        jsr mnbox
inpk:   jsr inpdraw
inpk2:  jsr tkey
        jsr poll            ; the link keeps running while you type
        lda READY
        beq inpk3
        jsr dispat
        lda #0
        sta READY
inpk3:  jsr GETIN
        cmp #0
        beq inpk2
        cmp #13
        beq inpok
        cmp #20
        beq inpdel
; The function keys are 133-136, inside the printable range, so they have
; to be caught before the range test or they land in the field as garbage
; -- the same trap the chat input already documents.
        cmp #133            ; f1 cancels
        beq inpcan
        cmp #134
        beq inpk2
        cmp #135
        beq inpk2
        cmp #136
        beq inpk2
        cmp #32
        bcc inpk2
        cmp #219            ; 193-218 are the shifted letters, and a node
        bcs inpk2           ; name may well want them
        ldx INPLEN
        cpx #32             ; a 128-bit key is exactly 32 hex digits
        bcs inpk2
; petscii -> ascii, the same case swap the chat input uses
        cmp #65
        bcc inpst
        cmp #91
        bcc inpup
        cmp #193
        bcc inpst
        cmp #219
        bcs inpst
        sec
        sbc #128
        jmp inpst
inpup:  clc
        adc #32
inpst:  ldx INPLEN
        sta INPASC,x
        inc INPLEN
        jmp inpk
inpdel: lda INPLEN
        beq inpk2
        dec INPLEN
        jmp inpk
inpok:  lda #1
        sta INPOK
        jmp inpend
inpcan: lda #0
        sta INPOK
inpend: lda #0
        sta UIMODE
        rts

; ===== info panel ======================================================
; Same frame as the menu, but the contents are built line by line and any
; key dismisses it. Route and stats both print into the chat otherwise,
; where the next incoming message scrolls them away.

; start a fresh panel
plinit: lda #0
        sta PLN
        lda #<PLBUF             ; the picker points this elsewhere
        sta PLBASE
        lda #>PLBUF
        sta PLBASE+1
        rts

; begin a new line
plnew:  lda #0
        sta PLCOL
        lda PLN
        sta PTR
        lda #0
        sta PTRH
        ldx #5
plnsh:  asl PTR                 ; x32, 16-bit: the picker can have ten
        rol PTRH                ; lines and 10*32 overflows a byte
        dex
        bne plnsh
        lda PTR
        clc
        adc PLBASE
        sta PTR
        lda PTRH
        adc PLBASE+1
        sta PTRH
; remember where it starts, for the pointer table
        lda PLN
        asl
        tay
        lda PTR
        sta PLTAB,y
        iny
        lda PTRH
        sta PLTAB,y
        rts

; append the character in A to the current line
plchr:  ldy PLCOL
        cpy #30
        bcs plcrt
        sta (PTR),y
        inc PLCOL
        ldy PLCOL
        lda #0
        sta (PTR),y             ; keep it terminated
plcrt:  rts

; append the null-terminated string at SPL
plstr:  ldy #0
pls2:   lda (SPL),y
        beq pls3
        sty CTMP
        jsr plchr
        ldy CTMP
        iny
        bne pls2
pls3:   rts

; finish the line
plend:  inc PLN
        rts

; append A as two hex digits
plhex:  pha
        lsr
        lsr
        lsr
        lsr
        jsr hexdig
        jsr plchr
        pla
        and #15
        jsr hexdig
        jsr plchr
        rts

; NUMH:NUML / 10, remainder in A -- the usual shift-and-subtract
div10:  lda #0
        sta REM
        ldx #32
d10l:   asl NUML
        rol NUMH
        rol NUM2
        rol NUM3
        rol REM
        lda REM
        sec
        sbc #10
        bcc d10n
        sta REM
        inc NUML
d10n:   dex
        bne d10l
        lda REM
        rts

; append NUMH:NUML as decimal. div10 yields digits least-significant
; first, so they are collected and then emitted in reverse.
pldec:  lda #0
        sta DECN
pld1:   lda NUML
        ora NUMH
        ora NUM2
        ora NUM3
        beq pld2
        jsr div10
        clc
        adc #48
        ldx DECN
        sta DECBUF,x
        inc DECN
        lda DECN
        cmp #10
        bcc pld1
pld2:   lda DECN
        bne pld3
        lda #48                 ; the value was zero
        jsr plchr
        rts
pld3:   ldx DECN
pld4:   dex
        lda DECBUF,x
        jsr plchr
        cpx #0
        bne pld4
        rts

; show the panel and wait for a key
plshow: lda #1
        sta UIMODE
        lda #147                ; a panel replaces the menu behind it
        jsr CHROUT
        lda #4
        sta MNX
        lda #6
        sta MNY
        lda #30
        sta MNW
        lda PLN
        sta MNN
        lda #<PLTAB
        sta MNPTR
        lda #>PLTAB
        sta MNPTRH
        lda #255                ; nothing highlighted: this is not a chooser
        sta MNSEL
        jsr mnbox
        jsr mnitems
plsk:   jsr poll
        lda READY
        beq plsk2
        jsr dispat
        lda #0
        sta READY
plsk2:  jsr GETIN
        cmp #0
        beq plsk
        lda #0
        sta UIMODE
        rts

; ===== link and radio stats ============================================
statvw: lda #20                 ; CMD_GET_BATT_AND_STORAGE
        sta TXBUF
        lda #1
        sta TXLEN
        jsr sendfr
        lda #0
        sta STGBIT
        lda #12                 ; RESP_CODE_BATT_AND_STORAGE
        jsr waitop
        jsr plinit
; battery, in millivolts
        jsr plnew
        lda #<sbatt
        sta SPL
        lda #>sbatt
        sta SPH
        jsr plstr
        lda BUF+1
        sta NUML
        lda BUF+2
        sta NUMH
        lda #0
        sta NUM2
        sta NUM3
        jsr pldec
        lda #<smv
        sta SPL
        lda #>smv
        sta SPH
        jsr plstr
        jsr plend
; storage used, in KB (low 16 bits is plenty for this display)
        jsr plnew
        lda #<sstor
        sta SPL
        lda #>sstor
        sta SPH
        jsr plstr
        lda BUF+3
        sta NUML
        lda BUF+4
        sta NUMH
        lda #0
        sta NUM2
        sta NUM3
        jsr pldec
        lda #<skb
        sta SPL
        lda #>skb
        sta SPH
        jsr plstr
        jsr plend
; our own link counters -- the ones that actually diagnose the radio link
        jsr plnew
        lda #<sframes
        sta SPL
        lda #>sframes
        sta SPH
        jsr plstr
        lda NFRM
        jsr plhex
        jsr plend
        jsr plnew
        lda #<srej
        sta SPL
        lda #>srej
        sta SPH
        jsr plstr
        lda RJ
        jsr plhex
        lda #32
        jsr plchr
        lda UNK
        jsr plhex
        lda #32
        jsr plchr
        lda PBAD
        jsr plhex
        jsr plend
        jsr plnew
        lda #<sframe
        sta SPL
        lda #>sframe
        sta SPH
        jsr plstr
        lda FRERR
        jsr plhex
        jsr plend
        jsr plnew
        lda #<sring
        sta SPL
        lda #>sring
        sta SPH
        jsr plstr
        lda OVR
        jsr plhex
        jsr plend
        lda #<tstats
        sta MNTIT
        lda #>tstats
        sta MNTITH
        jsr plshow
        jmp mmshut

; ===== radio configuration =============================================
; Each line renders the live value; RETURN on it steps to the next preset.
; "apply" writes them to the node.
radiovw:
        lda #1
        sta UIMODE
        lda #0
        sta MNSEL
rvdraw: jsr plinit
; --- frequency, shown in MHz from a kHz value ---
        jsr plnew
        lda #<srfreq
        sta SPL
        lda #>srfreq
        sta SPH
        jsr plstr
        lda RFREQ
        sta NUML
        lda RFREQ+1
        sta NUMH
        lda RFREQ+2
        sta NUM2
        lda RFREQ+3
        sta NUM3
        jsr pldec
        lda #<skhz
        sta SPL
        lda #>skhz
        sta SPH
        jsr plstr
        jsr plend
; --- bandwidth ---
        jsr plnew
        lda #<srbw
        sta SPL
        lda #>srbw
        sta SPH
        jsr plstr
        lda RBW
        sta NUML
        lda RBW+1
        sta NUMH
        lda RBW+2
        sta NUM2
        lda RBW+3
        sta NUM3
        jsr pldec
        lda #<shz
        sta SPL
        lda #>shz
        sta SPH
        jsr plstr
        jsr plend
; --- spreading factor ---
        jsr plnew
        lda #<srsf
        sta SPL
        lda #>srsf
        sta SPH
        jsr plstr
        lda RSF
        sta NUML
        lda #0
        sta NUMH
        sta NUM2
        sta NUM3
        jsr pldec
        jsr plend
; --- coding rate ---
        jsr plnew
        lda #<srcr
        sta SPL
        lda #>srcr
        sta SPH
        jsr plstr
        lda RCR
        sta NUML
        lda #0
        sta NUMH
        sta NUM2
        sta NUM3
        jsr pldec
        jsr plend
; --- transmit power ---
        jsr plnew
        lda #<srpwr
        sta SPL
        lda #>srpwr
        sta SPH
        jsr plstr
        lda RPWR
        sta NUML
        lda #0
        sta NUMH
        sta NUM2
        sta NUM3
        jsr pldec
        lda #<sdbm
        sta SPL
        lda #>sdbm
        sta SPH
        jsr plstr
        jsr plend
; --- node name ---
        jsr plnew
        lda #<srname
        sta SPL
        lda #>srname
        sta SPH
        jsr plstr
        jsr plend
; --- actions ---
        jsr plnew
        lda #<srapply
        sta SPL
        lda #>srapply
        sta SPH
        jsr plstr
        jsr plend
        jsr plnew
        lda #<srback
        sta SPL
        lda #>srback
        sta SPH
        jsr plstr
        jsr plend

        lda #147
        jsr CHROUT
        lda #4
        sta MNX
        lda #6
        sta MNY
        lda #28
        sta MNW
        lda PLN
        sta MNN
        lda #<PLTAB
        sta MNPTR
        lda #>PLTAB
        sta MNPTRH
        lda #<tradio
        sta MNTIT
        lda #>tradio
        sta MNTITH
        jsr menu
        lda MNSEL
        cmp #255
        beq rvdone
        cmp #0
        beq rvfreq
        cmp #1
        beq rvbw
        cmp #2
        beq rvsf
        cmp #3
        beq rvcr
        cmp #4
        beq rvpwr
        cmp #5
        beq rvname
        cmp #6
        beq rvapply
rvdone: lda #0
        sta UIMODE
        jmp mmshut

; step frequency through the common band presets
rvfreq: inc RIDX
        lda RIDX
        cmp #5
        bcc rvf2
        lda #0
        sta RIDX
rvf2:   lda RIDX
        asl
        asl
        tay
        ldx #0
rvf3:   lda freqtab,y
        sta RFREQ,x
        iny
        inx
        cpx #4
        bcc rvf3
        jmp rvdraw
; and bandwidth
rvbw:   inc RBIDX
        lda RBIDX
        cmp #4
        bcc rvb2
        lda #0
        sta RBIDX
rvb2:   lda RBIDX
        asl
        asl
        tay
        ldx #0
rvb3:   lda bwtab,y
        sta RBW,x
        iny
        inx
        cpx #4
        bcc rvb3
        jmp rvdraw
; sf 7..12, cr 5..8, power in 3dBm steps up to the node's maximum
rvsf:   inc RSF
        lda RSF
        cmp #13
        bcc rvs2
        lda #7
        sta RSF
rvs2:   jmp rvdraw
rvcr:   inc RCR
        lda RCR
        cmp #9
        bcc rvc2
        lda #5
        sta RCR
rvc2:   jmp rvdraw
rvpwr:  lda RPWR
        clc
        adc #3
        cmp RMAXP
        bcc rvp3
        beq rvp3
        lda #2
rvp3:   sta RPWR
        jmp rvdraw

; ask for a node name and set it
rvname: lda #<tname
        sta MNTIT
        lda #>tname
        sta MNTITH
        jsr inpget
        lda INPOK
        beq rvn3
        lda INPLEN
        beq rvn3
        lda #8                  ; CMD_SET_ADVERT_NAME
        sta TXBUF
        ldx #0
rvn2:   cpx INPLEN
        bcs rvn2d
        lda INPASC,x
        sta TXBUF+1,x
        inx
        jmp rvn2
rvn2d:  txa
        clc
        adc #1
        sta TXLEN
        jsr sendfr
rvn3:   lda #1
        sta UIMODE
        jmp rvdraw

; write them to the node: radio params, then tx power
rvapply:
        lda #11                 ; CMD_SET_RADIO_PARAMS
        sta TXBUF
        ldx #0
rva2:   lda RFREQ,x
        sta TXBUF+1,x
        lda RBW,x
        sta TXBUF+5,x
        inx
        cpx #4
        bcc rva2
        lda RSF
        sta TXBUF+9
        lda RCR
        sta TXBUF+10
        lda #11
        sta TXLEN
        jsr sendfr
        lda #12                 ; CMD_SET_RADIO_TX_POWER
        sta TXBUF
        lda RPWR
        sta TXBUF+1
        lda #2
        sta TXLEN
        jsr sendfr
        jsr plinit
        jsr plnew
        lda #<srsent
        sta SPL
        lda #>srsent
        sta SPH
        jsr plstr
        jsr plend
        lda #<tradio
        sta MNTIT
        lda #>tradio
        sta MNTITH
        jsr plshow
        jmp mmshut

; 869.525, 868.000, 915.000, 906.875, 433.500 -- all in kHz
freqtab: .byte 149,68,13,0
        .byte 160,62,13,0
        .byte 56,246,13,0
        .byte 123,214,13,0
        .byte 92,157,6,0
; 250k, 125k, 62.5k, 500k -- in Hz
bwtab:  .byte 144,208,3,0
        .byte 72,232,1,0
        .byte 36,244,0,0
        .byte 32,161,7,0

; ===== contacts ========================================================; ===== contacts ========================================================
; PTR -> contact slot for the index in A
contptr:
        sta PTR
        lda #0
        sta PTRH
        ldx #6
cptl:   asl PTR
        rol PTRH
        dex
        bne cptl
        lda PTR
        clc
        adc #<CONTACTS
        sta PTR
        lda PTRH
        adc #>CONTACTS
        sta PTRH
        rts

; RESP_CODE_CONTACT: 1-32 key, 33 type, 34 flags, 35 out_path_len,
; 36-99 route, 100-131 name. Keep the parts we can act on.
rxcont: lda NCONT
        cmp MAXCON
        bcs rxcrt               ; table full; the rest are dropped
        lda NCONT
        jsr contptr
; Take the name from the RAW frame, not the converted copy. conv() makes
; PETSCII for CHROUT, but the menu draws through a2s, which expects ASCII
; -- running both turned every name uppercase.
        ldy #0
rxcnl:  cpy #16
        bcs rxcnd
        lda BUF+100,y
        beq rxcnd
        cmp #32                 ; keep anything unprintable out of the list
        bcc rxcdot
        cmp #127
        bcc rxcsv
rxcdot: lda #46
rxcsv:  sta (PTR),y
        iny
        jmp rxcnl
rxcnd:  lda #0
        sta (PTR),y
; the key comes from the RAW buffer -- it is binary, not text
        ldx #0
rxcpl:  cpx #32
        bcs rxcpd
        txa
        clc
        adc #17
        tay
        lda BUF+1,x
        sta (PTR),y
        inx
        jmp rxcpl
rxcpd:  ldy #49
        lda BUF+35              ; out_path_len; $ff means "no route, flood"
        sta (PTR),y
        ldx #0
rxcrl:  cpx #8
        bcs rxcrd
        txa
        clc
        adc #50
        tay
        lda BUF+36,x
        sta (PTR),y
        inx
        jmp rxcrl
rxcrd:  ldy #58
        lda BUF+33
        sta (PTR),y
        inc NCONT
rxcrt:  rts

; ===== node list =======================================================
nodelst:
        lda #1
        sta UIMODE
        lda #147                ; a submenu replaces the parent, it does
        jsr CHROUT              ; not stack on top of it
        lda #0
        sta NCONT
        lda #4                  ; CMD_GET_CONTACTS
        sta TXBUF
        lda #1
        sta TXLEN
        jsr sendfr
        lda #0
        sta STGBIT
        lda #4                  ; RESP_CODE_END_OF_CONTACTS
        jsr waitop
; build the pointer table the menu reads
        lda #0
        sta MNIDX
ndtl:   lda MNIDX
        cmp NCONT
        bcs ndtd
        lda MNIDX
        jsr contptr
        lda MNIDX
        asl
        tay
        lda PTR
        sta NODETAB,y
        iny
        lda PTRH
        sta NODETAB,y
        inc MNIDX
        jmp ndtl
ndtd:   lda NCONT
        bne ndshow
        jmp mmshut              ; nothing to show
; The list scrolls. It used to cap MNN at 12 and use MNSEL directly as the
; contact index, so anything past the twelfth was stored but unreachable --
; which also made raising the cap pointless.
ndshow: lda #0
        sta NDOFF
        sta MNSEL
ndpage: lda #4
        sta MNX
        lda #4
        sta MNY
        lda #30
        sta MNW
; how many of the remainder fit on one screen
        lda NCONT
        sec
        sbc NDOFF
        cmp #12
        bcc ndn2
        lda #12
ndn2:   sta MNN
; MNPTR = NODETAB + NDOFF*2
        lda NDOFF
        asl
        clc
        adc #<NODETAB
        sta MNPTR
        lda #0
        adc #>NODETAB
        sta MNPTRH
        lda #<tnodes
        sta MNTIT
        lda #>tnodes
        sta MNTITH
        lda #147
        jsr CHROUT
        jsr mnbox
        jsr mnitems
ndkey:  jsr tkey
        jsr poll
        lda READY
        beq ndk2
        jsr dispat
        lda #0
        sta READY
ndk2:   jsr GETIN
        cmp #0
        beq ndkey
        cmp #17
        beq nddn
        cmp #145
        beq ndup
        cmp #13
        beq ndtake
        cmp #133
        beq ndcan
        jmp ndkey
nddn:   lda MNSEL
        clc
        adc #1
        cmp MNN
        bcc nddn2
; off the bottom: scroll if there is more below, otherwise wrap to the top
        lda NDOFF
        clc
        adc MNN
        cmp NCONT
        bcs ndwrap
        inc NDOFF
        jmp ndpage              ; MNSEL stays on the last row
nddn2:  sta MNSEL
        jsr mnitems
        jmp ndkey
ndwrap: lda #0
        sta NDOFF
        sta MNSEL
        jmp ndpage
ndup:   lda MNSEL
        bne ndup2
        lda NDOFF
        beq ndlast              ; at the very top: wrap to the end
        dec NDOFF
        jmp ndpage              ; MNSEL stays on the first row
ndup2:  sec
        sbc #1
        sta MNSEL
        jsr mnitems
        jmp ndkey
ndlast: lda NCONT
        cmp #12
        bcc ndsml
        sec
        sbc #12
        sta NDOFF
        lda #11
        sta MNSEL
        jmp ndpage
ndsml:  lda #0
        sta NDOFF
        lda NCONT
        sec
        sbc #1
        sta MNSEL
        jmp ndpage
ndtake: lda NDOFF
        clc
        adc MNSEL
        sta CIDX
        jmp nodeact
ndcan:  jmp mmshut

; ===== what to do with a node ==========================================
nodeact:
        lda #14
        sta MNX
        lda #10
        sta MNY
        lda #20
        sta MNW
        lda #6
        sta MNN
        lda #<natab
        sta MNPTR
        lda #>natab
        sta MNPTRH
        lda #<tnode1
        sta MNTIT
        lda #>tnode1
        sta MNTITH
        lda #0
        sta MNSEL
        jsr menu
        lda MNSEL
        cmp #0
        beq namsg
        cmp #1
        beq nalogin
        cmp #2
        beq natelem
        cmp #3
        beq naroute
        cmp #4
        beq nawipe
        jmp mmshut
nalogin: jmp nalogi
natelem: jmp natele
; --- direct message: typing now goes to this contact ---
; only the first six bytes of the key are needed to address it
namsg:  lda CIDX
        jsr contptr
        ldx #0
nam2:   cpx #6
        bcs nam3
        txa
        clc
        adc #17
        tay
        lda (PTR),y
        sta DMKEY,x
        inx
        jmp nam2
nam3:   lda #1
        sta DMON
        jmp mmshut
; --- show the route ---
naroute:
        lda CIDX
        jsr contptr
        jsr plinit
        jsr plnew
        lda #<troute
        sta SPL
        lda #>troute
        sta SPH
        jsr plstr
        ldy #49
        lda (PTR),y
        cmp #255
        bne narl
        lda #<tflood
        sta SPL
        lda #>tflood
        sta SPH
        jsr plstr
        jsr plend
        jmp narend
narl:   sta CTMP
        jsr plend
        jsr plnew
        lda #0
        sta MNIDX
narl2:  lda MNIDX
        cmp CTMP
        bcs narl3
        cmp #8
        bcs narl3
        lda MNIDX
        clc
        adc #50
        tay
        lda (PTR),y
        jsr plhex
        lda #32
        jsr plchr
        inc MNIDX
        jmp narl2
narl3:  jsr plend
narend: lda #<tnode1
        sta MNTIT
        lda #>tnode1
        sta MNTITH
        jsr plshow
        jmp mmshut
; --- wipe the route so the next message floods ---
nawipe: lda CIDX
        jsr contptr
        lda #13                 ; CMD_RESET_PATH
        sta TXBUF
        ldx #0
naw2:   cpx #32
        bcs naw3
        txa
        clc
        adc #17
        tay
        lda (PTR),y
        sta TXBUF+1,x
        inx
        jmp naw2
naw3:   lda #33
        sta TXLEN
        jsr sendfr
        jsr plinit
        jsr plnew
        lda #<twiped
        sta SPL
        lda #>twiped
        sta SPH
        jsr plstr
        jsr plend
        lda #<tnode1
        sta MNTIT
        lda #>tnode1
        sta MNTITH
        jsr plshow
        jmp mmshut

; ===== login and telemetry =============================================
; SEND_LOGIN carries the FULL 32-byte key (unlike a text message, which is
; addressed by a 6-byte prefix), then the password as plain text.
nalogi: lda #<tpass
        sta MNTIT
        lda #>tpass
        sta MNTITH
        jsr inpget
        lda INPOK
        bne nalg2
        jmp mmshut
nalg2:  lda CIDX
        jsr contptr
        lda #26                 ; CMD_SEND_LOGIN
        sta TXBUF
        jsr cpykey
        ldx #0
nalg3:  cpx INPLEN
        bcs nalg4
        lda INPASC,x
        sta TXBUF+33,x
        inx
        jmp nalg3
nalg4:  txa
        clc
        adc #33
        sta TXLEN
        jsr sendfr
        jsr plinit
        jsr plnew
        lda #<tlogsent
        sta SPL
        lda #>tlogsent
        sta SPH
        jsr plstr
        jsr plend
        lda #<tnode1
        sta MNTIT
        lda #>tnode1
        sta MNTITH
        jsr plshow
        jmp mmshut

; copy the selected contact's 32-byte key to TXBUF+1
cpykey: ldx #0
ckl:    txa
        clc
        adc #17
        tay
        lda (PTR),y
        sta TXBUF+1,x
        inx
        cpx #32
        bcc ckl
        rts

; SEND_TELEMETRY_REQ: three reserved bytes, then the full key at offset 4.
natele: lda #1
        sta UIMODE              ; the wait below polls
        lda CIDX
        jsr contptr
        lda #39
        sta TXBUF
        lda #0
        sta TXBUF+1
        sta TXBUF+2
        sta TXBUF+3
        ldx #0
ntl:    txa
        clc
        adc #17
        tay
        lda (PTR),y
        sta TXBUF+4,x
        inx
        cpx #32
        bcc ntl
        lda #36
        sta TXLEN
        jsr sendfr
        lda #0
        sta STGBIT
        lda #139                ; 0x8b, push_code_telemetry_response
        jsr waitop
        lda BUF
        cmp #139
        beq ntok
; nothing came back inside the timeout -- say so rather than show a blank
        jsr plinit
        jsr plnew
        lda #<tnotel
        sta SPL
        lda #>tnotel
        sta SPH
        jsr plstr
        jsr plend
        jmp ntshow
ntok:   jsr lppdec
ntshow: lda #<ttelem
        sta MNTIT
        lda #>ttelem
        sta MNTITH
        jsr plshow
        jmp mmshut

; ===== Cayenne LPP ====================================================
; Records are channel, type, then a value whose width depends on the type,
; big-endian. An unrecognised type ends the walk: without its width there
; is no way to find where the next record starts.
; Frame layout: 0 push code, 1 reserved, 2-7 key prefix, 8+ the records.
lppdec: jsr plinit
        lda #8
        sta LPPI
lppl:   lda PLN
        cmp #8
        bcs lppd                ; the panel holds eight lines
        ldx LPPI
        inx                     ; a record needs at least two more bytes
        cpx FLEN
        bcs lppd
        ldx LPPI
        lda BUF,x
        sta LPPC
        inx
        lda BUF,x
        sta LPPT
        inx
        stx LPPI
        jsr plnew
        lda #35                 ; '#'
        jsr plchr
        lda LPPC
        sta NUML
        lda #0
        sta NUMH
        jsr pldec
        lda #32
        jsr plchr
        lda LPPT
        cmp #116
        beq lppvlt
        cmp #103
        beq lpptmp
        cmp #104
        beq lpphum
        cmp #117
        beq lppcur
        cmp #2
        beq lppana
        cmp #0
        beq lppdig
        cmp #1
        beq lppdig
        cmp #101
        beq lpplux
        cmp #115
        beq lppbar
        cmp #102
        beq lppdig
; unknown: name it and stop
        lda #<slpptyp
        sta SPL
        lda #>slpptyp
        sta SPH
        jsr plstr
        lda LPPT
        sta NUML
        lda #0
        sta NUMH
        jsr pldec
        jsr plend
lppd:   lda PLN
        bne lppdr
        jsr plnew               ; nothing decoded at all
        lda #<tnotel
        sta SPL
        lda #>tnotel
        sta SPH
        jsr plstr
        jsr plend
lppdr:  rts

; --- the types we understand ---
lppvlt: lda #<svolt
        ldx #>svolt
        jsr lpplab
        jsr lpp16u
        lda #2
        sta DECS
        jsr plfix
        lda #<sv
        ldx #>sv
        jsr lpplab
        jmp lppnx
lppcur: lda #<scur
        ldx #>scur
        jsr lpplab
        jsr lpp16u
        lda #2
        sta DECS
        jsr plfix
        lda #<sa
        ldx #>sa
        jsr lpplab
        jmp lppnx
lpptmp: lda #<stemp
        ldx #>stemp
        jsr lpplab
        jsr lpp16s
        lda #1
        sta DECS
        jsr plfix
        lda #<sc
        ldx #>sc
        jsr lpplab
        jmp lppnx
lppbar: lda #<sbaro
        ldx #>sbaro
        jsr lpplab
        jsr lpp16u
        lda #1
        sta DECS
        jsr plfix
        lda #<shpa
        ldx #>shpa
        jsr lpplab
        jmp lppnx
lppana: lda #<sana
        ldx #>sana
        jsr lpplab
        jsr lpp16s
        lda #2
        sta DECS
        jsr plfix
        jmp lppnx
lpplux: lda #<slux
        ldx #>slux
        jsr lpplab
        jsr lpp16u
        jsr pldec
        jmp lppnx
lpphum: lda #<shum
        ldx #>shum
        jsr lpplab
        jsr lpp8
        lsr                     ; reported in half percent
        sta NUML
        lda #0
        sta NUMH
        jsr pldec
        lda #<spct
        ldx #>spct
        jsr lpplab
        jmp lppnx
lppdig: lda #<sdig
        ldx #>sdig
        jsr lpplab
        jsr lpp8
        sta NUML
        lda #0
        sta NUMH
        jsr pldec
        jmp lppnx
lppnx:  jsr plend
        jmp lppl

; A label or suffix, low byte in A and high in X. These used to be
; addressed by low byte alone with the page assumed, which saved two bytes
; per call and broke every time the code above them grew.
lpplab: sta SPL
        stx SPH
        jmp plstr

; --- pulling values out, big-endian ---
lpp8:   ldx LPPI
        lda BUF,x
        inc LPPI
        rts
lpp16u: ldx LPPI
        lda BUF,x
        sta NUMH
        inx
        lda BUF,x
        sta NUML
        inx
        stx LPPI
        lda #0
        sta LSIGN
        rts
lpp16s: jsr lpp16u
        lda NUMH
        bpl l16rt
        lda #1                  ; negate, and remember to print the sign
        sta LSIGN
        lda #0
        sec
        sbc NUML
        sta NUML
        lda #0
        sbc NUMH
        sta NUMH
l16rt:  rts

; NUMH:NUML scaled by 10 or 100, printed with that many decimals.
; div10 leaves the quotient in place and the remainder in A, so the first
; call yields the LAST digit.
plfix:  lda LSIGN
        beq pfx1
        lda #45                 ; '-'
        jsr plchr
pfx1:   lda DECS
        cmp #2
        bne pfx2
        jsr div10
        sta FRAC2
pfx2:   jsr div10
        sta FRAC1
        jsr pldec
        lda #46                 ; '.'
        jsr plchr
        lda FRAC1
        clc
        adc #48
        jsr plchr
        lda DECS
        cmp #2
        bne pfxrt
        lda FRAC2
        clc
        adc #48
        jsr plchr
pfxrt:  lda #0
        sta LSIGN
        rts

; print the null-terminated string at SPL
prtsp:  ldy #0
psp2:   lda (SPL),y
        beq psp3
        jsr CHROUT
        iny
        bne psp2
psp3:   rts

; ===== the F1 menu =====================================================
mainmnu:
        lda #7
        sta MNX
        lda #7
        sta MNY
        lda #24
        sta MNW
        lda #6
        sta MNN
        lda #<mtab
        sta MNPTR
        lda #>mtab
        sta MNPTRH
        lda #<mtitle
        sta MNTIT
        lda #>mtitle
        sta MNTITH
        lda #0
        sta MNSEL
        jsr menu
        lda MNSEL
        cmp #255
        beq mmshut
        cmp #0
        beq mmchan
        cmp #1
        beq mmnode
        cmp #2
        beq mmstat
        cmp #3
        beq mmrad
        cmp #4
        beq mmadd
mmshut: lda #147
        jsr CHROUT
        jmp setchan             ; repaint the chat and the prompt
mmchan: jmp picker
mmnode: jmp nodelst
mmstat: jmp statvw
mmrad:  jmp radiovw
mmadd:  jmp addchan

; ===== channel add / remove ===========================================
; SET_CHANNEL carries the secret verbatim -- the firmware does not derive
; one from the name (it only hashes the secret to get the channel hash),
; so the 16 bytes have to be typed in. That is the same 128-bit key the
; phone apps show, and only the 16-byte form is accepted: the firmware
; answers the 32-byte variant with ERR_CODE_UNSUPPORTED_CMD.
; A leading "#" is just part of the name; nothing special is needed here.
addchan:
        lda #12
        sta MNX
        lda #8
        sta MNY
        lda #24
        sta MNW
        lda #3
        sta MNN
        lda #<catab
        sta MNPTR
        lda #>catab
        sta MNPTRH
        lda #<tchan
        sta MNTIT
        lda #>tchan
        sta MNTITH
        lda #0
        sta MNSEL
        jsr menu
        lda MNSEL
        cmp #0
        beq caadd
        cmp #1
        beq carem
        jmp mmshut

caadd:  jsr caslot
        lda INPOK
        bne caa2
        jmp mmshut
caa2:   lda #<tcname
        sta MNTIT
        lda #>tcname
        sta MNTITH
        jsr inpget
        lda INPOK
        bne caa3
        jmp mmshut
caa3:   jsr canclr
        ldx #0
can2:   cpx INPLEN
        bcs can3
        lda INPASC,x
        sta CHNAME,x
        inx
        jmp can2
can3:   lda #<tsec
        sta MNTIT
        lda #>tsec
        sta MNTITH
        jsr inpget
        lda INPOK
        bne caa4
        jmp mmshut
caa4:   jsr inphx
        jmp chsend

; removing is the same frame with an empty name and a zero key
carem:  jsr caslot
        lda INPOK
        bne car2
        jmp mmshut
car2:   jsr canclr
        ldx #0
        lda #0
car3:   sta SECBUF,x
        inx
        cpx #16
        bcc car3
        jmp chsend

; Ask which slot, 0..39. Out of range aborts: clamping to zero would
; quietly overwrite Public, which is the one slot nobody means to touch.
caslot: lda #<tslot
        sta MNTIT
        lda #>tslot
        sta MNTITH
        jsr inpget
        lda INPOK
        beq casrt
        jsr inpnum
        cmp #40
        bcs casbad
        sta CHIDX
        rts
casbad: lda #0
        sta INPOK
casrt:  rts

canclr: ldx #0
        lda #0
canc2:  sta CHNAME,x
        inx
        cpx #32
        bcc canc2
        rts

; Build the frame only here, with no poll in between: dispat answers a
; MSG_WAITING push by sending a sync, so TXBUF cannot be held across a
; keyboard loop.
chsend: lda #1
        sta UIMODE              ; waitop and chscan poll; nothing may print
        lda #32                 ; CMD_SET_CHANNEL
        sta TXBUF
        lda CHIDX
        sta TXBUF+1
        ldx #0
chs2:   lda CHNAME,x
        sta TXBUF+2,x
        inx
        cpx #32
        bcc chs2
        ldx #0
chs3:   lda SECBUF,x
        sta TXBUF+34,x
        inx
        cpx #16
        bcc chs3
        lda #50
        sta TXLEN
        jsr sendfr
        lda #0
        sta STGBIT              ; not a handshake stage
        jsr waitop              ; RESP_CODE_OK
; re-scan so the picker shows the change straight away; CF forces the full
; sweep, because a new channel may well sit above a gap
        lda #1
        sta CF
        jsr chscan
        lda #0
        sta CF                  ; back to the quick scan, as the picker does
        jsr plinit
        jsr plnew
        lda #<tchset
        sta SPL
        lda #>tchset
        sta SPH
        jsr plstr
        jsr plend
        lda #<tchan
        sta MNTIT
        lda #>tchan
        sta MNTITH
        jsr plshow
        jmp mmshut

; ===== reading numbers back out of the input field =====================
; INPASC as decimal -> A. Stops at the first non-digit.
inpnum: lda #0
        sta CTMP
        ldx #0
innl:   cpx INPLEN
        bcs innd
        lda INPASC,x
        sec
        sbc #48
        cmp #10
        bcs innd
        sta TMP
        lda CTMP
        asl
        sta CTMP                ; n*2
        asl
        asl                     ; n*8
        clc
        adc CTMP                ; n*10
        clc
        adc TMP
        sta CTMP
        inx
        jmp innl
innd:   lda CTMP
        rts

; INPASC as hex digit pairs -> SECBUF. Short input leaves the rest zero,
; which is exactly what an unencrypted channel wants.
inphx:  ldx #0
        lda #0
ihz:    sta SECBUF,x
        inx
        cpx #16
        bcc ihz
        lda #0
        sta CTMP                ; read position
        sta MNIDX               ; write position
ihl:    lda MNIDX
        cmp #16
        bcs ihd
        ldx CTMP
        cpx INPLEN
        bcs ihd
        lda INPASC,x
        jsr hexval
        bcs ihd
        asl
        asl
        asl
        asl
        sta TMP
        inc CTMP
        ldx CTMP
        cpx INPLEN
        bcs ihd
        lda INPASC,x
        jsr hexval
        bcs ihd
        ora TMP
        ldx MNIDX
        sta SECBUF,x
        inc MNIDX
        inc CTMP
        jmp ihl
ihd:    rts

; ascii hex digit -> value; carry set means it was not one
hexval: cmp #48
        bcc hxbad
        cmp #58
        bcs hxa
        sec
        sbc #48
        clc
        rts
hxa:    cmp #97
        bcc hxbad
        cmp #103
        bcs hxbad
        sec
        sbc #87
        clc
        rts
hxbad:  sec
        rts

; ===== send ============================================================
sendmsg:
        lda INLEN
        beq smsrt
        lda DMON
        bne sendm2              ; addressed to a contact, not a channel
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
; ----- direct message -----
; [2][txt_type][attempt][timestamp:4][key prefix:6][text]
sendm2: lda #2
        sta TXBUF
        lda #0
        sta TXBUF+1             ; plain
        sta TXBUF+2             ; first attempt
        sta TXBUF+3
        sta TXBUF+4
        sta TXBUF+5
        sta TXBUF+6
        ldx #0
sdm2:   cpx #6
        bcs sdm3
        lda DMKEY,x
        sta TXBUF+7,x
        inx
        jmp sdm2
sdm3:   ldx #0
sdm4:   cpx INLEN
        bcs sdm5
        lda INASC,x
        sta TXBUF+13,x
        inx
        jmp sdm4
sdm5:   txa
        clc
        adc #13
        sta TXLEN
        jsr ledtx
        jsr sendfr
        rts

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
        lda #107            ; 'k' = unrecognised opcodes
        sta TXBUF,x
        inx
        lda UNK
        jsr apphex
        lda #32
        sta TXBUF,x
        inx
        lda #112            ; 'p' = frames rejected at the length header
        sta TXBUF,x
        inx
        lda PBAD
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

; Stepped once per jiffy from the main loop, so the animation is visible
; without costing anything measurable.
;
; When nothing is flashing the lamps are not idle -- they show how many
; messages are waiting, in binary, least significant on PB3. Four lamps
; count to 15; past that it simply reads 15, which is still "a lot".
ledstep:
        lda LEDON
        beq lsidle
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
        lda #255
        sta LEDLST              ; force the count back onto the lamps
; only written when the count changes, so the main loop is untouched the
; rest of the time
lsidle: lda UT
        cmp LEDLST
        beq lsrt
        sta LEDLST
        cmp #16
        bcc lsi2
        lda #15                 ; more than the lamps can show
lsi2:   asl
        asl
        asl                     ; bit 0 -> PB3
        sta C2PRB
lsrt:   rts

; ---- six lamps, when the pins are proven on real hardware ----
; PB1 and PB2 carry two more, so the count reaches 63:
;
;       lda UT
;       cmp #64
;       bcc ls6
;       lda #63
; ls6:  asl                     ; bit 0 -> PB1
;       sta C2PRB
;
; DDRB must become 126 as well as this changing, and that is the catch:
; PB1 is RTS and PB2 is DTR, and VICE's userport rs232 drops the link the
; moment either is driven -- so no emulator test can pass with it on. On
; the real cart those two pins go to lamps with nothing listening, and
; bit-zeal's meshtastic64 drives all six, so it should be fine. Should.
; Untested on hardware, which is why it is commented out rather than
; switched on.

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
        lda #96                 ; the archive is in the REU, so main RAM
        sta MAXCON              ; is free for a longer contact list
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
; No REU. The archive moves into main RAM rather than being switched off:
; one merged region of 409 lines in the reclaimed splash area.
rdno:   lda #0
        sta RU
        sta UKL
        sta UKH
        lda #32                 ; contacts compete with the archive here
        sta MAXCON
        lda #153                ; 409 lines
        sta MAXL
        lda #1
        sta MAXH
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

; PTR2 = ARCRAM + SLOT*40, for the RAM archive. Its own scratch, because
; appage holds TMP and TMP2 live across the transfer.
ramaddr:
        lda SLOTL
        sta PTR2
        lda SLOTH
        sta PTR2H
        lda SLOTL
        sta ARCTL
        lda SLOTH
        sta ARCTH
        ldx #3
ram8:   asl PTR2                ; slot*8
        rol PTR2H
        dex
        bne ram8
        ldx #5
ram32:  asl ARCTL               ; slot*32
        rol ARCTH
        dex
        bne ram32
        lda PTR2
        clc
        adc ARCTL               ; 8 + 32 = 40
        sta PTR2
        lda PTR2H
        adc ARCTH
        sta PTR2H
        lda PTR2H
        clc
        adc #>ARCRAM            ; the low byte of ARCRAM is zero
        sta PTR2H
        rts

; 40 bytes, PTR -> PTR2
ramwr:  ldy #0
ramwl:  lda (PTR),y
        sta (PTR2),y
        iny
        cpy #40
        bcc ramwl
        rts

; 40 bytes, PTR2 -> PTR
ramrd:  ldy #0
ramrl:  lda (PTR2),y
        sta (PTR),y
        iny
        cpy #40
        bcc ramrl
        rts

; set up a transfer of CNT*40 bytes between c64 PTR and the computed slot
reuxfer:
        lda RU
        bne rxreu
        jsr ramaddr             ; no REU: a plain copy into main RAM
        jsr ramwr
        rts
rxreu:  jsr reuaddr
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
; Which region a channel archives to. Without an REU there is only one --
; the merged feed -- and every line in it already carries a [channel]
; prefix, so it still says where each message came from.
lreg:   ldx RU
        bne lrreu
        lda #8
        sta REGION
        rts
lrreu:  cmp #255
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
        beq amall               ; no REU: the merged region only
        lda #11
        sta SOFF
        jsr scrn
        lda TMP                 ; the channel it arrived on
        jsr lreg
        jsr lput
; Without an REU we arrive straight here: one merged region, and the
; prefix is what makes it readable.
amall:
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
arcown:
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
        lda RU
        beq aoall               ; no REU: lreg would return region 8 here
        lda CC                  ; too, and the line would be stored twice
        jsr lreg
        jsr lput
aoall:  lda #8
        sta REGION
        jsr lput
aort:   rts

; ===== paint a page from the archive ===================================
; 24 lines, NOT 25: the bottom row belongs to the prompt. Painting all 25
; put the newest message where the prompt then overwrote it.
arcpage:
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

apxfer: lda RU
        bne axreu
        jsr ramaddr
        jsr ramrd
        rts
axreu:  lda CNT2
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
        lda #1
        sta UIMODE
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
        sta UIMODE
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
; ===== channel picker =================================================
; Drawn in the same frame as every other menu. It keeps its own key loop
; rather than calling menu(), because the digit shortcuts are worth having
; -- "f1 2" has been how you change channel since v1 and there is no
; reason to make people arrow to it instead.
picker: lda #1
        sta UIMODE
        lda CKED
        bne pkshow
        lda #147
        jsr CHROUT
        lda #<msgscan
        sta PTR
        lda #>msgscan
        sta PTRH
        jsr prtstr
        jsr chscan

; Map the list positions onto whatever slots actually have names, so a
; sparse radio still gets a dense list. "All" is synthetic and always 0.
pkshow: lda #255
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

; ----- render each row into the picker's own buffer -----
pkbd:   jsr plinit
        lda #<PKBUF
        sta PLBASE
        lda #>PKBUF
        sta PLBASE+1
        lda #0
        sta SCANI
pkrl:   lda SCANI
        cmp NPICK
        bcs pkrd
; the name address has to be worked out BEFORE plnew, which claims PTR
        ldx SCANI
        lda PKMAP,x
        cmp #255
        beq pkral
        jsr chnptr
        lda PTR
        sta SPL
        lda PTRH
        sta SPH
        jmp pkrn
pkral:  lda #<sall
        sta SPL
        lda #>sall
        sta SPH
pkrn:   jsr plnew
        lda SCANI               ; "0 " and so on, so the digits still read
        clc
        adc #48
        jsr plchr
        lda #32
        jsr plchr
        ldy #0
pknl:   cpy #16
        bcs pknd
        sty CTMP
        lda (SPL),y
        beq pknd
        jsr p2a
        jsr plchr
        ldy CTMP
        iny
        jmp pknl
; unread count, if any
pknd:   ldx SCANI
        lda PKMAP,x
        cmp #255
        beq pkrmk
        tax
        lda CUNR,x
        beq pkrmk
        sta NUML
        lda #0
        sta NUMH
        lda #32
        jsr plchr
        lda #40                 ; '('
        jsr plchr
        jsr pldec
        lda #41                 ; ')'
        jsr plchr
; a star marks where you are, which is not the same as where the cursor is
pkrmk:  ldx SCANI
        lda PKMAP,x
        cmp CC
        bne pkrnx
        lda #32
        jsr plchr
        lda #42
        jsr plchr
pkrnx:  jsr plend
        inc SCANI
        jmp pkrl

; ----- draw it -----
pkrd:   lda #147
        jsr CHROUT
        lda #4
        sta MNX
        lda #3
        sta MNY
        lda #28
        sta MNW
        lda NPICK
        sta MNN
        lda #<PLTAB
        sta MNPTR
        lda #>PLTAB
        sta MNPTRH
        lda #<tchans
        sta MNTIT
        lda #>tchans
        sta MNTITH
; open on the channel you are already in
        lda #0
        sta MNSEL
        lda #0
        sta SCANI
pkfl:   lda SCANI
        cmp NPICK
        bcs pkfd
        ldx SCANI
        lda PKMAP,x
        cmp CC
        bne pkfn
        lda SCANI
        sta MNSEL
        jmp pkfd
pkfn:   inc SCANI
        jmp pkfl
pkfd:   jsr mnbox
        jsr mnitems
; the hint goes under the frame
        lda MNY
        clc
        adc MNN
        adc #3
        sta MNROW
        jsr scrpos
        lda #12
        sta MNCLR
        lda #<pkhint
        sta SPL
        lda #>pkhint
        sta SPH
        lda #1
        sta MNCOL
        jsr mnstr

pkkey:  jsr tkey
        jsr poll
        lda READY
        beq pknk
        jsr dispat
        lda #0
        sta READY
pknk:   jsr GETIN
        cmp #0
        beq pkkey
        cmp #17                 ; cursor down
        beq pkdn
        cmp #145                ; cursor up
        beq pkup
        cmp #13
        beq pktake
        cmp #133
        beq pkend
        cmp #82                 ; 'r' rescans
        beq pkres
        cmp #210
        beq pkres
        cmp #48                 ; the digit shortcuts, as before
        bcc pkkey
        cmp #58
        bcs pkkey
        sec
        sbc #48
        cmp NPICK
        bcs pkkey
        sta MNSEL
pktake: ldx MNSEL
        lda PKMAP,x
        sta CC
pkend:  lda #0
        sta UIMODE
        lda #147
        jsr CHROUT
        jmp setchan
pkdn:   lda MNSEL
        clc
        adc #1
        cmp NPICK
        bcc pkdn2
        lda #0
pkdn2:  sta MNSEL
        jsr mnitems
        jmp pkkey
pkup:   lda MNSEL
        bne pkup2
        lda NPICK
pkup2:  sec
        sbc #1
        sta MNSEL
        jsr mnitems
        jmp pkkey
pkres:  lda #1
        sta CF
        jsr chscan
        lda #0
        sta CF
        jmp pkshow

; PETSCII back to ASCII, the inverse of conv().
;
; CHNAM has to stay PETSCII: the bottom prompt and the "[channel]" prefix
; on archived lines both print it with CHROUT. The menu draws through a2s,
; which wants ASCII. Converting the handful of characters here is cheaper
; than keeping a second copy of every channel name -- and running both
; conversions, which is what made the names come out uppercase.
p2a:    cmp #65
        bcc p2art
        cmp #91
        bcs p2a2
        ora #32                 ; petscii lowercase -> ascii lowercase
        rts
p2a2:   cmp #193
        bcc p2art
        cmp #219
        bcs p2art
        and #127                ; petscii shifted -> ascii uppercase
p2art:  rts

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
screp:  jsr arcpage
        jmp scprm
; No archive to paint from, so at least say where we are -- the picker
; cleared the screen on its way out and a bare prompt looks like the
; channel lost its history.
scprm:  jsr setprm
        jsr shoprm
        rts

; ===== non-REU replay ring =============================================
; With no REU there is no archive, so keep the last 24 messages in RAM and
; replay the ones for a channel when you switch to it. Only the UNREAD
; ones: anything you were already watching has been on screen once.

; PTR -> ring slot Y (40 bytes each: x32 + x8)
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
bitpal: .byte 0,0,0,0,0,0
bitntsc: .byte 0,0,0,0,0,0
blankb: .byte 0
testk:  .byte 0             ; nonzero = run the scripted keypresses
pyastart: .byte 1,0,0,0,0,0,0,0,67,54,52
pyquery:  .byte 22,3
pychan:   .byte 31,0
pytime:   .byte 5
banner: .text "meshcore 64  v2.2d"
        .byte 13,0
svideo: .text "video  "
        .byte 0
sradio: .text "radio  "
        .byte 0
sfwv:   .text "fw     "
        .byte 0
skeys:  .text "f1 menu  f3 stats  f5 history  f7 public"
        .byte 13,0
msgcon: .text "connecting..."
        .byte 13,0
msgrdy: .text "connected."
        .byte 13,13,0
msgpick: .text "pick a channel to send"
        .byte 13,0
msgscan: .text "scanning..."
        .byte 13,0
msgstat: .text "frames/rej/hw "
        .byte 0
mtitle: .text " meshcore 64 "
        .byte 0
mi0:    .text "channels"
        .byte 0
mi1:    .text "nodes"
        .byte 0
mi2:    .text "stats"
        .byte 0
mi3:    .text "radio config"
        .byte 0
mi4:    .text "add/remove channel"
        .byte 0
mi5:    .text "close"
        .byte 0
mtab:   .word mi0,mi1,mi2,mi3,mi4,mi5
; one colour per entry: red, yellow, cyan, purple, light green, light blue
mnclrs: .byte 2,7,3,4,13,14,2,7,3,4,13,14,2,7,3,4
; sender colours, chosen by name hash. No green -- that is the message --
; and nothing dark enough to vanish on black.
smpal:  .byte 5,158,159,156,153,154,150,155
tchans: .text " channels "
        .byte 0
sall:   .text "all"
        .byte 0
pkhint: .text "0-9 pick  return  r rescan  f1 back"
        .byte 0
ca0:    .text "add or edit channel"
        .byte 0
ca1:    .text "remove channel"
        .byte 0
ca2:    .text "back"
        .byte 0
catab:  .word ca0,ca1,ca2
tchan:  .text " channel "
        .byte 0
tslot:  .text " slot number 0-39 "
        .byte 0
tcname: .text " channel name "
        .byte 0
tsec:   .text " key, 32 hex digits "
        .byte 0
tchset: .text "channel updated"
        .byte 0
tnodes: .text " nodes "
        .byte 0
tnode1: .text " node "
        .byte 0
na0:    .text "send message"
        .byte 0
na1:    .text "log in..."
        .byte 0
na4:    .text "telemetry"
        .byte 0
na5:    .text "show route"
        .byte 0
na2:    .text "wipe route (flood)"
        .byte 0
na3:    .text "back"
        .byte 0
natab:  .word na0,na1,na4,na5,na2,na3
tpass:  .text " password "
        .byte 0
ttelem: .text " telemetry "
        .byte 0
tlogsent: .text "login sent - watch for reply"
        .byte 0
tlogok: .text "login accepted"
        .byte 13,0
tnotel: .text "no telemetry came back"
        .byte 0
; every LPP label is addressed by its low byte alone, so they must all
; sit in one page -- the assembler would not warn if they did not
svolt:  .text "voltage "
        .byte 0
scur:   .text "current "
        .byte 0
stemp:  .text "temp "
        .byte 0
sbaro:  .text "pressure "
        .byte 0
sana:   .text "analog "
        .byte 0
slux:   .text "light "
        .byte 0
shum:   .text "humidity "
        .byte 0
sdig:   .text "digital "
        .byte 0
sv:     .text " v"
        .byte 0
sa:     .text " a"
        .byte 0
sc:     .text " c"
        .byte 0
shpa:   .text " hpa"
        .byte 0
spct:   .text " pct"
        .byte 0
slpptyp: .text "type "
        .byte 0
troute: .text "route: "
        .byte 0
tflood: .text "none - will flood"
        .byte 0
tstats: .text " stats "
        .byte 0
tradio: .text " radio "
        .byte 0
sbatt:  .text "battery "
        .byte 0
smv:    .text " mv"
        .byte 0
sstor:  .text "storage "
        .byte 0
skb:    .text " kb"
        .byte 0
sframes: .text "frames  "
        .byte 0
srej:   .text "rej/unk/hdr "
        .byte 0
sframe: .text "framing "
        .byte 0
sring:  .text "ring hw "
        .byte 0
sfw:    .text "fw "
        .byte 0
svid:   .text "video "
        .byte 0
spal:   .text "pal"
        .byte 0
sntsc:  .text "ntsc"
        .byte 0
sbaud:  .text "link 2400 baud"
        .byte 0
srfreq: .text "freq  "
        .byte 0
srbw:   .text "bw    "
        .byte 0
srsf:   .text "sf    "
        .byte 0
srcr:   .text "cr    "
        .byte 0
srpwr:  .text "power "
        .byte 0
srname: .text "node name..."
        .byte 0
tname:  .text " node name "
        .byte 0
srapply: .text "apply to node"
        .byte 0
srback: .text "back"
        .byte 0
srsent: .text "radio settings sent"
        .byte 0
skhz:   .text " khz"
        .byte 0
shz:    .text " hz"
        .byte 0
sdbm:   .text " dbm"
        .byte 0
sreu:   .text "reu    "
        .byte 0
snone:  .text "none"
        .byte 0
twiped: .text "route wiped - next msg floods"
        .byte 0

; ===== splash artwork ==================================================
; Generated by mksplash.py: the MeshCore wordmark, "64" in the character
; ROM's own font, and a drawing of a breadbin. RLE (count, value) pairs,
; zero count ends it. Unpacked to $4000 in VIC bank 1, well clear of the
; program.
; screen RAM address of each row, so the menu never multiplies
rowlo:  .byte 0,40,80,120,160,200,240,24,64,104,144,184,224,8,48,88,128,168,208,248,32,72,112,152,192
rowhi:  .byte 4,4,4,4,4,4,4,5,5,5,5,5,5,6,6,6,6,6,6,6,7,7,7,7,7


"""

# 2400 is THE speed. The slower rates are kept only because the bit period
# is a build-time constant either way, so they cost nothing and leave a way
# back if real hardware disagrees with the emulator -- they are not tested,
# because a run that passes at 2400 cannot fail at 600 for timing reasons.
RATES = {7: 600, 8: 1200, 10: 2400, 11: 4800, 12: 9600}
DEFAULT_CTRL = 10               # 2400 baud


NTSC = 1022727


# Scripted keypresses for the VICE tests, by testk value. Each inner list
# is one BATCH: the feeder stuffs up to eight at a time into the kernal's
# own buffer, because a UI loop that opens mid-batch has to find whatever
# it needs already sitting there. Keys are PETSCII as GETIN returns them:
# 133 = f1, 17/145 = cursor down/up, 13 = return, 20 = delete.
TESTKEYS = {
    # The regression script: f1, "channels", pick channel 2, type "hi",
    # f5 scrollback then out, f7, and back to channel 1. F1 now opens a
    # menu before the picker, hence the extra RETURN.
    1: [[133, 13, 50], [104, 105, 13], [135, 32], [136], [133, 13, 49]],
    # f1 -> add/remove channel -> add -> slot 5, name "mych", key "abcd"
    2: [[133, 17, 17, 17, 17, 13], [13], [53, 13],
        [77, 89, 67, 72, 13], [65, 66, 67, 68, 13]],
    # f1 -> nodes -> first contact -> show route. No dismissing key: the
    # panel has to still be up when the screenshot is taken.
    3: [[133, 17, 13], [13], [17, 17, 17, 13]],
    # f1 -> nodes -> first contact -> telemetry
    4: [[133, 17, 13], [13], [17, 17, 13]],
    # f1 -> nodes -> first contact -> log in, password "pass"
    5: [[133, 17, 13], [13], [17, 13], [80, 65, 83, 83, 13]],
    # f1 -> nodes -> first contact -> send message, then type "hi"
    6: [[133, 17, 13], [13], [13], [72, 73, 13]],
    # let a few messages arrive (DEL is harmless on an empty line), then f5
    19: [[20], [20], [20], [20], [135]],
    # f1 -> nodes, then page down past the twelfth entry
    20: [[133, 17, 13], [17, 17, 17, 17, 17, 17, 17, 17],
         [17, 17, 17, 17, 17]],
    21: [],
    # f1 -> radio config -> node name -> type "c64"
    7: [[133, 17, 17, 17, 13], [145, 145, 145, 13], [67, 54, 52, 13]],
    # ---- documentation screenshots ----
    # Each of these STOPS on the screen it wants photographed. Menus and
    # panels wait for a key, and the feeder is exhausted, so the screen
    # stays up however long the run goes on. A panel does not call tkey at
    # all, so a script that ends in one cannot advance past it.
    10: [[133]],                                   # the f1 menu
    11: [[133, 13]],                               # channel picker
    12: [[133, 17, 13]],                           # node list
    13: [[133, 17, 13], [13]],                     # what to do with a node
    14: [[133, 17, 17, 13]],                       # stats
    15: [[133, 17, 17, 17, 13]],                   # radio config
    16: [[133, 17, 17, 17, 13], [145, 145, 145, 13],
         [67, 54, 52]],                            # node name, mid-typing
    17: [[133, 17, 13], [13], [17, 17, 17, 13]],   # show route
    18: [[133, 17, 17, 17, 17, 13], [13]],         # channel slot prompt
}


def keytable(testk):
    rows = TESTKEYS.get(testk, [])
    out = ["tktab:"]
    for batch in rows:
        assert len(batch) <= 8, "a batch cannot exceed the kernal buffer"
        out.append("        .byte " + ",".join(str(k) for k in batch) + ",0")
    out.append("        .byte 0")
    return "\n".join(out) + "\n"


def artwork():
    """
    The splash bitmap and its colour map, straight off disk.

    mksplash.py regenerates them whenever the art changes; appending the
    bytes here keeps several thousand .byte lines out of the source and
    means the two can never drift apart.
    """
    here = os.path.dirname(os.path.abspath(__file__))

    def blk(fn, label):
        data = open(os.path.join(here, fn), "rb").read()
        out = ["%s:" % label]
        for i in range(0, len(data), 16):
            out.append("        .byte "
                       + ",".join(str(b) for b in data[i:i + 16]))
        return "\n".join(out) + "\n"

    return ("\n; one foreground colour per screen row\n"
            + blk("logocol.bin", "logocol")
            + "\n; the bitmap itself, RLE (count, value)\n"
            + blk("logo.bin", "logodat"))


def build(ctrl=DEFAULT_CTRL, out=OUT, blank=0, clock=PAL, testk=0,
          latadj=275):
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
    code, syms = assemble(SRC + keytable(testk) + artwork(), ORG, EQU)
    code = bytearray(code)
    # txwait watches timer A's HIGH byte for the reload. If a whole bit
    # period fits inside 256 cycles that byte never changes and the wait
    # never returns, so the driver would hang rather than misbehave.
    if bit >> 8 == 0 or int(round(NTSC / float(baud))) >> 8 == 0:
        raise ValueError(
            "bit period %d/%d is under 256 cycles: txwait watches the "
            "timer high byte and would never see it move"
            % (bit, int(round(NTSC / float(baud)))))

    # Buffers that are indexed, not just read, and so will corrupt a
    # neighbour rather than fail loudly if they collide. PKBUF sitting
    # immediately after CONTACTS is exactly the adjacency worth checking.
    regions = [("CONTACTS", 96 * 64), ("PKBUF", 10 * 32),
               ("CHNAM", 40 * 18), ("NODENM", 20), ("NODETAB", 96 * 2),
               ("PLTAB", 10 * 2),
               ("DECBUF", 12), ("CHNAME", 32), ("FWVER", 20),
               ("INPASC", 32), ("SECBUF", 16),
               ("PLBUF", 8 * 32), ("RBUF", 256), ("TXBUF", 256),
               ("SBUF", 256), ("CBUF", 256), ("BUF", 256),
               ("BMBASE", 8000), ("BMCOL", 1000)]
    spans = sorted((EQU[n], EQU[n] + sz, n) for n, sz in regions)
    for (a0, a1, an), (b0, b1, bn) in zip(spans, spans[1:]):
        if a1 > b0:
            raise ValueError(
                "%s ($%04X..$%04X) overlaps %s ($%04X..$%04X)"
                % (an, a0, a1 - 1, bn, b0, b1 - 1))

    # The splash artwork is what makes this worth checking: it roughly
    # doubled the image, and the bitmap it unpacks into sits at $4000.
    end = ORG + len(code)
    if end > EQU["BMBASE"]:
        raise ValueError(
            "program ends at $%04X, past the splash bitmap at $%04X"
            % (end, EQU["BMBASE"]))
    nbit = int(round(NTSC / float(baud)))
    nhalf = int(round(nbit * 1.5)) - latadj
    # Half a bit in, less the same latency allowance, to check the start
    # bit is still low. Anything from a quarter to three quarters of the
    # way in would do, so this is very tolerant -- but never let the
    # allowance push it to nothing.
    hver = max(bit // 4, bit // 2 - latadj)
    nhver = max(nbit // 4, nbit // 2 - latadj)
    vals = [("btlo", bit & 0xFF), ("bthi", bit >> 8),
            ("hblo", half & 0xFF), ("hbhi", half >> 8),
            ("blankb", blank), ("testk", testk)]
    # the runtime table: PAL quad then NTSC quad, contiguous
    for i, v in enumerate([bit & 0xFF, bit >> 8, half & 0xFF, half >> 8,
                           hver & 0xFF, hver >> 8,
                           nbit & 0xFF, nbit >> 8, nhalf & 0xFF, nhalf >> 8,
                           nhver & 0xFF, nhver >> 8]):
        code[syms["bitpal"] - ORG + i] = v
    for name, val in vals:
        code[syms[name] - ORG] = val
    prg = bytes([ORG & 0xFF, ORG >> 8]) + bytes(code)
    with open(out, "wb") as f:
        f.write(prg)
    return code, syms, prg, bit, half


if __name__ == "__main__":
    ctrl = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CTRL
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
