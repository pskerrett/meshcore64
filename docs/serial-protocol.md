# MeshCore Companion Radio — Binary Serial Protocol

Reverse-engineered from `examples/companion_radio/MyMesh.cpp` /
`MyMesh.h` and the transport helpers under `src/helpers/`. This is the
protocol the official MeshCore companion apps (Android/iOS/desktop) speak
to a "companion radio" firmware build (`*_companion_radio_usb`,
`*_companion_radio_ble`, `*_companion_radio_wifi`). It is not documented
elsewhere in the repo — everything below is inferred directly from the
source.

There is no version number on the wire for the framing layer itself; the
*application* protocol has a version handshake (see `CMD_DEVICE_QUERY`
below) and the firmware constant `FIRMWARE_VER_CODE` (currently `13`,
`examples/companion_radio/MyMesh.h:8`) governs which reply variants
(`_V3` response codes, extra trailing fields, etc.) are used, gated by
`app_target_ver`, the value the app sends in `CMD_DEVICE_QUERY`.

## Transport layer (byte-stream links only)

USB serial, hardware UART, WiFi/TCP and Ethernet transports are raw byte
streams, so each application frame is wrapped with a start byte + a
2-byte little-endian length prefix. BLE does **not** use this framing —
GATT characteristic writes/notifications are already discrete packets, so
the raw application frame is sent as-is (see "Transport differences"
below).

Implementation: `src/helpers/ArduinoSerialInterface.cpp` (used by
`ENABLE_USB_INTERFACE` / hardware-serial builds), mirrored by
`src/helpers/esp32/SerialWifiInterface.cpp` and
`src/helpers/ethernet/SerialEthernetInterface.cpp`.

**Host → device (command) frame:**

| Byte | 1 | 2 | 3 | 4..N |
|---|---|---|---|---|
| Value | `'<'` (0x3C) | length LSB | length MSB | payload (`length` bytes) |

**Device → host (response/push) frame:**

| Byte | 1 | 2 | 3 | 4..N |
|---|---|---|---|---|
| Value | `'>'` (0x3E) | length LSB | length MSB | payload (`length` bytes) |

- `length` is the payload size only (header bytes not included), 0–`MAX_FRAME_SIZE`.
- `MAX_FRAME_SIZE = 176` bytes (`src/helpers/BaseSerialInterface.h:5`).
- The receiver (`ArduinoSerialInterface::checkRecvFrame`) is a tiny state
  machine: `IDLE` (waiting for `<`) → `HDR_FOUND` (got length LSB) →
  `LEN1_FOUND` (got length MSB, now reading payload) → complete frame
  returned, state resets to `IDLE`. Any `<` byte seen in `IDLE` state
  resyncs the parser, so it self-recovers from garbage/partial data.
- There is no checksum/CRC and no escaping — a `<`/`>` byte appearing
  inside a payload is not a problem for the *outbound* framing (payload
  length is explicit), but a corrupted length byte can desync the
  receiver until the next literal `<`.

### Transport differences

| Transport | Framing | Notes |
|---|---|---|
| USB / hardware serial (`ArduinoSerialInterface`) | `<`/`>` + 2-byte length, as above | Baud rate is whatever `Serial.begin()` is called with (default 115200; see `SERIAL_BAUD_RATE` build flag) |
| WiFi/TCP (`SerialWifiInterface`) | same `<`/`>` framing over the TCP stream | Port set by `TCP_PORT` (default 5000) |
| Ethernet (`SerialEthernetInterface`) | same `<`/`>` framing | |
| BLE (`SerialBLEInterface`, ESP32 & nRF52 variants) | **no header** — one GATT write/notify = one application frame | Payload is written directly to the RX characteristic / delivered via the TX characteristic's notify; queued and rate-limited (`BLE_WRITE_MIN_INTERVAL`) |

`src/helpers/MultiSerialInterface.h` lets several transports be active at
once (BLE + USB + WiFi + Ethernet + hardware-serial, up to
`MAX_INTERFACES`), fanning frames out to whichever are enabled — the
application layer above is transport-agnostic.

## Application layer

All app-layer buffers are `MAX_FRAME_SIZE + 1` bytes
(`cmd_frame`/`out_frame` in `examples/companion_radio/MyMesh.h:235-236`).

Byte 0 of every payload is an opcode:

- **`CMD_*`** — sent by the app to the device (request).
- **`RESP_CODE_*`** — sent by the device, as the *synchronous* reply to
  the `CMD_*` that was just processed (one reply per command, with a few
  multi-frame exceptions noted below).
- **`PUSH_CODE_*`** (0x80–0x90) — sent by the device *unsolicited*, at any
  time (radio events, incoming mesh messages, async request responses).
  These use the same frame format as responses; the app tells them apart
  purely by the opcode value being ≥ 0x80.

All multi-byte integers are little-endian. Frames are dispatched in
`MyMesh::handleCmdFrame()` (`examples/companion_radio/MyMesh.cpp:1022`),
called every loop iteration from `MyMesh::checkSerialInterface()`
(`MyMesh.cpp:2202`) after `_serial->checkRecvFrame()` returns a complete
frame. An unrecognized `CMD_*` gets `RESP_CODE_ERR` /
`ERR_CODE_UNSUPPORTED_CMD`.

### Handshake

1. App sends `CMD_DEVICE_QUERY` → device replies `RESP_CODE_DEVICE_INFO`.
2. App sends `CMD_APP_START` → device replies `RESP_CODE_SELF_INFO` (own
   identity/pubkey/radio params/name). After this, normal command traffic
   proceeds.

### Error codes (`RESP_CODE_ERR`, byte 1)

| Code | Name |
|---|---|
| 1 | `ERR_CODE_UNSUPPORTED_CMD` |
| 2 | `ERR_CODE_NOT_FOUND` |
| 3 | `ERR_CODE_TABLE_FULL` |
| 4 | `ERR_CODE_BAD_STATE` |
| 5 | `ERR_CODE_FILE_IO_ERROR` |
| 6 | `ERR_CODE_ILLEGAL_ARG` |

A bare `RESP_CODE_OK` (1 byte, code 0) or `RESP_CODE_ERR` + err code (2
bytes) is the generic ack/nack used by most "setter" commands.
`RESP_CODE_DISABLED` (1 byte) is returned instead of a normal reply for
commands compiled out (e.g. private-key export/import when the
`ENABLE_PRIVATE_KEY_EXPORT`/`_IMPORT` build flags are off).

### Commands (`CMD_*`)

Frame layouts are `payload[0] = opcode`, then the fields listed (offsets
continue from there). "→" shows the device's reply.

| # | Name | Request payload (after opcode) | Reply |
|---|---|---|---|
| 1 | `CMD_APP_START` | 7 reserved bytes, then app name (C string) | `RESP_CODE_SELF_INFO`: adv-type, tx power, max tx power, pubkey(32), lat(i32), lon(i32), multi_acks, advert_loc_policy, telemetry-mode byte, manual_add_contacts, freq(u32), bw(u32), sf, cr, node_name |
| 2 | `CMD_SEND_TXT_MSG` | txt_type, attempt, timestamp(u32), pubkey-prefix(6), text | `RESP_CODE_SENT`: is_flood, expected_ack(u32), est_timeout(u32) — or `ERR_CODE_TABLE_FULL`/`NOT_FOUND`/`UNSUPPORTED_CMD` |
| 3 | `CMD_SEND_CHANNEL_TXT_MSG` | txt_type, channel_idx, timestamp(u32), text | `RESP_CODE_OK` / `ERR_CODE_NOT_FOUND` (bad channel) / `ERR_CODE_UNSUPPORTED_CMD` |
| 4 | `CMD_GET_CONTACTS` | optional: `since` timestamp(u32) | `RESP_CODE_CONTACTS_START` (count u32) then a stream of `RESP_CODE_CONTACT` frames (one per contact, via background iterator) then `RESP_CODE_END_OF_CONTACTS` (most-recent lastmod u32) |
| 5 | `CMD_GET_DEVICE_TIME` | — | `RESP_CODE_CURR_TIME`: now(u32) |
| 6 | `CMD_SET_DEVICE_TIME` | secs(u32) | `RESP_CODE_OK` (only if `secs >= current time`) / `ERR_CODE_ILLEGAL_ARG` |
| 7 | `CMD_SEND_SELF_ADVERT` | optional: 1 byte (1=flood, 0=zero-hop) | `RESP_CODE_OK` / `ERR_CODE_TABLE_FULL` |
| 8 | `CMD_SET_ADVERT_NAME` | name (string, up to buffer size) | `RESP_CODE_OK` |
| 9 | `CMD_ADD_UPDATE_CONTACT` | pubkey(32), type, flags, out_path_len, out_path(64), name(32), last_advert_ts(u32), [gps_lat(i32), gps_lon(i32), [lastmod(u32)]] | `RESP_CODE_OK` / `ERR_CODE_TABLE_FULL` |
| 10 | `CMD_SYNC_NEXT_MESSAGE` | — | next queued message frame (`RESP_CODE_CONTACT_MSG_RECV[_V3]` / `RESP_CODE_CHANNEL_MSG_RECV[_V3]` / `RESP_CODE_CHANNEL_DATA_RECV`) or `RESP_CODE_NO_MORE_MESSAGES` |
| 11 | `CMD_SET_RADIO_PARAMS` | freq(u32, Hz), bw(u32, Hz), sf, cr, [repeat flag] | `RESP_CODE_OK` / `ERR_CODE_ILLEGAL_ARG` (range-checked: freq 150k–2.5M Hz, sf 5-12, cr 5-8, bw 7k–500k) |
| 12 | `CMD_SET_RADIO_TX_POWER` | power (i8, dBm) | `RESP_CODE_OK` / `ERR_CODE_ILLEGAL_ARG` (-9..`MAX_LORA_TX_POWER`) |
| 13 | `CMD_RESET_PATH` | pubkey(32) | `RESP_CODE_OK` / `ERR_CODE_NOT_FOUND` |
| 14 | `CMD_SET_ADVERT_LATLON` | lat(i32, ×1e6), lon(i32, ×1e6), [alt(i32), reserved] | `RESP_CODE_OK` / `ERR_CODE_ILLEGAL_ARG` |
| 15 | `CMD_REMOVE_CONTACT` | pubkey(32) | `RESP_CODE_OK` / `ERR_CODE_NOT_FOUND` |
| 16 | `CMD_SHARE_CONTACT` | pubkey(32) | `RESP_CODE_OK` / `ERR_CODE_NOT_FOUND`/`TABLE_FULL` |
| 17 | `CMD_EXPORT_CONTACT` | optional pubkey(32) (omit = export self) | `RESP_CODE_EXPORT_CONTACT`: serialized advert packet bytes |
| 18 | `CMD_IMPORT_CONTACT` | serialized advert packet bytes | `RESP_CODE_OK` / `ERR_CODE_ILLEGAL_ARG` |
| 19 | `CMD_REBOOT` | literal ASCII `"reboot"` (6 bytes, confirmation) | device reboots (no reply) |
| 20 | `CMD_GET_BATT_AND_STORAGE` | — | `RESP_CODE_BATT_AND_STORAGE`: batt_mv(u16), storage_used_kb(u32), storage_total_kb(u32) |
| 21 | `CMD_SET_TUNING_PARAMS` | rx_delay_base(u32, ×1000), airtime_factor(u32, ×1000) | `RESP_CODE_OK` |
| 22 | `CMD_DEVICE_QUERY` | app protocol version (1 byte) | `RESP_CODE_DEVICE_INFO`: fw_ver_code, max_contacts/2, max_group_channels, ble_pin(u32), build_date(12), manufacturer(40), fw_version(20), repeat_enabled, path_hash_mode |
| 23 | `CMD_EXPORT_PRIVATE_KEY` | — (compiled out unless `ENABLE_PRIVATE_KEY_EXPORT`) | `RESP_CODE_PRIVATE_KEY`: 64-byte key, or `RESP_CODE_DISABLED` |
| 24 | `CMD_IMPORT_PRIVATE_KEY` | 64-byte key (compiled out unless `ENABLE_PRIVATE_KEY_IMPORT`) | `RESP_CODE_OK` / `ERR_CODE_ILLEGAL_ARG`/`FILE_IO_ERROR`, or `RESP_CODE_DISABLED` |
| 25 | `CMD_SEND_RAW_DATA` | path_len (i8), path bytes, raw payload (≥4 bytes) | `RESP_CODE_OK` / `ERR_CODE_TABLE_FULL`/`UNSUPPORTED_CMD` (flood not supported) |
| 26 | `CMD_SEND_LOGIN` | pubkey(32), password (string) | `RESP_CODE_SENT` (same shape as #2); later followed by async `PUSH_CODE_LOGIN_SUCCESS`/`LOGIN_FAIL` |
| 27 | `CMD_SEND_STATUS_REQ` | pubkey(32) | `RESP_CODE_SENT`; later async `PUSH_CODE_STATUS_RESPONSE` |
| 28 | `CMD_HAS_CONNECTION` | pubkey(32) | `RESP_CODE_OK` / `ERR_CODE_NOT_FOUND` |
| 29 | `CMD_LOGOUT` | pubkey(32) | `RESP_CODE_OK` |
| 30 | `CMD_GET_CONTACT_BY_KEY` | pubkey(32) | `RESP_CODE_CONTACT` / `ERR_CODE_NOT_FOUND` |
| 31 | `CMD_GET_CHANNEL` | channel_idx | `RESP_CODE_CHANNEL_INFO`: idx, name(32), secret(16) / `ERR_CODE_NOT_FOUND` |
| 32 | `CMD_SET_CHANNEL` | channel_idx, name(32), secret(16) | `RESP_CODE_OK` / `ERR_CODE_NOT_FOUND`; a 32-byte-secret variant is parsed but currently always replies `ERR_CODE_UNSUPPORTED_CMD` |
| 33 | `CMD_SIGN_START` | — | `RESP_CODE_SIGN_START`: reserved byte, max_len(u32 = 8192); allocates a signing buffer |
| 34 | `CMD_SIGN_DATA` | chunk of data to append to signing buffer | `RESP_CODE_OK` / `ERR_CODE_BAD_STATE`/`TABLE_FULL` |
| 35 | `CMD_SIGN_FINISH` | — | `RESP_CODE_SIGNATURE`: 64-byte Ed25519 signature over the accumulated buffer / `ERR_CODE_BAD_STATE` |
| 36 | `CMD_SEND_TRACE_PATH` | tag(u32), auth(u32), flags (incl. path_size bits), explicit path bytes | `RESP_CODE_SENT`: 0, tag(u32), est_timeout(u32); later async `PUSH_CODE_TRACE_DATA` |
| 37 | `CMD_SET_DEVICE_PIN` | pin(u32) — 0 or 6-digit | `RESP_CODE_OK` / `ERR_CODE_ILLEGAL_ARG` |
| 38 | `CMD_SET_OTHER_PARAMS` | manual_add_contacts, [telemetry-mode byte], [advert_loc_policy], [multi_acks] | `RESP_CODE_OK` |
| 39 | `CMD_SEND_TELEMETRY_REQ` | pubkey(32) at offset+4, **or** len==4 for "self" telemetry | `RESP_CODE_SENT` (remote) or an immediate `PUSH_CODE_TELEMETRY_RESPONSE` (self) |
| 40 | `CMD_GET_CUSTOM_VARS` | — | `RESP_CODE_CUSTOM_VARS`: comma-separated `name:value` pairs (sensor settings) |
| 41 | `CMD_SET_CUSTOM_VAR` | `"name:value"` string | `RESP_CODE_OK` / `ERR_CODE_ILLEGAL_ARG` |
| 42 | `CMD_GET_ADVERT_PATH` | reserved byte, pubkey(32) | `RESP_CODE_ADVERT_PATH`: recv_timestamp(u32), path_len, path bytes / `ERR_CODE_NOT_FOUND` |
| 43 | `CMD_GET_TUNING_PARAMS` | — | `RESP_CODE_TUNING_PARAMS`: rx_delay_base(u32×1000), airtime_factor(u32×1000) |
| 50 | `CMD_SEND_BINARY_REQ` | pubkey(32), arbitrary request bytes | `RESP_CODE_SENT`; later async `PUSH_CODE_BINARY_RESPONSE` |
| 51 | `CMD_FACTORY_RESET` | literal ASCII `"reset"` (5 bytes, confirmation) | filesystem wiped, `RESP_CODE_OK` then reboot (serial disabled first to dodge app reconnect race) |
| 52 | `CMD_SEND_PATH_DISCOVERY_REQ` | reserved=0, pubkey(32) | `RESP_CODE_SENT`; later async `PUSH_CODE_PATH_DISCOVERY_RESPONSE` |
| 54 | `CMD_SET_FLOOD_SCOPE_KEY` | mode byte: `0`+optional 16-byte key (set/clear scope override), or `1` (force unscoped, v12+) | `RESP_CODE_OK` |
| 55 | `CMD_SEND_CONTROL_DATA` | control byte (high bit set) + payload | `RESP_CODE_OK` / `ERR_CODE_TABLE_FULL` |
| 56 | `CMD_GET_STATS` | stats_type (0=core,1=radio,2=packets) | `RESP_CODE_STATS` (see below) / `ERR_CODE_ILLEGAL_ARG` |
| 57 | `CMD_SEND_ANON_REQ` | pubkey(32), request bytes | `RESP_CODE_SENT`; later async `PUSH_CODE_BINARY_RESPONSE`-style path via `onContactResponse` |
| 58 | `CMD_SET_AUTOADD_CONFIG` | config bitmask, [max_hops] | `RESP_CODE_OK` |
| 59 | `CMD_GET_AUTOADD_CONFIG` | — | `RESP_CODE_AUTOADD_CONFIG`: config bitmask, max_hops |
| 60 | `CMD_GET_ALLOWED_REPEAT_FREQ` | — | `RESP_ALLOWED_REPEAT_FREQ`: list of (lower_freq(u32), upper_freq(u32)) ranges |
| 61 | `CMD_SET_PATH_HASH_MODE` | reserved=0, mode (0-2) | `RESP_CODE_OK` / `ERR_CODE_ILLEGAL_ARG` |
| 62 | `CMD_SEND_CHANNEL_DATA` | channel_idx, path_len (or 0xFF=flood), path bytes, data_type(u16), payload | `RESP_CODE_OK` / `ERR_CODE_ILLEGAL_ARG`/`NOT_FOUND`/`TABLE_FULL` |
| 63 | `CMD_SET_DEFAULT_FLOOD_SCOPE` | scope name(31) + key(16), or empty to clear | `RESP_CODE_OK` / `ERR_CODE_ILLEGAL_ARG` |
| 64 | `CMD_GET_DEFAULT_FLOOD_SCOPE` | — | `RESP_CODE_DEFAULT_FLOOD_SCOPE`: name(31)+key(16), or just the opcode if unset |
| 65 | `CMD_SEND_RAW_PACKET` | priority byte, raw mesh packet bytes | `RESP_CODE_OK` / `ERR_CODE_ILLEGAL_ARG`/`TABLE_FULL` |

`CMD_GET_STATS` sub-type replies (`RESP_CODE_STATS`, byte 1 = sub-type):

| Sub-type | Fields |
|---|---|
| 0 `STATS_TYPE_CORE` | battery_mv(u16), uptime_secs(u32), err_flags(u16), outbound_queue_len |
| 1 `STATS_TYPE_RADIO` | noise_floor(i16), last_rssi(i8), last_snr(i8, ×4), tx_air_secs(u32), rx_air_secs(u32) |
| 2 `STATS_TYPE_PACKETS` | packets_recv(u32), packets_sent(u32), sent_flood(u32), sent_direct(u32), recv_flood(u32), recv_direct(u32), recv_errors(u32) |

### Asynchronous push frames (`PUSH_CODE_*`, 0x80–0x90)

Sent by the device without a preceding command — radio/mesh events, or
delayed replies to a request that returned `RESP_CODE_SENT` earlier.

| Code | Name | Payload | Trigger |
|---|---|---|---|
| 0x80 | `PUSH_CODE_ADVERT` | pubkey(32) | advert heard from an already-known contact |
| 0x81 | `PUSH_CODE_PATH_UPDATED` | pubkey(32) | a contact's routing path changed |
| 0x82 | `PUSH_CODE_SEND_CONFIRMED` | ack_hash(4), round_trip_ms(u32) | an expected ACK arrived for a sent message |
| 0x83 | `PUSH_CODE_MSG_WAITING` | (opcode only) | "tickle" — new message(s) queued; app should send `CMD_SYNC_NEXT_MESSAGE` |
| 0x84 | `PUSH_CODE_RAW_DATA` | snr(i8×4), rssi(i8), 0xFF, raw payload | raw mesh packet received (see `CMD_SEND_RAW_DATA`) |
| 0x85 | `PUSH_CODE_LOGIN_SUCCESS` | is_admin/permissions, pubkey-prefix(6), [server_timestamp(u32), acl, fw_ver_level] (new-style only) | reply to `CMD_SEND_LOGIN` |
| 0x86 | `PUSH_CODE_LOGIN_FAIL` | reserved, pubkey-prefix(6) | reply to `CMD_SEND_LOGIN` |
| 0x87 | `PUSH_CODE_STATUS_RESPONSE` | reserved, pubkey-prefix(6), raw status bytes | reply to `CMD_SEND_STATUS_REQ` |
| 0x88 | `PUSH_CODE_LOG_RX_DATA` | snr(i8×4), rssi(i8), raw packet bytes | debug/log tap of every received raw radio packet |
| 0x89 | `PUSH_CODE_TRACE_DATA` | reserved, path_len, flags, tag(u32), auth(u32)?, per-hop SNRs, path hashes | reply to `CMD_SEND_TRACE_PATH` |
| 0x8A | `PUSH_CODE_NEW_ADVERT` | full contact record (same shape as `RESP_CODE_CONTACT`) | advert heard from a **new**, previously-unknown node |
| 0x8B | `PUSH_CODE_TELEMETRY_RESPONSE` | reserved, pubkey-prefix(6), telemetry blob | reply to `CMD_SEND_TELEMETRY_REQ` (remote), or immediate for "self" |
| 0x8C | `PUSH_CODE_BINARY_RESPONSE` | reserved, tag(u32), raw response bytes | reply to `CMD_SEND_BINARY_REQ` |
| 0x8D | `PUSH_CODE_PATH_DISCOVERY_RESPONSE` | reserved, pubkey-prefix(6), out_path_len, out_path, in_path_len, in_path | reply to `CMD_SEND_PATH_DISCOVERY_REQ` |
| 0x8E | `PUSH_CODE_CONTROL_DATA` | snr(i8×4), rssi(i8), path_len, raw payload | reply to `CMD_SEND_CONTROL_DATA` peer traffic |
| 0x8F | `PUSH_CODE_CONTACT_DELETED` | pubkey(32) | a contact was evicted (e.g. table full + overwrite-oldest policy) |
| 0x90 | `PUSH_CODE_CONTACTS_FULL` | (opcode only) | contact table is full and can't auto-add more |

### Contact record layout (`RESP_CODE_CONTACT` / `PUSH_CODE_NEW_ADVERT`)

Written by `writeContactRespFrame()` (`MyMesh.cpp:166`):

| Field | Size |
|---|---|
| code (`RESP_CODE_CONTACT` etc.) | 1 |
| pubkey | 32 |
| type (`ADV_TYPE_*`) | 1 |
| flags | 1 |
| out_path_len | 1 |
| out_path | 64 (`MAX_PATH_SIZE`) |
| name (null-padded) | 32 |
| last_advert_timestamp | 4 (u32) |
| gps_lat | 4 (i32) |
| gps_lon | 4 (i32) |
| lastmod | 4 (u32) |

`ADV_TYPE_*`: `0`=none, `1`=chat, `2`=repeater, `3`=room server, `4`=sensor
(`src/helpers/AdvertDataHelpers.h`).

`TXT_TYPE_*` (used in `CMD_SEND_TXT_MSG`/message-recv frames):
`0`=plain, `1`=CLI data, `2`=signed plain (`src/helpers/TxtDataHelpers.h`).

`OUT_PATH_UNKNOWN = 0xFF` marks "no cached path / flood".

### CLI rescue mode

Independent of the binary protocol: if the device enters "CLI rescue"
mode (`MyMesh::enterCLIRescue()`), the same serial port instead accepts
plain-text, newline-terminated commands (`set pin <n>`, `rebuild`,
`erase`, `reboot`, ...) handled in `checkCLIRescueCmd()`
(`MyMesh.cpp:2030`) — this is a separate, human-typed debug/recovery
interface, not framed with `<`/`>`.

## Source map

| File | Contents |
|---|---|
| `src/helpers/BaseSerialInterface.h` | Abstract transport interface, `MAX_FRAME_SIZE` |
| `src/helpers/ArduinoSerialInterface.cpp/.h` | USB/UART `<`/`>` length-prefixed framing |
| `src/helpers/esp32/SerialWifiInterface.cpp/.h` | Same framing over TCP |
| `src/helpers/ethernet/SerialEthernetInterface.cpp/.h` | Same framing over Ethernet |
| `src/helpers/esp32/SerialBLEInterface.cpp/.h`, `src/helpers/nrf52/SerialBLEInterface.cpp/.h` | BLE transport (no length-prefix framing) |
| `src/helpers/MultiSerialInterface.h` | Fan-out across simultaneously-enabled transports |
| `examples/companion_radio/MyMesh.h` | Frame buffers, `FIRMWARE_VER_CODE`, `REQ_TYPE_*` |
| `examples/companion_radio/MyMesh.cpp` | All `CMD_*`/`RESP_CODE_*`/`PUSH_CODE_*`/`ERR_CODE_*` constants; `handleCmdFrame()` dispatcher; all push-frame senders |
| `src/helpers/AdvertDataHelpers.h` | `ADV_TYPE_*` |
| `src/helpers/TxtDataHelpers.h` | `TXT_TYPE_*`, `DATA_TYPE_*` |
| `src/helpers/ContactInfo.h` / `ClientACL.h` | `OUT_PATH_UNKNOWN`, contact struct fields |
| `src/MeshCore.h` | `PUB_KEY_SIZE`, `SIGNATURE_SIZE` |
| `src/Packet.h` | `MAX_PATH_SIZE`, `PAYLOAD_TYPE_*` (underlying mesh packet types, one layer below this protocol) |

This document reflects `FIRMWARE_VER_CODE = 13` at commit
`0679dbef` of `meshcore-dev/meshcore`. No source files were modified to
produce it.
