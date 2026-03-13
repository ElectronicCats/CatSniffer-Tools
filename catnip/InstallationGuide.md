# Catnip Installation Guide

Welcome to the CatSniffer Tools (catnip) installation guide! This document provides step-by-step instructions for installing the CatSniffer multi-protocol sniffer and analysis tool on Windows, macOS, and Linux.

# Table of Contents
- [Catnip Installation Guide](#catnip-installation-guide)
- [Table of Contents](#table-of-contents)
  - [Windows Installation](#windows-installation)
    - [System Requirements](#system-requirements)
    - [Installation Steps](#installation-steps)
    - [Using Catnip on Windows](#using-catnip-on-windows)
  - [MacOS Installation](#macos-installation)
    - [System Requirements](#system-requirements-1)
      - [For Intel Macs(x86\_64)](#for-intel-macsx86_64)
      - [For Apple Silicon Macs (ARM64)](#for-apple-silicon-macs-arm64)
    - [Post-Installation (macOS)](#post-installation-macos)
  - [Linux Installation](#linux-installation)
    - [Debian/Ubuntu (.deb)](#debianubuntu-deb)
      - [System Requirements](#system-requirements-2)
      - [Installation Steps](#installation-steps-1)
    - [Arch Linux (.pkg.tar.zst)](#arch-linux-pkgtarzst)
      - [System Requirements](#system-requirements-3)
      - [Installation from Package](#installation-from-package)
      - [Installation from AUR](#installation-from-aur)
  - [Install from Source (All Linux Distributions)](#install-from-source-all-linux-distributions)
  - [Post Installation (Linux/macOs)](#post-installation-linuxmacos)
    - [1. Environment Setup (Linux/macOS)](#1-environment-setup-linuxmacos)
    - [2. Verify USB Connection](#2-verify-usb-connection)
    - [3. Shell Completion (Optional)](#3-shell-completion-optional)
  - [Verifying Installation](#verifying-installation)
    - [Run Basic Verification](#run-basic-verification)
    - [Test Different Protocols](#test-different-protocols)
    - [VHCI Bridge (Linux Only)](#vhci-bridge-linux-only)
  - [Troubleshooting](#troubleshooting)
    - [Windows Issues](#windows-issues)
    - [macOS Issues](#macos-issues)
    - [Linux Issues](#linux-issues)
    - [Common Issues Across Platforms](#common-issues-across-platforms)
  - [Uninstallation](#uninstallation)
    - [Windows](#windows)
    - [macOS](#macos)
    - [Linux (Debian/Ubuntu)](#linux-debianubuntu)
    - [Linux (Arch)](#linux-arch)

---

## Windows Installation

### System Requirements

- Windows 10 or Windows 11 (64-bit)
- Administrator privileges for driver installation
- At least 100 MB free disk space

### Installation Steps

1. **Download the installer**
   1. Download th latest `CatSniffer-Setup.exe` from the [Releases page](https://github.com/ElectronicCats/catsniffer-tools/releases)
2. **Run the Installer**
   1. Right click the installer and select **"Run as administrator"**
   2. Click "Yes" when prompted by User Account Control
3. **Follow the Installation Wizard**
   1. Select your preferred language
   2. Choose the installation directory (default: `C:\Program Files\Catnip`)
   3. Select components to install (all recommended)
   4. Click "Install"
4. **Driver Installation**
   1. The installer will automatically install the required USB drivers
   2. If prompted, confirm the driver installation
5. **Complete Installation**
   1. Click "Finish" to exit the installer
   2. Catnip will be available in your Start Menu

### Using Catnip on Windows

- Open Command Prompt or PowerShell and type:
  ```bash
  catnip --help
  ```

---

## MacOS Installation

### System Requirements

- macOS 11 (Big Sur) or newer
- Intel or Apple Silicon (M1, M2, M3) Mac
- At least 100 MB free disk space

Download the correct file.

You need to verify the architecture of your MAC with the command

```bash
uname -m
```

**Output Expected**

```bash
- "arm64" = Apple Silicon (M1/M2/M3)
- "x86_64" = Intel
```

#### For Intel Macs(x86_64)
```bash
# Download the Intel package
curl -LO https://github.com/ElectronicCats/catsniffer-tools/releases/download/latest/catnip-3.3.0.0-x86_64.pkg

# Install the package
sudo installer -allowUntrusted -pkg catnip-3.3.0.0-x86_64.pkg -target /
```

#### For Apple Silicon Macs (ARM64)

```bash
# Download the ARM64 package
curl -LO https://github.com/ElectronicCats/catsniffer-tools/releases/download/latest/catnip-3.3.0.0-arm64.pkg

# Install the package
sudo installer -allowUntrusted -pkg catnip-3.3.0.0-arm64.pkg -target /
```

### Post-Installation (macOS)
After installation, you may need to:

```bash
# Add your user to the necessary groups
sudo dseditgroup -o edit -a $(whoami) -t user dialout

# Install udev-like rules (for serial port access)
sudo catnip setup-env
```

---

## Linux Installation

### Debian/Ubuntu (.deb)

#### System Requirements
- Debian 11+ or Ubuntu 20.04+
- `sudo` privileges
- At least 100 MB free disk space


#### Installation Steps

```bash
# Download the .deb package
wget https://github.com/ElectronicCats/catsniffer-tools/releases/download/latest/catnip-3.3.0.0.deb

# Install the package
sudo dpkg -i catnip-3.3.0.0.deb

# Install dependencies (if any are missing)
sudo apt-get install -f

# Verify installation
catnip --version
```

### Arch Linux (.pkg.tar.zst)

#### System Requirements
- Arch Linux (or derivates like manjaro)
- `sudo`privileges
- Base-devel packafe group (for building from source)

#### Installation from Package

```bash
# Download the package
wget https://github.com/ElectronicCats/catsniffer-tools/releases/download/latest/catnip-3.3.0.0.pkg.tar.zst

# Install the package
sudo pacman -U catnip-3.3.0.0.pkg.tar.zst

# Verify installation
catnip --version
```

#### Installation from AUR
If you prefer using an AUR helper:

```bash
# Using yay
yay -S catnip

# Using paru
paru -S catnip
```

## Install from Source (All Linux Distributions)

```bash
# Clone the repository
git clone https://github.com/ElectronicCats/catsniffer-tools.git
cd catsniffer-tools/catnip

# Install system dependencies
# Debian/Ubuntu:
sudo apt-get update
sudo apt-get install python3 python3-pip python3-venv libusb-1.0-0 libmagic1

# Arch Linux:
sudo pacman -S python python-pip python-virtualenv libusb file

# Create and activate virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Install the package in development mode
pip install -e .

# Make the script executable
chmod +x catnip.py

# Create a symlink (optional)
sudo ln -s $(pwd)/catnip.py /usr/local/bin/catnip
```

## Post Installation (Linux/macOs)
### 1. Environment Setup (Linux/macOS)

Run the setup command to configure udev rules and user permissions:

```bash
# Linux (requires sudo)
sudo catnip setup-env

# macOS
sudo catnip setup-env
```

This command will
- Install udev rules for CatSniffer devices
- Add your user to the `dialout` and `bluetooth` groups
- Configure permissions for serial ports

**Important:** Log out and log back in for group changes to take effect.

### 2. Verify USB Connection

Connect your CatSniffer device via USB and check if it's detected:

```bash
# List connected devices
catnip devices
```

Expected output:

```
                          Found 1 CatSniffer device(s)
╭───────────────┬─────────────────────┬───────────────────┬────────────────────╮
│ Device        │ Cat-Bridge (CC1352) │ Cat-LoRa (SX1262) │ Cat-Shell (Config) │
├───────────────┼─────────────────────┼───────────────────┼────────────────────┤
│ CatSniffer #1 │ /dev/ttyACM0        │ /dev/ttyACM1      │ /dev/ttyACM2       │
╰───────────────┴─────────────────────┴───────────────────┴────────────────────╯
```

### 3. Shell Completion (Optional)
Install tab completion for tour shell:

```bash
# Auto-detect and install completion
catnip completion install

# Or specify shell explicitly
catnip completion install --shell bash
catnip completion install --shell zsh
catnip completion install --shell fish
```

Restart your terminal of source your shell configuration file.

## Verifying Installation

### Run Basic Verification

```bash
# Test basic functionality
catnip verify

# For comprehensive testing (includes LoRa)
catnip verify --test-all
```

### Test Different Protocols

```bash
# Check BLE sniffer
catnip sniff ble --help

# Check Zigbee sniffer
catnip sniff zigbee --help

# Check Meshtastic tools
catnip meshtastic --help
```

### VHCI Bridge (Linux Only)

```bash
# Check VHCI prerequisites
catnip vhci check

# Load kernel module
sudo modprobe hci_vhci

# Start VHCI bridge
catnip vhci start
```

---

## Troubleshooting

### Windows Issues

**Driver Installation Fails**
- Run installer as Administrator
- Disable driver signature enforcement temporarily
- Install drivers manually from `C:\Program Files\Catnip\drivers`

**Serial Port Not Detected**
- Check Device Manager for "CatSniffer" under Ports (COM & LPT)
- Try a different USB cable or port
- Update USB controllers drivers

### macOS Issues
**"Cannot be opened because the developer cannot be verified"**
- Go to System Preferences → Security & Privacy
- Click "Open Anyway" for the blocked application
- Or run: `sudo spctl --master-disable` (temporarily)

**Permission Denied for Serial Port**
```bash
# Add user to dialout group
sudo dseditgroup -o edit -a $(whoami) -t user dialout
# Log out and log back in
```

### Linux Issues

**Permission Denied for /dev/ttyACM***
```bash
# Add user to dialout group
sudo usermod -a -G dialout $USER
# Log out and log back in
```

**"Module hci_vhci not found"**
```bash
# Install kernel module
sudo modprobe hci_vhci

# Add user to bluetooth group
sudo usermod -a -G bluetooth $USER

# Make permanent
echo "hci_vhci" | sudo tee -a /etc/modules
```

**udev Rules Not Working**
```bash
# Reload udev rules
sudo udevadm control --reload-rules
sudo udevadm trigger

# Check if rules are applied
ls -la /dev/ttyACM*
```

### Common Issues Across Platforms
**"No CatSniffer device found"**
- Ensure device is connected via USB
- Try a different USB cable
- Check if device is in bootloader mode (hold BOOT button while connecting)
- Run catnip devices to list available devices

**Firmware Flashing Fails**
```bash
# Force firmware update
catnip update --force

# Flash specific firmware manually
catnip flash --list  # List available firmware
catnip flash ble     # Flash BLE firmware
```

---

## Uninstallation
### Windows
Go to Settings → Apps → CatSniffer → Uninstall

Or run the installer again and select "Remove"

### macOS

```bash
# Remove package receipts
sudo pkgutil --forget com.electroniccats.catnip

# Delete installed files
sudo rm -rf /usr/local/bin/catnip
sudo rm -rf /usr/local/lib/python3.*/dist-packages/catnip/
sudo rm -rf /usr/local/lib/python3.*/dist-packages/protocol/
```

### Linux (Debian/Ubuntu)
```bash
sudo dpkg -r catnip
```

### Linux (Arch)

```bash
sudo pacman -R catnip
```
