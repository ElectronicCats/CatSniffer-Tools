#!/bin/bash
set -e

# Prerequisites (macOS): native libraries must be installed before running this script.
#   brew install libusb libmagic
# In CI these are installed by the GitHub Actions workflow before this script is called.
# Note: openocd is NOT a build prerequisite — it is installed on the end user's machine
# via the postinstall script bundled in the .pkg (packaging/macos/scripts/postinstall).

echo "[*] Installing Python dependencies..."
pip install -r requirements.txt

echo "[*] Installing PyInstaller..."
pip install pyinstaller

echo "[*] Building catnip..."
pyinstaller \
  --onedir \
  --noupx \
  --name catnip \
  --collect-all scapy \
  --collect-all textual \
  --collect-all meshtastic \
  --collect-all rich \
  --collect-all matplotlib \
  --collect-all cryptography \
  --collect-all serial \
  --hidden-import click \
  --hidden-import usb \
  --hidden-import usb.backend.libusb1 \
  --hidden-import magic \
  catnip.py

echo "[*] Building lora_extcap..."
pyinstaller \
  --onedir \
  --noupx \
  --name lora_extcap \
  --collect-all scapy \
  --collect-all meshtastic \
  --collect-all rich \
  --collect-all cryptography \
  --collect-all serial \
  --hidden-import usb \
  --hidden-import usb.backend.libusb1 \
  lora_extcap.py

echo "[+] Verifying binaries..."
test -f dist/catnip/catnip       || { echo "[!] ERROR: dist/catnip/catnip not found";             exit 1; }
test -f dist/lora_extcap/lora_extcap || { echo "[!] ERROR: dist/lora_extcap/lora_extcap not found"; exit 1; }
ls -lh dist/catnip/catnip dist/lora_extcap/lora_extcap

echo "[*] Creating macOS Package (.pkg)..."
# Define packaging directory structure
PKG_ROOT="pkg_root"
INSTALL_LOCATION="/usr/local/opt/catnip"
BIN_DIR="/usr/local/bin"

mkdir -p "${PKG_ROOT}${INSTALL_LOCATION}"
mkdir -p "${PKG_ROOT}${BIN_DIR}"

# Copy binaries and their dependencies (PyInstaller --onedir output)
cp -R dist/catnip "${PKG_ROOT}${INSTALL_LOCATION}/"
cp -R dist/lora_extcap "${PKG_ROOT}${INSTALL_LOCATION}/"

# Create symlinks in /usr/local/bin
ln -sf "${INSTALL_LOCATION}/catnip/catnip" "${PKG_ROOT}${BIN_DIR}/catnip"
ln -sf "${INSTALL_LOCATION}/lora_extcap/lora_extcap" "${PKG_ROOT}${BIN_DIR}/lora_extcap"

VERSION=$(cat VERSION | tr -d '[:space:]')
if [ -z "$VERSION" ]; then
  VERSION="1.0.0"
fi

IDENTIFIER="com.electroniccats.catsniffer"

pkgbuild --root "${PKG_ROOT}" \
         --identifier "${IDENTIFIER}" \
         --version "${VERSION}" \
         --install-location "/" \
         --scripts "packaging/macos/scripts" \
         "catnip-${VERSION}.pkg"

echo "[+] Build successful. Installer created: catnip-${VERSION}.pkg"
