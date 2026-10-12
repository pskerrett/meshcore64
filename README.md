# MeshCore 64

**A Commodore 64 chat client for the [MeshCore](https://github.com/meshcore-dev/MeshCore) LoRa mesh.**
Version 2.0.1. Machine language, 5760 baud, all of it running on a stock C64.

<p align="center"><img src="docs/images/meshcore64-demo.gif" alt="MeshCore 64 in action" width="768"></p>

Plug a MeshCore radio into the user port and your C64 is a full mesh node's front end: read and send
messages on channels, send direct messages, browse every node the radio has heard, log in to
repeaters and pull telemetry, tune the radio, and keep months of history. It talks to the radio
with its own interrupt-driven RS-232 driver, so there is no BASIC, no KERNAL serial code and no
waiting around.

It also makes good use of the extras a well-equipped C64 may have:

| | add-on | what MeshCore 64 does with it |
|---|---|---|
| <img src="docs/images/addon-reu1750.jpg" width="170"> | **REU** (1700 / 1750 / 1764, or the Ultimate II+'s REU) | Message history for every channel, scrollback with F5, the node and channel lists cached, and the whole session **restored after a reset** |
| <img src="docs/images/addon-neoram.jpg" width="90"> | **GeoRAM / NeoRAM** | Everything the REU does. A **NeoRAM has a battery**, so history, channel list and node lists survive a power-off too |
| <img src="docs/images/addon-kawari.jpg" width="150"> | **VIC-II Kawari** | **80-column mode**: detected at start (with a short countdown you can cancel), every screen and menu in 80 columns, F3 swaps between 40 and 80 |
| <img src="docs/images/addon-ultimate.jpg" width="170"> | **Ultimate II+** (real-time clock) | Reads the clock at start, learns your time zone from the mesh, and **sets the radio's clock** when it is behind. Stats shows the offset |

None of them is required. Without any expansion memory you still get live chat, channels, nodes,
direct messages and a rolling history in main RAM; the program checks for each add-on when it starts and tells you what it found.
(Product photos are for illustration; the trademarks belong to their owners.)

---

## A tour

### Start

<img src="docs/images/01-splash.png" width="576"> <img src="docs/images/02-start.png" width="576">

The splash, then a status screen that reports what it found: **video** (PAL or NTSC, detected),
**memory** (REU, GeoRAM or none, with the size), the **clock** (an Ultimate's RTC, or "none: set
from the mesh"), and the **display** (a Kawari gets "kawari detected, switching to 80 columns in
3 seconds": press any key to stay in 40). Then it connects at 5760 baud, shows the radio's id and
firmware, scans your channels and prints the mesh time next to the radio time, correcting the
radio if it is behind. Restored history is painted back under the boot text.

### Chat

<img src="docs/images/03-chat.png" width="576">

Every sender gets a colour of their own, and it is the same colour every time, live or in
history. A rule separates messages. The prompt shows the channel and, after the `+`, how many
messages are waiting on other channels: `Public +15>`.

What you type is **white** until it is sent. It turns **yellow** when the radio has taken it, and
**green** when the mesh has proved it: an ack for a direct message, or a repeat you can hear for a
channel message. Each further repeat flashes the name again, so you can watch a message spread:

<img src="docs/images/14-heard.png" width="576">

You can type up to 135 characters; long lines wrap cleanly.

### Menus

<img src="docs/images/04-menu.png" width="576"> <img src="docs/images/05-channels.png" width="576">

**F1** opens the menu over the conversation: Channels, Nodes, Stats, Radio actions, Add/remove
channel. The channel list shows unread counts and a star where you are. Pick with the digit keys
or the cursor keys.

### Nodes

<img src="docs/images/06-companions.png" width="576"> <img src="docs/images/07-repeaters.png" width="576">

**Nodes** lists what the radio has heard: companions, repeaters, room servers and sensors, with a
count in the title. Names are shown in full. Press `/` and type to filter, `R` to refresh the list
from the radio. Nodes announced while you are connected are added automatically (and saved, with
an REU or GeoRAM).

<img src="docs/images/08-search.png" width="576">

### Talk to a node

<img src="docs/images/09-node-actions.png" width="576"> <img src="docs/images/10-telemetry.png" width="576">

Pick a node and you can **send it a message**, **log in** (repeaters and rooms ask for a password;
a wrong one is reported), pull **telemetry** (battery voltage, temperatures: it tries a guest
login first, so nodes without a password work), **show** its route, or **wipe** the route.
Direct messages try the stored route first; if no ack arrives in about 13 seconds the route is
reset and the message is sent again by flood ("no ack - resent by flood").

<img src="docs/images/11-route.png" width="576">

### Direct messages are channels too

<img src="docs/images/12-direct-message.png" width="576"> <img src="docs/images/13-dm-in-channels.png" width="576">

A direct-message conversation behaves exactly like a channel: it has its own history and unread
count, and it **stays in the channel list** after the first message so you can come back to it. The
conversations are saved with the session when you have an REU or GeoRAM.

### F7: jump to new messages

<img src="docs/images/15-f7.png" width="576">

**F7** takes you to the next channel or conversation with unread messages. With nothing unread it
just steps to the next channel, so you can cycle through them all.

### History

<img src="docs/images/16-scrollback.png" width="576">

**F5** scrolls back through everything the REU or GeoRAM has kept (the border turns red while you
are in history); F5 again goes further back, F7 comes forward, any other key returns to live.
After a reset the history is still there: the start screen says "REU detected ... restored".

### Stats

<img src="docs/images/17-stats.png" width="576">

Battery, storage and uptime from the radio; video standard; the **clock** (read live from an
Ultimate's RTC) and the **offset** between it and the radio; messages in and out; **how long ago the last message
was**; nodes known out of the maximum; the link speed and the receive-buffer peak; frames and
errors; and how full the REU / GeoRAM history is.

<img src="docs/images/hw-stats.jpg" width="576">

*The same screen on a real PAL C64 with an Ultimate II+ and a 2 MB GeoRAM.*

### Radio actions

<img src="docs/images/18-radio-actions.png" width="576"> <img src="docs/images/19-purge.png" width="576">

Frequency, bandwidth, spreading factor, coding rate and power; the node name; **Apply to node**;
send an advert (zero hop or flood). And **Purge old nodes...**: type a number of days and the C64
reads the radio's node list and removes every node it has not heard from in that long (favourites
are always kept), then tells you how many it checked and removed. The radio keeps nodes
forever until it is full, so this is how you keep the list tidy.

### Add a channel

<img src="docs/images/20-add-channel.png" width="576">

**Add/remove channel** creates a channel from a name and a key. Leave the key blank for a
`#hashtag` channel and the C64 works out the right key itself (SHA-256 of the name, in 6502).

---

## Getting started

### What you need

| | |
|---|---|
| A **Commodore 64** | real hardware, PAL or NTSC |
| A **MeshCore radio on the user port** | [bit-zeal's mesh modem cartridge](https://www.bit-zeal.com/s/shop): a Heltec WiFi LoRa 32 **V3** carried on a user-port board |
| The radio **firmware** in [`firmware/`](firmware) | MeshCore 1.17.1 Bluetooth companion with the C64 link at **5760 baud** |
| The **program** in [`release/`](release) | PRG, D64, CRT or BIN: pick one |

### 1. Flash the radio

With the Heltec **out of the cartridge** (bit-zeal warns against connecting USB while it is
seated), connect it to your computer by USB and flash it with the **MeshCore web flasher** in Chrome:

1. Download `firmware-heltec-v3-ble-5760-v1.17.1-c64-5760-merged.bin` from the
   [latest release](https://github.com/pskerrett/meshcore64/releases/latest).
2. Open <https://flasher.meshcore.io> in Chrome (or Edge).
3. Choose **Custom firmware**, then pick the `.bin` you just downloaded.
4. Select the board's serial port and flash.

It identifies itself as **`v1.17.1-c64-5760`** on the OLED splash ("mc64 ble 5760" under it) and
on the C64's boot screen. Then set the radio up as you would any MeshCore companion (region,
frequency, name, channels) with the MeshCore phone app: it is the Bluetooth companion build, so
that still works. MeshCore 64 reads the channels that are on the radio and can add more.

**The client and the firmware must run at the same speed.** If the C64 never gets past
"connecting at 5760 baud...", the radio is not running this firmware.

### 2. Run the program

| file | how |
|---|---|
| `meshcore64-v2.0.1.prg` | load it from anything: an Ultimate, SD2IEC, `LOAD"*",8,1` and `RUN` |
| `meshcore64-v2.0.1.d64` | a disk image: `LOAD"MESHCORE64",8` then `RUN` |
| `meshcore64-v2.0.1.crt` | a cartridge image (Magic Desk, 64K): runs the moment you switch on |
| `meshcore64-v2.0.1.bin` | the same cartridge as a flat 64K image for a **27C512** EPROM |
| `meshcore64-ez-v2.0.1.crt` | **MeshCore 64 EZ**: the same program on an **EasyFlash** cartridge ([details](#meshcore-64-ez-easyflash)) |

The cartridge copies the program into RAM and starts it, so after that it is the same program.
Because a cartridge cannot safely probe the GeoRAM window, **the cartridge builds do not look for
a GeoRAM**: with a GeoRAM or NeoRAM use the PRG or D64. An REU (including the Ultimate's) works
with every format, and so does the Ultimate's clock.

### Making a cartridge

**Ultimate II+ and similar:** copy `meshcore64-v2.0.1.crt` to the device and run it. Nothing to build.

**Your own EPROM cartridge:** burn `meshcore64-v2.0.1.bin` to a **27C512** (64K). It is one flat image,
the eight 8K banks end to end, and the unused tail is `$FF` (erased state). The `.crt` is the same
contents in the container emulators expect: it is **Magic Desk** (cartridge type 19), so VICE
runs it too (`x64sc -cartcrt meshcore64-v2.0.1.crt`).

| | |
|---|---|
| ROM | 27C512, 64K. About 41K is used (banks 0-4); the rest is `$FF` |
| Maps at | `$8000`-`$9FFF`, one 8K bank at a time |
| Bank register | write `$DE00`: low bits = bank, **bit 7 = switch the cartridge off** |
| `/EXROM` (edge pin 9) | tied **low** |
| `/GAME` (edge pin 8) | left high (not connected) |
| Autostart | the `CBM80` signature at `$8004` is already in the image |

The hardware is the EPROM plus a '273-style latch that decodes a write to `$DE00` (an Ultimate does
this in software). At power-on the ROM stub copies a small mover routine to the tape buffer at
`$033C`, and that routine copies the program from the banks into RAM and switches the cartridge
off, so BASIC comes back and the program runs from ordinary RAM. The bank switching has to run
from RAM: code that is itself executing inside the cartridge window would change under the CPU
the moment the latch is written.

**Status:** the `.crt` image is tested and works (VICE and a real Ultimate II+). Burning the `.bin` to a
physical EPROM cartridge **has not been tried yet**.

**Bank bits:** the eight banks need **three** bank bits from the latch, wired to the 27C512's A13, A14
and A15. A board built for the earlier 32K image only drives two; if A15 is tied low, the C64 only ever
sees the first 32K and the program will not start.

Why 64K: the program image is about 33K, more than the four banks a 27C256 gives. Why Magic
Desk at all: a plain 16K cartridge would replace BASIC at `$A000`, which the C64 needs to start
the program.

### MeshCore 64 EZ (EasyFlash)

**`meshcore64-ez-v2.0.1.crt`** is MeshCore 64 2.0.1 for an **EasyFlash** cartridge (CRT type 32), such as an
EasyFlash 3, or for an Ultimate II+ running an EasyFlash cartridge image. It is the same program,
byte for byte, as the cartridge build above; only the cartridge wrapper differs. Nothing in the
program changed and it never writes to the flash.

- **Ultimate II+:** run the `.crt` from its menu.
- **EasyFlash 3:** write the `.crt` to the cartridge with EasyProg (or any tool that programs EasyFlash
  `.crt` files). It uses ROML banks 0-4 for the program and ROMH bank 0 for the boot code, leaving the
  rest of the 1 MB free.
- **How it starts:** reset boots in Ultimax mode from ROMH bank 0, which switches to 8K mode and lets the
  KERNAL autostart the stub in ROML bank 0. The stub copies the program into RAM, switches the cartridge
  off, and runs it, exactly as the Magic Desk cartridge does. Details in [`src/mkcart_ez.py`](src/mkcart_ez.py).

**Status:** tested in VICE only (NTSC and PAL, with and without an REU); it has **not been tried on real
EasyFlash hardware or an Ultimate II+ yet**. VICE prints a harmless warning that it found no EasyAPI
(the library other EasyFlash programs use to write flash); this cartridge never writes flash, so it
does not carry one. A physical EasyFlash occupies the expansion port and has 256 bytes of its own RAM at
`$DF00`, where an REU has its registers, so do not expect to use an REU or GeoRAM *with* a physical EasyFlash.

### Keys

| key | does |
|---|---|
| `RETURN` | send what you typed |
| `DEL` | delete |
| `F1` | menu (also: back out of any menu or list) |
| `F3` | with a Kawari: swap 40 / 80 columns |
| `F5` | scroll back (needs an REU or GeoRAM) |
| `F7` | jump to the next channel with new messages; with none, cycle channels |
| in a node list | `RETURN` pick, `/` filter, `R` refresh from the radio |
| in the channel list | `0`-`9` or cursor keys, `RETURN`, `R` rescan the radio |

---

## About the link

The radio's second UART (GPIO45 RX / GPIO46 TX) is wired to the user port. The KERNAL's RS-232
cannot be trusted much beyond 600 baud (it samples every bit by hand inside an interrupt), so
MeshCore 64 has its **own driver**: timer-driven transmit, and a receiver that arms itself on the
start bit, samples each bit near its centre, and ignores interrupt sources it did not enable (the
CIA latches them regardless of the mask, which is what defeated the first attempts on real
hardware). It runs at **5760 baud**, which leaves about 60 cycles of margin per bit with the screen
on, in both PAL and NTSC. 7200 had no margin left: it dropped the odd character.

The firmware is stock MeshCore 1.17.1 plus [a small patch](firmware/meshcore64-firmware-v1.17.1-c64-5760.patch)
that selects UART 2, the pins and the baud rate for the companion link and lengthens the OLED version
string. The wire protocol is documented in [docs/serial-protocol.md](docs/serial-protocol.md); the
engineering notes behind the driver are in [docs/engineering](docs/engineering).

## Building

Everything is built by Python scripts; there are no other dependencies than VICE's `cartconv` and
`c1541` for the cartridge and disk images.

```bash
src/build.sh            # -> release/meshcore64-v2.0.1.{prg,crt,bin,d64}; byte-identical to the published files
pip install py65
src/tests/run-sims.sh   # the 6502 simulator suites
```

[`src/tests/fakeradio.py`](src/tests/fakeradio.py) is a MeshCore radio simulator for VICE (set
`-rsuserdev 0 -rsdev1 127.0.0.1:25232`); [`src/tests/run-vice.sh`](src/tests/run-vice.sh) shows how the
screenshots above were made. The program is a single readable file, [`src/meshcore64.py`](src/meshcore64.py),
with its own assembler; it is laid out in five code areas that fit the C64's 64K around the buffers.

## Tested

- Real hardware: an NTSC and a PAL C64 with the mesh modem cartridge, an Ultimate II+ (REU, clock) and a 2 MB GeoRAM/NeoRAM.
- VICE (NTSC and PAL): boot of every format, and long runs with several hundred messages, adverts and
  repeats on no expansion, an REU and a GeoRAM, with a scripted radio. No crashes, and the link error counter
  stays at 0-2 per run.
- 6502 simulators for the receiver timing, the menus, 80-column reflow, routes, F7, the purge, the stats.

Known limits: the 80-column mode needs a Kawari whose firmware has its 80-column mode (the same one Novaterm's
80-column driver uses). A message at the full 135 characters may be refused by the radio; the client
then says "the radio refused that message". The radio keeps at most 350 nodes; the C64 holds up to 160
(96 without expansion memory), so purge old nodes now and then.

## Credits

This stands on [**bit-zeal**](https://www.bit-zeal.com/s/shop)'s work: the **mesh modem cartridge** is
their hardware, MeshCore 64 targets its wiring exactly, and their
[meshtastic64](https://github.com/bit-zeal/meshtastic64-commodore-64) is the original client for the
board (if you run Meshtastic, use that). This is an independent, unofficial port for
[MeshCore](https://github.com/meshcore-dev/MeshCore). Thanks to the VICE team, the VIC-II Kawari
project, and Gideon Zweijtzer's Ultimate II+.

(c) 2026 -W9PDS
