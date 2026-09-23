# MeshCore 64

> ### 🧪 You are on the `v2.0-beta` branch
>
> **v2.01** is the client rewritten entirely in machine language with its
> own RS-232 driver, reaching **2400 baud** where v1.x tops out at 600.
> **[Read V2.md →](V2.md)**
>
> It is a beta and has only been tested in an emulator. The stable client
> is the BASIC one on [`main`](https://github.com/pskerrett/meshcore64/tree/main).
> Hardware setup, firmware flashing and the companion patch below are
> unchanged and apply to both.


A Commodore 64 chat client for the MeshCore mesh network.

A real C64 joins a LoRa mesh and sends and receives messages on it, using
**bit-zeal's mesh modem cartridge** — the Heltec V3 (ESP32-S3) carrier that
brings a LoRa radio onto the C64 user port. The C64 talks to the radio over
that port at 600 baud.

```
MeshCore 64   v1.2c
radio fw: mc64 1.17.1
connected as 59800697 on Public
f1 channels   f7 public
```

---

## Credit

This project stands entirely on
[**bit-zeal**](https://www.bit-zeal.com/s/shop)'s work.

The **mesh modem cartridge** is bit-zeal's hardware. It is what
makes any of this possible. MeshCore 64 is written specifically for
that cartridge and targets its wiring exactly.

bit-zeal wrote the original Meshtastic client for the C64
[**meshtastic64**](https://github.com/bit-zeal/meshtastic64-commodore-64).


**MeshCore 64 is a port of that hardware over to MeshCore.
It is the same cartridge, but a different mesh on the other end. If you
run Meshtastic, use meshtastic64 — it is the mature, original client for
this board. This exists for people who want to try MeshCore.

This is an independent, unofficial port and is not affiliated with Jim_64. 

---

## What it does

- **Chat on the mesh.** Type, press RETURN, it goes out over LoRa. Incoming
  messages appear as they arrive.
- **Channels.** `F1` lists the channels configured on your radio; pick one
  with a digit and everything — display and sending — scopes to it. `F7`
  jumps straight back to Public.
- **Tells you what you're missing.** `Public +3>` means 3 messages are
  waiting on other channels. Switch to one and they're replayed.
- **Lights up the cartridge.** All six lamps sweep at startup, then a
  ripple on every incoming message and a flash when you send.
- **Scrolls back, with a RAM Expansion Unit.** `F5` pages back through
  screens of history, `F7` pages forward, anything else returns to live.
  The border turns red while you are looking at history. Without an REU
  the client behaves exactly as it does otherwise, and `F5` is not
  offered.

Not yet: contacts, direct messages, or repeater admin. Channels only.

---

## What you need

| | |
|---|---|
| A Commodore 64 | any model, real not emulated |
| bit-zeal's mesh modem cartridge | the Heltec V3 / ESP32-S3 board that carries the LoRa radio onto the user port |
| The firmware image | `meshcore64-1.17.1-0679dbef-merged.bin` |
| The program | `meshcore64.prg`, `meshcore64.d64` (disk), or `meshcore64.crt` (cartridge) |

---

## Getting started

All of the setup happens with the Heltec board **out of the cartridge**.
bit-zeal warns against connecting USB while it is seated in the cart, and
steps 1–3 all need USB.

**1. Get the firmware.** Either patch a current MeshCore
`companion_radio_usb` build for the Heltec V3 yourself — see
[Updating to a newer MeshCore release](#updating-to-a-newer-meshcore-release)
below — or just use the prebuilt image here:

```bash
esptool.py --chip esp32s3 write_flash 0x0 meshcore64-1.17.1-0679dbef-merged.bin
```

Note this replaces Meshtastic on the board. To go back to meshtastic64,
reflash the Meshtastic firmware; the hardware is unchanged either way.

**2. Set up the companion over USB.** Connect to the board with any
MeshCore client over USB and configure it as you would any companion node —
region and frequency, node name, and whatever else your local MeshCore
setup expects. The patched firmware keeps USB working alongside the
600-baud user-port link, so this is exactly the normal MeshCore setup
process.

Get this right before moving on: if the radio isn't on your local
frequency, the C64 will connect happily and simply never hear anything.

**3. Set up your channels** in that same client. MeshCore 64 reads whatever
is already on the radio — it doesn't create channels.

**4. Seat the board in the cartridge**, plug the cart into the C64, and
start the program. It connects on its own.

Three ways to run it. Load `meshcore64.prg` the usual way; or put
`meshcore64.d64` on a disk and `LOAD"MESHCORE64",8`; or put
`meshcore64.crt` on a cartridge and it runs the moment you switch on — the
mesh modem is on the user port, so the expansion port is free for it.

## Known limits

- **The link carries 60 bytes per second, total** — shared with everything
  the radio reports, not just your messages. A short message is about a
  second on an idle mesh, longer on a busy one.
- **The radio is chatty.** It reports *every* LoRa packet it overhears,
  whether or not it's addressed to you, and on a 600-baud link that's the
  main reason a busy mesh feels slow. 
- **Scrollback needs an REU.** With a RAM Expansion Unit, every message is
  archived per channel and `F5` pages back through it. Without one,
  switching channels still replays what you missed, but earlier history
  isn't kept and `F5` is not offered.
- **Channel slots can have gaps.** The channel list normally stops scanning
  after a few empty slots, which is fast but misses a channel sitting above
  a gap. Press `r` in the list to sweep all 40 (about 40 seconds).

---
---

# Technical reference

*Everything above is what you need to use MeshCore 64. Everything below is
how it is built and why it works the way it does — skip it unless you are
compiling it yourself, burning a cartridge, or curious about the
internals.*

## Building the program

The source keeps every comment. The build strips them, and that is not
cosmetic: with comments intact the program compiles to about 36KB, which
leaves under 2.5KB for variables against the roughly 2.8KB the arrays
need, and it fails with `?OUT OF MEMORY` while building a string.
Stripped, it is about 10KB and leaves 28KB free.

Compiling needs VS64's BASIC tokeniser, which is plain Python and does
not need the editor:

```bash
git clone https://github.com/rolandshacks/vs64
BC=/path/to/vs64/tools/bc.py ./build.sh
```

`build.sh` passes **`-c`**, the tokeniser's own comment stripper, which is
what keeps the build small enough to run:

```bash
python3 bc.py -c -o meshcore64.prg meshcore64.bas
```

Drop the `-c` and you get a readable listing on the C64 — useful for
poking around, but too large to run. Other flags worth knowing: `-m`
writes a map file, which turns the line number in a `?ERROR IN nnn` back
into a line of source.

---

## Building a cartridge

The cartridge image is **Magic Desk** (`.crt` type 19) — a banked format,
and the banking is not optional. The reason is a squeeze:

- The program is about 12.5KB, so it **does not fit an 8K cart**.
- The expansion port exposes only two 8K windows, `$8000` and `$A000`, and
  `$A000` is where **BASIC ROM** lives. A 16K cart therefore *replaces*
  BASIC — leaving nothing to run a BASIC program with. A bigger EPROM
  doesn't help either: the C64 still only sees 8K at a time.

Magic Desk fixes both with one latch at `$DE00`. Its low bits select an 8K
bank; **bit 7 disables the cartridge outright**. So the cart copies bank 0
into RAM, switches to bank 1, copies the rest, then banks *itself* out —
BASIC reappears and `RUN`s the program, which from then on is an ordinary
BASIC program in ordinary RAM.

| | |
|---|---|
| ROM size | **32 KB** — a 27C256. Only the first two banks are used; the rest is `$FF` |
| Maps at | `$8000`–`$9FFF`, one 8K bank at a time |
| Bank register | write `$DE00` — low bits = bank, **bit 7 = disable cart** |
| `/EXROM` (edge pin 9) | **tied low** |
| `/GAME` (edge pin 8) | **left high** — not connected |
| Autostart | via the `CBM80` signature at `$8004`, already in the image |

Why 32K when only 16K is used: 32K is Magic Desk's **minimum**. VICE's own
`cartconv` rejects 8K and 16K images for this type outright, so a 16K burn
is not a valid Magic Desk cartridge even though 16K is all the data there
is. Burn the full 32K.

Hardware is an EPROM plus a '273-style latch decoding a write to `$DE00`.
The 1541 Ultimate II+ and similar do it in software with no extra parts —
and being software, they can supply the REU at the same time, so
scrollback works from cartridge.

Burn **`meshcore64.bin`** — one flat 32768-byte image, banks end to end,
which is what an EPROM burner wants. `meshcore64.crt` is the same contents
in the container emulators expect, so use that one for VICE. The padding is
`$FF`, which is also erased-EPROM state, so it burns cleanly.

*One trap if you build something like this yourself:* the code that writes
`$DE00` cannot itself be running inside the cartridge window. The instant
that write lands, the bytes under the program counter change — to program
data on a bank switch, to empty RAM on the bank-out — and the CPU runs off
into garbage with a blank screen and no other symptom. The cart's ROM stub
therefore does one thing: copy a small mover routine into the tape buffer
at `$033C` and jump to it. All the bank switching happens from there, in
RAM, where the banks moving beneath `$8000` cannot reach it.

## How it works

**The radio speaks binary.** MeshCore's companion protocol is framed
binary — a marker byte, a length, then a payload — not the line-based text
Meshtastic uses. Every frame is full of zero bytes, and C64 BASIC's `GET#`
cannot return a zero byte: an empty string means both "nothing arrived" and
"a real 0x00 arrived". So the client bypasses `GET#` and reads the KERNAL's
serial buffer directly.

**BASIC is too slow, so the serial engine is machine code.** At 600 baud a
byte lands every 17ms, but `GET#` alone costs about 50ms — a 3× deficit no
amount of BASIC tuning closes. A 113-byte 6502 routine at `$C000` drains
the buffer and reassembles frames, so BASIC only ever sees whole messages.
That single change took message latency from 3.4 seconds to 1.1, and kept
it flat under load instead of drifting into minutes.

**600 baud is the right rate — do not raise it.** Retested at 1.0, after
the machine-code work made rendering 6.6× faster, in case the earlier
failures had been the C64 failing to keep up. They were not:

| baud | syncs | sends | text |
|---|---|---|---|
| **600** | **54** | **2** | **clean** |
| 1200 | 32 | 0 | corrupted — `Public` rendered as `ubic`, wrong channel at the wrong index |
| 2400 | 1 | 0 | no channels found at all |

600 delivers *more* than 1200: corrupted frames cost retries and
mis-parses, so doubling the wire speed made the link slower in messages
actually delivered. The limit is the C64's KERNAL, which samples every
RS-232 bit by hand inside an interrupt — its timing margin shrinks as the
rate climbs until jitter starts mis-sampling. Going faster would mean
replacing that receiver outright (UP9600-style, driving the CIA shift
register), a far bigger job than anything here.

Worth knowing if you ever measure this yourself: at 1200 every *aggregate*
number looked healthy — clean handshake, full channel scan, queue drained
to zero — while the characters inside the frames were wrong. Frame counts
tell you a payload parsed, not that its bytes were right.

**Anything per-character belongs in machine code.** BASIC costs 20-56ms
*per character*, so converting a single 40-character message between ASCII
and the C64's character set took 2.3 seconds. That work happens in the
machine-code routine now, in about a millisecond. It is why messages
render quickly, why switching channels no longer freezes, and why pressing
RETURN sends immediately instead of pausing first.

**Messages are filtered for display, never for delivery.** The radio holds
one queue shared by every channel, so a message for a channel you aren't
watching still has to be collected — it's just not shown. Skipping it would
strand it and back the queue up. The same reason the channel list keeps
reading from the radio while it's on screen.

---

## Updating to a newer MeshCore release

The firmware is stock MeshCore plus a small patch — four build settings and
a few lines in one file — that points the companion serial link at the
cartridge's wiring. Nothing else is modified, so it should keep applying
cleanly as MeshCore moves on.

```bash
unzip meshcore64-patch.zip -d meshcore64-patch

git clone https://github.com/meshcore-dev/MeshCore
cd MeshCore
../meshcore64-patch/apply-patch.sh .
../meshcore64-patch/build-firmware.sh
```

`apply-patch.sh` is safe to re-run — it detects an already-patched tree,
falls back to a 3-way merge if upstream code has shifted around it, and
prints the handful of manual edits if it can't apply them itself.

`build-firmware.sh` reads MeshCore's own version and names the output
`meshcore64-<version>-<commit>.bin`, so the image always says which
upstream release it came from.

### What the patch changes, and why

| Change | Why |
|---|---|
| Use UART **2** | The shared code hardcodes UART 1, which on this board receives nothing at all regardless of pins or baud rate. This was the fix that made the link work. |
| Separate baud rate | The cartridge link runs at 600; USB stays at 115200. The original code hardcoded one rate for both. |
| Pins 45 (RX) / 46 (TX) | The cartridge's physical wiring. |

The version label is kept short (`mc64 1.17.1`) because the firmware's OLED
splash screen truncates anything longer, and lengthening its buffer would
mean patching code unrelated to serial I/O.

---

