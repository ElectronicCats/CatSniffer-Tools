"""Click options shared by more than one command.

``--device`` was declared 15 times across 7 modules with the same
``default``/``type`` and, in 12 of them, the same help text.  While every
command lived in ``modules/core/cli.py`` the duplication was at least visible
in one place; now that they are spread over ``modules/<feature>/cli.py`` it is
the kind of thing that drifts.  See ``BOMBERCAT_PARITY.md`` section 1.

Options are exposed as *factories* rather than plain constants because a few
commands need their own help text (``flash``, ``verify``, ``restore``) while
keeping the flags, type and default identical.
"""

# External
import click

DEVICE_HELP = "Device ID (for multiple CatSniffers)"


def device_option(help: str = DEVICE_HELP, **kwargs):
    """``-d/--device``: CatSniffer selector, uniform across the whole CLI.

    ``help`` is overridden by the few commands that narrow its meaning; any
    other keyword is forwarded to :func:`click.option`.
    """
    return click.option("--device", "-d", default=None, type=int, help=help, **kwargs)


RAW_HELP = "Save captured packets as raw hex to FILE (RX: <hex> | RSSI: <rssi>)"
ASCII_HELP = (
    "Save captured packets as decoded ASCII to FILE (RX: <ascii> | RSSI: <rssi>)"
)

_CAPTURE_FILE = click.Path(dir_okay=False, writable=True)


def raw_file_option(help: str = RAW_HELP, **kwargs):
    """``-r/--raw``: dump the capture as raw hex to a file.

    ``sniff lora`` overrides ``help`` because its records carry an extra SNR
    field.
    """
    return click.option(
        "--raw", "-r", "raw_file", default=None, type=_CAPTURE_FILE, help=help, **kwargs
    )


def ascii_file_option(help: str = ASCII_HELP, **kwargs):
    """``-ascii/--ascii``: dump the capture as decoded ASCII to a file."""
    return click.option(
        "-ascii",
        "--ascii",
        "ascii_file",
        default=None,
        type=_CAPTURE_FILE,
        help=help,
        **kwargs,
    )


PCAP_HELP = (
    "Write the capture to FILE for offline analysis (.pcap, or .pcapng if the "
    "name ends in .pcapng). Works with or without --wireshark"
)
FORCE_HELP = "Overwrite the --write file if it already exists"


def pcap_file_option(help: str = PCAP_HELP, **kwargs):
    """``-w/--write``: save the capture as a PCAP/PCAPNG file.

    The same records that go to the Wireshark pipe are written to disk, so the
    capture survives the session and can be replayed with ``tshark``/Wireshark,
    shared, or used as a regression fixture.  Unlike ``--raw``/``--ascii`` this
    file is a real capture: it keeps per-packet timestamps and the link-layer
    metadata (LoRaTap, TI radio header) that the text logs drop.
    """
    return click.option(
        "--write",
        "-w",
        "pcap_file",
        default=None,
        type=_CAPTURE_FILE,
        help=help,
        **kwargs,
    )


def force_option(help: str = FORCE_HELP, **kwargs):
    """``-f/--force``: allow ``--write`` to truncate an existing capture file.

    ``--raw``/``--ascii`` append, so an existing file is harmless there.  A
    PCAP file cannot be appended to safely (the second session would need the
    same link type, and a PCAPNG section header would land mid-file), so it is
    truncated instead — which means it has to be opt-in.
    """
    return click.option("--force", "-f", is_flag=True, help=help, **kwargs)


BOARD_HELP = (
    "Board generation override (v2 = SAMD21 + CC1352P1, v3 = RP2040 + "
    "CC1352P7). Only needed when the Cat-Shell port cannot answer; the wrong "
    "value disables the CC1352 bootloader"
)


def board_option(help: str = BOARD_HELP, **kwargs):
    """``--board``: name the board when detection cannot.

    Every flashing path asks the board which generation it is, because a
    CC1352P7 image on a CC1352P1 needs a cJTAG programmer to undo.  A board
    whose shell is dead cannot answer, and that is exactly the board a user
    is trying to recover, so the answer has to be supplyable by hand.
    """
    return click.option(
        "--board",
        "board_override",
        default=None,
        type=click.Choice(["v2", "v3"], case_sensitive=False),
        help=help,
        **kwargs,
    )
