---
name: catsniffer
description: Operate an Electronic Cats CatSniffer RF board with the catnip CLI and the other CatSniffer-Tools. Covers finding a board, reading its status, flashing or restoring CC1352 firmware, updating the RP2040/SAMD21 firmware, and sniffing BLE, Zigbee, Thread, LoRa, (G)FSK and AirTags to the terminal, pcap or Wireshark. Also covers 802.15.4 channel surveys (cativity), LoRa spectrum and scan, Meshtastic decoding, the VHCI Bluetooth bridge, the catsnifferTUI testbench, and the repo's tests and CLI snapshot. Use whenever the user mentions CatSniffer, catnip, catsnifferTUI, sniffing or capturing any of those protocols, flashing the board, Sniffle, the TI sniffer, LoRaTap, or a pcap from the board.
---

# CatSniffer tools

A CatSniffer is a multi-protocol RF board with three chips behind one USB cable:

| Chip | Job | Firmware written by |
|---|---|---|
| **CC1352** (P1 on v2, P7 on v3) | 2.4 GHz radio: BLE, Zigbee, Thread, AirTag | `catnip flash` (`.hex` over the serial bootloader) |
| **SX1262** | Sub-GHz: LoRa, (G)FSK | no image of its own; the host MCU drives it, so LoRa and FSK only need radio settings |
| **Host MCU** (SAMD21 on v1/v2, RP2040 on v3) | USB, Cat-Shell, SX1262 control, debug probe | `catnip update` (`.uf2` copied to a USB volume) |

Each board exposes **three USB CDC ports** (VID:PID `1209:babb`):

- **Cat-Bridge**: CC1352 traffic.
- **Cat-LoRa**: SX1262.
- **Cat-Shell**: board identity, firmware and bootloader control.

catnip groups the three ports per board, so you never pass a port path. You pass `-d N` instead.

**The key fact: the CC1352 holds one image at a time, and that image must match the protocol.** Sniffle handles BLE. The TI sniffer handles Zigbee and Thread. The AirTag scanner handles Find My. `catnip sniff <proto>` flashes the right image on the way in, so switching from Zigbee to BLE means a reflash.

## Where things live in this repo

| Path | What |
|---|---|
| `catnip/` | **The main tool**: `catnip` CLI (Click + rich), version in `catnip/VERSION` |
| `catnip/docs/` | Full manual. `usage.md`, `reference.md`, `troubleshooting.md`, `firmware.md`, `wireshark.md`, `limitations.md`, and one page per command in `docs/commands/` |
| `catnip/tests/snapshots/cli_tree_linux.txt` | Every `--help` in the tree, as a snapshot |
| `catnip/lora_extcap.py` | Standalone Wireshark extcap for LoRa, with a live toolbar |
| `catnip/modules/protocols/vhci/README.md` | VHCI bridge internals and per-tool examples (bluetoothctl, bettercap, bleak, btmon) |
| `catsnifferTUI/` | Textual multi-device testbench: hotplug, an 11-step smoke test, interactive terminals |
| `Legacy/` | Retired tools (pycatsniffer_bv3, cc2538-bsl, catnip_uploader, cativity, sx1262Tools). **Do not use them for new work.** Each has been folded into catnip; see the table at the end |

When a flag or behaviour is in doubt, **run `--help`** on the live CLI. It is the source of truth. The committed snapshot can lag behind the code. `catnip/docs/commands/<cmd>.md` has the long-form explanation.

## Running catnip

```sh
catnip <command> ...                 # installed (.deb/.pkg/.exe/AUR or `pip install -e .`)
cd catnip && python catnip.py ...    # from a checkout
```

Setting up from source needs Python **3.12+**. `setup.py` says 3.9, but that is wrong.

```sh
cd catnip
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt && pip install -e .
```

Rules that trip people up:

- **Global `-v`/`-vv` goes before the command**: `catnip -v sniff zigbee -c 15`. `vhci start -v` and `sniff lora/fsk -v` are separate per-command flags.
- **There is no `--version` flag.** The version is in the banner every command prints, or in `catnip/VERSION`.
- **`-d N` is a board index from `catnip devices`**, starting at 1, not a port. Omitting it picks the *first* board. IDs renumber after any replug. `verify` without `-d` tests *every* board.
- **`CATNIP_DEBUG=1`** prints the full traceback. Without it, an error is one line. Ask for this output in bug reports.
- **`CATNIP_PROFILES_FILE`** overrides `~/.config/catnip/profiles.toml`.
- **Commands that exist only on some platforms**:
  - `vhci` and `setup-env`: Linux only.
  - `completion`: Linux and macOS only (bash, zsh, fish).
- **Exit codes**:

  | Code | Meaning |
  |---|---|
  | 0 | OK. `devices` also exits 0 when it finds nothing. |
  | 1 | Generic error. "No CatSniffer device found" also exits 1, not 4. |
  | 2 | Usage error |
  | 3 | Firmware error |
  | 4 | Device or connection error |
  | 5 | Not supported on this board generation |
  | 130 | Ctrl-C |

  Scripts should branch on non-zero and not on the specific code.

## Hardware access: be honest about it

Almost every catnip command needs a physical board on USB. Before running one, check the board is reachable from *this* machine with `catnip devices`.

- If no board is reachable, say so plainly. If the board is on the user's computer, run the command there, or give them the exact command to run.
- **Never invent device output, packet captures or firmware versions.**
- These commands work without hardware:
  - `--help` at any level
  - `sniff profiles`
  - `flash --list --all`
  - `meshtastic decode` and `meshtastic config`
  - the test suite (`pytest -m "not hardware"`)

Captures and live views (`sniff`, `cativity`, `lora spectrum/scan`, `meshtastic live/dashboard`, `vhci start`) run until Ctrl-C. To run one unattended, put it in the background or under `timeout`, and write to a file with `-w`.

## Golden path

```sh
sudo catnip setup-env           # Linux, once: udev rules + dialout/bluetooth groups; then log out/in
catnip devices                  # one row per board, three ports each. Empty -> stop, troubleshoot
catnip status                   # board generation (v2/v3), firmware on CC1352 + host MCU, capabilities
catnip verify                   # exercise the board if anything looks off (add --test-all only if TX is OK)
catnip cativity                 # 802.15.4 only: find the busy channel (11-26)
catnip sniff zigbee -c 15 -ws -w capture.pcap   # flash-if-needed, then terminal + Wireshark + file
```

Every capture has the same shape: pick the subcommand, say where to listen, and say where the packets go.

## Task → command

| Goal | Command |
|---|---|
| List boards / blink one | `catnip devices [--debug]`, `catnip identify -d N` |
| What is it running? | `catnip status [-d N] [-D]` |
| Self-test | `catnip verify [-d N] [-q]` (`--test-all` **transmits** on 915 MHz at 14 dBm and leaves the SX1262 at SF7/BW125) |
| See or flash CC1352 images | `catnip flash --list [--all] [--full]`, `catnip flash <alias> [-d N] [--board v2\|v3]` |
| Refresh the firmware cache (`~/.catnip/`) | `catnip flash --refresh [--force]` |
| Update host MCU firmware | `catnip update [-f] [--board v2\|v3]` |
| CC1352 bootloader dead (v3 only, needs OpenOCD) | `catnip restore [file.hex] [-d N] [--board v3]` |
| BLE | `catnip sniff ble [-c 37\|38\|39] [-m conn_follow\|passive_scan\|active_scan] [-ws]` |
| Zigbee / Thread | `catnip sniff zigbee -c CH ...`, `catnip sniff thread -c CH ...` (`-c` is required, 11-26) |
| LoRa | `catnip sniff lora [-freq HZ -sf N -bw 125\|250\|500 -cr N -sw private\|public\|0xNN -pre N --iq normal\|inverted] [-P profile]` |
| (G)FSK, sub-GHz | `catnip sniff fsk [-freq HZ -br BPS -fd HZ -bw KHZ -sw HEX --bt ... --whitening --crc --pktlen ...] [-P profile]` |
| AirTags / Find My | `catnip sniff airtag_scanner [--putty]` |
| Radio presets | `catnip sniff profiles [-c lora\|fsk]` (the built-in presets are Meshtastic LoRa presets for us915/eu868), then `-P <name>` (explicit flags still win). Save your own with `--save-profile NAME` |
| 802.15.4 activity / topology | `catnip cativity [-c CH] [-t] [-p all\|zigbee\|thread]` |
| Sub-GHz spectrum | `catnip lora spectrum [--start-freq MHz --end-freq MHz --offset dBm]` |
| Unknown LoRa transmitter | `catnip lora scan [-f 868.1,868.3] [--sf 7,9] [--bw 125] [--dwell S] [--passes N] [-sw 0x2B]` |
| Meshtastic | `catnip meshtastic config FILE`, `decode -i HEX [-k B64\|ham\|nokey]`, `live` / `dashboard [-f MHz] [-ps LongFast]` |
| Board as a Linux BLE adapter | `sudo modprobe hci_vhci && catnip vhci check && sudo catnip vhci start` → `hciN` |
| Tab completion | `catnip completion install [--shell bash\|zsh\|fish]` |

### Output sinks (combine freely)

The LoRa/FSK sniffers and the Zigbee/Thread sniffers support these sinks:

- **No flag**: packets print to the terminal.
- **`-ws`**: live Wireshark through a FIFO at `/tmp/fcatnip` (`\\.\pipe\fcatnip` on Windows). Only one live capture can run per machine.
- **`-w FILE`**: writes `.pcap`, or `.pcapng` when the name ends in `.pcapng`. It refuses to overwrite an existing file unless you add `-f`.
- **`-r FILE` / `-ascii FILE`**: hex or ASCII logs.

LoRa and FSK also support:

- **`-l`**: a live stats panel.
- **`-oc`**: opens Wireshark when the capture stops.

### Firmware aliases (for `flash`)

| Alias | Image | Supported boards |
|---|---|---|
| `ble`, `sniffle` | Sniffle | v2 and v3 |
| `zigbee`, `thread`, `15.4`, `ti`, `sniffer`, `multiprotocol` | TI sniffer | **v3 only** |
| `airtag_scanner` / `airtag-scanner` | Find My scanner | v3 only |
| `airtag_spoofer` / `airtag-spoofer` | Find My emulator | v3 only |
| `justworks` | BLE JustWorks scanner | v3 only |

`flash` also accepts a `.hex` path. LoRa is **not** a CC1352 image: the `lora-*` aliases that `flash --list` still prints are retired.

## Safety rules (do not skip)

1. **Board generation matters for flashing.** A CC1352P7 (v3) image written to a CC1352P1 (v2) disables the serial bootloader. Recovering needs an external cJTAG programmer. catnip refuses when the generation is unknown.
   - **Only pass `--board v2|v3` when the user knows which board they have.** Never pass it as a guess to get past an error.
   - v2 boards can do BLE but not Zigbee, Thread, AirTag, `restore` or `vhci`. Expect exit code 5 for those.
2. **Transmitting.** Most of catnip only listens. A few commands transmit:
   - `verify --test-all`
   - `sniff ble -m active_scan` (it sends SCAN_REQ; `passive_scan` and `conn_follow` only listen)
   - `vhci` (the board becomes an active BLE controller)
   - the AirTag spoofer image
   - non-default `-pw` (TX power)

   Before running any of these, confirm with the user that transmitting is legal where they are.
3. **Authorisation.** Capture only networks and devices the user owns or has written permission to test. If the target sounds like third-party traffic, ask before helping.
4. **Close serial monitors first.** A busy port (minicom, screen, PuTTY, the TUI) makes commands fail. Only one tool can own a port.

## Troubleshooting quick hits

Full symptom list with ordered checks: `catnip/docs/troubleshooting.md`.

- **`devices` lists nothing**: check the cable carries data, then `lsusb | grep 1209:babb`, then permissions (`setup-env` + re-login, or the `dialout` group).
  - If `lsusb` sees the board but catnip doesn't, fewer than three ports enumerated, so catnip skips the board.
  - On Windows, `devices --debug` shows the raw port mapping.
- **Permission denied**: run `sudo catnip setup-env`, then log out and back in.
- **Generation unknown, or flash refused**: run `catnip status`. If the shell port is dead, use `--board` with the *known* generation.
  - Bootloader gone on a v3: `catnip restore`. It needs OpenOCD, which on Linux needs `apt install openocd`.
- **Capture runs, no packets**: check, in order:
  - the right channel. Run `cativity` first for 802.15.4.
  - for LoRa, the exact frequency, SF, BW and sync word. Try a `-P` profile, or `lora scan` to find them.
  - for FSK, the bitrate, deviation and sync word.
  - for LoRaWAN downlinks, `--iq inverted`.
- **Wireshark empty**, by protocol:
  - **Zigbee/Thread** need Wireshark profiles named exactly `Zigbee` / `Thread`, with USER0 (DLT 147) mapped to the 802.15.4 dissector.
  - **BLE** needs NCC Group's `sniffle_extcap` plugin in the extcap folder. catnip does not bundle it.
  - **LoRa/FSK** are dissected natively as LoRaTap (DLT 270). No setup is needed.
- **Stale FIFO** after a crash: `rm /tmp/fcatnip`.
- **Traceback wanted**: `CATNIP_DEBUG=1 catnip <cmd>`.

## Working on the code

```sh
cd catnip
pytest -q                     # full suite
pytest -m "not hardware"      # no board needed
pytest -k cli_structure       # CLI tree vs snapshot
python scripts/dump_cli_tree.py > tests/snapshots/cli_tree_linux.txt   # after changing any command/flag
```

- Layout:
  - `modules/core/cli.py`: `build_cli()`, platform gating and `main_cli()` exit-code mapping.
  - `modules/sniff/`, `modules/firmware/`, `modules/protocols/{cativity,meshtastic,sx1262,vhci}`: the commands.
  - `modules/radio/profiles.py`: LoRa/FSK presets.
  - `modules/firmware/fw_aliases.py`: alias → image table, per board generation.
  - `protocol/`: TI and SX framing, pcap.
- Conventions for adding a command, protocol or image: `catnip/docs/contributing.md`.
- Release steps: `catnip/docs/release.md`. The version string lives in seven places.
- When you change a command's flags, update `catnip/docs/commands/<cmd>.md` and regenerate the snapshot.

## Other tools

- **catsnifferTUI**: factory and bench testing of many boards at once.
  - Run from the **repo root**: `pip install -r catsnifferTUI/requirements.txt && python -m catsnifferTUI`. It uses relative imports, so it will not start from inside its own folder. It needs Python 3.11+.
  - Keys: `R` rescans, `0`–`4` switch tabs, `L` opens logs, `Q` quits.
  - Smoke test: Cat-Shell runs `status`, `band3`, `modulation lora`, `lora_mode command`, `lora_config`, `lora_apply`, then Cat-LoRa runs `TEST` and `TXTEST`. After that, Cat-Shell runs `modulation fsk` and `fsk_apply`, and Cat-LoRa runs `FSKTEST`. **It transmits.**
- **lora_extcap.py**: starts LoRa captures from Wireshark's interface list, with a live toolbar.
  - It emits DLT 148 (USER1), which needs a Wireshark mapping.
  - Prefer `catnip sniff lora -ws` (LoRaTap, works out of the box) unless the user wants the toolbar.
- **Legacy → catnip replacements**:

  | Legacy tool | Use instead |
  |---|---|
  | `pycatsniffer_bv3` | `catnip sniff` |
  | `cc2538-bsl` / `catnip_uploader` | `catnip flash` |
  | `cativity` | `catnip cativity` |
  | `sx1262Tools` | `catnip lora` / `catnip meshtastic` |

  Point users at the catnip equivalent rather than the legacy script.

For worked end-to-end scenarios, see [references/recipes.md](references/recipes.md). It covers a Zigbee investigation, BLE connection following, LoRaWAN, Meshtastic, an unknown sub-GHz device, FSK meters, a v2 board, recovery, scripting and VHCI.
