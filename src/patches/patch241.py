#!/usr/bin/env python3
"""
v2.4b (respin): the connecting screen says what speed it is trying.

"connecting..." -> "connecting at 2400 baud..." (the build fills in the
rate it was built for, so the 600 KERNAL fallback says 600). A client and
radio on different speeds look exactly like a dead radio; this line is the
first thing to check.
"""
import io, sys

SRC_FILE = sys.argv[1] if len(sys.argv) > 1 else "mlfull.py"
s = io.open(SRC_FILE, encoding="utf-8").read()


def rep(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, "anchor found %d times, wanted %d: %r" % (n, count, old[:70])
    s = s.replace(old, new)


rep('''    code, syms, code2 = assemble2(SRC + keytable(testk) + artwork(),''',
    '''    # the connecting line names the rate this image was built for
    msg = 'msgcon: .text "connecting..."'
    assert SRC.count(msg) == 1, "msgcon"
    src1 = SRC.replace(msg, 'msgcon: .text "connecting at %d baud..."' % baud)
    code, syms, code2 = assemble2(src1 + keytable(testk) + artwork(),''')
io.open(SRC_FILE, "w", encoding="utf-8").write(s)
print("patched", SRC_FILE)
