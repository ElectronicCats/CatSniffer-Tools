"""``catnip meshtastic`` - Meshtastic protocol tools."""

# Internal
from ...core.device_utils import get_device_or_exit

# External
import click
import sys
import queue

from ...utils.output import (
    print_warning,
    print_error,
    print_info,
    print_dim,
    print_empty_line,
)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def meshtastic():
    """Meshtastic protocol tools"""
    pass


@meshtastic.command("decode")
@click.option(
    "-i",
    "--input",
    required=True,
    help="Hex-encoded payload (raw packet data starting with dest, sender, etc.)",
)
@click.option(
    "-k",
    "--key",
    default="1PG7OiApB1nwvP+rz05pAQ==",
    help="Base64-encoded AES key. Use 'ham' or 'nokey' for open channels",
)
def meshtastic_decode(input, key):
    """Decrypt and decode a hex-encoded Meshtastic packet"""
    try:
        from ..meshtastic import MeshtasticDecoder
    except ImportError as e:
        print_error(
            f"The 'meshtastic' library is required for this command. (Error: {e})"
        )
        print_empty_line()
        print_warning("This library should be bundled with the package.")
        print_info("If it's missing, you can install it manually:")
        print_dim("pip install meshtastic protobuf pyyaml")
        sys.exit(1)

    try:
        decoder = MeshtasticDecoder(key=key)
        decrypted_hex, result = decoder.decode(input)
        print(f"Decrypted raw (hex): {decrypted_hex}")
        print(result)
    except Exception as e:
        print_error(f"Error: {e}")
        sys.exit(1)


@meshtastic.command("live")
@click.option(
    "-d",
    "--device",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
@click.option(
    "-baud",
    "--baudrate",
    type=int,
    default=115200,
    help="Baudrate (default: 115200)",
)
@click.option(
    "-f",
    "--frequency",
    type=float,
    default=906.875,
    help="Frequency in MHz (default: 906.875)",
)
@click.option(
    "-ps",
    "--preset",
    type=click.Choice(
        [
            "defcon33",
            "ShortTurbo",
            "ShortSlow",
            "ShortFast",
            "MediumSlow",
            "MediumFast",
            "LongSlow",
            "LongFast",
            "LongMod",
            "VLongSlow",
        ]
    ),
    default="LongFast",
    help="Channel preset (default: LongFast)",
)
def meshtastic_live(device, baudrate, frequency, preset):
    """Live Meshtastic decoder - Capture and decode packets in real-time"""
    try:
        from ..meshtastic import MeshtasticLiveDecoder
    except ImportError as e:
        print_error(
            f"The 'meshtastic' library is required for this command. (Error: {e})"
        )
        print_empty_line()
        print_warning("This library should be bundled with the package.")
        print_info("If it's missing, you can install it manually:")
        print_dim("pip install meshtastic protobuf pyyaml")
        sys.exit(1)

    # Get device or exit with error
    dev = get_device_or_exit(device)

    # Use the LoRa port from the device
    port = dev.lora_port
    if not port:
        print_error("LoRa port not found for device!")
        return

    # Use the Shell port for configuration
    shell_port = dev.shell_port
    if not shell_port:
        print_error("Shell port not found for device! Required for configuration.")
        return

    decoder = MeshtasticLiveDecoder(port, baudrate)

    freq_hz = int(frequency * 1_000_000)
    print_info(f"Using device: {dev}")
    print_info(f"Configuring radio: {frequency} MHz ({freq_hz} Hz), preset: {preset}")

    # Configure radio using shell port with correct commands
    if not decoder.configure_radio(freq_hz, preset, shell_port):
        print_error("Failed to configure radio")
        return

    print_info("Starting capture... Press Ctrl+C to stop")
    decoder.start()

    try:
        decoder.process_packets()
    except KeyboardInterrupt:
        print_info("Shutting down...")
    finally:
        decoder.stop()


@meshtastic.command("dashboard")
@click.option(
    "-d",
    "--device",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
@click.option(
    "-baud",
    "--baudrate",
    type=int,
    default=115200,
    help="Baudrate (default: 115200)",
)
@click.option(
    "-f",
    "--frequency",
    type=float,
    default=906.875,
    help="Frequency in MHz (default: 906.875)",
)
@click.option(
    "-ps",
    "--preset",
    type=click.Choice(
        [
            "defcon33",
            "ShortTurbo",
            "ShortSlow",
            "ShortFast",
            "MediumSlow",
            "MediumFast",
            "LongSlow",
            "LongFast",
            "LongMod",
            "VLongSlow",
        ]
    ),
    default="LongFast",
    help="Channel preset (default: LongFast)",
)
def meshtastic_dashboard(device, baudrate, frequency, preset):
    """Meshtastic Chat TUI - Beautiful terminal dashboard for Meshtastic"""
    import asyncio

    try:
        from ..meshtastic.core import configure_meshtastic_radio
        from ..meshtastic import MeshtasticChatApp, Monitor
    except ImportError as e:
        print_error(
            f"The 'meshtastic' library is required for this command. (Error: {e})"
        )
        print_empty_line()
        print_warning("This library should be bundled with the package.")
        print_info("If it's missing, you can install it manually:")
        print_dim("pip install meshtastic protobuf pyyaml")
        sys.exit(1)

    # Get device or exit with error
    dev = get_device_or_exit(device)

    # Use the LoRa port from the device
    port = dev.lora_port
    if not port:
        print_error("LoRa port not found for device!")
        return

    # Use the Shell port for configuration
    shell_port = dev.shell_port
    if not shell_port:
        print_error("Shell port not found for device! Required for configuration.")
        return

    print_info(f"Using device: {dev}")

    # Create monitor
    rx_queue = queue.Queue()
    mon = Monitor(port, baudrate, rx_queue)
    mon.start()

    # Configure radio using shell port securely
    print_info("Configuring radio...")
    freq_hz = int(frequency * 1_000_000)

    if not configure_meshtastic_radio(shell_port, freq_hz, preset):
        print_error("Failed to configure radio")
        mon.stop()
        return

    try:
        app = MeshtasticChatApp(monitor=mon, preset=preset, freq=str(frequency))
        asyncio.run(app.run_async())
    finally:
        mon.stop()


@meshtastic.command("config")
@click.argument("file")
def meshtastic_config(file):
    """Extract PSKs and config info from a Meshtastic JSONC config file"""
    try:
        from ..meshtastic import MeshtasticConfigExtractor
    except ImportError as e:
        print_error(
            f"The 'meshtastic' library is required for this command. (Error: {e})"
        )
        print_empty_line()
        print_warning("This library should be bundled with the package.")
        print_info("If it's missing, you can install it manually:")
        print_dim("pip install meshtastic protobuf pyyaml")
        sys.exit(1)

    extractor = MeshtasticConfigExtractor(file)
    if extractor.load():
        extractor.print_all()
    else:
        sys.exit(1)
