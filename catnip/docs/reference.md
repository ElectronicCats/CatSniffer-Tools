# Reference

Everything that is true of the CLI as a whole: how to invoke it, the options
every command accepts, how a board is selected, the environment variables that
change its behaviour, and what each exit code means. Per-command detail lives
in [`commands/`](commands/) — one page per group.

- [Invocation](#invocation)
- [Global options](#global-options)
- [Device selection](#device-selection)
- [Environment variables](#environment-variables)
- [Exit codes](#exit-codes)
- [Commands](#commands)
- [Old anchor links (pre-restructure)](#old-anchors)

---

<a id="invocation"></a>
## Invocation

Two spellings, same program:

```sh
catnip <command> [options]          # installed package or bundled binary
python catnip.py <command> [options] # from a checkout
```

Every command prints the ASCII banner first. The banner is where the version
lives — **there is no `--version` flag**:

```
╭─ Electronic Cats - PWNLAB ───────────────────────────────────────────────────╮
│                                                                              │
│        :=--             --=-       |                                         │
│        -====-         -=====       |                                         │
│        :===================-       |                                         │
│         ===================:       |                                         │
│    -   :==--===========--==-   -   |  catnip devices                         │
│   -===:===-   :=====-   -==-.-=--  |  v3.3.3.0                               │
│  --    ====-   :===-   -====    -- |  What even is encryption?               │
│  -=:   :===================-   .=- |                                         │
│   ---=-- -===============-  -=---  |                                         │
│   ---       --=======--        --  |                                         │
│                                                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

The label on the right names the command you ran, or `catnip: (root)` when the
process is running as root. The tagline under the version is picked at random
and means nothing.

Group names are not abbreviated: `catnip sniff ble`, never `catnip sn ble`.
An unknown command is a usage error, and so is a missing required option:

```
Usage: catnip sniff zigbee [OPTIONS]
Try 'catnip sniff zigbee --help' for help.

Error: Missing option '--channel' / '-c'.
```

---

<a id="global-options"></a>
## Global options

These sit on the root group, so they go **before** the command:

| Option | Description |
|---|---|
| `-v, --verbose` | Increase logging verbosity. Repeatable: `-v` (INFO), `-vv` (DEBUG + timestamps). |
| `-h, --help` | Show this message and exit. |

```sh
catnip -v sniff zigbee -c 15     # right
catnip sniff zigbee -c 15 -v     # wrong: -v is not a sniff option
```

Verbosity maps onto the Python logger: default `WARNING`, `-v` `INFO`,
`-vv` and above `DEBUG` with timestamps in the log lines. It changes what is
logged, not what the commands print — the `✓`/`✗`/`ℹ` lines are always there.

`-h/--help` works at every level of the tree, and is the source of truth for
this documentation:

```sh
catnip --help
catnip sniff --help
catnip sniff lora --help
```

> [!Note]
> `catnip vhci start` has its own `-v/--verbose` flag, a boolean that turns on
> DEBUG logging for the bridge. It is not the global counter, and it goes after
> the subcommand.

---

<a id="device-selection"></a>
## Device selection

Every command that talks to hardware takes the same selector:

| Option | Description |
|---|---|
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |

The ID is **not** a port path. catnip enumerates USB interfaces matching the
CatSniffer VID/PID (`1209:babb`), groups them per physical board, keeps only
boards where all three ports resolve, sorts them by port path and numbers them
from `1`. [`catnip devices`](commands/devices.md) prints that numbering.

Three consequences worth knowing:

- **Omitting `-d` picks the first board**, not "the" board. With one board
  connected that is what you want; with several, it is whichever the OS
  enumerated first.
- **IDs are stable only while nothing is replugged.** Unplugging board `1`
  renumbers the rest. Re-run `devices` after touching the cables.
- **A board with fewer than three detected ports is skipped entirely** and
  never gets an ID. That is the usual reason a board that shows up in `lsusb`
  does not show up in `devices` — see
  [Troubleshooting](troubleshooting.md#no-devices).

[`catnip verify`](commands/verify.md) is the exception to the "first board"
rule: with no `-d` it tests **every** connected device rather than picking one.

---

<a id="environment-variables"></a>
## Environment variables

| Variable | Effect |
|---|---|
| `CATNIP_DEBUG` | Any non-empty value: print the full Python traceback instead of the one-line error. |
| `CATNIP_PROFILES_FILE` | Path to the radio profiles TOML, replacing `~/.config/catnip/profiles.toml`. |
| `_CATNIP_COMPLETE` | Set by the shell completion script. When present, catnip suppresses the banner. Not for interactive use. |

`CATNIP_DEBUG` is what a bug report should carry:

```sh
CATNIP_DEBUG=1 catnip status
```

Without it, a failure is one line naming the exception class:

```
✗ DeviceError: Shell port not available for this device! (set CATNIP_DEBUG=1 for a traceback)
```

Errors carrying an actionable fix print a panel with numbered steps instead of
the bare line. Either way, **values that look like credentials — passwords,
PSKs, tokens, keys — are redacted before the message is printed**, so error
output is safe to paste into an issue.

Radio profiles are covered in [`sniff profiles`](commands/sniff.md#sniff-profiles).

---

<a id="exit-codes"></a>
## Exit codes

Defined in [`modules/core/exceptions.py`](../modules/core/exceptions.py) and
applied in one place, `main_cli()`:

| Exit code | Meaning | Raised by |
|---|---|---|
| `0` | Success | — |
| `1` | Generic or unexpected error | `CatnipError`, `ProtocolError`, any uncaught exception |
| `2` | Usage error: unknown command, bad or missing option | Click's own `UsageError` |
| `3` | Firmware error: detection, flashing, updating or verification | `FirmwareError` |
| `4` | Device or connection error: not found, port busy, disconnected | `DeviceError`, `ConnectionError` |
| `5` | Not supported on this board generation | `UnsupportedOnBoardError` |
| `130` | Interrupted (Ctrl-C, or EOF at a prompt) | `KeyboardInterrupt` / Click `Abort` |

`5` is deliberately not `3`: "this board cannot do that" is not a failure that
retrying or reflashing will fix. A v2 has no NVS, no CMSIS-DAP probe and no
CC1352P7 image, and a script can tell that apart from a flash that went wrong.

> [!Important]
> **Not every failure path is typed yet.** The shared "pick a device" helper
> (`get_device_or_exit`) prints its own message and exits `1`, so the most
> common failure of all — no board connected — comes back as `1`, not `4`:
>
> ```
> ✗ No CatSniffer device found!
>   Make sure your CatSniffer is connected.
> ```
>
> Verified on `identify`, `status` and `verify`. Scripts should treat any
> non-zero code as failure and read the message, rather than branching on `4`.

`catnip devices` **exits `0` when it finds nothing**: an empty list is a valid
answer to "what is connected", not an error.

---

<a id="commands"></a>
## Commands

One page per group. Descriptions are the CLI's own, verbatim.

| Command | Description | Page |
|---|---|---|
| `devices` | List connected CatSniffer devices | [devices.md](commands/devices.md) |
| `identify` | Send identification command to CatSniffer device | [devices.md](commands/devices.md#identify) |
| `status` | Show board, firmware and capabilities detected on a CatSniffer. | [status.md](commands/status.md) |
| `verify` | Verify CatSniffer device functionality | [verify.md](commands/verify.md) |
| `flash` | Flash CC1352 Firmware or list available firmware images. | [flash.md](commands/flash.md) |
| `update` | Check and update RP2040 firmware to match the latest release. | [flash.md](commands/flash.md#catnip-update) |
| `restore` | Restore CC1352 when bootloader is broken. | [restore.md](commands/restore.md) |
| `sniff` | Sniffer protocol control | [sniff.md](commands/sniff.md) |
| `cativity` | IQ Activity Monitor | [cativity.md](commands/cativity.md) |
| `meshtastic` | Meshtastic protocol tools | [meshtastic.md](commands/meshtastic.md) |
| `lora` | LoRa SX1262 tools | [lora.md](commands/lora.md) |
| `vhci` | VHCI Bridge - Expose CatSniffer as hciX. | [vhci.md](commands/vhci.md) |
| `setup-env` | Setup environment: install udev rules and add user to groups. | [setup-env.md](commands/setup-env.md) |
| `completion` | Install shell tab completion for catnip. | [completion.md](commands/completion.md) |

**The command tree is platform-dependent.** `vhci` and `setup-env` are
registered on Linux only; `completion` on Linux and macOS. They are absent from
`catnip --help` elsewhere — see [Limitations](limitations.md).

---

<a id="old-anchors"></a>
## Old anchor links (pre-restructure)

Until this reorganisation the whole manual was one README. Links to its
headings — in issues, bookmarks or other repos — map here:

| Old README section | Now in |
|---|---|
| Project Architecture · Directory Structure · Main Components | [architecture.md](architecture.md) |
| Capabilities and Features | [reference.md#commands](#commands) |
| Installation · Prerequisites · Global Installation · Virtual Environment Installation | [installation.md](installation.md) |
| Quick Start · First Execution | [usage.md](usage.md) |
| Available Commands | [reference.md#commands](#commands) |
| Verifying Connected Devices | [commands/devices.md](commands/devices.md) |
| Board Generations (v1/v2 vs v3) | [firmware.md](firmware.md) |
| Firmware Management · Viewing Available Firmware · Flashing Process | [commands/flash.md](commands/flash.md) |
| Firmware Selection Methods | [firmware.md](firmware.md) |
| Troubleshooting Flashing Issues | [troubleshooting.md](troubleshooting.md#flash-failed) |
| Firmware Recovery (Restore) | [commands/restore.md](commands/restore.md) |
| Device Verification · Failure Diagnosis | [commands/verify.md](commands/verify.md) |
| Protocol Sniffing · Bluetooth Low Energy (BLE) | [commands/sniff.md](commands/sniff.md#sniff-ble) |
| AirTag Scanner | [commands/sniff.md](commands/sniff.md#sniff-airtag_scanner) |
| LoRa/FSK Radio Profiles | [commands/sniff.md](commands/sniff.md#sniff-profiles) |
| IQ Activity Monitor (Cativity) | [commands/cativity.md](commands/cativity.md) |
| Meshtastic Protocol Tools | [commands/meshtastic.md](commands/meshtastic.md) |
| Wireshark Integration · What is Extcap? | [wireshark.md](wireshark.md) |
| Error Handling and Exit Codes | [reference.md#exit-codes](#exit-codes) |
| Common Problem Solving (every `Problem:` heading) | [troubleshooting.md](troubleshooting.md) |
| Contributions and Support | [contributing.md](contributing.md) |

---

## See also

- End-to-end flow: [Usage](usage.md).
- Terms used across these pages: [Glossary](glossary.md).
- What works where: [Limitations](limitations.md).
