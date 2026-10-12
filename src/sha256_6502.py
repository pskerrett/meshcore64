#!/usr/bin/env python3
"""
SHA-256 for the 6502, ONE 64-byte block only -- enough for a MeshCore
hashtag channel key, which is the first 16 bytes of sha256("#name") and a
channel name is at most 32 bytes (one block holds up to 55).

Entry  hashch: hashes the NUL-terminated (max 32 bytes) string at CHNAME
       and writes the first 16 bytes of the digest to SECBUF.
Words are kept LITTLE-endian in memory (byte 0 = least significant) so the
adds and rotates are plain carry chains; the message is byte-swapped in
and the digest swapped out. Speed is irrelevant (it runs once per channel
add, ~0.4 s), so rotations are done one bit at a time.

Only opcodes/modes that asm.py already has are used (abs, absx, absy, imm).
"""


def _icbrt(n):
    x = int(round(n ** (1.0 / 3)))
    while x * x * x > n:
        x -= 1
    while (x + 1) ** 3 <= n:
        x += 1
    return x


def _isqrt(n):
    import math
    return math.isqrt(n)


def _primes(k):
    out, n = [], 2
    while len(out) < k:
        if all(n % p for p in out if p * p <= n):
            out.append(n)
        n += 1
    return out


def constants():
    p = _primes(64)
    K = [_icbrt(q << 96) & 0xFFFFFFFF for q in p]
    H = [_isqrt(q << 64) & 0xFFFFFFFF for q in p[:8]]
    return K, H


def _le(words):
    out = []
    for w in words:
        out += [w & 255, (w >> 8) & 255, (w >> 16) & 255, (w >> 24) & 255]
    return out


def _bytelines(label, data):
    rows = [label + ":"]
    for i in range(0, len(data), 16):
        rows.append("        .byte " + ",".join(str(b) for b in data[i:i + 16]))
    return "\n".join(rows) + "\n"


CODE = r"""
; ===== SHA-256, one block: SECBUF = sha256(CHNAME)[0:16] ==============
; MeshCore derives a #hashtag channel's secret this way, in the CLIENT --
; the firmware stores whatever 16 bytes SET_CHANNEL hands it. Sending zeros
; makes a channel nobody else can read and that drops everyone else's
; messages (docs/companion_protocol.md, "Hashtag Channels").
hashch: ldx #0                  ; message block: zero it
        lda #0
h2z:    sta h2v+128,x
        inx
        cpx #64
        bne h2z
        ldx #0                  ; copy the name, find its length
h2c:    cpx #32
        beq h2cd
        lda CHNAME,x
        beq h2cd
        sta h2v+128,x
        inx
        jmp h2c
h2cd:   lda #128                ; the 1 bit after the message
        sta h2v+128,x
        txa                     ; bit length = len*8 (< 256 for len <= 31)
        asl
        asl
        asl
        sta h2v+191
        txa
        lsr
        lsr
        lsr
        lsr
        lsr
        sta h2v+190             ; len*8 >> 8 (only 32 can reach it)
; W[0..15] = the block, big-endian words stored little-endian: W[x] = M[x^3]
        ldx #0
h2m:    txa
        eor #3
        tay
        lda h2v+128,y
        sta h2w,x
        inx
        cpx #64
        bne h2m
; H = initial hash value; a..h = H
        ldx #0
h2h:    lda h2hi,x
        sta h2v,x
        sta h2v+32,x
        inx
        cpx #32
        bne h2h
; ---- message schedule, W[16..63] ----
        lda #64
        sta h2o
h2sl:   lda h2o
        sec
        sbc #64
        tax
        jsr h2wa                ; ACC = W[t-16]
        lda h2o
        sec
        sbc #28
        tax
        jsr h2wr                ; R = W[t-7]
        jsr h2aar
        jsr h2sq                ; Q = ACC
        lda h2o
        sec
        sbc #60
        tax
        jsr h2ws                ; SRC = W[t-15]
        lda #7
        sta h2g1
        lda #18
        sta h2g2
        lda #3
        sta h2g3
        lda #1
        sta h2gm
        jsr h2sig               ; ACC = sigma0
        jsr h2qa                ; ACC += Q
        jsr h2sq
        lda h2o
        sec
        sbc #8
        tax
        jsr h2ws                ; SRC = W[t-2]
        lda #17
        sta h2g1
        lda #19
        sta h2g2
        lda #10
        sta h2g3
        lda #1
        sta h2gm
        jsr h2sig               ; ACC = sigma1
        jsr h2qa
        ldx h2o
        jsr h2aw                ; W[t] = ACC
        lda h2o
        clc
        adc #4
        sta h2o
        beq h2sd
        jmp h2sl
h2sd:
; ---- 64 rounds ----
        lda #0
        sta h2o
h2rl:   ldx #48
        jsr h2vs                ; SRC = e
        lda #6
        sta h2g1
        lda #11
        sta h2g2
        lda #25
        sta h2g3
        lda #0
        sta h2gm
        jsr h2sig               ; ACC = S1(e)
        jsr h2sq                ; Q = S1
        ldx #0                  ; ACC = ch(e,f,g) = (e&f) ^ (~e&g)
h2ch:   lda h2v+48,x
        eor #255
        and h2v+56,x
        sta h2tb
        lda h2v+48,x
        and h2v+52,x
        eor h2tb
        sta h2acc,x
        inx
        cpx #4
        bne h2ch
        jsr h2qa                ; + S1
        ldx #60
        jsr h2vr
        jsr h2aar               ; + h
        ldx h2o
        jsr h2kr
        jsr h2aar               ; + K[t]
        ldx h2o
        jsr h2wr
        jsr h2aar               ; + W[t]
        ldx #64
        jsr h2av                ; T1
        ldx #32
        jsr h2vs                ; SRC = a
        lda #2
        sta h2g1
        lda #13
        sta h2g2
        lda #22
        sta h2g3
        lda #0
        sta h2gm
        jsr h2sig               ; ACC = S0(a)
        jsr h2sq
        ldx #0                  ; ACC = maj(a,b,c)
h2mj:   lda h2v+32,x
        and h2v+36,x
        sta h2tb
        lda h2v+32,x
        and h2v+40,x
        eor h2tb
        sta h2tb
        lda h2v+36,x
        and h2v+40,x
        eor h2tb
        sta h2acc,x
        inx
        cpx #4
        bne h2mj
        jsr h2qa                ; + S0 = T2
        ldx #68
        jsr h2av
; h=g g=f f=e e=d d=c c=b b=a: slide a..g up one word (top down)
        ldx #27
h2mv:   lda h2v+32,x
        sta h2v+36,x
        dex
        bpl h2mv
        ldx #48                 ; e = d + T1 (old d now sits in e)
        jsr h2va
        ldx #64
        jsr h2vr
        jsr h2aar
        ldx #48
        jsr h2av
        ldx #64                 ; a = T1 + T2
        jsr h2va
        ldx #68
        jsr h2vr
        jsr h2aar
        ldx #32
        jsr h2av
        lda h2o
        clc
        adc #4
        sta h2o
        beq h2rd
        jmp h2rl
h2rd:
; ---- H += a..h ----
        lda #0
        sta h2o
h2fl:   ldx h2o
        jsr h2va
        lda h2o
        clc
        adc #32
        tax
        jsr h2vr
        jsr h2aar
        ldx h2o
        jsr h2av
        lda h2o
        clc
        adc #4
        sta h2o
        cmp #32
        bne h2fl
; ---- first 16 digest bytes, big-endian: SECBUF[x] = H[x^3] ----
        ldx #0
h2o2:   txa
        eor #3
        tay
        lda h2v,y
        sta SECBUF,x
        inx
        cpx #16
        bne h2o2
        rts

; --- sigma: ACC = rot(SRC,g1) ^ rot(SRC,g2) ^ (gm ? shr : rot)(SRC,g3) ---
h2sig:  lda #0
        sta h2acc
        sta h2acc+1
        sta h2acc+2
        sta h2acc+3
        lda h2g1
        jsr h2rot
        jsr h2axr
        lda h2g2
        jsr h2rot
        jsr h2axr
        lda h2g3
        ldx h2gm
        bne h2sg3
        jsr h2rot
        jmp h2axr
h2sg3:  jsr h2shr
        jmp h2axr
; R = SRC rotated right by A bits
h2rot:  sta h2n
        jsr h2sr
h2r1:   lda h2n
        beq h2r2
        lda h2r
        lsr                     ; carry = bit 0, which wraps to bit 31
        ror h2r+3
        ror h2r+2
        ror h2r+1
        ror h2r
        dec h2n
        jmp h2r1
h2r2:   rts
; R = SRC shifted right by A bits
h2shr:  sta h2n
        jsr h2sr
h2s1:   lda h2n
        beq h2s2
        lsr h2r+3
        ror h2r+2
        ror h2r+1
        ror h2r
        dec h2n
        jmp h2s1
h2s2:   rts
; ACC ^= R
h2axr:  lda h2acc
        eor h2r
        sta h2acc
        lda h2acc+1
        eor h2r+1
        sta h2acc+1
        lda h2acc+2
        eor h2r+2
        sta h2acc+2
        lda h2acc+3
        eor h2r+3
        sta h2acc+3
        rts
; ACC += R (mod 2^32)
h2aar:  clc
        lda h2acc
        adc h2r
        sta h2acc
        lda h2acc+1
        adc h2r+1
        sta h2acc+1
        lda h2acc+2
        adc h2r+2
        sta h2acc+2
        lda h2acc+3
        adc h2r+3
        sta h2acc+3
        rts
; Q = ACC ; ACC += Q
h2sq:   lda h2acc
        sta h2q
        lda h2acc+1
        sta h2q+1
        lda h2acc+2
        sta h2q+2
        lda h2acc+3
        sta h2q+3
        rts
h2qa:   lda h2q
        sta h2r
        lda h2q+1
        sta h2r+1
        lda h2q+2
        sta h2r+2
        lda h2q+3
        sta h2r+3
        jmp h2aar
; R = SRC
h2sr:   lda h2src
        sta h2r
        lda h2src+1
        sta h2r+1
        lda h2src+2
        sta h2r+2
        lda h2src+3
        sta h2r+3
        rts
; word moves, X = byte offset of the word
h2vr:   lda h2v,x
        sta h2r
        lda h2v+1,x
        sta h2r+1
        lda h2v+2,x
        sta h2r+2
        lda h2v+3,x
        sta h2r+3
        rts
h2wr:   lda h2w,x
        sta h2r
        lda h2w+1,x
        sta h2r+1
        lda h2w+2,x
        sta h2r+2
        lda h2w+3,x
        sta h2r+3
        rts
h2kr:   lda h2k,x
        sta h2r
        lda h2k+1,x
        sta h2r+1
        lda h2k+2,x
        sta h2r+2
        lda h2k+3,x
        sta h2r+3
        rts
h2va:   lda h2v,x
        sta h2acc
        lda h2v+1,x
        sta h2acc+1
        lda h2v+2,x
        sta h2acc+2
        lda h2v+3,x
        sta h2acc+3
        rts
h2wa:   lda h2w,x
        sta h2acc
        lda h2w+1,x
        sta h2acc+1
        lda h2w+2,x
        sta h2acc+2
        lda h2w+3,x
        sta h2acc+3
        rts
h2vs:   lda h2v,x
        sta h2src
        lda h2v+1,x
        sta h2src+1
        lda h2v+2,x
        sta h2src+2
        lda h2v+3,x
        sta h2src+3
        rts
h2ws:   lda h2w,x
        sta h2src
        lda h2w+1,x
        sta h2src+1
        lda h2w+2,x
        sta h2src+2
        lda h2w+3,x
        sta h2src+3
        rts
h2av:   lda h2acc
        sta h2v,x
        lda h2acc+1
        sta h2v+1,x
        lda h2acc+2
        sta h2v+2,x
        lda h2acc+3
        sta h2v+3,x
        rts
h2aw:   lda h2acc
        sta h2w,x
        lda h2acc+1
        sta h2w+1,x
        lda h2acc+2
        sta h2w+2,x
        lda h2acc+3
        sta h2w+3,x
        rts
h2acc:  .byte 0,0,0,0
h2r:    .byte 0,0,0,0
h2src:  .byte 0,0,0,0
h2q:    .byte 0,0,0,0
h2tb:   .byte 0
h2n:    .byte 0
h2o:    .byte 0
h2g1:   .byte 0
h2g2:   .byte 0
h2g3:   .byte 0
h2gm:   .byte 0
"""


def source():
    K, H = constants()
    zeros = [0] * 256
    return (CODE
            + _bytelines("h2hi", _le(H))
            + _bytelines("h2k", _le(K))
            + _bytelines("h2v", zeros)        # H 0-31, a..h 32-63, T1 64, T2 68, block 128-191
            + _bytelines("h2w", zeros))       # W[0..63]


if __name__ == "__main__":
    K, H = constants()
    print("K[0]=%08x K[63]=%08x H[0]=%08x H[7]=%08x" % (K[0], K[63], H[0], H[7]))
