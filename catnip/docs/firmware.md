# Firmware

Which chip runs what, which image exists for which board, how a name on the
command line becomes a file on disk, and where those files come from. This page
is the shared background for [`flash`](commands/flash.md),
[`restore`](commands/restore.md), [`verify`](commands/verify.md),
[`status`](commands/status.md) and [`sniff`](commands/sniff.md).

- [Two chips, two kinds of firmware](#two-chips)
- [Board generations](#generations)
- [The image catalogue](#catalogue)
- [Naming an image](#naming)
- [Where the images come from](#downloads)
- [How a board remembers what it runs](#fw-id)
- [Version numbers](#versions)

---

<a id="two-chips"></a>
## Two chips, two kinds of firmware

A CatSniffer carries two independently programmable parts, and "firmware"
means a different thing for each:

| | Host MCU | CC1352 |
|---|---|---|
| Chip | SAMD21 (v2) / RP2040 (v3) | CC1352P1 (v2) / CC1352P7 (v3) |
| What it does | USB interfaces, Cat-Shell command shell, SX1262 control, debug probe | the 2.4 GHz / sub-GHz radio itself |
| Written by | [`catnip update`](commands/flash.md#catnip-update) | [`catnip flash`](commands/flash.md) |
| Image format | `.uf2`, copied onto a USB volume | `.hex`, sent over the serial bootloader |
| How often | rarely — it tracks the tool release | per protocol |

**The [SX1262](glossary.md#sx1262) has no image of its own.** It is driven by
the host MCU firmware, which is why LoRa and FSK capture is a matter of radio
parameters rather than flashing.

So "reflash the board to sniff Zigbee" always means the CC1352, and "the board
does not enumerate any more" always means the host MCU.

---

<a id="generations"></a>
## Board generations

| | v1.x / v2.x | v3.x |
|---|---|---|
| Host MCU | SAMD21E17 | RP2040 |
| Radio | CC1352P1 — 352 KB flash | CC1352P7 — 704 KB flash |
| UF2 volume | `SNIFFER` | `RPI-RP2` |
| Release tags | `v2.X.Y.Z` | `v3.X.Y.Z` |
| Bridge ring buffer | 256 B | 16 KB |
| Stores a CC1352 firmware id | no | yes |
| Can self-program the CC1352 | no | yes |
| Its releases ship CC1352 `.hex` assets | no | yes |

Both generations share the USB identity (`1209:babb`), the three ports and the
shell command set — which is exactly why the generation has to be established
rather than assumed.

**Detection**: catnip reads the `Board:` line of the `fw_version` shell reply
(for example `Board: v2 SAMD21 CC1352P1`). The SAMD21 firmware has emitted that
line since its first release. Without it, only an explicit `FW: v3.X` tag
identifies a board — an RP2040 build predating the line. Anything else is
**unknown**, and catnip never guesses:

> [!Important]
> **A CC1352P7 image written to a CC1352P1 disables the serial bootloader**,
> and recovering from that needs a cJTAG programmer. Guessing v3 on a v2 is
> precisely the mistake that bricks a board, so an unknown generation stops
> the flash instead of picking the more likely answer. When the shell port is
> dead and you know what you have, say so with `--board v2` / `--board v3`.

Every rule that differs between generations is data on `BoardInfo`
([`modules/firmware/board.py`](../modules/firmware/board.py)), not a
`generation == "v3"` comparison scattered through the code — a test enforces
that with an AST check. [`status`](commands/status.md) prints those capability
rows as *Board can*.

---

<a id="catalogue"></a>
## The image catalogue

CC1352 images, by official id:

| Official id | What it is | v2 image | v3 image |
|---|---|---|---|
| `sniffle` | NCC Group's BLE sniffer — [`sniff ble`](commands/sniff.md#sniff-ble), and what the [`vhci`](commands/vhci.md) bridge speaks to | `sniffle_cc1352p1_cc2652p1_1M` | `sniffle_cc1352p7_1M` |
| `ti_sniffer` | TI multiprotocol sniffer — Zigbee, Thread, 802.15.4 | — | `sniffer_fw_Catsniffer_v3.x` |
| `airtag_scanner_cc1352p7` | Apple Find My beacon scanner | — | `airtag_scanner_CC1352P_7` |
| `airtag_spoofer_cc1352p7` | Find My beacon emulator | — | `airtag_spoofer_CC1352P_7` |
| `justworks_scanner_cc1352p7` | BLE JustWorks pairing scanner | — | `justworks_scanner` |

Host MCU images, for [`update`](commands/flash.md#catnip-update):

| Official id | What it is | Volume |
|---|---|---|
| `catnip_v2` | v2 system firmware (`catsniffer-v2.X.Y.Z.uf2`) | `SNIFFER` |
| `rp2040_boot` / `catnip_v3` | v3 system firmware (`catsniffer-v3.X.Y.Z.uf2`) | `RPI-RP2` |
| `free_dap_catsniffer.uf2` | the CMSIS-DAP probe [`restore`](commands/restore.md) loads onto the RP2040 to reprogram a CC1352 whose bootloader is gone | `RPI-RP2` |

**A v2 has exactly two images: Sniffle and its own system firmware.** Zigbee,
Thread, AirTag and JustWorks have no CC1352P1 build, so on a v2 those commands
stop with [exit code 5](reference.md#exit-codes) rather than flashing something
that cannot work.

`catnip flash --list` prints this catalogue filtered to the connected board;
`--list --all` prints it whole.

---

<a id="naming"></a>
## Naming an image

Four ways to say which image you mean, in the order catnip resolves them:

**1. An alias** — short, protocol-shaped, the usual choice:

```sh
catnip flash sniffle
catnip flash zigbee
```

| Alias | Resolves to |
|---|---|
| `ble`, `sniffle` | `sniffle` |
| `zigbee`, `thread`, `15.4`, `ti`, `sniffer`, `multiprotocol` | `ti_sniffer` |
| `airtag_scanner`, `airtag-scanner` | `airtag_scanner_cc1352p7` |
| `airtag_spoofer`, `airtag-spoofer` | `airtag_spoofer_cc1352p7` |
| `justworks` | `justworks_scanner_cc1352p7` |
| `v3`, `catnip_v3` | `catnip_v3` |

**2. An official id** — the ids in the table above are accepted verbatim.

**3. A partial or full file name** — matched by substring, so `sniffle` in any
spelling lands on the Sniffle image, and anything containing `sniffer`,
`zigbee`, `thread` or `15.4` lands on the TI sniffer:

```sh
catnip flash sniffer_fw_Catsniffer_v3.x.hex
```

**4. A path to your own image** — a file that is not in the catalogue at all:

```sh
catnip flash ~/work/custom_firmware_v1.0.hex
```

Resolution is case-insensitive and happens before any hardware is touched. The
resolved pair is printed, so you can see what a short name became:

```
Resolved 'sniffle' to sniffle -> sniffle_cc1352p7_1M.hex
```

> [!Note]
> The alias list is per generation. `flash --list` on a v2 shows only the ids
> that have a CC1352P1 image, and an id with no image for the connected board
> is refused rather than resolved to the other generation's file.

---

<a id="downloads"></a>
## Where the images come from

Images are **downloaded on demand**, not shipped with catnip:

| Source | What it provides |
|---|---|
| `ElectronicCats/CatSniffer-Firmware` releases | system firmware `.uf2`, TI sniffer, AirTag and JustWorks `.hex`, `descriptions.json` |
| `nccgroup/Sniffle` releases | the Sniffle `.hex` builds, mirrored for both generations |
| `ElectronicCats/CatSniffer-Tools` releases | the version [`update`](commands/flash.md#catnip-update) compares the tool against |

They are cached under `~/.catnip/`:

```
~/.catnip/
├── release_v3.1.0.0/          # one directory per firmware release tag
│   ├── sniffle_cc1352p7_1M.hex
│   ├── sniffle_cc1352p1_cc2652p1_1M.hex
│   ├── sniffer_fw_Catsniffer_v3.x.hex
│   ├── airtag_scanner_CC1352P_7.hex
│   ├── catsniffer-v3.1.0.1.uf2
│   ├── free_dap_catsniffer.uf2
│   ├── releases.json          # release metadata as fetched
│   └── descriptions.json      # the Description column of flash --list
└── restore_cache/             # the probe image restore falls back to
```

The path is the same whether catnip runs from a package, a checkout or a
bundled binary, so the cache is shared between them. If `$HOME` is not
writable, it falls back to the working directory.

**Your own images work too**: drop a `.hex` into the release directory and it
is listed alongside the rest, or pass a path from anywhere.

Deleting `~/.catnip/release_*` is safe — the next flash re-downloads what it
needs. It is also the fix when an image is suspected to be corrupt.

---

<a id="fw-id"></a>
## How a board remembers what it runs

A CC1352 does not announce which image is on it. A **v3** solves that by having
the RP2040 record the official id in [NVS](glossary.md#nvs) whenever catnip
flashes it, through four shell commands:

```
cc1352_fw_id get        → the stored id
cc1352_fw_id set <id>   → record one (catnip does this after a successful flash)
cc1352_fw_id clear      → forget it
cc1352_fw_id list       → the ids the firmware knows
```

That record is what lets [`status`](commands/status.md) answer *Detected via
metadata* — the definitive answer. Two replies mean the board will never store
one, so catnip stops asking rather than retrying:

| Reply | Meaning |
|---|---|
| `ERR not supported on this board` | a v2: no NVS at all |
| `ERR storage unavailable` | a v3 whose NVS failed to mount |

Without the record, identification falls back to **direct communication** — a
protocol probe only `sniffle` and `ti_sniffer` can answer. Any other image on a
board without NVS reports `unknown`, which is a limit of the detection, not a
sign that anything is wrong.

---

<a id="versions"></a>
## Version numbers

Firmware is versioned `vA.X.Y.Z`, where **`A` is the board generation the image
is built for**. A v3 board runs `v3.X.Y.Z` images; a v2 runs `v2.X.Y.Z`.
Releases are tagged per generation, which is why `update` follows the board's
own line and never offers the other one.

The tool has its own version (`VERSION` in the repository root, printed in the
banner of every command). They are independent: `update` compares the **tool**
version against the latest tool release to decide whether the firmware
catalogue it carries is current, and warns when the local build is ahead of the
latest release:

```
⚠ Development version detected! Local: 3.3.3.0 > Latest release: 3.3.2.1
⚠ This build is ahead of the latest release and may be unstable.
⚠ Use it for testing only — firmware compatibility is not guaranteed.
```

---

## See also

- Putting an image on the radio: [`flash`](commands/flash.md).
- Recovering a CC1352 that no longer answers: [`restore`](commands/restore.md).
- What is on the board right now: [`status`](commands/status.md).
- What a v2 cannot do: [Limitations](limitations.md#board-limits).
