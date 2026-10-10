# MeshCore 64 — v2.4b (2400 baud)

**`meshcore64-v2.4b-2400.crt`**. The `.prg` and `.bin` (flat 32K, for a 27C256) are the same build.
The banner reads `meshcore 64  v2.4b`.

## Radio firmware: you MUST flash the 2400 image

**`firmware-heltec-v3-ble-2400-v1.17.1-c64-merged.bin`** (full flash at 0x0).
MeshCore 1.17.1 companion, Bluetooth on, plus the C64 user-port link at
**2400 baud** (UART2, GPIO45 RX / GPIO46 TX). It identifies itself as
**`v1.17.1-c64`**: on the OLED splash (with "mc64 ble 2400" under it) and on
the C64's boot screen (FW line). `...-app.bin` is the app-only image for
updates. `meshcore64-firmware-v1.17.1-c64.patch` is the source change
against MeshCore 1.17.1 (env `Heltec_v3_companion_radio_ble`).

The C64 and the radio must run at the same speed: the boot screen now says
"connecting at 2400 baud..." -- if it never gets past that, check the radio
is on this firmware.

## What's new: 4x faster link

v2.4b talks to the radio at **2400 baud** (was 600) using its own RS-232 driver
instead of the KERNAL's, which cannot go above 600 reliably. Messages, channel
scans and node lists arrive four times faster.

Getting there took two fixes to the driver, both found on real hardware:
- The CIA latches the FLAG (start-bit) interrupt on every falling edge of the
  serial line, even when it is masked. The receiver now ignores sources it has
  not enabled, as the KERNAL does. (This is why the driver worked in the
  emulator but never on a real C64.)
- The radio starts its reply within a fraction of a bit of our last stop bit.
  The receiver is now armed before that stop bit ends, so the first byte of
  every reply is no longer lost.

## Fix: #hashtag channels

Adding a `#hashtag` channel with the key left blank now gives it the real key
(the first 16 bytes of SHA-256 of the name, computed on the C64). Before, it
was given an all-zero key: you could not read anyone on that channel and they
could not read you. **If you added # channels with an older version, remove
each one and add it again** (F1 > add/remove channel), leaving the key blank.

## Connecting screen

Shows the speed it is connecting at ("connecting at 2400 baud...").

## Splash

Now credited bottom right: © 2026 -W9PDS.

## Tested
- Real C64 (NTSC) + Heltec V3 at 2400: probe 3/3 exact replies, full client
  sends/receives in Public and re-added # channels.
- Simulator (6502 + CIA model): receiver byte-exact at 600/1200/2400; SHA-256
  matches Python's hashlib on 70 names.
- VICE: cartridge boots, splash, connect.
- Not yet: a long soak on a very busy mesh; PAL machines.

## In this branch
- `meshcore64-v2.4b-2400.*` -- the C64 client (cart image .crt, flat 27C256 .bin, .prg)
- `firmware-heltec-v3-ble-2400-v1.17.1-c64-*.bin` + `meshcore64-firmware-v1.17.1-c64.patch` -- the radio
- `src/` -- client sources (`python3 src/mlfull.py 10 out.prg 0 0 275`, then `src/mkcart.py out.prg out.crt`);
  `src/patches/` records the v2.4 changes (already applied to `mlfull.py`)
- `docs/path-to-higher-speeds.md`, `docs/speed-reports/` -- how 2400 baud was made to work, step by step
- `md5.txt` -- checksums of the binaries
