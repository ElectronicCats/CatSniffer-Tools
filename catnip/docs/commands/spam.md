# `catnip spam`

> BLE advertising-spam control (CC1352P7 `ble_spam` firmware)

Drives the `ble_spam_cc1352p_7` firmware, which emits BLE *advertising* frames
carrying multi-vendor payloads (Apple / Android / Windows / Samsung) to provoke
pairing dialogs on nearby devices.

This is a **security-research / pentesting** tool. Use it only on devices you
own or are explicitly authorised to test. The CLI adds no new offensive
capability — it surfaces the control the firmware already exposes over UART,
the same way `catnip sniff airtag_scanner` surfaces the AirTag firmware.

- [`modes`](#spam-modes) — list the vendor modes (no hardware needed).
- [`start`](#spam-start) — select a mode and begin emitting.
- [`run`](#spam-run) — emit with a live view of the cycle (Ctrl+C to stop).
- [`status`](#spam-status) — report mode, running state and model count.
- [`stop`](#spam-stop) — stop emitting.

If the firmware is not present, these commands flash it first (verified by
metadata, `cc1352_fw_id=ble_spam_cc1352p_7`) — the same session flow as the
sniff commands.

## Quick Start

```sh
# See the vendor modes without a device attached
catnip spam modes

# Emit Apple pairing adverts (authorised targets only)
catnip spam start --mode apple

# Check what it is doing, then stop
catnip spam status
catnip spam stop
```

> **Note:** the firmware boots emitting in `all` mode after a flash or reset.
> `catnip spam status` never stops an active cycle; `catnip spam stop` does.

---

## Subcommands

<a id="spam-modes"></a>
### `spam modes`

> List the available vendor modes (no device needed).

Prints each mode's long token and its single-letter alias: `all` (a),
`apple` (p), `android` (n), `windows` (w), `samsung` (s).

<a id="spam-start"></a>
### `spam start`

> Select a mode and start emitting.

| Option | Description |
|---|---|
| `-m, --mode [all\|apple\|android\|windows\|samsung]` | Vendor advertising set to emit (default: `all`) |
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-b, --baudrate INTEGER` | Override the bridge baudrate (default: firmware value, 921600) |
| `-y, --yes` | Skip the authorised-use confirmation prompt (for scripting) |

```sh
catnip spam start                 # emit the full multi-vendor set
catnip spam start --mode apple    # only Apple payloads
catnip spam start --mode apple -y # skip the confirmation (scripting)
```

Before it begins, the command prints the authorised-use warning and asks for
confirmation; declining aborts and nothing is emitted. Pass `-y/--yes` to skip
the prompt in scripts.

The firmware is left emitting after this returns; run [`stop`](#spam-stop) to
halt it. Selecting a mode while a cycle is running restarts it with the new
mode.

<a id="spam-run"></a>
### `spam run`

> Start emitting and show a live view of the cycle (Ctrl+C to stop).

| Option | Description |
|---|---|
| `-m, --mode [all\|apple\|android\|windows\|samsung]` | Vendor advertising set to emit (default: `all`) |
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-b, --baudrate INTEGER` | Override the bridge baudrate (default: firmware value, 921600) |
| `-y, --yes` | Skip the authorised-use confirmation prompt (for scripting) |

```sh
catnip spam run --mode apple      # live panel while emitting Apple payloads
```

Like [`start`](#spam-start), it prints the authorised-use warning and asks for
confirmation before emitting (skip with `-y/--yes`). Renders a fixed panel — active mode, elapsed time, the model being advertised
now, ads emitted and the last rotated address. Unlike [`start`](#spam-start),
this is an interactive session: pressing **Ctrl+C** (or the stream ending) always
stops the firmware and closes the port, so the hardware is never left emitting.

<a id="spam-status"></a>
### `spam status`

> Report the current mode, running state and model count.

| Option | Description |
|---|---|
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-b, --baudrate INTEGER` | Override the bridge baudrate (default: firmware value, 921600) |

Reports `mode=<mode> state=<running\|stopped> models=<n>`. Reading status does
not change what the firmware is doing.

<a id="spam-stop"></a>
### `spam stop`

> Stop emitting.

| Option | Description |
|---|---|
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-b, --baudrate INTEGER` | Override the bridge baudrate (default: firmware value, 921600) |

```sh
catnip spam stop
```
