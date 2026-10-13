# MeshCore 64 v2.0.2

**More nodes, and the lists no longer reload.**

- With an REU or GeoRAM/NeoRAM the C64 now holds **255 nodes** (96 without expansion memory; it was 160 / 96).
  The extra room is RAM that sat idle.
- When the table is full the **newest nodes are kept**: every node remembers when it was last heard, and a
  newer one replaces the oldest instead of being dropped. The list title says "newest" then, e.g. "Companions (85) newest".
- Node lists are always marked as loaded, so a full table never forces a reload. After a restart with an REU or
  GeoRAM the saved node table is used as it is; otherwise **all node types load in the background** a few seconds
  after start (one pass instead of one per list). R in a list still refreshes it.
- A list shows at most 128 rows; node names are kept to 23 characters.
- F7 is labelled "channels".
- **First start after the update:** the node format changed, so a node table saved by an older version is dropped once and
  reloaded. Channel history is kept.
- Every format is still the same program. The radio firmware is unchanged (5760 baud).

The C64 client for MeshCore, rewritten in machine language with its own 5760-baud RS-232 driver.

**Assets** (all four program formats, plus the radio firmware that must go with them):

- `meshcore64-v2.0.2.prg`, `.d64`, `.crt` (Magic Desk 64K), `.bin` (flat 64K for a 27C512)
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
