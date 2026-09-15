# MeshCore 64

A Commodore 64 chat client for the MeshCore mesh network.

A real C64 joins a LoRa mesh and sends and receives messages on it, using
**bit-zeal's mesh modem cartridge** — the Heltec V3 (ESP32-S3) carrier that
brings a LoRa radio onto the C64 user port. The C64 talks to the radio over
that port at 600 baud.

```
meshcore 64  0.92b
radio fw: mc64 1.17.1
connected as 59800697 on Public
f1 channels   f7 public

alice: anyone around tonight?
bob: just got home
Public +3> _
```

---

## Credit

This project stands entirely on
[**bit-zeal**](https://github.com/bit-zeal)'s work.

The **mesh modem cartridge** is bit-zeal's hardware. It is the thing that
makes any of this possible — without that board there is no LoRa radio on
the user port and no project here. MeshCore 64 is written specifically for
that cartridge and targets its wiring exactly.

bit-zeal also wrote
[**meshtastic64**](https://github.com/bit-zeal/meshtastic64-commodore-64),
the Commodore 64 client that made the cartridge useful in the first place,
for the Meshtastic network.

**MeshCore 64 is a beta port of that hardware over to MeshCore — a
complement to meshtastic64, not a replacement for it.** Same cartridge,
same user port, same 600 baud; a different mesh on the other end. If you
run Meshtastic, use meshtastic64 — it is the mature, original client for
this board. This exists for people whose mesh is MeshCore.

It is an independent, unofficial port and is not affiliated with or
endorsed by bit-zeal. No code was copied from meshtastic64 (it is
all-rights-reserved); only the general approach the hardware itself
dictates — user port at 600 baud, and PETSCII conversion.

---

## What it does

- **Chat on the mesh.** Type, press RETURN, it goes out over LoRa. Incoming
  messages appear as they arrive.
- **Channels.** `F1` lists the channels configured on your radio; pick one
  with a digit and everything — display and sending — scopes to it. `F7`
  jumps straight back to Public.
- **Tells you what you're missing.** `Public +3>` means 3 messages are
  waiting on other channels. Switch to one and they're replayed.

Not yet: contacts, direct messages, or repeater admin. Channels only.

---

## What you need

| | |
|---|---|
| A Commodore 64 | any model, real or emulated |
| bit-zeal's mesh modem cartridge | the Heltec V3 / ESP32-S3 board that carries the LoRa radio onto the user port |
| The firmware image | `meshcore64-1.17.1-0679dbef-merged.bin` |
| The program | `meshcore64.prg` |

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
load the program. It connects on its own.

Keys: `F1` channels · `F7` Public · `F3` status · `r` (in the channel list)
scan all 40 slots.

---

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

**600 baud is the right speed.** Tested against 1200 and 2400: both are
worse. The machine-code engine fixed how fast frames are *processed*, but
the KERNAL still receives each bit by hand in an interrupt, and its timing
margin shrinks as the rate climbs. At 1200 characters drop; at 2400 the
link is effectively dead.

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

## Known limits

- **The link carries 60 bytes per second, total** — shared with everything
  the radio reports, not just your messages. A short message is about a
  second on an idle mesh, longer on a busy one.
- **The radio is chatty.** It reports *every* LoRa packet it overhears,
  whether or not it's addressed to you, and on a 600-baud link that's the
  main reason a busy mesh feels slow. Left as-is to keep the firmware
  stock.
- **No scrollback.** Switching channels replays what you missed, but
  earlier history isn't kept.
- **Channel slots can have gaps.** The channel list normally stops scanning
  after a few empty slots, which is fast but misses a channel sitting above
  a gap. Press `r` in the list to sweep all 40 (about 40 seconds).
