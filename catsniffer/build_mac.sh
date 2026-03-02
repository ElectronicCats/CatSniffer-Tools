#!/bin/bash
set -e

echo "[*] Installing PyInstaller..."
pip install pyinstaller

echo "[*] Building catsniffer..."
pyinstaller \
  --onefile \
  --name catsniffer \
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
  catsniffer.py

echo "[*] Building lora_extcap..."
pyinstaller \
  --onefile \
  --name lora_extcap \
  --collect-all scapy \
  --collect-all meshtastic \
  --collect-all rich \
  --collect-all cryptography \
  --collect-all serial \
  --hidden-import usb \
  --hidden-import usb.backend.libusb1 \
  lora_extcap.py

echo "[+] Done! Binaries are in dist/"
ls -lh dist/catsniffer dist/lora_extcap
