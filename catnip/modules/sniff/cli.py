"""``catnip sniff`` - sniffing commands (BLE, Zigbee, Thread, LoRa, AirTag)."""

import logging
import os
import platform
import re
import subprocess
import sys
import tempfile
import time

# Internal
from ..core.bridge import run_bridge, run_fsk_bridge, run_sx_bridge
from ..core.catnip import SniffingBaseFirmware, SniffingFirmware
from ..core.device_session import device_session
from ..core.device_utils import get_device_or_exit
from ..core.extcap import (
    find_putty_path,
    find_wireshark_path,
    open_capture_in_wireshark,
    print_wireshark_install_hint,
    run_extcap_directly,
)
from ..core.usb_connection import open_serial_port
from ..firmware.flasher import Flasher
from protocol.sniffer_sx import (
    FSK_BANDWIDTHS,
    FSK_FALLBACK_BANDWIDTH,
    LORAWAN_SYNCWORD,
    fsk_bandwidth_is_wide_enough,
    lora_decode_as_args,
    lora_wireshark_display_args,
    normalize_fsk_syncword,
    normalize_syncword,
)

# External
import click
import serial

from ..utils.cli_options import (
    ascii_file_option,
    device_option,
    force_option,
    pcap_file_option,
    raw_file_option,
)
from ..utils.output import (
    console,
    print_success,
    print_error,
    print_info,
    print_dim,
    print_warning,
    refuse_overwrite,
)

logger = logging.getLogger("rich")


def _capture_file_is_writable(pcap_file: str, force: bool) -> bool:
    """Check ``-w`` before the capture starts, not once it is under way.

    The bridge refuses to clobber an existing capture file anyway, but by then
    the device has been flashed, the port opened and the radio configured — so
    the same check runs here first and the command exits having done nothing.
    """
    return refuse_overwrite(pcap_file, force=force, mode="block")


def _require_wireshark(command: str = "catnip sniff lora") -> bool:
    """Report a missing Wireshark before the capture starts, not after.

    Same reasoning as :func:`_capture_file_is_writable`: the live path only
    finds out that Wireshark never opened the pipe once the radio is
    configured, and then it just times out.  Checked up front, the command
    exits immediately with something the user can act on.
    """
    if find_wireshark_path():
        return True

    print_error("Wireshark not found on this system")
    print_wireshark_install_hint()
    print_info("Or capture now and analyse the file later:")
    print_dim(f"  {command} -w capture.pcapng")
    return False


def _explain_lorawan_dissection(opening_wireshark: bool, sync_word: str) -> None:
    """Say out loud which dissector the 0x34 sync word just cost the user.

    Wireshark's LoRaTap dissector hands anything captured on sync word 0x34 to
    the LoRaWAN dissector, and a plain-LoRa payload then arrives as "LoRaWAN MAC
    Header malformed".  catnip overrides that, since raw bytes are a harmless
    reading of a LoRaWAN frame while the reverse looks like a broken capture —
    but a real LoRaWAN user has to be told, in one line, how to get their
    dissector back.
    """
    if not opening_wireshark:
        return
    try:
        _, syncword_byte = normalize_syncword(sync_word)
    except ValueError:
        return
    if syncword_byte != LORAWAN_SYNCWORD:
        return

    print_info(
        f"Sync word 0x{LORAWAN_SYNCWORD:02X} (LoRaWAN) — payloads shown as raw "
        "data in Wireshark"
    )
    print_dim(
        "If this really is LoRaWAN traffic, right-click a packet in Wireshark and "
        "pick Decode As... → LoRaWAN"
    )


def _offer_wireshark_after_capture(
    pcap_file: str,
    packet_count: int,
    always_open: bool,
    live_wireshark: bool,
    wireshark_args: list = None,
) -> None:
    """Open the saved capture in Wireshark once the sniffer has stopped.

    ``--open-capture`` opens it without asking; otherwise the user is offered
    the choice, so that a plain ``catnip sniff lora -w capture.pcapng`` ends one
    keystroke away from Wireshark.  The prompt is skipped when Wireshark was
    already following the capture live (``-ws``), when nothing was captured, and
    when there is no terminal to answer on (scripts, pipes, CI).
    """
    if not pcap_file or not os.path.isfile(pcap_file):
        return
    if not packet_count:
        # Nothing was captured, or the bridge bailed out before streaming.
        return

    if not always_open:
        if live_wireshark or not sys.stdin.isatty():
            return
        if not find_wireshark_path():
            print_dim(f"Analyse the capture later with: wireshark -r {pcap_file}")
            return
        try:
            if not click.confirm(f"Open {pcap_file} in Wireshark now?", default=True):
                print_dim(f"Analyse it later with: wireshark -r {pcap_file}")
                return
        except (click.Abort, EOFError, KeyboardInterrupt):
            # A second Ctrl+C at the prompt means "just quit".
            return

    open_capture_in_wireshark(pcap_file, extra_args=wireshark_args)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-v", "--verbose", is_flag=True, help="Show Verbose mode")
def sniff(verbose):
    """Sniffer protocol control"""
    if verbose:
        logger.level = logging.INFO
    pass


@sniff.command(SniffingFirmware.BLE.name.lower())
@device_option()
@click.option(
    "--wireshark",
    "-ws",
    is_flag=True,
    help="Open Wireshark with Sniffle extcap plugin",
)
@click.option(
    "--channel",
    "-c",
    default=37,
    type=click.IntRange(37, 39),
    help="BLE advertising channel (37, 38, 39)",
)
@click.option(
    "--mode",
    "-m",
    default="conn_follow",
    type=click.Choice(["conn_follow", "passive_scan", "active_scan"]),
    help="Sniffle mode",
)
def sniff_ble(device, wireshark, channel, mode):
    """Sniffing BLE with Sniffle firmware.

    \b
    Examples:
        catnip sniff ble                    # ready for manual Wireshark setup
        catnip sniff ble --wireshark        # auto-open Wireshark
        catnip sniff ble -c 39 -m passive_scan
    """
    with device_session(
        device,
        required_firmware=SniffingBaseFirmware.BLE.value,
        feature="catnip sniff ble",
        flasher=Flasher(),
        verify_retries=2,
    ) as dev:
        if wireshark:
            # Always use the direct method when --wireshark is specified
            success = run_extcap_directly(dev.bridge_port, channel, mode)

            if not success:
                print_error(
                    "Could not open Wireshark automatically using direct method"
                )
                print_info("\nYou can try manual configuration:")
                print_info("1. Open Wireshark manually")
                print_info("2. Press Ctrl+E for Capture Options")
                print_info("3. Select 'sniffle' interface")
                print_info(f"4. Configure port: {dev.bridge_port}")
        else:
            print_info("Sniffle firmware is ready!")
            print_info("\nTo capture with Wireshark:")
            print_info(f"1. Open Wireshark and select 'sniffle' interface")
            print_info(f"2. Configure serial port: {dev.bridge_port}")
            print_info(f"3. Set channel: {channel}")
            print_info(f"4. Set mode: {mode}")


@sniff.command(SniffingFirmware.ZIGBEE.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--channel", "-c", required=True, type=click.IntRange(11, 26), help="Zigbee channel"
)
@device_option()
@raw_file_option()
@ascii_file_option()
@pcap_file_option()
@force_option()
def sniff_zigbee(ws, channel, device, raw_file, ascii_file, pcap_file, force):
    """Sniffing Zigbee with Sniffer TI firmware.

    \b
    Examples:
        catnip sniff zigbee -c 15
        catnip sniff zigbee -c 15 -ws              # open Wireshark
        catnip sniff zigbee -c 15 -r capture.raw   # save raw log to file
        catnip sniff zigbee -c 15 -w capture.pcap  # save a capture for tshark
    """
    if not _capture_file_is_writable(pcap_file, force):
        raise SystemExit(1)

    with device_session(
        device,
        required_firmware="ti_sniffer",
        feature="catnip sniff zigbee",
        flasher=Flasher(),
        post_flash_wait=0.5,
        verify_retries=0,
    ) as dev:
        print_info(f"[{dev}] Sniffing Zigbee at channel: {channel}")
        if raw_file:
            print_dim(f"Raw log:          {raw_file}")
        if ascii_file:
            print_dim(f"ASCII log:        {ascii_file}")
        if pcap_file:
            print_dim(f"Capture file:     {pcap_file}")
        run_bridge(
            dev,
            channel,
            ws,
            profile="Zigbee",
            raw_file=raw_file,
            ascii_file=ascii_file,
            pcap_file=pcap_file,
            force=force,
        )


@sniff.command(SniffingFirmware.THREAD.name.lower())
@click.option("-ws", is_flag=True, help="Open Wireshark")
@click.option(
    "--channel", "-c", required=True, type=click.IntRange(11, 26), help="Thread channel"
)
@device_option()
@raw_file_option()
@ascii_file_option()
@pcap_file_option()
@force_option()
def sniff_thread(ws, channel, device, raw_file, ascii_file, pcap_file, force):
    """Sniffing Thread with Sniffer TI firmware.

    \b
    Examples:
        catnip sniff thread -c 15
        catnip sniff thread -c 15 -ws              # open Wireshark
        catnip sniff thread -c 15 -w capture.pcap  # save a capture for tshark
    """
    if not _capture_file_is_writable(pcap_file, force):
        raise SystemExit(1)

    with device_session(
        device,
        required_firmware="ti_sniffer",
        feature="catnip sniff thread",
        flasher=Flasher(),
        post_flash_wait=0.5,
        verify_retries=0,
    ) as dev:
        print_info(f"[{dev}] Sniffing Thread at channel: {channel}")
        if raw_file:
            print_dim(f"Raw log:          {raw_file}")
        if ascii_file:
            print_dim(f"ASCII log:        {ascii_file}")
        if pcap_file:
            print_dim(f"Capture file:     {pcap_file}")
        run_bridge(
            dev,
            channel,
            ws,
            profile="Thread",
            raw_file=raw_file,
            ascii_file=ascii_file,
            pcap_file=pcap_file,
            force=force,
        )


def _validate_sync_word(ctx, param, value):
    """Accept the firmware's own sync word spec: private|public|0xNN."""
    try:
        arg, _ = normalize_syncword(value)
    except ValueError as exc:
        raise click.BadParameter(str(exc))
    return arg


@sniff.command(SniffingFirmware.LORA.name.lower())
@click.option(
    "--wireshark",
    "-ws",
    "ws",
    is_flag=True,
    help="Open Wireshark live while the capture runs (LoRaTap over a local pipe)",
)
@click.option(
    "--open-capture",
    "-oc",
    "open_capture",
    is_flag=True,
    help=(
        "Open the capture in Wireshark when the sniffer stops. Without --write "
        "the packets are saved to a temporary .pcapng file first"
    ),
)
@click.option("-v", "--verbose", is_flag=True, help="Show verbose output in terminal")
@click.option(
    "--frequency",
    "-freq",
    default=915000000,
    type=click.IntRange(150000000, 960000000),
    help="Frequency in Hz, 150-960 MHz (e.g., 915000000 for 915 MHz)",
)
@click.option(
    "--bandwidth",
    "-bw",
    # The default has to be one of the *strings* in the Choice: Click 8.0/8.1
    # match the default against the choices without coercing it, so an int 125
    # made `sniff lora` unusable without an explicit -bw ("125 is not one of
    # '125', '250', '500'").  Click >=8.2 stringifies first and hid the bug.
    # `bw_int` below converts it back for the bridge.
    default="125",
    type=click.Choice(["125", "250", "500"]),
    help="Bandwidth in kHz",
)
@click.option(
    "--spread_factor",
    "-sf",
    default=7,
    type=click.IntRange(7, 12),
    help="Spreading Factor (7-12)",
)
@click.option(
    "--coding_rate",
    "-cr",
    default=5,
    type=click.IntRange(5, 8),
    help="Coding Rate (5-8)",
)
@click.option(
    "--tx_power",
    "-pw",
    default=20,
    type=click.IntRange(-9, 22),
    help="TX Power in dBm (-9 to 22, SX1262 hardware range)",
)
@device_option()
@click.option(
    "--sync-word",
    "-sw",
    default="private",
    callback=_validate_sync_word,
    help=(
        "LoRa sync word: 'public' (0x34, LoRaWAN), 'private' (0x12) or any raw "
        "byte as 0xNN (e.g. 0x2B for Meshtastic). Default: private."
    ),
)
@click.option(
    "--preamble",
    "-pre",
    default=12,
    type=click.IntRange(6, 65535),
    help="Preamble length in symbols (6-65535). Default: 12.",
)
@click.option(
    "--iq",
    default="normal",
    type=click.Choice(["normal", "inverted"]),
    help="IQ polarity. LoRaWAN downlinks need 'inverted'. Default: normal.",
)
@raw_file_option(
    help="Save captured packets as raw hex to FILE (RX: <hex> | RSSI: <rssi> | SNR: <snr>)"
)
@ascii_file_option(
    help="Save captured packets as decoded ASCII to FILE (RX: <ascii> | RSSI: <rssi> | SNR: <snr>)"
)
@pcap_file_option()
@force_option()
def sniff_lora(
    ws,
    open_capture,
    verbose,
    frequency,
    bandwidth,
    spread_factor,
    coding_rate,
    tx_power,
    device,
    sync_word,
    preamble,
    iq,
    raw_file,
    ascii_file,
    pcap_file,
    force,
):
    """Sniffing LoRa with Sniffer SX1262 firmware.

    \b
    Examples:
        catnip sniff lora                          # defaults: 915MHz, SF7, BW125
        catnip sniff lora -freq 868000000 -sf 9
        catnip sniff lora -ws                      # live Wireshark while sniffing
        catnip sniff lora -oc                      # sniff, then open Wireshark
        catnip sniff lora -w capture.pcapng        # save it, offer to open it
        catnip sniff lora -sw public               # LoRaWAN sync word (0x34)
        catnip sniff lora -sw 0x2B -pre 16         # Meshtastic sync word
        catnip sniff lora -sw public --iq inverted # LoRaWAN downlinks
    """
    if not _capture_file_is_writable(pcap_file, force):
        raise SystemExit(1)

    # Both Wireshark paths need the binary; refuse now rather than after the
    # radio has been configured and the user has spent a capture session.
    if (ws or open_capture) and not _require_wireshark():
        raise SystemExit(1)

    # --open-capture has to have something to open: without --write the capture
    # would only ever exist in the pipe.
    if open_capture and not pcap_file:
        pcap_file = os.path.join(
            tempfile.gettempdir(),
            # The PID keeps two sniffers started in the same second apart —
            # a name collision would abort the capture on the overwrite guard.
            f"catnip_lora_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.pcapng",
        )
        print_info(f"No --write given — saving the capture to {pcap_file}")

    # Wireshark keys the payload dissector off the sync word in the LoRaTap
    # header; catnip overrides that for 0x34 so plain LoRa is not shown as
    # malformed LoRaWAN, without the user having to know any of it.
    wireshark_args = lora_decode_as_args(sync_word)
    wireshark_args += lora_wireshark_display_args()
    _explain_lorawan_dissection(ws or open_capture, sync_word)

    dev = get_device_or_exit(device)

    # Convert bandwidth from string to int
    bw_int = int(bandwidth)

    print_info(f"[{dev}] Sniffing LoRa with configuration:")
    print_dim(f"Frequency:        {frequency} Hz ({frequency / 1000000:.3f} MHz)")
    print_dim(f"Bandwidth:        {bw_int} kHz")
    print_dim(f"Spreading Factor: SF{spread_factor}")
    print_dim(f"Coding Rate:      4/{coding_rate}")
    print_dim(f"TX Power:         {tx_power} dBm")
    print_dim(f"Sync Word:        {sync_word}")
    print_dim(f"Preamble:         {preamble} symbols")
    print_dim(f"IQ:               {iq}")
    if raw_file:
        print_dim(f"Raw log:          {raw_file}")
    if ascii_file:
        print_dim(f"ASCII log:        {ascii_file}")
    if pcap_file:
        print_dim(f"Capture file:     {pcap_file}")

    packet_count = run_sx_bridge(
        dev,
        frequency,
        bw_int,
        spread_factor,
        coding_rate,
        tx_power,
        ws,
        verbose,
        sync_word,
        preamble,
        iq,
        raw_file,
        ascii_file,
        pcap_file,
        force,
        wireshark_args=wireshark_args,
    )

    _offer_wireshark_after_capture(
        pcap_file,
        packet_count,
        open_capture,
        live_wireshark=ws,
        wireshark_args=wireshark_args,
    )


def _validate_fsk_sync_word(ctx, param, value):
    """Accept the firmware's own FSK sync word spec: 1-8 bytes of hex."""
    try:
        return normalize_fsk_syncword(value)
    except ValueError as exc:
        raise click.BadParameter(str(exc))


def _warn_narrow_fsk_bandwidth(bandwidth: str, bitrate: int, fdev: int) -> None:
    """Say out loud that the firmware is about to overrule the -bw just given.

    ``apply_fsk_config`` checks the RX bandwidth against Carson's rule
    (bitrate + 2*fdev) and, when it is too narrow to fit the signal, replaces it
    with 187.2 kHz — on the Cat-Shell port, which ``sniff fsk`` does not show.
    Without this the user reads their own ``-bw 58.6`` back from the summary and
    captures on a bandwidth they never asked for.
    """
    if fsk_bandwidth_is_wide_enough(bandwidth, bitrate, fdev):
        return

    print_warning(
        f"Bandwidth {bandwidth} kHz is too narrow for {bitrate} bps at "
        f"{fdev} Hz deviation — the firmware will use "
        f"{FSK_FALLBACK_BANDWIDTH} kHz instead"
    )
    print_dim(
        f"  Pass -bw {FSK_FALLBACK_BANDWIDTH} (or wider) to choose it yourself, "
        "or lower --bitrate/--fdev"
    )


@sniff.command(SniffingFirmware.FSK.name.lower())
@click.option(
    "--wireshark",
    "-ws",
    "ws",
    is_flag=True,
    help="Open Wireshark live while the capture runs (LoRaTap over a local pipe)",
)
@click.option(
    "--open-capture",
    "-oc",
    "open_capture",
    is_flag=True,
    help=(
        "Open the capture in Wireshark when the sniffer stops. Without --write "
        "the packets are saved to a temporary .pcapng file first"
    ),
)
@click.option("-v", "--verbose", is_flag=True, help="Show verbose output in terminal")
@click.option(
    "--frequency",
    "-freq",
    default=915000000,
    type=click.IntRange(137000000, 1020000000),
    help="Frequency in Hz, 137-1020 MHz (e.g., 915000000 for 915 MHz)",
)
@click.option(
    "--bitrate",
    "-br",
    default=50000,
    type=click.IntRange(600, 300000),
    help="Bitrate in bps (600-300000). Default: 50000.",
)
@click.option(
    "--fdev",
    "-fd",
    default=25000,
    type=click.IntRange(600, 200000),
    help="Frequency deviation in Hz (600-200000). Default: 25000.",
)
@click.option(
    "--bandwidth",
    "-bw",
    default="187.2",
    type=click.Choice(list(FSK_BANDWIDTHS)),
    help=(
        "RX bandwidth in kHz. Must cover bitrate + 2x deviation or the firmware "
        "widens it to 187.2. Default: 187.2."
    ),
)
@click.option(
    "--tx_power",
    "-pw",
    default=14,
    type=click.IntRange(-9, 22),
    help="TX Power in dBm (-9 to 22, SX1262 hardware range)",
)
@click.option(
    "--preamble",
    "-pre",
    default=8,
    type=click.IntRange(0, 65535),
    help="Preamble length in bytes (FSK counts bytes, not symbols). Default: 8.",
)
@click.option(
    "--sync-word",
    "-sw",
    default="12AD",
    callback=_validate_fsk_sync_word,
    help=(
        "FSK sync word: 1-8 bytes of hex (e.g. 2DD4 for 802.15.4g/Meshtastic). "
        "Default: 12AD."
    ),
)
@click.option(
    "--bt",
    default="0.5",
    type=click.Choice(["off", "0.3", "0.5", "0.7", "1.0"]),
    help="Gaussian filter BT: 'off' is plain FSK, a value is GFSK. Default: 0.5.",
)
@click.option(
    "--crc/--no-crc",
    default=False,
    help="Let the modem verify the CRC and drop failing frames. Default: --no-crc.",
)
@click.option(
    "--whitening/--no-whitening",
    default=False,
    help="Undo the transmitter's data whitening. Default: --no-whitening.",
)
@click.option(
    "--pktlen",
    default="variable",
    type=click.Choice(["variable", "fixed"]),
    help=(
        "'variable' reads each frame's length from its header, 'fixed' assumes "
        "--payload bytes. Default: variable."
    ),
)
@click.option(
    "--payload",
    default=255,
    type=click.IntRange(1, 255),
    help="Payload length for --pktlen fixed, maximum length otherwise. Default: 255.",
)
@device_option()
@raw_file_option(
    help="Save captured packets as raw hex to FILE (RX: <hex> | RSSI: <rssi>)"
)
@ascii_file_option(
    help="Save captured packets as decoded ASCII to FILE (RX: <ascii> | RSSI: <rssi>)"
)
@pcap_file_option()
@force_option()
def sniff_fsk(
    ws,
    open_capture,
    verbose,
    frequency,
    bitrate,
    fdev,
    bandwidth,
    tx_power,
    preamble,
    sync_word,
    bt,
    crc,
    whitening,
    pktlen,
    payload,
    device,
    raw_file,
    ascii_file,
    pcap_file,
    force,
):
    """Sniffing (G)FSK with Sniffer SX1262 firmware.

    Same radio and same ports as ``sniff lora``, with the SX1262 in FSK mode —
    where it hears the sub-GHz traffic LoRa cannot: 802.15.4g/Wi-SUN, smart
    meters, alarm and sensor links, and anything else on a plain (G)FSK ISM
    channel.  Unlike LoRa, FSK only demodulates what matches the bitrate,
    deviation and sync word it was told to expect, so those have to be right.

    \b
    Examples:
        catnip sniff fsk                             # defaults: 915MHz, 50kbps
        catnip sniff fsk -freq 868000000 -br 100000 -fd 50000
        catnip sniff fsk -sw 2DD4 --whitening        # 802.15.4g-style framing
        catnip sniff fsk -ws                         # live Wireshark
        catnip sniff fsk -w capture.pcapng           # save it, offer to open it
        catnip sniff fsk --bt off                    # plain FSK, no shaping
    """
    if not _capture_file_is_writable(pcap_file, force):
        raise SystemExit(1)

    # Both Wireshark paths need the binary; refuse now rather than after the
    # radio has been configured and the user has spent a capture session.
    if (ws or open_capture) and not _require_wireshark("catnip sniff fsk"):
        raise SystemExit(1)

    # --open-capture has to have something to open: without --write the capture
    # would only ever exist in the pipe.
    if open_capture and not pcap_file:
        pcap_file = os.path.join(
            tempfile.gettempdir(),
            # The PID keeps two sniffers started in the same second apart —
            # a name collision would abort the capture on the overwrite guard.
            f"catnip_fsk_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.pcapng",
        )
        print_info(f"No --write given — saving the capture to {pcap_file}")

    _warn_narrow_fsk_bandwidth(bandwidth, bitrate, fdev)

    # No decode-as rule here: the LoRaTap sync word of an FSK frame is written
    # as 0, so Wireshark reaches for no payload dissector of its own.  The
    # column layout is still worth overriding, minus the SNR an FSK frame is
    # never reported with.
    wireshark_args = lora_wireshark_display_args(snr=False)

    dev = get_device_or_exit(device)

    print_info(f"[{dev}] Sniffing FSK")
    if raw_file:
        print_dim(f"Raw log:          {raw_file}")
    if ascii_file:
        print_dim(f"ASCII log:        {ascii_file}")
    if pcap_file:
        print_dim(f"Capture file:     {pcap_file}")

    packet_count = run_fsk_bridge(
        dev,
        frequency,
        bitrate,
        fdev,
        bandwidth,
        tx_power,
        preamble,
        sync_word,
        crc,
        whitening,
        pktlen,
        payload,
        bt,
        ws,
        verbose,
        raw_file,
        ascii_file,
        pcap_file,
        force,
        wireshark_args=wireshark_args,
    )

    _offer_wireshark_after_capture(
        pcap_file,
        packet_count,
        open_capture,
        live_wireshark=ws,
        wireshark_args=wireshark_args,
    )


_AIRTAG_BAUDRATE = 9600

# Log-distance path-loss model: distance = 10 ** ((txPowerAt1m - rssi) / (10 * n)).
# There is no calibration data for the AirTag's actual TX power, so
# txPowerAt1m/n are just typical BLE-beacon defaults — treat the result as an
# order-of-magnitude estimate, not a measurement.
_AIRTAG_TX_POWER_AT_1M = -59  # dBm, RSSI expected at 1 meter
_AIRTAG_PATH_LOSS_EXPONENT = 2.0  # ~2 free space, ~3-4 indoors/obstructed

_AIRTAG_LINE_RE = re.compile(
    r"Airtag detected! -> (?P<addr>\S+) RSSI:(?P<rssi>-?\d+) Status: (?P<status>.+)"
)


def _estimate_distance_m(rssi: int) -> float:
    """Rough distance estimate (meters) from RSSI via the log-distance path-loss model."""
    return 10 ** ((_AIRTAG_TX_POWER_AT_1M - rssi) / (10 * _AIRTAG_PATH_LOSS_EXPONENT))


def _stream_airtag_scanner(port: str) -> None:
    ser = open_serial_port(port, baudrate=_AIRTAG_BAUDRATE, timeout=0.5)
    if ser is None:
        print_error(f"Could not open {port} at {_AIRTAG_BAUDRATE} baud")
        return

    print_success(
        f"Listening on {port} at {_AIRTAG_BAUDRATE} baud — press Ctrl+C to stop"
    )

    detections = 0
    try:
        while True:
            try:
                raw = ser.readline()
            except serial.SerialException as exc:
                print_warning(f"Serial error (device disconnected?): {exc}")
                break

            if not raw:
                continue

            line = raw.decode("ascii", errors="replace").strip()
            if not line:
                continue

            match = _AIRTAG_LINE_RE.search(line)
            if not match:
                print_dim(line)
                continue

            detections += 1
            rssi = int(match.group("rssi"))
            distance_m = _estimate_distance_m(rssi)
            console.print(
                f"[green][{detections:>4}][/green] AirTag [bold]{match.group('addr')}[/bold]  "
                f"RSSI=[cyan]{rssi:>4} dBm[/cyan]  "
                f"~distance=[yellow]{distance_m:.1f} m[/yellow]  "
                f"({match.group('status')})"
            )
    except KeyboardInterrupt:
        print_info(f"Stopped — {detections} AirTag detection(s) captured")
    finally:
        ser.close()


@sniff.command(SniffingFirmware.AIRTAG_SCANNER.name.lower())
@device_option()
@click.option(
    "--putty", is_flag=True, help="Open PuTTY with serial configuration instead"
)
def sniff_airtag_scanner(device, putty):
    """Sniffing Airtag Scanner firmware.

    Prints each detected AirTag directly in this terminal, along with its
    RSSI and an approximate distance estimate.

    \b
    Examples:
        catnip sniff airtag_scanner
        catnip sniff airtag_scanner --putty    # auto-open PuTTY at 9600 baud instead
    """
    # Must match ALIAS_TO_OFFICIAL_ID in fw_aliases.py
    official_id = "airtag_scanner_cc1352p7"

    with device_session(
        device,
        required_firmware=official_id,
        feature="catnip sniff airtag-scanner",
        flasher=Flasher(),
        verify_retries=0,
    ) as dev:
        if putty:
            putty_path = find_putty_path()
            if not putty_path:
                print_error(
                    "PuTTY not found! Make sure it is installed and in your PATH."
                )
                if platform.system() == "Linux":
                    print_info(
                        "On Linux, you can install it with: sudo apt install putty"
                    )
                elif platform.system() == "Darwin":
                    print_info("On macOS, you can install it with: brew install putty")
                return

            print_info(f"Opening PuTTY on {dev.bridge_port} at 9600 baud...")
            try:
                # putty -serial [port] -sercfg 9600,8,n,1,n
                cmd = [
                    putty_path,
                    "-serial",
                    dev.bridge_port,
                    "-sercfg",
                    "9600,8,n,1,n",
                ]
                subprocess.Popen(cmd)
                print_success("PuTTY launched successfully!")
            except Exception as e:
                print_error(f"Failed to launch PuTTY: {str(e)}")
        else:
            _stream_airtag_scanner(dev.bridge_port)
