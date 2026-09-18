# `catnip flash`

> Flash CC1352 Firmware or list available firmware images.

The CC1352 only speaks one protocol at a time, and it speaks the one its
firmware implements. **The firmware must match the protocol you want to
sniff** — flashing is not an install step you do once, it is part of switching
between BLE, Zigbee/Thread and the AirTag tools.

`update` is documented here too: it flashes the *other* chip, the host MCU, and
the two are easy to confuse.

## Quick Start

```sh
# 1. See which images this board can take
catnip flash --list

# 2. Flash one, by alias
catnip flash ble

# 3. Confirm what is actually running now
catnip status
```

[`sniff`](sniff.md) flashes the image it needs when it is missing, so for the
common path you can skip straight to `catnip sniff ble`. Use `flash` when you
want to choose the image yourself, or install one that no `sniff` subcommand
covers (`airtag_spoofer`, `justworks`).

---

## How it works

```
  resolve name ──► verify SHA256 ──► shell: enter bootloader ──► mass erase
       │                                                             │
       │                                                             ▼
  status ◄── identify ◄── reset ◄── write NVS metadata ◄── CRC32 verify ◄── write
```

1. **Device selection** — first connected board, or `--device N`.
2. **Firmware resolution** — alias, partial name, full name or path becomes one file.
3. **Integrity check** — SHA256 is validated before anything is erased.
4. **Bootloader entry** — the `bootloader` command goes over the **Cat-Shell**
   port; the image goes over **Cat-Bridge**. Both ports are needed.
5. **Mass erase**, then **write**.
6. **CRC32 verification** — the host recomputes and compares against the chip.
7. **Metadata update** — the firmware id is written to NVS so [`status`](status.md)
   can identify it later by `metadata` rather than by probing. Retried up to 5
   times while the shell comes back up.
8. **Reset and identify.**

Step 7 is why a v3 reports its firmware confidently and a v2 often reports
`unknown`: **v2 boards have no firmware-id storage**, so there is nothing to
write.

**Before erasing, catnip compares the image against the chip the bootloader
reports and refuses a mismatch** — a CC1352P7 image written to a CC1352P1
disables that chip's serial bootloader, and recovering from that needs
[`restore`](restore.md) or an external programmer.

---

## Naming the firmware

Four ways, in order of convenience. All four resolve to the same file.

| Method | Example | When to use |
|---|---|---|
| **Alias** | `catnip flash sniffle` | Normal use. Short, stable, hard to typo. |
| **Partial name** | `catnip flash sniffer_fw` | Any unique substring of the file name. |
| **Full name** | `catnip flash sniffle_cc1352p7_1M.hex` | Scripts, or when two images share a substring. |
| **Path to your own image** | `catnip flash ~/work/custom_v1.0.hex` | Firmware you built yourself. |

---

## Options

| Option | Description |
|---|---|
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers). If not specified, first device will be selected. |
| `-l, --list` | List available firmware images to flash |
| `--full` | Show full descriptions without truncation in the list |
| `--all` | With `--list`, show the whole catalogue instead of only the images that can be flashed on the connected board |
| `--refresh` | Check GitHub for a newer firmware release now and download it if there is one. A standalone command on its own — cannot be combined with `--list` or a firmware name. |
| `--force` | With `--refresh`: wipe the local `.catnip` firmware cache and re-download everything from scratch, even onto the same tag. For a corrupted local file. |
| `--board [v2\|v3]` | Board generation override (v2 = SAMD21 + CC1352P1, v3 = RP2040 + CC1352P7). Only needed when the Cat-Shell port cannot answer; the wrong value disables the CC1352 bootloader |

> [!Important]
> `--board` exists for one situation: the Cat-Shell port cannot answer, so the
> generation cannot be read from the board. **Passing the wrong value disables
> the CC1352 bootloader.** If the shell port works, do not pass it.

---

## `flash --list`

Without a readable board, the list is unfiltered and says so:

```sh
catnip flash --list --all
```

```

Available Firmware Images:
  Board generation unknown — showing every image. Connect the Cat-Shell port or pass --board v2/--board v3 to filter.
╭─────────────────────────┬──────────────────────────────────┬────────────────────────────────────────────────────────────────────────╮
│ Alias                   │ Firmware Name                    │ Description                                                            │
├─────────────────────────┼──────────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
│ airtag_scanner_cc1352p7 │ airtag_scanner_CC1352P_7.hex     │ Specialized passive scanner for detecting Apple AirTag beacons. Its... │
│ airtag_spoofer_cc1352p7 │ airtag_spoofer_CC1352P_7.hex     │ Acts as an Apple AirTag beacon emulator. Its main function is to tr... │
│ catnip_v2               │ catsniffer-v2.1.0.0.uf2          │ No description available                                               │
│ rp2040_boot             │ catsniffer-v3.1.0.0.uf2          │ Main system firmware for CatSniffer V3, designed to run on the RP20... │
│ rp2040_boot             │ catsniffer-v3.1.0.1.uf2          │ No description available                                               │
│ ti_sniffer              │ free_dap_catsniffer.uf2          │ No description available                                               │
│ justworks               │ justworks_scanner_CC1352P7_1.hex │ Analysis and security testing tool for Bluetooth Low Energy (BLE) d... │
│ ti_sniffer              │ sniffer_fw_Catsniffer_v3.x.hex   │ Official Texas Instruments multi-protocol sniffer firmware, origina... │
│ sniffle                 │ sniffle_cc1352p1_cc2652p1_1M.hex │ No description available                                               │
│ sniffle                 │ sniffle_cc1352p7_1M.hex          │ Implementation of the Sniffle firmware for CC1352P7, a high-perform... │
╰─────────────────────────┴──────────────────────────────────┴────────────────────────────────────────────────────────────────────────╯
```

With a board connected, plain `--list` shows **only what that board can take**.
`--all` overrides the filter and says which images the board cannot accept.

Without a firmware argument and without `--list`, it stops and points at the
list rather than picking something:

```
✗ No firmware specified!

ℹ Use 'catnip flash --list' to see available firmware images and aliases.
ℹ Or specify a firmware name: catnip flash <firmware_name_or_alias>
```

---

## `flash --refresh`

```sh
catnip flash --refresh
```

```
ℹ Checking for firmware updates...
✓ Updated v3.1.0.0 → v3.1.0.1 (11 images).
```

```sh
catnip flash --refresh   # nothing new
```

```
ℹ Checking for firmware updates...
✓ Already up to date — v3.1.0.1 (11 images).
```

Checks GitHub's latest `CatSniffer-Firmware` release against what is cached
under `~/.catnip`, and downloads it only if the tag actually changed. Only one
release is ever kept on disk, so an update replaces it rather than adding to
it. A network failure here is a clean error (exit code 3), not a silent
fall-back — you explicitly asked to check.

```sh
catnip flash --refresh --force
```

```
⚠ --force: deleting the local firmware cache and starting over.
✓ Downloaded v3.1.0.1 (11 images).
```

`--force` only makes sense with `--refresh`. It deletes the whole cache —
every downloaded image, not just the CC1352 one you happen to be using — and
re-downloads the latest release from nothing, even if it is the same tag
already on disk. Reach for it when a local image is suspected corrupt (an
interrupted download, a manually edited cache) and a normal `--refresh` would
see the same tag and consider it done.

`--refresh` cannot be combined with `--list` or a firmware name; run it on its
own. Firmware is otherwise still downloaded on demand as usual — `--refresh`
is for pulling a newer release in ahead of that, not something flashing itself
needs.

---

## `catnip update`

> Check and update RP2040 firmware to match the latest release.

**A different chip.** `flash` writes the **CC1352** radio; `update` writes the
**host MCU** — the RP2040 on a v3, the SAMD21 on a v2 — which is the chip that
runs the Cat-Shell and the USB interface. Updating it does not change which
protocol you can sniff.

| Option | Description |
|---|---|
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-f, --force` | Force update even if firmware versions match |
| `--board [v2\|v3]` | Board generation override (see the warning above) |

```sh
catnip update              # check and update if outdated
catnip update --force      # reflash regardless of version
```

It follows the board's own release line (`v2.X.Y.Z` for a v2, `v3.X.Y.Z` for a
v3), looks for that generation's UF2 volume (`SNIFFER` or `RPI-RP2`), and
**asks for confirmation before rebooting the board into the bootloader**. If
the device is not detected it prints the manual Boot Mode steps instead of
failing silently.

---

### Notes

- **`flash` needs both the Cat-Bridge and the Cat-Shell port.** Bootloader entry
  is a shell command; the image transfer is a bridge transfer. If
  [`devices`](devices.md) shows either as `Not found`, fix that first.
- Images are downloaded on demand. `--list` shows the catalogue for the board;
  `--list --all` shows the whole catalogue including what is already on disk.
- **On a v2 board, `zigbee`, `thread` and the AirTag images do not exist.** The
  command says so rather than flashing something that would not work. Currently
  only Sniffle ships a CC1352P1 build.
- The `Usage Examples` block printed by `--list` still advertises `lora-sniffer`
  and other LoRa aliases that the alias listing above it no longer shows. LoRa
  and FSK capture is handled by the SX1262 firmware, not by a CC1352 image —
  see [`sniff lora`](sniff.md).
- The images table is wide. Terminals narrower than about 140 columns clip the
  `Description` column rather than wrapping it.

---

## See also

- [`status`](status.md) — verify what actually ended up on the chip.
- [`restore`](restore.md) — recovery when the CC1352 bootloader no longer answers.
- [`sniff`](sniff.md) — flashes the image it needs automatically.
- Catalogue, aliases, NVS metadata and board generations: [Firmware](../firmware.md).
