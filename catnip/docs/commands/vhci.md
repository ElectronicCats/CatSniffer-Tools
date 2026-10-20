# `catnip vhci`

> VHCI Bridge - Expose CatSniffer as hciX.

Everything else in catnip captures traffic. This one makes the CatSniffer act
as a **standard Bluetooth LE controller**: the bridge creates a virtual HCI
controller through `/dev/vhci`, BlueZ registers it as `hciN`, and from then on
any BlueZ tool — `bluetoothctl`, `btmon`, `bettercap`, `bleak` — drives the
CatSniffer radio with no changes of its own.

**Linux only.** The group is not registered on macOS or Windows.

## Quick Start

```sh
# 1. Load the kernel module the bridge needs
sudo modprobe hci_vhci

# 2. Check that everything is in place before starting
catnip vhci check

# 3. Start the bridge (needs root) — it prints the hciN it created
sudo catnip vhci start

# 4. In another terminal, use it like any BlueZ controller
hciconfig -a
```

---

## Requirements

| Requirement | Why |
|---|---|
| **CatSniffer v3** (CC1352P7 + RP2040) | The bridge is only validated on v3. |
| **Sniffle firmware** on the CC1352 | `catnip flash sniffle` |
| Linux with **BlueZ 5.x** | The stack that registers `hciN`. |
| **`hci_vhci` kernel module** loaded | Provides `/dev/vhci`. |
| **Root** | `/dev/vhci` requires it. |
| `pyserial` | Bundled with the package. |

Load the module persistently with:

```sh
echo hci_vhci | sudo tee /etc/modules-load.d/hci_vhci.conf
```

[`setup-env`](setup-env.md) installs the udev rule that grants group access to
`/dev/vhci`, which is what makes `vhci check` report `permissions: OK`.

---

## Subcommands

### `vhci check`

> Check VHCI bridge prerequisites (kernel module, /dev/vhci, root, packages).

Run this first. It checks every prerequisite independently and reports each one,
so a failure names what is missing rather than failing at start time:

```sh
catnip vhci check
```

```
✓   permissions  : OK (access to /dev/vhci)
✓   hci_vhci     : loaded
✓   /dev/vhci    : exists
✓   bluetoothctl : found
✓   btmon        : found
✓   bleak        : installed
⚠   CatSniffer   : no device detected

⚠ Some prerequisites are missing. See above.
```

### `vhci start`

> Start the VHCI bridge — CatSniffer appears as hciX.

| Option | Description |
|---|---|
| `-d, --device INTEGER` | Device ID (for multiple CatSniffers) |
| `--baud INTEGER` | Baud rate for serial port `[default: 2000000]` |
| `-v, --verbose` | Enable verbose (DEBUG) logging |

```sh
sudo modprobe hci_vhci
sudo catnip vhci start
hciconfig -a
```

On success it prints the index BlueZ assigned:

```
Created hci1
```

**That number is what every tool below needs** — `--adapter hci1`,
`set ble.device 1`, and so on.

`-v` logs every HCI opcode and data packet. It is the first thing to reach for
when a connection behaves oddly.

---

## Compatible tools

`bluetoothctl`, `btmgmt`, `btmon`, `bleak` and `bettercap`.

```sh
# BlueZ interactive shell — select the bridge by its BD_ADDR
sudo bluetoothctl
```

```python
# bleak, pinned to the bridge adapter
device = await BleakScanner.find_device_by_address(ADDR, adapter="hci1")
```

For worked examples with each tool — `bluetoothctl` GATT navigation,
`bettercap` recon and writes, `btmon` tracing — see the implementation notes in
[`modules/protocols/vhci/README.md`](../../modules/protocols/vhci/README.md).

---

### Notes

> [!Important]
> **No LE encryption.** `LL_ENC_REQ` / `LL_ENC_RSP` are not implemented, so
> characteristics behind pairing or bonding are unreachable. A device that
> requires an encrypted channel will disconnect or return ATT error `0x0F`
> (Insufficient Encryption).

- **One connection at a time.** The bridge tracks a single handle
  (`0x0001`); connecting to a second device while connected is not supported.
- **Central role only.** Peripheral code paths exist but are not validated
  end-to-end.
- No duplicate advertisement filtering — expect repeats during scanning.
- Scanning does not always resume after certain disconnect sequences; restart
  the bridge if discovery goes quiet after a connection ends.
- Validated through GATT service discovery and characteristic reads (the bleak
  test suite). Offensive tooling on top of the bridge is **not** tested.
- Tested on Arch Linux with kernel 6.18, BlueZ 5.x, Python 3.11+, against an
  ESP32/NimBLE target.

---

## See also

- [`setup-env`](setup-env.md) — installs the udev rule for `/dev/vhci`.
- [`flash`](flash.md) — `catnip flash sniffle` puts the required firmware on the CC1352.
- [`sniff ble`](sniff.md#sniff-ble) — passive BLE capture, the other way to use the same firmware.
- Implementation notes, data flow, serial framing and per-symptom troubleshooting:
  [`modules/protocols/vhci/README.md`](../../modules/protocols/vhci/README.md).
