# CatSniffer Firmware (RP2040/Zephyr)

Multi-protocol wireless sniffer and LoRa communication device based on RP2040, CC1352, and SX1262 radios.

[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](VERSION)
[![Zephyr](https://img.shields.io/badge/Zephyr-4.1.99-green.svg)](https://zephyrproject.org/)
[![Platform](https://img.shields.io/badge/platform-RP2040-red.svg)](https://www.raspberrypi.com/products/rp2040/)

## Table of Contents

- [Features](#features)
- [Hardware](#hardware)
- [To-Do](#to-do)
- [Quick Start](#quick-start)
- [USB Endpoints](#usb-endpoints)
- [Command Reference](#command-reference)
- [Usage Examples](#usage-examples)
- [Building from Source](#building-from-source)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

---

## Features

### Dual Radio Support
- **CC1352 (TI)**: Zigbee, Thread, BLE, 2.4GHz/Sub-GHz protocols
- **SX1262 (Semtech)**: LoRa long-range communication

### Triple USB CDC-ACM Endpoints
- **Cat-Bridge**: Transparent UART bridge to CC1352
- **Cat-LoRa**: Dual-mode LoRa interface (stream/command)
- **Cat-Shell**: Unified configuration shell

### LoRa Capabilities
- **Dual-mode operation**:
  - **Stream mode**: Raw binary TX/RX for programmatic access
  - **Command mode**: Text-based interface for debugging
- **Runtime configuration**: No recompilation needed
  - Frequency: 137-1020 MHz
  - Spreading factor: SF7-SF12
  - Bandwidth: 125/250/500 kHz
  - Coding rate: 4/5, 4/6, 4/7, 4/8
  - TX power: -9 to 22 dBm
- **Visual mode indicators**: LED blink rate changes with mode

### System Features
- RF band switching (2.4GHz / Sub-GHz / LoRa)
- CC1352 bootloader mode support
- Concurrent radio operation
- USB bootloader for easy firmware updates

---

## Hardware

### RP2040 Microcontroller
- **Dual ARM Cortex-M0+ cores @ 133 MHz**
- **264 KB RAM**
- **USB Device support**

### CC1352P Radio (Texas Instruments)
- **Protocols**: Zigbee, Thread, BLE 5.2, IEEE 802.15.4
- **Frequencies**: 2.4 GHz + Sub-GHz (863-928 MHz)
- **Interface**: UART @ 921600 baud (passthrough), 500000 baud (bootloader)
- **Control Pins**: GPIO2 (boot), GPIO3 (reset)

### SX1262 LoRa Radio (Semtech)
- **Frequency Range**: 150-960 MHz
- **LoRa Modulation**: SF5-SF12
- **Interface**: SPI @ 1 MHz
- **Control Pins**: GPIO24 (reset), GPIO4 (busy), GPIO5 (DIO1)

### RF Switching
- **Automatic band selection** via GPIO-controlled RF switch
- **3 paths**: 2.4GHz, Sub-GHz, LoRa

---

## TO-DO

- **LoRa Stream only**: Configure the Board to just transmit as fast as possible since going from RX to TX is taking a 5mS delay.
- **Access to modify Preamble**: for meshtastic we use an specific preamble, this cannot be modified on runtime.
- **Access to FSK on SX1262**: Right now we are using the Zephyr original driver, this limits us to the use of different modulations, but the capabilities are there.
- **Check Firmware ID**: Add a register on shell termianl, of the latest firmware flashed to the CC1352.
- **Add identification command**: Command to identify different boards on a PC, blink LEDs in a beauty way.
- **Add support to save CC1352 images**: Save CC1352 different firmwares on the sam flash memmory.
- **Add automated testings with 2 boards**: Fully automate testings adding the CC1352 programming
- **Add CC1352 serial programmer**: Add the programing functionallity to reprogram the CC1352 on-the-go

## Quick Start

### Prerequisites

1. **Zephyr SDK** (0.17.0 or later)
2. **Python 3.10+** with virtual environment
3. **Build tools**: CMake, Ninja, GCC ARM

### Setup Environment

```bash
# Activate Zephyr environment
source ~/zephyrproject/.venv/bin/activate
export ZEPHYR_BASE=$HOME/zephyrproject/zephyr

# Install dependencies
pip install pyusb pyserial
```

### Build and Flash

```bash
# Build, flash, and verify
./scripts/catsniffer_build_flash_test.sh

# Or build only
west build -b rpi_pico

# Flash to device
picotool load build/zephyr/zephyr.uf2
```

### Connect

The device enumerates as 3 serial ports:

```bash
# macOS
/dev/cu.usbmodem21X1  # Cat-Bridge (CC1352)
/dev/cu.usbmodem21X3  # Cat-LoRa (SX1262)
/dev/cu.usbmodem21X5  # Cat-Shell (Config)

# Linux
/dev/ttyACM0  # Cat-Bridge
/dev/ttyACM1  # Cat-LoRa
/dev/ttyACM2  # Cat-Shell
```

---

## USB Endpoints

### CDC0: Cat-Bridge (CC1352 Passthrough)

**Purpose**: Direct UART access to CC1352 radio

**Baud Rates**:
- Passthrough: 921600 baud
- Bootloader: 500000 baud

**Use Cases**:
- Wireless protocol sniffing (Zigbee, Thread, BLE)
- CC1352 firmware updates
- Integration with tools like Wireshark, TI Flash Programmer

**Example** (Python):
```python
import serial

# Open CC1352 bridge
bridge = serial.Serial('/dev/cu.usbmodem2101', 921600)

# Send/receive raw protocol data
bridge.write(b'\x00\x01\x02...')  # Transparent passthrough
data = bridge.read(100)
```

---

### CDC1: Cat-LoRa (Dual-Mode Interface)

#### Stream Mode (Default)

**Purpose**: Raw binary LoRa transceiver for automated applications

**TX Format**: Raw bytes (max 255 bytes)
```python
lora.write(b'HELLO WORLD')  # Sends as LoRa packet
```

**RX Format**: `[length:1][payload:N][rssi_offset:1][snr_offset:1]`
```python
length = ord(lora.read(1))
payload = lora.read(length)
rssi = ord(lora.read(1)) - 128  # Offset removed
snr = ord(lora.read(1)) - 128
```

**Example** (Python):
```python
import serial

lora = serial.Serial('/dev/cu.usbmodem2103', 115200)

# Transmit
lora.write(b'Hello LoRa!')

# Receive
while True:
    if lora.in_waiting:
        length = ord(lora.read(1))
        payload = lora.read(length)
        rssi = ord(lora.read(1)) - 128
        snr = ord(lora.read(1)) - 128
        print(f"RX: {payload.hex()} | RSSI: {rssi} dBm | SNR: {snr} dB")
```

#### Command Mode (Optional)

**Purpose**: Text-based interface for debugging and testing

**Commands**:
- `TEST` - Initialize LoRa and check status
- `TXTEST` - Send test packet "PING"
- `TX <hex>` - Send hex-encoded packet

**RX Format**: `RX: <hex> | RSSI: -45 | SNR: 8\r\n`

**Example** (Terminal):
```bash
# Switch to command mode first (on Cat-Shell)
$ screen /dev/cu.usbmodem2105
> lora_mode command

# Use LoRa port
$ screen /dev/cu.usbmodem2103
> TEST
LoRa: Starting initialization...
LoRa: Initialization completed!

> TX 48656C6C6F
TX Result: 0 (Success)

> TXTEST
TX Result: 0 (Success)
```

**Mode Switching**:
```bash
# On Cat-Shell (CDC2)
> lora_mode stream   # Switch to binary mode
> lora_mode command  # Switch to text mode
```

---

### CDC2: Cat-Shell (Configuration Shell)

**Purpose**: System configuration and control

**Baud Rate**: 115200

#### System Commands

| Command | Description | Example |
|---------|-------------|---------|
| `help` | List all commands | `help` |
| `status` | Show device status | `status` |
| `boot` | Enter CC1352 bootloader | `boot` |
| `exit` | Return to passthrough | `exit` |
| `band1` | Switch to 2.4GHz band | `band1` |
| `band2` | Switch to Sub-GHz band | `band2` |
| `band3` | Switch to LoRa band | `band3` |
| `reboot` | Enter RP2040 USB bootloader | `reboot` |

#### LoRa Configuration Commands

| Command | Parameters | Description | Example |
|---------|-----------|-------------|---------|
| `lora_freq` | `<Hz>` | Set frequency (137-1020 MHz) | `lora_freq 868000000` |
| `lora_sf` | `<7-12>` | Set spreading factor | `lora_sf 10` |
| `lora_bw` | `<125\|250\|500>` | Set bandwidth (kHz) | `lora_bw 250` |
| `lora_cr` | `<5\|6\|7\|8>` | Set coding rate (4/5, 4/6, 4/7, 4/8) | `lora_cr 7` |
| `lora_power` | `<-9 to 22>` | Set TX power (dBm) | `lora_power 14` |
| `lora_mode` | `<stream\|command>` | Switch LoRa interface mode | `lora_mode stream` |
| `lora_config` | - | Display current configuration | `lora_config` |
| `lora_apply` | - | Apply pending changes | `lora_apply` |

---

## Command Reference

### Example Shell Session

```bash
$ screen /dev/cu.usbmodem2105 115200

> help
Commands:
  help     - Show available commands
  boot     - CC1352 bootloader mode
  exit     - Return to passthrough
  band1    - 2.4GHz band
  band2    - SUB-GHz band
  band3    - LoRa band
  reboot   - RP2040 USB bootloader
  status   - Device status
  lora_freq - Set frequency (Hz)
  lora_sf  - Set spreading factor
  lora_bw  - Set bandwidth (kHz)
  lora_cr  - Set coding rate
  lora_power - Set TX power (dBm)
  lora_mode - stream|command mode
  lora_config - Show LoRa config
  lora_apply - Apply pending config

> status
Mode: 0, Band: 0, LoRa: initialized, LoRa Mode: Stream

> lora_config
LoRa Configuration:
  Frequency: 915000000 Hz
  Spreading Factor: SF7
  Bandwidth: 125 kHz
  Coding Rate: 4/5
  TX Power: 20 dBm
  Preamble Length: 12
  Mode: Stream

> lora_freq 868000000
Frequency set to 868000000 Hz (pending)

> lora_sf 10
Spreading Factor set to SF10 (pending)

> lora_apply
Applying LoRa configuration...
LoRa configuration applied successfully

> lora_config
LoRa Configuration:
  Frequency: 868000000 Hz
  Spreading Factor: SF10
  Bandwidth: 125 kHz
  Coding Rate: 4/5
  TX Power: 20 dBm
  Preamble Length: 12
  Mode: Stream
```

---

## Usage Examples

### Example 1: Zigbee Sniffer with Wireshark

```bash
# Connect to CC1352 bridge
cat /dev/cu.usbmodem2101 | wireshark -k -i -
```

### Example 2: LoRa Point-to-Point Communication

**Device 1** (Transmitter):
```python
import serial
import time

lora = serial.Serial('/dev/cu.usbmodem2103', 115200)

while True:
    message = b"Hello from Device 1"
    lora.write(message)
    print(f"Sent: {message}")
    time.sleep(2)
```

**Device 2** (Receiver):
```python
import serial

lora = serial.Serial('/dev/cu.usbmodem2103', 115200)

while True:
    if lora.in_waiting:
        length = ord(lora.read(1))
        payload = lora.read(length)
        rssi = ord(lora.read(1)) - 128
        snr = ord(lora.read(1)) - 128
        print(f"Received: {payload.decode()} | RSSI: {rssi} dBm | SNR: {snr} dB")
```

### Example 3: EU LoRa Configuration

```bash
# Configure for EU868 frequency
> lora_freq 868100000
> lora_sf 12
> lora_bw 125
> lora_cr 5
> lora_power 14
> lora_apply
LoRa configuration applied successfully
```

### Example 4: Concurrent CC1352 + LoRa Operation

**Terminal 1** (CC1352 sniffing):
```bash
screen /dev/cu.usbmodem2101 921600
# Sniffing Zigbee traffic
```

**Terminal 2** (LoRa communication):
```python
import serial
lora = serial.Serial('/dev/cu.usbmodem2103', 115200)
lora.write(b'Status update')
```

Both radios work independently without interference!

---

## Building from Source

### Directory Structure

```
catsniffer/
├── boards/           # Device tree overlays
│   └── rpi_pico.overlay
├── include/          # Header files
│   ├── catsniffer.h
│   ├── catsniffer_usbd.h
│   └── shell_commands.h
├── src/              # Source files
│   ├── main.c
│   ├── shell_commands.c
│   └── USB/
│       └── usbd_init.c
├── scripts/          # Build and verification scripts
│   ├── catsniffer_build_flash_test.sh
│   ├── verify_endpoints.py
│   └── README.md
├── prj.conf          # Zephyr project configuration
├── CMakeLists.txt
└── VERSION
```

### Build Configuration

**Key Kconfig Options** (in `prj.conf`):
```
CONFIG_USB_DEVICE_STACK_NEXT=y
CONFIG_USB_DEVICE_MANUFACTURER="Electronic Cats"
CONFIG_USB_DEVICE_PRODUCT="Catsniffer"
CONFIG_USB_DEVICE_VID=0x1209
CONFIG_USB_DEVICE_PID=0xBABB

CONFIG_LORA=y
CONFIG_LORA_SX126X=y

CONFIG_UART_INTERRUPT_DRIVEN=y
CONFIG_RING_BUFFER=y
```

### Build Steps

```bash
# Clean build
west build -b rpi_pico -p

# Incremental build
west build -b rpi_pico

# Build with debugging
west build -b rpi_pico -- -DOVERLAY_CONFIG=debug.conf

# Flash via USB bootloader
# Hold BOOTSEL button while connecting USB
cp build/zephyr/zephyr.uf2 /Volumes/RPI-RP2/

# Or use the automated script
./scripts/catsniffer_build_flash_test.sh
```

### Firmware Size

Typical build:
- **Flash**: ~63 KB / 2 MB (3% usage)
- **RAM**: ~29 KB / 264 KB (11% usage)

---

## Development

### Testing

Run the verification script to test all endpoints and commands:

```bash
# Basic test (4 tests)
python3 scripts/verify_endpoints.py

# Full test suite (12 tests)
python3 scripts/verify_endpoints.py --test-all

# Test specific device
python3 scripts/verify_endpoints.py --device 1
```

See [scripts/README.md](scripts/README.md) for details.

### Adding New Shell Commands

1. **Add forward declaration** in `shell_commands.c`:
```c
static void cmd_mycommand(char *args);
```

2. **Add to command table**:
```c
{"mycommand", cmd_mycommand, "My command help", false},
```

3. **Implement handler**:
```c
static void cmd_mycommand(char *args) {
    shell_reply("Command executed\r\n");
}
```

### LED Indicators

- **LED0**: USB enumeration status
- **LED1**: Reserved
- **LED2**: Mode indicator
  - Slow blink (1s): Normal operation / Stream mode
  - Fast blink (200ms): Boot mode / Command mode

### Debugging

```bash
# View serial output
screen /dev/cu.usbmodem2105 115200

# Monitor USB enumeration
system_profiler SPUSBDataType | grep -A 10 "1209:babb"

# Check endpoints
python3 scripts/verify_endpoints.py
```

---

## Troubleshooting

### Device Not Detected

**Check USB enumeration:**
```bash
# macOS
system_profiler SPUSBDataType | grep -i catsniffer

# Linux
lsusb | grep 1209:babb
```

**Reset to bootloader:**
1. Disconnect USB
2. Hold BOOTSEL button
3. Connect USB
4. Release button
5. Flash firmware

### Serial Port Permissions (Linux)

```bash
sudo usermod -a -G dialout $USER
# Log out and back in
```

### LoRa Not Working

1. Check initialization:
```bash
> status
# Should show: LoRa: initialized
```

2. Verify band selection:
```bash
> band3  # Switch to LoRa band
```

3. Test LoRa:
```bash
> lora_mode command
# Switch to LoRa port
> TEST
# Should show: LoRa: Initialization completed!
```

### Commands Not Responding

1. Check baud rate: 115200 for all ports
2. Check line endings: Use `\r\n` or `\n`
3. Verify correct port:
   - Cat-Shell for configuration (ends in X5)
   - Cat-LoRa for LoRa commands (ends in X3)

### Build Errors

```bash
# Clean build directory
rm -rf build

# Rebuild from scratch
west build -b rpi_pico -p

# Check Zephyr environment
west --version
```

---

## Performance

### Throughput

- **CC1352 UART**: Up to 921600 baud (115 KB/s)
- **LoRa**: Depends on modulation (SF7@125kHz: ~5.5 kbps, SF12@125kHz: ~250 bps)
- **USB**: Full-speed (12 Mbps)

### Latency

- **USB to UART**: <1 ms
- **LoRa Air Time**:
  - SF7, 20 bytes: ~30 ms
  - SF12, 20 bytes: ~1.5 s

### Power Consumption

- Active (all radios): ~150 mA @ 5V
- CC1352 only: ~30 mA
- LoRa TX (20 dBm): ~120 mA

---

## Contributing

Contributions are welcome! Please ensure:

1. Code follows existing style
2. All tests pass (`./scripts/verify_endpoints.py --test-all`)
3. Build succeeds without warnings
4. Documentation is updated

---

## License

Check with Electronic Cats for licensing information.

---

## References

- [Zephyr Project Documentation](https://docs.zephyrproject.org/)
- [RP2040 Datasheet](https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf)
- [CC1352P Technical Reference](https://www.ti.com/product/CC1352P)
- [SX1262 Datasheet](https://www.semtech.com/products/wireless-rf/lora-core/sx1262)
- [Electronic Cats CatSniffer](https://github.com/ElectronicCats/CatSniffer)

---

## Support

- **Issues**: Report bugs via GitHub Issues
- **Documentation**: See `docs/` directory
- **Scripts**: See [scripts/README.md](scripts/README.md)

---

**Version**: 0.2.0
**Last Updated**: January 2026
**Maintainer**: Electronic Cats
