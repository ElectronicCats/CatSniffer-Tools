#!/bin/bash
# Catsniffer Build, Flash, and Verify Script
# Cross-platform: macOS and Linux
# Automatically sends 'reboot' command to enter bootloader

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
UF2_FILE="$PROJECT_DIR/build/zephyr/zephyr.uf2"

# Detect OS and set paths
if [[ "$OSTYPE" == "darwin"* ]]; then
    MOUNT_POINT="/Volumes/RPI-RP2"
    SERIAL_PATTERN="/dev/cu.usbmodem*"
elif [[ "$OSTYPE" == "linux"* ]]; then
    MOUNT_POINT="/media/$USER/RPI-RP2"
    SERIAL_PATTERN="/dev/ttyACM*"
else
    echo "ERROR: Unsupported OS: $OSTYPE"
    exit 1
fi

echo "=== Catsniffer Build & Flash ==="
echo "Platform: $OSTYPE"
cd "$PROJECT_DIR"

# Step 1: Build
echo ""
echo "[1/4] Building firmware..."
source ~/zephyrproject/.venv/bin/activate
export ZEPHYR_BASE=$HOME/zephyrproject/zephyr
west build -p always -b rpi_pico

if [ ! -f "$UF2_FILE" ]; then
    echo "ERROR: Build failed - $UF2_FILE not found"
    exit 1
fi
echo "Build successful: $(ls -lh "$UF2_FILE" | awk '{print $5}')"

# Step 2: Find Shell port and send reboot command
echo ""
echo "[2/4] Finding Shell port and sending reboot..."

# Find Shell port (last of the 3 CDC ports by convention)
SHELL_PORT=$(ls $SERIAL_PATTERN 2>/dev/null | sort | tail -1)

if [ -n "$SHELL_PORT" ]; then
    echo "      Sending 'reboot' to $SHELL_PORT"
    echo "reboot" > "$SHELL_PORT" 2>/dev/null || true
    sleep 1
else
    echo "      No device found. Hold BOOTSEL and plug USB..."
fi

# Step 3: Wait for RPI-RP2 and flash
echo ""
echo "[3/4] Waiting for RPI-RP2 drive..."

TIMEOUT=30
ELAPSED=0
while [ ! -d "$MOUNT_POINT" ]; do
    sleep 1
    ELAPSED=$((ELAPSED + 1))
    if [ $ELAPSED -ge $TIMEOUT ]; then
        echo "ERROR: Timeout waiting for $MOUNT_POINT"
        echo "       Try: hold BOOTSEL and plug USB manually"
        exit 1
    fi
    printf "\r      Waiting... %ds" $ELAPSED
done

echo ""
echo "      Found $MOUNT_POINT, copying..."
cp "$UF2_FILE" "$MOUNT_POINT/"
echo "      Flashed!"

# Step 4: Wait for device to reboot and verify
echo ""
echo "[4/4] Waiting for device to reboot..."
sleep 3

# Wait for serial ports to appear
TIMEOUT=15
ELAPSED=0
while [ $(ls $SERIAL_PATTERN 2>/dev/null | wc -l) -lt 3 ]; do
    sleep 1
    ELAPSED=$((ELAPSED + 1))
    if [ $ELAPSED -ge $TIMEOUT ]; then
        echo "ERROR: Device did not enumerate properly"
        exit 1
    fi
done

# Run verification
echo ""
echo "=== Running Verification ==="

# Wait a bit for ports to stabilize
sleep 5

# Verify Shell port is responsive
echo "Verifying Shell port is ready..."
SHELL_PORT=$(ls $SERIAL_PATTERN 2>/dev/null | sort | tail -1)
if [ -n "$SHELL_PORT" ]; then
    # Send a newline and wait for prompt
    for i in {1..5}; do
        echo "" > "$SHELL_PORT" 2>/dev/null || true
        sleep 1
    done
fi

python3 "$SCRIPT_DIR/verify_endpoints.py"

echo ""
echo "=== Done ==="
