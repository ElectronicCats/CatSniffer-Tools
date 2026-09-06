"""``device_session()``: resolve a device and, when a specific CC1352
firmware is required, guarantee it is running — flashing it if not.

This is the sequence that used to be copy-pasted (with small, arbitrary
variations) across ``sniff/cli.py``'s ``sniff_ble``/``sniff_zigbee``/
``sniff_thread``/``sniff_airtag_scanner`` (~50 lines each; see
analisis-bombercat-vs-catnip.md, section 2, "Duplicación de lógica").
"""

import time
from contextlib import contextmanager
from typing import Optional

from . import device_utils
from .exceptions import FirmwareError
from .firmware_verifier import FirmwareVerifier
from ..utils.output import print_info, print_success, print_warning


@contextmanager
def device_session(
    device_id=None,
    *,
    required_firmware: Optional[str] = None,
    flasher=None,
    post_flash_wait: float = 1.0,
    verify_retries: int = 2,
    verify_retry_delay: float = 0.5,
    identify: bool = True,
):
    """Resolve a device, optionally ensuring ``required_firmware`` is present.

    Args:
        device_id: Device selector forwarded to ``get_device_or_exit``.
        required_firmware: Official firmware id (see ``firmware_registry``)
            that must be running on the device's CC1352. Skipped when None.
        flasher: A ``Flasher`` instance used to flash ``required_firmware``
            when it isn't detected. Required if ``required_firmware`` is set
            and the firmware might be missing.
        post_flash_wait: Seconds to wait after flashing before re-verifying.
        verify_retries: Extra verification attempts after flashing, spaced
            ``verify_retry_delay`` seconds apart.
        identify: Send the "identify" command once the session is ready.

    Raises:
        FirmwareError: the flash itself failed, or no ``flasher`` was given
            for a missing firmware. A failed *re*-verification after a
            successful flash only warns and continues — matching prior
            per-command behaviour, since the device commonly still works.

    Yields:
        The resolved ``CatSnifferDevice``.
    """
    dev = device_utils.get_device_or_exit(device_id)

    if required_firmware is not None:
        verifier = FirmwareVerifier(dev.bridge_port, dev.shell_port)
        print_info(f"Checking for '{required_firmware}' firmware...")
        result = verifier.verify(required_firmware)

        if result.verified:
            print_success(
                f"'{required_firmware}' firmware found (via {result.confidence.value})!"
            )
        else:
            if flasher is None:
                raise FirmwareError(
                    f"'{required_firmware}' firmware not found on device.",
                    hint=[f"Flash it first: catnip flash {required_firmware}"],
                )

            print_warning(f"'{required_firmware}' firmware not found! Flashing...")
            if not flasher.find_flash_firmware(required_firmware, dev):
                raise FirmwareError(
                    f"Failed to flash '{required_firmware}' firmware.",
                    hint=[
                        "Run 'catnip flash --list' to see available firmware images."
                    ],
                )

            print_info("Waiting for device to initialize after flashing...")
            time.sleep(post_flash_wait)

            result = verifier.verify_with_retries(
                required_firmware, retries=verify_retries, delay=verify_retry_delay
            )
            if result.verified:
                print_success(
                    f"'{required_firmware}' firmware verified successfully "
                    f"(via {result.confidence.value})!"
                )
            else:
                print_warning(
                    "Firmware verification failed after flashing; "
                    "the device may still work."
                )

    if identify:
        device_utils.send_identify_command(dev)

    yield dev
