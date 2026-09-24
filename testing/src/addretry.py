#!/usr/bin/env python3
"""
Add handshake retries and a longer pre-handshake wait, to any variant.

There was no retry anywhere in the handshake: waitop returns when it times
out and the client carries on with nothing, so one lost APP_START strands
it for good. And the driver build waits 1.2s before speaking where the
KERNAL build waits 3.2 -- its post-OPEN settle on top of the same 1.2 --
which may be the only reason the KERNAL build connects at all.
"""
import io, sys


def patch(src, dst):
    s = io.open(src, encoding="utf-8").read()

    s = s.replace('    "LEDLST":  0xCFF9,',
                  '    "LEDLST":  0xCFF9,\n'
                  '    "HSRTY":   0xCFFE,   # app_start attempts\n'
                  '    "WTMO":    0xCFFF,   # waitop timeout, in jiffy wraps')

    old = "        cmp #7\n        bcs wotmo"
    assert s.count(old) == 1, "waitop timeout"
    s = s.replace(old, "        cmp WTMO\n        bcs wotmo")

    old = "handshk:\n        ldx #60\nrsyncw: jsr poll"
    assert s.count(old) == 1, "handshake head"
    s = s.replace(old, """handshk:
        lda #7              ; the normal, patient timeout
        sta WTMO
; **Three seconds before saying anything.** The C64 boots from cartridge
; in about two; the radio has bluetooth, a display and a LoRa front end to
; bring up and takes longer. The kernal build waits this long by accident
; and connects; this one waited 1.2s and did not.
        ldx #150
rsyncw: jsr poll""")

    old = """        lda #<pyastart
        sta PTR
        lda #>pyastart
        sta PTRH
        lda #11
        jsr setpay
        jsr sendfr
        lda #1
        sta STGBIT
        lda #5
        jsr waitop"""
    assert s.count(old) == 1, "app_start stage"
    s = s.replace(old, """; Four tries at eight seconds rather than one at thirty.
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
        sta WTMO""")

    io.open(dst, "w", encoding="utf-8").write(s)
    print("wrote %s" % dst)


if __name__ == "__main__":
    patch(sys.argv[1], sys.argv[2])
