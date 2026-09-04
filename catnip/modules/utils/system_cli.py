"""``catnip setup-env`` - udev rules and user group setup.

Registered on the root group only on Linux, see section 3.2 of
``CLI_REFACTOR_PLAN.md``.
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

# External
import click

from .output import (
    print_success,
    print_warning,
    print_error,
    print_info,
    print_dim,
)


@click.command("setup-env")
def setup_env():
    """Setup environment: install udev rules and add user to groups.

    Requires root privileges (sudo). This command installs the necessary
    udev rules for CatSniffer devices and VHCI, and adds the current
    user to the 'dialout' and 'bluetooth' groups.
    """
    if platform.system() != "Windows" and os.geteuid() != 0:
        print_error("Root privileges required. Please run with sudo:")
        print_dim(f"sudo {sys.argv[0]} setup-env")
        sys.exit(1)

    # 1. Install udev rules
    rules_content = """# Permission to VHCI (Bluetooth Virtual)
KERNEL=="vhci", MODE="0660", GROUP="bluetooth", TAG+="uaccess"

# Permission to CatSniffer (RP2040)
SUBSYSTEM=="tty", ATTRS{idVendor}=="2e8a", ATTRS{idProduct}=="00c0", MODE="0660", GROUP="dialout", TAG+="uaccess"
"""
    rules_path = Path("/etc/udev/rules.d/99-catsniffer.rules")
    try:
        rules_path.write_text(rules_content)
        print_success(f"Udev rules installed to {rules_path}")
    except Exception as e:
        print_error(f"Failed to install udev rules: {e}")

    # 2. Add user to groups
    # Get the real user (since we are likely running with sudo)
    real_user = os.environ.get("SUDO_USER")
    if not real_user:
        # Fallback if SUDO_USER is not set
        import getpass

        real_user = getpass.getuser()

    groups = ["dialout", "bluetooth"]
    for group in groups:
        try:
            subprocess.run(["usermod", "-aG", group, real_user], check=True)
            print_success(f"User '{real_user}' added to group '{group}'")
        except subprocess.CalledProcessError:
            print_warning(
                f"Could not add user '{real_user}' to group '{group}' (does it exist?)"
            )
        except Exception as e:
            print_error(f"Error adding user to group {group}: {e}")

    # 3. Reload udev rules
    try:
        subprocess.run(["udevadm", "control", "--reload-rules"], check=True)
        subprocess.run(["udevadm", "trigger"], check=True)
        print_success("Udev rules reloaded")
    except Exception as e:
        print_warning(f"Could not reload udev rules automatically: {e}")

    print_success("Environment setup complete!")
    print_info("Please log out and log back in for group changes to take effect.")
