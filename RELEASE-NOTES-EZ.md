# MeshCore 64 EZ 2.3

MeshCore 64 2.3 for **EasyFlash** cartridges: `meshcore64-ez-v2.3.crt` (CRT type 32).

It is the same program, byte for byte, as the v2.3 PRG and cartridge images; only the cartridge wrapper differs.
It does not write to the flash.

- **Ultimate II+:** run the `.crt` from its menu.
- **EasyFlash 3:** program it with EasyProg.
- Needs the radio firmware from the [v2.3 release](https://github.com/pskerrett/meshcore64/releases/tag/v2.3)
  (`v1.17.1-c64-5760`): client and radio must both run at 5760 baud.

**Status:** tested in VICE (NTSC and PAL, with and without an REU). Not yet tried on real EasyFlash
hardware or an Ultimate II+. A physical EasyFlash has its own RAM at `$DF00`, where an REU has its
registers, so use the Magic Desk cartridge or the PRG if you want an REU or GeoRAM.
