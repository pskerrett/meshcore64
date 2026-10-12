# MeshCore 64 v2.0

The C64 client for MeshCore, rewritten in machine language with its own 5760-baud RS-232 driver.

**Assets** (all four program formats, plus the radio firmware that must go with them):

- `meshcore64-v2.0.prg`, `.d64`, `.crt` (Magic Desk 64K), `.bin` (flat 64K for a 27C512)
- `firmware-heltec-v3-ble-5760-v1.17.1-c64-5760-merged.bin` (flash at 0x0), `...-app.bin`, and the source patch

**Highlights**

- 5760 baud on a stock C64, PAL and NTSC, with the C64's screen on
- Channels, direct messages (a DM conversation lives in the channel list), nodes (companions, repeaters, room servers, sensors), login, telemetry, routes, radio settings
- Sent-message status in colour: white while typing, yellow sent, green when acked or repeated
- F7 jumps to the next channel with new messages; F5 scrolls back through history
- REU and GeoRAM/NeoRAM: history, node and channel lists, saved sessions that survive a reset (NeoRAM: a power-off)
- VIC-II Kawari: 80-column mode, F3 swaps 40/80
- Ultimate II+ real-time clock: read at start, radio clock synchronised, offset in Stats
- Purge nodes the radio has not heard from in N days
- Stats: battery, link, clock offset, last message, memory

Radio and client must both be the 5760 versions. Full documentation: README.
