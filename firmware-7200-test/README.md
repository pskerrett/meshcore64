# Radio firmware: 7200 baud TEST (v1.17.1-c64-7200)

MeshCore 1.17.1 Bluetooth companion for the Heltec V3, with the C64 user-port
link (UART2, GPIO45 RX / GPIO46 TX) at **7200 baud**. Not a release: it pairs
only with the meshcore64 7200 test client.

- `firmware-heltec-v3-ble-7200-v1.17.1-c64-7200-merged.bin`: full flash at 0x0
- `firmware-heltec-v3-ble-7200-v1.17.1-c64-7200-app.bin`: app-only update
- `meshcore64-firmware-v1.17.1-c64-7200.patch`: source change against
  MeshCore 1.17.1 (env `Heltec_v3_companion_radio_ble_7200`)

Identifies as **`v1.17.1-c64-7200`** on the OLED splash ("mc64 ble 7200"
under it) and on the C64's FW line. The OLED version buffer was widened
from 12 to 21 characters for the MeshCore64 builds so the suffix fits.
