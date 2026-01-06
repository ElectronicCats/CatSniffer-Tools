# CatSniffer V2 Tools – User Guide
> Current version: v2.0.1
## Overview

This new version of CatSniffer Tools is designed as a unified environment that combines all existing tools into a single workflow.

Instead of maintaining multiple standalone scripts, all functionality is now exposed through one main script, allowing you to manage firmware, flashing, and protocol sniffing from a single entry point.

## Features

- All-in-One CatSniffer Environment: Single unified CLI that replaces multiple standalone scripts, simplifying firmware management, flashing, and protocol sniffing.
- Automatic Firmware Management: Automatically detects, downloads, verifies (SHA256), and updates firmware releases from the official repository.
- Automatic Device Detection: Detects connected CatSniffer devices automatically, with optional manual port selection for multi-device setups.
- Multi-Protocol Sniffing:
  - LoRa (SX1262)
  - Zigbee
  - Thread
  - BLE (via Sniffle and TI firmware)
- On-Demand Firmware Flashing: Automatically flashes the required firmware if it is not detected before starting a sniffing session.
- Wireshark Integration (Extcap): Native extcap support for live captures directly inside Wireshark, including custom dissectors.
- Cross-Platform Support: Compatible with Linux, macOS, and Windows.

## Installation

### Global install
If you want to use this tool in your global context running just `catsniffer` without navigate throught the repo.
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
source .venv/bin/activate
pip install -r requirements.txt
```

## Getting Started

When starting from a clean environment, the tool automatically downloads the latest firmware releases from the official repository.
```bash
python3 catsniffer.py
```

Example output:
```bash
[10:20:29] [*] Looking for local releases
           [*] No Local release folder found!
           [*] Local release folder created: /Users/astrobyte/ElectronicCats/CatSniffer-Tools/envcat/release_board-v3.x-v1.2.2
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

Commands:
  cativity  IQ Activity Monitor
  flash     Flash firmware
  releases  Show Firmware releases
  sniff     Sniffer protocol control
```

---


## Release Management

The script creates a metadata file inside the release folder.
This file stores the timestamp of the last release check.

On each execution:
- The timestamp is compared with the repository state
- If a newer release is available, the tool automatically queries GitHub and downloads updated firmware

To list available firmware releases:

```bash
python3 catsniffer.py releases
```

Example output:

```bash
Current Release board-v3.x-v1.2.2 - 2025-06-09T22:07:38Z
```

A table is displayed with all supported firmware, target microcontrollers, and descriptions.

---

## Flashing Firmware (CC1352)

The script automatically detects the connected CatSniffer device.
If more than one device is connected, you can manually specify the serial port using -p.

### Flash Command Help
```bash
electronic@cats> python3 catsniffer.py flash --help

Usage: catsniffer.py flash [OPTIONS] FIRMWARE

Options:
  -f, --firmware TEXT  Firmware name or full path
  -p, --port TEXT      CatSniffer serial port
```
### Flashing a Firmware Image

Firmware can be flashed using its short name:

```bash
python3 catsniffer.py flash sniffle
```

Example flashing process:

```bash
[*] Flashing firmware: sniffle
[*] Opening port /dev/cu.usbmodem2123401 at baud: 500000
[*] Performing mass erase
[*] Write done
[*] Verified match: 0x6d6c64a5
```

### Flashing Errors and Recovery

If flashing fails due to synchronization issues, you may see the following error:
```bash
[X] Please reset your board manually, disconnect and reconnect or press the RESET_CC1 and RESET1 buttons.
Error: Timeout waiting for ACK/NACK after 'Synch'
```

In this case:
1. Manually reset the board
2. Disconnect and reconnect the device
3. Retry the flashing command

---

## Sniffing Protocols

Sniffing is initiated by specifying the protocol name.
If the required firmware is not detected, the tool automatically flashes the appropriate firmware before starting the sniffer.

```bash

      :-:              :--       |
      ++++=.        .=++++       |
      =+++++===++===++++++       |
      -++++++++++++++++++-       |  Module:  Catsniffer
 .:   =++---++++++++---++=   :.  |  Author:  JahazielLem
 ::---+++.   -++++-   .+++---::  |  Version: 2.0.1
::1..:-++++:   ++++   :++++-::.::|  Company: Electronic Cats - PWNLab
.:...:=++++++++++++++++++=:...:. |
 :---.  -++++++++++++++-  .---:  |
 ..        .:------:.        ..  |


Usage: catsniffer sniff [OPTIONS] COMMAND [ARGS]...

  Sniffer protocol control

Options:
  --verbose  Show Verbose mode
  --help     Show this message and exit.

Commands:
  ble     Sniffing BLE with Sniffle firmware
  lora    Sniffing LoRa with Sniffer SX1262 firmware
  thread  Sniffing Thread with Sniffer TI firmware
  zigbee  Sniffing Zigbee with Sniffer TI firmware
```

### LoRa Sniffing
```bash
python3 catsniffer.py sniff lora --help
```

Available options include frequency, bandwidth, spreading factor, sync word, preamble length and coding rate.

#### Example configuration:
```bash
python3 catsniffer.py sniff lora -freq 916 -bw 8 -sf 11 -p /dev/tty.usbmodem101 -ws
```

> The **-p** option is only required when multiple CatSniffer devices are connected.

### Zigbee Sniffing
```bash
python3 catsniffer.py sniff zigbee -c 25 -p /dev/tty.usbmodem2123401
```

The tool automatically creates a named pipe for packet forwarding:
```bash
[*] Pipeline created: /tmp/fcatsniffer
```

### Thread Sniffing
```bash
python3 catsniffer.py sniff thread -c 25 -p /dev/tty.usbmodem2123401
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
