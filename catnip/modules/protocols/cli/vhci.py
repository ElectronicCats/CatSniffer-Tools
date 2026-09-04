"""``catnip vhci`` - expose the CatSniffer as an ``hciX`` interface."""

# Internal
from ...firmware.flasher import Flasher
from ...core.catnip import Catnip, catnip_get_device, catnip_get_devices

# External
import click
import logging
import os
import sys
import time
from rich.logging import RichHandler

from ...utils.cli_options import device_option
from ...utils.output import (
    console,
    print_success,
    print_warning,
    print_error,
    print_info,
    print_dim,
    print_empty_line,
)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def vhci():
    """VHCI Bridge - Expose CatSniffer as hciX.

    Requires sudo and the hci_vhci kernel module.

    \b
        sudo modprobe hci_vhci
        sudo python3 catnip.py vhci start
    """
    pass


@vhci.command("start")
@device_option()
@click.option(
    "--baud",
    default=2000000,
    type=int,
    show_default=True,
    help="Baud rate for serial port",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose (DEBUG) logging")
def vhci_start(device, baud, verbose):
    """Start the VHCI bridge — CatSniffer appears as hciX.

    Requires root privileges and the hci_vhci kernel module:

    \b
        sudo modprobe hci_vhci
        sudo catnip vhci start
        hciconfig -a

    Compatible tools: bluetoothctl, btmgmt, btmon, bleak, bettercap.
    """
    import signal
    from ..vhci import VHCIBridge

    if os.geteuid() != 0 and not os.access("/dev/vhci", os.R_OK | os.W_OK):
        print_warning(
            "Insufficient permissions for /dev/vhci access. Try running with sudo or check group membership."
        )

    if not os.path.exists("/dev/vhci"):
        print_error("/dev/vhci not found. Load the kernel module first:")
        print_dim("sudo modprobe hci_vhci")
        sys.exit(1)

    # Resolve device
    if device is not None:
        dev = catnip_get_device(device)
        if dev is None:
            print_error(f"CatSniffer device #{device} not found.")
            sys.exit(1)
        if not dev.bridge_port:
            print_error(f"Device #{device} has no Cat-Bridge port detected.")
            sys.exit(1)
        print_info(f"Using device {dev}, port: {dev.bridge_port}")
    else:
        devs = catnip_get_devices()
        if devs and devs[0].bridge_port:
            dev = devs[0]
            print_info(f"Auto-detected CatSniffer: {dev}, port: {dev.bridge_port}")
        else:
            print_error("CatSniffer not found. Connect a device or specify -d.")
            sys.exit(1)

    # Firmware check
    cat = Catnip(dev.bridge_port)
    print_info("Checking for Sniffle firmware...")
    if cat.check_firmware_by_metadata("sniffle", dev.shell_port):
        print_success("Sniffle firmware found!")
    else:
        print_warning("Sniffle firmware not found — flashing now...")
        flasher = Flasher()
        if not flasher.find_flash_firmware("sniffle", dev):
            print_error("Failed to flash Sniffle firmware. Aborting.")
            sys.exit(1)
        print_info("Waiting for device to initialize...")
        time.sleep(1)
        if cat.check_firmware_by_metadata("sniffle", dev.shell_port):
            print_success("Sniffle firmware verified!")
        else:
            print_warning("Firmware verification failed, continuing anyway...")

    # Logging
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_time=False)],
    )
    log = logging.getLogger("vhci")

    bridge = VHCIBridge(dev.bridge_port, log)

    def _shutdown(sig, frame):
        print_warning("Shutting down VHCI bridge...")
        bridge.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        bridge.start()
    except Exception as e:
        print_error(f"Failed to start bridge: {e}")
        sys.exit(1)

    print_success("Bridge running. Device should appear as hciX.")
    print_dim("Check with: hciconfig -a   |   Press Ctrl+C to stop")

    try:
        bridge.run()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()


@vhci.command("check")
def vhci_check():
    """Check VHCI bridge prerequisites (kernel module, /dev/vhci, root, packages)."""
    import subprocess as _sp

    all_ok = True

    # Permissions check
    if os.access("/dev/vhci", os.R_OK | os.W_OK):
        print_success("  permissions  : OK (access to /dev/vhci)")
    elif os.geteuid() == 0:
        print_success("  root         : OK")
    else:
        print_warning(
            "  permissions  : Insufficient — bridge may fail to open /dev/vhci"
        )
        all_ok = False

    # Kernel module
    try:
        result = _sp.run(["lsmod"], capture_output=True, text=True, timeout=5)
        if "hci_vhci" in result.stdout:
            print_success("  hci_vhci     : loaded")
        else:
            print_warning("  hci_vhci     : NOT loaded — run: sudo modprobe hci_vhci")
            all_ok = False
    except Exception:
        print_error("  hci_vhci     : could not run lsmod")
        all_ok = False

    # /dev/vhci
    if os.path.exists("/dev/vhci"):
        print_success("  /dev/vhci    : exists")
    else:
        print_warning("  /dev/vhci    : missing — run: sudo modprobe hci_vhci")
        all_ok = False

    # BlueZ (bluetoothctl)
    try:
        _sp.run(["bluetoothctl", "--version"], capture_output=True, timeout=3)
        print_success("  bluetoothctl : found")
    except FileNotFoundError:
        print_warning("  bluetoothctl : not found — install bluez")
        all_ok = False
    except Exception:
        print_warning("  bluetoothctl : check failed")

    # btmon
    try:
        _sp.run(["btmon", "--version"], capture_output=True, timeout=3)
        print_success("  btmon        : found")
    except FileNotFoundError:
        print_dim("  btmon        : not found (optional — install bluez-utils)")
    except Exception:
        pass

    # bleak (Python)
    try:
        import bleak  # noqa: F401

        print_success("  bleak        : installed")
    except ImportError:
        print_dim("  bleak        : not installed (optional — pip install bleak)")

    # CatSniffer device
    devs = catnip_get_devices()
    if devs:
        for dev in devs:
            port = dev.bridge_port or "?"
            print_success(f"  CatSniffer   : {dev}  bridge={port}")
    else:
        print_warning("  CatSniffer   : no device detected")
        all_ok = False

    print_empty_line()
    if all_ok:
        if os.access("/dev/vhci", os.R_OK | os.W_OK):
            print_success("All prerequisites met. Run: catnip vhci start")
        else:
            print_success("All prerequisites met. Run: sudo catnip vhci start")
    else:
        print_warning("Some prerequisites are missing. See above.")
