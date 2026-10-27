# MeshCore 64 v2.4

**Start MeshCore 64 from a GeoRAM / NeoRAM with SYS 57000: no disk needed**

- **F1 > Settings > Write app** copies the version you are running onto the card. The line shows what the
  card holds now: `(card v2.4)`, `(card: none)`, or `(no copy)` if there is nothing to write (a card
  under 512 KB, or a copy that did not verify). RETURN writes it: the border steps once a page (about 2
  seconds), every byte is read back, and the launcher is switched on last, so a write that fails never starts.
- **After that, `SYS 57000` starts MeshCore 64 from the card** after a reset or power-on, with no disk.
  With a NeoRAM's battery the app and the session both survive a power-off.
  If something else has used the card since: `POKE 57342,0:POKE 57343,0:SYS 57000`.
- **Nothing else on the card changes.** At every start MeshCore 64 keeps a scratch copy of itself in the
  card's top three blocks (about half a second, read back); Write app copies that into blocks 0-2. Your
  channels, nodes and history (blocks 3 and up) are never touched, so to upgrade you load the new version
  from disk, choose Write app, and keep your session. Loading a version from disk never changes what
  SYS 57000 starts until you choose Write app.
- **Bigger cards keep more history.** Each of the nine history areas holds 512 lines on 512 KB (as before),
  **1024 on 1 MB, 2048 on 2 MB, 4096 on 4 MB**. Changing the size starts a new session on that card.

**Changed**

- **Data moved up** to make room for the app: it starts at block 3 now, so a card needs 256 KB or more
  (512 KB for Write app). **Sessions saved by v2.3 or earlier are not restored**: the first start of 2.4
  on a GeoRAM starts a new session (the node list reloads from the radio). The REU is unchanged.
- The launcher uses the card's first page, as other GeoRAM software does (NeoRAM-Drive, Maniac Mansion
  GOLD): only one of them can own SYS 57000 at a time.
- An Ultimate II+'s own GeoRAM only answers about 0.1 s after the Ultimate starts a program; the startup
  copy waits up to half a second for it.

Works with either radio firmware: `v1.18.0-c64-5760` (current) or `v1.17.1-c64-5760`.

**Assets**

- `meshcore64-v2.4.prg`, `.d64`, `.crt` (Magic Desk 64K), `.bin` (flat 64K for a 27C512)
- `meshcore64-ez-v2.4.crt` (EasyFlash)
- Radio firmware, MeshCore 1.18.0: `firmware-heltec-v3-ble-5760-v1.18.0-c64-5760-merged.bin` (flash at 0x0), `...-app.bin`, and the source patch
- The previous firmware, MeshCore 1.17.1 (`...v1.17.1-c64-5760...`), and its patch

Radio and client must both be the 5760 versions. Full documentation: README.

---

# MeshCore 64 v2.3

**F1 > Live dump is readable now**

- **Message text.** DMs and channel messages are encrypted on the air, so their bytes can never be read
  directly. The radio decrypts every message it has a key for, and the dump now prints that text on its
  own line, e.g. `[#test] W9PDS-BOT: ack`. On a busy mesh the text can arrive a few packets after its packet.
- **Words, not codes.** `Channel msg flood, 3 hops -50 dBm SNR 12.3 40 bytes` instead of `GRP FL h3`.
  Packet types, adverts (`repeater "W9PDS-rpt" key 3A7F19C2`), acks and region codes are spelled out.
- **Node names.** The to/from and every repeater in the path are shown by name when exactly one node in
  your list matches the hash (up to 14 per packet); unknown or ambiguous hashes stay in hex.
- **T hides types.** The dump opens showing everything. T pauses it and lists the five types
  (`1 adverts:on 2 channel:on 3 direct:on 4 acks:on 5 other:on`); 1-5 hide or show one, any other key
  carries on. Hidden types reset the next time you open the dump.
- **Repeats collapse.** The same packet heard again within 10 seconds (a flood passed on by another
  repeater) prints one line under the first, `heard x2 via ORD-LISLE-EGG-RO -48 dBm`, instead of a new block.
- **Channels by name and colour.** The first time the dump opens after a boot it works out each channel's
  hash (about 0.6 s a channel, shown as `-- [#bot] is channel CA --`). Packets on your channels then say
  `[#bot]` in that channel's colour, and its decrypted text uses the same colour. **C** cycles all channels,
  then each one alone. The channel secrets this needs are kept in the GeoRAM or REU when there is one,
  else in main RAM.
- **P (payload)** is off whenever the dump opens; it marks encrypted payloads as encrypted and shows their bytes as hex only.

**Fixed**

- SNR decimals in the Live dump were wrong (6.0 showed as 6.3, 6.5 as 6.8).

Works with either radio firmware: `v1.18.0-c64-5760` (current) or `v1.17.1-c64-5760`.

**Assets**

- `meshcore64-v2.3.prg`, `.d64`, `.crt` (Magic Desk 64K), `.bin` (flat 64K for a 27C512)
- `meshcore64-ez-v2.3.crt` (EasyFlash)
- Radio firmware, MeshCore 1.18.0: `firmware-heltec-v3-ble-5760-v1.18.0-c64-5760-merged.bin` (flash at 0x0), `...-app.bin`, and the source patch
- The previous firmware, MeshCore 1.17.1 (`...v1.17.1-c64-5760...`), and its patch

Radio and client must both be the 5760 versions. Full documentation: README.

---

## Earlier: v2.2

This release includes everything new since v2.0.2, which covers v2.1 and v2.2.

**New**

- **F1 > Live dump.** Every packet the radio hears: time, type, route, hops, RSSI/SNR, size, to/from or
  channel hash, advert key/kind/name, transport code and path. Full 80 column screen in 80 column mode.
  Keys: SPACE pause, P payload rows as hex + text, T type filter, F1 / RUN-STOP back.
- **Cartridge lamps.** All six: a sweep when a message comes in, a double flash when one is sent, back-and-forth
  when a repeater sent yours on, and the unread count in binary when idle, on every screen.
- **Timestamps.** Each message's time sits on the rule above it, in light grey: `09:41` today,
  `Sat 17 Oct 22:58` for older ones. Local time when the time zone is known (Ultimate II+ clock),
  otherwise UTC. The sender's clock is used; when it is missing or far ahead, the time the message arrived.
  In 80 columns the time is at the right end of the rule.
- **Alert sound.** The SID plays a short blip for a channel message and a rising two-note chime for a DM.
- **F1 > Settings.** Sound: all / DMs / off. Timestamps: on / off. Kept with the saved session (REU / GeoRAM).
- **F1 > Stats** shows the program version and the radio firmware.
- **Radio actions > Path hash** sets 1, 2 or 3-byte path hashes (RETURN steps; saved on the radio).

**Fixed**

- **Switching channels showed another channel's messages.** Only channels 0-5 had their own history;
  every channel from slot 6 up shared one, and all DM conversations shared another. Now each channel or
  DM that gets messages has its own (up to eight at a time; the quietest is recycled when a ninth needs one).
- **The channel scan at start could hang** if one reply from the radio was lost on a busy mesh: unrelated
  traffic kept restarting its timeout, and keys were ignored. The timeout now runs from the request, and a
  slot whose reply is lost is asked for again.
- A quote byte in a packet no longer scrambles the colours.

**Changed**

- The C64 holds up to 234 nodes with an REU or GeoRAM (was 255): the room went to the new code. 96 without.
- First start after the update: the node list reloads once in the background. Channels 0-5 keep their
  history; the old shared histories (channels 6 and up, DMs) start empty.

The radio firmware is unchanged (5760 baud).

The C64 client for MeshCore, rewritten in machine language with its own 5760-baud RS-232 driver.

**Assets**

- `meshcore64-v2.2.prg`, `.d64`, `.crt` (Magic Desk 64K), `.bin` (flat 64K for a 27C512)
- `meshcore64-ez-v2.2.crt` (EasyFlash)
- Radio firmware, MeshCore 1.18.0: `firmware-heltec-v3-ble-5760-v1.18.0-c64-5760-merged.bin` (flash at 0x0), `...-app.bin`, and the source patch
- The previous firmware, MeshCore 1.17.1 (`...v1.17.1-c64-5760...`), still works with this release

Radio and client must both be the 5760 versions. Full documentation: README.
