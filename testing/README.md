# testing

## READ THIS FIRST — the hardware said transmit is fine

fixAC failed on hardware with F3 reading:

    frames/rej/hw 00 00 03 Nff Bff

255+ start bits, 255+ bytes, **not one valid frame**. Bytes are arriving
in quantity, so the radio IS answering us — **transmit works.** The
overnight theory (the interrupt-register race) was a transmit-side
theory and is **not what is blocking the link**. It may still be a real
latent bug; it is not this bug.

Firmware confirmed at 600, and the KERNAL build connects on the same
setup, so: **the fault is in our receive path and nothing else.**

### The difference between the two receive paths

The KERNAL samples half a bit in and **checks the start bit is still
low**, discarding the edge if it is not. Ours takes any falling edge and
immediately commits to nine samples, no check.

One false edge becomes one bad byte — and that byte's own 1→0
transitions look like more start bits, producing more bad bytes. That
cascade is exactly `Nff Bff frames 00`.

Why it passes in an emulator: VICE flips the line instantaneously and on
schedule, so every edge it produces IS a start bit and there is nothing
to reject. Real wiring has slope, ringing, and 3.3V logic driving a 5V
input — an edge that crosses the threshold twice on the way down gives
two triggers from one transition.

### Try these, in order

| cartridge | what it changes |
|---|---|
| `meshcore64-v2.2d-600-fixD.crt` | **start with this.** Verifies the start bit, as the KERNAL does. |
| `meshcore64-v2.2d-600-fixE.crt` | fixD **plus** driving RTS/DTR, which the KERNAL does and we do not. **See the warning below.** |

F3 now has a third counter, `g`, which **tests the theory rather than
assuming it**:

    frames/rej/hw XX XX XX nXX bXX gXX

| reading | meaning |
|---|---|
| `g` large | false edges are real; the check is doing the work |
| `g00`, frames climbing | fixed, and it was not glitches |
| `g00`, frames still `00` | **the theory is wrong.** Tell me — next step is sweeping the sample point on hardware, which was dismissed on margin arguments that now look too confident. |

### Warning about fixE

**fixE cannot be verified in the emulator.** VICE models RTS/DTR as live
handshake lines and throttles the link whenever they are driven — fixD
scores 41 and 41 on repeated runs, fixE scores 13 and 2. On the real
cartridge those pins go to LEDs with nothing listening, so the effect
cannot happen there, but that also means there was no way to test this
build before shipping it.

Treat it as a last-resort experiment, not a verified fix. It is here
because "our driver leaves RTS/DTR floating where the kernal drives
them" is a genuine difference between the working path and the broken
one, and floating pins sit next to RXD and FLAG on the connector.

---

## Earlier plan (transmit theory — superseded, kept for the record)

## Start here (morning of 24 Sep)

The KERNAL build **connects on real hardware**, which proves the wiring,
the 600-baud Bluetooth firmware, the client and the protocol are all fine.
**The fault is in our RS-232 driver**, and there is a specific, documented
reason it would fail on hardware while passing every emulator test.

Read **[DRIVER-600.md](DRIVER-600.md)** — it has the analysis, what was
ruled out and why, and how to read the on-screen diagnostics.

Flash `firmware-heltec-v3-ble-600-merged.bin`, then work down this list.
All three put `n<NN> b<NN>` on **F3**; those two numbers say which third
of the problem we are in even when a build fails.

There are **two** competing explanations, and the builds separate them.

| order | cartridge | why |
|---|---|---|
| 1 | `meshcore64-v2.2d-600-fixAC.crt` | **both fixes. Reach for this if you just want a working link.** |
| 2 | `meshcore64-v2.2d-600-base.crt` | **control.** Unchanged. Two minutes, and if it connects the driver was never broken at 600 and the problem is 2400-specific. |
| 3 | `meshcore64-v2.2d-600-fixA.crt` | interrupt-register race **only** |
| 4 | `meshcore64-v2.2d-600-fixC.crt` | handshake retries **only** |

3 and 4 are what tell us *which* theory was right. If fixAC works, they
are worth ten minutes so the fix is understood rather than superstition.

| result | conclusion |
|---|---|
| fixA works, fixC does not | the interrupt-register race |
| fixC works, fixA does not | we were talking too early, with no retry |
| both work | either suffices; ship both |
| neither, but fixAC works | the two faults compound |
| none work | read `n`/`b` on F3 — see DRIVER-600.md |

**Then 2400.** `meshcore64-v2.2d-2400-fixAC.crt` and `-2400-fixA.crt` are
built and waiting, paired with the release
`firmware-heltec-v3-2400-merged.bin`.

`meshcore64-v2.2d-600-fixB.crt` is a **600-only** fallback if fixA turns
out to have a flaw of its own — it fails at 2400 by design, see
DRIVER-600.md.

All three pass in the emulator. That proves only that they break nothing:
the bug they target is one VICE does not reproduce, so the emulator
cannot confirm the cure either. Only the hardware can.

---

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
