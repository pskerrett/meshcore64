# testing

**Not a release.** These are isolation builds for working out why the
2400-baud pairing does not connect on real hardware.

600 baud is the speed v1.2d was proven on. Pairing the **v2.2d client** with
a **600-baud firmware** changes one variable at a time:

| result | conclusion |
|---|---|
| connects | the v2.2 client and its RS-232 driver are fine on real hardware, and the fault is specific to 2400 |
| does not connect | the fault is in the client's driver or the firmware pairing, not the speed |

## What is here

| file | what it is |
|---|---|
| `meshcore64-v2.2d-600.crt` | v2.2d client, **600 baud**, cartridge |
| `meshcore64-v2.2d-600.prg` | the same, as a program |
| `meshcore64-v2.2d-600-c64-eprom.bin` | the same, flat 32K for a 27C256 — a C64 EPROM image, **not** radio firmware |

A matching 600-baud Bluetooth firmware is being built and will land here
next. **Both halves must be 600** — that is the whole point of these
builds, and mixing speeds is what sent the first hardware test wrong.

The client is identical to the release except for the bit-period
constants: same source, built with `python3 mlfull.py 7` instead of `10`.
It carries no test instrumentation, so it transmits only what you type.

From the splash you can tell which you are running: the banner reads
`meshcore 64 v2.2d` either way, so **check the firmware's OLED**, which
now reports its own build tag (`mc64 ble 600`, `mc64 ble 2400`, ...).
