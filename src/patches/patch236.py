#!/usr/bin/env python3
"""
v2.3.6d: hashtag channels get their real key.

User report (2026-10-10, real hardware): Public works, but channels added on
the C64 can neither send nor receive. All were #hashtag channels, added with
the key field left blank -- and the client sent an all-zero secret.

MeshCore derives a hashtag channel's secret IN THE CLIENT as the first 16
bytes of sha256("#name") (docs/companion_protocol.md, "Hashtag Channels");
the firmware stores whatever SET_CHANNEL hands it. Now: a name starting
with '#' and an EMPTY key field -> SECBUF = sha256(name)[0:16], computed on
the C64 by sha256_6502.py (segment 2; verified against hashlib, 70/70).
A typed key is still used as typed.
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


rep('banner: .text "meshcore 64  v2.3.5d"', 'banner: .text "meshcore 64  v2.3.6d"')
rep('from asm import assemble, parse\n', 'from asm import assemble, parse\nimport sha256_6502\n')
rep('    code, syms, code2 = assemble2(SRC + keytable(testk) + artwork(), SRC2)',
    '    code, syms, code2 = assemble2(SRC + keytable(testk) + artwork(),\n'
    '                                  SRC2 + sha256_6502.source())')
rep('''; A leading "#" is just part of the name; nothing special is needed here.''',
    '''; **A #hashtag channel's key is sha256(name)[0:16], derived HERE.** The
; firmware does not derive it -- leaving the key blank used to send sixteen
; zeros, which makes a channel nobody else can read and that drops everyone
; else's messages. Name starting with '#' + empty key field -> hashch.''')
rep('''caa4:   jsr inphx
        jmp chsend''',
    '''caa4:   lda INPLEN
        bne caa5                ; a typed key is used as typed
        lda CHNAME
        cmp #35                 ; '#'
        bne caa5
        jsr hashch              ; SECBUF = sha256(CHNAME)[0:16], ~0.6 s
        jmp chsend
caa5:   jsr inphx
        jmp chsend''')
io.open(SRC_FILE, "w", encoding="utf-8").write(s)

k = io.open(KFILE, encoding="utf-8").read()
for old, new in (('banner: .text "meshcore 64  v2.3.5d"', 'banner: .text "meshcore 64  v2.3.6d"'),
                 ("'banner: .text \"meshcore 64  v2.3.5\"'", "'banner: .text \"meshcore 64  v2.3.6\"'")):
    assert k.count(old) == 1, old
    k = k.replace(old, new)
io.open(KFILE, "w", encoding="utf-8").write(k)
print("patched", SRC_FILE, KFILE)
