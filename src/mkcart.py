#!/usr/bin/env python3
"""
Wrap the BASIC program in an autostarting Magic Desk cartridge (.crt).

Why Magic Desk and not a plain 8K ROM board:

  The cartridge port exposes only two 8K windows - $8000 and $A000 - and
  $A000 is where BASIC ROM lives. A 16K cart therefore REPLACES BASIC, so
  the stub would have nothing left to run the program with, and a plain
  board cannot step out of the way afterwards because EXROM/GAME are
  hardwired. A bigger EPROM does not help: the C64 can still only see 8K
  at a time.

  Magic Desk solves it with one latch. Writing $DE00 selects an 8K bank,
  and bit 7 of that register DISABLES the cartridge entirely. So the stub
  copies bank 0 into RAM, switches to bank 1, copies the rest, then banks
  itself out - BASIC reappears and runs the program.

  The catch, and it cost a debugging round: code cannot do that switching
  from inside the cartridge window. The moment $DE00 is written the bytes
  under the program counter change - to program data on a bank switch, to
  empty RAM on the bank-out - and the CPU runs off into garbage with a
  blank screen. So the ROM stub's only job is to copy a small MOVER into
  the tape buffer at $033C and jump to it. The mover runs from RAM, where
  the banks moving beneath $8000 cannot touch it.

  Hardware: an EPROM plus a '273-style latch decoding a write to $DE00.
  The 1541 Ultimate II+ and similar do it in software with no extra parts.

The program MUST be the crunched build; the commented one does not fit in
RAM at all, never mind a cartridge.
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ml"))
from asm import assemble

PRG  = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "meshcore64.prg")
OUT  = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "meshcore64.crt")
NAME = "MESHCORE 64"

BANKSZ = 8192
ROMSZ  = 32768           # magic desk's minimum: cartconv rejects 8K and
                         # 16K outright. that is a 27C256, a stock part.
SRCPG  = 0x8100          # program data starts one page in, so the copy
                         # works in whole pages
B0     = 0xA000 - SRCPG          # 7936 bytes of program in bank 0

raw = open(PRG, "rb").read()
load, data = raw[0] | (raw[1] << 8), raw[2:]
assert load == 0x0801, "expected a BASIC program loading at $0801, got $%04X" % load
proglen = len(data)
# A program small enough for one bank still ships as Magic Desk: the format
# has a 32K minimum anyway, so there is nothing to gain from a second cart
# type, and the stub simply skips the bank-1 copy. The machine-language
# client is about 5K and lands here; the BASIC one is 13K and does not.
if proglen <= B0:
    rest = 0
    nb0 = (proglen + 255) // 256
    nb1 = 0
else:
    rest = proglen - B0
    assert rest <= BANKSZ, "needs more than 2 banks (%d bytes over)" % (rest - BANKSZ)
    nb0 = (B0 + 255) // 256
    nb1 = (rest + 255) // 256
pend = 0x0801 + proglen

MOVER_ADDR = 828        # $033C, the tape buffer: free at boot, and the
                        # BASIC program does not touch it until its REU
                        # probe runs long afterwards.

# Runs from RAM. Everything that writes $DE00 has to live here.
MOVER = """
        lda #0
        sta 251
        lda #129
        sta 252             ; source $8100 (bank 0, past the stub page)
        lda #1
        sta 253
        lda #8
        sta 254             ; dest $0801
        ldx #NB0
        jsr copy

@BANK1@
; bank the cartridge out so BASIC ROM comes back
        lda #128
        sta 56832           ; $DE00 bit 7 = disable

        lda #<PEND
        sta 45
        lda #>PEND
        sta 46              ; VARTAB = end of program
        jsr 42585           ; $A659 CLR

        lda #82
        sta 631             ; R
        lda #85
        sta 632             ; U
        lda #78
        sta 633             ; N
        lda #13
        sta 634
        lda #4
        sta 198             ; four characters pending
        jmp 42112           ; $A480 basic main loop reads them and RUNs

copy:   ldy #0
cpl:    lda (251),y
        sta (253),y
        iny
        bne cpl
        inc 252
        inc 254
        dex
        bne cpl
        rts
"""

# Runs from ROM at $8009. Deliberately does NOT touch $DE00.
STUB = """
cold:   sei
        cld
        ldx #255
        txs
        jsr 64931           ; $FDA3 IOINIT
        jsr 64848           ; $FD50 RAMTAS
        jsr 64789           ; $FD15 RESTOR
        jsr 65371           ; $FF5B CINT
        cli
        jsr 58451           ; $E453 init basic vectors
        jsr 58303           ; $E3BF init basic

; hand off to RAM before any bank moves
        ldx #0
mvc:    lda mover,x
        sta MVDST,x
        inx
        cpx #MVLEN
        bne mvc
        jmp MVDST

mover:  .byte MVBYTES
"""

BANK1 = """; select bank 1 and carry on - the destination pointer is already where
; the first chunk left off, so this just continues the stream
        lda #1
        sta 56832           ; $DE00 bank select
        lda #0
        sta 251
        lda #128
        sta 252             ; source $8000 (all of bank 1 is program)
        ldx #NB1
        jsr copy
"""

msrc = (MOVER.replace("@BANK1@", BANK1 if nb1 else "")
             .replace("#NB0", "#%d" % nb0)
             .replace("#NB1", "#%d" % nb1)
             .replace("#<PEND", "#%d" % (pend & 0xFF))
             .replace("#>PEND", "#%d" % (pend >> 8)))
mover, _ = assemble(msrc, MOVER_ADDR, {})
assert len(mover) <= 192, "mover overflows the tape buffer (%d bytes)" % len(mover)

src = (STUB.replace("MVDST", str(MOVER_ADDR))
           .replace("#MVLEN", "#%d" % len(mover))
           .replace("MVBYTES", ",".join(str(b) for b in mover)))
code, _ = assemble(src, 0x8009, {})
header = bytes([0x09, 0x80, 0x09, 0x80, 0xC3, 0xC2, 0xCD, 0x38, 0x30])
assert 9 + len(code) <= 256, "stub overflows the first page (%d bytes)" % len(code)

bank0 = header + code
assert 9 + len(code) <= 256, "stub overflows the first page (%d bytes)" % len(code)
bank0 += b"\xFF" * (256 - len(bank0)) + data[:B0 if nb1 else proglen]
bank0 += b"\xFF" * (BANKSZ - len(bank0))
bank1 = data[B0:]   # from $8000: the mover is in RAM, nothing reserved
bank1 += b"\xFF" * (BANKSZ - len(bank1))

# ONE flat image, banks concatenated - that is what an eprom burner wants,
# and what cartconv expects. Padded to 32K; banks 2 and 3 are unused.
rom = bank0 + bank1
rom += b"\xFF" * (ROMSZ - len(rom))
binout = os.path.splitext(OUT)[0] + ".bin"
open(binout, "wb").write(rom)

# build the .crt with vice's own tool rather than hand-rolling the format
rc = os.system('cartconv -t md -i "%s" -o "%s" -n "%s" >/dev/null 2>&1'
               % (binout, OUT, NAME))
assert rc == 0, "cartconv failed - is VICE installed?"

print("program : %d bytes -> $0801..$%04X" % (proglen, pend - 1))
print("stub    : %d bytes at $8009 (page 0 of bank 0)" % len(code))
print("mover   : %d bytes, copied to $%04X and run from RAM"
      % (len(mover), MOVER_ADDR))
print("bank 0  : %d program bytes (%d pages copied)"
      % (B0 if nb1 else proglen, nb0))
print("bank 1  : %d program bytes (%d pages copied)" % (rest, nb1))
print("written : %s (%d bytes, flat - burn this to a 27C256)" % (binout, len(rom)))
print("written : %s (Magic Desk, via cartconv)" % OUT)
