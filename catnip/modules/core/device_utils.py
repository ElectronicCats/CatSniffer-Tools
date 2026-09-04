"""Device resolution helpers shared by the catnip commands.

Kept free of Click so that any ``modules/<feature>/cli.py`` can import it
without creating a cycle back to ``modules.core.cli``.
"""

# Internal
from .catnip import catnip_get_device
from .usb_connection import ShellConnection

# External
from ..utils.output import (
    print_success,
    print_warning,
    print_error,
    print_info,
    print_dim,
)


def get_device_or_exit(device_id=None):
    """Get CatSniffer device or exit with error."""
    device = catnip_get_device(device_id)
    if device is None:
        print_error("No CatSniffer device found!")
        print_dim("Make sure your CatSniffer is connected.")
        exit(1)
    if not device.is_valid():
        print_warning(f"Not all ports detected for {device}")
        print_dim(f"Bridge: {device.bridge_port}")
        print_dim(f"LoRa:   {device.lora_port}")
        print_dim(f"Shell:  {device.shell_port}")
    return device


def send_identify_command(device):
    """Send identification command to device to help identify it visually."""
    if not device.shell_port:
        print_warning("Shell port not available for identification!")
        return False

    print_info(f"Sending identification command to {device}...")

    try:
        shell = ShellConnection(port=device.shell_port, timeout=1.0)
        with shell:
            response = shell.send_command("identify", timeout=1.0)
            if response:
                print_info(f"Device response: {response}")

        print_success(f"Identification command sent to device #{device.device_id}!")
        return True

    except Exception as e:
        print_warning(f"Could not send identification command: {str(e)}")
        return False
