# Architecture

How the code is laid out and why, for anyone about to change it. If you only
want to *use* catnip, [Usage](usage.md) and [Reference](reference.md) are the
pages you want.

- [The shape of it](#shape)
- [Directory structure](#tree)
- [The runtime core](#core)
- [Command modules](#commands)
- [Firmware lifecycle](#firmware)
- [Protocol implementations](#protocols)
- [Radio drivers](#drivers)
- [Tests and the CLI snapshot](#tests)

---

<a id="shape"></a>
## The shape of it

Four layers, each depending only on the ones below it:

```
  catnip.py                      thin launcher, no logic
      │
  modules/core/cli.py            build_cli() assembles the command tree
      │                          main_cli() maps exceptions → exit codes
      ├── modules/device/cli.py      ┐
      ├── modules/firmware/cli.py    │ one Click group per feature area
      ├── modules/sniff/cli.py       │
      ├── modules/protocols/cli/*    │
      └── modules/utils/*_cli.py     ┘
              │
  modules/core/*                 device discovery, sessions, pipes, bridges
  modules/firmware/*             images, flashing, verification, boards
  modules/protocols/*            cativity, meshtastic, sx1262, vhci
              │
  protocol/*                     frame parsers for the two radios
```

Two rules hold that together:

- **The entry point carries no logic.** [`catnip.py`](../catnip.py) adds the
  vendored dependency path and calls `main_cli()`. That is what makes the
  PyInstaller, `.deb`, `.pkg` and source layouts interchangeable.
- **Errors are turned into exit codes in exactly one place.** `main_cli()`
  runs Click with `standalone_mode=False` so the exceptions Click would
  swallow reach it, and maps each typed exception to its code. See
  [Reference](reference.md#exit-codes).

---

<a id="tree"></a>
## Directory structure

```text
catnip/
├── catnip.py                   # entry point: sys.path + main_cli()
├── lora_extcap.py              # Wireshark extcap plugin for LoRa
├── protocol/                   # radio frame drivers
│   ├── common.py               # SOF/EOF markers, pcap global header
│   ├── sniffer_ti.py           # CC1352 frame protocol (Zigbee/Thread/15.4)
│   ├── sniffer_sx.py           # SX1262 frame protocol (LoRa/FSK), LoRaTap
│   └── lora_ascii.lua          # Wireshark postdissector: payload as text
├── modules/
│   ├── core/                   # runtime core (see below)
│   ├── device/cli.py           # devices · identify · status
│   ├── firmware/               # images, flashing, boards, verification
│   ├── sniff/cli.py            # the sniff group, all seven subcommands
│   ├── radio/profiles.py       # named radio settings (profiles.toml)
│   ├── protocols/
│   │   ├── cli/                # cativity · meshtastic · lora · vhci groups
│   │   ├── cativity/           # 802.15.4 activity monitor
│   │   ├── meshtastic/         # decoder, live, dashboard, config
│   │   ├── sx1262/             # spectrum, scan
│   │   └── vhci/               # HCI bridge (see its own README)
│   └── utils/                  # output, shared options, completion, setup-env
├── scripts/dump_cli_tree.py    # dumps every --help: the docs' source of truth
├── tests/                      # 986 tests, including the CLI snapshot
├── packaging/ · installer/     # .deb, .pkg and .exe inputs
└── docs/                       # this documentation
```

Firmware images are **not** in the tree: they are downloaded to `~/.catnip/`
on demand. See [Firmware](firmware.md#downloads).

---

<a id="core"></a>
## The runtime core

`modules/core/` is what every command builds on:

| Module | Responsibility |
|---|---|
| [`cli.py`](../modules/core/cli.py) | root Click group, `-v/-vv`, the banner, `build_cli()`, `main_cli()` |
| [`exceptions.py`](../modules/core/exceptions.py) | the typed error hierarchy and its exit codes |
| [`usb_connection.py`](../modules/core/usb_connection.py) | finds boards by VID/PID, maps the three CDC interfaces to roles, numbers the devices |
| [`device_utils.py`](../modules/core/device_utils.py) | "give me a device or fail" — the shared selector |
| [`device_session.py`](../modules/core/device_session.py) | context manager: resolve a device **and** guarantee the firmware a command needs, flashing it if missing |
| [`firmware_verifier.py`](../modules/core/firmware_verifier.py) | identifies the running firmware in confidence order (stored id → protocol probe) |
| [`firmware_registry.py`](../modules/core/firmware_registry.py) | what each image *can do*, so commands ask for a capability rather than an id |
| [`bridge.py`](../modules/core/bridge.py) | the capture loops: serial in, pcap out, to file / pipe / terminal |
| [`pipes.py`](../modules/core/pipes.py) | FIFO on Unix, named pipe on Windows, plus the Wireshark launcher |
| [`extcap.py`](../modules/core/extcap.py) | finding Wireshark and its plugins, and bridging the Sniffle extcap |
| [`live_panel.py`](../modules/core/live_panel.py) | the live capture panel (`-l`) |
| [`vhci_bridge.py`](../modules/core/vhci_bridge.py) | `/dev/vhci` ↔ Sniffle, so BlueZ sees an `hciX` |

**`device_session()` is the one to know.** Before it existed, every sniff
subcommand repeated some fifty lines of "find the device, check the firmware,
flash it if missing, wait, re-verify" with small arbitrary differences. It is
now one context manager, which is why `sniff ble` and `sniff zigbee` behave
identically around everything except the radio.

---

<a id="commands"></a>
## Command modules

The CLI is split by feature area, one Click group per module, assembled by
`build_cli()`:

| Module | Commands |
|---|---|
| `modules/device/cli.py` | `devices`, `identify`, `status` |
| `modules/firmware/cli.py` | `flash`, `update`, `restore`, `verify` |
| `modules/sniff/cli.py` | `sniff` and its seven subcommands |
| `modules/protocols/cli/cativity.py` | `cativity` |
| `modules/protocols/cli/meshtastic.py` | `meshtastic` |
| `modules/protocols/cli/sx1262.py` | `lora` |
| `modules/protocols/cli/vhci.py` | `vhci` *(Linux)* |
| `modules/utils/system_cli.py` | `setup-env` *(Linux)* |
| `modules/utils/completion.py` | `completion` *(Linux, macOS)* |

Options shared by more than one command are **factories**, not constants, in
[`modules/utils/cli_options.py`](../modules/utils/cli_options.py): `-d/--device`
was declared fifteen times across seven modules, and a factory keeps the flag,
type and default identical while letting the few commands that narrow its
meaning pass their own help text.

Console output goes through
[`modules/utils/output.py`](../modules/utils/output.py) — one `rich` console,
one set of styles, and the `print_success` / `print_error` / `print_info` /
`print_dim` helpers that produce the `✓ ✗ ℹ` lines. Nothing prints directly.

---

<a id="firmware"></a>
## Firmware lifecycle

| Module | Responsibility |
|---|---|
| [`board.py`](../modules/firmware/board.py) | `BoardInfo` per generation, `Board:` line parsing, capability assertions |
| [`fw_aliases.py`](../modules/firmware/fw_aliases.py) | alias → official id → filename, per generation |
| [`flasher.py`](../modules/firmware/flasher.py) | downloading, caching, resolving and writing CC1352 images |
| [`cc2538.py`](../modules/firmware/cc2538.py) | the CC1352/CC2538 serial bootloader protocol itself |
| [`fw_metadata.py`](../modules/firmware/fw_metadata.py) | the `cc1352_fw_id` shell commands (NVS) |
| [`fw_update.py`](../modules/firmware/fw_update.py) | host MCU UF2 updates and version comparison |
| [`fw_status.py`](../modules/firmware/fw_status.py) | assembling what `status` reports |
| [`restore.py`](../modules/firmware/restore.py) | CC1352 recovery through the RP2040 CMSIS-DAP probe and OpenOCD |
| [`verify.py`](../modules/firmware/verify.py) | the three hardware test suites |

**Generation differences are data, not conditionals.** Every rule that differs
between a v2 and a v3 is a field on `BoardInfo` — `has_fw_id_storage`,
`can_self_program_cc1352`, `accepts_unnamed_images` — and no module outside
`board.py` may compare `board.generation` against a literal. A test enforces
that with an AST check, because a stray `== "v3"` is exactly how a CC1352P7
image ends up on a CC1352P1. See [Firmware](firmware.md#generations).

---

<a id="protocols"></a>
## Protocol implementations

Each is a self-contained sub-package under `modules/protocols/`, with its CLI
group kept separately in `modules/protocols/cli/`:

- **`cativity/`** — `runner.py` orchestrates, `packets.py` parses 802.15.4,
  `network.py` builds the topology, `graphs.py` draws.
- **`meshtastic/`** — `core.py` holds the shared crypto and packet parsing;
  `decoder.py` (offline), `live.py` (capture), `dashboard.py` (TUI) and
  `config.py` (PSK/config extraction) build on it.
- **`sx1262/`** — `spectrum.py` (matplotlib sweep) and `scan.py` (parameter
  sweep).
- **`vhci/`** — `bridge.py` plus HCI `commands.py`, `constants.py` and
  `events.py`. It has [its own README](../modules/protocols/vhci/README.md) for
  implementation notes.

---

<a id="drivers"></a>
## Radio drivers

`protocol/` is the lowest layer: turning bytes on a serial port into frames,
and frames into pcap records.

- **`sniffer_ti.py`** — the TI CC1352 frame protocol for Zigbee, Thread and
  raw 802.15.4.
- **`sniffer_sx.py`** — the SX1262 frame protocol for LoRa and FSK, plus
  everything LoRaTap: the DLT, the sync-word mapping, the Wireshark column
  layout and the `Decode As` rule. See [Wireshark](wireshark.md).
- **`common.py`** — the SOF/EOF markers and the pcap global header both
  drivers share.

They know nothing about Click, devices or firmware, which is what lets the
same drivers serve the CLI, `lora_extcap.py` and the tests.

---

<a id="tests"></a>
## Tests and the CLI snapshot

986 tests, run on `ubuntu-latest` against Python 3.12, 3.13 and 3.14. None of
them touch hardware.

Two are worth knowing about when you change the CLI:

- **`tests/test_cli_structure.py`** pins the assembled command tree — every
  command, every subcommand, every option flag — in an `EXPECTED_PARAMS` table.
  **A new command or flag fails the suite until that table is updated**, which
  is the point: the failure mode it guards against is a command that silently
  stops being registered, where the binary still builds and the subcommand is
  simply gone.

- **`scripts/dump_cli_tree.py`** dumps the full `--help` text of every command.
  Its output is committed as `tests/snapshots/cli_tree_linux.txt` and is the
  source every option table in `docs/commands/` is copied from. The diff also
  covers help *wording*, but it is sensitive to the Click version, so it is a
  manual check rather than a test — regenerate it whenever you change a help
  string:

  ```sh
  python scripts/dump_cli_tree.py > tests/snapshots/cli_tree_linux.txt
  ```

- **`tests/test_board_support.py`** holds the AST check described above, plus
  the invariant that the firmware emits the `Board:` line.

---

## See also

- Adding a command, protocol or firmware: [Contributing](contributing.md).
- Wire formats and framing: [Protocol](protocol.md).
- What the packaged builds contain: [Packaging](packaging.md).
