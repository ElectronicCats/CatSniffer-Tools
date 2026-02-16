# CatSniffer V3 Tools – Complete User Guide
> **Current Version:** v3.0.0
> **Developed by:** Electronic Cats - PWNLAB

---

## Table of Contents

- [CatSniffer V3 Tools – Complete User Guide](#catsniffer-v3-tools--complete-user-guide)
  - [Table of Contents](#table-of-contents)
  - [Introduction](#introduction)
    - [What is CatSniffer V3 Tools?](#what-is-catsniffer-v3-tools)
    - [Who is this tool for?](#who-is-this-tool-for)
  - [Project Architecture](#project-architecture)
    - [Directory Structure](#directory-structure)
    - [Main Components](#main-components)
      - [1. **catsniffer.py** (Entry Point)](#1-catsnifferpy-entry-point)
      - [2. **`modules/` Module** (Application Core)](#2-modules-module-application-core)
      - [3. **`protocol`/ Module** (Radio Drivers)](#3-protocol-module-radio-drivers)
      - [4. **Auto-generated Firmware Directory**](#4-auto-generated-firmware-directory)
  - [Capabilities and Features](#capabilities-and-features)
    - [Main Features](#main-features)
  - [Installation](#installation)
    - [Prerequisites](#prerequisites)
    - [Global Installation](#global-installation)
    - [Virtual Environment Installation](#virtual-environment-installation)
  - [Quick Start](#quick-start)
    - [First Execution](#first-execution)
    - [Available Commands](#available-commands)
    - [Verifying Connected Devices](#verifying-connected-devices)
      - [CatSniffer Port Architecture](#catsniffer-port-architecture)
      - [Example with Multiple Devices](#example-with-multiple-devices)
  - [Firmware Management](#firmware-management)
    - [Viewing Available Firmware](#viewing-available-firmware)
    - [Firmware Selection Methods](#firmware-selection-methods)
      - [1. Using Aliases (Recommended)](#1-using-aliases-recommended)
      - [2. Using Partial Names](#2-using-partial-names)
      - [3. Using Full Names](#3-using-full-names)
    - [Flashing Process](#flashing-process)
    - [Troubleshooting Flashing Issues](#troubleshooting-flashing-issues)
      - [Common Errors and Solutions](#common-errors-and-solutions)
  - [Device Verification](#device-verification)
    - [Basic Verification](#basic-verification)
    - [Complete Verification](#complete-verification)
    - [Specific Device Verification](#specific-device-verification)
    - [Quiet Mode](#quiet-mode)
    - [Failure Diagnosis](#failure-diagnosis)
  - [Protocol Sniffing](#protocol-sniffing)
    - [Bluetooth Low Energy (BLE)](#bluetooth-low-energy-ble)
      - [BLE Configuration Parameters](#ble-configuration-parameters)
      - [Practical Example: Basic BLE Capture](#practical-example-basic-ble-capture)
      - [Wireshark Integration](#wireshark-integration)
      - [Common Use Cases](#common-use-cases)
    - [AirTag Scanner](#airtag-scanner)
      - [What is AirTag?](#what-is-airtag)
      - [Basic Usage](#basic-usage)
      - [PuTTY Integration](#putty-integration)
      - [Cross-Platform Support](#cross-platform-support)
      - [Manual Serial Connection](#manual-serial-connection)
      - [Practical Use Cases](#practical-use-cases)
      - [Troubleshooting](#troubleshooting)
    - [Important Notes](#important-notes)
  - [IQ Activity Monitor (Cativity)](#iq-activity-monitor-cativity)
    - [Fundamental Concepts](#fundamental-concepts)
      - [What is 802.15.4?](#what-is-802154)
      - [802.15.4 Channels](#802154-channels)
    - [Command Help](#command-help)
    - [Operation Modes](#operation-modes)
      - [1. Channel Activity Monitoring (Default Mode)](#1-channel-activity-monitoring-default-mode)
      - [2. Fixed Channel Mode](#2-fixed-channel-mode)
      - [3. Network Topology Discovery](#3-network-topology-discovery)
      - [4. Protocol Filter](#4-protocol-filter)
    - [Practical Examples](#practical-examples)
      - [Example 1: Zigbee Network Audit](#example-1-zigbee-network-audit)
      - [Example 2: Interference Detection](#example-2-interference-detection)
      - [Example 3: Deep Channel Analysis](#example-3-deep-channel-analysis)
      - [Example 4: Multi-Device Configuration](#example-4-multi-device-configuration)
    - [Troubleshooting](#troubleshooting-1)
  - [Wireshark Integration](#wireshark-integration-1)
    - [What is Extcap?](#what-is-extcap)
    - [Extcap Plugin Installation](#extcap-plugin-installation)
      - [On Unix-like Systems (Linux, macOS)](#on-unix-like-systems-linux-macos)
    - [Integrated Capture Workflow](#integrated-capture-workflow)
    - [Current Limitations](#current-limitations)
  - [Common Problem Solving](#common-problem-solving)
    - [Problem: Pipeline Already Exists](#problem-pipeline-already-exists)
    - [Problem: Permission Denied on Serial Ports](#problem-permission-denied-on-serial-ports)
    - [Problem: Device Not Detected](#problem-device-not-detected)
    - [Problem: Flash Verification Failed](#problem-flash-verification-failed)
    - [Problem: Wireshark Shows No Packets](#problem-wireshark-shows-no-packets)
    - [Problem: Cativity Shows No Activity](#problem-cativity-shows-no-activity)
  - [Contributions and Support](#contributions-and-support)
    - [How to Contribute](#how-to-contribute)
    - [Report Issues](#report-issues)
    - [Additional Resources](#additional-resources)
  - [License](#license)
  - [Credits](#credits)

---

## Introduction

### What is CatSniffer V3 Tools?

CatSniffer V3 Tools is a unified development environment designed for research and analysis of communication protocols in the Internet of Things (IoT). This tool centralizes in a single command-line interface (CLI) all the functionalities needed to work with CatSniffer V3 hardware, eliminating the need to use multiple independent scripts.

The system automates complex processes such as firmware management, hardware configuration, and radio traffic capture, allowing users to focus on security analysis and protocol development.

### Who is this tool for?

This tool is aimed at:
- **Security researchers** analyzing vulnerabilities in IoT devices
- **Firmware developers** working with wireless communication protocols
- **Network engineers** specializing in Zigbee, Thread, LoRa, and BLE technologies
- **Pentesting professionals** assessing the security of IoT ecosystems

---

## Project Architecture

### Directory Structure

```text
CatSniffer-Tools/
├── catsniffer.py               # Main entry point
├── lora_extcap.py              # Wireshark extcap plugin (LoRa)
├── requirements.txt            # Python dependencies
├── setup.py                    # Installation configuration
├── modules/                    # Core application modules
│   ├── cli.py                  # CLI command definitions
│   ├── catnip.py               # Firmware management and flashing
│   ├── catsniffer.py           # Hardware detection and communication
│   ├── bridge.py               # Serial communication bridge
│   ├── cc2538.py               # CC2538 chip controller
│   ├── pipes.py                # PCAP pipe management for Wireshark
│   ├── verify.py               # Hardware diagnostic tests
│   ├── fw_aliases.py           # Firmware aliases
│   ├── fw_metadata.py          # Firmware metadata
│   └── cativity/               # IQ Activity Monitor
│       ├── graphs.py           # Graph visualization
│       ├── network.py          # Network topology analysis
│       ├── packets.py          # Packet processing
│       └── runner.py           # Cativity main orchestrator
└── protocol/                   # Radio protocol drivers
    ├── common.py               # Shared functionality
    ├── sniffer_ti.py           # Texas Instruments chip support
    └── sniffer_sx.py           # Semtech chip support (LoRa)
```

### Main Components

#### 1. **catsniffer.py** (Entry Point)
Main script providing access to all system functionalities through structured commands.

#### 2. **`modules/` Module** (Application Core)

- **cli.py**: Defines the user-available command interface
- **catnip.py**: Manages download, SHA256 verification, and flashing of firmware to the CC1352 chip
- **catsniffer.py**: Implements automatic serial port detection logic and hardware communication
- **bridge.py**: Establishes the serial communication bridge with devices
- **cc2538.py:** Provides low-level control for the CC2538 chip
- **pipes.py**: Creates data pipes that transmit captured packets in PCAP format to Wireshark
- **verify.py**: Runs self-diagnostic tests to validate hardware operation
- **cativity/**: Submodule dedicated to monitoring activity on 802.15.4 channels (Zigbee/Thread)

#### 3. **`protocol`/ Module** (Radio Drivers)

Contains specific implementations for each radio chip family:
- **sniffer_ti.py**: Driver for Texas Instruments chips (Zigbee, Thread, 802.15.4)
- **sniffer_sx.py**: Driver for Semtech SX1262 chips (LoRa)
- **common.py**: Functions shared across all protocols

#### 4. **Auto-generated Firmware Directory**

When run for the first time, the tool automatically creates a directory following the pattern:

```text
release_board-v3.x-vX.X.X/
```

This directory stores downloaded firmware files (.hex, .uf2) from the official GitHub repository.

---

## Capabilities and Features

### Main Features

1. Unified All-in-One Environment
   - Single CLI interface replacing multiple independent scripts
   - Simplifies firmware management, flashing, and protocol capture

2. Automatic Firmware Management
   - Automatic detection of available versions
   - Download from official GitHub repository
   - Integrity verification via SHA256
   - Automatic updates when new versions are available

3. **Automatic Device Detection**
   - Automatic identification of connected CatSniffer devices
   - Sequential ID assignment for multi-device configurations
   - Optional manual selection for environments with multiple units

4. **Multi-Protocol Support**
   - **LoRa**: SX1262 radio for long-range communications
   - **Zigbee**: IEEE 802.15.4 protocol for sensor networks
   - **Thread**: Mesh protocol for residential IoT
   - **BLE**: Bluetooth Low Energy via Sniffle firmware

5. **Automatic On-Demand Flashing**
   - Detects if required firmware is present
   - Automatically flashes before starting capture sessions
   - Minimizes manual user intervention

6. **Native Wireshark Integration**
   - Extcap support for real-time captures
   - Custom dissectors for specialized protocols
   - Integrated workflow without manual configuration

7. **Cross-Platform Compatibility**
   - Full support for Linux
   - Functionality on macOS
   - Windows compatibility

---

## Installation

### Prerequisites

- Python 3.8 or higher
- Git installed on the system
- Access permissions to serial ports (may require administrator privileges)

### Global Installation
This option installs CatSniffer Tools as a global system command, allowing it to be run from any location without navigating to the repository directory.

```bash
git clone https://github.com/ElectronicCats/CatSniffer-Tools.git
cd CatSniffer-Tools/catsnifferv2/
pip install .
```

**Installation verification:**
```bash
catsniffer --help
```

**Expected output**:
```bash
Usage: catsniffer [OPTIONS] COMMAND [ARGS]...
  CatSniffer: All in one catsniffer tools environment.
```

### Virtual Environment Installation

Recommended for development or to avoid conflicts with other Python dependencies on the system.
```bash
git clone https://github.com/ElectronicCats/CatSniffer-Tools.git
cd CatSniffer-Tools/catsnifferv2/
python -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Installation verification:**
```bash
python catsniffer.py --help
```

---

## Quick Start

### First Execution

When running the tool for the first time from a clean environment, the system automatically performs:

1. Download of the latest official firmwares
2. Integrity verification via SHA256 checksums
3. Creation of working directories

**Initial command:**
```bash
python3 catsniffer.py
```

**Expected output:**

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
           [*] Local release folder created: /path/to/release_board-v3.x-v1.2.2
           [*] Local metadata created
[10:20:30] [*] Firmware airtag_scanner_CC1352P_7_v1.0.hex done.
           [*] airtag_scanner_CC1352P_7_v1.0.hex Checksum SHA256 verified
           [*] Firmware CC1352_sniffle_CC1352P_7_v1.9.1.hex done.
           [*] CC1352_sniffle_CC1352P_7_v1.9.1.hex Checksum SHA256 verified
           ...
[10:20:34] [*] Current Release board-v3.x-v1.2.2 - 2025-06-09T22:07:38Z
```

**Output interpretation:**
- **ASCII Header**: Identifies the tool, version, and developer
- **Local release search**: Checks if firmware has been previously downloaded
- **Firmware download**: Retrieves each required file from the official repository
- **SHA256 verification**: Validates the integrity of each downloaded firmware
- **Final confirmation**: Shows the installed release version and its publication date

### Available Commands

After initialization, the tool displays available commands:

```bash
Usage: catsniffer.py [OPTIONS] COMMAND [ARGS]...

  CatSniffer: All in one catsniffer tools environment.

Options:
  -v, --verbose  Show Verbose mode
  -h, --help     Show this message and exit.

Commands:
  cativity       IQ Activity Monitor
  devices        List connected CatSniffer devices
  flash          Flash CC1352 Firmware or list available firmware images
  sniff          Sniffer protocol control
  verify         Verify CatSniffer device functionality
```

**Command description:**

| Command | Purpose |
|---------|-----------|
| `cativity` | 	IQ activity monitor for 802.15.4 networks |
| `devices` | Lists connected CatSniffer devices
flash	 |
| `flash` | Manages and flashes firmware on the CC1352 chip |
| `help-firmware` | Shows detailed information about available firmware |
| `sniff` | 	Starts wireless protocol captures |
| `verify` | Runs hardware functionality diagnostics |

### Verifying Connected Devices

Before performing any operation, it is recommended to verify that the system correctly detects CatSniffer devices.

**Command:**
```bash
python3 catsniffer.py devices
```

#### CatSniffer Port Architecture

Each CatSniffer device exposes three serial ports with specific functions:

1. **Cat-Bridge (CC1352)**: Main communication port
   - Used for firmware flashing
   - Data channel for protocol sniffing
   - TI CC1352 chip control interface

2. **Cat-LoRa (SX1262)**: LoRa radio interface
   - Communication with Semtech SX1262 chip
   - LoRa packet capture
   - Radio parameter configuration

3. **Cat-Shell (Config)**: Configuration port
   - Bootloader access
   - Advanced device configuration
   - Interactive command shell

#### Example with Multiple Devices

**Output with two connected devices:**

```bash
                          Found 2 CatSniffer device(s)
╭───────────────┬─────────────────────┬───────────────────┬────────────────────╮
│ Device        │ Cat-Bridge (CC1352) │ Cat-LoRa (SX1262) │ Cat-Shell (Config) │
├───────────────┼─────────────────────┼───────────────────┼────────────────────┤
│ CatSniffer #1 │ /dev/ttyACM3        │ /dev/ttyACM4      │ /dev/ttyACM5       │
│ CatSniffer #2 │ /dev/ttyACM0        │ /dev/ttyACM1      │ /dev/ttyACM2       │
╰───────────────┴─────────────────────┴───────────────────┴────────────────────╯
```

**Interpretation:**

- **CatSniffer #1**: First detected device, accessible as `--device 1`
- **CatSniffer #2**: Second detected device, accessible as `--device 2`
- Ports are automatically assigned by the operating system

> [!Note]
> In multi-device configurations, it is essential to specify the device ID using the `--device <ID>` parameter in all subsequent commands to avoid ambiguity.

---

## Firmware Management

The CatSniffer V3 Tools firmware management system completely automates the process of downloading, verifying, and installing firmware on the CC1352 chip.

### Viewing Available Firmware

To explore all firmware available in the official repository:

**Command:**
```bash
python catsniffer.py flash --list
```

**Flash command help:**
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

**Expected output:**

```bash
Available Firmware Images:

╭─────────────────────────┬───────────────────────────────────┬────────────────┬────────────────────┬────────────────────────────────────────────────────╮
│ Alias                   │ Firmware Name                     │ Type           │ Protocols          │ Description                                        │
├─────────────────────────┼───────────────────────────────────┼────────────────┼────────────────────┼────────────────────────────────────────────────────┤
│ lora                    │ LoRa-CAD.uf2                      │ LoRa CAD       │ LoRa               │ Channel activity detector v1.0.0                   │
│ lora_1                  │ LoRa-CLI.uf2                      │ LoRa CLI       │ LoRa               │ LoRa Command Line Interface v1.0                   │
│ lora_2                  │ LoRa-Freq.uf2                     │ LoRa Freq      │ LoRa               │ Frequency Spectrum analyzer v1.0.0                 │
│ ti_sniffer              │ LoraSniffer.uf2                   │ LoRa Sniffer   │ LoRa               │ CLI LoRa for connection with pycatsniffer as sn... │
│ serialpassth...         │ SerialPassthroughwithboot.uf2     │ Serial         │ Serial             │ No description available                           │
│ airtag_scanner_cc1352p7 │ airtag_scanner_CC1352P_7_v1.0.hex │ Airtag Scanner │ BLE                │ Apple Airtag Scanner firmware (Windows/Linux/Mac)  │
│ airtag_spoofer_cc1352p7 │ airtag_spoofer_CC1352P_7_v1.0.hex │ Airtag Spoofer │ BLE                │ Apple Airtag Spoofer firmware (Windows/Linux/Mac)  │
│ firmware                │ firmware.uf2                      │ Other          │ Various            │ Meshtastic port for Catsniffer                     │
│ ti_sniffer              │ free_dap_catsniffer.uf2           │ Debugger       │ Debug              │ Debugger firmware for CC1352                       │
│ justworks               │ justworks_scanner_CC1352P7_1.hex  │ JustWorks      │ BLE                │ Justworks scanner for scanner vulnerable devices   │
│ ti_sniffer              │ sniffer_fw_CC1352P_7_v1.10.hex    │ TI Sniffer     │ Zigbee/Thread/15.4 │ Multiprotocol sniffer from Texas Instrument (Wi... │
│ sniffle                 │ sniffle_cc1352p7_1M.hex           │ BLE            │ BLE                │ BLE sniffer for Bluetooth 5 and 4.x (LE) from N... │
╰─────────────────────────┴───────────────────────────────────┴────────────────┴────────────────────┴────────────────────────────────────────────────────╯

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

**Table structure:**
- **Alias**: Short names to facilitate selection (there may be multiple aliases per firmware)
- **Firmware File**: Full firmware file name
- **Chip**: Target chip (CC1352 in all cases for this platform)
- **Protocol**: Supported communication protocol
- **Description**: Functional description of the firmware

### Firmware Selection Methods

The system accepts three methods to specify which firmware to flash, ordered by convenience:

#### 1. Using Aliases (Recommended)
Aliases are short, memorable names assigned to each firmware. This is the most convenient method for frequent users.

*Example:*
```bash
python catsniffer.py flash sniffle
```

**Advantages:**
- Easy to remember
- Requires less typing
- Less prone to typos

#### 2. Using Partial Names
The system can make partial matches of the firmware file name.

**Ejemplo:**
```bash
python catsniffer.py flash sniffer_ti
```

**Advantages:**
- No need to remember specific aliases
- Works with any unique substring of the name
- Useful when you know part of the file name

#### 3. Using Full Names

Exact specification of the firmware file name.

**Example:**

```bash
python catsniffer.py flash sniffer_ti_CC1352P_7_v1.0.hex
```

**Advantages:**
- Absolute precision
- No possible ambiguity
- Useful in automated scripts

### Flashing Process

Firmware flashing follows a predictable and transparent flow:

**Complete example command:**
```bash
python catsniffer.py flash --device 1 sniffle
```

**Step-by-step output:**

```bash
[10:25:15] [*] Selected device: CatSniffer #1
           [*] Device port: /dev/ttyACM3
           [*] Resolving firmware alias 'sniffle'...
           [*] Matched firmware: CC1352_sniffle_CC1352P_7_v1.9.1.hex
           [*] Verifying firmware integrity...
           [*] SHA256 checksum: VERIFIED
           [*] Initiating flash sequence...
           [*] Entering bootloader mode...
           [*] Erasing flash memory...
           [*] Writing firmware (0%)
           [*] Writing firmware (25%)
           [*] Writing firmware (50%)
           [*] Writing firmware (75%)
           [*] Writing firmware (100%)
           [*] Verifying written data...
           [*] Resetting device...
           [✓] Flash completed successfully!
           [*] Device ready for use
```

**Flashing workflow:**

1. **Device selection**: Identifies the target CatSniffer
2. **Firmware resolution**: Converts alias/partial name to complete file
3. **Integrity verification**: Validates SHA256 before flashing
4. **Bootloader mode**: Places the chip in programming mode
5. **Flash erasure**: Clears existing flash memory
6. **Writing**: Transfers the new firmware with progress indicator
7. **Post-write verification**: Confirms data was written correctly
8. **Reset**: Returns device to normal operating mode

### Troubleshooting Flashing Issues

#### Common Errors and Solutions

**Error: "Device not found"**
```bash
[-] Error: No CatSniffer devices detected
```

**Cause**: The device is not connected or not recognized by the system

**Solution:**
1. Check physical USB connection
2. Verify USB-Serial drivers are installed
3. On Linux, check permissions with `ls -l /dev/ttyACM*`
4. Run `python catsniffer.py devices` to confirm detection

**Error: "Permission denied"**
```bash
[-] Error: Permission denied accessing /dev/ttyACM0
```

**Cause**: User does not have permissions to access the serial port.

**Solution on Linux:**
```bash
sudo usermod -a -G dialout $USER
# Log out and log back in
```

**Alternative solution (temporary):**
```bash
sudo python catsniffer.py flash sniffle
```

**Error: "Flash verification failed"**
```bash
[-] Error: Flash verification mismatch at address 0x1234
```

**Cause**: Error during writing, possible interference or faulty hardware.

**Recovery steps:**
1. Disconnect and reconnect the device
2. Attempt flashing again
3. Try a different USB cable
4. Verify firmware integrity: `python catsniffer.py flash --list`
5. If persists, contact technical support

**Error: "Firmware not found"**
```bash
[-] Error: Firmware 'unknown_alias' not found
```

**Cause**: The specified alias or name does not match any available firmware.

**Solution:**
```bash
python catsniffer.py flash --list  # View available firmware
```

---

## Device Verification

The verification system runs diagnostic tests to confirm that CatSniffer hardware is working correctly.

### Basic Verification

Runs fundamental communication and detection tests.

**Command:**
```bash
python catsniffer.py verify
```

**Command help:**
```bash
python catsniffer.py verify --help

Usage: catsniffer.py verify [OPTIONS]

  Verify CatSniffer device functionality

Options:
  -d, --device INTEGER  Device ID (for multiple CatSniffers)
  -a, --all             Run all verification tests
  -q, --quiet           Suppress detailed output
  -h, --help            Show this message and exit.
```

**Expected output:**

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
╭────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ Testing CatSniffer #1 - Basic Commands                                                                                                                                         │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

[HELP] Help command...
  ✓ PASS
  Response: helpCommands:
  help     - Show available commands
  boot     - CC1352 bootloader mode
  exit   ...

[STATUS] Status command...
  ✓ PASS
  Response: statusMode: 0, Band: 0, LoRa: initialized, LoRa Mode: Command, CC1352 FW: ti_sniffer (official)

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
╭────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│                                                                                                                                                                                │
│  Verification Summary                                                                                                                                                          │
│                                                                                                                                                                                │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

  Device      Basic
 ───────────────────
  Device #1    ✅

✓ Verification completed successfully!

✓ Basic functionality verified. Use --test-all for comprehensive testing.
```

### Complete Verification

Runs a comprehensive set of tests including radio transmission/reception.

**Command:**
```bash
python catsniffer.py verify --test-all
```

**Expected output:**

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
  Response: statusMode: 0, Band: 0, LoRa: initialized, LoRa Mode: Command, CC1352 FW:
ti_sniffer (official)

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

### Specific Device Verification

In multi-device configurations:

**Command:**
```bash
python catsniffer.py verify --device 2
```

### Quiet Mode

For use in scripts or when only the pass/fail result is needed:

**Command:**
```bash
python catsniffer.py verify --quiet
```

**Expected output:**
```bash
╭──────────────────────────────────────────────────────────────────────────────────────╮
│ Testing CatSniffer #1 - Basic Commands                                               │
╰──────────────────────────────────────────────────────────────────────────────────────╯

Summary: 4/4 tests passed
Device #1: PASS
✓ Verification completed successfully!

✓ Basic functionality verified. Use --test-all for comprehensive testing.
```

### Failure Diagnosis

When verification fails, the system provides detailed information to diagnose the problem:

**Failure example:**

```bash
[10:32:00] [*] Starting verification for CatSniffer #1
           [*] Testing serial communication...
           [✓] Serial port accessible: /dev/ttyACM3
           [*] Probing device identification...
           [✗] FAILED: No response from device

            Troubleshooting tips:
            1. Make sure all 3 USB endpoints are connected (Bridge, LoRa, Shell)
            2. Try reconnecting the USB cable
            3. Check if the correct firmware is flashed
            4. Verify serial port permissions (Linux/Mac)

           ╭─────────────────────────────────╮
           │  Verification: FAILED           │
           │  Check connection and retry     │
           ╰─────────────────────────────────╯
```

**Recommended diagnostic steps:**
1. **Verify physical connection**: Check USB cable and connection
2. **Re-enumerate devices**: `python catsniffer.py devices`
3. **Test alternative port**: Connect to different USB port
4. **Verify drivers**: Confirm USB-Serial driver installation
5. **Reset device**: Disconnect/reconnect power
6. **Flash firmware**: `python catsniffer.py flash sniffle` as reset

## Protocol Sniffing

The sniffing module allows capturing radio traffic in real-time and sending it to analysis tools like Wireshark.

### Bluetooth Low Energy (BLE)

CatSniffer uses Sniffle firmware for BLE traffic capture.

**Command help:**
```bash
python catsniffer.py sniff ble --help

Usage: catsniffer.py sniff ble [OPTIONS]

  Sniffing BLE with Sniffle firmware

Options:
  -d, --device INTEGER            Device ID (for multiple CatSniffers)
  -ws, --wireshark                Open Wireshark with Sniffle extcap plugin
  -c, --channel INTEGER RANGE     BLE advertising channel (37, 38, 39)
                                  [37<=x<=39]
  -m, --mode [conn_follow|passive_scan|active_scan]
                                  Sniffle mode
  -h, --help                      Show this message and exit.
```

#### BLE Configuration Parameters

**1. Advertising Channels (`--channel`)**

BLE uses three dedicated channels for advertising:
- Channel 37: Frequency 2402 MHz
- Channel 38: Frequency 2426 MHz
- Channel 39: Frequency 2480 MHz

**2. Operation Modes (`--mode`)**
- **conn_follow**: Follows established BLE connections
  - Useful for analyzing communication between already paired devices
  - Captures all traffic of the active connection

- **passive_scan**: Passive advertising scan
  - Does not send packets, only listens
  - Lower energy consumption
  - Not detectable by BLE devices

- **active_scan**: Active scan
  - Sends scan requests (SCAN_REQ)
  - Obtains more information from devices
  - Detectable by BLE devices

#### Practical Example: Basic BLE Capture

**Command:**
```bash
python catsniffer.py sniff ble --channel 37 --mode passive_scan
```

#### Wireshark Integration

For real-time visual analysis:

**Command:**
```bash
python catsniffer.py sniff ble --wireshark --channel 38 --mode conn_follow
```

**Process**:

1. Detects/flashes Sniffle firmware if necessary
2. Configures the BLE sniffer
3. Creates PCAP pipe
4. Launches Wireshark automatically
5. Wireshark begins showing packets in real-time

**Result**:
- Wireshark opens automatically
- The capture interface shows "CatSniffer BLE"
- Packets appear in real-time
- Sniffle dissector decodes BLE packets

#### Common Use Cases

**1. Device Discovery**
```bash
python catsniffer.py sniff ble -c 37 -m passive_scan
```
Useful for inventorying BLE devices in the environment.

**2. Specific Connection Analysis**
```bash
python catsniffer.py sniff ble -c 39 -m conn_follow --wireshark
```
Monitors data traffic between two paired devices.

**3. Security Audit**
```bash
python catsniffer.py sniff ble -c 38 -m active_scan
```
Obtains extended information from all nearby BLE devices.

---

### AirTag Scanner

The AirTag Scanner is a specialized firmware that allows CatSniffer to detect and monitor Apple AirTag and Find My network devices. This tool is useful for security research, privacy auditing, and understanding the Apple Find My ecosystem.

#### What is AirTag?

Apple AirTag is a tracking device that uses Bluetooth Low Energy (BLE) to communicate with nearby Apple devices, which then relay the AirTag's location to iCloud. The Find My network is a crowdsourced network of Apple devices that helps locate lost items.

**Command help:**
```bash
python catsniffer.py sniff airtag_scanner --help

Usage: catsniffer.py sniff airtag_scanner [OPTIONS]

  Sniffing Airtag Scanner firmware

Options:
  -d, --device INTEGER  Device ID (for multiple CatSniffers)
  --putty               Open PuTTY with serial configuration
  -h, --help            Show this message and exit.
```

#### Basic Usage

The AirTag Scanner operates differently from other sniffing modes. Instead of creating a PCAP file, it outputs detection information directly to the serial console.

**Command:**
```bash
python catsniffer.py sniff airtag_scanner
```

**Expected output:**
```bash
ℹ Checking for Airtag Scanner firmware...
✓ Airtag Scanner firmware found (via metadata)!
ℹ Airtag Scanner firmware is ready!

Connect to /dev/ttyACM0 at 9600 baud to see the output.
```

#### PuTTY Integration

For convenience, CatSniffer Tools includes automatic PuTTY integration that configures the serial terminal with the correct parameters.

**Command:**
```bash
python catsniffer.py sniff airtag_scanner --putty
```

**What happens:**
1. Verifies AirTag Scanner firmware is installed (flashes if needed)
2. Detects PuTTY installation on your system
3. Launches PuTTY with correct serial configuration:
   - Port: Detected CatSniffer bridge port
   - Baud rate: 9600
   - Data bits: 8
   - Parity: None
   - Stop bits: 1
   - Flow control: None

**Expected output:**
```bash
ℹ Checking for Airtag Scanner firmware...
✓ Airtag Scanner firmware found (via metadata)!
ℹ Opening PuTTY on /dev/ttyACM0 at 9600 baud...
✓ PuTTY launched successfully!
```

#### Cross-Platform Support

The `--putty` option works across different operating systems:

**Linux:**
```bash
# Install PuTTY if not already installed
sudo apt install putty

# Run AirTag Scanner
python catsniffer.py sniff airtag_scanner --putty
```

**macOS:**
```bash
# Install PuTTY via Homebrew
brew install putty

# Run AirTag Scanner
python catsniffer.py sniff airtag_scanner --putty
```

**Windows:**
```bash
# Download PuTTY from https://www.putty.org/
# Install to default location (C:\Program Files\PuTTY\)

# Run AirTag Scanner
python catsniffer.py sniff airtag_scanner --putty
```

#### Manual Serial Connection

If you prefer to use a different serial terminal (screen, minicom, etc.), you can connect manually:

**Using screen (Linux/macOS):**
```bash
# Start the firmware
python catsniffer.py sniff airtag_scanner

# In another terminal, connect with screen
screen /dev/ttyACM0 9600
```

**Using minicom (Linux):**
```bash
# Configure minicom
minicom -D /dev/ttyACM0 -b 9600
```

**Using Windows Serial Terminal:**
```bash
# Use any serial terminal (PuTTY, TeraTerm, etc.)
# Configure: COM port (check Device Manager), 9600 baud, 8N1
```

#### Practical Use Cases

**1. Privacy Audit**
```bash
python catsniffer.py sniff airtag_scanner --putty
```
Monitor for nearby AirTags to detect potential tracking devices in your environment.

**2. Research and Development**
```bash
python catsniffer.py sniff airtag_scanner
# Connect with your preferred serial tool for custom logging
```
Analyze the BLE advertising packets from AirTags and Find My devices.

**3. Multi-Device Monitoring**
```bash
# Terminal 1 - Device 1
python catsniffer.py sniff airtag_scanner --device 1 --putty

# Terminal 2 - Device 2
python catsniffer.py sniff airtag_scanner --device 2 --putty
```
Monitor different areas simultaneously with multiple CatSniffer devices.

#### Troubleshooting

**Problem: PuTTY not found**

**Error:**
```bash
✗ PuTTY not found! Make sure it is installed and in your PATH.
```

**Solution:**
- **Linux**: `sudo apt install putty`
- **macOS**: `brew install putty`
- **Windows**: Download from [putty.org](https://www.putty.org/) and install

**Problem: No output in serial terminal**

**Possible causes:**
- Incorrect baud rate (must be 9600)
- Wrong serial port selected
- Firmware not properly flashed

**Solutions:**
1. Verify the correct port:
   ```bash
   python catsniffer.py devices
   ```
2. Reflash the firmware:
   ```bash
   python catsniffer.py flash airtag-scanner
   ```
3. Verify firmware is active:
   ```bash
   python catsniffer.py verify
   ```

**Problem: Permission denied on serial port**

**Error:**
```bash
Permission denied: '/dev/ttyACM0'
```

**Solution (Linux):**
```bash
sudo usermod -a -G dialout $USER
# Log out and log back in
```

### Important Notes

> [!IMPORTANT]
> The AirTag Scanner firmware operates in a different mode than other sniffers. It does not create PCAP files or integrate with Wireshark. All output is displayed through the serial console.

> [!TIP]
> For automated logging, redirect the serial output to a file using your serial terminal's logging feature or tools like `screen -L`.


## IQ Activity Monitor (Cativity)

Cativity is a specialized tool for analyzing 802.15.4 networks (Zigbee and Thread) that provides real-time visualization of radio channel activity and network topology discovery.

### Fundamental Concepts

#### What is 802.15.4?

IEEE 802.15.4 is the physical and data link layer standard used by:
- **Zigbee**: Mesh network protocol for IoT (smart home, industrial automation)
- **Thread**: IPv6 over mesh networks (Google Nest, Matter)

#### 802.15.4 Channels

The standard defines 16 channels in the 2.4 GHz band:

| Channel | Center Frequency | Bandwidth |
|-------|-------------------|----------------|
| 11    | 2405 MHz          | 2 MHz          |
| 12    | 2410 MHz          | 2 MHz          |
| ...   | ...               | ...            |
| 26    | 2480 MHz          | 2 MHz          |

Cativity monitors all these channels to detect network activity.

### Command Help

```bash
python catsniffer.py cativity --help

Usage: catsniffer.py cativity [OPTIONS]

  IQ Activity Monitor

Options:
  -d, --device INTEGER    Device ID (for multiple CatSniffers)
  -c, --channel INTEGER   Fixed channel (11-26)
  -t, --topology          Show network topology
  -p, --protocol [all|zigbee|thread]
                          Protocol filter
  -h, --help              Show this message and exit.
```

### Operation Modes

#### 1. Channel Activity Monitoring (Default Mode)

This mode visualizes packet activity on all 802.15.4 channels through automatic channel hopping.

**Command:**
```bash
python3 catsniffer.py cativity
```

**Initialization Process:**
```bash
ℹ Checking for Sniffer TI firmware...
✓ Sniffer TI firmware found (via metadata)!
ℹ [CatSniffer #1] Starting Cativity analysis...
```

**Real-time Visualization:**

```bash
                    Channel Activity
┏━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Current ┃ Channel ┃ Activity                ┃ Packets ┃
┡━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│         │ 11      │                         │ 0       │
│         │ 12      │                         │ 0       │
│         │ 13      │                         │ 0       │
│         │ 14      │                         │ 0       │
│         │ 15      │ ❚❚                      │ 2       │
│         │ 16      │                         │ 0       │
│         │ 17      │                         │ 0       │
│         │ 18      │                         │ 0       │
│         │ 19      │ ❚                       │ 1       │
│         │ 20      │                         │ 0       │
│         │ 21      │ ❚                       │ 1       │
│         │ 22      │                         │ 0       │
│         │ 23      │                         │ 0       │
│         │ 24      │                         │ 0       │
│         │ 25      │ ❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚❚ │ 23      │
│ ---->   │ 26      │ ❚                       │ 1       │
└─────────┴─────────┴─────────────────────────┴─────────┘
                Channel Hopping Activity
```

**Interpretation:**
- **Current**: Indicates the channel currently being monitored (marked with ----->)
- **Channel**: 802.15.4 channel number (11-26)
- **Activity**: Graphical representation of traffic intensity (each ❚ represents activity)
- **Packets**: Cumulative packet count on that channel

**Example analysis**:
- **Channel 25**: High activity (23 packets) - possible active Zigbee network
- **Channel 15**: Moderate activity (2 packets)
- **Channels 19, 21, 26**: Minimal activity (1 packet each)
- **Other channels**: No detected activity

#### 2. Fixed Channel Mode

Continuously monitors a specific channel without hopping.

**Command:**
```bash
python3 catsniffer.py cativity --channel 15
```

**When to use:**
- When the target network's operating channel is known
- For detailed analysis of a specific channel
- To reduce packet loss from channel hopping

**Output:**
```bash
ℹ Checking for Sniffer TI firmware...
✓ Sniffer TI firmware found (via metadata)!
ℹ [CatSniffer #1] Starting Cativity analysis...
                    Channel Activity
┏━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Current ┃ Channel ┃ Activity                ┃ Packets ┃
┡━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ ---->   │ 25      │ ❚❚❚❚❚❚❚❚ (107) ❚❚❚❚❚❚❚❚ │ 107     │
└─────────┴─────────┴─────────────────────────┴─────────┘
                Channel Hopping Activity
```

#### 3. Network Topology Discovery

Builds a visual map of relationships between devices in the network.

**Command:**
```bash
python3 catsniffer.py cativity --topology
```

**Output:**

```bash

```

#### 4. Protocol Filter

Allows focusing on Zigbee or Thread traffic specifically.

**Zigbee Filter:**
```bash
python3 catsniffer.py cativity --protocol zigbee
```

**Thread Filter:**
```bash
python3 catsniffer.py cativity --protocol thread
```

**All protocols (default):**
```bash
python3 catsniffer.py cativity --protocol all
```

**Differentiation:**
- **Zigbee**: Identifies frames through the Application Support Layer protocol field
- **Thread**: Detects via presence of IPv6 headers and MLE (Mesh Link Establishment) characteristics

### Practical Examples

#### Example 1: Zigbee Network Audit

**Objective**: Identify all devices in a home Zigbee network

**Command:**
```bash
python3 catsniffer.py cativity --topology --protocol zigbee
```

**Result**: Complete network topology map with identified device types

#### Example 2: Interference Detection

Objective: Identify congested channels in a building with multiple networks

**Command:**
```bash
python3 catsniffer.py cativity
```

**Analysis**: Channels with longer activity bars have higher traffic/interference

#### Example 3: Deep Channel Analysis
**Objective**: Capture all traffic on channel 25 for later analysis

**Command**
```bash
python3 catsniffer.py cativity --channel 25 --protocol all
```

**Usage**: Keep running during the period of interest, packets are recorded for analysis

#### Example 4: Multi-Device Configuration
**Objective**: Monitor two channels simultaneously with two CatSniffers

**Terminal 1:**
```bash
python3 catsniffer.py cativity --device 1 --channel 15
```

**Terminal 2:**
```bash
python3 catsniffer.py cativity --device 2 --channel 25
```

**Result**: Parallel monitoring of two different channels

### Troubleshooting

**Problem: "No activity detected"**

**Possible causes:**
- 802.15.4 devices out of range
- Inactive network or in sleep mode
- Incorrect channel

**Solutions:**
- Move CatSniffer closer to known devices
- Activate Zigbee/Thread devices (turn on lights, open sensors)
- Try full scan mode without specifying channel


**Problem: "Topology not showing devices"**

**Possible causes:**
- Insufficient capture time
- Encrypted devices
- Network not transmitting beacons

**Solutions**:
- Let it run longer (minimum 2-5 minutes)
- Generate network traffic (activate devices)
- Use fixed channel mode on the network's main channel


**Problem: "Performance issues / Dropped packets"**

**Possible causes**:
- CPU overload
- Multiple applications accessing the serial port
- Hopping speed too fast

**Solutions**:
- Close unnecessary applications
- Use fixed channel mode: --channel <N>
- Increase dwell time per channel (modify configuration)


**Problem: "Firmware not found"**

**Error:**
```bash
✗ Sniffer TI firmware not detected
✗ Failed to flash firmware
```

**Solution:**

```bash
# Manually flash TI firmware
python catsniffer.py flash sniffer-ti

# Verify installation
python catsniffer.py verify

# Retry Cativity
python catsniffer.py cativity
```

---

## Wireshark Integration

CatSniffer V3 Tools provides native integration with Wireshark through the extcap (External Capture) plugin mechanism.

### What is Extcap?

Extcap is a Wireshark plugin interface that allows external tools to appear as native capture interfaces. This means CatSniffer can integrate directly into Wireshark's graphical interface without the need for intermediate processes.

### Extcap Plugin Installation

#### On Unix-like Systems (Linux, macOS)

**Step 1: Locate the Wireshark extcap directory**

```bash
# Typical location on Linux
~/.local/lib/wireshark/extcap/

# Typical location on macOS
~/Library/Application Support/Wireshark/extcap/
```

**Step 2: Create symbolic link**

```bash
# From the CatSniffer-Tools repository directory
ln -s ${PWD}/lora_extcap.py ~/.local/lib/wireshark/extcap/lora_extcap.py

# Give execution permissions
chmod +x ~/.local/lib/wireshark/extcap/lora_extcap.py
```

**Step 3: Verify installation**
```bash
# Restart Wireshark
# The plugin should appear in the capture interface list
```

### Integrated Capture Workflow

**Complete example with BLE:**

```bash
# Terminal 1: Start capture
python catsniffer.py sniff ble --wireshark -c 37 -m passive_scan
```

**What happens internally:**

1. **Firmware verification**: If Sniffle is not installed, it is flashed automatically
2. **PCAP pipe creation**: `/tmp/fcatsniffer` is created as a named pipe
3. **Sniffer configuration**: BLE channel and mode are configured
4. **Wireshark launch**: Wireshark is executed pointing to the pipe
5. **Packet streaming**: Captured packets flow in real-time to Wireshark

**Advantages of integrated workflow:**

- **Real-time analysis**: View packets as they are captured
- **Wireshark filters**: Apply complex display filters
- **Export**: Save captures in .pcap format for later analysis
- **Advanced dissectors**: Leverage Wireshark's dissectors for BLE, 802.15.4, etc.

### Current Limitations

- **Multiple instances**: Running multiple simultaneous Wireshark captures on the same machine is not recommended
- **Permissions**: May require elevated permissions depending on system configuration

---

## Common Problem Solving

### Problem: Pipeline Already Exists

**Error:**
```bash
[-] Pipeline already exists.
```

**Cause:** A previous sniffing session did not close properly, leaving the PCAP pipe active.

**Solution on Unix-like:**
```bash
rm /tmp/fcatsniffer
```

**Prevention**: Always end sniffing sessions with Ctrl+C and wait for the process to clean up resources.

### Problem: Permission Denied on Serial Ports

**Error:**
```bash
[-] Error: Permission denied accessing /dev/ttyACM0
```

**Permanent solution on Linux:**
```bash
sudo usermod -a -G dialout $USER
sudo usermod -a -G uucp $USER  # On some systems
# Log out and log back in
```

**Temporary solution:**
```bash
sudo chmod 666 /dev/ttyACM*
```

### Problem: Device Not Detected

**Symptom**: `python catsniffer.py devices` shows no devices.

**Diagnostic checklist:**

1. **Check physical USB connection**
```bash
lsusb  # On Linux
system_profiler SPUSBDataType  # On macOS
```
Look for "Electronic Cats" or "CatSniffer"

2. **Check drivers**
- On Windows: Install CH340 or CP210x USB-Serial drivers
- On Linux/macOS: Drivers included in modern kernel

3. **Check permissions**
```bash
ls -l /dev/ttyACM*  # Check permissions
groups  # Verify you are in dialout group
```

4. **Try another USB port**
- Some USB ports may have power issues
- Prefer direct USB ports over hubs

### Problem: Flash Verification Failed

**Error:**

```bash
[-] Error: Flash verification mismatch
```

**Resolution steps:**

1. **Retry flashing**

  ```bash
  python catsniffer.py flash <firmware>
  ```

2. **Verify firmware integrity**
  ```bash
  python catsniffer.py flash --list
  # Verify checksums are "VERIFIED"
  ```

3. **Re-download firmware**
  ```bash
  # Delete releases directory
  rm -rf release_board-v3.x-*
  # Restart tool to re-download
  python catsniffer.py
  ```

4. **Try different USB cable**
- Poor quality cables can cause transmission errors

### Problem: Wireshark Shows No Packets

**Symptoms**: Wireshark open but no packets appearing.

**Diagnosis**:

1. **Check PCAP pipe**
   ```bash
   ls -l /tmp/fcatsniffer
   # Must exist and be a pipe (type p)
   ```
2. **Check capture process**
   ```bash
   ps aux | grep catsniffer
   # There should be an active Python process
   ```

3. **Review Wireshark configuration**
- For LoRa: Verify DLT_USER configured correctly
- For BLE: Verify Wireshark has Sniffle dissector

4. Test capture without Wireshark

  ```bash
  # Terminal 1
  python catsniffer.py sniff ble -c 37 -m passive_scan

  # Terminal 2
  cat /tmp/fcatsniffer | tcpdump -r -
  ```

### Problem: Cativity Shows No Activity

**Symptoms**: All channels show 0 packets.

**Solutions**:

1. **Verify proximity to 802.15.4 devices**
   - Move CatSniffer closer to known Zigbee/Thread devices

2. **Activate network traffic**
   - Turn on/off Zigbee lights
   - Activate Thread sensors
   - Open/close door/window sensors

3. **Verify firmware**
   ```bash
   python catsniffer.py verify
   # Confirm TI Sniffer firmware is active
   ```

4. **Try known specific channel**
   ```bash
   python catsniffer.py cativity --channel 15  # Common Zigbee channel
   python catsniffer.py cativity --channel 25  # Common Thread channel
   ```

---

## Contributions and Support

### How to Contribute

Contributions to the project are welcome. Please visit the official repository:

**GitHub**: [https://github.com/ElectronicCats/CatSniffer-Tools](https://github.com/ElectronicCats/CatSniffer-Tools)


### Report Issues

To report bugs or request features:

1. Visit the [Issues](https://github.com/ElectronicCats/CatSniffer-Tools/issues) section
2. Check if the problem has already been reported
3. Create a new issue with detailed information:
   1. CatSniffer Tools version
   2. Operating system and version
   3. Steps to reproduce the problem
   4. Error logs (if applicable)

### Additional Resources
- **Project Wiki**: [CatSniffer Wiki](https://github.com/ElectronicCats/CatSniffer/wiki)
- **Hardware Documentation**: CatSniffer V3 technical specifications
- **Community Forum**: Discussions and community support
- **Electronic Cats**: [https://electroniccats.com](https://electroniccats.com)

---

## License
This project is licensed under the terms specified in the official repository. Check the LICENSE file for more details.

---

## Credits

- **Developed by**: Electronic Cats - PWNLAB
- **Version**: 3.0.0
- **Last Updated**: 2026
