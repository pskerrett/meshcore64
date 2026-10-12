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
from asm import assemble, parse
import sha256_6502

ORG = 0x0801
OUT = os.path.join(HERE, "meshcore64.prg")
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
    "NMIEN":   0xCF08,
    "TXNX":    0xCF0A,   # s6: next TXD level, worked out before the wait
    "TXW":     0xCFFD,   # last timer-A high byte seen by txwaitc
    "TXLST":   0xCFFE,   # nonzero while the LAST byte of a frame is going out   # CIA2 NMI sources currently enabled (mirror of the mask)
    # --- message timestamps; see tsput ---
    "NOWTS":   0xCF27,   # 4 bytes: device epoch, advanced locally
    "LSTTS":   0xCF2B,   # 4 bytes: the last one we actually sent
    "TSCNT":   0xCF2F,   # jiffies accumulated toward the next second
    # ---- channels / ui ----
    "CHNAM":   0xC400,   # 48 names, 18 bytes each: 0-39 channels, 40-47 DMs
    "CUNR":    0xC2D0,   # 48 unread counters, to $c2ff
    "PKMAP":   0xC300,   # picker slot -> channel index
    "INBUF":   0xC8F0,   # s26: 136 bytes (was 80 at $c310)   # the line being typed (petscii, for the screen)
    "INASC":   0xC978,   # s26: 136 bytes, to $c9ff   # the same line in ascii, for the wire
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
    "DECBUF":  0xC860,   # 12 bytes
    "SBUF":    0xCC00,   # up to six 40-byte screen-code lines
    # ---- REU controller ----
    "GEOWIN":  0xDE00,   # GeoRAM 256-byte window
    "GEOPG":   0xDFFE,   # GeoRAM page in block (0-63), write only
    "GEOBK":   0xDFFF,   # GeoRAM 16K block, write only
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
    "SD":      0xCF93,   # scrollback depth, lines (16-bit with SDH)
    "SDH":     0xCF9F,
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
    "TSJIF":   0xCFA7,   # JIFFY as of the last tick
    "TSOK":    0xCFA8,   # 1 = the radio has told us the time
    "DMW":     0xCFA9,   # scratch for the DM sender lookup
    "DMI":     0xCFAA,   # write position while rebuilding the line
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
    #   0-25 name, 26-57 public key, 58 out_path_len, 59 type, 60-63 route
    # 96 slots with an REU (where the archive lives in the REU and main
    # RAM is idle), 32 without (where it competes with the archive).
    "CONTACTS": 0x8000,
    "MAXCON":  0xCFF4,
    "NODETAB": 0x9B00,   # name pointers for the VISIBLE nodes, up to 255 x 2
    "NODEIX":  0x9D00,   # contact slot of each visible node, up to 255
    "NDOFF":   0xCFF5,   # first visible entry, for scrolling
    "SMC":     0xCFF6,   # index of the colon that ends the sender name
    "SMH":     0xCFF7,   # name hash, picks the sender colour
    "SMX":     0xCFF8,
    "LEDLST":  0xCFF9,   # count the lamps are currently showing
    "NCONT":   0xCFC4,
    "CIDX":    0xCFC5,   # which contact is selected
    "DMON":    0xCFC6,   # 1 = typing goes to a contact, not a channel
    "DMKEY":   0xCFC7,   # 6-byte key prefix of that contact
    "CTMP":    0xCFCE,
    # ---- info panel ----
    # Ten rendered lines, 32 bytes each. It was eight at $c900 and full;
    # the radio panel needs ten once the two advert lines are in it.
    "LOGODAT": 0x6800,   # s14: splash RLE data, loaded here, read once
    "PLBUF":   0x9E00,
    "TSTR":    0x9FC0,   # s14: a time line being built, 40 bytes
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
    "NODENM":  0x9FE8,   # node's own name, from SELF_INFO (20 bytes)
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
; **Move segment 2 under BASIC ROM before anything else runs.** The
; program outgrew the space below the splash bitmap at $4000, and this
; client never calls BASIC -- so the 8K of RAM beneath it at $a000 is free
; once $01 banks the ROM out. The image loads straight after segment 1,
; i.e. on top of $4000, so the copy MUST happen before the splash unpacks
; into that same RAM.
        lda #54                 ; $36: basic out, kernal and i/o in
        sta 1
        lda #<s2img
        sta PTR
        lda #>s2img
        sta PTRH
        lda #0
        sta PTR2
        lda #160
        sta PTR2H
        ldx #S2PG
        ldy #0
s2cp:   lda (PTR),y
        sta (PTR2),y
        iny
        bne s2cp
        inc PTRH
        inc PTR2H
        dex
        bne s2cp
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
        lda #0                  ; segment 4: out of the image at $8000 into
        sta PTR                 ; the logo's place, now the splash is done
        sta PTR2
        lda #$80
        sta PTRH
        lda #$68
        sta PTR2H
        ldx #S4PG
        ldy #0
s4cp:   lda (PTR),y
        sta (PTR2),y
        iny
        bne s4cp
        inc PTRH
        inc PTR2H
        dex
        bne s4cp
        lda #$99                ; segment 5: image -> $9960..$9AFF
        sta PTR2H
        ldx #2
        ldy #$60
s5cp:   lda (PTR),y
        sta (PTR2),y
        iny
        bne s5cp
        inc PTRH
        inc PTR2H
        dex
        bne s5cp

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
        sta CHNAM+768,x         ; 864 bytes now; $c760-$c7ff is free too
        inx
        bne zch
        ldx #0
zcu:    sta CUNR,x
        inx
        cpx #48
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
        lda RU
        bne bootru
        jsr geodet              ; no REU: a GeoRAM/NeoRAM instead?
bootru: jsr s2init              ; where contacts live depends on the reu
        jsr georest             ; NeoRAM: bring back the last session
        jsr serini

        jsr kwboot              ; VIC-II Kawari? first: it sets the width
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
        jsr ctsave
        jsr flrest
        jsr dmwd                ; DM: no ack by direct route -> flood
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
        jsr btitle
        lda #<svideo
        ldx #>svideo
        jsr blab
        lda #<sntsc
        ldx #>sntsc
        ldy ISNTSC
        bne bivd
        lda #<spal
        ldx #>spal
bivd:   jsr bstr
        lda #<smem              ; memory: what and how big
        ldx #>smem
        jsr blab
        lda RU
        bne bim0
        lda #<snone2
        ldx #>snone2
        jsr bstr
        jmp bim3
bim0:   lda #<sreu2
        ldx #>sreu2
        ldy RU
        cpy #2
        bne bim1
        lda #<sgeo2
        ldx #>sgeo2
bim1:   sta PTR
        stx PTRH
        jsr prtstr
        lda UKL
        sta NUML
        lda UKH
        sta NUMH
        jsr prdec
        lda #<skb
        sta PTR
        lda #>skb
        sta PTRH
        jsr prtstr
        jsr birest
        lda #13
        jsr CHROUT
bim3:   jsr ucboot              ; clock
        lda #<sdisp             ; display
        ldx #>sdisp
        jsr blab
        lda #<sd80
        ldx #>sd80
        ldy K80
        bne bid1
        lda #<sd40k
        ldx #>sd40k
        ldy KWOK
        bne bid1
        lda #<sd40
        ldx #>sd40
bid1:   jsr bstr
; a rule across the screen
brule:  lda #151                ; dark grey
        jsr CHROUT
        ldx KSEPW
brl1:   lda #192
        jsr CHROUT
        dex
        bne brl1
        lda #13
        jmp CHROUT
; grey label at A/X, then white
blab:   sta PTR
        stx PTRH
        lda #155
        jsr CHROUT
        jsr prtstr
        lda #5
        jmp CHROUT
; the string at A/X and a new line
bstr:   sta PTR
        stx PTRH
        jsr prtstr
        lda #13
        jmp CHROUT
; a cyan bar: " meshcore 64" ... version, one short of the screen width
btitle: lda #147
        jsr CHROUT
        lda #159
        jsr CHROUT
        lda #18
        jsr CHROUT
        lda #<stitle
        sta PTR
        lda #>stitle
        sta PTRH
        jsr prtstr
        ldy #0
btl1:   lda banner+13,y         ; the version, up to its CR
        cmp #13
        beq btl2
        iny
        bne btl1
btl2:   sty TMP
        lda KWID
        sec
        sbc #14
        sbc TMP
        tax
btl3:   lda #32
        jsr CHROUT
        dex
        bne btl3
        ldy #0
btl4:   lda banner+13,y
        cmp #13
        beq btl5
        jsr CHROUT
        iny
        bne btl4
btl5:   lda #32
        jsr CHROUT
        lda #146
        jsr CHROUT
        lda #13
        jsr CHROUT
        lda #13
        jmp CHROUT

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
        jsr brule
        jsr kkeys               ; keys white, words light blue
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
scrpos: jsr k40m                ; Kawari 80: menus use the 40 column screen
        ldy MNROW
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
        jsr mnhint              ; the keys, under the frame
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
        lda #<LOGODAT
        sta PTR
        lda #>LOGODAT
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
        lda #16
        sta NMIEN           ; what the handler will believe is enabled
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
        lda C2ICR           ; read = acknowledge
        and NMIEN           ; only what we enabled (KERNAL $FE73)
        lsr
        lsr                 ; C = timer B
        bcc nmflag
        lda C2PRB           ; --- sample a data bit ---
        lsr                 ; PB0 -> carry
        ror SHIFT
        dec BITCNT
        beq nmbyte
        pla
        rti

nmflag: and #4              ; FLAG (bit 4, shifted down two)
        beq nmx1
        lda hblo            ; --- start bit: half a bit + one to bit 0 ---
        sta C2TBLO
        lda hbhi
        sta C2TBHI
        lda #17             ; force load, start, CONTINUOUS
        sta C2CRB
        lda btlo            ; timer running: these go to the latch only,
        sta C2TBLO          ; so every later underflow is one bit apart
        lda bthi
        sta C2TBHI
        lda #127
        sta C2ICR
        lda #130            ; now interrupt on timer B instead
        sta C2ICR
        lda #2
        sta NMIEN
        lda #8              ; 8 data bits; the stop bit is not sampled
        sta BITCNT
nmx1:   pla
        rti

; --- eighth bit sampled: store it and re-arm on the next start bit ---
nmbyte: lda #0
        sta C2CRB           ; stop the bit clock
        txa
        pha
        lda SHIFT
        ldx RHEAD
        sta RBUF,x
        inc RHEAD
; the entry read acknowledged every data-edge FLAG; the line only rises
; from here to the next start bit, so a FLAG latched now is that start bit
        lda #127
        sta C2ICR
        lda #16
        sta NMIEN
        lda #144
        sta C2ICR
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
        sta TXNX
        lda #17             ; restart the bit clock for this byte
        sta C2CRA
        lda C2ICR           ; drop an underflow latched before it
        lda TXNX
        sta C2PRA           ; start edge, ~11 cycles after the restart
        ldx #8
txbl:   lda C2PRA           ; next level FIRST, then wait, then write:
        and #251            ; the edge lands a fixed ~12 cycles after
        lsr TXB             ; the underflow instead of after this work
        bcc txb0
        ora #4
txb0:   sta TXNX
txbw:   lda C2ICR
        and #1
        beq txbw
        lda TXNX
        sta C2PRA
        dex
        bne txbl
        lda C2PRA
        ora #4              ; stop bit: high
        sta TXNX
txbw2:  lda C2ICR
        and #1
        beq txbw2
        lda TXNX
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
txwaitc: lda bthi
        bne txwch           ; bit >= 256 cycles: the high byte moves
        lda C2TALO          ; short bit (4800+): high byte is always 0
        sta TXW
txwll:  lda C2TALO
        cmp TXW
        sta TXW
        bcc txwll           ; still counting down
        rts                 ; jumped up: the timer reloaded
txwch:  lda C2TAHI
        sta TXW
txwcl:  lda C2TAHI
        cmp TXW
        beq txwcl           ; unchanged: still counting within this byte
        bcs txwcd           ; went UP = the timer reloaded = underflow
        sta TXW             ; went down, as expected; keep watching
        jmp txwcl
txwcd:  rts

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
        lda #0
        sta TXLST
        lda #127
        sta C2ICR           ; receiver off for the duration: half duplex,
                            ; which is what this protocol actually is
        lda #0
        sta NMIEN
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
        rts
SFY:    .byte 0

; ===== drain our ring and reassemble frames ============================
poll:   jsr kmir                ; 80 columns: show the menu (s33)
        jsr tick
        lda READY
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
        bne nfrm1
        inc NFRMH               ; frames, 16-bit (F1 > Stats)
nfrm1:
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
s1warm: lda #55                 ; basic back in, then its own warm start
        sta 1
        jmp ($A002)

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
chktik: rts

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

        lda #153                ; light green: we are up
        jsr CHROUT
        lda #<msgrdy
        sta PTR
        lda #>msgrdy
        sta PTRH
        jsr prtstr
        jsr radinf
        jsr ucset
        jsr keyhelp
        jsr bootscan
        lda GREST
        beq bnohis
        jsr kcrow               ; restored session: as much of its history
        sta KT5                 ; as fits between the boot text (cursor
        lda #24                 ; row) and the prompt; f5 for more
        sec
        sbc KT5
        bcc bnohis
        beq bnohis
        sta APMAX
        jsr arcpage
        lda #24
        sta APMAX
        ldx #23
        ldy #0
        clc
        jsr kplot               ; $fff0 PLOT: prompt on the bottom row
bnohis: jsr setprm
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

dispat: jsr clkhook             ; message timestamps can set the clock
        lda BUF
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
        cmp #16                 ; RESP_CODE_CONTACT_MSG_RECV_V3 (a DM)
        beq ddmj
        cmp #9                  ; RESP_CODE_CURR_TIME
        beq dtime
        cmp #133                ; 0x85, push_code_login_success
        beq dlogin
        cmp #134                ; 0x86, push_code_login_fail
        bne dsp86
        jmp dlgfail
dsp86:  lda BUF
        cmp #138                ; 0x8a, push_code_new_advert
        bne dsa1
        jmp dnadv
dsa1:   cmp #128                ; 0x80, push_code_advert (key only)
        bne dsa2
        jmp dadv
dsa2:   cmp #6                  ; RESP_CODE_SENT: our DM's ack tag
        bne dsa3
        jmp pnsent
dsa3:   cmp #130                ; 0x82, push_code_send_confirmed
        bne dsa4
        jmp pnack
dsa4:   cmp #136                ; 0x88, push_code_log_rx_data
        bne dsa5
        jmp pnlog
dsa5:   cmp #1                  ; RESP_CODE_ERR: did it refuse our send?
        bne dsa6
        jmp pnerr
dsa6:
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
ddmj:   jmp ddm
dchan:  jmp rxchan
dcont:  lda SCBUSY
        bne dcn
        jmp dnadv               ; nobody asked: our fetch-by-key reply
dcn:    jmp rxcont
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
        jmp notice
dlgrt:  rts

; ===== message timestamps ==============================================
; **Every message used to go out stamped ZERO.** That is not cosmetic and
; it is not a display problem -- it stops messages reaching the mesh at
; all.
;
; The firmware folds the timestamp into the packet, calling it "mostly an
; extra blob to help make packet_hash unique", and every repeater drops a
; hash it has already seen (SimpleMeshTables::wasSeen). With a constant
; zero, the same text from the same sender on the same channel is
; byte-identical every time, hashes identically, and is swallowed by the
; first node that already has that hash in its table. Sending "hi" twice
; meant the second one simply never existed.
;
; The radio has a real clock and the handshake already asks for it with
; CMD_GET_DEVICE_TIME. The reply was recognised and discarded. Now we keep
; it, and advance it from the C64's own jiffy clock between updates.
dtime:  ldx #0
dtl:    lda BUF+1,x
        sta NOWTS,x
        inx
        cpx #4
        bcc dtl
        lda #0
        sta TSCNT
        lda JIFFY
        sta TSJIF
        lda #1
        sta TSOK
        rts

; Called from poll, so it runs whenever anything else is running. JIFFY is
; the low byte of TI and wraps every 256 jiffies (~4.3s); poll is called
; far more often than that, so a one-byte delta is always enough.
tick:   lda TSOK
        beq tckrt
        lda JIFFY
        sec
        sbc TSJIF
        beq tckrt               ; same jiffy, nothing has moved
        clc
        adc TSCNT
        bcs tckrt               ; absurd gap; drop it rather than skip years
        sta TSCNT
        lda JIFFY
        sta TSJIF
tck2:   lda TSCNT
        cmp #60
        bcc tckrt
        sec
        sbc #60
        sta TSCNT
        jsr tsinc
        jmp tck2
tckrt:  rts

tsinc:  inc NOWTS
        bne tsirt
        inc NOWTS+1
        bne tsirt
        inc NOWTS+2
        bne tsirt
        inc NOWTS+3
tsirt:  rts

; ===== clock from the mesh (s12) =======================================
clkhook:
        lda BUF
        cmp #17                 ; channel message: ts at 7
        bne chk16
        lda FLEN
        cmp #11
        bcc chkrt
        ldx #7
        jmp clksee
chk16:  cmp #16                 ; direct message: ts at 12
        bne chkrt
        lda FLEN
        cmp #16
        bcc chkrt
        ldx #12
        jmp clksee
chkrt:  rts

clksee: lda TSOK
        beq chkrt               ; we do not know the radio's time yet
        lda CLKSET
        bne chkrt               ; done this session
        ldy #0
cks1:   lda BUF,x
        sta CLKM,y
        inx
        iny
        cpy #4
        bcc cks1
; 2025-01-01 or later ($67748580), or it is someone else's unset clock
        lda CLKM
        cmp #$80
        lda CLKM+1
        sbc #$85
        lda CLKM+2
        sbc #$74
        lda CLKM+3
        sbc #$67
        bcc chkrt
; and a second message has to agree, so one node with a wild clock
; cannot drag ours off on its own
        lda CLKHAV
        beq cknew
        ldx #4                  ; T = candidate + 3600
        jsr ckcan
        ldx #0
        jsr ckcmp
        bcs cknew               ; M is over an hour past the candidate
        ldx #0                  ; T = M + 3600: is the candidate within it?
cksw:   lda CLKM,x
        sta CLKT,x
        inx
        cpx #4
        bcc cksw
        lda CLKT
        clc
        adc #$10
        sta CLKT
        lda CLKT+1
        adc #$0E
        sta CLKT+1
        lda CLKT+2
        adc #0
        sta CLKT+2
        lda CLKT+3
        adc #0
        sta CLKT+3
        ldx #4
        jsr ckcmp               ; candidate >= M + 3600: disagree
        bcs cknew
; agreed: report it, once a session; sync if over an hour behind
        lda #1
        sta CLKSET
        lda #0
        sta CKBOOT
        lda #60                 ; over a minute behind: sync
        sta CKTH
        lda #0
        sta CKTH+1
        lda #<tclkset
        sta CKMS
        lda #>tclkset
        sta CKMS+1
        lda #<sagree
        sta CKAG
        lda #>sagree
        sta CKAG+1
        jsr cklrn               ; the mesh is the truth: learn the offset
        lda #<slmesh
        ldx #>slmesh
        jsr ckrep
        lda UTCOFF
        cmp #$80
        beq ckm9
        lda UCOK
        cmp #2
        bne ckm9
        jmp ucnow
ckm9:   rts
cknew:  ldx #0
ckn1:   lda CLKM,x
        sta CLKC,x
        inx
        cpx #4
        bcc ckn1
        lda #1
        sta CLKHAV
        rts
; T = CLKC + 3600
ckcan:  lda CLKC
        clc
        adc #$10
        sta CLKT
        lda CLKC+1
        adc #$0E
        sta CLKT+1
        lda CLKC+2
        adc #0
        sta CLKT+2
        lda CLKC+3
        adc #0
        sta CLKT+3
        rts
; X=0: compare CLKM with CLKT; X=4: CLKC with CLKT. Carry set if >=.
ckcmp:  lda CLKM,x
        cmp CLKT
        lda CLKM+1,x
        sbc CLKT+1
        lda CLKM+2,x
        sbc CLKT+2
        lda CLKM+3,x
        sbc CLKT+3
        rts

; a system line where the prompt was, prompt redrawn under it
notice: lda UIMODE
        bne ntcrt
        jsr bkprm
        lda #155                ; grey
        jsr CHROUT
        jsr prtsp               ; leaves Y = length
ntcp:   cpy #39
        bcs ntcd
        lda #32
        jsr CHROUT
        iny
        jmp ntcp
ntcd:   lda #30
        jsr CHROUT
        jsr shoprm
ntcrt:  rts

dlgfail:
        lda UIMODE
        bne ntcrt
        lda #<tlogbad
        sta SPL
        lda #>tlogbad
        sta SPH
        jmp notice

tclkset: .text "radio clock set from the mesh"
        .byte 0

; ===== Ultimate clock (s13, mkuci.py) ==================================
ucboot: jsr ucget
        lda #155
        jsr CHROUT
        lda UCOK
        bne ucb1
        lda #<sucno
        ldx #>sucno
        jmp ucbp
ucb1:   cmp #2
        beq ucb2
        lda #<sucbad
        ldx #>sucbad
        jsr ucpr
        jmp ucbs
ucb2:   lda #<suclk
        ldx #>suclk
        jsr ucpr
ucbs:   lda #5
        jsr CHROUT
        lda #<UCSTR
        ldx #>UCSTR
ucbp:   jsr ucpr
        lda #13
        jmp CHROUT
ucpr:   sta PTR
        stx PTRH
        jmp prtstr

; the radio's time is known now; move it forward to the Ultimate's
ucset:  jmp ucset4              ; two lines at boot (segment 4)
; the Ultimate, as UTC, against the radio; also right after the mesh has
; taught us the offset
ucnow:  jsr ucget
        lda UCOK
        cmp #2
        bne ucsrt
        jsr uctoutc             ; CLKM = its time as UTC
        lda #60                 ; within 60 s counts as agreeing
        sta CKTH
        lda #0
        sta CKTH+1
        lda #<sucset
        sta CKMS
        lda #>sucset
        sta CKMS+1
        lda #<sagree
        sta CKAG
        lda #>sagree
        sta CKAG+1
        lda #0
        sta CKDN
        lda #<slult
        ldx #>slult
        jsr ckrep
        lda CKDN                ; verified: the mesh need not repeat it
        beq ucn9
        lda #1
        sta CLKSET
ucn9:   rts
ucrad:  ldx #3
ucr1:   lda NOWTS,x
        sta UCAC,x
        dex
        bpl ucr1
        lda #<slrad
        ldx #>slrad
        jmp ckln
ucsrt:  rts

suclk:  .text "clock    "
        .byte 5
        .text "ultimate "
        .byte 0
sucno:  .text "clock    "
        .byte 5
        .text "none - set from the mesh"
        .byte 0
sucbad: .text "clock    unreadable: "
        .byte 0
sucset: .text "radio clock set from the ultimate"
        .byte 0

; ===== clock report (s14, mkclk.py) ====================================
; CLKM = a detected time, A/X = its label. Show it and the radio's time,
; then set the radio if it is more than CKTH seconds behind, or say why not.
ckrep:  sta CKL
        stx CKL+1
        ldx #3
ckr0:   lda CLKM,x
        sta UCAC,x
        dex
        bpl ckr0
        lda CKL
        ldx CKL+1
        jsr ckln
        ldx #3
ckr1:   lda NOWTS,x
        sta UCAC,x
        dex
        bpl ckr1
        lda #<slrad
        ldx #>slrad
        jsr ckln
        jsr ckgap
        lda NOWTS               ; behind: detected >= radio + CKTH
        clc
        adc CKTH
        sta CLKT
        lda NOWTS+1
        adc CKTH+1
        sta CLKT+1
        lda NOWTS+2
        adc #0
        sta CLKT+2
        lda NOWTS+3
        adc #0
        sta CLKT+3
        ldx #0
        jsr ckcmp
        bcs ckq
        lda CLKM                ; ahead: radio >= detected + CKTH
        clc
        adc CKTH
        sta CLKT
        lda CLKM+1
        adc CKTH+1
        sta CLKT+1
        lda CLKM+2
        adc #0
        sta CLKT+2
        lda CLKM+3
        adc #0
        sta CLKT+3
        lda NOWTS
        cmp CLKT
        lda NOWTS+1
        sbc CLKT+1
        lda NOWTS+2
        sbc CLKT+2
        lda NOWTS+3
        sbc CLKT+3
        ldy #2
        sty CKV                 ; (radio ahead)
        lda #<sahead
        ldx #>sahead
        bcs ckout
        ldy #0
        sty CKV                 ; in sync
        lda #1
        sta CKDN                ; in sync
        lda CKAG                ; source's own "close enough" wording
        ldx CKAG+1
        jmp ckout
ckq:    lda #6                  ; CMD_SET_DEVICE_TIME (forward only)
        sta TXBUF
        ldx #0
ckq1:   lda CLKM,x
        sta TXBUF+1,x
        sta NOWTS,x
        inx
        cpx #4
        bcc ckq1
        lda #0
        sta TSCNT
        lda JIFFY
        sta TSJIF
        lda #5
        sta TXLEN
        jsr sendfr
        lda #1
        sta CKDN                ; just synced
        sta CKV
        lda CKMS
        ldx CKMS+1
        jmp ckout
ckln:   jsr tsline
        lda #<TSTR
        ldx #>TSTR
; a line: at boot printed in place, later as a notice over the prompt
ckout:  sta SPL
        stx SPH
        lda CKBOOT
        bne ckob
        jmp notice
ckob:   lda CKQ                 ; quiet: the boot summary prints instead
        beq ckob2
        rts
ckob2:  lda #155
        jsr CHROUT
        jsr prtsp
        lda #13
        jsr CHROUT
        lda #5
        jmp CHROUT

slult:  .text "ultimate time "
        .byte 0
slmesh: .text "mesh time     "
        .byte 0
slrad:  .text "radio time    "
        .byte 0
sutc:   .text " utc"
        .byte 0
sagree: .text "clocks agree - no sync needed"
        .byte 0
sahead: .text "radio is ahead - left as is"
        .byte 0
CKL:    .byte 0,0
CKTH:   .byte 0,0
CKMS:   .byte 0,0
CKBOOT: .byte 0
lrxset: pha                     ; (pnrec still needs its A)
        sei
        lda $A2
        sta LRX
        lda $A1
        sta LRX+1
        lda $A0
        sta LRX+2
        cli
        lda #1
        sta LRXOK
        pla
        rts
LRX:    .byte 0,0,0
soff:   .text "Offset    "
        .byte 0
srad:   .text "radio "
        .byte 0
slast:  .text "Last msg  "
        .byte 0
snoyet: .text "none yet"
        .byte 0
sago:   .text " ago"
        .byte 0
sss:    .text "s"
        .byte 0
LRXOK:  .byte 0

; ===== Radio actions > Purge old nodes (s39, mkpurge.py) ================
; Asks for a number of days, reads the radio's whole node list and keeps
; the keys of the nodes not heard from since then (the later of their last
; advert and the radio's last update of them; favourites never), then, once
; the list has ended -- the C64 cannot listen while it sends -- removes each
; with CMD_REMOVE_CONTACT. The keys are kept in the C64's node table, which
; is emptied for it: every list is fetched again the next time it opens.
purge4: lda #<tpgq
        sta MNTIT
        lda #>tpgq
        sta MNTITH
        jsr inpget
        lda INPOK
        beq pgx
        lda #0                  ; the number typed, up to 4 digits
        sta UCAC
        sta UCAC+1
        sta UCAC+2
        sta UCAC+3
        sta PGI
pgn1:   ldx PGI
        cpx INPLEN
        bcs pgn2
        lda INPASC,x
        sec
        sbc #48
        cmp #10
        bcs pgn2
        tax
        lda #10
        jsr ucmul               ; UCAC = UCAC * 10 + digit
        inc PGI
        lda PGI
        cmp #4
        bcc pgn1
pgn2:   lda UCAC
        sta PGD
        lda UCAC+1
        sta PGD+1
        ora PGD
        beq pgx                 ; nothing (or 0): leave it
        lda TSOK
        bne pgc
pgx:    jmp mmshut
; cutoff = radio time - days * 86400 (UCAC still holds the days)
pgc:    lda #24
        ldx #0
        jsr ucmul
        lda #60
        ldx #0
        jsr ucmul
        lda #60
        ldx #0
        jsr ucmul
        ldx #0
        ldy #4
        sec
pgc1:   lda NOWTS,x
        sbc UCAC,x
        sta PGCUT,x
        inx
        dey
        bne pgc1
; the list
        jsr k80c
        lda #1
        sta SCBUSY
        sta UIMODE
        lda #0
        sta NCONT
        sta PGN
        sta PGCH
        sta PGCH+1
        sta PGRM
        lda MAXCON              ; keys fit two to a node slot
        asl
        bcc pgm1
        lda #255
pgm1:   sta PGMAX
        lda #0
        ldx #4
pgt0:   sta TLOAD,x             ; every node list reloads next time
        dex
        bpl pgt0
        lda #147
        jsr CHROUT
        lda #<tpg1
        sta SPL
        lda #>tpg1
        sta SPH
        jsr prtsp
        lda #13
        jsr CHROUT
        lda #13
        jsr CHROUT
        lda #4                  ; CMD_GET_CONTACTS, all of them
        sta TXBUF
        lda #1
        sta TXLEN
        jsr sendfr
        jsr pgw0
pgl1:   jsr pgw
        bcc pgl2
        jmp pgend               ; quiet too long: done
pgl2:   lda BUF
        cmp #4                  ; END_OF_CONTACTS
        bne pgl3
        jmp pgend
pgl3:
        cmp #3                  ; a contact
        beq pgcon
        cmp #2
        beq pgnx                ; CONTACTS_START
        jsr dispat              ; anything else as usual
pgnx:   lda #0
        sta READY
        jmp pgl1
pgcon:  inc PGCH
        bne pgk1
        inc PGCH+1
pgk1:   lda FLEN
        cmp #148
        bcc pgnx
        lda BUF+34              ; a favourite: keep
        and #1
        bne pgnx
        ldx #0                  ; seen recently by either clock: keep
        jsr pgold
        bcc pgnx
        ldx #12
        jsr pgold
        bcc pgnx
        lda PGN                 ; old: keep its key for afterwards
        cmp PGMAX
        bcs pgnx
        lsr
        lsr
        lsr
        clc
        adc CBASEH
        sta PTRH
        lda PGN
        and #7
        asl
        asl
        asl
        asl
        asl
        sta PTR
        ldy #31
pgk2:   lda BUF+1,y
        sta (PTR),y
        dey
        bpl pgk2
        inc PGN
        jsr pgshow
        jmp pgnx

; ===== nodes the radio announces (s21, mkauto.py) ======================
; 0 = found, carry set = not in the table. Key at BUF+1.
ckfind: lda #0
        sta CFI
cfl:    lda CFI
        cmp NCONT
        bcs cfno
        jsr contptr
        ldy #26
        ldx #0
cfc:    lda (PTR),y
        cmp BUF+1,x
        bne cfn
        iny
        inx
        cpx #8
        bcc cfc
        clc
        rts
cfn:    inc CFI
        jmp cfl
cfno:   sec
cfrt:   rts
; a whole record, from 0x8a or a reply to our fetch-by-key
dnadv:  lda SCBUSY
        bne cfrt
        lda FLEN
        cmp #101
        bcc cfrt
        lda BUF+33              ; type 1-4: companion, repeater, room, sensor
        beq cfrt
        cmp #5
        bcs cfrt
        tax
        lda TLOAD,x             ; a list never opened is fetched whole later
        beq cfrt
        jsr ckfind
        bcc cfrt
        lda NCONT
        cmp MAXCON
        bcs cfrt
        lda NTYPE
        pha
        lda BUF+33
        sta NTYPE
        jsr rxcont
        pla
        sta NTYPE
        lda #1
        sta CDIRTY
        lda $A1                 ; TI middle byte: ticks every 4.3 s
        sta CDT
        rts
; one save for a burst of new nodes, ~20 s after the last
ctsave: lda CDIRTY
        beq cfrt
        lda $A1
        sec
        sbc CDT
        cmp #5
        bcc cfrt
        lda #0
        sta CDIRTY
        jmp gsvk
CFI:    .byte 0
CDIRTY: .byte 0
CDT:    .byte 0
CKDN:   .byte 0
rqbuild:
        lda CIDX
        jsr contptr
        lda RQMODE
        cmp #1
        beq rqbt
        lda #26                 ; CMD_SEND_LOGIN
        sta TXBUF
        jsr cpykey
        ldx #0
rqb1:   cpx INPLEN
        bcs rqb2
        lda INPASC,x
        sta TXBUF+33,x
        inx
        jmp rqb1
rqb2:   txa
        clc
        adc #33
        sta TXLEN
        rts
rqbt:   lda #39                 ; CMD_SEND_TELEMETRY_REQ
        sta TXBUF
        lda #0
        sta TXBUF+1
        sta TXBUF+2
        sta TXBUF+3
        ldx #0
rqb3:   txa
        clc
        adc #26
        tay
        lda (PTR),y
        sta TXBUF+4,x
        inx
        cpx #32
        bcc rqb3
        lda #36
        sta TXLEN
        rts

; CMD_RESET_PATH for the node, and forget the route here too
rstp:   lda CIDX
        jsr contptr
        lda #13
        sta TXBUF
        jsr cpykey
        ldy #58
        lda #255
        sta (PTR),y
        lda #33
        sta TXLEN
        jsr sendfr
        lda #0
        sta STGBIT
        lda #0                  ; RESP_CODE_OK
        jmp waitop

; the panel for whatever happened (success for telemetry is drawn by lppdec)
rqshow: jsr plinit
        lda RQRES
        cmp #1
        beq rqs1
        cmp #2
        beq rqs2
        cmp #3
        beq rqs3
        lda RQMODE              ; no answer
        cmp #1
        beq rqst
        cmp #2
        beq rqsg2
        lda #<tnorpl
        ldx #>tnorpl
        jsr rqln
        jsr rqpath
        lda #<twrongp
        ldx #>twrongp
        jmp rqln
rqsg2:  lda #<tnorpl           ; the guest login before a telemetry request
        ldx #>tnorpl
        jsr rqln
        jsr rqpath
        lda #<tneedpw
        ldx #>tneedpw
        jmp rqln
rqst:   lda #<tnorpl
        ldx #>tnorpl
        jsr rqln
        jsr rqpath
        lda #<tnotel
        ldx #>tnotel
        jmp rqln
rqs1:   lda #<tlgin             ; a login that worked
        ldx #>tlgin
        jsr rqln
        lda BUF+1               ; is_admin
        beq rqsg
        lda #<tpadm
        ldx #>tpadm
        jmp rqln
rqsg:   lda #<tpgst
        ldx #>tpgst
        jmp rqln
rqs2:   lda #<tlogbad
        ldx #>tlogbad
        jmp rqln
rqs3:   lda #<tradno
        ldx #>tradno
        jsr rqln
        jsr plnew
        lda #<terrc
        sta SPL
        lda #>terrc
        sta SPH
        jsr plstr
        lda RQERR
        sta NUML
        lda #0
        sta NUMH
        jsr pldec
        jsr plend
        lda RQERR
        cmp #2
        bne rqs3b
        lda #<tnotin
        ldx #>tnotin
        jmp rqln
rqs3b:  cmp #3
        bne rqs3c
        lda #<ttabf
        ldx #>ttabf
        jmp rqln
rqs3c:  rts
; how it went out
rqpath: lda RQF1
        cmp #255
        bne rqp1
        lda #<tnocnf
        ldx #>tnocnf
        jmp rqln
rqp1:   cmp #1
        bne rqp2
        lda #<tflooded
        ldx #>tflooded
        jmp rqln
rqp2:   lda RQF2                ; direct first
        cmp #255
        bne rqp3
        lda #<tdirect
        ldx #>tdirect
        jmp rqln
rqp3:   lda #<tdirfl
        ldx #>tdirfl
        jmp rqln
; one whole line: string at A/X
rqln:   sta SPL
        stx SPH
        jsr plnew
        jsr plstr
        jmp plend

tneedpw: .text "May need a login password"
        .byte 0
twaitn: .text "waiting for the node..."
        .byte 0
tnorpl: .text "No reply from the node"
        .byte 0
twrongp: .text "Wrong password = no reply"
        .byte 0
tlgin:  .text "Logged in"
        .byte 0
tpadm:  .text "Permission: admin"
        .byte 0
tpgst:  .text "Permission: guest"
        .byte 0
tradno: .text "The radio refused"
        .byte 0
terrc:  .text "Error code "
        .byte 0
tnotin: .text "Node not in the radio list"
        .byte 0
ttabf:  .text "Radio table full"
        .byte 0
tnocnf: .text "Radio never confirmed it"
        .byte 0
tflooded: .text "Sent by flood"
        .byte 0
tdirect: .text "Sent direct"
        .byte 0
tdirfl: .text "Tried direct, then flood"
        .byte 0
RQMODE: .byte 0
RQTRY:  .byte 0
RQF1:   .byte 0
RQF2:   .byte 0
RQFLD:  .byte 0
RQRES:  .byte 0
RQERR:  .byte 0
RQWANT: .byte 0
; "radio is      00:06:47 behind" -- CLKM against the radio
ckgap:  ldx #0
        ldy #4
        sec
ckg1:   lda CLKM,x
        sbc NOWTS,x
        sta UCAC,x
        inx
        dey
        bne ckg1
        lda UCAC+3
        sta CKSG                ; bit 7: the radio is ahead
        bpl ckg2
        ldx #0
        ldy #4
        sec
ckg3:   lda #0
        sbc UCAC,x
        sta UCAC,x
        inx
        dey
        bne ckg3
ckg2:   lda #0
        sta TSN
        lda #<sgap
        ldx #>sgap
        jsr tscat
        lda #$80                ; 86400
        ldx #$51
        ldy #$01
        jsr ucdiv               ; days; the rest in UCR
        lda UCAC+1
        ora UCAC+2
        ora UCAC+3
        bne ckgbig
        lda UCAC
        beq ckghms
        cmp #100
        bcs ckgbig
        jsr ts2d
        lda #<sdays
        ldx #>sdays
        jsr tscat
        jmp ckgdir
ckgbig: lda #<sover
        ldx #>sover
        jsr tscat
        jmp ckgdir
ckghms: jsr tscr
        lda #$10                ; 3600
        ldx #$0E
        ldy #0
        jsr ucdiv
        lda UCAC
        jsr ts2d
        lda #58
        jsr tschr
        jsr tscr
        lda #60
        ldx #0
        ldy #0
        jsr ucdiv
        lda UCAC
        jsr ts2d
        lda #58
        jsr tschr
        lda UCR
        jsr ts2d
        lda #32
        jsr tschr
ckgdir: lda #<sbehd
        ldx #>sbehd
        bit CKSG
        bpl ckgd2
        lda #<sahd
        ldx #>sahd
ckgd2:  jsr tscat
        lda #<TSTR
        ldx #>TSTR
        jmp ckout
sgap:   .text "radio is      "
        .byte 0
sdays:  .text " days "
        .byte 0
sover:  .text "over 99 days "
        .byte 0
sbehd:  .text "behind"
        .byte 0
sahd:   .text "ahead"
        .byte 0
CKAG:   .byte 0,0
CKSG:   .byte 0
UTCOFF: .byte $80               ; Ultimate local - UTC, in 15 min; $80 unknown

; CLKM = UCTS - UTCOFF * 900
uctoutc:
        lda UTCOFF
        bpl uto1
        eor #$FF
        clc
        adc #1
uto1:   sta UCAC
        lda #0
        sta UCAC+1
        sta UCAC+2
        sta UCAC+3
        lda #30
        ldx #0
        jsr ucmul
        lda #30
        ldx #0
        jsr ucmul               ; |offset| * 900
        ldx #0
        ldy #4
        lda UTCOFF
        bmi uto3
        sec
uto2:   lda UCTS,x
        sbc UCAC,x
        sta CLKM,x
        inx
        dey
        bne uto2
        rts
uto3:   clc
uto4:   lda UCTS,x
        adc UCAC,x
        sta CLKM,x
        inx
        dey
        bne uto4
        rts

; CLKM = the mesh's time. Read the Ultimate now; its offset from UTC is
; the difference, to the nearest 15 minutes. A change (first time, or
; daylight saving) is kept with the saved session and reported.
cklrn:  lda UCOK
        cmp #2
        bne ckl9
        jsr ucget
        lda UCOK
        cmp #2
        bne ckl9
        ldx #0
        ldy #4
        sec
ckl1:   lda UCTS,x              ; local - utc
        sbc CLKM,x
        sta UCAC,x
        inx
        dey
        bne ckl1
        lda UCAC+3
        sta CKSG
        bpl ckl2
        ldx #0
        ldy #4
        sec
ckl3:   lda #0
        sbc UCAC,x
        sta UCAC,x
        inx
        dey
        bne ckl3
ckl2:   lda UCAC                ; + 450, / 900: rounded
        clc
        adc #$C2
        sta UCAC
        lda UCAC+1
        adc #$01
        sta UCAC+1
        lda UCAC+2
        adc #0
        sta UCAC+2
        lda UCAC+3
        adc #0
        sta UCAC+3
        lda #$84
        ldx #$03
        ldy #0
        jsr ucdiv
        lda UCAC+1
        ora UCAC+2
        ora UCAC+3
        bne ckl9
        lda UCAC
        cmp #57                 ; past 14 hours: not a time zone
        bcs ckl9
        ldx CKSG
        bpl ckl4
        eor #$FF
        clc
        adc #1
ckl4:   cmp UTCOFF
        beq ckl9
        sta UTCOFF
        jsr gsvh                ; with the saved session (GeoRAM / REU)
        jmp ucoffln
ckl9:   rts

; "ultimate clock is utc-05:00"
ucoffln:
        lda #0
        sta TSN
        lda #<sucoff
        ldx #>sucoff
        jsr tscat
        lda UTCOFF
        bmi ucf1
        sta CKSG
        lda #43                 ; +
        bne ucf2
ucf1:   eor #$FF
        clc
        adc #1
        sta CKSG
        lda #45                 ; -
ucf2:   jsr tschr
        lda CKSG
        lsr
        lsr
        jsr ts2d
        lda #58
        jsr tschr
        lda CKSG
        and #3
        tax
        lda ucfm,x
        jsr ts2d
        lda #<TSTR
        ldx #>TSTR
        jmp ckout
ucfm:   .byte 0,15,30,45
sucoff: .text "ultimate clock is utc"
        .byte 0

; ===== Unix time -> text (s14, mkclk.py) ===============================
; TSTR = the label at A/X + "yyyy/mm/dd hh:mm:ss" + sutc, from UCAC
tsline: ldy #0
        sty TSN
        jsr tscat
        lda #$80                ; 86400 = $015180
        ldx #$51
        ldy #$01
        jsr ucdiv               ; days; seconds of the day left in UCR
        lda UCAC
        sta UCDY
        lda UCAC+1
        sta UCDY+1
        jsr tscr
        lda #$10                ; 3600
        ldx #$0E
        ldy #0
        jsr ucdiv
        lda UCAC
        sta UCHH
        jsr tscr
        lda #60
        ldx #0
        ldy #0
        jsr ucdiv               ; minutes; seconds left in UCR
        lda UCAC
        sta UCMM
        ldx #70                 ; year - 1900
tsy1:   lda #$6D                ; 365 = $016D
        sta UCT
        txa
        and #3
        bne tsy2
        inc UCT                 ; leap year (2000 included)
tsy2:   lda UCDY
        sec
        sbc UCT
        sta UCT+2
        lda UCDY+1
        sbc #1
        bcc tsy3
        sta UCDY+1
        lda UCT+2
        sta UCDY
        inx
        bne tsy1
tsy3:   stx UCY
        ldx #1
tsm1:   cpx #12
        bcs tsm3                ; december: whatever is left
        lda UCML-1,x
        cpx #2
        bne tsm2
        lda UCY
        and #3
        beq tsfl
        lda #28
        bne tsm2
tsfl:   lda #29
tsm2:   sta UCT
        lda UCDY
        sec
        sbc UCT
        tay
        lda UCDY+1
        sbc #0
        bcc tsm3
        sta UCDY+1
        sty UCDY
        inx
        bne tsm1
tsm3:   stx UCMO
        lda UCY
        cmp #100
        bcc ts19
        sbc #100
        pha
        lda #50                 ; 20yy
        jsr tschr
        lda #48
        jmp tsyy
ts19:   pha
        lda #49                 ; 19yy
        jsr tschr
        lda #57
tsyy:   jsr tschr
        pla
        jsr ts2d
        lda #47
        jsr tschr
        lda UCMO
        jsr ts2d
        lda #47
        jsr tschr
        ldx UCDY
        inx
        txa
        jsr ts2d
        lda #32
        jsr tschr
        lda UCHH
        jsr ts2d
        lda #58
        jsr tschr
        lda UCMM
        jsr ts2d
        lda #58
        jsr tschr
        lda UCR
        jsr ts2d
        lda #<sutc
        ldx #>sutc
; append the string at A/X
tscat:  sta SPL
        stx SPH
        ldy #0
tsc1:   lda (SPL),y
        beq tsc2
        jsr tschr
        iny
        bne tsc1
tsc2:   rts
; A = 0..99 as two digits
ts2d:   ldx #47
tsd1:   inx
        sec
        sbc #10
        bcs tsd1
        adc #58
        pha
        txa
        jsr tschr
        pla
; one character (tschr); keeps TSTR terminated; Y is left alone
tschr:  ldx TSN
        sta TSTR,x
        inx
        stx TSN
        lda #0
        sta TSTR,x
        rts
; UCAC = UCAC / (A + X*256 + Y*65536), remainder in UCR
ucdiv:  sta UCDV
        stx UCDV+1
        sty UCDV+2
        lda #0
        sta UCR
        sta UCR+1
        sta UCR+2
        ldx #32
udv1:   asl UCAC
        rol UCAC+1
        rol UCAC+2
        rol UCAC+3
        rol UCR
        rol UCR+1
        rol UCR+2
        lda UCR
        sec
        sbc UCDV
        tay
        lda UCR+1
        sbc UCDV+1
        sta UCT
        lda UCR+2
        sbc UCDV+2
        bcc udv2
        sta UCR+2
        lda UCT
        sta UCR+1
        sty UCR
        inc UCAC
udv2:   dex
        bne udv1
        rts
; UCAC = UCR
tscr:   ldx #2
tscr1:  lda UCR,x
        sta UCAC,x
        dex
        bpl tscr1
        lda #0
        sta UCAC+3
        rts
UCDV:   .byte 0,0,0
UCR:    .byte 0,0,0
UCDY:   .byte 0,0
UCHH:   .byte 0
UCMM:   .byte 0
UCMO:   .byte 0
TSN:    .byte 0

; " repeaters (12) " into NTBUF, and make it the menu title
ndtit:  ldx NTYPE
        dex
        txa
        asl
        tax
        lda nttab,x
        sta SPL
        lda nttab+1,x
        sta SPH
        lda #32
        sta NTBUF
        ldx #1
        ldy #0
ndt1:   lda (SPL),y
        beq ndt2
        sta NTBUF,x
        inx
        iny
        bne ndt1
ndt2:   lda #32
        sta NTBUF,x
        inx
        lda #40                 ; (
        sta NTBUF,x
        inx
        lda NVIS
        sta NDV
        lda #0
        sta NDZ
        ldy #0
ndh1:   lda NDV
        cmp #100
        bcc ndh2
        sbc #100
        sta NDV
        iny
        bne ndh1
ndh2:   tya
        jsr ndig
        ldy #0
ndh3:   lda NDV
        cmp #10
        bcc ndh4
        sbc #10
        sta NDV
        iny
        bne ndh3
ndh4:   tya
        jsr ndig
        lda NDV
        ora #48
        sta NTBUF,x
        inx
        jsr nfslash             ; "/total" when a filter is on
        lda #41                 ; )
        sta NTBUF,x
        inx
        lda #32
        sta NTBUF,x
        inx
        lda #0
        sta NTBUF,x
        lda #<NTBUF
        sta MNTIT
        lda #>NTBUF
        sta MNTITH
        rts
; a digit, unless it is a leading zero
ndig:   bne ndg1
        ldy NDZ
        beq ndg2
ndg1:   ora #48
        sta NTBUF,x
        inx
        lda #1
        sta NDZ
ndg2:   rts
NDV:    .byte 0
NDZ:    .byte 0
NTBUF:  .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
tlogbad: .text "login refused - check the password"
        .byte 0
CLKM:   .byte 0,0,0,0           ; this message's time
CLKC:   .byte 0,0,0,0           ; the previous candidate (must follow CLKM)
CLKT:   .byte 0,0,0,0
CLKHAV: .byte 0
CLKSET: .byte 0

; Stamp an outgoing frame. Both message commands put the timestamp at the
; same offset: SEND_TXT_MSG is [2][type][attempt][ts:4][key:6][text] and
; SEND_CHANNEL_TXT_MSG is [3][type][chan][ts:4][text].
;
; The value must DIFFER from the last one we sent. Two messages inside the
; same second would otherwise hash alike and the second would be dropped
; as a duplicate -- the same trap as the constant zero, just narrower.
tsput:  lda NOWTS
        cmp LSTTS
        bne tsu2
        lda NOWTS+1
        cmp LSTTS+1
        bne tsu2
        lda NOWTS+2
        cmp LSTTS+2
        bne tsu2
        lda NOWTS+3
        cmp LSTTS+3
        bne tsu2
        jsr tsinc               ; this second is used up; step forward
tsu2:   ldx #0
tspl:   lda NOWTS,x
        sta LSTTS,x
        sta TXBUF+3,x
        inx
        cpx #4
        bcc tspl
        rts

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
; **Read the channel back from MCH, not TMP.** arcmsg's helpers use TMP as
; scratch -- lput leaves line*2 in it, chnptr the low byte of index*2 --
; so a message for the channel you were IN was being compared as channel
; 0: it printed "+1", counted an unread against Public, and only showed
; up when you re-selected the channel and it repainted from the archive.
; **Filtered for display, never for delivery.** The radio holds one queue
; shared by every channel, so a message for a channel we are not watching
; still has to be collected -- skipping it would strand it and back the
; queue up. It just is not printed.
; An incoming DM joins here too, with MCH = its conversation (40-47).
dmroute:
        lda CC
        cmp #255
        beq dmshow          ; "All" shows everything
        lda MCH
        cmp CC
        beq dmshow
        ldx MCH
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
dmshow: jsr lrxset
        inc MSGS
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

; ===== an incoming direct message ======================================
; **Opcode 16 was not handled at all.** It fell through to the "unknown"
; branch, which does NOT re-issue SYNC_NEXT_MESSAGE -- so one incoming DM
; wedged the radio's queue and nothing arrived after it, channel messages
; included. Losing DMs was the smaller half of that bug.
;
;   [16][snr][0][0][key:6][path_len][txt_type][timestamp:4][text]
;
; Unlike a channel message, the firmware does not prefix the sender's
; name -- a DM is identified by its key. So look the key up and build
; "<name>: <text>", which is the shape shomsg already colours by sender.
ddm:    lda FLEN
        cmp #17
        bcc dbad
        lda BUF+11              ; txt_type -- from the RAW buffer
        cmp #3
        bcs dbad
        jsr ledrx
        lda #0
        sta DMI
        jsr dmwho
        bcs ddmq                ; never seen this node
        ldy #0
ddmn:   cpy #16
        bcs ddmsep
        lda (PTR),y
        beq ddmsep
        cmp #65                 ; the same case swap as conv
        bcc ddmst
        cmp #91
        bcc ddmup
        cmp #97
        bcc ddmst
        cmp #123
        bcs ddmst
        and #223
        bne ddmst
ddmup:  ora #128
ddmst:  sty DMW
        ldx DMI
        sta SBUF,x
        inc DMI
        ldy DMW
        iny
        jmp ddmn
ddmq:   ldx DMI
        lda #63                 ; '?' -- unknown sender, still delivered
        sta SBUF,x
        inc DMI
ddmsep: ldx DMI
        lda #58                 ; ':'
        sta SBUF,x
        inx
        lda #32
        sta SBUF,x
        inx
        stx DMI
; the text, from the CONVERTED copy
        ldy #16
ddmt:   cpy CLEN
        bcs ddmd
        lda CBUF,y
        sty DMW
        ldx DMI
        sta SBUF,x
        inc DMI
        ldy DMW
        iny
        jmp ddmt
; put it back at cbuf+11, where scrn and shomsg both expect the text
ddmd:   ldx #0
ddmc:   cpx DMI
        bcs ddmce
        lda SBUF,x
        sta CBUF+11,x
        inx
        jmp ddmc
ddmce:  txa
        clc
        adc #11
        sta CLEN
; Its own conversation, opened if this is the first we have heard from
; them, then shown or counted unread exactly like a channel message.
        jsr dmin
        sta TMP
        jsr arcmsg
        jmp dmroute

; Match the 6-byte key prefix against the contact table. CF clear and
; PTR -> the record when found. The key is binary, so it is compared
; against the RAW frame; CBUF has been through the character conversion
; and would not match.
dmwho:  lda #0
        sta DMW
dmwl:   lda DMW
        cmp NCONT
        bcs dmwno
        lda DMW
        jsr contptr
        ldx #0
dmwk:   txa
        clc
        adc #26                 ; the key sits at record offset 26
        tay
        lda (PTR),y
        cmp BUF+4,x
        bne dmwnx
        inx
        cpx #6
        bcc dmwk
        clc                     ; all six matched
        rts
dmwnx:  inc DMW
        jmp dmwl
dmwno:  sec
        rts

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
        lda CBUF,x
        jsr p2sc                ; screen codes: history hashes the same
        clc
        adc SMH
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
smnp:   jsr smsep               ; rule under it, prompt under that
        jsr shoprm
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
        lda #5                  ; white: not sent yet (green = verified)
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
        sta BKN
        tax
        beq bkrt
        jsr bkl
        lda BKN
        cmp #40
        bcc bkrt                ; one row: whatever comes is printed over it
        tax                     ; several rows: blank them first, or a
bkw:    lda #32                 ; shorter line leaves the tail behind
        jsr CHROUT
        dex
        bne bkw
        ldx BKN
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
        cpx #135            ; mesh: 160 with "name: "; wraps over rows
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
        lda K80                 ; 80 columns: the driver's own DEL
        beq kbd40
        lda K40
        bne kbd40
        lda #20
        jmp CHROUT
kbd40:
        lda #157                ; left (crosses rows), then blank the cell:
        jsr CHROUT              ; the KERNAL's DEL stops at an unlinked row
        ldy 211                 ; PNTR ($d3), column in the logical line
        lda #32
        sta (209),y             ; PNT ($d1): the line's screen address
        rts

kbret:  lda INLEN
        beq kbrt                ; nothing typed: no new prompt line
        jsr sendmsg
        lda INLEN
        sta PN_TL
        lda #0
        sta INLEN
        jsr shoprm
        jmp pnrec

kbf1:   jmp mainmnu
kbf3:   jmp kf3                 ; F3: 80 <-> 40 columns (Kawari)
kbf5:   jmp scrollb
kbf7:   jmp f7next

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
statvw: jmp stat4
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
namsg:  jmp dmopen              ; a conversation, not a one-off mode
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
        ldy #58
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
        cmp #4
        bcs narl3
        lda MNIDX
        clc
        adc #60
        tay
        lda (PTR),y
        jsr plhex
        lda #32
        jsr plchr
        inc MNIDX
        jmp narl2
narl3:  lda CTMP
        cmp #5
        bcc narl4
        lda #46
        jsr plchr
        lda #46
        jsr plchr
narl4:  jsr plend
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
        adc #26
        tay
        lda (PTR),y
        sta TXBUF+1,x
        inx
        jmp naw2
naw3:   ldy #58                 ; the C64's copy of the route too
        lda #255
        sta (PTR),y
        lda #1
        sta CDIRTY              ; saved with the table shortly
        lda $A1
        sta CDT
        lda #33
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
nalg2:  lda #0
        sta RQMODE
        jsr rqrun
        jsr rqshow
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
        adc #26
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
        lda #2
        sta RQMODE
        lda #0
        sta INPLEN              ; a blank password: a guest login
        jsr rqrun
        lda RQRES
        cmp #1
        bne ntbad
        lda #1
        sta RQMODE
        jsr rqrun
        lda RQRES
        cmp #1
        bne ntbad
        jsr lppdec
        jmp ntshow
ntbad:  jsr rqshow
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
        jsr mmsel2              ; 6 items, or 7 with "40/80 column mode"
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
        cmp #5                  ; "40/80 column mode", or "close"
        bne mmshut
        jmp mmcol
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
; **A #hashtag channel's key is sha256(name)[0:16], derived HERE.** The
; firmware does not derive it -- leaving the key blank used to send sixteen
; zeros, which makes a channel nobody else can read and that drops everyone
; else's messages. Name starting with '#' + empty key field -> hashch.
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

caadd:  jsr cafree
        lda INPOK
        bne caa2
        jmp cafull
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
caa4:   lda INPLEN
        bne caa5                ; a typed key is used as typed
        lda CHNAME
        cmp #35                 ; '#'
        bne caa5
        jsr hashch              ; SECBUF = sha256(CHNAME)[0:16], ~0.6 s
        jmp chsend
caa5:   jsr inphx
        jmp chsend

; removing is the same frame with an empty name and a zero key
carem:  jsr capick
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

; ----- where does a new channel go? -----
;
; This used to be a prompt: "slot number 0-39". Nobody can answer that.
; The picker lists POSITIONS, not slots, so the number being asked for is
; never shown anywhere in the interface -- and getting it wrong silently
; overwrites a channel that was already there. Adding a channel means
; adding it; finding room is our job, not the operator's.
cafree: lda SCNMAX
        bne caf1
; No scan yet, so run one. If it is aborted, SCNMAX stops the hunt at the
; last slot actually read: an unread slot looks empty, and taking it
; would silently overwrite a channel we never saw.
        jsr chscan
caf1:   lda #0
        sta SCANI
caf2:   lda SCANI
        cmp SCNMAX
        bcs cafno
        lda SCANI
        jsr chnptr
        ldy #0
        lda (PTR),y
        beq caffd               ; empty name = free slot
        inc SCANI
        jmp caf2
caffd:  lda SCANI
        sta CHIDX
        lda #1
        sta INPOK
        rts
cafno:  lda #0
        sta INPOK
        rts

; ----- pick an EXISTING channel, by name -----
;
; Same reasoning as above, in reverse: to remove a channel you have to be
; able to say WHICH, and a slot number is not something the UI ever shows.
; Slot 0 is deliberately left out -- that is Public, and wiping it is
; never what anyone means.
capick: lda SCNMAX
        bne cap1
        jsr chscan
cap1:   jsr plinit
        lda #1                  ; skip Public
        sta SCANI
        lda #0
        sta NPICK
cap2:   lda SCANI
        cmp #40
        bcs cap4
        lda NPICK
        cmp #8                  ; PLBUF holds eight rows
        bcs cap4
        lda SCANI
        jsr chnptr
        ldy #0
        lda (PTR),y
        beq cap3                ; empty slot, nothing to remove
; the name address must be taken BEFORE plnew, which claims PTR
        lda PTR
        sta SPL
        lda PTRH
        sta SPH
        ldx NPICK
        lda SCANI
        sta PKMAP,x
        inc NPICK
        jsr plnew
        ldy #0
cap5:   cpy #16
        bcs cap6
        sty CTMP
        lda (SPL),y
        beq cap6
        jsr p2a                 ; CHNAM is PETSCII; the menu wants ASCII
        jsr plchr
        ldy CTMP
        iny
        jmp cap5
cap6:   jsr plend
cap3:   inc SCANI
        jmp cap2
cap4:   lda NPICK
        bne cap7
        lda #0
        sta INPOK               ; nothing there to remove
        rts
cap7:   lda #12
        sta MNX
        lda #8
        sta MNY
        lda #22
        sta MNW
        lda NPICK
        sta MNN
        lda #<PLTAB
        sta MNPTR
        lda #>PLTAB
        sta MNPTRH
        lda #<tcrem
        sta MNTIT
        lda #>tcrem
        sta MNTITH
        lda #0
        sta MNSEL
        jsr menu
        lda MNSEL
        cmp #255                ; f1 backed out
        beq capno
        ldx MNSEL
        lda PKMAP,x
        sta CHIDX
        lda #1
        sta INPOK
        rts
capno:  lda #0
        sta INPOK
        rts

; Every slot taken. Say so rather than silently doing nothing.
cafull: jsr plinit
        jsr plnew
        lda #<tcfull
        sta SPL
        lda #>tcfull
        sta SPH
        jsr plstr
        jsr plend
        lda #<tchan
        sta MNTIT
        lda #>tchan
        sta MNTITH
        jsr plshow
        jmp mmshut

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
; **Re-read ONLY the slot we just changed.**
;
; This used to force a full 40-slot sweep. At 600 baud that is forty
; round trips -- the better part of a minute with a frozen screen, no
; progress shown, and keys ignored because no key loop is running. It
; looks exactly like a hang, because functionally it is one. And any slot
; the radio does not answer adds a thirty second timeout on top.
;
; One slot is all that changed, so read back one slot.
        lda #31                 ; CMD_GET_CHANNEL
        sta TXBUF
        lda CHIDX
        sta TXBUF+1
        lda #2
        sta TXLEN
        jsr sendfr
        lda #0
        sta STGBIT
        lda #18                 ; RESP_CODE_CHANNEL_INFO
        jsr waitop
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
        jsr tsput               ; **not zero** -- see tsput
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
        lda #1
        sta PN_SK
        jsr arcown
smsrt:  rts
; ----- direct message -----
; [2][txt_type][attempt][timestamp:4][key prefix:6][text]
sendm2: lda #2
        sta TXBUF
        lda #0
        sta TXBUF+1             ; plain
        sta TXBUF+2             ; first attempt
        jsr tsput               ; **not zero** -- see tsput
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
        lda #2
        sta PN_SK
        rts

; "All" is a read-only monitor: there is no single channel to send to, and
; quietly defaulting to Public would post to the wrong place.
smsall: lda #<msgpick
        sta PTR
        lda #>msgpick
        sta PTRH
        jsr prtstr
        rts

; **Deferred while a scan or node fetch owns the link.** Every queued
; message would otherwise interleave with the replies being waited for and
; print over the status line. The radio holds them in its offline queue,
; so nothing is lost by asking later -- SYNCP remembers that we owe it.
sync:   lda SCBUSY
        beq sync2
        sta SYNCP
        rts
sync2:  lda #10
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
        jsr tsput               ; before X is set up; tsput uses it
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
        lda UKH                 ; 9 regions + persist area must fit
        cmp #2
        bcs rd512               ; 512K and up: 9 x 32K
        cmp #1
        beq rd256               ; 256K: 9 x 16K
        lda #7                  ; 128K: 9 x 8K
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
        lda #<NOREU_LINES       ; lines of 40 bytes from $4000 up to segment 3
        sta MAXL
        lda #>NOREU_LINES
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
        lda #60                 ; tail of slot 0: lines use 40 of 64 bytes
        sta RREUL
        lda #0
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
        cmp #2
        bne rxnotg
        jmp geowr
rxnotg: lda RU
        bne rxreu
        jsr ramaddr             ; no REU: a plain copy into main RAM
        jsr ramwr
        rts
rxreu:  jsr reuaddr
        lda CNT
        sta DLEN
        lda #144                ; c64 -> reu, in short pieces
        sta DCMD
        jmp reuchunk

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
        cpy #240                ; six lines: a full-length message fits
        bcc snl
        lda #6
        sta SLEN
        rts
; lines = Y/40 rounded up, at least one; blank the rest of the buffer
spad:   tya
        ldx #0
spdv:   inx
        sec
        sbc #40
        beq spdn
        bcs spdv
spdn:   stx SLEN
        lda #32
spfl:   cpy #240
        bcs spfd
        sta SBUF,y
        iny
        jmp spfl
spfd:   rts

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
lrn:    cmp #40
        bcs lrdm
        cmp #6
        bcc lrok
        lda #6
        bne lrok
lrdm:   lda #7                  ; direct messages
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
        asl                     ; line index * 40 (was *10)
        asl
        asl
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
        jsr reuxfer             ; does the transfer itself now
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
lpdone: jmp gsvh                ; GeoRAM: pointers + unread survive

; ===== archive one received message ====================================
; Twice: plain into its own channel's region, and prefixed into "All" so
; that scrolling the merged feed still says where each line came from.
arcmsg:
; Callers pass the channel in TMP, but lput and chnptr below both use TMP
; as scratch. Take a private copy before either runs.
        lda TMP
        sta MCH
        lda RU
        beq amall               ; no REU: the merged region only
        lda MCH                 ; the channel it arrived on
        jsr lreg
        jsr lsep                ; rule above it
        lda #11
        sta SOFF
        jsr scrnm
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
        lda MCH
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
        lda MCH
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
amcd:   lda #8
        sta REGION
        jsr lsep
        jsr scrnm
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
        lda RU
        beq aoall               ; no REU: lreg would return region 8 here
        lda CC                  ; too, and the line would be stored twice
        jsr lreg
        jsr lsep
        jsr scrnm
        jsr lput
aoall:  lda #8
        sta REGION
        jsr lsep
        jsr scrnm
        jsr lput
aort:   rts

; ===== paint a page from the archive ===================================
; 24 lines, NOT 25: the bottom row belongs to the prompt. Painting all 25
; put the newest message where the prompt then overwrote it.
arcpage:
        jsr k80c                ; Kawari 80: back from a menu
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
        sta SDH
        jsr appage
aprt:   rts

; paint 24 lines ending at slot ZY
appage: jsr k80c
        jsr sdcalc            ; how far the view is behind the newest
        ldx REGION            ; lines that exist from here back: fill - SD
        lda LFL,x
        sec
        sbc SD
        sta NLINE
        lda LFH,x
        sbc SDH
        bne ap24
        lda NLINE
        cmp APMAX
        bcs ap24
        lda APMAX
        cmp #24
        bne apgo                ; boot: the rows under the boot text only
        lda #147                ; short page: clear first so nothing older
        jsr CHROUT              ; is left on screen behind it
        jmp apgo
ap24:   lda APMAX
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
        ora SLOTH
        bne apb1
        lda MAXL                ; slot 0 steps back to MAX-1
        sta SLOTL
        lda MAXH
        sta SLOTH
apb1:   lda SLOTL
        bne apb2
        dec SLOTH
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
        jsr k80typ              ; first row / continuation / rule (80 cols)
        jsr apcol               ; sender colour, text green, rules grey
        inc CNT
        jsr apnext
        jmp apfl
aprt2:  jmp k80flow              ; 80 columns: lay the page out
APMAX:  .byte 24                ; page height; lower only at boot

apxfer: lda RU
        cmp #2
        bne apnotg
        jmp georr
apnotg: lda RU
        bne axreu
        jsr ramaddr
        jsr ramrd
        rts
axreu:  jsr reuaddr
        lda CNT2
        sta DLEN
        lda #145                ; reu -> c64, in short pieces
        sta DCMD
        jmp reuchunk

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
        sta SDH
        jsr zynew               ; the view starts at the newest line
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
sbold:  lda CC              ; a message archived meanwhile left
        jsr lreg            ; REGION on the merged feed: recompute
        jsr sdcalc          ; and the newest line has moved on
        lda SD
        clc
        adc #24
        sta TMP
        lda SDH
        adc #0
        sta TMP2
; only while SD+24 < fill: a page that would start at or past the oldest
; line we hold would be painted from slots that were never written
        ldx REGION
        lda TMP2
        cmp LFH,x
        bcc sbok
        bne sbstop
        lda TMP
        cmp LFL,x
        bcc sbok
sbstop: jmp sbkey
sbok:   lda TMP2
        sta SDH
        lda TMP
        sta SD
        ldx #24
sbol:   jsr sbdec
        dex
        bne sbol
        jsr appage
        jmp sbkey
sbnew:  lda CC              ; a message archived meanwhile left
        jsr lreg            ; REGION on the merged feed: recompute
        jsr sdcalc
        lda SD
        ora SDH
        beq sbstop
        lda SDH
        bne sbn24
        lda SD
        cmp #24
        bcs sbn24
        jsr zynew           ; under a page from the newest: go there
        jmp sbnp
sbn24:  ldx #24
sbnl:   jsr sbinc
        dex
        bne sbnl
sbnp:   jsr appage
        jmp sbkey
sbexit: lda #0
        sta UIMODE
        sta SD
        sta SDH
        jsr arcpage
        lda OLDB
        sta BORDER
        ldx #23
        ldy #0
        clc
        jsr kplot
        jsr shoprm
sbrt:   rts

; SD = (LW - 1 - ZY) mod MAX: lines between the view and the newest
sdcalc: ldx REGION
        lda LWL,x
        sec
        sbc #1
        sta SD
        lda LWH,x
        sbc #0
        sta SDH
        lda SD
        sec
        sbc ZYL
        sta SD
        lda SDH
        sbc ZYH
        sta SDH
        bpl sdcr
        lda SD
        clc
        adc MAXL
        sta SD
        lda SDH
        adc MAXH
        sta SDH
sdcr:   rts
; ZY = the newest line (LW - 1, wrapping)
zynew:  ldx REGION
        lda LWL,x
        sta ZYL
        lda LWH,x
        sta ZYH
        jmp sbdec
sbdec:  lda ZYL
        ora ZYH
        bne sbd1
        lda MAXL                ; 0 steps back to MAX-1
        sta ZYL
        lda MAXH
        sta ZYH
sbd1:   lda ZYL
        bne sbd2
        dec ZYH
sbd2:   dec ZYL
        rts
sbinc:  inc ZYL
        bne sbi1
        inc ZYH
sbi1:   lda ZYH                 ; MAX wraps to 0
        cmp MAXH
        bcc sbi2
        bne sbiw
        lda ZYL
        cmp MAXL
        bcc sbi2
sbiw:   lda #0
        sta ZYL
        sta ZYH
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
        lda #5                  ; white, as shoprm: not sent yet
        jsr CHROUT
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
; **No scan here.** Boot scans once; after that the list is shown from
; memory and r rescans. Scanning whenever the list was not marked complete
; meant an aborted or timed-out boot scan made EVERY visit a 40-second wait.

; Map the list positions onto whatever slots actually have names, so a
; sparse radio still gets a dense list. "All" is synthetic and always 0.
pkshow: lda #255
        sta PKMAP
        lda #1
        sta NPICK
        lda #0
        sta SCANI
pkbl:   lda SCANI
        cmp #48                 ; 40-47 are DM conversations
        bcs pkbd
        lda NPICK
        cmp #10
        bcs pkbd
        lda SCANI
        jsr slotok
        bcc pkbn
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
        jsr dmsel               ; a DM conversation types to its contact
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
screp:  jsr gsvh                ; unread counts just changed
        jsr arcpage
        jmp scprm
; No archive to paint from, so at least say where we are -- the picker
; cleared the screen on its way out and a bare prompt looks like the
; channel lost its history.
scprm:  ldx #23                 ; cursor to row 23: shoprm's RETURN then
        ldy #0                  ; puts the prompt on the bottom row, under
        clc                     ; the history, where the chat expects it
        jsr kplot               ; $fff0 PLOT (and the 80 column cursor)
        jsr setprm
        jsr shoprm
        rts

; ===== non-REU replay ring =============================================
; With no REU there is no archive, so keep the last 24 messages in RAM and
; replay the ones for a channel when you switch to it. Only the UNREAD
; ones: anything you were already watching has been on screen once.

; PTR -> ring slot Y (40 bytes each: x32 + x8)

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
geook:  .byte 1             ; 0 = never probe GeoRAM (cartridge build)
testk:  .byte 0             ; nonzero = run the scripted keypresses
pyastart: .byte 1,0,0,0,0,0,0,0,67,54,52
pyquery:  .byte 22,3
pychan:   .byte 31,0
pytime:   .byte 5
banner: .text "meshcore 64  v2.0.1"
        .byte 13,0
svideo: .text "video    "
        .byte 0
sradio: .text "radio    "
        .byte 0
sfwv:   .text "firmware "
        .byte 0
msgcon: .text "connecting..."
        .byte 13,0
msgrdy: .text "connected."
        .byte 13,13,0
msgpick: .text "pick a channel to send"
        .byte 13,0
mtitle: .text " MeshCore 64 "
        .byte 0
mi0:    .text "Channels"
        .byte 0
mi1:    .text "Nodes"
        .byte 0
mi2:    .text "Stats"
        .byte 0
mi3:    .text "Radio actions"
        .byte 0
mi4:    .text "Add/remove channel"
        .byte 0
mi5:    .text "Close"
        .byte 0
mtab:   .word mi0,mi1,mi2,mi3,mi4,mi5
; one colour per entry: red, yellow, cyan, purple, light green, light blue
mnclrs: .byte 2,7,3,4,13,14,2,7,3,4,13,14,2,7,3,4
; sender colours, chosen by name hash. No green -- that is the message --
; and nothing dark enough to vanish on black.
smpal:  .byte 5,158,159,156,129,154,150,155
smcr:   .byte 1,7,3,4,8,14,10,15    ; the same, as colour-RAM values
tchans: .text " Channels "
        .byte 0
sall:   .text "All"
        .byte 0
pkhint: .text "0-9 pick  RETURN  R rescan  F1 back"
        .byte 0
ca0:    .text "Add or edit channel"
        .byte 0
ca1:    .text "Remove channel"
        .byte 0
ca2:    .text "Back"
        .byte 0
catab:  .word ca0,ca1,ca2
tchan:  .text " Channel "
        .byte 0
tcrem:  .text " Remove which channel "
        .byte 0
tcfull: .text "No free channel slots"
        .byte 0
tcname: .text " Channel name "
        .byte 0
tsec:   .text " Key: hex, or blank for none "
        .byte 0
tchset: .text "Channel updated"
        .byte 0
tnodes: .text " Nodes "
        .byte 0
tnode1: .text " Node "
        .byte 0
na0:    .text "Send message"
        .byte 0
na1:    .text "Log in..."
        .byte 0
na4:    .text "Telemetry"
        .byte 0
na5:    .text "Show route"
        .byte 0
na2:    .text "Wipe route (flood)"
        .byte 0
na3:    .text "Back"
        .byte 0
natab:  .word na0,na1,na4,na5,na2,na3
tpass:  .text " Password "
        .byte 0
ttelem: .text " Telemetry "
        .byte 0
tlogok: .text "login accepted"
        .byte 13,0
tnotel: .text "No reply - log in to it first"
        .byte 0
; every LPP label is addressed by its low byte alone, so they must all
; sit in one page -- the assembler would not warn if they did not
svolt:  .text "Voltage "
        .byte 0
scur:   .text "Current "
        .byte 0
stemp:  .text "Temp "
        .byte 0
sbaro:  .text "Pressure "
        .byte 0
sana:   .text "Analog "
        .byte 0
slux:   .text "Light "
        .byte 0
shum:   .text "Humidity "
        .byte 0
sdig:   .text "Digital "
        .byte 0
sv:     .text " V"
        .byte 0
sa:     .text " A"
        .byte 0
sc:     .text " C"
        .byte 0
shpa:   .text " hPa"
        .byte 0
spct:   .text " %"
        .byte 0
slpptyp: .text "Type "
        .byte 0
troute: .text "Route: "
        .byte 0
tflood: .text "None - will flood"
        .byte 0
tstats: .text " Stats "
        .byte 0
tradio: .text " Radio actions "
        .byte 0
skb:    .text " kb"
        .byte 0
spal:   .text "pal"
        .byte 0
sntsc:  .text "ntsc"
        .byte 0
srfreq: .text "Freq  "
        .byte 0
srbw:   .text "BW    "
        .byte 0
srsf:   .text "SF    "
        .byte 0
srcr:   .text "CR    "
        .byte 0
srpwr:  .text "Power "
        .byte 0
srname: .text "Node name..."
        .byte 0
tname:  .text " Node name "
        .byte 0
srapply: .text "Apply to node"
        .byte 0
srsent: .text "Radio settings sent"
        .byte 0
skhz:   .text " kHz"
        .byte 0
shz:    .text " Hz"
        .byte 0
sdbm:   .text " dBm"
        .byte 0
sreu:   .text "reu detected  "
        .byte 0
twiped: .text "Route wiped - next msg floods"
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

SRC2 = r"""
; =======================================================================
; SEGMENT 2 -- assembled at $a000 and copied there by main, in the RAM
; under BASIC ROM. Vectors first: RUN/STOP+RESTORE jumps through ($a002),
; and with BASIC banked out that is read from here.
; =======================================================================
        .word s1warm,s1warm
; ===== segment 2 setup =================================================
; With an REU the archive lives there and the 16K at $4000 (the splash's
; bitmap, then the RAM archive) is idle -- room for 255 contacts. Without
; one, the table keeps its own 6K at $8000: 96 contacts.
s2init: lda RU
        beq s2i1
        lda #64                 ; $4000
        sta CBASEH
        lda #160                ; to $6800, where segment 4 starts
        sta MAXCON
        rts
s2i1:   lda #128                ; $8000
        sta CBASEH
        lda #96
        sta MAXCON
        rts

; ===== small printing helpers ==========================================
; Each counts the columns it prints in SCOL, so s2pad can blank the rest
; of a line that is being rewritten in place.

; the null-terminated PETSCII string at SPL
s2str:  ldy #0
s2s1:   lda (SPL),y
        beq s2s2
        jsr CHROUT
        inc SCOL
        iny
        bne s2s1
s2s2:   rts

; The same for an ASCII string -- contact names are kept in ASCII because
; the menus draw them through a2s. CHROUT wants PETSCII, where the two
; letter cases are the other way round.
s2asc:  ldy #0
s2a1:   lda SCOL                ; stop at the screen edge: never wrap
        cmp KSEPW
        bcs s2a4
        lda (SPL),y
        beq s2a4
        cmp #65
        bcc s2a3
        cmp #91
        bcs s2a2
        ora #32                 ; A-Z -> 97..122, which shows as capitals
        bne s2a3
s2a2:   cmp #97
        bcc s2a3
        cmp #123
        bcs s2a3
        and #223                ; a-z -> 65..90, which shows as lower case
s2a3:   jsr CHROUT
        inc SCOL
        iny
        cpy #25
        bcc s2a1
s2a4:   rts

; A as decimal, no leading zeros
s2dec:  jsr dec8
        sta S2T
        lda #3
        sec
        sbc S2T
        tay
s2d1:   lda DECBUF,y
        jsr CHROUT
        inc SCOL
        iny
        cpy #3
        bcc s2d1
        rts

; Start rewriting the status line: up one row, back to column 0. The line
; itself always ends with a RETURN, so the cursor sits just below it and
; this lands exactly on it -- even after the screen has scrolled.
s2up:   lda #145
        jsr CHROUT
        lda #0
        sta SCOL
        rts

; blank out to column 39 and end the line
s2pad:  lda SCOL
        cmp KSEPW               ; to the screen edge (39 or 79)
        bcs s2pd
        lda #32
        jsr CHROUT
        inc SCOL
        jmp s2pad
s2pd:   lda #13
        jmp CHROUT

; ===== wait for a reply, with an idle timeout ==========================
; WANT2 = the opcode wanted (255 = any frame at all); an error frame
; (opcode 1) also ends the wait. Anything else is dispatched as usual.
; S2TMO = jiffies of SILENCE allowed; the clock restarts on every frame.
; Returns carry clear and the opcode in A with READY still set -- the
; caller handles the frame and clears READY -- or carry set on timeout.
s2wait: lda JIFFY
        sta WJ2
s2w1:   jsr poll
        lda READY
        bne s2w3
; S2KEY set: a keypress ends the wait too -- carry set, key in S2HIT. A
; timeout also returns carry set, with S2HIT left at 0.
        lda S2KEY
        beq s2w2
        jsr GETIN
        cmp #0
        beq s2w2
        sta S2HIT
        sec
        rts
s2w2:   lda JIFFY
        sec
        sbc WJ2
        cmp S2TMO
        bcc s2w1
        rts
s2w3:   lda WANT2
        cmp #255
        beq s2w4
        lda BUF
        cmp WANT2
        beq s2w4
        cmp #1
        beq s2w4
        jsr dispat
        lda #0
        sta READY
        jmp s2wait
s2w4:   lda BUF
        clc
        rts

; ===== scan the radio's channel list ===================================
; Every slot, every time: the old quick scan stopped after three blank
; slots and missed a channel sitting above a gap (a real setup had them
; at 0, 1 and 5).
;
; It is slow because the link is. An EMPTY slot still comes back as a full
; 53-byte frame -- the name field is fixed-width -- and at 600 baud that is
; most of a second per slot, so forty slots is roughly 35-40 seconds. Hence
; the running status line, and any key aborts.
;
; SCMODE = 1 at boot: bootscan has already printed the header and the
; screen is not ours to clear. Otherwise this is a refresh from the picker
; or the channel editor and it takes the screen over.
chscan: lda #1
        sta SCBUSY
        lda #0
        sta SCANI
        sta NFOUND
        sta SCABT
        sta CSTMO
        lda #255
        sta LASTF
        lda SCMODE
        bne csh2
        lda #147
        jsr CHROUT
        lda #<s2refr
        sta SPL
        lda #>s2refr
        sta SPH
        jsr prtsp
csh2:   lda #13                 ; the row the status line rewrites
        jsr CHROUT
cslp:   jsr csline
        lda SCANI
        cmp #40
        bcs csdone
        jsr GETIN
        cmp #0
        beq csgo
        inc SCABT
        jmp csdone
; forget the old name first: a channel deleted from a phone since the last
; scan comes back with an empty name, and that has to clear it here too
csgo:   lda SCANI
        jsr chnptr
        lda #0
        tay
        sta (PTR),y
        lda #31                 ; CMD_GET_CHANNEL
        sta TXBUF
        lda SCANI
        sta TXBUF+1
        lda #2
        sta TXLEN
        jsr sendfr
        lda #18                 ; RESP_CODE_CHANNEL_INFO
        sta WANT2
        lda #200                ; ~3.3s of silence
        sta S2TMO
        jsr s2wait
        bcs cstmo
        cmp #18
        bne cserr
        jsr dispat              ; rxchan files the name
        lda #0
        sta READY
        sta CSTMO
        lda SCANI
        jsr chnptr
        ldy #0
        lda (PTR),y
        beq csnx
        inc NFOUND
        lda SCANI
        sta LASTF
csnx:   inc SCANI
        jmp cslp
; An error means the slot does not exist: the radio has fewer than forty
; and we are past the last one. That is a complete scan, not a failure.
cserr:  lda #0
        sta READY
        jmp csdone
; One silent slot is skipped. Two in a row means the radio is not
; answering at all, and forty more 3-second waits would look like a hang.
cstmo:  inc SCANI
        inc CSTMO
        lda CSTMO
        cmp #2
        bcc cslp
        inc SCABT
csdone: lda SCANI
        sta SCNMAX              ; how far add-channel may trust the list
        lda SCABT
        bne csd2
        lda #1
        sta CKED
csd2:   jsr gsvc                ; channel list -> GeoRAM
        jsr csfin
        lda #0
        sta SCBUSY
        lda SCMODE
        bne csd3                ; boot: the handshake syncs straight after
        lda SYNCP
        beq csd3
        jsr sync
csd3:   lda #0
        sta SYNCP
        sta SCMODE
        rts

; "slot 12/40  found 3: #test"
csline: jsr s2up
        lda #<s2slot
        sta SPL
        lda #>s2slot
        sta SPH
        jsr s2str
        lda SCANI
        jsr s2dec
        lda #<s2of40
        sta SPL
        lda #>s2of40
        sta SPH
        jsr s2str
        lda NFOUND
        jsr s2dec
        lda LASTF
        cmp #255
        beq csl2
        lda #<s2colon
        sta SPL
        lda #>s2colon
        sta SPH
        jsr s2str
        lda LASTF
        jsr chnptr
        lda PTR
        sta SPL
        lda PTRH
        sta SPH
        jsr s2str               ; channel names are kept in petscii
csl2:   jmp s2pad

; "channels found: 3" -- and say so if it was cut short
csfin:  jsr s2up
        lda #<s2cfnd
        sta SPL
        lda #>s2cfnd
        sta SPH
        jsr s2str
        lda NFOUND
        jsr s2dec
        lda SCABT
        beq csf2
        lda #<s2abt
        sta SPL
        lda #>s2abt
        sta SPH
        jsr s2str
csf2:   jmp s2pad

; ===== scan at boot, unless a key says not to ==========================
; Two seconds to opt out, then the full scan. Message sync is held off
; until it is done (see sync), so nothing prints over the status line.
bootscan:
        lda #1
        sta UIMODE
        sta SCBUSY
        sta SCMODE
        lda #0
        sta 198                 ; ndx: drop keys pressed during the splash
        lda #<s2boot
        sta SPL
        lda #>s2boot
        sta SPH
        jsr prtsp
        lda #120
        sta S2T
        lda JIFFY
        sta WJ2
bsw:    jsr poll
        lda READY
        beq bsw2
        jsr dispat
        lda #0
        sta READY
bsw2:   jsr GETIN
        cmp #0
        bne bsab
        lda JIFFY
        cmp WJ2
        beq bsw
        sta WJ2
        dec S2T
        bne bsw
        jsr chscan
        jmp bsdn
bsab:   lda #<s2skip
        sta SPL
        lda #>s2skip
        sta SPH
        jsr prtsp
bsdn:   lda #0
        sta UIMODE
        sta SCBUSY
        sta SCMODE
        sta SYNCP               ; handshk syncs next regardless
        rts

; ===== node list =======================================================
; Which kind first. The radio has no type filter -- CMD_GET_CONTACTS only
; takes 'since' -- so every contact still crosses the link, ~148 bytes and
; about 2.5 seconds each at 600 baud. What the choice buys is the TABLE:
; only this type is kept, so hundreds of nodes do not have to fit in RAM
; and the list is not a scroll through every repeater to find a person.
;
; Each type is cached once fetched (TLOAD), and reopening it is instant.
; R in the list fetches it again.
nodelst:
        lda #1
        sta UIMODE
        lda #147                ; a submenu replaces the parent
        jsr CHROUT
        lda #10
        sta MNX
        lda #7
        sta MNY
        lda #20
        sta MNW
        lda #4
        sta MNN
        lda #<nttab
        sta MNPTR
        lda #>nttab
        sta MNPTRH
        lda #<tnodes
        sta MNTIT
        lda #>tnodes
        sta MNTITH
        lda #0
        sta MNSEL
        jsr menu
        lda MNSEL
        cmp #255
        bne ntsel
        jmp mmshut
; menu() clears UIMODE on its way out. Put it back, or every message that
; arrives while the list is up prints straight over it.
ntsel:  ldx #1
        stx UIMODE
        clc
        adc #1                  ; ADV_TYPE_CHAT=1 REPEATER=2 ROOM=3 SENSOR=4
        sta NTYPE
        tax
        lda TLOAD,x
        beq ndfetch
        lda #0
        sta NTRUNC
        jmp ndview

; ----- fetch one type from the radio -----
ndfetch:
        jsr k80c                ; 80 columns: progress on the full screen
        lda #1
        sta SCBUSY
        sta UIMODE
        lda #147
        jsr CHROUT
        lda #<s2load
        sta SPL
        lda #>s2load
        sta SPH
        jsr prtsp
        jsr ntname
        lda #<s2ldh
        sta SPL
        lda #>s2ldh
        sta SPH
        jsr prtsp
        jsr ndpurge             ; drop this type's stale entries
        lda #0
        sta NRECV
        sta NSEEN
        sta NSEENH
        sta NTRUNC
        sta NTMO
        lda #4                  ; CMD_GET_CONTACTS, no 'since': all of them
        sta TXBUF
        lda #1
        sta TXLEN
        jsr sendfr
        jsr ndline
        lda #1
        sta S2KEY               ; any key stops the fetch
ndfl:   lda #0
        sta S2HIT
        lda #255                ; any frame; ~4.3s of silence per try
        sta WANT2
        sta S2TMO
        jsr s2wait
        bcc ndfg
        lda S2HIT
        bne ndfab
; The radio can sit on a frame while it is transmitting. Three silences
; in a row (~13s) and we keep what arrived.
        inc NTMO
        lda NTMO
        cmp #3
        bcc ndfl
        lda #1
        sta NTRUNC
        jmp ndfend
ndfg:   ldx #0
        stx NTMO
        cmp #2
        beq ndfst
        cmp #3
        beq ndfc
        cmp #4
        beq ndfeok
        cmp #1
        beq ndferr
        jsr dispat
ndfnx:  lda #0
        sta READY
        jmp ndfl
; RESP_CODE_CONTACTS_START carries the radio's TOTAL, all types. If that
; many could not sit alongside what is cached, drop the cache now so this
; type gets the whole table.
ndfst:  lda BUF+2
        ora BUF+3
        ora BUF+4
        bne ndfclr
        lda BUF+1
        clc
        adc NCONT
        bcs ndfclr
        cmp MAXCON
        bcc ndfnx
        beq ndfnx
ndfclr: lda #0
        sta NCONT
        ldx #4
ndfcl2: sta TLOAD,x
        dex
        bpl ndfcl2
        jmp ndfnx
ndfc:   inc NSEEN
        bne ndfc1
        inc NSEENH              ; a radio can hold 350
ndfc1:  lda BUF+33
        cmp NTYPE
        bne ndfsk               ; another type: not kept
        lda NCONT
        cmp MAXCON
        bcc ndfc2
        lda #1                  ; no room: count it, but this list is not
        sta NTRUNC              ; complete and must not be kept
        bne ndfc3
ndfc2:  jsr rxcont
ndfc3:  inc NRECV
ndfsk:  jsr ndline              ; every frame, so a run of other types
        jmp ndfnx               ; still visibly moves the count
; Stopped by a key. The radio has no way to cancel its iterator, so the
; rest still arrives -- and rxcont, called from dispat, keeps adding this
; type's entries in the background. Opening the list again shows them.
ndfab:  lda #1
        sta NTRUNC
        jmp ndfend
ndferr: lda #1                  ; e.g. ERR_CODE_BAD_STATE: the radio's
        sta NTRUNC              ; iterator was already busy
ndfeok: lda #0
        sta READY
ndfend: jsr gsvk                ; node list -> GeoRAM
        lda #0
        sta SCBUSY
        sta S2KEY
        lda SYNCP
        beq ndfe2
        lda #0
        sta SYNCP
        jsr sync
; **Kept even when incomplete.** It used to be thrown away, so a list that
; stalled, overflowed or was stopped was fetched again -- for minutes -- on
; every visit. Now it stays until r.
ndfe2:  ldx NTYPE
        lda #1
        sta TLOAD,x
        jmp ndview

; "checked 40  kept 12: alice"
ndline: jsr s2up
        lda #<s2chk
        sta SPL
        lda #>s2chk
        sta SPH
        jsr s2str
        lda NSEEN               ; 16-bit, so through prdec
        sta NUML
        lda NSEENH
        sta NUMH
        jsr prdec
        lda DECN                ; digits printed; 0 means it printed "0"
        bne ndl1
        lda #1
ndl1:   clc
        adc SCOL
        sta SCOL
        lda #<s2kept
        sta SPL
        lda #>s2kept
        sta SPH
        jsr s2str
        lda NRECV
        jsr s2dec
        lda NRECV
        beq ndl2
        lda NTRUNC
        bne ndl2                ; the last one was not stored
        lda #<s2colon
        sta SPL
        lda #>s2colon
        sta SPH
        jsr s2str
        ldx NCONT
        dex
        txa
        jsr contptr             ; names are first in the slot
        lda PTR
        sta SPL
        lda PTRH
        sta SPH
        jsr s2asc
ndl2:   jmp s2pad

; print the plural name of type NTYPE
ntname: ldx NTYPE
        dex
        txa
        asl
        tax
        lda nttab,x
        sta SPL
        lda nttab+1,x
        sta SPH
        jmp prtsp

; ----- remove every entry of type NTYPE, closing the gaps -----
ndpurge:
        lda #0
        sta NIDX
        sta NDST
npl:    lda NIDX
        cmp NCONT
        bcs npd
        jsr contptr
        ldy #59
        lda (PTR),y
        cmp NTYPE
        beq npnx                ; this type: drop it
        lda NIDX
        cmp NDST
        beq npkeep              ; already where it belongs
        lda PTR
        pha
        lda PTRH
        pha
        lda NDST
        jsr contptr
        lda PTR
        sta PTR2
        lda PTRH
        sta PTR2H
        pla
        sta PTRH
        pla
        sta PTR
        ldy #63
npc:    lda (PTR),y
        sta (PTR2),y
        dey
        bpl npc
npkeep: inc NDST
npnx:   inc NIDX
        jmp npl
npd:    lda NDST
        sta NCONT
        rts

; ----- show the cached entries of type NTYPE -----
; NODETAB is what the menu draws (name pointers); NODEIX maps a row back
; to its contact slot, which is what nodeact works with.
ndview: lda #0
        sta NVIS
        sta NIDX
        sta NTOT
        lda #<NODETAB
        sta PTR2
        lda #>NODETAB
        sta PTR2H
ndvl:   lda NIDX
        cmp NCONT
        bcs ndvd
        jsr contptr
        ldy #59
        lda (PTR),y
        cmp NTYPE
        bne ndvn
        jsr nfmatch             ; counts it; carry set = filtered out
        bcs ndvn
        ldx NVIS
        lda NIDX
        sta NODEIX,x
        ldy #0
        lda PTR
        sta (PTR2),y
        iny
        lda PTRH
        sta (PTR2),y
        lda PTR2
        clc
        adc #2
        sta PTR2
        bcc ndv2
        inc PTR2H
ndv2:   inc NVIS
ndvn:   inc NIDX
        jmp ndvl
ndvd:   lda NVIS
        bne ndvd2
        jmp nfempty             ; (with a filter: show everything instead)
ndnone:
; nothing of this type: say so rather than flash an empty frame
        jsr plinit
        jsr plnew
        lda #<s2none
        sta SPL
        lda #>s2none
        sta SPH
        jsr plstr
        jsr plend
        lda #<tnodes
        sta MNTIT
        lda #>tnodes
        sta MNTITH
        jsr plshow
        jmp mmshut
ndvd2:  lda NTRUNC
        beq ndshow
; too many to hold, or the transfer stalled: show what we have, but it is
; not cached -- next time it is fetched again
        jsr plinit
        jsr plnew
        lda #<s2trn1
        sta SPL
        lda #>s2trn1
        sta SPH
        jsr plstr
        jsr plend
        jsr plnew
        lda #<s2trn2
        sta SPL
        lda #>s2trn2
        sta SPH
        jsr plstr
        jsr plend
        lda #<tnodes
        sta MNTIT
        lda #>tnodes
        sta MNTITH
        jsr plshow

; The list scrolls, twelve rows at a time.
ndshow: lda #0
        sta NDOFF
        sta MNSEL
ndpage: lda #4
        sta MNX
        lda #4
        sta MNY
        lda #30
        sta MNW
        lda NVIS
        sec
        sbc NDOFF
        cmp #12
        bcc ndn2
        lda #12
ndn2:   sta MNN
; MNPTR = NODETAB + NDOFF*2, 16-bit now that there can be 255
        lda NDOFF
        asl
        sta MNPTR
        lda #0
        rol
        sta MNPTRH
        lda MNPTR
        clc
        adc #<NODETAB
        sta MNPTR
        lda MNPTRH
        adc #>NODETAB
        sta MNPTRH
        jsr ndtit
        lda #147
        jsr CHROUT
        jsr mnbox
        jsr mnitems
        lda MNY                 ; the hint goes under the frame
        clc
        adc MNN
        adc #3
        sta MNROW
        jsr scrpos
        lda #12
        sta MNCLR
        jsr nfhint
        lda #1
        sta MNCOL
        jsr mnstr
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
        cmp #47                 ; / : find
        beq ndfnd
        cmp #82                 ; r / R: fetch this type again
        beq ndref
        cmp #210
        beq ndref
        jmp ndkey
ndfnd:  jmp nfkey
ndref:  ldx NTYPE
        lda #0
        sta TLOAD,x
        jmp ndfetch
nddn:   lda MNSEL
        clc
        adc #1
        cmp MNN
        bcc nddn2
; off the bottom: scroll if there is more below, otherwise wrap to the top
        lda NDOFF
        clc
        adc MNN
        cmp NVIS
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
ndlast: lda NVIS
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
        lda NVIS
        sec
        sbc #1
        sta MNSEL
        jmp ndpage
ndtake: lda NDOFF
        clc
        adc MNSEL
        tax
        lda NODEIX,x
        sta CIDX
        jmp nodeact
ndcan:  jmp mmshut


; ===== direct-message conversations ====================================
; Channels 40-47. Each has the contact's 6-byte key prefix in DMKEYS and
; its name in the ordinary channel-name table, so the picker, the prompt,
; the unread counters and the archive all treat it as a channel.

; open the selected contact's conversation and switch to it
dmopen: lda CIDX
        jsr contptr
        ldy #26                 ; key starts at 26 in a contact slot
        ldx #0
dmo1:   lda (PTR),y
        sta DMNK,x
        iny
        inx
        cpx #6
        bcc dmo1
        lda PTR                 ; the name is first in the slot
        sta SPL
        lda PTRH
        sta SPH
        jsr dmslot
        sta CC
        jmp mmshut              ; clears and runs setchan

; an incoming DM: key at BUF+4. Returns its conversation in A.
dmin:   ldx #0
dmi1:   lda BUF+4,x
        sta DMNK,x
        inx
        cpx #6
        bcc dmi1
        lda #0
        sta SPH                 ; no name unless the contact is known
        jsr dmwho
        bcs dmi2
        lda PTR
        sta SPL
        lda PTRH
        sta SPH
dmi2:   jmp dmslot

; DMNK = key prefix, SPL/SPH = its ASCII name (SPH 0: none).
; Returns A = 40 + the slot already holding that key, or a new one -- a
; free slot first, else the next in rotation.
dmslot: lda #0
        sta DSN
dsl1:   ldx DSN
        cpx #8
        bcs dsnew
        lda DMUSE,x
        beq dsnx
        jsr dsoff
        ldx #0
dsl2:   lda DMKEYS,y
        cmp DMNK,x
        bne dsnx
        iny
        inx
        cpx #6
        bcc dsl2
; Already open. If we now know the name, use it: a DM that arrived before
; the node list was loaded opened the conversation as "dm xxxxxx".
        lda SPH
        beq dsret
        jmp dsnm
dsnx:   inc DSN
        jmp dsl1
dsnew:  ldx #0
dsf:    lda DMUSE,x
        beq dsgot
        inx
        cpx #8
        bcc dsf
        lda DMNEXT              ; all eight in use: recycle the next one
        tax
        clc
        adc #1
        and #7
        sta DMNEXT
dsgot:  stx DSN
        lda #1
        sta DMUSE,x
; a recycled slot's unread belonged to someone else -- take it back off
; the "+N" total too
        txa
        clc
        adc #40
        tax
        lda UT
        sec
        sbc CUNR,x
        bcs dsut
        lda #0
dsut:   sta UT
        lda #0
        sta CUNR,x
        jsr dsoff
        ldx #0
dsk:    lda DMNK,x
        sta DMKEYS,y
        iny
        inx
        cpx #6
        bcc dsk
; the name, into the channel-name table as PETSCII
dsnm:   lda DSN
        clc
        adc #40
        jsr chnptr
        ldy #0
        lda SPH
        beq dsanon
dsn1:   lda (SPL),y
        beq dsn2
        cmp #65
        bcc dsn4
        cmp #91
        bcs dsn3
        ora #32                 ; same case swap as s2asc
        bne dsn4
dsn3:   cmp #97
        bcc dsn4
        cmp #123
        bcs dsn4
        and #223
dsn4:   sta (PTR),y
        iny
        cpy #16
        bcc dsn1
dsn2:   lda #0
        sta (PTR),y
        jmp dsret
; not in the node list: "dm" and the first three key bytes in hex
dsanon: lda #68                 ; 'd'
        sta (PTR),y
        iny
        lda #77                 ; 'm'
        sta (PTR),y
        iny
        lda #32
        sta (PTR),y
        iny
        ldx #0
dsh1:   lda DMNK,x
        lsr
        lsr
        lsr
        lsr
        jsr dshex
        lda DMNK,x
        and #15
        jsr dshex
        inx
        cpx #3
        bcc dsh1
        jmp dsn2
dshex:  cmp #10
        bcc dshx2
        adc #6                  ; carry set: +7, 10 -> 'a'
dshx2:  adc #48
        sta (PTR),y
        iny
        rts
dsret:  lda DSN
        clc
        adc #40
        rts
; Y = DSN * 6
dsoff:  lda DSN
        asl
        sta S2T
        asl
        clc
        adc S2T
        tay
        rts

; Called by setchan: in a DM conversation, typing goes to its contact.
; Anywhere else it goes to the channel -- this is what clears DMON, which
; nothing used to.
dmsel:  lda CC
        cmp #40
        bcc dmoff
        cmp #48
        bcs dmoff
        sec
        sbc #40
        sta DSN
        jsr dsoff
        ldx #0
dms1:   lda DMKEYS,y
        sta DMKEY,x
        iny
        inx
        cpx #6
        bcc dms1
        lda #1
        sta DMON
        rts
dmoff:  lda #0
        sta DMON
        rts

; ===== segment 2 strings (ascii; CHROUT shows them as the rest of the ui)
s2refr: .text "refreshing channels, please wait"
        .byte 13
        .text "(any key aborts)"
        .byte 13,0
s2boot: .text "scanning for channels,"
        .byte 13
        .text "press any key to skip"
        .byte 13,0
s2skip: .text "skipped. f1, channels scans later."
        .byte 13,0
s2slot: .text "slot "
        .byte 0
s2of40: .text "/40  found "
        .byte 0
s2colon: .text ": "
        .byte 0
s2cfnd: .text "channels found: "
        .byte 0
s2abt:  .text " (aborted)"
        .byte 0
s2load: .text "loading "
        .byte 0
s2ldh:  .text "..."
        .byte 13
        .text "reading every node from the radio."
        .byte 13
        .text "the list is kept, r reloads it."
        .byte 13
        .text "any key stops and keeps what arrived."
        .byte 13,13,0
s2chk:  .text "checked "
        .byte 0
s2kept: .text "  kept "
        .byte 0
s2none: .text "None found"
        .byte 0
s2trn1: .text "List incomplete - showing what"
        .byte 0
s2trn2: .text "arrived. R in the list reloads"
        .byte 0
nt1:    .text "Companions"
        .byte 0
nt2:    .text "Repeaters"
        .byte 0
nt3:    .text "Room servers"
        .byte 0
nt4:    .text "Sensors"
        .byte 0
nttab:  .word nt1,nt2,nt3,nt4
tt1:    .text " Companions "
        .byte 0
tt2:    .text " Repeaters "
        .byte 0
tt3:    .text " Room servers "
        .byte 0
tt4:    .text " Sensors "
        .byte 0
nttit:  .word tt1,tt2,tt3,tt4
sradz:  .text "Advert: zero hop"
        .byte 0
sradf:  .text "Advert: flood"
        .byte 0
sadsz:  .text "Zero-hop advert sent"
        .byte 0
sadsf:  .text "Flood advert sent"
        .byte 0

; ===== segment 2 variables =============================================
; Re-initialised by the copy at every boot.
SCBUSY: .byte 0                 ; a scan / fetch owns the link: defer sync
SYNCP:  .byte 0                 ; ...and one was asked for meanwhile
SCMODE: .byte 0                 ; 1 = boot scan: header printed, keep screen
SCABT:  .byte 0
CSTMO:  .byte 0
NFOUND: .byte 0
LASTF:  .byte 0
SCNMAX: .byte 0                 ; slots the last scan actually read
MCH:    .byte 0                 ; channel of the message being archived
SCOL:   .byte 0
S2T:    .byte 0
WJ2:    .byte 0
WANT2:  .byte 0
S2TMO:  .byte 0
CBASEH: .byte 128               ; contact table, high byte
NTYPE:  .byte 0
NVIS:   .byte 0
NIDX:   .byte 0
NDST:   .byte 0
NRECV:  .byte 0                 ; kept
NSEEN:  .byte 0                 ; every contact frame, any type
NSEENH: .byte 0
NTRUNC: .byte 0
NTMO:   .byte 0
ADVF:   .byte 0
TLOAD:  .byte 0,0,0,0,0         ; per type: fetched, shown from memory

; ===== GeoRAM / NeoRAM (s7, mkgeo.py) ==================================
; Only reached with no REU. A real one answers at $DE00 with page/block
; selects at $DFFE/$DFFF; with nothing there the window is open bus and
; the two test patterns do not read back.
geodet: lda geook
        bne gdgo
        rts
gdgo:   lda #63
        sta GEOPG
        lda #0
        sta GEOBK
        lda GEOWIN+253
        sta GORIG
        lda #165
        sta GEOWIN+253
        lda GEOWIN+253
        cmp #165
        bne gdno
        lda #90
        sta GEOWIN+253
        lda GEOWIN+253
        cmp #90
        bne gdno
; the page register has to select different memory, or this is just some
; RAM-like thing in I/O 1 and not a GeoRAM
        lda #62
        sta GEOPG
        lda GEOWIN+253
        sta GTMP
        lda #195
        sta GEOWIN+253
        lda #63
        sta GEOPG
        lda GEOWIN+253
        sta GTMP2
        lda #62
        sta GEOPG
        lda GTMP
        sta GEOWIN+253
        lda GTMP2
        cmp #90
        bne gdno
; size: mark block N, look at block 0. Unused high block bits wrap, so the
; first N that lands back on block 0 is the size. 256 blocks wraps N to 0.
        lda #1
        sta GBLKS
gdsz:   lda #63
        sta GEOPG
        lda GBLKS
        sta GEOBK
        lda GEOWIN+253
        sta GTMP
        lda #195
        sta GEOWIN+253
        lda #0
        sta GEOBK
        lda GEOWIN+253
        cmp #90
        bne gdwrap
        lda GBLKS
        sta GEOBK
        lda GTMP
        sta GEOWIN+253
        asl GBLKS
        bne gdsz
gdwrap: lda #63
        sta GEOPG
        lda #0
        sta GEOBK
        lda GORIG
        sta GEOWIN+253
        lda GBLKS
        beq gdbig
        cmp #8                  ; under 128K is not worth having
        bcs gdbig
gdno:   lda #0
        sta RU
        rts
; size in KB = blocks * 16 (256 blocks = 4096)
gdbig:  lda GBLKS
        sta UKL
        lda #0
        sta UKH
        lda GBLKS
        bne gdk
        lda #16
        sta UKH
        jmp gdl
gdk:    ldx #4
gdkl:   asl UKL
        rol UKH
        dex
        bne gdkl
; two blocks are ours (header + channels, contacts); the rest is archive,
; 9 regions of 2^L lines x 64 bytes: L=9 wants 18 blocks, 8 wants 9, 7 wants 5
gdl:    lda GBLKS
        beq gl9
        cmp #32
        bcs gl9
        cmp #16
        bcs gl8
        lda #7
        jmp glset
gl8:    lda #8
        jmp glset
gl9:    lda #9
glset:  jsr rdset               ; MAXL/STRL from LSHIFT, as for an REU
        lda #2
        sta RU
        rts

; ----- block/page/offset of an archive slot (after reuaddr) -----
garc:   lda ADRL
        sta GOFF
        lda ADRM
        and #63
        sta GPAG
        lda ADRH
        asl
        asl
        sta GBLK
        lda ADRM
        lsr
        lsr
        lsr
        lsr
        lsr
        lsr
        ora GBLK
        clc
        adc #2                  ; past header and contacts
        sta GBLK
        rts

; CNT bytes, PTR -> archive slot (lput)
geowr:  jsr reuaddr
        jsr garc
        lda CNT
        sta GLENL
        lda #0
        sta GLENH
        sta GDIR
        jmp gcopy
; CNT2 bytes, archive slot -> PTR (arcpage)
georr:  jsr reuaddr
        jsr garc
        lda CNT2
        sta GLENL
        lda #0
        sta GLENH
        lda #1
        sta GDIR
        jmp gcopy

; GLEN bytes between RAM at PTR and GBLK:GPAG:GOFF. GDIR 0 = to GeoRAM.
; PTR is left as it was.
gcopy:  lda PTR
        pha
        lda PTRH
        pha
gcsel:  lda GPAG
        sta GEOPG
        lda GBLK
        sta GEOBK
        ldy #0
gcl:    lda GLENL
        ora GLENH
        beq gcd
        ldx GOFF
        lda GDIR
        bne gcr
        lda (PTR),y
        sta GEOWIN,x
        jmp gcn
gcr:    lda GEOWIN,x
        sta (PTR),y
gcn:    inc PTR
        bne gcn1
        inc PTRH
gcn1:   lda GLENL
        bne gcn2
        dec GLENH
gcn2:   dec GLENL
        inc GOFF
        bne gcl
        inc GPAG
        lda GPAG
        cmp #64
        bcc gcsel
        lda #0
        sta GPAG
        inc GBLK
        jmp gcsel
gcd:    pla
        sta PTRH
        pla
        sta PTR
        rts

; ----- header: block 0 page 0 -----
ghsel:  lda #0
        sta GEOPG
        sta GEOBK
        rts

gsvh:   lda RU
        cmp #2
        beq gsh1
        cmp #1
        bne gshx
        jmp rsvh
gshx:   rts
gsh1:   jsr ghsel
        ldx #0
gshs:   lda gsig,x
        sta GEOWIN,x
        inx
        cpx #5
        bcc gshs
        lda LSHIFT
        sta GEOWIN+5
        lda GBLKS
        sta GEOWIN+6
        lda NCONT
        sta GEOWIN+7
        lda CKED
        sta GEOWIN+8
        lda SCNMAX
        sta GEOWIN+9
        ldx #0
gsht:   lda TLOAD,x
        sta GEOWIN+10,x
        inx
        cpx #5
        bcc gsht
        lda UTCOFF
        sta GEOWIN+15
        ldx #0
gshp:   lda LWL,x               ; LWL..LFH: $cf50-$cf8f
        sta GEOWIN+64,x
        inx
        cpx #64
        bcc gshp
        ldx #0
gshu:   lda CUNR,x
        sta GEOWIN+128,x
        inx
        cpx #48
        bcc gshu
        jmp gdmsv

; channel names, then the header
gsvc:   lda RU
        cmp #2
        beq gsc1
        cmp #1
        bne gscx
        jmp rsvc
gscx:   rts
gsc1:   lda PTR
        pha
        lda PTRH
        pha
        lda #<CHNAM
        sta PTR
        lda #>CHNAM
        sta PTRH
        lda #0
        sta GBLK
        sta GOFF
        sta GDIR
        lda #1
        sta GPAG
        lda #<864
        sta GLENL
        lda #>864
        sta GLENH
        jsr gcopy
        pla
        sta PTRH
        pla
        sta PTR
        jmp gsvh

; the node table (NCONT x 64), then the header
gsvk:   lda RU
        cmp #2
        beq gsk1
        cmp #1
        bne gskx
        jmp rsvk
gskx:   rts
gsk1:   lda PTR
        pha
        lda PTRH
        pha
        jsr gkset
        lda #0
        sta GDIR
        jsr gcopy
        pla
        sta PTRH
        pla
        sta PTR
        jmp gsvh
gkset:  lda #0
        sta PTR
        sta GPAG
        sta GOFF
        lda CBASEH
        sta PTRH
        lda #1
        sta GBLK
        lda NCONT               ; x64
        sta GLENL
        lda #0
        sta GLENH
        ldx #6
gksl:   asl GLENL
        rol GLENH
        dex
        bne gksl
        rts

; ----- boot: is this NeoRAM holding our last session? -----
georest:
        lda #0
        sta GREST
        lda RU
        cmp #2
        beq grs1
        cmp #1
        bne grsx
        jmp rrest
grsx:   rts
grs1:   jsr ghsel
        ldx #0
grsg:   lda GEOWIN,x
        cmp gsig,x
        bne grnew
        inx
        cpx #5
        bcc grsg
        lda GEOWIN+5            ; same layout, or the pointers are nonsense
        cmp LSHIFT
        bne grnew
        lda GEOWIN+6
        cmp GBLKS
        bne grnew
        lda GEOWIN+7
        cmp MAXCON
        beq grs2
        bcs grnew
grs2:   lda GEOWIN+7
        sta NCONT
        lda GEOWIN+8
        sta CKED
        lda GEOWIN+9
        sta SCNMAX
        ldx #0
grst:   lda GEOWIN+10,x
        sta TLOAD,x
        inx
        cpx #5
        bcc grst
        lda GEOWIN+15
        sta UTCOFF
        ldx #0
grsp:   lda GEOWIN+64,x
        sta LWL,x
        inx
        cpx #64
        bcc grsp
        ldx #0
grsu:   lda GEOWIN+128,x
        sta CUNR,x
        inx
        cpx #48
        bcc grsu
        jsr gdmld
; channel names
        lda PTR
        pha
        lda PTRH
        pha
        lda #<CHNAM
        sta PTR
        lda #>CHNAM
        sta PTRH
        lda #0
        sta GBLK
        sta GOFF
        lda #1
        sta GPAG
        sta GDIR
        lda #<864
        sta GLENL
        lda #>864
        sta GLENH
        jsr gcopy
; nodes
        jsr gkset
        lda #1
        sta GDIR
        jsr gcopy
        pla
        sta PTRH
        pla
        sta PTR
        lda #1
        sta GREST
        rts
; blank or foreign: claim it with an empty session
grnew:  jmp gsvh

; ----- boot line -----
; ----- Stats: radio clock against the RTC (s41) -----
stoff:  lda #<soff
        ldx #>soff
        jsr stl
        lda UCOK
        cmp #2
        beq sto1
        lda #<snortc5
        ldx #>snortc5
        jmp stend
sto1:   lda UTCOFF
        cmp #$80
        bne sto2
        lda #<snoyet            ; no zone learned yet
        ldx #>snoyet
        jmp stend
sto2:   jsr uctoutc             ; CLKM = the RTC in UTC
        ldx #0
        ldy #4
        sec
sto3:   lda NOWTS,x
        sbc CLKM,x
        sta UCAC,x
        inx
        dey
        bne sto3
        lda #43                 ; '+': the radio is ahead
        bcs sto6
        ldx #0
        ldy #4
        sec
sto4:   lda CLKM,x
        sbc NOWTS,x
        sta UCAC,x
        inx
        dey
        bne sto4
        lda #45                 ; '-': behind
sto6:   pha
        lda #<srad
        ldx #>srad
        jsr stcat
        pla
        jsr plchr
        jsr stsec
        jmp plend
birest: lda GREST
        bne bir1
        rts
bir1:   lda #<srest
        sta PTR
        lda #>srest
        sta PTRH
        jmp prtstr

gsig:   .byte 77,67,54,52,2     ; "MC64", layout 2: 25-char contact names
sgeo:   .text "georam detected  "
        .byte 0
srest:  .text ", restored"
        .byte 0
GBLK:   .byte 0
GPAG:   .byte 0
GOFF:   .byte 0
GLENL:  .byte 0
GLENH:  .byte 0
GDIR:   .byte 0
GBLKS:  .byte 0                 ; GeoRAM size in 16K blocks, 0 = 256
GORIG:  .byte 0
GTMP:   .byte 0
GTMP2:  .byte 0
GREST:  .byte 0                 ; 1 = this boot restored a NeoRAM session

; ===== REU session persistence (s10, mkreup.py) =========================
; An REU keeps its RAM through a reset. The persist area sits right after
; the nine archive regions, at 9 * stride.
; ADR = persist base + page X, offset Y
rpad:   sty ADRL
        lda STRM                ; 9 * stride; stride is a multiple of 8K,
        sta RPM                 ; so its low byte is 0
        lda STRH
        sta RPH
        ldy #3
rpa8:   asl RPM                 ; x8
        rol RPH
        dey
        bne rpa8
        lda RPM
        clc
        adc STRM                ; +1
        sta RPM
        lda RPH
        adc STRH
        sta RPH
        txa
        clc
        adc RPM
        sta ADRM
        lda RPH
        adc #0
        sta ADRH
        rts

; GLEN bytes between RAM at PTR and the REU at ADR, command DCMD.
; Moves PTR along; callers save it.
rpbig:  lda GLENH
        bne rpb1
        lda GLENL
        beq rpbd
        cmp #128
        bcc rpb2
rpb1:   lda #128
rpb2:   sta DLEN
        sta RPN
        jsr reuchunk
        lda PTR
        clc
        adc RPN
        sta PTR
        bcc rpb3
        inc PTRH
rpb3:   lda GLENL
        sec
        sbc RPN
        sta GLENL
        bcs rpbig
        dec GLENH
        jmp rpbig
rpbd:   rts

; one piece of the header page: A = RAM low, X = RAM high, Y = offset,
; RPN = length
rphp:   sta PTR
        stx PTRH
        lda RPN
        sta GLENL
        lda #0
        sta GLENH
        ldx #0
        jsr rpad
        jmp rpbig

; header: signature + small state, archive pointers, unread counts
rsvh:   lda PTR
        pha
        lda PTRH
        pha
        ldx #0
rshs:   lda rsig,x
        sta RHB,x
        inx
        cpx #5
        bcc rshs
        lda LSHIFT
        sta RHB+5
        lda UKH
        sta RHB+6
        lda NCONT
        sta RHB+7
        lda CKED
        sta RHB+8
        lda SCNMAX
        sta RHB+9
        ldx #0
rsht:   lda TLOAD,x
        sta RHB+10,x
        inx
        cpx #5
        bcc rsht
        lda UTCOFF
        sta RHB+15
        lda #144                ; $90 c64 -> reu
        sta DCMD
        jsr rhdo
        pla
        sta PTRH
        pla
        sta PTR
        rts
; the three header pieces, in the direction DCMD says
rhdo:   lda #16
        sta RPN
        lda #<RHB
        ldx #>RHB
        ldy #0
        jsr rphp
        lda #64
        sta RPN
        lda #<LWL
        ldx #>LWL
        ldy #64
        jsr rphp
        lda #48
        sta RPN
        lda #<CUNR
        ldx #>CUNR
        ldy #128
        jsr rphp
        jmp rdmp                ; the DM conversations

; channel names -> pages 1-4, then the header
rsvc:   lda PTR
        pha
        lda PTRH
        pha
        lda #144
        sta DCMD
        jsr rcdo
        pla
        sta PTRH
        pla
        sta PTR
        jmp rsvh
rcdo:   lda #<CHNAM
        sta PTR
        lda #>CHNAM
        sta PTRH
        lda #<864
        sta GLENL
        lda #>864
        sta GLENH
        ldx #1
        ldy #0
        jsr rpad
        jmp rpbig

; node table -> pages 5.., then the header
rsvk:   lda PTR
        pha
        lda PTRH
        pha
        lda #144
        sta DCMD
        jsr rkdo
        pla
        sta PTRH
        pla
        sta PTR
        jmp rsvh
rkdo:   jsr gkset               ; PTR = table, GLEN = NCONT * 64
        ldx #5
        ldy #0
        jsr rpad
        jmp rpbig

; boot: is the REU still holding our last session (a reset, not a
; power-off)? Same checks as a NeoRAM.
rrest:  lda PTR
        pha
        lda PTRH
        pha
        lda #145                ; $91 reu -> c64
        sta DCMD
        lda #16
        sta RPN
        lda #<RHB
        ldx #>RHB
        ldy #0
        jsr rphp
        ldx #0
rrsg:   lda RHB,x
        cmp rsig,x
        bne rrnew
        inx
        cpx #5
        bcc rrsg
        lda RHB+5               ; same layout, or the pointers are nonsense
        cmp LSHIFT
        bne rrnew
        lda RHB+6
        cmp UKH
        bne rrnew
        lda RHB+7
        cmp MAXCON
        beq rrs2
        bcs rrnew
rrs2:   lda RHB+7
        sta NCONT
        lda RHB+8
        sta CKED
        lda RHB+9
        sta SCNMAX
        ldx #0
rrst:   lda RHB+10,x
        sta TLOAD,x
        inx
        cpx #5
        bcc rrst
        lda RHB+15
        sta UTCOFF
        jsr rhdo                ; DCMD is still $91: pointers + unread + DMs
        jsr dmfix
        jsr rcdo
        jsr rkdo
        pla
        sta PTRH
        pla
        sta PTR
        lda #1
        sta GREST
        rts
; blank or foreign: claim it with an empty session
rrnew:  pla
        sta PTRH
        pla
        sta PTR
        jmp rsvh

rsig:   .byte 77,67,54,52,3     ; "MC64", REU layout 3: 25-char contact names
RHB:    .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
RPM:    .byte 0
RPH:    .byte 0
RPN:    .byte 0

; ===== readability (s11) ===============================================
; one separator row into the archive, before a message (REGION set)
lsep:   ldx #39
        lda #64                 ; screen code: horizontal rule
lsl:    sta SBUF,x
        dex
        bpl lsl
        lda #1
        sta SLEN
        jmp lput
; scrn, then flag the first row as a message start
scrnm:  jsr scrn
        lda SBUF+39
        ora #128
        sta SBUF+39
        rts
; live: CR, a dark grey rule, back to green for the prompt
smsep:  lda #13
        jsr CHROUT
        lda #151
        jsr CHROUT
        ldx KSEPW               ; 39, or 79 on the 80 column screen
sssl:   lda #192                ; petscii horizontal rule
        jsr CHROUT
        dex
        bne sssl
        lda #30
        jmp CHROUT
; petscii -> screen code, as scrn does it. X kept.
p2sc:   cmp #32
        bcc p2c
        cmp #64
        bcc p2r
        cmp #96
        bcc p2a
        cmp #128
        bcc p2b
        cmp #192
        bcc p2r
        and #127
        rts
p2a:    and #191
        rts
p2b:    and #223
        rts
p2c:    lda #32
p2r:    rts
; colour the screen row at PTR from what was painted into it
apcol:  lda PTR
        sta PTR2
        lda PTRH
        clc
        adc #212                ; $0400 -> $d800
        sta PTR2H
        ldy #0
        lda (PTR),y
        cmp #64
        bne acm
        iny
        lda (PTR),y
        cmp #64
        bne acm
        ldy #0
        lda #11                 ; a separator: dark grey
        jmp acfill
acm:    ldy #39
        lda (PTR),y
        bpl actxt               ; a continuation row: all text
        and #127
        sta (PTR),y
        ldy #0
        lda (PTR),y
        cmp #62                 ; '>': our own message
        beq actxt
        cmp #27                 ; '[': the merged view's room
        bne acnm
acrl:   lda #3                  ; cyan
        sta (PTR2),y
        lda (PTR),y
        iny
        cmp #29                 ; ']'
        beq acrd
        cpy #40
        bcc acrl
        rts
acrd:   cpy #40
        bcs acdone
        lda #3
        sta (PTR2),y            ; the space after it
        iny
acnm:   sty APS
acfl:   cpy #40
        bcs acnone
        lda (PTR),y
        cmp #58                 ; ':'
        beq acfnd
        iny
        jmp acfl
acnone: ldy APS                 ; no sender field: plain text
        jmp actx2
acfnd:  sty APC
        lda #0
        sta APH
        ldy APS
achl:   cpy APC
        bcs ach2
        lda (PTR),y
        clc
        adc APH
        sta APH
        iny
        jmp achl
ach2:   lda APH
        and #7
        tax
        lda smcr,x
        ldy APS
acnl:   sta (PTR2),y
        iny
        cpy APC
        bcc acnl
        jmp actx2
actxt:  ldy #0
actx2:  lda #5                  ; green: all message text
acfill: sta (PTR2),y
        iny
        cpy #40
        bcc acfill
acdone: rts
APS:    .byte 0
APC:    .byte 0
APH:    .byte 0

; ===== REU transfer in short pieces (patch243) =========================
; DMA halts the CPU, and the receiver's NMI with it, for the whole
; transfer. Eight bytes at a time keeps every stall to ~10 cycles, which
; even a 7200-baud bit absorbs. DLEN bytes between PTR and ADR, command
; DCMD ($90 stash / $91 fetch). PTR is left alone; ADR is advanced.
reuchunk:
        lda PTR
        sta DPL
        lda PTRH
        sta DPH
rcl:    lda DLEN
        beq rcd
        cmp #8
        bcc rc1
        lda #8
rc1:    sta DN
        lda DPL
        sta RC64L
        lda DPH
        sta RC64H
        lda ADRL
        sta RREUL
        lda ADRM
        sta RREUM
        lda ADRH
        sta RREUB
        lda DN
        sta RLENL
        lda #0
        sta RLENH
        sta RCTL
        lda DCMD
        sta RCMD
        lda DPL
        clc
        adc DN
        sta DPL
        bcc rc2
        inc DPH
rc2:    lda ADRL
        clc
        adc DN
        sta ADRL
        bcc rc3
        inc ADRM
        bne rc3
        inc ADRH
rc3:    lda DLEN
        sec
        sbc DN
        sta DLEN
        jmp rcl
rcd:    rts
DLEN:   .byte 0
DCMD:   .byte 0
DN:     .byte 0
DPL:    .byte 0
DPH:    .byte 0
S2KEY:  .byte 0                 ; s2wait: a key also ends the wait
S2HIT:  .byte 0                 ; ...and this is the key
DSN:    .byte 0
DMNEXT: .byte 0
DMNK:   .byte 0,0,0,0,0,0
DMUSE:  .byte 0,0,0,0,0,0,0,0
DMKEYS: .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
        .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
DMMK:   .byte $D7                ; DMUSE..DMMK = 57 bytes saved with the session


; ===== radio configuration =============================================
; Each line renders the live value; RETURN on it steps to the next preset.
; "apply" writes them to the node.
radiovw:
        lda #1
        sta UIMODE
        lda #0
        sta MNSEL
; **Ask the radio what it is actually set to, right now.**
; These values arrived once, in the handshake reply, and were never read
; again -- so anything changed since boot, by us or from a phone, showed
; stale. APP_START is the only command that returns SELF_INFO, and dself
; refills RFREQ/RBW/RSF/RCR/RPWR from it.
        jsr rvload
        jsr rvseed
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
        lda #<sradz
        sta SPL
        lda #>sradz
        sta SPH
        jsr plstr
        jsr plend
        jsr plnew
        lda #<sradf
        sta SPL
        lda #>sradf
        sta SPH
        jsr plstr
        jsr plend
        jsr plnew
        lda #<srpurge
        sta SPL
        lda #>srpurge
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
        cmp #7
        beq rvadz
        cmp #8
        beq rvadf
        jmp purge4              ; 9: purge old nodes (255, F1, lands below)
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

; Re-read the node's live settings. UIMODE is already 1, so nothing that
; arrives while we wait will print over the panel.
rvload: lda #<pyastart
        sta PTR
        lda #>pyastart
        sta PTRH
        lda #11
        jsr setpay
        jsr sendfr
        lda #0
        sta STGBIT              ; not a handshake stage
        lda #5                  ; RESP_CODE_SELF_INFO
        jmp waitop

; Line the two cycling fields up with reality.
;
; Both step with "inc <index>", and the index started at zero whatever the
; radio was actually on -- so the first keypress jumped to preset 1 and
; discarded the node's real setting without ever showing it as a choice.
; Find the live value in the table instead. 255 means "not one of the
; presets", and inc takes that to 0, which is the sensible place to start.
rvseed: lda #255
        sta RIDX
        ldy #16                 ; five presets, four bytes each
rvq1:   lda freqtab,y
        cmp RFREQ
        bne rvq2
        lda freqtab+1,y
        cmp RFREQ+1
        bne rvq2
        lda freqtab+2,y
        cmp RFREQ+2
        bne rvq2
        lda freqtab+3,y
        cmp RFREQ+3
        bne rvq2
        tya
        lsr
        lsr
        sta RIDX
rvq2:   tya
        sec
        sbc #4
        tay
        bpl rvq1
        lda #255
        sta RBIDX
        ldy #12                 ; four presets
rvq3:   lda bwtab,y
        cmp RBW
        bne rvq4
        lda bwtab+1,y
        cmp RBW+1
        bne rvq4
        lda bwtab+2,y
        cmp RBW+2
        bne rvq4
        lda bwtab+3,y
        cmp RBW+3
        bne rvq4
        tya
        lsr
        lsr
        sta RBIDX
rvq4:   tya
        sec
        sbc #4
        tay
        bpl rvq3
        rts

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

; 910.525, 869.525, 868.000, 906.875, 433.500 -- all in kHz.
;
; **910.525 is FIRST on purpose.** It is MeshCore's US frequency, and the
; slot it replaced held 915.000 -- the band edge, not the frequency the US
; mesh actually runs on. A node still sitting on 915.000 does not match
; any entry here, so rvseed leaves the index at 255 and the first press
; lands on entry 0. Putting the US preset there makes that first press the
; useful one instead of a walk through two EU bands.
; ----- send an advert -----
; CMD_SEND_SELF_ADVERT, and its one optional byte picks the reach:
; 0 = zero hop (neighbours that hear us directly), 1 = flood (repeated
; across the mesh).
rvadz:  lda #0
        beq rvadv
rvadf:  lda #1
rvadv:  sta ADVF
        sta TXBUF+1
        lda #1                  ; menu() cleared it; the panel needs it
        sta UIMODE
        lda #7
        sta TXBUF
        lda #2
        sta TXLEN
        jsr sendfr
        jsr plinit
        jsr plnew
        lda ADVF
        bne rvadv2
        lda #<sadsz
        sta SPL
        lda #>sadsz
        sta SPH
        jmp rvadv3
rvadv2: lda #<sadsf
        sta SPL
        lda #>sadsf
        sta SPH
rvadv3: jsr plstr
        jsr plend
        lda #<tradio
        sta MNTIT
        lda #>tradio
        sta MNTITH
        jsr plshow
        jmp mmshut

freqtab: .byte 189,228,13,0
        .byte 149,68,13,0
        .byte 160,62,13,0
        .byte 123,214,13,0
        .byte 92,157,6,0
; 250k, 125k, 62.5k, 500k -- in Hz
bwtab:  .byte 144,208,3,0
        .byte 72,232,1,0
        .byte 36,244,0,0
        .byte 32,161,7,0



; ===== contacts ========================================================
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
; the table base is page-aligned and depends on the reu: see s2init
        lda PTRH
        clc
        adc CBASEH
        sta PTRH
        rts

; RESP_CODE_CONTACT: 1-32 key, 33 type, 34 flags, 35 out_path_len,
; 36-99 route, 100-131 name. Keep the parts we can act on.
; Only the type being fetched. The radio sends every contact -- it has no
; type filter -- so the choice is made here.
rxcont: lda BUF+33
        cmp NTYPE
        bne rxcrt
        lda NCONT
        cmp MAXCON
        bcs rxcrt               ; table full; the rest are dropped
        lda NCONT
        jsr contptr
; Take the name from the RAW frame, not the converted copy. conv() makes
; PETSCII for CHROUT, but the menu draws through a2s, which expects ASCII
; -- running both turned every name uppercase.
        ldy #0
rxcnl:  cpy #25
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
        adc #26
        tay
        lda BUF+1,x
        sta (PTR),y
        inx
        jmp rxcpl
rxcpd:  ldy #58
        lda BUF+35              ; out_path_len; $ff means "no route, flood"
        sta (PTR),y
        ldx #0
rxcrl:  cpx #4
        bcs rxcrd
        txa
        clc
        adc #60
        tay
        lda BUF+36,x
        sta (PTR),y
        inx
        jmp rxcrl
rxcrd:  ldy #59
        lda BUF+33
        sta (PTR),y
        inc NCONT
rxcrt:  rts

; ===== Ultimate Command Interface: GET_TIME (s13, mkuci.py) ============
; UCOK: 0 no interface or no answer, 1 answered but not a usable date,
; 2 UCTS = Unix time. UCSTR = the text, 0-terminated, either way.
ucget:  lda #0
        sta UCOK
        sta UCSTR
        lda $DF1D
        cmp #$C9                ; the interface identifies itself
        bne ucgx
        lda $DF1C
        and #$30
        beq ucg1
        lda #4                  ; left busy by someone: abort it
        sta $DF1C
        jsr ucidl
        bcs ucgx
ucg1:   lda #1                  ; DOS target
        sta $DF1D
        lda #$26                ; GET_TIME
        sta $DF1D
        lda #1                  ; push
        sta $DF1C
        lda #$20                ; wait for a data state (10 or 11)
        sta UCWM
        sta UCWV
        jsr ucwt
        bcs ucgab
        ldy #0
ucg2:   lda $DF1C
        bpl ucg3                ; no more data
        lda $DF1E
        cpy #39
        bcs ucg2                ; keep what fits a line
        sta UCSTR,y
        iny
        bne ucg2
ucg3:   lda #0
        sta UCSTR,y
ucg4:   lda $DF1C               ; drain the status text ("00,ok")
        and #$40
        beq ucg5
        lda $DF1F
        jmp ucg4
ucg5:   lda #2                  ; data accepted: back to idle
        sta $DF1C
        jsr ucidl
        lda #1
        sta UCOK
        jmp ucpar
ucgab:  lda #4
        sta $DF1C
ucgx:   rts

ucidl:  lda #$30
        sta UCWM
        lda #0
        sta UCWV
; wait for (status & UCWM) = UCWV, about half a second at most; C set = gave up
ucwt:   ldx #0
        ldy #0
ucw1:   lda $DF1C
        and UCWM
        cmp UCWV
        beq ucw2
        dex
        bne ucw1
        dey
        bne ucw1
        sec
        rts
ucw2:   clc
        rts

; six numbers out of the text: year month day hour minute second
ucpar:  ldx #13
        lda #0
ucp0:   sta UCN,x               ; UCN..+11, UCIN
        dex
        bpl ucp0
        inx                     ; X = 0: first number
        ldy #0
ucp1:   lda UCSTR,y
        beq ucp4
        iny
        sec
        sbc #48
        cmp #10
        bcs ucp3
        pha                     ; UCN[x] = UCN[x] * 10 + digit
        lda UCN,x
        sta UCT
        lda UCN+1,x
        sta UCT+1
        asl UCT
        rol UCT+1               ; 2v
        lda UCT
        sta UCT+2
        lda UCT+1
        sta UCT+3
        asl UCT
        rol UCT+1
        asl UCT
        rol UCT+1               ; 8v
        clc
        lda UCT
        adc UCT+2
        sta UCT
        lda UCT+1
        adc UCT+3
        sta UCT+1               ; 10v
        pla
        clc
        adc UCT
        sta UCN,x
        lda UCT+1
        adc #0
        sta UCN+1,x
ucp2:   lda #1
        sta UCIN
        bne ucp1
ucp3:   lda UCIN                ; a separator ends a number
        beq ucp1
        lda #0
        sta UCIN
        inx
        inx
        cpx #12
        bcc ucp1
ucp4:
; checks: 2025 <= year <= 2047, month 1-12, day 1-31, h < 24, m,s < 60
        lda UCN+1
        cmp #7
        bne ucbad
        lda UCN
        cmp #$E9                ; 2025 = $07E9 (to 2047 = $07FF)
        bcc ucbad
        lda UCN+3
        ora UCN+5
        ora UCN+7
        ora UCN+9
        ora UCN+11
        bne ucbad
        lda UCN+2
        beq ucbad
        cmp #13
        bcs ucbad
        lda UCN+4
        beq ucbad
        cmp #32
        bcs ucbad
        lda UCN+6
        cmp #24
        bcs ucbad
        lda UCN+8
        cmp #60
        bcs ucbad
        lda UCN+10
        cmp #60
        bcc ucdays
ucbad:  rts                     ; UCOK stays 1
; days since 1970-01-01. Y = year - 1900 (125..199); every fourth is a
; leap year in this range, 2000 included
ucdays: lda UCN
        sec
        sbc #$6C                ; 1900 = $076C
        sta UCY
        lda #0
        sta UCAC
        sta UCAC+1
        sta UCAC+2
        sta UCAC+3
        ldx #70
ucd1:   cpx UCY
        bcs ucd3
        clc                     ; 365 = $016D
        txa
        and #3
        bne ucd2
        sec                     ; leap year: 366
ucd2:   lda UCAC
        adc #$6D
        sta UCAC
        lda UCAC+1
        adc #1
        sta UCAC+1
        inx
        bne ucd1
ucd3:   ldx #1
ucd4:   cpx UCN+2
        bcs ucd6
        lda UCML-1,x
        cpx #2
        bne ucd5
        lda UCY
        and #3
        bne ucd5a
        lda #29
        bne ucd5
ucd5a:  lda #28
ucd5:   clc
        adc UCAC
        sta UCAC
        bcc ucd5b
        inc UCAC+1
ucd5b:  inx
        bne ucd4
ucd6:   ldx UCN+4
        dex
        txa
        clc
        adc UCAC
        sta UCAC
        bcc ucd7
        inc UCAC+1
ucd7:   ldx UCN+6               ; *24 + hour
        lda #24
        jsr ucmul
        ldx UCN+8               ; *60 + minute
        lda #60
        jsr ucmul
        ldx UCN+10              ; *60 + second
        lda #60
        jsr ucmul
        ldx #3
ucd8:   lda UCAC,x
        sta UCTS,x
        dex
        bpl ucd8
        lda #2
        sta UCOK
        rts

; UCAC = UCAC * A + X
ucmul:  sta UCK
        ldy #3
ucm0:   lda UCAC,y
        sta UCT,y
        lda #0
        sta UCAC,y
        dey
        bpl ucm0
        stx UCAC
ucm1:   lsr UCK
        bcc ucm3
        ldx #0
        ldy #4
        clc
ucm2:   lda UCAC,x
        adc UCT,x
        sta UCAC,x
        inx
        dey
        bne ucm2
ucm3:   asl UCT
        rol UCT+1
        rol UCT+2
        rol UCT+3
        lda UCK
        bne ucm1
        rts


; ===== login / telemetry requests, with every stage reported (s18) ======
; RQMODE 0 = login (password in INPASC/INPLEN), 1 = telemetry; CIDX = node.
; RQRES: 0 no answer, 1 answered (BUF holds it), 2 login refused (0x86),
; 3 the radio itself said no (RQERR). RQF1/RQF2 = the radio's "sent" flag
; for the first / second attempt: 0 direct, 1 flood, 255 it never confirmed.
rqrun:  lda #0
        sta RQTRY
        lda #255
        sta RQF1
        sta RQF2
        lda #133                ; push_code_login_success
        ldx RQMODE
        cpx #1
        bne rqr0
        lda #139                ; push_code_telemetry_response
rqr0:   sta RQWANT
rqgo:   ldx #11                 ; the input box is still up: a line under it
        ldy #4
        clc
        jsr 65520               ; $fff0 PLOT
        lda #<twaitn
        sta SPL
        lda #>twaitn
        sta SPH
        jsr prtsp
        jsr rqbuild
        jsr sendfr
        jsr rqwait
        lda RQTRY
        bne rqg1
        lda RQFLD
        sta RQF1
        jmp rqg2
rqg1:   lda RQFLD
        sta RQF2
rqg2:   lda RQRES
        bne rqdone
        lda RQTRY
        bne rqdone              ; already retried
        lda RQF1
        bne rqdone              ; flood (1) or never confirmed (255): no retry
        inc RQTRY               ; sent direct, silence: the stored route
        jsr rstp                ; may be dead. Forget it and flood, as the
        jmp rqgo                ; phone app does
rqdone: rts

; wait for the answer: RQWANT, 0x86 (login), or an error frame; "sent"
; frames just record how it went out. About 25 s at most.
rqwait: lda #0
        sta RQRES
        sta TOL
        lda #255
        sta RQFLD
        lda JIFFY
        sta WJ
rqw1:   jsr poll
        lda READY
        bne rqw3
        lda JIFFY
        cmp WJ
        bcs rqw2
        inc TOL
        lda TOL
        cmp #6
        bcs rqw9
rqw2:   lda JIFFY
        sta WJ
        jmp rqw1
rqw3:   lda BUF
        cmp #6                  ; RESP_CODE_SENT: byte 1 = 1 if flooded
        bne rqw4
        lda BUF+1
        sta RQFLD
        jmp rqw8
rqw4:   cmp #1                  ; RESP_CODE_ERR: byte 1 = the code
        bne rqw5
        lda BUF+1
        sta RQERR
        lda #3
        sta RQRES
        jmp rqwd
rqw5:   cmp RQWANT
        bne rqw6
        lda #1
        sta RQRES
        jmp rqwd
rqw6:   cmp #134                ; 0x86, login refused
        bne rqw7
        lda RQMODE
        cmp #1
        beq rqw7
        lda #2
        sta RQRES
        jmp rqwd
rqw7:   jsr dispat              ; something else: the usual handling
rqw8:   lda #0
        sta READY
        jmp rqw1
rqwd:   lda #0
        sta READY
rqw9:   rts


; a key only: ask for the record if it is new to us
dadv:   lda SCBUSY
        bne cfrt
        lda NCONT               ; nothing loaded yet: the first open fetches all
        beq cfrt
        lda NCONT
        cmp MAXCON
        bcs cfrt
        jsr ckfind
        bcc cfrt
        lda #30                 ; CMD_GET_CONTACT_BY_KEY
        sta TXBUF
        ldx #0
dak:    lda BUF+1,x
        sta TXBUF+1,x
        inx
        cpx #32
        bcc dak
        lda #33
        sta TXLEN
        jmp sendfr
UCML:   .byte 31,0,31,30,31,30,31,31,30,31,30
UCOK:   .byte 0
UCTS:   .byte 0,0,0,0
UCN:    .byte 0,0,0,0,0,0,0,0,0,0,0,0
UCIN:   .byte 0                 ; must follow UCN (cleared with it)
UCY:    .byte 0
UCAC:   .byte 0,0,0,0
UCT:    .byte 0,0,0,0
UCK:    .byte 0
UCWM:   .byte 0
UCWV:   .byte 0
UCSTR:  .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
        .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0


"""

# 2400 is THE speed. The slower rates are kept only because the bit period
# is a build-time constant either way, so they cost nothing and leave a way
# back if real hardware disagrees with the emulator -- they are not tested,
# because a run that passes at 2400 cannot fail at 600 for timing reasons.
RATES = {7: 600, 8: 1200, 10: 2400, 11: 4800, 12: 9600,
         13: 5760, 14: 6400, 15: 7200, 16: 8000}   # s5 experiments
DEFAULT_CTRL = 13               # 5760 baud


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
    # f1 -> add/remove channel -> add -> name "mych", key "abcd". No slot
    # step any more: the free slot is found for us.
    2: [[133, 17, 17, 17, 17, 13], [13],
        [77, 89, 67, 72, 13], [65, 66, 67, 68, 13]],
    # the #channel case: a name, then RETURN on an EMPTY key field
    22: [[133, 17, 17, 17, 17, 13], [13],
         [35, 111, 112, 101, 110, 13], [13]],
    # backing out of the key prompt with f1 must return to chat, not hang
    23: [[133, 17, 17, 17, 17, 13], [13],
         [77, 89, 67, 72, 13], [133]],
    # add/remove -> remove: the chooser lists channels BY NAME now, so
    # the last RETURN picks the first one -- without it the script stops
    # AT the chooser and never exercises the removal at all.
    24: [[133, 17, 17, 17, 17, 13], [17, 13], [13]],
    # f1 -> nodes -> first contact -> show route. No dismissing key: the
    # panel has to still be up when the screenshot is taken.
    3: [[133, 17, 13], [13], [13], [17, 17, 17, 13]],
    # f1 -> nodes -> first contact -> telemetry
    4: [[133, 17, 13], [13], [13], [17, 17, 13]],
    # f1 -> nodes -> first contact -> log in, password "pass"
    5: [[133, 17, 13], [13], [13], [17, 13], [80, 65, 83, 83, 13]],
    # f1 -> nodes -> first contact -> send message, then type "hi"
    6: [[133, 17, 13], [13], [13], [13], [72, 73, 13]],
    # let a few messages arrive (DEL is harmless on an empty line), then f5
    19: [[20], [20], [20], [20], [135]],
    # f1 -> nodes, then page down past the twelfth entry
    20: [[133, 17, 13], [13], [17, 17, 17, 17, 17, 17, 17, 17],
         [17, 17, 17, 17, 17]],
    21: [],
    50: [[104, 105, 13]],
    55: [[84, 72, 69, 32, 81, 85, 73, 67], [75, 32, 66, 82, 79, 87, 78, 32], [70, 79, 88, 32, 74, 85, 77, 80], [83, 32, 79, 86, 69, 82, 32, 84], [72, 69, 32, 76, 65, 90, 89, 32], [68, 79, 71, 32, 65, 78, 68, 32], [84, 72, 69, 78, 32, 83, 79, 77], [69, 32, 77, 79, 82, 69, 32, 84], [69, 88, 84, 32, 65, 66, 67, 88], [20, 20, 20], [13]],
    54: [[104, 105]],
    51: [[133, 17, 13], [17, 13], [47], [84, 79, 87, 69, 82, 13]],
    52: [[133, 17, 13], [17, 13], [47], [90, 90, 13]],
    53: [[133, 17, 13], [17, 13], [47], [79, 13]],
    42: [[20]] * 14 + [[133, 17, 13], [17, 13]],
    43: [[133, 17, 13], [17, 13], [133]] + [[20]] * 10 + [[133, 17, 13], [17, 13]],
    44: [[133, 17, 13], [17, 17, 13], [133]] + [[20]] * 8 + [[133, 17, 13], [17, 17, 13]],
    47: [[133, 17, 13], [17, 17, 13]],
    48: [[133, 17, 13], [17, 17, 13], [133]],
    49: [[133, 17, 13], [13], [133]],
    45: [[133, 17, 13], [13], [133]] + [[20]] * 8 + [[133, 17, 13], [13]],
    40: [[133, 17, 13], [17, 13], [13], [17, 13], [80, 65, 83, 83, 13]],
    41: [[133, 17, 13], [17, 13], [13], [17, 17, 13]],
    25: [[20]] * 12 + [[135], [135]],
    26: [[20]] * 3 + [[135], [135]],
    27: [[20]] * 6 + [[135], [135]],
    # ---- v2.3.1 ----
    # into #Test and stay there: its messages must PRINT, not count "+1"
    30: [[133, 13, 50]],
    # nodes -> companions (list stays up for the shot)
    31: [[133, 17, 13], [13]],
    # nodes -> repeaters
    32: [[133, 17, 13], [17, 13]],
    # radio config -> up twice wraps to "send advert: flood"
    33: [[133, 17, 17, 17, 13], [145, 145, 13]],
    # picker -> r: a full refresh with its status line, then the picker
    34: [[133, 13], [82]],
    # companions, out, companions again: the second must come from the
    # cache -- one GET_CONTACTS in the radio log, not two
    35: [[133, 17, 13], [13], [133], [133, 17, 13], [13]],
    # v2.3.3: let long messages arrive in Public, go to #Test, f7 back --
    # the repainted history must show every line of each message
    36: [[20], [20], [20], [20], [20], [133, 13, 50], [20], [136]],
    # f1 -> radio config -> node name -> type "c64"
    7: [[133, 17, 17, 17, 13], [145, 145, 145, 13], [67, 54, 52, 13]],
    # ---- documentation screenshots ----
    # Each of these STOPS on the screen it wants photographed. Menus and
    # panels wait for a key, and the feeder is exhausted, so the screen
    # stays up however long the run goes on. A panel does not call tkey at
    # all, so a script that ends in one cannot advance past it.
    10: [[133]],                                   # the f1 menu
    11: [[133, 13]],                               # channel picker
    12: [[133, 17, 13], [13]],                     # node list
    13: [[133, 17, 13], [13], [13]],               # what to do with a node
    14: [[133, 17, 17, 13]],                       # stats
    15: [[133, 17, 17, 17, 13]],                   # radio config
    16: [[133, 17, 17, 17, 13], [145, 145, 145, 13],
         [67, 54, 52]],                            # node name, mid-typing
    17: [[133, 17, 13], [13], [13], [17, 17, 17, 13]],  # show route
    18: [[133, 17, 17, 17, 17, 13], [13]],         # channel name prompt
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
            )


S2ORG = 0xA000
# Segment 3: read in place right after the splash logo, which is only read
# at boot. The no-expansion archive (ARCRAM, 40-byte lines from $4000)
# therefore ends where it starts.
S3ORG = EQU["LOGODAT"] + os.path.getsize(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.bin"))
# Segment 4 (s32): assembled for $6800 -- the logo's place, free once the
# splash is done -- carried in the image at $8000 and copied there by main.
S4ORG = 0x6800
S4IMG = 0x8000
S5ORG = 0x9960             # segment 5: $9960-$9AFF, 416 bytes
S5MAX = 0x9B00
SEG5 = b''
NOREU_LINES = (S4ORG - 0x4000) // 40
SRC5 = r"""
; ===== segment 5 (s43): the purge's remove phase =====
; carry set when the time at BUF+132+X is before the cutoff
pgold:  lda BUF+132,x
        cmp PGCUT
        lda BUF+133,x
        sbc PGCUT+1
        lda BUF+134,x
        sbc PGCUT+2
        lda BUF+135,x
        sbc PGCUT+3
        bcc pgo1
        clc                     ; at or after the cutoff: not old
        rts
pgo1:   sec
        rts
; the list is done: remove them, one by one
pgend:  lda #0
        sta READY
        sta PGI
pge1:   lda PGI
        cmp PGN
        bcc pge0
        jmp pgdone
pge0:
        lsr
        lsr
        lsr
        clc
        adc CBASEH
        sta PTRH
        lda PGI
        and #7
        asl
        asl
        asl
        asl
        asl
        sta PTR
        lda #15                 ; CMD_REMOVE_CONTACT
        sta TXBUF
        ldy #31
pge2:   lda (PTR),y
        sta TXBUF+1,y
        dey
        bpl pge2
        lda #33
        sta TXLEN
        jsr sendfr
        jsr pgw0
pge3:   jsr pgw
        bcs pge5                ; no answer: count it as not removed
        lda BUF
        cmp #0                  ; RESP_CODE_OK
        beq pge4
        cmp #1                  ; RESP_CODE_ERR
        beq pge6
        jsr dispat
        lda #0
        sta READY
        jmp pge3
pge4:   inc PGRM
pge6:   lda #0
        sta READY
pge5:   inc PGI
        jsr pgshow
        jmp pge1

; ===== F7: the next channel / DM with unread messages (s44) ============
; None unread: the next listed one, so F7 cycles through everything.
f7next: lda #0
        jsr f7nx
        bcs f7go
        lda #1
        jsr f7nx
        bcc f7rt
f7go:   stx CC
        lda #147                ; clear first, as the channel picker does
        jsr CHROUT
        jmp setchan
f7rt:   rts
; A = 0 unread only, 1 any listed. Carry set and X = the slot found.
f7nx:   sta F7M
        lda #48
        sta F7C
        ldx CC
        cpx #48
        bcc f7l                 ; (All = 255: start before slot 0)
        ldx #47
f7l:    inx
        cpx #48
        bcc f7c
        ldx #0
f7c:    lda F7M
        bne f7a
        lda CUNR,x
        bne f7hit
        beq f7n
f7a:    txa
        jsr slotok
        bcs f7hit
f7n:    dec F7C
        bne f7l
        clc
        rts
f7hit:  sec
        rts
; carry set when slot A is a channel with a name or a DM in use
slotok: cmp #40
        bcs sok2
        jsr chnptr
        ldy #0
        lda (PTR),y
        beq sokn
sokh:   sec
        rts
sok2:   sec
        sbc #40
        tay
        lda DMUSE,y
        bne sokh
sokn:   clc
        rts
; a session from before the DMs were saved leaves no marker: no DMs
dmfix:  lda DMMK
        cmp #$D7
        beq dmfx2
        ldx #7
        lda #0
dmfx1:  sta DMUSE,x
        dex
        bpl dmfx1
        lda #$D7
        sta DMMK
dmfx2:  rts
F7M:    .byte 0
F7C:    .byte 0
; the DM conversations with the session (57 bytes at +176 of the header)
gdmsv:  ldx #0
gdms1:  lda DMUSE,x
        sta GEOWIN+176,x
        inx
        cpx #57
        bcc gdms1
        rts
gdmld:  ldx #0
gdml1:  lda GEOWIN+176,x
        sta DMUSE,x
        inx
        cpx #57
        bcc gdml1
        jmp dmfix
rdmp:   lda #57
        sta RPN
        lda #<DMUSE
        ldx #>DMUSE
        ldy #176
        jmp rphp

"""
SRC4 = r"""
; ===== DM: stored route first, then flood (s38, mkroute.py) ============
; A DM goes out by the route the radio has. If it went DIRECT and no ack
; (0x82) arrives in about 13 s, the route is reset (CMD_RESET_PATH) and the
; same text is sent again -- now by flood -- once.
; pnrec, for a DM: keep what was sent
dmsave: ldx #0
dms1:   cpx PN_TL
        bcs dms2
        lda INASC,x
        sta DMB,x
        inx
        bne dms1
dms2:   stx DMRL
        ldx #5
dms3:   lda DMKEY,x
        sta DMKC,x
        dex
        bpl dms3
        lda #0
        sta DMTRY
        lda #1
        sta DMFL                ; until the radio says it went direct
        rts
; main loop: is a direct DM overdue?
dmwd:   lda PN_ST+1
        cmp #1                  ; sent, not acknowledged
        bne dmw9
        lda DMFL
        bne dmw9                ; it flooded already: nothing better to try
        lda DMTRY
        bne dmw9                ; tried once
        lda UIMODE
        bne dmw9                ; not while a menu is up
        lda $A1
        sec
        sbc DMT
        cmp #3                  ; about 13 s
        bcs dmw1
dmw9:   rts
dmw1:   inc DMTRY
; the contact with that key prefix: its full key for CMD_RESET_PATH
        lda #0
        sta DMI2
dmf1:   lda DMI2
        cmp NCONT
        bcs dmrs                ; not in the table: just resend
        jsr contptr
        ldy #26
        ldx #0
dmf2:   lda (PTR),y
        cmp DMKC,x
        bne dmf3
        iny
        inx
        cpx #6
        bcc dmf2
        lda #13                 ; CMD_RESET_PATH
        sta TXBUF
        ldy #26
        ldx #0
dmf4:   lda (PTR),y
        sta TXBUF+1,x
        iny
        inx
        cpx #32
        bcc dmf4
        ldy #58                 ; and forget it here
        lda #255
        sta (PTR),y
        lda #33
        sta TXLEN
        jsr sendfr
        jmp dmrs
dmf3:   inc DMI2
        jmp dmf1
; the same text again: [2][plain][attempt 1][time][key prefix][text]
dmrs:   lda #2
        sta TXBUF
        lda #0
        sta TXBUF+1
        lda #1
        sta TXBUF+2
        jsr tsput
        ldx #5
dmr1:   lda DMKC,x
        sta TXBUF+7,x
        dex
        bpl dmr1
        ldx #0
dmr2:   cpx DMRL
        bcs dmr3
        lda DMB,x
        sta TXBUF+13,x
        inx
        bne dmr2
dmr3:   txa
        clc
        adc #13
        sta TXLEN
        jsr sendfr
        lda #1                  ; its new ack tag comes with the sent reply
        sta PN_AW
        lda $A1
        sta PN_AG+1
        sta DMT
        lda #<tdmfl
        sta SPL
        lda #>tdmfl
        sta SPH
        jmp notice
tdmfl:  .text "no ack - resent by flood"
        .byte 0
DMRL:   .byte 0
DMTRY:  .byte 1
DMFL:   .byte 1
DMT:    .byte 0
DMI2:   .byte 0
DMKC:   .byte 0,0,0,0,0,0
DMB:    .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
        .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
        .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
        .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
        .byte 0,0,0,0,0,0,0,0


; ===== F3: 80 <-> 40 columns (s34, mkf3.py) =============================
kf3:    lda KWOK                ; only with a Kawari
        bne kf31
        rts
kf31:   jmp mmcol               ; the F1 menu's switch, either way
; the key line: with an F3 entry when there is a Kawari
kkeys:  lda #<skeys2
        ldx #>skeys2
        ldy KWOK
        beq kk1
        lda #<skeys3
        ldx #>skeys3
kk1:    sta PTR
        stx PTRH
        rts
skeys3: .byte 5
        .text "f1"
        .byte 154
        .text " menu  "
        .byte 5
        .text "f3"
        .byte 154
        .text " 40/80  "
        .byte 5
        .text "f5"
        .byte 154
        .text " scroll  "
        .byte 5
        .text "f7"
        .byte 154
        .text " new"
        .byte 13,0

; ===== menus on the 80 column screen (s33, mkmir.py) ===================
; In 80 column mode the menus, lists and panels still draw on the 40
; column screen ($0400/$D800) -- all their code works in 40 column
; coordinates -- but the display no longer switches to it: about ten
; times a second (from poll) the 40 x 25 screen is copied, centred, onto
; the 80 column screen. Registers kept; no zero page used.
kmir:   lda K40
        bne kmi0
        rts
kmi0:   lda JIFFY
        sec
        sbc KMT
        cmp #6
        bcs kmi1
        rts
kmi1:   lda JIFFY
        sta KMT
        txa
        pha
        tya
        pha
        ldx #0
kmr1:   stx KMR
        lda rowlo,x             ; this row's screen and colour addresses
        sta kms+1
        sta kmc+1
        lda rowhi,x
        sta kms+2
        clc
        adc #$D4
        sta kmc+2
        lda KMR
        ldx #$10
        ldy #20                 ; centred: columns 20-59
        jsr kaddr
        ldy #0
kms:    lda $FFFF,y
        sta $D03B
        iny
        cpy #40
        bcc kms
        lda KMR
        ldx #$18
        ldy #20
        jsr kaddr
        ldy #0
kmc:    lda $FFFF,y
        and #15
        ora #$80
        sta $D03B
        iny
        cpy #40
        bcc kmc
        ldx KMR
        inx
        cpx #25
        bcc kmr1
        pla
        tay
        pla
        tax
        rts
KMT:    .byte 0
KMR:    .byte 0


; ===== segment 4 (s32, mkui.py) ========================================
; Assembled at $6800, carried in the program image at $8000 and copied
; into place right after the splash (the logo there is only read by it).

; ---- F1 menus: a reminder of the keys, under the frame ----
mnhint: lda MNY
        clc
        adc MNN
        adc #3
        cmp #25
        bcs mnh9
        sta MNROW
        lda MNX
        pha
        lda #0
        sta MNX
        jsr scrpos
        lda #12                 ; grey
        sta MNCLR
        lda #<tmnh
        sta SPL
        lda #>tmnh
        sta SPH
        lda #0
        sta MNCOL
        jsr mnstr
        pla
        sta MNX
mnh9:   rts

; ---- the clock at boot: two lines instead of five ----
;   time     2026/10/12 03:49:39 utc
;            ultimate utc-05:00 - in sync
ucset4: lda TSOK
        bne uc41
        rts
uc41:   lda #1
        sta CKBOOT
        sta CKQ                 ; ckrep / ucoffln work, but print nothing
        lda #255
        sta CKV
        lda #0
        sta UC4S                ; 0 no ultimate, 1 offset known, 2 not yet
        lda UCOK
        cmp #2
        bne uc4p
        jsr ucget
        lda UCOK
        cmp #2
        bne uc4p
        inc UC4S
        lda UTCOFF
        cmp #$80
        beq uc4u
        jsr ucnow               ; compare, and set the radio if behind
        jmp uc4p
uc4u:   inc UC4S
uc4p:   lda #155                ; line 1: the radio's time (after any set)
        jsr CHROUT
        lda #<stime4
        sta PTR
        lda #>stime4
        sta PTRH
        jsr prtstr
        lda #5
        jsr CHROUT
        ldx #3
uc4c:   lda NOWTS,x
        sta UCAC,x
        dex
        bpl uc4c
        lda #<snull4
        ldx #>snull4
        jsr tsline
        jsr uc4ts
        lda UC4S
        beq uc49
        lda #155                ; line 2: the ultimate and what was done
        jsr CHROUT
        lda #<sult4
        sta PTR
        lda #>sult4
        sta PTRH
        jsr prtstr
        lda UC4S
        cmp #2
        beq uc4n
        jsr ucoffln             ; TSTR = "ultimate clock is utc-05:00"
        lda #$D2                ; TSTR+18 ($9FC0+18): "utc-05:00"
        sta PTR
        lda #$9F
        sta PTRH
        jsr prtstr
        lda CKV
        cmp #3
        bcs uc4e
        lda #<svin4
        ldx #>svin4
        ldy CKV
        beq uc4v
        lda #<svset4
        ldx #>svset4
        dey
        beq uc4v
        lda #<svah4
        ldx #>svah4
uc4v:   sta PTR
        stx PTRH
        jsr prtstr
        jmp uc4e
uc4n:   lda #<soffn4
        sta PTR
        lda #>soffn4
        sta PTRH
        jsr prtstr
uc4e:   lda #13
        jsr CHROUT
uc49:   lda #0
        sta CKQ
        rts
uc4ts:  lda #<TSTR
        sta PTR
        lda #>TSTR
        sta PTRH
        jsr prtstr
        lda #13
        jmp CHROUT

; ---- F1 > Stats (s36: video, the Ultimate clock, 16-bit frames) ----
stat4:  lda #20                 ; CMD_GET_BATT_AND_STORAGE
        sta TXBUF
        lda #1
        sta TXLEN
        jsr sendfr
        lda #0
        sta STGBIT
        lda #12                 ; RESP_CODE_BATT_AND_STORAGE
        jsr waitop
        jsr plinit
        lda #<sbat4             ; battery mV
        ldx #>sbat4
        jsr stl
        lda BUF+1
        ldx BUF+2
        jsr stnum
        lda #<smv4
        ldx #>smv4
        jsr stend
        lda #<ssto4             ; storage KB
        ldx #>ssto4
        jsr stl
        lda BUF+3
        ldx BUF+4
        jsr stnum
        lda #<skb4
        ldx #>skb4
        jsr stend
        lda #<supt4             ; uptime from the jiffy clock
        ldx #>supt4
        jsr stl
        sei
        lda $A2
        sta UCAC
        lda $A1
        sta UCAC+1
        lda $A0
        sta UCAC+2
        cli
        lda #0
        sta UCAC+3
        lda #$10                ; / 3600: minutes
        ldx #$0E
        ldy #0
        jsr ucdiv
        lda #60
        ldx #0
        ldy #0
        jsr ucdiv               ; hours, minutes left in UCR
        lda UCAC
        ldx UCAC+1
        jsr stnum
        lda #<sh4
        ldx #>sh4
        jsr stcat
        lda UCR
        ldx #0
        jsr stnum
        lda #<sm4
        ldx #>sm4
        jsr stend
        lda #<svid5             ; video standard
        ldx #>svid5
        jsr stl
        lda #<sntsc5
        ldx #>sntsc5
        ldy ISNTSC
        bne stv1
        lda #<spal5
        ldx #>spal5
stv1:   jsr stend
        lda #<sclk5             ; the Ultimate's clock, read now
        ldx #>sclk5
        jsr stl
        jsr ucget
        lda UCOK
        cmp #2
        beq stc1
        lda #<snortc5
        ldx #>snortc5
        jsr stend
        jmp stc2
stc1:   lda #0                  ; "yyyy/mm/dd hh:mm" -- 16 characters
        sta UCSTR+16
        lda #<UCSTR
        ldx #>UCSTR
        jsr stend
stc2:   jsr stoff
        lda #<smsg4             ; messages in / out
        ldx #>smsg4
        jsr stl
        lda MSGS
        ldx MSGSH
        jsr stnum
        lda #<sin4
        ldx #>sin4
        jsr stcat
        lda PN_SN
        ldx PN_SN+1
        jsr stnum
        lda #<sout4
        ldx #>sout4
        jsr stend
        jsr stlast
        lda #<snod4             ; nodes in the table
        ldx #>snod4
        jsr stl
        lda NCONT
        ldx #0
        jsr stnum
        lda #<sof6
        ldx #>sof6
        jsr stcat
        lda MAXCON
        ldx #0
        jsr stnum
        jsr plend
        lda #<slnk4             ; link speed, receive buffer peak
        ldx #>slnk4
        jsr stl
        lda BAUDV
        ldx BAUDV+1
        jsr stnum
        lda #<sbaud5
        ldx #>sbaud5
        jsr stcat
        lda OVR
        ldx #0
        jsr stnum
        jsr plend
        lda #<sfr4              ; frames received, errors (total)
        ldx #>sfr4
        jsr stl
        lda NFRM
        ldx NFRMH
        jsr stnum
        lda #<serr5
        ldx #>serr5
        jsr stcat
        lda RJ
        clc
        adc UNK
        sta KT5
        lda #0
        adc #0
        sta KT6
        lda KT5
        clc
        adc PBAD
        sta KT5
        bcc ste1
        inc KT6
ste1:   lda KT5
        clc
        adc FRERR
        sta KT5
        bcc ste2
        inc KT6
ste2:   lda KT5
        ldx KT6
        jsr stnum
        jsr plend
        lda #<smem4             ; expansion memory, and how full the history is
        ldx #>smem4
        jsr stl
        lda #<snon6
        ldx #>snon6
        ldy RU
        beq stm2
        lda #<sreu6
        ldx #>sreu6
        cpy #2
        bne stm1
        lda #<sgeo6
        ldx #>sgeo6
stm1:   jsr stcat
        lda UKL
        ldx UKH
        jsr stnum
        lda #<sk6
        ldx #>sk6
stm2:   jsr stcat
; lines stored: the fill counts of the regions in use (all nine with an
; REU / GeoRAM, the merged one -- region 8 -- in main RAM)
        lda #0
        sta UCAC
        sta UCAC+1
        sta UCAC+2
        sta UCAC+3
        sta KT5                 ; room: regions x MAXL, 24-bit in KT5..KT7
        sta KT6
        sta KT7
        ldx #0
        lda RU
        bne sth1
        ldx #8
sth1:   lda UCAC
        clc
        adc LFL,x
        sta UCAC
        lda UCAC+1
        adc LFH,x
        sta UCAC+1
        lda KT5
        clc
        adc MAXL
        sta KT5
        lda KT6
        adc MAXH
        sta KT6
        bcc sth2
        inc KT7
sth2:   inx
        cpx #9
        bcc sth1
        lda #100                ; percent: used * 100 / room
        ldx #0
        jsr ucmul
        lda KT5
        ldx KT6
        ldy KT7
        bne sth3
        cpx #0
        bne sth3
        cmp #0
        beq sth4                ; no room at all: say 0
sth3:   jsr ucdiv
sth4:   lda UCAC
        ldx #0
        jsr stnum
        lda #<sfull6
        ldx #>sfull6
        jsr stend
stm3:   lda #<tstats
        sta MNTIT
        lda #>tstats
        sta MNTITH
        jsr plshow
        jmp mmshut
svid5:  .text "Video     "
        .byte 0
sntsc5: .text "NTSC"
        .byte 0
spal5:  .text "PAL"
        .byte 0
sclk5:  .text "Clock     "
        .byte 0
snortc5: .text "no RTC"
        .byte 0
sbaud5: .text " baud, peak "
        .byte 0
serr5:  .text ", errors "
        .byte 0
NFRMH:  .byte 0
; ----- purge old nodes, second half (s39): segment 4 -----
pgdone: lda #0
        sta SCBUSY
        jsr gsvk                ; the emptied node table, saved
        lda SYNCP
        beq pgd1
        lda #0
        sta SYNCP
        jsr sync
pgd1:   jsr plinit
        lda #<tpg2              ; "Checked n nodes"
        ldx #>tpg2
        jsr stl
        lda PGCH
        ldx PGCH+1
        jsr stnum
        jsr plend
        lda #<tpg3              ; "Removed n"
        ldx #>tpg3
        jsr stl
        lda PGRM
        ldx #0
        jsr stnum
        lda #<tpg4              ; " of n old ones"
        ldx #>tpg4
        jsr stcat
        lda PGN
        ldx #0
        jsr stnum
        jsr plend
        lda #<tpg5              ; "Older than n days"
        ldx #>tpg5
        jsr stl
        lda PGD
        ldx PGD+1
        jsr stnum
        lda #<tpg6
        ldx #>tpg6
        jsr stend
        lda #<tpg7              ; favourites kept
        ldx #>tpg7
        jsr stl
        jsr plend
        lda #<tradio
        sta MNTIT
        lda #>tradio
        sta MNTITH
        jsr plshow
        jmp mmshut
; "checked n  old n  removed n", in place
pgshow: jsr s2up
        lda #<s2chk
        sta SPL
        lda #>s2chk
        sta SPH
        jsr s2str
        lda PGCH
        sta NUML
        lda PGCH+1
        sta NUMH
        jsr prdec
        lda #<tpgo
        sta SPL
        lda #>tpgo
        sta SPH
        jsr s2str
        lda PGN
        jsr s2dec
        lda #<tpgr
        sta SPL
        lda #>tpgr
        sta SPH
        jsr s2str
        lda PGRM
        jsr s2dec
        lda #13                 ; the counts only grow: no padding needed
        jmp CHROUT
; wait for a frame: carry set after about 13 s of silence
pgw0:   lda #0
        sta PGT
        lda JIFFY
        sta PGJ
        rts
pgw:    jsr poll
        lda READY
        bne pgw2
        lda JIFFY
        cmp PGJ
        sta PGJ
        bcs pgw
        inc PGT                 ; the jiffy byte wrapped: 4.3 s more
        lda PGT
        cmp #3
        bcc pgw
        sec
        rts
pgw2:   jsr pgw0
        clc
        rts
srpurge: .text "Purge old nodes..."
        .byte 0
tpgq:   .text " Remove nodes older than (days) "
        .byte 0
tpg1:   .text "checking the radio's nodes..."
        .byte 0
tpgo:   .text "  old "
        .byte 0
tpgr:   .text "  removed "
        .byte 0
tpg2:   .text "Checked   "
        .byte 0
tpg3:   .text "Removed   "
        .byte 0
tpg4:   .text " of "
        .byte 0
tpg5:   .text "Older than "
        .byte 0
tpg6:   .text " days"
        .byte 0
tpg7:   .text "Favourites kept"
        .byte 0
PGD:    .byte 0,0
PGCUT:  .byte 0,0,0,0
PGN:    .byte 0
PGI:    .byte 0
PGCH:   .byte 0,0
PGRM:   .byte 0
PGT:    .byte 0
PGJ:    .byte 0
PGMAX:  .byte 0
KT7:    .byte 0
sof6:   .text " of "
        .byte 0
snon6:  .text "main RAM "
        .byte 0
sreu6:  .text "REU "
        .byte 0
sgeo6:  .text "Geo "
        .byte 0
sk6:    .text "K "
        .byte 0
sfull6: .text "% full"
        .byte 0
; a new panel line starting with the label at A/X
stl:    sta SPL                 ; (plnew does not touch SPL/SPH)
        stx SPH
        jsr plnew
        jmp plstr
stcat:  sta SPL
        stx SPH
        jmp plstr
; the string at A/X, then end the line
stend:  jsr stcat
        jmp plend
; A (low) X (high) as decimal
stnum:  sta NUML
        stx NUMH
        lda #0
        sta NUM2
        sta NUM3
        jmp pldec

tmnh:   .text " Up/down choose  RETURN open  F1 back   "
        .byte 0
stime4: .text "time     "
        .byte 0
sult4:  .text "         ultimate "
        .byte 0
soffn4: .text "offset - learning from mesh"
snull4: .byte 0
svin4:  .text " - in sync"
        .byte 0
svset4: .text " - radio set"
        .byte 0
svah4:  .text " - radio ahead"
        .byte 0
sbat4:  .text "Battery   "
        .byte 0
smv4:   .text " mV"
        .byte 0
ssto4:  .text "Storage   "
        .byte 0
skb4:   .text " KB"
        .byte 0
supt4:  .text "Uptime    "
        .byte 0
sh4:    .text "h "
        .byte 0
sm4:    .text "m"
        .byte 0
smsg4:  .text "Messages  "
        .byte 0
sin4:   .text " in, "
        .byte 0
sout4:  .text " out"
        .byte 0
snod4:  .text "Nodes     "
        .byte 0
slnk4:  .text "Link      "
        .byte 0
sfr4:   .text "Frames    "
        .byte 0
smem4:  .text "Memory    "
        .byte 0
BAUDV:  .byte 0,0
CKQ:    .byte 0
CKV:    .byte 255
UC4S:   .byte 0
"""
EQU["NOREU_LINES"] = NOREU_LINES

SRC3 = r"""
; ===== start screen strings (s31, mkboot2.py) ==========================
stitle: .text " meshcore 64"
        .byte 0
smem:   .text "memory   "
        .byte 0
sdisp:  .text "display  "
        .byte 0
sreu2:  .text "reu "
        .byte 0
sgeo2:  .text "georam "
        .byte 0
snone2: .text "none"
        .byte 0
sd80:   .text "kawari - 80 columns"
        .byte 0
sd40k:  .text "kawari - 40 columns (f1 for 80)"
        .byte 0
sd40:   .text "40 columns"
        .byte 0
skeys2: .byte 5
        .text "f1"
        .byte 154
        .text " menu  "
        .byte 5
        .text "f5"
        .byte 154
        .text " scroll back  "
        .byte 5
        .text "f7"
        .byte 154
        .text " new msgs"
        .byte 13,0


; ===== F1: 80 columns again (s30, mkcol80.py) ==========================
; Listed in 40 columns only when a Kawari answered at boot (KWOK).
mmsel2: lda K80
        bne mmsel               ; 80 on: "40 column mode"
        lda KWOK
        beq mmsel               ; no Kawari: the usual six
        lda #7
        sta MNN
        lda #<mtab40
        sta MNPTR
        lda #>mtab40
        sta MNPTRH
        rts
; menu item 5: the column switch, either way
mmcol:  lda K80
        beq mmc1
        jmp k40off
mmc1:   lda KWOK
        beq mmc2
        jsr k80on
mmc2:   jmp mmshut              ; clear and repaint the chat
mtab40: .word mi0,mi1,mi2,mi3,mi4,mi80,mi5
mi80:   .text "80 column mode"
        .byte 0
KWOK:   .byte 0


; ===== F1: back to 40 columns (s29, mkcol40.py) ========================
; The main menu lists "40 column mode" (above "close") only while the 80
; column chat is on.
mmsel:  lda K80
        bne mms80
        lda #6
        sta MNN
        lda #<mtab
        sta MNPTR
        lda #>mtab
        sta MNPTRH
        rts
mms80:  lda #7
        sta MNN
        lda #<mtab80
        sta MNPTR
        lda #>mtab80
        sta MNPTRH
        rts
; switch the 80 column chat off and repaint it in 40
k40off: lda KOLDV               ; CHROUT back to the KERNAL
        sta $0326
        lda KOLDV+1
        sta $0327
        lda #0
        sta K80
        sta K40
        lda #39
        sta KSEPW
        lda #40
        sta KWID
        lda $D037
        and #239
        sta $D037
        jmp mmshut              ; clear and repaint the chat (40 columns)
mtab80: .word mi0,mi1,mi2,mi3,mi4,mi40,mi5
mi40:   .text "40 column mode"
        .byte 0


; ===== history pages in 80 columns (s28, mkflow.py) ====================
; appage paints the archive's 40 column rows onto the 40 column screen as
; always; k80typ notes what each row is (before apcol clears the marker),
; and at the end k80flow lays them onto the 80 column screen: a message's
; rows side by side in pairs -- row 1 | row 2, row 3 | row 4 -- which is
; exactly where an 80 column screen would have wrapped them; a rule is
; stretched across. The page sits at the bottom, under what is left.
; KTYP: 0 = a message's first row, 1 = a continuation, 2 = a rule
k80typ: lda K80
        beq kfrt
        lda K40
        bne kfrt
        lda TMP
        clc
        adc CNT
        tax
        ldy #0
        lda (PTR),y
        cmp #64
        bne kty1
        iny
        lda (PTR),y
        cmp #64
        bne kty1
        lda #2
        bne kty3
kty1:   ldy #39
        lda (PTR),y
        bmi kty2
        lda #1
        bne kty3
kty2:   lda #0
kty3:   sta KTYP,x
kfrt:   rts

k80flow: lda K80
        beq kfrt
        lda K40
        bne kfrt
; pair the rows TMP..23 into lines (KLR left row, KRR right row or 255)
        lda #0
        sta KM
        ldx TMP
kfl1:   cpx #24
        bcs kfl4
        lda KTYP,x
        cmp #1
        bne kfnew               ; a first row or a rule: a new line
        ldy KM
        beq kfnew
        dey
        lda KRR,y
        cmp #255
        bne kfnew               ; that line is full
        lda KLR,y
        sty KT6
        tay
        lda KTYP,y
        ldy KT6
        cmp #2
        beq kfnew               ; never beside a rule
        txa
        sta KRR,y
        jmp kfl3
kfnew:  ldy KM
        txa
        sta KLR,y
        lda KTYP,x
        cmp #2
        bne kfn1
        txa                     ; a rule: the same row both halves
        jmp kfn2
kfn1:   lda #255
kfn2:   sta KRR,y
        inc KM
kfl3:   inx
        jmp kfl1
; blank TMP .. 23-M, then the lines at 24-M .. 23
kfl4:   lda #24
        sec
        sbc KM
        sta KT5                 ; first row of the page on the 80 screen
        lda TMP
        sta KT6
kfb1:   lda KT6
        cmp KT5
        bcs kfb3
        ldx #$10
        ldy #0
        jsr kaddr
        lda #32
        ldy #80
kfb2:   sta $D03B
        dey
        bne kfb2
        inc KT6
        jmp kfb1
kfb3:   ldx #0
        stx KFI
kfo1:   ldx KFI
        cpx KM
        bcs kfrt
        lda KLR,x
        jsr kfsrc               ; PTR / PTR2 = that 40 column row
        lda KT5
        clc
        adc KFI
        sta KFR
        ldx #$10
        ldy #0
        jsr kaddr
        ldy #0
kfo2:   lda (PTR),y
        sta $D03B
        iny
        cpy #40
        bcc kfo2
        lda KFR
        ldx #$18
        ldy #0
        jsr kaddr
        ldy #0
kfo3:   lda (PTR2),y
        and #15
        ora #$80
        sta $D03B
        iny
        cpy #40
        bcc kfo3
; right half: the paired row, or blank
        lda KFR
        ldx #$10
        ldy #40
        jsr kaddr
        ldx KFI
        lda KRR,x
        cmp #255
        beq kfo6
        jsr kfsrc
        ldy #0
kfo4:   lda (PTR),y
        sta $D03B
        iny
        cpy #40
        bcc kfo4
        lda KFR
        ldx #$18
        ldy #40
        jsr kaddr
        ldy #0
kfo5:   lda (PTR2),y
        and #15
        ora #$80
        sta $D03B
        iny
        cpy #40
        bcc kfo5
        inc KFI
        jmp kfo1
kfo6:   lda #32
        ldy #40
kfo7:   sta $D03B
        dey
        bne kfo7
        lda KFR
        ldx #$18
        ldy #40
        jsr kaddr
        lda #$85
        ldy #40
kfo8:   sta $D03B
        dey
        bne kfo8
        inc KFI
        jmp kfo1
; PTR = $0400 + A*40, PTR2 = its colours
kfsrc:  jsr pnrowp
        lda PTR
        sta PTR2
        lda PTRH
        clc
        adc #212
        sta PTR2H
        rts

KTYP:   .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
KLR:    .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
KRR:    .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
KM:     .byte 0
KFI:    .byte 0
KFR:    .byte 0


; ===== VIC-II Kawari: 80 column chat (s27, mk80.py) ====================
; Reference: vicii-kawari doc/REGISTERS.md and disks/util/80col. "VIC2"
; into $D03F unlocks the extra registers. Video RAM through port A
; ($D039/$D03A address, $D035 index, $D03B data, $D03F=1 auto-increment);
; DMA: port 1 ($D039/$D03A) = destination, port 2 ($D03C/$D03D) = source,
; $D035/$D036 = count, $D03F=15, $D03B = 1 copy / 4 fill (fill byte in
; $D03C); done when the count reads 0. Font at $0000, screen $1000, colour
; $1800 ($D038 = 50); bit 4 of $D037 = 80 columns. Colour byte: bits 0-3
; colour, bit 6 reverse, bit 7 the second (lower case) character set.
;
; While the chat is showing, CHROUT ($0326) comes here and draws on the
; 80 column screen. A menu, list or panel draws on the ordinary 40 column
; screen (scrpos switches to it); going back to the chat (arcpage) switches
; back. History pages are the archive's 40 column lines, on the left.

kwboot: lda #155                ; grey
        jsr CHROUT
        jsr kwdet
        bcc kwyes
        rts                     ; no Kawari: the display line says so
kwyes:  lda #1
        sta KWOK                ; F1 can switch to 80 columns later
        lda #<tkwyes
        ldx #>tkwyes
        jsr kwln
        lda #<tkwsw
        ldx #>tkwsw
        jsr kwln
        lda #<tkwak
        ldx #>tkwak
        jsr kwln
        lda #180                ; about 3 s, any key cancels
        jsr kwwait
        bcc kwgo
        rts
kwgo:   jmp k80on

; carry clear = a Kawari answered: after the unlock a port register reads
; back what was written (an ordinary VIC-II returns $FF up there)
kwdet:  lda #86
        sta $D03F
        lda #73
        sta $D03F
        lda #67
        sta $D03F
        lda #50
        sta $D03F
        lda #$55
        sta $D039
        lda $D039
        cmp #$55
        bne kwdn
        lda #$AA
        sta $D039
        lda $D039
        cmp #$AA
        bne kwdn
        clc
        rts
kwdn:   sec
        rts

; wait A jiffies; carry set = a key was pressed (and eaten)
kwwait: sta KWN
        lda JIFFY
        sta KWT
kww1:   jsr GETIN
        bne kwwk
        lda JIFFY
        sec
        sbc KWT
        cmp KWN
        bcc kww1
        clc
        rts
kwwk:   sec
        rts

kwln:   sta PTR
        stx PTRH
        jsr prtstr
        lda #13
        jmp CHROUT

; ---- port A = video RAM (X = $10 screen / $18 colour) + A*80 + Y ----
kaddr:  stx KBH
        sty KT4
        sta KT0
        lda #0
        sta KT1
        lda KT0
        asl
        rol KT1
        asl
        rol KT1
        asl
        rol KT1
        asl
        rol KT1                 ; KT1:A = row * 16
        sta KT2
        lda KT1
        sta KT3
        lda KT2
        asl
        rol KT1
        asl
        rol KT1                 ; KT1:A = row * 64
        clc
        adc KT2
        sta KT2
        lda KT1
        adc KT3
        sta KT3                 ; KT3:KT2 = row * 80
        lda KT2
        clc
        adc KT4
        sta $D039
        lda KT3
        adc KBH
        sta $D03A
        lda #0
        sta $D035
        lda #1
        sta $D03F
        rts

; DMA: KDL/KDH destination, KSL/KSH source, KNL/KNH count; A = function
; (1 copy, 4 fill with KFB)
kdma:   pha
        lda KDL
        sta $D039
        lda KDH
        sta $D03A
        lda KSL
        sta $D03C
        lda KSH
        sta $D03D
        pla
        pha
        cmp #4
        bne kdm1
        lda KFB                 ; a fill: port 2 low is the byte
        sta $D03C
kdm1:   lda #15
        sta $D03F
        lda KNL
        sta $D035
        lda KNH
        sta $D036
        pla
        sta $D03B
kdm2:   lda $D035
        ora $D036
        bne kdm2
        lda #1
        sta $D03F
        rts
; fill KNH:KNL bytes from A(hi):0 + X(lo) with Y
kfill:  sta KDH
        stx KDL
        sty KFB
        lda #4
        jmp kdma

; ---- switch on (boot): font, the 40 column screen carried over, hook ----
k80on:  lda #$7F                ; no serial NMI while the I/O is banked out
        sta C2ICR
        sei
        lda #0
        tay
        ldx #0
        jsr kaddr               ; video RAM $0000 (X=0: base 0)
        lda #0
        sta $D03A
        sta $D039
        lda #0
        sta PTR
        lda #$D0
        sta PTRH
        ldy #0
        ldx #16
kon1:   lda #$33                ; character ROM visible at $D000
        sta 1
        lda (PTR),y
        pha
        lda #$36                ; I/O back (BASIC stays out)
        sta 1
        pla
        sta $D03B
        iny
        bne kon1
        inc PTRH
        dex
        bne kon1
        cli
        lda NMIEN
        ora #$80
        sta C2ICR
; the boot text so far, on the left of each 80 column row
        lda #0
        sta KT5
        lda #0
        sta PTR
        lda #4
        sta PTRH
kon2:   lda KT5
        ldx #$10
        ldy #0
        jsr kaddr
        ldy #0
kon3:   lda (PTR),y
        sta $D03B
        iny
        cpy #40
        bcc kon3
        lda #32
kon4:   sta $D03B
        iny
        cpy #80
        bcc kon4
        lda KT5
        ldx #$18
        ldy #0
        jsr kaddr
        lda PTRH
        clc
        adc #212
        sta PTR2H
        lda PTR
        sta PTR2
        ldy #0
kon5:   lda (PTR2),y
        and #15
        ora #$80
        sta $D03B
        iny
        cpy #40
        bcc kon5
        lda #$85
kon6:   sta $D03B
        iny
        cpy #80
        bcc kon6
        lda PTR
        clc
        adc #40
        sta PTR
        bcc kon7
        inc PTRH
kon7:   inc KT5
        lda KT5
        cmp #25
        bcc kon2
        lda 214                 ; carry on where the 40 column cursor is
        sta KROW
        lda #0
        sta KCOL
        sta KRVS
        sta K40
        lda TXTCOL
        and #15
        sta KCLR
        lda #79
        sta KSEPW
        lda #80
        sta KWID
        lda $0326               ; CHROUT comes to us from now on
        sta KOLDV
        lda $0327
        sta KOLDV+1
        lda #<k80out
        sta $0326
        lda #>k80out
        sta $0327
        lda #16                 ; 80 columns, font at $0000
        sta $D037
        lda #50                 ; screen $1000, colour $1800
        sta $D038
        lda #1
        sta K80
        rts

; ---- CHROUT ----
k80out: pha
        lda K80
        beq kold
        lda K40
        bne kold
        lda $9A                 ; output device: the screen only
        cmp #3
        bne kold
        pla
        sta KCH
        stx KSX
        sty KSY
        jsr k80chr
        ldx KSX
        ldy KSY
        lda KCH
        clc
        rts
kold:   pla
        jmp (KOLDV)

k80chr: cmp #13
        beq kcr
        cmp #141
        beq kcr
        cmp #147
        beq kclr
        cmp #157
        beq kleft
        cmp #20
        beq kdel
        cmp #29
        beq kright
        cmp #19
        beq khome
        cmp #145
        beq kup
        cmp #17
        beq kdown
        cmp #18
        beq krvon
        cmp #146
        beq krvof
        ldx #15
kcc:    cmp kcodes,x            ; a colour code?
        beq kccol
        dex
        bpl kcc
        cmp #32                 ; petscii -> screen code, as the KERNAL
        bcc krt
        cmp #64
        bcc kput
        cmp #96
        bcc kc64
        cmp #128
        bcc kc32
        cmp #160
        bcc krt
        cmp #192
        bcc kc64
        cmp #255
        beq kc255
        sec
        sbc #128
        jmp kput
kc255:  lda #94
        jmp kput
kc64:   sec
        sbc #64
        jmp kput
kc32:   sec
        sbc #32
        jmp kput
kccol:  stx KCLR
krt:    rts
krvon:  lda #$40
        sta KRVS
        rts
krvof:  lda #0
        sta KRVS
        rts
khome:  lda #0
        sta KROW
        sta KCOL
        rts
kright: inc KCOL
        lda KCOL
        cmp #80
        bcc krt
        jmp knl
kleft:  lda KCOL
        beq kl1
        dec KCOL
        rts
kl1:    lda KROW
        beq krt
        dec KROW
        lda #79
        sta KCOL
        rts
kup:    lda KROW
        beq krt
        dec KROW
        rts
kdown:  inc KROW
        lda KROW
        cmp #25
        bcc krt
        lda #24
        sta KROW
        jmp kscrl
kdel:   jsr kleft
        lda #32
        jsr kcell
        rts
kcr:    lda #0
        sta KRVS
knl:    lda #0
        sta KCOL
        inc KROW
        lda KROW
        cmp #25
        bcc krt
        lda #24
        sta KROW
        jmp kscrl
; a character at the cursor, then move on (wrapping when the row is full)
kput:   ldx KCOL
        cpx #80
        bcc kput1
        pha
        jsr knl
        pla
kput1:  jsr kcell
        inc KCOL
        rts
; screen code A and the current colour at the cursor, cursor unchanged
kcell:  sta KSC
        lda KROW
        ldx #$10
        ldy KCOL
        jsr kaddr
        lda KSC
        sta $D03B
        lda KROW
        ldx #$18
        ldy KCOL
        jsr kaddr
        lda KCLR
        ora #$80
        ora KRVS
        sta $D03B
        rts
kclr:   lda #0
        sta KROW
        sta KCOL
        lda #<2000
        sta KNL
        lda #>2000
        sta KNH
        lda #$10
        ldx #0
        ldy #32
        jsr kfill
        lda #<2000
        sta KNL
        lda #>2000
        sta KNH
        lda KCLR
        ora #$80
        tay
        lda #$18
        ldx #0
        jmp kfill
; rows 1-24 up one, row 24 blank
kscrl:  lda #<1920
        sta KNL
        lda #>1920
        sta KNH
        lda #$00
        sta KDL
        lda #$10
        sta KDH
        lda #$50
        sta KSL
        lda #$10
        sta KSH
        lda #1
        jsr kdma
        lda #<1920
        sta KNL
        lda #>1920
        sta KNH
        lda #$00
        sta KDL
        lda #$18
        sta KDH
        lda #$50
        sta KSL
        lda #$18
        sta KSH
        lda #1
        jsr kdma
        lda #80
        sta KNL
        lda #0
        sta KNH
        lda #$17
        ldx #$80
        ldy #32
        jsr kfill
        lda #80
        sta KNL
        lda #0
        sta KNH
        lda KCLR
        ora #$80
        tay
        lda #$1F
        ldx #$80
        jmp kfill

; ---- the 40 column screen for a menu / back to the chat ----
k40m:   lda K80
        beq kmrt
        lda K40
        bne kmrt
        lda #1
        sta K40
        lda #0                  ; a clean 40 column screen under the menu
        sta PTR
        lda #4
        sta PTRH
        ldx #4
        ldy #0
        lda #32
km1:    sta (PTR),y
        iny
        bne km1
        inc PTRH
        dex
        bne km1
        lda #147                ; the 80 column screen stays on: blank it,
        jsr k80chr              ; the menu is copied onto it (kmir)
        lda JIFFY
        sec
        sbc #6
        sta KMT                 ; and copy straight away
kmrt:   rts
k80c:   lda K80
        beq kmrt
        lda K40
        beq kmrt
        lda #0
        sta K40
        lda #147                ; through k80chr: a clean 80 column screen
        jsr k80chr
        lda $D037
        ora #16
        sta $D037
        rts

; ----- Stats: time since the last message (s41) -----
stlast: lda #<slast
        ldx #>slast
        jsr stl
        lda LRXOK
        bne stl1
        lda #<snoyet
        ldx #>snoyet
        jmp stend
stl1:   sei
        lda $A2
        sec
        sbc LRX
        sta UCAC
        lda $A1
        sbc LRX+1
        sta UCAC+1
        lda $A0
        sbc LRX+2
        sta UCAC+2
        cli
        lda #0
        sta UCAC+3
        lda #60                 ; jiffies -> seconds
        ldx #0
        ldy #0
        jsr ucdiv
        jsr stsec
        lda #<sago
        ldx #>sago
        jmp stend
; UCAC seconds as "12s", "4m" or "3h"
stsec:  lda UCAC+1
        ora UCAC+2
        ora UCAC+3
        bne sts1
        lda UCAC
        cmp #120
        bcs sts1
        ldx #0
        jsr stnum
        lda #<sss
        ldx #>sss
        jmp stcat
sts1:   lda #60
        ldx #0
        ldy #0
        jsr ucdiv               ; minutes
        lda UCAC+1
        ora UCAC+2
        ora UCAC+3
        bne sts2
        lda UCAC
        cmp #120
        bcc sts3
sts2:   lda #60
        ldx #0
        ldy #0
        jsr ucdiv               ; hours
        lda UCAC
        ldx UCAC+1
        jsr stnum
        lda #104                ; 'h'
        jmp plchr
sts3:   lda UCAC
        ldx #0
        jsr stnum
        lda #<sm4
        ldx #>sm4
        jmp stcat

; PLOT that also moves the 80 column cursor (carry clear: set)
kplot:  stx KROW
        sty KCOL
        jmp 65520
; the cursor row, whichever screen
kcrow:  lda K80
        beq kcr4
        lda K40
        bne kcr4
        lda KROW
        rts
kcr4:   lda 214
        rts

; ---- sent-line colouring on the 80 column screen (see pnpaint) ----
; PN_O8 = signature offset, PN_SL slot, PN_CL colour
pnp80:  lda #24
        sta PN_RR
pnq1:   lda PN_RR
        ldx #$10
        ldy #0
        jsr kaddr
        lda #0
        sta $D03F               ; no increment: read by index
        ldy #0
pnq2:   sty $D035
        lda $D03B
        sta KT0
        tya
        clc
        adc PN_O8
        tax
        lda PN_SG,x
        cmp KT0
        bne pnq3
        iny
        cpy #16
        bcc pnq2
        lda PN_RR               ; found: its colours
        ldx #$18
        ldy #0
        jsr kaddr
        ldx PN_SL
        lda PN_LB,x
        ldy PN_CL
        cpy #5
        bne pnq4
        lda PN_LN,x             ; green: label and text
pnq4:   tax
        lda PN_CL
        ora #$80
pnq5:   sta $D03B
        dex
        bne pnq5
        rts
pnq3:   dec PN_RR
        bpl pnq1
        rts
; the signature of row A from the 80 column screen
pnsig80: ldx #$10
        ldy #0
        jsr kaddr
        lda #0
        sta $D03F
        ldy #0
pns8:   sty $D035
        lda $D03B
        sta KT0
        tya
        clc
        adc PN_O8
        tax
        lda KT0
        sta PN_SG,x
        iny
        cpy #16
        bcc pns8
        lda #1
        sta $D03F
        rts

; ---- a send the radio refused (an error frame right after it) ----
pnerr:  lda PN_ST               ; a send in the last few seconds?
        ora PN_ST+1
        beq pner9
        lda $A1
        sec
        sbc PN_AG
        cmp #2
        bcc pner1
        lda $A1
        sec
        sbc PN_AG+1
        cmp #2
        bcs pner9
pner1:  lda BUF+1
        sta KT0
        lda #<tsnderr
        sta SPL
        lda #>tsnderr
        sta SPH
        jmp notice
pner9:  rts

; colour codes, in colour order 0-15
kcodes: .byte 144,5,28,159,156,30,31,158,129,149,150,151,152,153,154,155
tkwyes: .text "kawari detected"
        .byte 0
tkwsw:  .text "switching to 80 columns in 3 seconds"
        .byte 0
tkwak:  .text "any key to stay in 40 columns"
        .byte 0
tsnderr: .text "the radio refused that message"
        .byte 0
KOLDV:  .byte 0,0
KWN:    .byte 0
KWT:    .byte 0
K80:    .byte 0
K40:    .byte 0
KROW:   .byte 0
KCOL:   .byte 0
KCLR:   .byte 5
KRVS:   .byte 0
KCH:    .byte 0
KSX:    .byte 0
KSY:    .byte 0
KSC:    .byte 0
KBH:    .byte 0
KT0:    .byte 0
KT1:    .byte 0
KT2:    .byte 0
KT3:    .byte 0
KT4:    .byte 0
KT5:    .byte 0
KT6:    .byte 0
KDL:    .byte 0
KDH:    .byte 0
KSL:    .byte 0
KSH:    .byte 0
KNL:    .byte 0
KNH:    .byte 0
KFB:    .byte 0
KSEPW:  .byte 39
KWID:   .byte 40
PN_RR:  .byte 0
BKN:    .byte 0


; ===== node list filter (s23, mkfind.py) ===============================
; "/" in a node list asks for a text; the list then shows only the nodes
; whose name contains it (any letter case). NFLEN = 0: no filter.

; ndview calls this for every node of the type: count it, then keep it
; (carry clear) or skip it (carry set). PTR = the contact record.
nfmatch: inc NTOT
        lda NFLEN
        beq nfyes
        ldy #0
nfs0:   lda (PTR),y
        beq nfno                ; end of the name: no match from here on
        sty NFY
        ldx #0
nfs1:   lda (PTR),y
        beq nfno
        cmp #65
        bcc nfs4
        cmp #91
        bcs nfs4
        adc #32                 ; upper -> lower (carry is clear here)
nfs4:   cmp NFB,x
        bne nfs2
        iny
        inx
        cpx NFLEN
        bcc nfs1
nfyes:  clc
        rts
nfs2:   ldy NFY
        iny
        jmp nfs0
nfno:   sec
        rts

; the "/" key
nfkey:  lda #<tfind
        sta MNTIT
        lda #>tfind
        sta MNTITH
        jsr inpget
        lda INPOK
        beq nfgo                ; cancelled: the same list again
        ldx #0
nfc:    cpx INPLEN
        bcs nfc2
        cpx #12
        bcs nfc2
        lda INPASC,x
        cmp #65
        bcc nfc3
        cmp #91
        bcs nfc3
        adc #32
nfc3:   sta NFB,x
        inx
        jmp nfc
nfc2:   stx NFLEN
        stx NFTL
        lda #0
        sta NFMS
nfgo:   lda #1
        sta UIMODE
        jmp ndview

; ndview found nothing: with a filter on, say so and show everything
nfempty: lda NFLEN
        beq nfe1
        lda #0
        sta NFLEN
        lda #1
        sta NFMS
        jmp ndview
nfe1:   jmp ndnone

; the line under the list; sets SPL/SPH
nfhint: lda #<tnfh0
        sta SPL
        lda #>tnfh0
        sta SPH
        lda NFMS
        beq nfh1
        lda #<tnfm              ; "no match for "
        ldx #>tnfm
        jsr nfcat0
        jsr nftxt
        lda #<tnfa              ; " - all shown"
        ldx #>tnfa
        jsr nfcat
        jmp nfhd
nfh1:   lda NFLEN
        beq nfhrt
        lda #<tnff              ; "filter: "
        ldx #>tnff
        jsr nfcat0
        jsr nftxt
        lda #<tnfe              ; "  / edit  f1 back"
        ldx #>tnfe
        jsr nfcat
nfhd:   lda #0
        sta NFMS                ; said once
        ldx NFHN
        sta NFH,x
        lda #<NFH
        sta SPL
        lda #>NFH
        sta SPH
nfhrt:  rts
nfcat0: ldy #0
        sty NFHN
nfcat:  sta nfct1+1             ; the operand below is set here: every
        stx nfct1+2             ; zero-page pointer is taken by the menu
        ldy #0
nfct1:  lda $FFFF,y
        beq nfct2
        ldx NFHN
        sta NFH,x
        inc NFHN
        iny
        bne nfct1
nfct2:  rts
nftxt:  ldy #0                  ; the filter text (kept even once cleared)
nftx1:  cpy NFTL
        bcs nfct2
        lda NFB,y
        ldx NFHN
        sta NFH,x
        inc NFHN
        iny
        bne nftx1

; ndtit appends "/total" when a filter is on; X = write index into NTBUF
nfslash: lda NFLEN
        beq nfsl9
        lda #47
        sta NTBUF,x
        inx
        lda NTOT
        sta NDV
        lda #0
        sta NDZ
        ldy #0
nfd1:   lda NDV
        cmp #100
        bcc nfd2
        sbc #100
        sta NDV
        iny
        bne nfd1
nfd2:   tya
        jsr ndig
        ldy #0
nfd3:   lda NDV
        cmp #10
        bcc nfd4
        sbc #10
        sta NDV
        iny
        bne nfd3
nfd4:   tya
        jsr ndig
        lda NDV
        ora #48
        sta NTBUF,x
        inx
nfsl9:  rts

tfind:  .text " Find "
        .byte 0
tnfh0:  .text "RET pick / find  R refresh  F1 back"
        .byte 0
tnfm:   .text "No match: "
        .byte 0
tnfa:   .text " - all shown"
        .byte 0
tnff:   .text "Find: "
        .byte 0
tnfe:   .text "  / edit  F1 back"
        .byte 0
NFB:    .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
NFH:    .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
        .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
        .byte 0,0,0,0,0,0
NFLEN:  .byte 0
NFTL:   .byte 0
NFY:    .byte 0
NFMS:   .byte 0
NFHN:   .byte 0
NTOT:   .byte 0


; ===== delivery / repeat indication (s22, mkpend.py) ===================
; Segment 3. Two slots: 0 = the last channel message sent, 1 = the last DM.
; The label of the sent line (the prompt text at its start) is yellow when
; sent and turns green when the DM is acknowledged, or when a repeater is
; heard re-broadcasting the channel message; each further repeat flashes
; it white for a moment. The line is found again on screen by comparing its
; first 16 characters, so it does not matter how far it has scrolled.

; after kbret's shoprm: SK = 1 channel / 2 DM, TL = text length sent
pnrec:  lda PN_SK
        beq pnrt
        jsr lrxset
        inc PN_SN               ; messages sent (F1 > Stats)
        bne pnsn1
        inc PN_SN+1
pnsn1:
        tax
        dex
        stx PN_SL
        lda #0
        sta PN_SK
        lda #1
        sta PN_ST,x
        lda PRLEN
        sta PN_LB,x
        clc
        adc PN_TL               ; label + text: the whole sent line
        sta PN_LN,x
        lda $A1                 ; TI middle byte: ticks every 4.3 s
        sta PN_AG,x
        txa
        asl
        asl
        asl
        asl
        sta PN_O8
        ldx PN_SL               ; rows it took, less one
        lda PN_LN,x
        sec
        sbc #1
        ldx #0
pnrr1:  cmp KWID                 ; 40 or 80 columns a row
        bcc pnrr2
        sbc KWID
        inx
        bne pnrr1
pnrr2:  stx PN_RW
        jsr kcrow               ; the line just sent ends above the prompt
        sec
        sbc #1
        sbc PN_RW               ; its first row
        ldx K80
        beq pnr0
        ldx K40
        bne pnr0
        jsr pnsig80
        jmp pnr1x
pnr0:   jsr pnrowp
        ldy #0
pnr1:   tya
        clc
        adc PN_O8
        tax
        lda (PTR),y
        sta PN_SG,x
        iny
        cpy #16
        bcc pnr1
pnr1x:  ldx PN_SL
        bne pnr2
; a channel message: the packet a repeater sends back carries a payload of
; 3 + 16 * ceil((5 + len(name) + 2 + len(text)) / 16) bytes
        ldy #0
pnr3:   lda NODENM,y
        beq pnr4
        iny
        bne pnr3
pnr4:   tya
        clc
        adc PN_TL
        adc #22                 ; 7 + 15
        and #$F0
        adc #3
        sta PN_EL
        jmp pnr5
pnr2:   stx PN_AW               ; a DM: its ack tag comes with the sent reply
        jsr dmsave              ; and keep it for a flood retry (s38)
pnr5:   lda #7                  ; yellow
        ldx PN_SL
        jmp pnpaint
pnrt:   rts

; PTR = $0400 + A * 40
pnrowp: tax
        lda #0
        sta PTR
        lda #4
        sta PTRH
pnw1:   cpx #0
        beq pnw2
        lda PTR
        clc
        adc #40
        sta PTR
        bcc pnw3
        inc PTRH
pnw3:   dex
        jmp pnw1
pnw2:   rts

; A = colour, X = slot: recolour the label of that slot's line, if on screen
pnpaint: sta PN_CL
        stx PN_SL
        lda UIMODE
        bne pnrt                ; a menu or panel owns the screen
        txa
        asl
        asl
        asl
        asl
        sta PN_O8
        lda K80
        beq pnp40
        lda K40
        bne pnp40
        jmp pnp80
pnp40:  lda #24                 ; from the prompt row up
        jsr pnrowp
        lda #25
        sta PN_RW
pnp1:   ldy #0
pnp2:   tya
        clc
        adc PN_O8
        tax
        lda PN_SG,x
        cmp (PTR),y
        bne pnp3
        iny
        cpy #16
        bcc pnp2
        lda PTRH                ; found: colour RAM is 212 pages up
        clc
        adc #212
        sta PTR2H
        lda PTR
        sta PTR2
        ldx PN_SL
        lda PN_LB,x
        ldy PN_CL
        cpy #5
        bne pnp6
        lda PN_LN,x             ; green: label and text
pnp6:   sta PN_RW
        ldy #0
        lda PN_CL
pnp4:   sta (PTR2),y
        iny
        cpy PN_RW
        bcc pnp4
        rts
pnp3:   lda PTR                 ; one row up
        sec
        sbc #40
        sta PTR
        bcs pnp5
        dec PTRH
pnp5:   dec PN_RW
        bne pnp1
        rts

; RESP_CODE_SENT [6][flood][ack tag:4][timeout:4] -- for our last DM
pnsent: lda PN_AW
        bmi pnrt1
        tax
        lda #255
        sta PN_AW
        lda $A1
        sec
        sbc PN_AG,x
        cmp #2
        bcs pnrt1               ; too old to be the reply to that DM
        ldx #4
        ldy #0
pns1:   lda BUF+2,y
        sta PN_KY,x
        inx
        iny
        cpy #4
        bcc pns1
        lda BUF+1               ; 0 = went direct (s38: flood retry later)
        sta DMFL
        lda $A1
        sta DMT
pnrt1:  rts

; PUSH_CODE_SEND_CONFIRMED [0x82][ack tag:4][trip time:4]
pnack:  lda PN_ST+1
        cmp #1
        bne pnrt1
        ldy #0
pna1:   lda BUF+1,y
        cmp PN_KY+4,y
        bne pnrt1
        iny
        cpy #4
        bcc pna1
        lda #2
        sta PN_ST+1
        lda #5                  ; green
        ldx #1
        jmp pnpaint

; PUSH_CODE_LOG_RX_DATA [0x88][snr][rssi][raw packet]: is it our channel
; message coming back from a repeater?
pnlog:  lda PN_ST
        beq pnrt1
        lda $A1
        sec
        sbc PN_AG
        cmp #8                  ; about 34 s
        bcs pnrt1
        lda FLEN
        cmp #12
        bcc pnrt1
        lda BUF+3               ; packet header
        and #$3C
        cmp #$14                ; payload type 5: group text
        bne pnrt1
        lda BUF+3
        and #3
        cmp #2
        bcs pnrt1               ; a direct packet is not a flood repeat
        ldx #4                  ; path length byte follows the header...
        cmp #0
        bne pnl1
        ldx #8                  ; ...and the 4 transport code bytes
pnl1:   lda BUF,x
        sta PN_PL
        and #$3F
        beq pnrt1               ; no hops: not heard through a repeater
        sta PN_HC
        stx PN_PX
        lda PN_PL
        lsr
        lsr
        lsr
        lsr
        lsr
        lsr
        tay
        iny                     ; hash size 1-4 bytes per hop
        lda #0
pnl2:   clc
        adc PN_HC
        dey
        bne pnl2                ; A = bytes of path
        sec
        adc PN_PX               ; + path length byte position + 1
        sta PN_PX               ; = payload offset in the frame
        lda FLEN
        sec
        sbc PN_PX
        cmp PN_EL
        bne pnrt1               ; not the length of our message
        lda #<BUF
        clc
        adc PN_PX
        sta PTR
        lda #>BUF
        adc #0
        sta PTRH
        lda PN_ST
        cmp #1
        bne pnl4
        ldy #3                  ; the first echo: remember its signature
pnl3:   lda (PTR),y
        sta PN_KY,y
        dey
        bpl pnl3
        lda #2
        sta PN_ST
        lda #5                  ; green
        ldx #0
        jmp pnpaint
pnl4:   ldy #3                  ; later ones must carry the same signature
pnl5:   lda (PTR),y
        cmp PN_KY,y
        bne pnrt1
        dey
        bpl pnl5
        lda PN_FS
        bmi pnl6
        jsr pnrest              ; one flash at a time
pnl6:   lda #1                  ; white
        ldx #0
        jsr pnpaint
        lda #0
        sta PN_FS
        lda $A2
        sta PN_FT
        rts

pnrest: ldx PN_FS
        lda #5
        jsr pnpaint
        lda #255
        sta PN_FS
        rts
; main loop: end a flash after ~0.25 s
flrest: lda PN_FS
        bmi flrt
        lda $A2
        sec
        sbc PN_FT
        cmp #15
        bcc flrt
        jmp pnrest
flrt:   rts

PN_ST:  .byte 0,0
PN_SN:  .byte 0,0
PN_LB:  .byte 0,0
PN_LN:  .byte 0,0
PN_EL:  .byte 0,0
PN_AG:  .byte 0,0
PN_SG:  .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
        .byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
PN_KY:  .byte 0,0,0,0,0,0,0,0
PN_FS:  .byte 255
PN_FT:  .byte 0
PN_AW:  .byte 255
PN_SK:  .byte 0
PN_TL:  .byte 0
PN_SL:  .byte 0
PN_O8:  .byte 0
PN_CL:  .byte 0
PN_RW:  .byte 0
PN_PL:  .byte 0
PN_HC:  .byte 0
PN_PX:  .byte 0
"""


def strip_debug(src1, testk):
    """report is test-only and nothing needs it; tkey only when testk."""
    a = src1.index("report: lda #3")
    b = src1.index("apphex: pha")
    src1 = src1[:a] + "report: rts\n" + src1[b:]
    if not testk:
        a = src1.index("tkey:   lda testk")
        b = src1.index("; f1+pick Test | type")
        src1 = src1[:a] + "tkey:   rts\n" + src1[b:]
    return src1


def assemble4(src1, src2, src3, src4):
    """Five segments that call each other; placeholders settle in a few passes.
    Segment 5's bytes are left in SEG5 (the return value stays four code
    blocks, as every test harness expects)."""
    global SEG5
    def labels(src):
        return [p[0] for p in (parse(l) for l in src.splitlines()) if p and p[0]]
    labels2, labels3, labels4, labels5 = labels(src2), labels(src3), labels(src4), labels(SRC5)
    others = set(labels2) | set(labels3) | set(labels4) | set(labels5)
    src1 = src1 + "\ns2img:\n"
    s2 = {n: S2ORG for n in labels2}
    s3 = {n: S3ORG for n in labels3}
    s4 = {n: S4ORG for n in labels4}
    s5 = {n: S5ORG for n in labels5}
    eq1 = dict(EQU)
    for d in (s2, s3, s4, s5):
        eq1.update(d)
    eq1["S2PG"] = 1
    eq1["S4PG"] = 1
    prev = None
    for _ in range(8):
        code1, syms1 = assemble(src1, ORG, eq1)
        base = {k: v for k, v in syms1.items() if k not in others}
        eq2 = dict(base); eq2.update(s3); eq2.update(s4); eq2.update(s5)
        code2, syms2 = assemble(src2, S2ORG, eq2)
        s2 = {n: syms2[n] for n in labels2}
        eq3 = dict(base); eq3.update(s2); eq3.update(s4); eq3.update(s5)
        code3, syms3 = assemble(src3, S3ORG, eq3)
        s3 = {n: syms3[n] for n in labels3}
        eq4 = dict(base); eq4.update(s2); eq4.update(s3); eq4.update(s5)
        code4, syms4 = assemble(src4, S4ORG, eq4)
        s4 = {n: syms4[n] for n in labels4}
        eq5 = dict(base); eq5.update(s2); eq5.update(s3); eq5.update(s4)
        code5, syms5 = assemble(SRC5, S5ORG, eq5)
        s5 = {n: syms5[n] for n in labels5}
        eq1 = dict(EQU)
        for d in (s2, s3, s4, s5):
            eq1.update(d)
        eq1["S2PG"] = (len(code2) + 255) // 256
        eq1["S4PG"] = (len(code4) + 255) // 256
        if (code1, code2, code3, code4, code5) == prev:
            allsyms = dict(syms1)
            for d in (syms2, syms3, syms4, syms5):
                allsyms.update(d)
            SEG5 = bytes(code5)
            return code1, allsyms, code2, code3, code4
        prev = (code1, code2, code3, code4, code5)
    raise ValueError("segments did not settle")


def build(ctrl=DEFAULT_CTRL, out=OUT, blank=0, clock=PAL, testk=0,
          latadj=125, nogeo=0):
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
    # the connecting line names the rate this image was built for
    msg = 'msgcon: .text "connecting..."'
    assert SRC.count(msg) == 1, "msgcon"
    src1 = SRC.replace(msg, 'msgcon: .text "connecting at %d baud..."' % baud)
    src1 = strip_debug(src1, testk)
    code, syms, code2, code3, code4 = assemble4(src1 + keytable(testk) + artwork(),
                                                SRC2 + sha256_6502.source(), SRC3, SRC4)
    if syms["KOLDV"] & 0xFF == 0xFF:
        raise ValueError("KOLDV at $%04X: JMP () would wrap the page" % syms["KOLDV"])
    code = bytearray(code)
    # Buffers that are indexed, not just read, and so will corrupt a
    # neighbour rather than fail loudly if they collide. PKBUF sitting
    # immediately after CONTACTS is exactly the adjacency worth checking.
    regions = [("CONTACTS", 96 * 64), ("PKBUF", 10 * 32),
               ("CHNAM", 48 * 18), ("CUNR", 48), ("PROMPT", 80), ("NODENM", 20), ("NODETAB", 255 * 2),
               ("NODEIX", 255),
               ("PLTAB", 10 * 2),
               ("DECBUF", 12), ("CHNAME", 32), ("FWVER", 20),
               ("INPASC", 32), ("SECBUF", 16),
               ("PLBUF", 10 * 32), ("TSTR", 40), ("RBUF", 256), ("TXBUF", 256),
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
    vals = [("btlo", (bit - 1) & 0xFF), ("bthi", (bit - 1) >> 8),
            ("hblo", half & 0xFF), ("hbhi", half >> 8),
            ("blankb", blank), ("testk", testk),
            ("geook", 0 if nogeo else 1)]
    # the runtime table: PAL quad then NTSC quad, contiguous
    for i, v in enumerate([(bit - 1) & 0xFF, (bit - 1) >> 8, half & 0xFF, half >> 8,
                           (nbit - 1) & 0xFF, (nbit - 1) >> 8, nhalf & 0xFF, nhalf >> 8]):
        code[syms["bitpal"] - ORG + i] = v
    for name, val in vals:
        code[syms[name] - ORG] = val
    # Segment 2 rides directly behind segment 1 and is copied to $a000 at
    # startup. While loaded it sits on top of $4000, which is fine -- that
    # is splash/archive RAM nothing touches before the copy -- but it must
    # not reach the contact table or the buffers above it.
    if end + len(code2) > EQU["LOGODAT"]:
        raise ValueError("segment 2 image ends at $%04X, into the logo"
                         % (end + len(code2)))
    logo = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "logo.bin"), "rb").read()
    if EQU["LOGODAT"] + len(logo) > 0x8000:
        raise ValueError("logo runs into $8000")
    if S2ORG + len(code2) > EQU["CUNR"]:
        raise ValueError("segment 2 is %d bytes, into CUNR at $%04X"
                         % (len(code2), EQU["CUNR"]))
    prg = bytes([ORG & 0xFF, ORG >> 8]) + bytes(code) + bytes(code2)
    prg += bytes(EQU["LOGODAT"] - (ORG + len(prg) - 2)) + logo
    if S3ORG != EQU["LOGODAT"] + len(logo) or S3ORG + len(code3) > 0x8000:
        raise ValueError("segment 3 ($%04X, %d bytes) does not fit before $8000"
                         % (S3ORG, len(code3)))
    prg += bytes(code3)
    if S3ORG + len(code3) > S4IMG:
        raise ValueError("segment 3 runs into the segment 4 image")
    if S4ORG + 256 * ((len(code4) + 255) // 256) > S3ORG:
        raise ValueError("segment 4 is %d bytes: its pages reach segment 3" % len(code4))
    code4 = bytearray(code4)
    code4[syms["BAUDV"] - S4ORG] = baud & 0xFF
    code4[syms["BAUDV"] - S4ORG + 1] = baud >> 8
    prg += bytes(S4IMG - (ORG + len(prg) - 2)) + bytes(code4)
    if S5ORG + len(SEG5) > S5MAX:
        raise ValueError("segment 5 is %d bytes: past $%04X" % (len(SEG5), S5MAX))
    # its image: segment 4's pages, then two pages whose bytes from $60 on
    # are $9960-$9AFF (main copies Y = $60.. of the first, all of the second)
    prg += bytes(256 * ((len(code4) + 255) // 256) - len(code4))
    prg += bytes(S5ORG - 0x9900) + SEG5 + bytes(S5MAX - S5ORG - len(SEG5))
    with open(out, "wb") as f:
        f.write(prg)
    return code, syms, prg, bit, half


if __name__ == "__main__":
    ctrl = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CTRL
    out = sys.argv[2] if len(sys.argv) > 2 else OUT
    blank = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    testk = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    latadj = int(sys.argv[5]) if len(sys.argv) > 5 else 125
    nogeo = int(sys.argv[6]) if len(sys.argv) > 6 else 0
    code, syms, prg, bit, half = build(ctrl, out, blank, PAL, testk, latadj, nogeo)
    print("; %d baud: PAL %d cycles/bit (sample %d), NTSC %d (%d)"
          % (RATES[ctrl], bit, half, int(round(NTSC / float(RATES[ctrl]))),
             int(round(NTSC / float(RATES[ctrl])) * 1.5) - latadj))
    print("; assembled %d bytes at $%04X" % (len(code), ORG))
    print("; segment 2: %d bytes at $%04X" % (len(prg) - 2 - (syms["s2img"] - ORG), S2ORG))
    for n in ("main", "serini", "nmih", "txbyte", "sendfr", "poll", "handshk"):
        print(";   %-8s = $%04X" % (n, syms[n]))
    print("; wrote %s (%d bytes)" % (out, len(prg)))
