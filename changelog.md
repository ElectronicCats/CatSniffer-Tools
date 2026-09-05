# Change Log

## V3.3.2 - Catnip (unreleased)
### Added
- CatSniffer v1.x/v2.x (SAMD21 + CC1352P1) support: board generation is read
  from the `Board:` line of `fw_version` (missing line = v3), shown by
  `catnip devices`, and used to pick per-board CC1352 images
  (`modules/board.py`, `modules/fw_aliases.py`).
- Flash safety gate: before erasing, the CC1352 image name and size are
  checked against the chip the bootloader reports; a CC1352P7 image is never
  written to a CC1352P1 (or the reverse). The loader drains the bridge and
  retries the bootloader sync, and always returns the CC1352 to passthrough
  when a flash fails.
- On-demand download of a board's CC1352 image (for example the Sniffle
  CC1352P1 build) when it is not in the local release folder.
- Board-aware `catnip update`: uses the release line of the board
  (v2.X.Y.Z or v3.X.Y.Z), the board's UF2 volume (SNIFFER or RPI-RP2), asks
  for confirmation before rebooting and never reboots without a matching UF2.
### Changed
- `cc1352_fw_id set` replies of "not supported" (SAMD21 boards have no NVS)
  are recognized and the metadata update is skipped instead of retried.

## V2.0 - Catnip
### Added
- Automatic catsniffer serial path location
- Setup for local pip package
### Changed
- Change the firmware argument to named input insted of index input
### Fixed
- Fix python validation

## V2.0 - Pycatsniffer
### Added
- Automatic catsniffer serial path location
- Setup for local pip package
- Protocol filters for Thread and Zigbee
### Changed
- Change the firmware argument to named input insted of index input
- Change the .lua dissector for compiled dissectors

> Note: Our compiled dissectores are for **Wireshark 4.4** version, are no compatible with under version, we are not supporting more in a production use the **.lua** (this are for testing or development)

## V1.0 - Cativity
### Added
- Cativity - Adding a new tool for Zigbee Networks activity detection
