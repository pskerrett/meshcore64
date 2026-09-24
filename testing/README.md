# testing

**Not a release.** Isolation builds for working out why the 2400-baud
pairing does not connect on real hardware.

v1.2d works on this hardware at 600 baud using the KERNAL's RS-232. v2.2
does not connect at 2400 using its own driver. Three things changed at
once — **speed**, **driver**, and **firmware build** — so these separate
them one at a time.

## The ladder

Work down it. Each rung changes one thing from the rung above.

| # | client | firmware | what a PASS proves |
|---|---|---|---|
| 1 | `-600-kernal` | BLE 600 | the whole stack works at 600 with the KERNAL. Isolates **my driver**. |
| 2 | `-600` | BLE 600 | my driver is fine at 600 — so the fault is specific to **2400**. |
| 3 | release `v2.2d` | BLE 2400 | this is the combination that currently fails. |

- **1 passes, 2 fails** → my RS-232 driver is the problem, at any speed.
- **1 and 2 pass, 3 fails** → the fault is speed-specific: bit timing,
  most likely the NMI-latency constant tuned only in an emulator.
- **1 fails** → the fault is below all of that — the BLE firmware's
  hardware-serial path, or the wiring.

**Both halves must be the same speed.** Flashing a 600 firmware against a
2400 client, or the reverse, boots perfectly and never exchanges a byte.
That is what went wrong on the first hardware attempt. The firmware now
reports its own build on the **OLED** (`mc64 ble 600`, `mc64 ble 2400`),
so you can confirm what is on the board without USB.

## Files

| file | what it is |
|---|---|
| `meshcore64-v2.2d-600-kernal.crt` / `.prg` | v2.2 client, 600 baud, **KERNAL RS-232** — my driver bypassed entirely |
| `meshcore64-v2.2d-600.crt` / `.prg` | v2.2 client, 600 baud, **my driver** |
| `*-c64-eprom.bin` | the same programs as flat 32K images for a 27C256 — C64 EPROM images, **not** radio firmware |
| `firmware-heltec-v3-ble-600-merged.bin` | Bluetooth companion firmware at **600 baud** — flash for rungs 1 and 2 |
| `firmware-heltec-v3-usb-2400-merged.bin` | **USB** companion firmware at 2400 — the configuration v1.2d was proven on, at the new speed |
| `src/mlkernal.py` | source of the KERNAL variant |

Flash firmware with:

```bash
esptool.py --chip esp32s3 write_flash 0x0 firmware-heltec-v3-ble-600-merged.bin
```

### The USB 2400 build

A fourth rung, for the theory that the Bluetooth companion is itself the
problem. v1.2d ran against the **USB** companion; the 2400 release uses
the **BLE** one, which had never been tested. Reading the source I could
not find a mechanism — the hardware serial is registered and enabled the
same way in both — but "I could not find it" is not "it is not there".

Pair `firmware-heltec-v3-usb-2400-merged.bin` with the **release**
`meshcore64-v2.2d.crt`. If that connects and the BLE 2400 pair does not,
the BLE build is the fault.

Note this firmware also restores the USB companion interface, which the
BLE env does not define — so you can configure the node over USB again
rather than only over Bluetooth.

## About the KERNAL build

Same client throughout — menus, node list, telemetry, archive, colour.
Only the RS-232 layer differs: `SETLFS`/`OPEN` on device 2, receive by
draining the KERNAL's own ring, transmit by `CHKOUT` and `CHROUT`. Our NMI
handler is never installed.

Three things that port forced, all found by smoke testing rather than
reasoning:

- **Zero page had to move.** `$F7-$FA` *are* the KERNAL's RS-232 buffer
  pointers; the client only had them because it replaced the KERNAL.
- **`CHKIN` arms the receiver but also redirects `GETIN`.** Leaving the
  channel open meant the keyboard routine read the *radio*, so incoming
  traffic was typed into the input line and every byte that happened to be
  13 sent it back out as a chat message. `CHKIN` once to arm, then
  `CLRCHN`; the receiver stays armed.
- **Two second settle after OPEN.** v1.2d documents this: bytes sent or
  received before the KERNAL's engine is armed come out corrupted.
- **The cartridge lamps are off** in this build. Every lamp write puts a
  whole byte into `$DD01`, and under the KERNAL PB1/PB2 are RTS/DTR
  *outputs* — writing zeros there drives them low and kills reception.

Verified in VICE at 600: full handshake, 37 messages received, nothing
transmitted that was not typed.
