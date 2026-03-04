# VHCI Bridge

The VHCI bridge makes CatSniffer V3 appear as a standard Bluetooth LE controller
to the Linux Bluetooth stack (BlueZ). It creates a virtual HCI controller via
`/dev/vhci` that BlueZ registers as `hciN`, enabling any BLE tool that speaks
BlueZ to use the CatSniffer radio without modification.

## Requirements

### Hardware

- CatSniffer V3 (CC1352P7 + RP2040)
- Sniffle firmware flashed to the CC1352P7

### Software

- Linux with BlueZ 5.x
- Python 3.11 or later
- `pyserial` Python package
- Kernel module `hci_vhci` loaded (`/dev/vhci` must exist)
- Root access (`/dev/vhci` requires root)

### Load the kernel module

```
sudo modprobe hci_vhci
```

To load it automatically on boot:

```
echo hci_vhci | sudo tee /etc/modules-load.d/hci_vhci.conf
```

### Install the package

From the repository root:

```
pip install -e .
```

### Flash Sniffle firmware

If the CatSniffer does not already have Sniffle firmware:

```
catnip flash sniffle
```

---

## Usage

### Check prerequisites

```
catnip vhci check
```

This verifies that `hci_vhci` is loaded, `/dev/vhci` exists, and lists any
existing HCI controllers.

### Start the bridge

```
sudo catnip vhci start
```

Options:

| Flag | Description |
|------|-------------|
| `-d`, `--device` | CatSniffer device index when multiple are connected |
| `-p`, `--port` | Serial port path (auto-detected if omitted) |
| `-v`, `--verbose` | Enable verbose logging (shows all HCI opcodes and data packets) |

Examples:

```
sudo catnip vhci start
sudo catnip vhci start -d 1
sudo catnip vhci start -p /dev/ttyACM0
sudo catnip vhci start -p /dev/ttyACM0 -v
```

When the bridge starts successfully it prints a line such as:

```
Created hci1
```

The number indicates which HCI index BlueZ assigned. Use that index with all
tools below.

---

## Compatible Software

### bluetoothctl

Standard BlueZ interactive shell. Select the bridge controller by its BD_ADDR
(printed by `bluetoothctl` at startup as `[NEW] Controller`).

```
sudo bluetoothctl
[bluetoothctl]> select EE:FF:C0:EE:FF:C0
[bluetoothctl]> scan on
[bluetoothctl]> connect 34:85:18:00:35:F6
[NimBLE_GATT]> menu gatt
[NimBLE_GATT]> select-attribute 2a00
[NimBLE_GATT]> read
[NimBLE_GATT]> select-attribute /org/bluez/hci1/dev_34_85_18_00_35_F6/service000e/char000f
[NimBLE_GATT]> read
[NimBLE_GATT]> back
[bluetoothctl]> disconnect 34:85:18:00:35:F6
```

Notes:
- Use `list-attributes <device-address>` to see all discovered services and
  characteristics with their full D-Bus paths.
- Use `select-attribute <UUID>` as a shorthand instead of the full path.
- Use `write <hex bytes>` after selecting a writable characteristic.
- After GATT service resolution (`ServicesResolved: yes`) there is a 60-second
  idle window before the bridge watchdog terminates the connection.

### bettercap

BLE reconnaissance framework. Set the device index to the bridge HCI number
before enabling BLE:

```
sudo bettercap
192.168.x.x > ...  » set ble.device 1
192.168.x.x > ...  » ble.recon on
```

Wait for the target device to appear, then enumerate it:

```
BLE  » ble.recon off
BLE  » ble.enum 34:85:18:00:35:f6
```

Write to a characteristic (handle in hex, data in hex):

```
BLE  » ble.write 34:85:18:00:35:f6 0014 deadbeef
```

Do not use plain `ble.enum` without a MAC address; the syntax requires the
target address as an argument.

See the quirks section for known issues with `ble.recon` auto-reconnect.

### bleak (Python)

Async BLE library. Works reliably with the bridge for scanning, connecting,
and GATT reads and writes.

Minimal example:

```python
import asyncio
from bleak import BleakClient, BleakScanner

async def main():
    device = await BleakScanner.find_device_by_address(
        "34:85:18:00:35:F6", adapter="hci1"
    )
    async with BleakClient(device) as client:
        services = await client.get_services()
        for service in services:
            print(service)
        val = await client.read_gatt_char("00002a37-0000-1000-8000-00805f9b34fb")
        print(val.hex())

asyncio.run(main())
```

A full layered test script is provided at `tests/vhci/test_gatt.py`:

```
python tests/vhci/test_gatt.py 34:85:18:00:35:F6 hci1
```

### btmon

HCI packet monitor. Runs alongside the bridge to capture and decode all HCI
traffic between BlueZ and the bridge. Useful for debugging.

```
sudo btmon -i hci1
```

### gatttool and hcitool (optional, deprecated)

These tools were removed from `bluez-utils` in recent BlueZ versions. On Arch
Linux they are available from the AUR as `bluez-utils-compat`:

```
yay -S bluez-utils-compat
```

Once installed:

```
gatttool -i hci1 -b 34:85:18:00:35:F6 --char-read -a 0x0003
gatttool -i hci1 -b 34:85:18:00:35:F6 -I
hcitool -i hci1 lescan
```

---

## Architecture

The bridge is implemented in four files under `catnip/modules/vhci/`:

| File | Role |
|------|------|
| `bridge.py` | `VHCIBridge`: main loop, VHCI read/write, serial framing, connection state machine |
| `commands.py` | `HCICommandDispatcher`: handlers for 60+ HCI opcodes from BlueZ |
| `events.py` | HCI event builders (Connection Complete, Advertising Report, Disconnect, etc.) |
| `constants.py` | Sniffle state constants, HCI opcodes, BLE LL constants |

### Data flow

```
BlueZ (userspace tools)
        |
        | HCI_CMD packets (type 0x01)
        v
   /dev/vhci
        |
   VHCIBridge._handle_hci_command()
        |
   HCICommandDispatcher.dispatch()
        |
   Sniffle serial command (base64 encoded, UART 2 Mbaud)
        |
   CatSniffer CC1352P7 radio
        |  (RF)
   BLE peripheral device

Return path:
   BLE peripheral -> radio -> Sniffle serial message
        |
   VHCIBridge._handle_sniffle_packet()
        |
   HCI_ACL (type 0x02) or HCI_EVT (type 0x04)
        |
   /dev/vhci -> BlueZ -> userspace tool
```

### Serial framing

Sniffle commands and events are base64-encoded frames over UART at 2 Mbaud:

```
encoded = base64(bytes([b0]) + cmd_bytes) + b'\r\n'
b0 = ceil(len(cmd_bytes) / 3)
```

### LL control handling

Sniffle firmware in CENTRAL mode does not automatically respond to LL control
PDUs received from the peer. Without these responses the peer's ATT layer stalls
and GATT data does not flow. The bridge handles:

| Opcode | PDU | Response |
|--------|-----|----------|
| 0x08 | LL_FEATURE_REQ | LL_FEATURE_RSP (0x09) |
| 0x0C | LL_VERSION_IND | LL_VERSION_IND (BLE 5.0, company 0x005F) |
| 0x0E | LL_SLAVE_FEATURE_REQ | LL_FEATURE_RSP (0x09) |
| 0x14 | LL_LENGTH_REQ | LL_LENGTH_RSP (0x15), max parameters |
| 0x09 | LL_FEATURE_RSP | logged only |
| 0x02 | LL_TERMINATE_IND | connection teardown via state change |

### L2CAP fragmentation

BLE LL splits large L2CAP PDUs across multiple LL PDUs:

- LLID=2: first or complete fragment (carries L2CAP length + CID header), forwarded
  to BlueZ with HCI ACL PB flag 0x02.
- LLID=1: continuation fragment (raw payload, no header), forwarded with PB flag
  0x01. Without this the peer's ATT response is truncated at BlueZ and GATT
  discovery stalls.

---

## Known Quirks and Limitations

### No LE encryption

LL encryption (`LL_ENC_REQ` / `LL_ENC_RSP`) is not implemented. Characteristics
protected by pairing or bonding are not accessible. Devices that require encrypted
channels will disconnect or return ATT error 0x0F (Insufficient Encryption).

### event_ctr always 0

The Sniffle TRANSMIT command includes a connection event counter that tells the
firmware at which connection event to transmit. The bridge always sends 0. This
works in practice but may cause occasional LL retransmissions, visible as
additional empty PDUs (keepalive packets) in verbose log output.

### Default MTU is 23 with bleak

bleak uses the default ATT MTU (23 bytes) unless `_acquire_mtu()` is called
before GATT operations. The bridge and NimBLE_GATT support up to 256 bytes. This
is a bleak API usage concern rather than a bridge limitation.

### bettercap aggressive auto-reconnect

`ble.recon on` automatically connects to every device it discovers in order to
enumerate its GATT services, and repeats this on every scan cycle. This generates
a continuous stream of connection attempts. Use `ble.recon off` combined with
`ble.enum <MAC>` for controlled single-shot enumeration.

### bettercap connection timeout

bettercap imposes an internal connection timeout of approximately 5 seconds. If
the bridge establishes the connection after that deadline (visible in bettercap
as "connected to X but after the timeout"), bettercap does not send
`HCI_Disconnect`. The bridge detects this condition via a watchdog: connections
where BlueZ sends no ACL data within 10 seconds are force-disconnected and
scanning is restarted automatically.

### Supervision timeout

The LL supervision timeout derived from BlueZ's connection parameters is
typically 720 ms. The connection survives as long as the radio link is healthy.
Poor RF conditions, interference, or significant distance between the CatSniffer
and the target may cause frequent disconnections.

### Single connection only

The bridge tracks one active connection (`conn_handle = 0x0001`). Connecting to
a second device while already connected is not supported.

### Central role only tested

The bridge has partial peripheral code paths (advertising, state machine entries
for STATE_PERIPHERAL) but peripheral mode has not been validated end-to-end.

### No duplicate advertisement filtering

The bridge forwards every advertising packet received at the radio to BlueZ.
High-frequency advertisers (common with Apple and Samsung devices) generate
significant VHCI write volume and log noise. Sniffle firmware does not implement
duplicate filtering at the radio level.

### Scanning may not resume after certain disconnect sequences

The bridge auto-restarts scanning after disconnect when `scanning` is set to
True. In edge cases involving rapid consecutive connection attempts by BlueZ the
scan restart may be skipped. Issuing `scan off` then `scan on` in bluetoothctl,
or `ble.recon off` then `ble.recon on` in bettercap, always recovers the state.

---

## Validated Layers

| Layer | Description | Status |
|-------|-------------|--------|
| 1 | HCI initialisation, controller info, BlueZ registers hciN | PASS |
| 2 | LE scanning, advertising reports, device discovery | PASS |
| 3 | LE connection as central, Connection Complete, disconnect | PASS |
| 4 | GATT service discovery, characteristic reads, bleak test suite | PASS |
| 5 | Offensive tools (bettercap writes, fuzzing) | Not tested |

Test procedure and manual test script: `tests/vhci/README.md`

---

## Tested Configuration

| Component | Details |
|-----------|---------|
| Hardware | CatSniffer V3 (CC1352P7 + RP2040) |
| Firmware | Sniffle (nccgroup/Sniffle) |
| OS | Arch Linux, kernel 6.18 |
| BlueZ | 5.x |
| Python | 3.11+ |
| BLE target | NimBLE_GATT example (ESP32, ESP-IDF, NimBLE stack) |

---

## Troubleshooting

### /dev/vhci does not exist

```
sudo modprobe hci_vhci
```

### CatSniffer not responding

The device may be in bootloader mode. Check connected ports:

```
ls -la /dev/ttyACM*
```

Re-flash Sniffle firmware:

```
catnip flash sniffle
```

### BlueZ does not register hciN

The bridge prints `Created hciX` when registration succeeds. If this line does
not appear, confirm that `hci_vhci` is loaded and that the process has root
access.

### Connection drops immediately with no data packets

The target device was not advertising when the CONNECT_IND was sent, or missed
the connection window. Retry. If the problem is consistent, verify the target
is actively advertising at close range.

### GATT discovery stalls after MTU exchange

This was caused by L2CAP continuation fragments (LLID=1) being dropped. It is
fixed in the current bridge. If it recurs, check that the firmware has not been
downgraded.

### Scanning stops after a connection ends

Issue `scan off` then `scan on` in bluetoothctl, or `ble.recon off` then
`ble.recon on` in bettercap. The auto-restart covers most cases but not all
BlueZ state sequences.

### NimBLE disconnects immediately after a GATT read

The NimBLE_GATT example firmware has an application-level connection timer. If
the connection is held open without activity for the firmware's configured
timeout, NimBLE sends LL_TERMINATE_IND. This is normal NimBLE behaviour and not
a bridge defect.
