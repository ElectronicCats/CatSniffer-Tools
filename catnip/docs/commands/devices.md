# `catnip devices`

> List connected CatSniffer devices

The discovery command, and the first thing to run on a new machine or after
plugging a board in. Every other command that touches hardware picks its target
from this same list, so if a board does not appear here, nothing else will find
it either.

`identify` is documented here too: it answers the other half of the discovery
question — *which physical board is `#2`?*

## Quick Start

```sh
# 1. See what is connected and which ports each board claims
catnip devices

# 2. With several boards plugged in, blink one to tell them apart
catnip identify --device 2

# 3. Ask that board what firmware it is running
catnip status --device 2
```

---

## Port architecture

Each CatSniffer exposes **three** serial ports, and they are not
interchangeable:

| Port | Chip | What runs over it |
|---|---|---|
| **Cat-Bridge** | CC1352 | Firmware flashing and the packet stream for BLE / Zigbee / Thread sniffing |
| **Cat-LoRa** | SX1262 | LoRa and FSK capture, radio parameter configuration |
| **Cat-Shell** | host MCU (SAMD21 or RP2040) | Interactive command shell: board identity, firmware version, bootloader entry |

The operating system assigns the port numbers, in enumeration order — they are
**not stable across reboots or replugs**. Address a board by its catnip ID
(`--device 1`), never by hard-coding `/dev/ttyACM3` into a script.

Cat-Shell is the port that answers the `Board:` question, which is why a board
whose shell port is missing falls back to `unknown` in the `Board` column and
why [`flash`](flash.md) and [`restore`](restore.md) grow a `--board v2|v3`
override for exactly that case.

---

## Subcommands

### `devices`

> List connected CatSniffer devices

| Option | Description |
|---|---|
| `--debug` | Show raw USB port info for each interface (useful for diagnosing Windows port mapping). |

```sh
catnip devices
```

The table has one row per board and one column per port, plus the detected
generation:

<!-- TODO: paste a real run with hardware attached. The 5-column table
     (Device / Board / Cat-Bridge / Cat-LoRa / Cat-Shell) cannot be captured
     without a CatSniffer connected. See the progress log in
     plan-implementacion-documentacion.md. -->

With nothing plugged in it warns and **exits 0** — an empty list is not an
error:

```
⚠ No CatSniffer devices found.
```

`--debug` adds a second table straight from pyserial: port, description, HWID,
location, interface and serial number, for every USB interface matching the
CatSniffer VID/PID. Use it when the three ports come up in an unexpected order
or one is missing:

```sh
catnip devices --debug
```

```
⚠ No CatSniffer devices found.
No CatSniffer USB interfaces visible to pyserial.
```

> [!Note]
> `--debug` is most useful on Windows, where COM port numbering does not follow
> the interface order the way `/dev/ttyACM*` does.

---

### `identify`

> Send identification command to CatSniffer device

| Option | Description |
|---|---|
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |

Sends `identify` over the **Cat-Shell** port; the board signals back so you can
tell which physical unit holds a given ID.

```sh
catnip identify --device 1
```

With no board connected it fails cleanly and **exits 1**:

```
✗ No CatSniffer device found!
  Make sure your CatSniffer is connected.
```

---

### Notes

- **`devices` exits 0 when it finds nothing; `identify` and `status` exit 1.**
  Listing nothing is a valid result; being asked to talk to a board that is not
  there is not.
- `identify` needs the Cat-Shell port. If that port was not detected it stops
  with `Shell port not available for this device!` rather than trying another
  port.
- A serial monitor left open on Cat-Shell will block `identify`. The error names
  this as the first thing to check.
- **In a multi-device setup, pass `--device <ID>` to every command.** Without it
  each command picks the first board it finds, which is whichever one the OS
  enumerated first.

---

## See also

- [`status`](status.md) — what firmware and capabilities the board actually reports.
- [`verify`](verify.md) — goes further: exercises the shell and the LoRa radio.
- [`setup-env`](setup-env.md) — run this first on Linux if no device shows up at all.
- Board generations and firmware lines: [Firmware](../firmware.md).
