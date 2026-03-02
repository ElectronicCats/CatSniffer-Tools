# CatSniffer VHCI Bridge

A virtual HCI bridge that exposes CatSniffer hardware as a BLE central device with direct GATT operations via Unix socket.

## What Actually Works

### Primary Interface: Unix Socket (`/tmp/catsniffer.sock`)

This is the **main way to use the bridge**. Commands are sent as JSON:

| Command | Status | Description |
|---------|--------|-------------|
| `scan [timeout]` | Working | Scan for BLE devices |
| `connect <addr> [type]` | Working | Connect to peripheral |
| `disconnect` | Working | Terminate connection |
| `status` | Working | Get connection status |
| `mtu [size]` | Working | Exchange MTU |
| `services` | Working | Discover primary services |
| `characteristics` | Working | Discover characteristics |
| `read <handle>` | Working | Read characteristic |
| `write <handle> <hex>` | Working | Write to characteristic |
| `advertise [0\|1]` | Partial | Basic advertising |

### HCI Interface (`/dev/vhci`): Limited

The bridge creates a virtual `hciX` device, but **most HCI commands are stubbed**:

**Implemented (does real work):**
- `LE Set Scan Enable` - triggers firmware scan
- `LE Set Advertise Enable` - triggers firmware advertising
- `LE Set Random Address` - sets address on firmware
- `Reset` - resets firmware

**Stubbed (returns fake success):**
- `Read BD_ADDR` - returns hardcoded address
- `Read Local Name` - returns "CatSniffer"
- `Read Buffer Size` - returns hardcoded values
- `Read LE Supported States` - returns zeros
- Most other commands - just return success without action

**Not Implemented:**
- `LE Create Connection` via HCI
- `LE Connection Update`
- `Encrypt/Pairing` commands
- Most vendor-specific commands

**Result:** Tools like `hciconfig -a` will show the device, but `gatttool`, `bluetoothctl` connections will **not** work through the HCI interface. Use the socket interface instead.

---

## Requirements

- CatSniffer hardware with Sniffle-compatible firmware
- Linux kernel with VHCI support (`/dev/vhci`)
- Root privileges (for VHCI access)
- Python 3 with `pyserial`, `rich`

```bash
sudo apt install python3-serial
pip install rich
```

## Quick Start

```bash
# Terminal 1: Start bridge
sudo python3 vhci_bridge.py -p /dev/ttyACM0

# Terminal 2: Use socket interface
python3 << 'EOF'
import socket, json, time

s = socket.socket(socket.AF_UNIX)
s.connect('/tmp/catsniffer.sock')
s.settimeout(30)

def cmd(c, wait=1):
    s.send((c + '\n').encode())
    time.sleep(wait)
    return json.loads(s.recv(8192))

# Scan
print(cmd('scan 5'))

# Connect
print(cmd('connect AA:BB:CC:DD:EE:FF 0', 3))

# Wait for connection
for _ in range(10):
    if cmd('status', 0.5).get('connected'):
        break

# Discover
print(cmd('services', 5))
print(cmd('characteristics', 5))

# Read/write
print(cmd('read 0x0012', 2))
print(cmd('write 0x0012 deadbeef', 2))

# Disconnect
print(cmd('disconnect', 2))
s.close()
EOF
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   User Space                         │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │    Unix Socket (/tmp/catsniffer.sock)       │    │
│  │    JSON commands: connect, scan, read...    │    │
│  └──────────────────┬──────────────────────────┘    │
│                     │                                │
│  ┌──────────────────▼──────────────────────────┐    │
│  │         vhci_bridge.py                       │    │
│  │  ┌─────────────────────────────────────────┐│    │
│  │  │  GATTClient                             ││    │
│  │  │  • connect() → Sniffle CONNECT_IND      ││    │
│  │  │  • services() → ATT Read By Group       ││    │
│  │  │  • read() → ATT Read Request            ││    │
│  │  │  • write() → ATT Write Request          ││    │
│  │  └─────────────────────────────────────────┘│    │
│  │  ┌─────────────────────────────────────────┐│    │
│  │  │  Sniffle Protocol                       ││    │
│  │  │  • Base64 encoded commands              ││    │
│  │  │  • Packet/State message parsing         ││    │
│  │  └─────────────────────────────────────────┘│    │
│  └──────────────────┬──────────────────────────┘    │
│                     │ Serial                         │
└─────────────────────┼────────────────────────────────┘
                      │ /dev/ttyACM0
              ┌───────▼───────┐
              │  CatSniffer   │
              │   Hardware    │
              └───────────────┘

VHCI Interface (/dev/vhci):
  ┌──────────────────┐
  │ hciX (virtual)   │  ← Limited support
  │ • hciconfig -a   │    (mostly stubbed)
  │ • scan enable    │
  └──────────────────┘
```

---

## Socket Command Reference

### `help`
Returns list of commands.

```json
{"commands": ["connect", "disconnect", "scan", "mtu", "services", "characteristics", "read", "write", "advertise", "status"]}
```

### `scan [timeout]`
Scan for BLE devices. Default timeout: 5 seconds.

```bash
scan 10
```

Response:
```json
{
  "devices": ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"],
  "count": 2,
  "details": {
    "AA:BB:CC:DD:EE:FF": {"rssi": -45, "addr_type": 0},
    "11:22:33:44:55:66": {"rssi": -67, "addr_type": 1}
  }
}
```

### `connect <addr> [addr_type]`
Connect to a BLE peripheral.

- `addr`: MAC address in `AA:BB:CC:DD:EE:FF` format
- `addr_type`: `0` = public (default), `1` = random

```bash
connect 34:85:18:00:35:F6 0
```

Response:
```json
{"status": "connecting", "address": "34:85:18:00:35:F6", "addr_type": 0}
```

**Note:** Connection is asynchronous. Poll `status` to confirm.

### `disconnect`
Terminate current connection.

```json
{"status": "disconnecting"}
```

### `status`
Get current state.

```json
{
  "connected": true,
  "address": "34:85:18:00:35:F6",
  "mtu": 100,
  "advertising": false
}
```

### `mtu [size]`
Exchange MTU. Default: 517.

```json
{"mtu": 100}
```

### `services`
Discover all primary services.

```json
{
  "services": [
    {"start": 4096, "end": 4105, "uuid": "180d"},
    {"start": 4096, "end": 4110, "uuid": "1800"}
  ]
}
```

### `characteristics [start] [end]`
Discover characteristics in handle range.

```bash
characteristics 0x0001 0xFFFF
```

```json
{
  "characteristics": [
    {"handle": 4097, "properties": 16, "value_handle": 4098, "uuid": "2a37"}
  ]
}
```

**Properties flags:**
- `0x01` BROADCAST
- `0x02` READ
- `0x04` WRITE_NO_RESP
- `0x08` WRITE
- `0x10` NOTIFY
- `0x20` INDICATE

### `read <handle>`
Read characteristic value.

```bash
read 0x0012
```

```json
{"value": "011e00"}
```

Error response:
```json
{"error": "ATT error 0x0E"}
```

### `write <handle> <hex_data>`
Write to characteristic.

```bash
write 0x0012 0100
```

```json
{"status": "ok"}
```

### `advertise [0|1]`
Start/stop advertising (basic).

```bash
advertise 1
```

```json
{"status": "advertising", "address": "c0ffee00c0ffee"}
```

---

## What's NOT Supported

| Feature | Status | Notes |
|---------|--------|-------|
| Encryption/Pairing | Not implemented | No Security Manager |
| Bonding | Not implemented | Requires encryption |
| Multiple connections | Not implemented | Single connection only |
| Extended advertising | Not implemented | Legacy only |
| 2M/Coded PHY | Not implemented | 1M only |
| Connection via HCI | Not implemented | Use socket interface |
| gatttool | Not working | HCI LE Create Conn not impl |
| bluetoothctl connect | Not working | HCI LE Create Conn not impl |

---

## Testing

### Basic Test

```bash
# Start bridge
sudo python3 vhci_bridge.py -p /dev/ttyACM0 -v

# In another terminal
python3 << 'EOF'
import socket, json, time

s = socket.socket(socket.AF_UNIX)
s.connect('/tmp/catsniffer.sock')
s.settimeout(30)

def cmd(c, wait=1):
    s.send((c + '\n').encode())
    time.sleep(wait)
    try:
        return json.loads(s.recv(8192))
    except:
        return {}

# 1. Scan
print("=== Scanning ===")
result = cmd('scan 5', 6)
print(json.dumps(result, indent=2))

# 2. Connect to first device
if result.get('devices'):
    addr = result['devices'][0]
    print(f"\n=== Connecting to {addr} ===")
    cmd(f'connect {addr} 0', 3)

    for _ in range(10):
        st = cmd('status', 0.5)
        if st.get('connected'):
            print(f"Connected! MTU={st.get('mtu')}")
            break

    # 3. Enumerate
    print("\n=== Services ===")
    print(json.dumps(cmd('services', 5), indent=2))

    print("\n=== Characteristics ===")
    print(json.dumps(cmd('characteristics', 5), indent=2))

    # 4. Disconnect
    cmd('disconnect', 2)

s.close()
EOF
```

### HCI Interface Test (Limited)

```bash
# After starting bridge, check if hci device appears
hciconfig -a

# This works - shows device info
# hcitool -i hci1 lescan  <- will NOT work (HCI scan is stubbed)
# Use socket 'scan' command instead
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Need root" warning | Run with `sudo` |
| Device not in scan | Check firmware, serial port, baud rate |
| Connection fails | Device may not be connectable, try addr_type 1 |
| Read/Write timeout | Increase wait time, check MTU |
| "VHCI response: empty" | `sudo modprobe vhci` |
| gatttool not working | Expected - use socket interface |

### Debug Mode

```bash
sudo python3 vhci_bridge.py -p /dev/ttyACM0 -v
```

---

## Sniffle Commands Used

The bridge translates operations to Sniffle firmware commands:

| Sniffle Opcode | Command |
|----------------|---------|
| `0x10` | Set channel |
| `0x11` | Pause/resume |
| `0x13` | MAC filter |
| `0x15` | Set follow mode |
| `0x16` | Aux adv handling |
| `0x17` | Reset |
| `0x19` | Tx packet |
| `0x1A` | Connect |
| `0x1B` | Set identity address |
| `0x1C` | Set adv data |
| `0x22` | Start scan |
| `0x27` | Set TX power |

---

## Future Work

To make standard tools work via HCI:

- [ ] Implement `LE Create Connection` (0x200D)
- [ ] Implement `LE Connection Update` (0x2013)
- [ ] Implement `LE Start Encryption` (0x2017)
- [ ] Implement ACL data path for GATT
- [ ] Add Security Manager for pairing

---

## References

- [Sniffle Firmware](https://github.com/nccgroup/sniffle)
- [Bluetooth Core Specification](https://www.bluetooth.com/specifications/bluetooth-core-specification/)
- [Linux VHCI](https://www.kernel.org/doc/html/latest/bluetooth/hci.html)
