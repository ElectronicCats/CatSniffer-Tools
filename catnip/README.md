# catnip — CatSniffer control CLI and tooling

One command-line tool for the [CatSniffer](https://github.com/ElectronicCats/CatSniffer)
multi-protocol RF board: it finds the board, puts the right firmware on it,
captures BLE, Zigbee, Thread, LoRa and FSK traffic, and hands the packets to
your terminal, a `.pcap` file or a live Wireshark session.

The CC1352 covers the 2.4 GHz protocols and the SX1262 covers sub-GHz, so one
board sniffs both bands — but the CC1352 holds exactly one image at a time, and
**the firmware must match the protocol you want to capture**. catnip flashes it
for you on the way into a capture.

Hardware, schematics and the board's own documentation live in the
[CatSniffer wiki](https://github.com/ElectronicCats/CatSniffer/wiki).

---

## Install

| Platform | Asset from the [Releases page](https://github.com/ElectronicCats/CatSniffer-Tools/releases) |
|---|---|
| Windows 10/11 (64-bit) | `Catnip-Setup.exe` — run it as administrator, the USB drivers need it |
| macOS 11+ (Intel / Apple Silicon) | `catnip-<version>.pkg` |
| Debian 11+ / Ubuntu 20.04+ | `catnip-<version>.deb` |
| Arch and derivatives | `catnip-<version>.pkg.tar.zst`, or the AUR |

The packaged builds bundle a Python runtime and every dependency: nothing else
has to be installed first, at the cost of about 100 MB on disk.

**From source** — the development route, and the only one that gets you the
test suite. Python 3.12 or newer:

```sh
git clone https://github.com/ElectronicCats/CatSniffer-Tools.git
cd CatSniffer-Tools/catnip
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Per-platform steps, post-installation and uninstallation:
[docs/installation.md](docs/installation.md).

---

## Quick start

```sh
# 1. Linux only: udev rules and group membership, so the serial ports open
#    without sudo. Log out and back in afterwards.
sudo catnip setup-env

# 2. Confirm the board is seen — one row per board, three ports each.
#    If this lists nothing, no other command will find it either.
catnip devices

# 3. Ask the board what it is and what firmware it is running.
catnip status

# 4. Find a busy 802.15.4 channel before capturing on it.
catnip cativity

# 5. Capture. The firmware it needs is flashed on the way in; the packets go
#    to the terminal, to Wireshark and to a file, all at once.
catnip sniff zigbee -c 15 -ws -w capture.pcap
```

The shape of that last line is the same for every protocol: pick the
subcommand, say where to listen, say where the packets go. The full walkthrough
is [docs/usage.md](docs/usage.md).

---

## Documentation

Start at [docs/usage.md](docs/usage.md) if you have a board in front of you, or
[docs/reference.md](docs/reference.md) if you are looking for a flag.

| Page | What's in it |
|---|---|
| [usage.md](docs/usage.md) | The path from a board in a box to packets on screen: the three-port pipeline, first run, a typical session, and where captures can be sent. |
| [reference.md](docs/reference.md) | Everything true of the CLI as a whole — invocation, global options, the `-d/--device` selector, environment variables (`CATNIP_DEBUG`, `CATNIP_PROFILES_FILE`), exit codes, and the command index. |
| [firmware.md](docs/firmware.md) | Which chip runs what, the image catalogue and its aliases, how a name on the command line becomes a file on disk, the `~/.catnip/` cache and the NVS metadata. |
| [wireshark.md](docs/wireshark.md) | Live FIFO versus written file, what each protocol needs to dissect (Zigbee/Thread profiles, the Sniffle plugin, native LoRaTap), the `lora_extcap.py` plugin and the Lua postdissector. |
| [troubleshooting.md](docs/troubleshooting.md) | 21 symptoms, each with the checks in the order worth doing them: no devices, permission denied, flashing failures, empty captures, serial terminals. |
| [limitations.md](docs/limitations.md) | Which commands exist on which OS, and the known rough edges with a link to the code that causes each one. |
| [glossary.md](docs/glossary.md) | The 32 terms these pages assume — CC1352, SX1262, extcap, VHCI, NVS, SF/BW, LoRaTap, 802.15.4 — each linked to where it actually matters. |
| [installation.md](docs/installation.md) | Install and uninstall per platform, post-installation permissions, and how to verify the result. |
| [architecture.md](docs/architecture.md) | The four layers, the real module tree, the firmware lifecycle and how the CLI snapshot keeps the docs honest. For anyone about to change the code. |
| [protocol.md](docs/protocol.md) | The wire level: what travels over each of the three serial ports, TI framing versus SX1262 text, the LoRaTap header, pcap records and pipes. |
| [packaging.md](docs/packaging.md) | Building the artefacts yourself — PyInstaller bundles, the `.deb`, the macOS `.pkg`, the Inno Setup installer, Nuitka and the Makefile targets. |
| [release.md](docs/release.md) | Cutting a version: the seven places the version number lives, the procedure, the checklist, and what publishing changes for people running `catnip update`. |
| [contributing.md](docs/contributing.md) | Adding a command, a protocol or a firmware image to the project, with the conventions each one has to follow. |

**One page per command group**, in [docs/commands/](docs/commands/). Each opens
with a *Quick Start* block you can paste:

| Page | Commands |
|---|---|
| [devices.md](docs/commands/devices.md) | `devices`, `identify` — discovery and the three-port architecture |
| [status.md](docs/commands/status.md) | `status` — board generation, firmware, capabilities |
| [verify.md](docs/commands/verify.md) | `verify` — shell, LoRa config and LoRa transmission tests |
| [flash.md](docs/commands/flash.md) | `flash`, `update` — the image catalogue and the flashing pipeline |
| [restore.md](docs/commands/restore.md) | `restore` — CC1352 recovery when the bootloader stopped answering |
| [sniff.md](docs/commands/sniff.md) | `ble`, `zigbee`, `thread`, `lora`, `fsk`, `airtag_scanner`, `profiles` |
| [spam.md](docs/commands/spam.md) | `spam` — BLE advertising spam (`start`, `stop`, `status`, `modes`) |
| [cativity.md](docs/commands/cativity.md) | `cativity` — 802.15.4 channel activity and network topology |
| [meshtastic.md](docs/commands/meshtastic.md) | `decode`, `live`, `dashboard`, `config` |
| [lora.md](docs/commands/lora.md) | `spectrum`, `scan` — survey the sub-GHz band before capturing |
| [vhci.md](docs/commands/vhci.md) | `check`, `start` — expose the CatSniffer as `hciX` (Linux) |
| [setup-env.md](docs/commands/setup-env.md) | `setup-env` — udev rules and group membership (Linux) |
| [completion.md](docs/commands/completion.md) | `completion install` — bash, zsh and fish tab completion |

This README documents no flags. Every option is in the page for its command.

---

## Dev tooling

| Tool | What it does |
|---|---|
| `scripts/dump_cli_tree.py` | Walks the live command tree and dumps every `--help`. The source of truth for the docs — regenerate the snapshot after any CLI change. |
| `lora_extcap.py` | Standalone Wireshark extcap plugin for LoRa, usable without the CLI. See [wireshark.md](docs/wireshark.md). |
| `scripts/install.sh` | Global symlink used by `make install`. |
| `scripts/install_windows_drivers.ps1` | USB-serial drivers, run by the Windows installer. |
| `Makefile` | `make install`, `make compile-install` (Nuitka), `make uninstall`, `make clean`. |

```sh
python scripts/dump_cli_tree.py > tests/snapshots/cli_tree_linux.txt
```

---

## Tests

```sh
pytest -q                      # the whole suite
pytest -m "not hardware"       # skip the board-dependent tests
pytest -k cli_structure        # the CLI snapshot against build_cli()
```

`tests/snapshots/cli_tree_linux.txt` is compared against the real command tree,
so a command, subcommand or flag cannot change without the test noticing.
[`.github/workflows/tests.yml`](../.github/workflows/tests.yml), at the root of
the monorepo, runs the suite on Python 3.12, 3.13 and 3.14, on Linux only, with
coverage reported to Codecov. The copy under `catnip/.github/` is never run —
GitHub reads workflows only from the repository root.

---

## Current limitations

- **Linux is the tested platform.** macOS and Windows are supported and used,
  but CI does not exercise them; `vhci` and `setup-env` are Linux-only and
  `completion` does not cover PowerShell.
- **One live capture at a time per machine** — the Wireshark path uses a fixed
  pipe name.
- **BLE into Wireshark needs the Sniffle extcap plugin**, which is not bundled.

The full matrix and the rest of the known gaps, each with a link to the code:
[docs/limitations.md](docs/limitations.md).

---

## Firmware and hardware

| Repository | What it holds |
|---|---|
| [CatSniffer](https://github.com/ElectronicCats/CatSniffer) | The board: schematics, hardware revisions, wiki. |
| [CatSniffer-Firmware](https://github.com/ElectronicCats/CatSniffer-Firmware) | The images catnip downloads and flashes — system `.uf2`, TI sniffer, AirTag, JustWorks. |
| [Sniffle](https://github.com/nccgroup/Sniffle) | The BLE sniffer firmware, fetched from its own releases. |
| [CatSniffer-Tools](https://github.com/ElectronicCats/CatSniffer-Tools) | This repository — the CLI and its releases. |

catnip resolves firmware from the release tags of those repositories and caches
them under `~/.catnip/`; see [docs/firmware.md](docs/firmware.md).

---

## Disclaimer

> [!IMPORTANT]
> catnip captures and analyses radio traffic. Use it only on networks and
> devices you own or have written permission to test. Intercepting third-party
> communications is illegal in most jurisdictions. Most of catnip only listens,
> but two paths do transmit — `verify --test-all` emits a LoRa frame, and
> [`vhci`](docs/commands/vhci.md) turns the board into an active Bluetooth
> controller — and local regulations on frequency, power and duty cycle apply
> to you when they do.

---

## Contribute

Issues and pull requests go to
[CatSniffer-Tools](https://github.com/ElectronicCats/CatSniffer-Tools). A good
bug report carries the catnip version from the startup banner, your OS, the
exact command, and the output — a traceback in particular, since every handled
error is supposed to be a one-line message.

Adding a command, a protocol driver or a firmware image has conventions worth
reading first: [docs/contributing.md](docs/contributing.md).

---

## License

GPL-3.0 — see [LICENSE](../LICENSE) at the root of the repository.

## Credits

Developed by **Electronic Cats — PWNLAB**.
Version 3.3.3.0 · [electroniccats.com](https://electroniccats.com)
