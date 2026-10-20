# Radio firmware

Two builds are here, both for the **Heltec WiFi LoRa 32 V3** with the C64 user-port link on UART 2
(GPIO45 RX / GPIO46 TX) at **5760 baud**. Radio and C64 program must both run 5760.

| MeshCore | firmware name | use it with |
|---|---|---|
| **1.18.0** (current) | `v1.18.0-c64-5760` | MeshCore 64 v2.2 and later |
| 1.17.1 | `v1.17.1-c64-5760` | MeshCore 64 v2.0 - v2.2 |

## v1.18.0-c64-5760

The stock MeshCore 1.18.0 Bluetooth companion (WiFi included), with three changes: the hardware serial
port is UART 2 instead of 1, it runs at 5760 baud instead of 115200, and the version reads
`v1.18.0-c64-5760`. Nothing else differs from upstream.

| file | |
|---|---|
| `firmware-heltec-v3-ble-5760-v1.18.0-c64-5760-merged.bin` | full flash image: write it at **0x0** |
| `firmware-heltec-v3-ble-5760-v1.18.0-c64-5760-app.bin` | the application partition only, for updating a board that already runs this firmware |
| `meshcore64-firmware-v1.18.0-c64-5760.patch` | the source change against MeshCore 1.18.0 (PlatformIO env `Heltec_v3_companion_radio_ble_5760`) |

The C64 program talks the same companion protocol as before. Compared with 1.17.1, 1.18.0 only adds a command
(`CMD_RUN_CLI_COMMAND`) and a generic push for responses the radio does not recognise; the frames the C64
sends and reads are unchanged. The C64 start screen shows the full version. The radio's OLED shows
the stock `v1.18.0` (upstream cuts the version at the dash).

---

## v1.17.1-c64-5760

MeshCore **1.17.1** Bluetooth companion for the **Heltec WiFi LoRa 32 V3**, with the C64 user-port
link on UART 2 (GPIO45 RX / GPIO46 TX) at **5760 baud**. It pairs with MeshCore 64 v2.0, and only
with it: both ends must run the same speed.

| file | |
|---|---|
| `firmware-heltec-v3-ble-5760-v1.17.1-c64-5760-merged.bin` | full flash image: write it at **0x0** |
| `firmware-heltec-v3-ble-5760-v1.17.1-c64-5760-app.bin` | the application partition only, for updating a board that already runs this firmware |
| `meshcore64-firmware-v1.17.1-c64-5760.patch` | the source change against MeshCore 1.17.1 (PlatformIO env `Heltec_v3_companion_radio_ble_5760`) |
| `md5.txt` | checksums |

Flash it with the MeshCore web flasher in Chrome: open <https://flasher.meshcore.io>, choose
**Custom firmware**, and pick the merged `.bin` you downloaded. (Command line, if you prefer:
`esptool.py --chip esp32s3 write_flash 0x0 <merged.bin>`.)

Flash with the board out of the cartridge. This replaces whatever was on the board (Meshtastic
included); the hardware is unchanged. The firmware identifies itself as **`v1.17.1-c64-5760`**
on the OLED splash screen (with "mc64 ble 5760" under it) and on the C64's start screen.

The patch is small: it selects UART 2 for the companion serial interface (the shared code
hard-codes UART 1, which receives nothing on this board), sets the pins and baud rate, and widens the
OLED version string so the suffix fits. Everything else is stock MeshCore, so it should keep applying
cleanly as MeshCore moves on. To build it yourself, apply the patch to a MeshCore 1.17.1 tree and
build the env above with PlatformIO.
