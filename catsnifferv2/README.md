# CatSniffer V3 Tools – User Guide
> Current version: v3.0.0

## Content Table

- [CatSniffer V3 Tools – User Guide](#catsniffer-v3-tools--user-guide)
  - [Content Table](#content-table)
  - [Overview](#overview)
  - [Features](#features)
  - [Installation](#installation)
    - [Global install](#global-install)
    - [Environment install](#environment-install)
  - [Getting Started](#getting-started)
  - [Verifying Devices](#verifying-devices)
  - [Flashing Firmware (CC1352)](#flashing-firmware-cc1352)
    - [Flash Command Help](#flash-command-help)
    - [Listing Available Firmware](#listing-available-firmware)
      - [Firmware Selection Methods:](#firmware-selection-methods)
    - [Flashing a Firmware Image](#flashing-a-firmware-image)
      - [Method 1: Using Aliases (Recommended)](#method-1-using-aliases-recommended)
      - [Method 2: Using Partial Names](#method-2-using-partial-names)
      - [Method 3: Using Full Filenames](#method-3-using-full-filenames)
      - [Example Flashing Process](#example-flashing-process)
      - [Flashing Workflow:](#flashing-workflow)
    - [Flashing Errors and Recovery](#flashing-errors-and-recovery)
      - [Troubleshooting Steps](#troubleshooting-steps)
  - [Testing Device Functionality](#testing-device-functionality)
    - [Basic Verification](#basic-verification)
    - [Comprehensive Testing](#comprehensive-testing)
    - [Testing Specific Devices](#testing-specific-devices)
    - [Quiet Mode](#quiet-mode)
    - [Verification Command Options](#verification-command-options)
    - [Troubleshooting Failed Verification](#troubleshooting-failed-verification)
  - [Sniffing Protocols](#sniffing-protocols)
    - [Bluetooth Low Energy(BLE) Sniffing](#bluetooth-low-energyble-sniffing)
    - [LoRa Sniffing](#lora-sniffing)
      - [Example configuration:](#example-configuration)
    - [Zigbee Sniffing](#zigbee-sniffing)
    - [Thread Sniffing](#thread-sniffing)
  - [Pipeline Warnings and Firmware Updates](#pipeline-warnings-and-firmware-updates)
  - [Wireshark Extcap Integration](#wireshark-extcap-integration)
  - [Future Improvements](#future-improvements)

## Overview

This new version of CatSniffer Tools is designed as a unified environment that combines all existing tools into a single workflow.

Instead of maintaining multiple standalone scripts, all functionality is now exposed through one main script, allowing you to manage firmware, flashing, and protocol sniffing from a single entry point.

## Features

- All-in-One CatSniffer Environment: Single unified CLI that replaces multiple standalone scripts, simplifying firmware management, flashing, and protocol sniffing.
- Automatic Firmware Management: Automatically detects, downloads, verifies (SHA256), and updates firmware releases from the official repository.
- Automatic Device Detection: Detects connected CatSniffer devices automatically, with optional manual device selection for multi-device setups.
- Multi-Protocol Sniffing:
  - LoRa (SX1262)
  - Zigbee
  - Thread
  - BLE (via Sniffle firmware)
- On-Demand Firmware Flashing: Automatically flashes the required firmware if it is not detected before starting a sniffing session.
- Wireshark Integration (Extcap): Native extcap support for live captures directly inside Wireshark, including custom dissectors.
- Cross-Platform Support: Compatible with Linux, macOS, and Windows.

## Installation

### Global install
If you want to use this tool in your global context running just `catsniffer` without navigating through the repo:
```bash
git clone https://github.com/ElectronicCats/CatSniffer-Tools.git
cd CatSniffer-Tools/catsnifferv2/
pip install .
```

### Environment install
```bash
git clone https://github.com/ElectronicCats/CatSniffer-Tools.git
cd CatSniffer-Tools/catsnifferv2/
python -m venv .venv
source .venv/bin/activate # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Getting Started

When starting from a clean environment, the tool automatically downloads the latest firmware releases from the official repository:

```bash
python3 catsniffer.py
```

You will see the CatSniffer ASCII art header followed by initialization messages:

```bash
╭─ PyCat-Sniffer CLI - For sniffing the TI CC1352 device communication interfa─╮
│                                                                              │
│        :-:              :--       |                                          │
│        ++++=.        .=++++       |                                          │
│        =+++++===++===++++++       |                                          │
│        -++++++++++++++++++-       |                                          │
│   .:   =++---++++++++---++=   :.  |  Module:  Catsniffer                     │
│   ::---+++.   -++++-   .+++---::  |  Version: 3.0.0                          │
│  ::1..:-++++:   ++++   :++++-::.::|  Company: Electronic Cats - PWNLAB       │
│  .:...:=++++++++++++++++++=:...:. |                                          │
│   :---.  -++++++++++++++-  .---:  |                                          │
│   ..        .:------:.        ..  |                                          │
│                                                                              │
╰──────────────────────────────────────────────────────────────────────────────╯


[10:20:29] [*] Looking for local releases
           [*] No Local release folder found!
           [*] Local release folder created: /path/to/CatSniffer-Tools/release_board-v3.x-v1.2.2
           [*] Local metadata created
[10:20:30] [*] Firmware airtag_scanner_CC1352P_7_v1.0.hex done.
           [*] airtag_scanner_CC1352P_7_v1.0.hex Checksum SHA256 verified
...
[10:20:34] [*] Current Release board-v3.x-v1.2.2 - 2025-06-09T22:07:38Z
```

After initialization, the available commands are displayed:

```bash
Usage: catsniffer.py [OPTIONS] COMMAND [ARGS]...

  CatSniffer: All in one catsniffer tools environment.

Options:
  -v, --verbose  Show Verbose mode
  -h, --help     Show this message and exit.

Commands:
  cativity       IQ Activity Monitor (Not implemented yet)
  devices        List connected CatSniffer devices
  flash          Flash CC1352 Firmware or list available firmware images
  help-firmware  Show detailed information about available firmware images
  sniff          Sniffer protocol control
  verify         Verify CatSniffer device functionality
```

---

## Verifying Devices

The script automatically detects connected CatSniffer devices and assigns them sequential IDs. Each CatSniffer device exposes three serial ports:
- **Cat-Bridge (CC1352)**: Main communication port for firmware flashing and sniffing
- **Cat-LoRa (SX1262)**: LoRa radio interface
- **Cat-Shell (Config)**: Configuration and bootloader control

To list all connected devices with their assigned ports:
```bash
python3 catsniffer.py devices
```

Example output with two connected CatSniffers:

```bash

                          Found 2 CatSniffer device(s)
╭───────────────┬─────────────────────┬───────────────────┬────────────────────╮
│ Device        │ Cat-Bridge (CC1352) │ Cat-LoRa (SX1262) │ Cat-Shell (Config) │
├───────────────┼─────────────────────┼───────────────────┼────────────────────┤
│ CatSniffer #1 │ /dev/ttyACM3        │ /dev/ttyACM4      │ /dev/ttyACM5       │
│ CatSniffer #2 │ /dev/ttyACM0        │ /dev/ttyACM1      │ /dev/ttyACM2       │
╰───────────────┴─────────────────────┴───────────────────┴────────────────────╯
```

> [!Note]
> When multiple devices are connected, use the device ID (e.g., --device 2) with other commands to target a specific CatSniffer.


---

## Flashing Firmware (CC1352)

You can flash firmware images to the CatSniffer device using the flash command. The tool supports firmware aliases, partial names, and full filenames.

### Flash Command Help
```bash
python3 catsniffer.py flash --help

Usage: catsniffer.py flash [OPTIONS] [FIRMWARE]

  Flash CC1352 Firmware or list available firmware images

Options:
  -d, --device INTEGER  Device ID (for multiple CatSniffers). If not
                        specified, first device will be selected.
  -l, --list            List available firmware images to flash
  -h, --help            Show this message and exit.
```

### Listing Available Firmware
To view all available firmware images with their aliases and descriptions:

```bash
python catsniffer.py flash --list
```

Example output:
```bash
Available Firmware Images:

╭─────────────────┬───────────────────────────────────┬────────────────┬────────────────────┬────────────────────────────────────────────────────╮
│ Alias           │ Firmware Name                     │ Type           │ Protocols          │ Description                                        │
├─────────────────┼───────────────────────────────────┼────────────────┼────────────────────┼────────────────────────────────────────────────────┤
│ lora            │ LoRa-CAD.uf2                      │ LoRa CAD       │ LoRa               │ Channel activity detector v1.0.0                   │
│ lora_1          │ LoRa-CLI.uf2                      │ LoRa CLI       │ LoRa               │ LoRa Command Line Interface v1.0                   │
│ lora_2          │ LoRa-Freq.uf2                     │ LoRa Freq      │ LoRa               │ Frequency Spectrum analyzer v1.0.0                 │
│ lorasniffer     │ LoraSniffer.uf2                   │ LoRa Sniffer   │ LoRa               │ CLI LoRa for connection with pycatsniffer as sn... │
│ serialpassth... │ SerialPassthroughwithboot.uf2     │ Serial         │ Serial             │ No description available                           │
│ airtag_scanner  │ airtag_scanner_CC1352P_7_v1.0.hex │ Airtag Scanner │ BLE                │ Apple Airtag Scanner firmware (Windows/Linux/Mac)  │
│ airtag_spoofer  │ airtag_spoofer_CC1352P_7_v1.0.hex │ Airtag Spoofer │ BLE                │ Apple Airtag Spoofer firmware (Windows/Linux/Mac)  │
│ firmware        │ firmware.uf2                      │ Other          │ Various            │ Meshtastic port for Catsniffer                     │
│ free            │ free_dap_catsniffer.uf2           │ Debugger       │ Debug              │ Debugger firmware for CC1352                       │
│ justworks       │ justworks_scanner_CC1352P7_1.hex  │ JustWorks      │ BLE                │ Justworks scanner for scanner vulnerable devices   │
│ zigbee          │ sniffer_fw_CC1352P_7_v1.10.hex    │ TI Sniffer     │ Zigbee/Thread/15.4 │ Multiprotocol sniffer from Texas Instrument (Wi... │
│ ble             │ sniffle_cc1352p7_1M.hex           │ BLE            │ BLE                │ BLE sniffer for Bluetooth 5 and 4.x (LE) from N... │
╰─────────────────┴───────────────────────────────────┴────────────────┴────────────────────┴────────────────────────────────────────────────────╯

Recommended Aliases by Protocol:

  BLE:
    ble / sniffle     → Sniffle BLE sniffer
    airtag-scanner → Apple Airtag Scanner
    airtag-spoofer → Apple Airtag Spoofer
    justworks     → JustWorks scanner

  Zigbee/Thread/15.4 (TI Sniffer):
    zigbee  → Texas Instruments multiprotocol sniffer
    thread  → (same as zigbee - supports both)
    15.4    → (same as zigbee - supports 802.15.4)
    ti      → Texas Instruments sniffer
    multiprotocol → TI multiprotocol firmware

  LoRa (RP2040):
    lora-sniffer → LoRa Sniffer for Wireshark
    lora-cli    → LoRa Command Line Interface
    lora-cad    → LoRa Channel Activity Detector
    lora-freq   → LoRa Frequency Spectrum analyzer

Usage Examples:
  catsniffer flash zigbee          (TI multiprotocol sniffer)
  catsniffer flash thread         (same TI firmware)
  catsniffer flash ble            (Sniffle BLE)
  catsniffer flash lora-sniffer   (LoRa Sniffer)
  catsniffer flash airtag-scanner (Apple Airtag)
  catsniffer flash --device 1 zigbee
```

#### Firmware Selection Methods:
1. Alias: Use short names like ble, justworks
2. Partial name: Any unique part of the filename (case-insensitive)
3. Full filename: Exact filename as shown in the list

### Flashing a Firmware Image

Firmware can be flashed using aliases, partial names, or full filenames:

#### Method 1: Using Aliases (Recommended)
```bash
# Flash BLE Sniffle firmware using the 'ble' alias
python3 catsniffer.py flash ble -d 1

# Flash Airtag Scanner firmware
python3 catsniffer.py flash airtag_scanner

# Flash JustWorks scanner
python3 catsniffer.py flash justworks
```


#### Method 2: Using Partial Names
```bash
# Flash using any unique part of the filename
python3 catsniffer.py flash sniffle -d 1
```

#### Method 3: Using Full Filenames
```bash
# Flash using the exact filename
python3 catsniffer.py flash sniffle_cc1352p7_1M.hex -d 1
```

#### Example Flashing Process

When flashing firmware, you'll see detailed output showing each step:

```bash
ℹ Alias 'ble' resolved to: sniffle
ℹ Flashing firmware: sniffle to device: CatSniffer #1
Alias 'sniffle' matched to: sniffle_cc1352p7_1M.hex
[*] Opening bridge port /dev/ttyACM3 at baud: 500000
[*] Sending boot command via shell port: /dev/ttyACM5
[*] Boot command sent successfully
[*] Chip ID: 0xF000 (CatSniffer CC1352 (Bootloader Mode))
[*] Chip details:
        Package: CC1350 PG2.0 - 704 KB Flash - 20KB SRAM - CCFG.BL_CONFIG at 0x000AFFD8
        Primary IEEE Address: 00:12:4B:00:2A:79:BF:F1
[*] Performing mass erase
[*] Erase done
[*] Write done
[*] Verifying by comparing CRC32 calculations.
[*] Verified match: 0x6d6c64a5
[*] Sending exit command via shell port
[*] Exit command sent successfullysssss
```

#### Flashing Workflow:
1. **Boot Command**: Sends command via shell port to enter bootloader mode
2. **Chip Detection**: Identifies the CC1352 chip and displays details
3. **Mass Erase**: Clears the entire flash memory
4. **Write: Programs** the new firmware
5. **Verification**: Compares CRC32 checksums to ensure integrity
6. **Exit**: Returns to normal operation mode

### Flashing Errors and Recovery

If flashing fails due to synchronization issues, you may see:

```bash
[X] Please reset your board manually, disconnect and reconnect or press the RESET_CC1 and RESET1 buttons.
Error: Timeout waiting for ACK/NACK after 'Synch'
```

#### Troubleshooting Steps
1. **Retry**: First, simply retry the flashing command
2. **Manual Reset**: If retry fails, press the RESET buttons on the CatSniffer device
   1. **RESET_CC1**: Resets the CC1352 microcontroller
   2. **RESET1**: General system reset
3. **Reconnect**: Disconnect and reconnect the USB cable
4. **Verify Device**: Use catsniffer.py devices to ensure the device is properly detected


**Common Issues and Solutions**
- **No device found**: Ensure CatSniffer is connected and drivers are installed
- **Partial port detection**: Some ports may not appear if the device firmware is corrupted
- **Permission denied**: On Linux/macOS, you may need to add your user to the dialout group

---

## Testing Device Functionality
The `verify` command provides comprehensive testing of CatSniffer hardware functionality, ensuring all components are working correctly before use.

### Basic Verification
To run tests on all connectes devices:

```bash
python3 catsniffer.py verify
```

This performs:
- Device detection and port mapping
- Basic shell command validation (help, status, lora_config, lora_mode)
- Device status reporting

Example output:

```bash
Starting device verification...
✓ Found 1 CatSniffer device(s)
                             Detected Devices
╭───────────────┬──────────────┬──────────────┬──────────────┬────────────╮
│ Device        │ Bridge Port  │ LoRa Port    │ Shell Port   │ Status     │
├───────────────┼──────────────┼──────────────┼──────────────┼────────────┤
│ CatSniffer #1 │ /dev/ttyACM0 │ /dev/ttyACM1 │ /dev/ttyACM2 │ ✓ Complete │
╰───────────────┴──────────────┴──────────────┴──────────────┴────────────╯

============================================================
Testing CatSniffer #1
============================================================
╭──────────────────────────────────────────────────────────────────────────────────────╮
│ Testing CatSniffer #1 - Basic Commands                                               │
╰──────────────────────────────────────────────────────────────────────────────────────╯

[HELP] Help command...
  ✓ PASS
  Response: helpCommands:
  help     - Show available commands
  boot     - CC1352 bootloader mode
  exit   ...

[STATUS] Status command...
  ✓ PASS
  Response: statusMode: 0, Band: 0, LoRa: initialized, LoRa Mode: Command

[LORA_CONFIG] LoRa config command...
  ✓ PASS
  Response: lora_configLoRa Configuration:
  Frequency: 915000000 Hz
  Spreading Factor: SF7
  Bandwidth: 12...

[LORA_MODE] LoRa mode switch...
  ✓ PASS
  Response: lora_mode streamLoRa mode set to STREAM (slow blink)

Summary: 4/4 tests passed
╭──────────────────────────────────────────────────────────────────────────────────────╮
│                                                                                      │
│  Verification Summary                                                                │
│                                                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────╯

  Device      Basic
 ───────────────────
  Device #1    ✅

✓ Verification completed successfully!

✓ Basic functionality verified. Use --test-all for comprehensive testing.
```

### Comprehensive Testing
For complete hardware validation including LoRa configuration and communication:

```bash
python3 catsniffer.py verify --test-all
```

This adds:
- **LoRa Configuration Tests**: Frecuency, spreading factor, bandwidth, coding rate, TX power
- **LoRa Communication Tests**: Inter-port communication between LoRa and Shell ports
- **Data Transmission Verification**: TEST, TXTEST, and TX command validation

Example output with `--test-all`

```bash
╭──────────────────────────────────────────────────────────────────────────────────────╮
│ Testing CatSniffer #1 - LoRa Configuration                                           │
╰──────────────────────────────────────────────────────────────────────────────────────╯

[FREQ] Set frequency to 915MHz...
  ✓ PASS

[SF] Set spreading factor to 7...
  ✓ PASS

[BW] Set bandwidth to 125kHz...
  ✓ PASS

[CR] Set coding rate to 4/5...
  ✓ PASS

[POWER] Set TX power to 14dBm...
  ✓ PASS

[APPLY] Apply configuration...
  ✓ PASS

Summary: 6/6 configuration tests passed
╭──────────────────────────────────────────────────────────────────────────────────────╮
│ Testing CatSniffer #1 - LoRa Communication                                           │
╰──────────────────────────────────────────────────────────────────────────────────────╯

[SETUP] Switching to command mode...
  ✓ Command mode enabled

[TEST] Sending 'TEST' to LoRa port...
  Sent 6 bytes to LoRa port
  Shell response: TEST: LoRa ready!
  ✓ Response received and validated

[TEST2] Sending 'TEST' to LoRa port...
  Sent 6 bytes to LoRa port
  Shell response: TEST: LoRa ready!
  ✓ Response received and validated

[TXTEST] Sending 'TXTEST' to LoRa port...
  Sent 8 bytes to LoRa port
  Shell response: DEBUG: Sending PING packet
TX Result: 0 (Success)
  ✓ Response received and validated

[TX] Sending 'TX 50494E47' to LoRa port...
  Sent 13 bytes to LoRa port
  Shell response: DEBUG: Hex input '50494E47', length 8
DEBUG: Converting to 4 bytes
DEBUG: Sending bytes 50 49 4E 4...
  ✓ Response received and validated

[CHECK] Checking for data on LoRa port...
  No data on LoRa port (normal)

[CLEANUP] Switching back to stream mode...
  ✓ Stream mode restored

Summary: 5/5 communication tests passed
╭──────────────────────────────────────────────────────────────────────────────────────╮
│                                                                                      │
│  Verification Summary                                                                │
│                                                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────╯

  Device      Basic   Config   Comm   Overall
 ─────────────────────────────────────────────
  Device #1    ✅       ✅      ✅      ✅

✓ Verification completed successfully!

✓ All devices are fully functional and ready for use!
```

### Testing Specific Devices
When multiple CatSniffers are connected, test a specific device by ID:

```bash
# Test only device #2
python3 catsniffer.py verify --test-all --device 2

# Test only device #3 with quiet output and basic mode
python3 catsniffer.py verify --device 3 -q
```

### Quiet Mode
For automated testing or minimal output, use quiet mode:

```bash
python3 catsniffer.py verify --test-all --device 1 --quiet
```

Quiet mode provides concise output:
```bash
╭──────────────────────────────────────────────────────────────────────────────────────╮
│ Testing CatSniffer #1 - Basic Commands                                               │
╰──────────────────────────────────────────────────────────────────────────────────────╯

Summary: 4/4 tests passed
╭──────────────────────────────────────────────────────────────────────────────────────╮
│ Testing CatSniffer #1 - LoRa Configuration                                           │
╰──────────────────────────────────────────────────────────────────────────────────────╯

Summary: 6/6 configuration tests passed
╭──────────────────────────────────────────────────────────────────────────────────────╮
│ Testing CatSniffer #1 - LoRa Communication                                           │
╰──────────────────────────────────────────────────────────────────────────────────────╯

Summary: 5/5 communication tests passed
Device #1: PASS
✓ Verification completed successfully!

✓ All devices are fully functional and ready for use!
```

### Verification Command Options

```bash
python3 catsniffer.py verify --help

Usage: catsniffer.py verify [OPTIONS]

  Verify CatSniffer device functionality

  Tests all connected CatSniffers and verifies:
  - Basic shell commands (help, status, lora_config, lora_mode)
  - LoRa configuration (frequency, SF, BW, etc.)
  - LoRa communication (TEST, TXTEST, TX commands)

  Use --test-all for comprehensive testing.

Options:
  --test-all     Run all tests including LoRa configuration and communication
  -d, --device INTEGER  Test only a specific device (by ID)
  -q, --quiet    Show only summary results
  -h, --help     Show this message and exit.
```

### Troubleshooting Failed Verification
If verification fails, check:
1. **USB Connections**: Ensure all 3 USB endpoints are properly connected
2. **Port Permissions**: On Linux/macOS, verify serial port permissions
3. **Firmware Status**: Ensure appropriate firmware is flashed for testing
4. **Cable Quality**: Try a different USB cable if communication is unstable

Common failure messages and solutions:
- **"Shell port not available"**: Check USB connection or reflash base firmware
- **"No response"**: Verify device is powered and in correct mode
- **"Unexpected response"**: May indicate firmware mismatch or corruption

---

## Sniffing Protocols

Sniffing is initiated by specifying the protocol name.
If the required firmware is not detected, the tool automatically flashes the appropriate firmware before starting the sniffer.

```bash
python catsniffer.py sniff --help
```

```bash
Usage: catsniffer.py sniff [OPTIONS] COMMAND [ARGS]...

  Sniffer protocol control

Options:
  -v, --verbose  Show Verbose mode
  -h, --help     Show this message and exit.

Commands:
  ble     Sniffing BLE with Sniffle firmware
  lora    Sniffing LoRa with Sniffer SX1262 firmware
  thread  Sniffing Thread with Sniffer TI firmware
  zigbee  Sniffing Zigbee with Sniffer TI firmware
```
### Bluetooth Low Energy(BLE) Sniffing


### LoRa Sniffing
```bash
python3 catsniffer.py sniff lora --help
```

Available options include frequency, bandwidth, spreading factor, sync word, preamble length and coding rate.


```bash
Usage: catsniffer.py sniff lora [OPTIONS]

  Sniffing LoRa with Sniffer SX1262 firmware

Options:
  -ws                             Open Wireshark
  -freq, --frequency INTEGER      Frequency in Hz (e.g., 915000000 for 915
                                  MHz)
  -bw, --bandwidth [125|250|500]  Bandwidth in kHz
  -sf, --spread_factor INTEGER RANGE
                                  Spreading Factor (7-12)  [7<=x<=12]
  -cr, --coding_rate INTEGER RANGE
                                  Coding Rate (5-8)  [5<=x<=8]
  -pw, --tx_power INTEGER         TX Power in dBm
  -d, --device INTEGER            Device ID (for multiple CatSniffers)
  -h, --help                      Show this message and exit.
```

#### Example configuration:
```bash
python3 catsniffer.py sniff lora -freq 916 -bw 125 -sf 11 -d 1 -ws
```

### Zigbee Sniffing
```bash
python3 catsniffer.py sniff zigbee -c 25 -d 1
```

### Thread Sniffing
```bash
python3 catsniffer.py sniff thread -c 25 -d 1
```

Thread sniffing follows the same workflow as Zigbee.

## Pipeline Warnings and Firmware Updates

If a previous sniffer instance was not closed properly, you may encounter:
```bash
[-] Pipeline already exists.
```
This warning in most of the sniff process wil not cause disruption of the communication. But is you encounter some problems you can use the following command to remove the pipeline created and re-run the tool.

**This only works for Unix-like systems:**
```bash
rm /tmp/fcatsniffer
```

In this scenario:
- Ensure that previous processes are terminated before starting a new session

## Wireshark Extcap Integration

> At the version **2.0.1** this Extcap only works for Unix-like systems

To enable Wireshark support, create a symbolic link to the extcap script:

```bash
ln -s ${PWD}/lora_extcap.py ~/.local/lib/wireshark/extcap
```

> The destination path may vary depending on your operating system. For more information check [Dissector for Wireshark](https://github.com/ElectronicCats/CatSniffer/wiki/02.-Supported-Software#dissector-for-wireshark)

Once linked:
- The new extcap plugin will appear in Wireshark
- Capturing can begin directly from the Wireshark interface

For LoRa captures:
- Use the dissector `catsniffersx1262_rpi`
- Configure it under `DLT_USER 148`

## Future Improvements

Planned enhancements include:
- Reliable firmware downloads with retry and error correction
- Ability to launch Sniffle directly from the CLI
- Compatibility with Jupyter-based workflows
- TUI for handling the device communications
- Windows Extcap support
- Integration with SXTools and cativity
