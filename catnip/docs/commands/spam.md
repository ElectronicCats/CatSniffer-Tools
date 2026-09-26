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
- [`pwr`](#spam-pwr) — switch the TX-power/interval profile (`high|bal|low`).
- [`int`](#spam-int) — override the advertising interval (0.625 ms units).
- [`stats`](#spam-stats) — on-demand resource telemetry (stack/heap/cycles).
- [`scan`](#spam-scan) — toggle the passive GAP coexistence scan (`on|off`).

> The `pwr`, `int`, `stats` and `scan` controls target the **hardened** firmware
> build. They surface the runtime knobs the firmware added over UART (power
> profile, advertising interval, telemetry and a passive coexistence scan) —
> again with no new offensive capability. `scan` is built into the default
> firmware image (no recompile needed); an older image flashed before it became
> standard reports a clear reflash hint and exits non-zero (see [`scan`](#spam-scan)).

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
| `-p, --power [high\|bal\|low]` | TX-power/interval profile to pin before emitting (hardened firmware) |
| `-i, --interval MIN MAX` | Advertising interval in 0.625 ms units (`32..16384`); see [`int`](#spam-int) |
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-b, --baudrate INTEGER` | Override the bridge baudrate (default: firmware value, 921600) |
| `-y, --yes` | Skip the authorised-use confirmation prompt (for scripting) |

```sh
catnip spam start                     # emit the full multi-vendor set
catnip spam start --mode apple        # only Apple payloads
catnip spam start -m apple -p low     # ... at the low-power profile
catnip spam start -m apple -i 40 60   # ... with a 25–37.5 ms interval
catnip spam start --mode apple -y     # skip the confirmation (scripting)
```

Before it begins, the command prints the authorised-use warning and asks for
confirmation; declining aborts and nothing is emitted. Pass `-y/--yes` to skip
the prompt in scripts.

`--power` / `--interval` are applied **before** emission starts, so the first
advert already uses the chosen profile. An out-of-range `--interval` is rejected
on the host, before the port is opened, so nothing is emitted.

The firmware is left emitting after this returns; run [`stop`](#spam-stop) to
halt it. Selecting a mode while a cycle is running restarts it with the new
mode.

<a id="spam-run"></a>
### `spam run`

> Start emitting and show a live view of the cycle (Ctrl+C to stop).

| Option | Description |
|---|---|
| `-m, --mode [all\|apple\|android\|windows\|samsung]` | Vendor advertising set to emit (default: `all`) |
| `-p, --power [high\|bal\|low]` | TX-power/interval profile to pin before emitting (hardened firmware) |
| `-i, --interval MIN MAX` | Advertising interval in 0.625 ms units (`32..16384`); see [`int`](#spam-int) |
| `-s, --scan [on\|off]` | Enable the passive-scan feed in the live view (built into the default firmware) |
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-b, --baudrate INTEGER` | Override the bridge baudrate (default: firmware value, 921600) |
| `-y, --yes` | Skip the authorised-use confirmation prompt (for scripting) |

```sh
catnip spam run --mode apple          # live panel while emitting Apple payloads
catnip spam run -m apple -p low        # ... at the low-power profile
catnip spam run --scan on              # ... with the passive-scan feed (see below)
```

Like [`start`](#spam-start), it prints the authorised-use warning and asks for
confirmation before emitting (skip with `-y/--yes`). Renders a fixed panel — active mode, elapsed time, the model being advertised
now, ads emitted and the last rotated address. On the hardened firmware the
panel also shows the active power profile, interval and stack/heap use (the
stack row turns red on a low-stack `WARN`).

`--scan on` adds a secondary table of the passive scan's reports (MAC / RSSI /
length) as they arrive. It's built into the default firmware; an older image
flashed before scan became standard surfaces the same reflash hint as
[`scan`](#spam-scan) and still halts the hardware on the way out.

Unlike [`start`](#spam-start), this is an interactive session: pressing
**Ctrl+C** (or the stream ending) always turns the scan off, stops the firmware
and closes the port, so the hardware is never left emitting or scanning.

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

<a id="spam-pwr"></a>
### `spam pwr`

> Select a TX-power/interval profile (`high|bal|low`). *(hardened firmware)*

| Argument / Option | Description |
|---|---|
| `PROFILE` | `high`, `bal` or `low` — the coupled TX-power/interval profile |
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-b, --baudrate INTEGER` | Override the bridge baudrate (default: firmware value, 921600) |

```sh
catnip spam pwr low     # drop to the low-power profile
```

Each profile pins both TX power and a coupled advertising interval; the exact
interval is echoed by [`status`](#spam-status) and [`stats`](#spam-stats).
Changing the profile does **not** begin new emission (so it needs no
authorised-use confirmation) and does **not** stop an active cycle.

<a id="spam-int"></a>
### `spam int`

> Override the advertising interval: `MIN MAX` in 0.625 ms units. *(hardened firmware)*

| Argument / Option | Description |
|---|---|
| `MIN MAX` | Interval bounds in 0.625 ms units, `MIN <= MAX` |
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-b, --baudrate INTEGER` | Override the bridge baudrate (default: firmware value, 921600) |

```sh
catnip spam int 40 60     # 25 ms .. 37.5 ms
```

**Units.** The interval is expressed in the firmware's raw **0.625 ms ticks**,
matching the BLE advertising-interval unit exactly (no host-side conversion, so
the value maps 1:1 to what the firmware validates and reports). The valid range
is `32..16384` ticks, i.e. **20 ms .. 10.24 s**, with `MIN <= MAX`:

| Ticks | Milliseconds |
|---|---|
| `32` (`0x20`) | 20 ms |
| `48` | 30 ms |
| `160` | 100 ms |
| `1600` | 1 s |
| `16384` (`0x4000`) | 10.24 s |

The range is checked **on the host before the port is opened**, so a bad
interval (out of range, or `MIN > MAX`) fails immediately with no traffic to the
device. On success the firmware's own reply is confirmed, so the command only
reports success once the interval was actually accepted. The profile's coupled
interval (see [`pwr`](#spam-pwr)) stays in effect until overridden this way.

<a id="spam-stats"></a>
### `spam stats`

> Report on-demand resource telemetry. *(hardened firmware)*

| Option | Description |
|---|---|
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-b, --baudrate INTEGER` | Override the bridge baudrate (default: firmware value, 921600) |

```sh
catnip spam stats
# cycles=1500 stack=812/1024 heap=12992/16384 pwr=low int=40-60
```

Prints one greppable line: advertising `cycles`, `stack` used/size, free/total
`heap`, and (when the firmware reports them) the active power profile and
interval. Reading telemetry does not stop an active cycle. On a firmware that
never answers, the command times out with an actionable error and a non-zero
exit code rather than hanging.

<a id="spam-scan"></a>
### `spam scan`

> Toggle the passive GAP coexistence scan (`on|off`). *(built into the default firmware)*

| Argument / Option | Description |
|---|---|
| `STATE` | `on` or `off` |
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `-b, --baudrate INTEGER` | Override the bridge baudrate (default: firmware value, 921600) |

```sh
catnip spam scan on      # start the passive coexistence scan
catnip spam scan off     # stop it
```

The scan is a **passive** GAP observer that only lists nearby advertisers
(MAC / RSSI / length) so you can gauge coexistence while spamming — it decodes
no payloads. Toggling it does not stop an active cycle.

**Built into the default firmware.** The scan ships in the default `ble_spam`
image (`SPAM_WITH_SCAN=1` is now the build default), so `catnip spam scan on`
works out of the box — no recompile or custom flags. The scan is **passive** and
**windowed** (50 ms window in a 100 ms interval), so the spam advertising always
keeps radio priority; the two coexist. Only an **older** image, flashed before
scan became standard, reports a clear error — *reflash the current `ble_spam`
firmware* — and exits non-zero, with no traceback unless `CATNIP_DEBUG=1`. The
host infers that from the firmware's reply at runtime, not by inspecting the
`.hex`. If you build your own image you can still opt out with
`SPAM_WITH_SCAN=0` (the historical advertise-only binary).

---

## Hardware verification checklist

The automated suite runs entirely against a mocked serial device. Use this
end-to-end pass on a physical CatSniffer v3 to confirm the full flow — flashing,
transport and each vendor mode — on real hardware. Only test against devices you
own or are authorised to spam.

**Setup**

- [ ] `catnip device list` shows the CatSniffer v3 (`1209:babb`) with a
      `bridge_port` (CDC0, e.g. `/dev/ttyACM0`).
- [ ] `catnip spam status` flashes `ble_spam` if absent, then reports
      `mode=… state=… models=…` (metadata-verified, `cc1352_fw_id=ble_spam_cc1352p_7`).

**Per-mode pass** — for each of `all`, `apple`, `android`, `windows`, `samsung`:

- [ ] `catnip spam start --mode <mode> -y` prints `Started BLE spam (mode=<mode>)`
      and `state=running`.
- [ ] `catnip spam status` reports the same mode with `state=running` and a
      plausible model count (`all=82`, `apple=22`, others as reported).
- [ ] `catnip spam stop` prints `Stopped BLE spam.` and a following
      `catnip spam status` shows `state=stopped`.

**Live view + safety**

- [ ] `catnip spam run --mode apple` (confirm the prompt, or `-y`) renders the
      live panel with the current model, ads emitted and the rotating address.
- [ ] Pressing **Ctrl+C** stops it; a subsequent `catnip spam status` shows
      `state=stopped` (R5 — the hardware is never left emitting).
- [ ] Declining the `start`/`run` confirmation aborts without emitting
      (`catnip spam status` still `state=stopped`).

**Hardened-firmware controls** — `pwr` / `int` / `stats` / `scan`. These need
the hardened `ble_spam` build; `scan` is part of the default image (see
[`scan`](#spam-scan)). Instrument each against real RF/telemetry:

- [ ] **`pwr`** (receiver, e.g. a phone's Bluetooth scanner or an SDR): `catnip
      spam pwr high|bal|low` visibly changes the received signal strength across
      profiles; `catnip spam status` echoes the matching `pwr=` and coupled `int=`.
- [ ] **`int`** (RF sniffer, e.g. a second CatSniffer running `sniff`): `catnip
      spam int 40 60` changes the measured advertising interval to ~25–37.5 ms;
      `catnip spam int 10 20` is rejected on the host (`out of range`) with no RF
      change, and `catnip spam int 60 40` likewise (`MIN > MAX`).
- [ ] **`stats`** (telemetry over UART): `catnip spam stats` prints a plausible
      `cycles=… stack=u/n heap=free/total` line, with `stack`/`heap` moving as a
      cycle runs; a low-stack condition shows the `WARN` row red in `run`.
- [ ] **`scan`** (a third BLE emitter nearby): on the default firmware,
      `catnip spam scan on` then `catnip spam run --scan on` lists the third
      emitter (MAC / RSSI / length) in the live feed; `scan off` stops it, and a
      `run --scan on` interrupted with **Ctrl+C** leaves scan **and** spam off.
      Spam keeps radiating throughout (passive/windowed scan, spam priority).
- [ ] **Legacy image** (an older build flashed with `SPAM_WITH_SCAN=0`): `catnip
      spam scan on` reports the reflash hint and exits non-zero without hanging or
      a traceback (traceback only under `CATNIP_DEBUG=1`).

> Firmware side: the UART controls these commands drive are specified and
> validated in the firmware plan
> [`plan-ble-spam-mejoras.md`](../../../../CatSniffer-Firmware/docs/plan-ble-spam-mejoras.md).
