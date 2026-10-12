#!/usr/bin/env python3
"""
Wrap the program in an autostarting EasyFlash cartridge (.crt) -- "MeshCore 64 EZ".

EasyFlash is a banked cartridge (CRT type 32) with 8K ROML banks at $8000 and 8K ROMH
banks at $A000/$E000 (two flash chips), selected by a register at $DE00; $DE02 sets the
GAME/EXROM lines in software. Flash can be rewritten by the C64 itself.

Boot, step by step:
  1. Reset starts in Ultimax mode: the CPU reads the reset vector from ROMH bank 0 ($FFFC).
     That boot code ($E000) copies a three-instruction routine to $0100 and jumps there,
     because switching modes changes the memory under the program counter.
  2. The routine writes $86 to $DE02 (8K mode: ROML + KERNAL visible) and jumps through the
     KERNAL reset vector. The KERNAL finds the CBM80 signature at $8004 of ROML bank 0 and
     starts the stub at $8009, exactly as for the Magic Desk cartridge.
  3. The stub copies a mover to the tape buffer; the mover copies the program out of ROML
     banks 0..n into RAM at $0801, writes $04 to $DE02 (cartridge off: BASIC comes back)
     and RUNs the program. From then on it is the ordinary program in ordinary RAM.

The program is the normal v2.0 build, byte for byte; only the cartridge wrapper differs.
"""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from asm import assemble

PRG  = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "meshcore64.prg")
OUT  = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "meshcore64-ez.crt")
NAME = "MESHCORE 64 EZ"

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
# Bank 0 carries up to B0 bytes; every later bank a full 8K. From v2.3.1
# the client has a second code segment and no longer fits in two.
if proglen <= B0:
    rest = 0
    nb0 = (proglen + 255) // 256
else:
    rest = proglen - B0
    nb0 = (B0 + 255) // 256
later = []                       # pages to copy from bank 1, 2, ...
r = rest
while r > 0:
    later.append((min(r, BANKSZ) + 255) // 256)
    r -= BANKSZ
# 32K (27C256) while it fits; past four banks, 64K (27C512, same 28-pin
# footprint -- Magic Desk takes up to 128K). The .crt for an Ultimate does
# not care either way.
if 1 + len(later) > ROMSZ // BANKSZ:
    ROMSZ = 65536
NBANKS = ROMSZ // BANKSZ
assert 1 + len(later) <= NBANKS, "needs %d banks, the ROM has %d" % (1 + len(later), NBANKS)
EPROM = "27C256" if ROMSZ == 32768 else "27C512"
nb1 = later[0] if later else 0
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
; switch the cartridge off so BASIC ROM comes back
        lda #4
        sta 56834           ; $DE02: both GAME and EXROM released = cartridge off

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

# one copy block per later bank; each continues the stream where the last
# left off, so only the bank number and page count differ
banks_src = "".join(BANK1.replace("lda #1\n", "lda #%d\n" % (i + 1), 1)
                         .replace("#NB1", "#%d" % n)
                    for i, n in enumerate(later))
msrc = (MOVER.replace("@BANK1@", banks_src)
             .replace("#NB0", "#%d" % nb0)
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
# later banks from $8000: the mover is in RAM, nothing reserved
rom = bank0
for i in range(len(later)):
    chunk = data[B0 + i * BANKSZ:B0 + (i + 1) * BANKSZ]
    rom += chunk + b"\xFF" * (BANKSZ - len(chunk))

# --- the EasyFlash image ------------------------------------------------------
# ROMH bank 0: boot code at $E000, vectors at $FFFA. Assembled for $E000.
BOOT = """
boot:   sei
        ldx #255
        txs
        cld
        ldx #7              ; copy the 8 bytes of bcode to $0100
cp:     lda bcode,x
        sta 256,x
        dex
        bpl cp
        jmp 256
bcode:  lda #134            ; $86: 8K mode, ROML and KERNAL visible
        sta 56834           ; $DE02
        jmp (65532)         ; through the KERNAL reset vector
rtiv:   rti
"""
bootcode, bsyms = assemble(BOOT, 0xE000, {})
assert bootcode[-1] == 0x40 and len(bootcode) - 1 - (bsyms["bcode"] - 0xE000) == 8, "bcode must be 8 bytes"
rti = bsyms["rtiv"]
romh0 = bootcode + b"\xFF" * (0x1FFA - len(bootcode))
romh0 += bytes([rti & 255, rti >> 8, 0x00, 0xE0, rti & 255, rti >> 8])   # NMI, RESET, IRQ
assert len(romh0) == 8192

assert 1 + len(later) <= 64   # ROML banks 0..63

def chip(bank, addr, data):
    assert len(data) == 8192
    return b"CHIP" + struct.pack(">IHHHH", 16 + 8192, 2, bank, addr, 8192) + data

roml = [bank0] + [rom[BANKSZ * (i + 1):BANKSZ * (i + 2)] for i in range(len(later))]
chips = b""
for i, d in enumerate(roml):
    chips += chip(i, 0x8000, d)
    if i == 0:
        chips += chip(0, 0xA000, romh0)
hdr = b"C64 CARTRIDGE   " + struct.pack(">IHHBB", 0x40, 0x0100, 32, 1, 0) + bytes(6) + NAME.encode().ljust(32, b"\0")
assert len(hdr) == 0x40
open(OUT, "wb").write(hdr + chips)
print("program : %d bytes -> $0801..$%04X" % (proglen, pend - 1))
print("stub    : %d bytes at $8009 (page 0 of ROML bank 0)" % len(code))
print("mover   : %d bytes, copied to $%04X and run from RAM" % (len(mover), MOVER_ADDR))
print("boot    : %d bytes at $E000 (ROMH bank 0), vectors at $FFFA" % len(bootcode))
print("banks   : ROML 0..%d carry the program" % len(later))
print("written : %s (EasyFlash, CRT type 32)" % OUT)
