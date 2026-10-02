# Limitations

What catnip does not do, and where it does less. Two kinds of limit live here:
**platform support** — which commands exist at all on your OS — and **known
gaps**, the rough edges worth knowing about before they surprise you.

- [Platform support](#platform-support)
- [What the evidence is](#evidence)
- [Board generation limits](#board-limits)
- [Known gaps](#known-gaps)

---

<a id="platform-support"></a>
## Platform support

| Command | Linux | macOS | Windows |
|---|---|---|---|
| `devices` · `identify` | ✅ | ⚠️ | ⚠️ |
| `status` | ✅ | ⚠️ | ⚠️ |
| `verify` | ✅ | ⚠️ | ⚠️ |
| `flash` · `update` | ✅ | ⚠️ | ⚠️ |
| `restore` | ✅ | ⚠️ | ⚠️ |
| `sniff` (all subcommands) | ✅ | ⚠️ | ⚠️ |
| `cativity` | ✅ | ⚠️ | ⚠️ |
| `meshtastic` | ✅ | ⚠️ | ⚠️ |
| `lora` | ✅ | ⚠️ | ⚠️ |
| `vhci` | ✅ | ❌ | ❌ |
| `setup-env` | ✅ | ❌ | ❌ |
| `completion` | ✅ | ⚠️ | ❌ |

✅ available, exercised · ⚠️ available, not systematically tested ·
❌ not offered

**The `❌` rows are not registered at all.** `build_cli()` adds `vhci` and
`setup-env` only on Linux and `completion` only on Linux and macOS
([`modules/core/cli.py`](../modules/core/cli.py)), so on the other platforms
they do not appear in `catnip --help` and an attempt to run one is a usage
error, not a runtime failure.

The reasons are structural, not scheduling:

- **`vhci`** needs `/dev/vhci`, the `hci_vhci` kernel module and BlueZ. There
  is no equivalent on macOS or Windows.
- **`setup-env`** writes a udev rule and edits Unix group membership. Neither
  concept exists elsewhere; macOS does not gate serial ports the same way, and
  Windows uses drivers.
- **`completion`** generates bash, zsh and fish scripts. PowerShell is not
  covered.

Platform-specific code paths that *do* exist everywhere:

| Concern | Linux | macOS | Windows |
|---|---|---|---|
| Capture pipe | FIFO at `/tmp/fcatnip` | FIFO at `/tmp/fcatnip` | named pipe `\\.\pipe\fcatnip`, needs **pywin32** |
| UF2 bootloader volume | `/media/*`, `/run/media/*`, `/mnt` | `/Volumes` | drive-letter scan |
| Wireshark lookup | `/usr/bin`, `/usr/local/bin`, Flatpak, `PATH` | `/Applications/Wireshark.app` | `C:\Program Files\Wireshark` |
| extcap plugin directory | `~/.local/lib/wireshark/extcap` | `~/.local/lib/wireshark/extcap` | `%APPDATA%\Wireshark\extcap` |
| Serial port roles | interface descriptor | interface descriptor | positional fallback, `--debug` to diagnose |

---

<a id="evidence"></a>
## What the evidence is

Be clear about what the table above claims. **Linux is where catnip is
developed and the only platform the test suite ever runs on** — `tests.yml`
runs on `ubuntu-latest` against Python 3.12, 3.13 and 3.14. macOS and Windows
do get CI runners, but only to *build* installers (`build-mac.yml` on
`macos-15-intel` and `macos-latest`, `build-windows.yml` on `windows-latest`);
neither runs a single test. So a `⚠️` means "written for it, and it compiles
and packages there, but no behaviour is proven on it".

Hardware-dependent behaviour is a further step removed: the test suite does not
touch a board, so every `✅` covers the command's logic, not a captured packet.

---

<a id="board-limits"></a>
## Board generation limits

A **v2** (SAMD21 + CC1352P1) cannot do several things a **v3** (RP2040 +
CC1352P7) can, and catnip says so with a dedicated exit code (`5`) rather than
letting the attempt fail halfway:

| Feature | v2 | v3 | Why |
|---|---|---|---|
| BLE sniffing (Sniffle) | ✅ | ✅ | the one CC1352P1 image that ships |
| Zigbee / Thread sniffing | ❌ | ✅ | no CC1352P1 build of the TI sniffer |
| AirTag scanner | ❌ | ✅ | no CC1352P1 build |
| Firmware id in NVS | ❌ | ✅ | the SAMD21 build has no `CONFIG_NVS` — 16 KB of SRAM |
| `restore` through the debug probe | ❌ | ✅ | needs the RP2040's CMSIS-DAP probe |
| `vhci` bridge | ❌ | ✅ | only validated on v3 |

Without NVS, firmware detection on a v2 falls back to behavioural probing —
slower, and less certain than reading back an id.

See [Firmware](firmware.md) for the catalogue behind this table.

---

<a id="known-gaps"></a>
## Known gaps

**Declared Python version is wrong.**
[`setup.py`](../setup.py) says `python_requires=">=3.9"`, but the code uses
3.10+ syntax — `hint: list[str] | None` in
[`modules/core/exceptions.py`](../modules/core/exceptions.py) is evaluated at
import time and raises on 3.9. The classifiers and CI both target 3.12–3.14.
Treat **3.12+** as the real floor.

**Not every failure carries its typed exit code.** The shared device lookup
prints its message and exits `1`, so "no board connected" — the most common
failure there is — never reaches the `4` the table in
[Reference](reference.md#exit-codes) promises. Branch on non-zero, not on the
specific code.

**One capture at a time per machine.** The live path uses a fixed pipe name
(`fcatnip`), so two simultaneous Wireshark captures collide. Run them on
separate machines, or capture to files with `-w` and open them afterwards.

**The Sniffle extcap plugin is not bundled.** BLE into Wireshark needs
`sniffle_extcap` installed separately; catnip detects its absence and says so,
but cannot install it for you. LoRa needs no plugin — it is dissected natively
as [LoRaTap](glossary.md#loratap).

**`flash --list` is clipped below ~140 columns.** The `Description` column
declares a minimum width that does not fit, and `rich` truncates the table
instead of wrapping it
([`modules/firmware/cli.py:218`](../modules/firmware/cli.py#L218)).

**`flash --list` still advertises retired LoRa aliases.** Its `Usage Examples`
block names `lora-sniffer`, `lora-cli`, `lora-cad` and `lora-freq`, which no
longer appear in the alias listing above it. LoRa capture is an SX1262
configuration, not a CC1352 image — use [`sniff lora`](commands/sniff.md).

**`verify --test-all` transmits, and leaves the radio reconfigured.** It emits
on 915 MHz at 14 dBm, and ends with the SX1262 on SF7 / BW125 / CR4-5. Confirm
that transmitting is legal where you are, and re-apply your own settings before
the next capture.

**No `--version` flag.** The version is printed in the banner every command
shows. Scripts that need it should read `VERSION` in the repository root.

---

## See also

- Symptoms and fixes: [Troubleshooting](troubleshooting.md).
- Exit codes and global behaviour: [Reference](reference.md).
- Per-generation firmware detail: [Firmware](firmware.md).
