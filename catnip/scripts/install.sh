#!/bin/bash

# CatSniffer Post-Installation Script
# Purpose: Create a symlink in /usr/local/bin to ensure catnip is accessible by sudo.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}[*] CatSniffer Post-Installation Hook${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[!] Please run as root (sudo ./install.sh)${NC}"
  exit 1
fi

# Detect catnip location
if [ -n "$1" ]; then
    CATNIP_PATH="$1"
else
    CATNIP_PATH=$(runuser -u "$SUDO_USER" -- which catnip 2>/dev/null || which catnip)
fi

if [ -z "$CATNIP_PATH" ]; then
    # Try to find it in common user paths if not in PATH
    USER_HOME=$(eval echo "~$SUDO_USER")
    if [ -f "$USER_HOME/.local/bin/catnip" ]; then
        CATNIP_PATH="$USER_HOME/.local/bin/catnip"
    fi
fi

if [ -z "$CATNIP_PATH" ]; then
    echo -e "${RED}[-] Could not find 'catnip' command. Please install the package first with 'pip install .'${NC}"
    exit 1
fi

echo -e "${BLUE}[*] Found catnip at: $CATNIP_PATH${NC}"

# Create symlink in /usr/local/bin (usually in sudo secure_path)
TARGET="/usr/local/bin/catnip"

if [ -L "$TARGET" ] || [ -f "$TARGET" ]; then
    echo -e "${BLUE}[*] Removing existing catnip link/binary in $TARGET...${NC}"
    rm -f "$TARGET"
fi

echo -e "${BLUE}[*] Creating global symlink...${NC}"
ln -s "$CATNIP_PATH" "$TARGET"

echo -e "${GREEN}[+] catnip is now globally accessible, including via sudo!${NC}"
echo -e "${GREEN}[+] Try running: sudo catnip devices${NC}"
