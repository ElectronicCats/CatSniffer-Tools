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

```sh
catnip spam start                 # emit the full multi-vendor set
catnip spam start --mode apple    # only Apple payloads
```

The firmware is left emitting after this returns; run [`stop`](#spam-stop) to
halt it. Selecting a mode while a cycle is running restarts it with the new
mode.

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
