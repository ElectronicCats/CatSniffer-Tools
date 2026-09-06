#! /usr/bin/env python3

# Electronic Cats
# Original Creation Date: Dec 19, 2025
# This code is beerware; if you see me (or any other Electronic Cats
# member) at the local, and you've found our code helpful,
# please buy us a round!
# Distributed as-is; no warranty is given.

import logging
import os
import sys

# Internal
from ..utils._version import __version__

# Command groups assembled by build_cli()
from ..sniff.cli import sniff as _sniff
from ..device.cli import devices as _devices
from ..device.cli import identify as _identify
from ..firmware.cli import flash as _flash
from ..firmware.cli import update as _update
from ..firmware.cli import restore as _restore
from ..firmware.cli import verify as _verify
from ..protocols.cli.cativity import cativity as _cativity
from ..protocols.cli.meshtastic import meshtastic as _meshtastic
from ..protocols.cli.sx1262 import lora as _lora
from ..protocols.cli.vhci import vhci as _vhci
from ..utils.completion import completion as _completion
from ..utils.system_cli import setup_env as _setup_env

# External
import click
from rich.logging import RichHandler
from rich.panel import Panel

from ..utils.output import (
    console,
    print_error,
    print_error_panel,
    redact_secrets,
    STYLES,
)
from . import exceptions

import platform

# APP Information
VERSION_NUMBER = __version__
COMPANY = "Electronic Cats - PWNLAB"
_FUNNY_PHRASES = [
    "Catching packets, not mice.",
    "Your RF spy in the sky.",
    "Sniffing the air so you don't have to.",
    "Making invisible waves visible.",
    "The only cat that loves antennas.",
    "Packet sniffer. Not a drug.",
    "Who said curiosity killed the cat?",
    "Zigbee, Thread, LoRa — we don't discriminate.",
    "Turning radio waves into trust issues.",
    "Your neighbor's smart bulb has secrets.",
    "Legally (probably) sniffing since 2024.",
    "Because plaintext is a lifestyle choice.",
    "RF doesn't lie. People do.",
    "We sniff, you learn.",
    "Not all heroes wear capes. Some carry antennas.",
    "What even is encryption?",
    "The air is full of data. Help yourself.",
    "Meow. That was a Zigbee beacon.",
    "If it transmits, we see it.",
    "BLE, LoRa, Thread — all your protocols belong to us.",
    "Your Meshtastic network is not as private as you think.",
    "802.15.4 never had a chance.",
    "From 433MHz to 2.4GHz, we catch them all.",
    "LoRa? More like LoRa-caught.",
    "Sub-GHz whisperer.",
]

import random as _random

FUNNY_PHRASE = _random.choice(_FUNNY_PHRASES)

logger = logging.getLogger("rich")
FORMAT = "%(message)s"
logging.basicConfig(
    level="WARNING", format=FORMAT, datefmt="[%X]", handlers=[RichHandler(markup=True)]
)


def print_header(module=None):
    """Print the ASCII art header"""
    if module:
        label = f"catnip {module}"
    elif platform.system() != "Windows" and os.geteuid() == 0:
        label = "catnip: (root)"
    else:
        label = "catnip"

    ascii_art = f"""      :=--             --=-       |
      -====-         -=====       |
      :===================-       |
       ===================:       |
  -   :==--===========--==-   -   |  {label}
 -===:===-   :=====-   -==-.-=--  |  v{VERSION_NUMBER}
--    ====-   :===-   -====    -- |  {FUNNY_PHRASE}
-=:   :===================-   .=- |
 ---=-- -===============-  -=---  |
 ---       --=======--        --  |"""

    colored_ascii = f"[cyan bold]{ascii_art}[/cyan bold]"

    header_panel = Panel(
        colored_ascii,
        title=f"[cyan]{COMPANY}[/cyan]",
        border_style=STYLES["header"],
        title_align="left",
        padding=(1, 2),
    )
    console.print(header_panel)


@click.group(
    "catnip",
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="Set CATNIP_DEBUG=1 to see a full traceback instead of a one-line error.",
)
@click.option("-v", "--verbose", is_flag=True, help="Show Verbose mode")
def cli(verbose):
    """CatSniffer: All in one catnip tools environment."""
    if verbose:
        logger.level = logging.INFO
    pass


def build_cli() -> click.Group:
    """Register every command on the root group and return it assembled.

    Kept apart from :func:`main_cli` so the command tree can be inspected
    without running it (tests, snapshot dumps).
    """
    cli.add_command(_sniff)
    cli.add_command(_cativity)
    cli.add_command(_meshtastic)
    cli.add_command(_devices)
    cli.add_command(_identify)
    cli.add_command(_flash)
    cli.add_command(_update)
    cli.add_command(_restore)
    cli.add_command(_lora)
    if platform.system() == "Linux":
        cli.add_command(_vhci)
        cli.add_command(_setup_env)
    cli.add_command(_verify)
    if platform.system() in ["Linux", "Darwin"]:
        cli.add_command(_completion)
    return cli


def main_cli() -> None:
    """Entry point: run the CLI and turn every failure into an exit code.

    Click is driven with ``standalone_mode=False`` so that the exceptions it
    would otherwise swallow reach us and can be mapped deliberately.  Commands
    that call ``sys.exit()`` themselves are unaffected: ``SystemExit`` is not
    an ``Exception`` and travels straight through.

    See ``BOMBERCAT_PARITY.md`` section 2.
    """
    if not os.environ.get("_CATNIP_COMPLETE"):
        module = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
        print_header(module)
    try:
        rv = build_cli()(prog_name="catnip", standalone_mode=False)
    except click.exceptions.Abort:
        # Ctrl-C or EOF, including inside a prompt: Click has already turned
        # the KeyboardInterrupt into an Abort by the time it gets here.
        raise SystemExit(130)
    except KeyboardInterrupt:
        print_error("interrupted")
        raise SystemExit(130)
    except click.ClickException as e:
        # Click prints these itself in standalone mode; now it is our job.
        e.show()
        raise SystemExit(e.exit_code)
    except exceptions.CatnipError as e:
        # Typed catnip errors: same escape hatch as the generic branch below,
        # but with the exit code and (optionally) the actionable panel that
        # the specific error class carries. See modules/core/exceptions.py.
        if os.environ.get("CATNIP_DEBUG"):
            raise
        if e.hint:
            print_error_panel(type(e).__name__, redact_secrets(str(e)), fix=e.hint)
        else:
            print_error(
                redact_secrets(
                    f"{type(e).__name__}: {e} (set CATNIP_DEBUG=1 for a traceback)"
                )
            )
        raise SystemExit(e.exit_code)
    except Exception as e:
        if os.environ.get("CATNIP_DEBUG"):
            raise
        print_error(
            redact_secrets(
                f"{type(e).__name__}: {e} (set CATNIP_DEBUG=1 for a traceback)"
            )
        )
        raise SystemExit(1)
    else:
        # ``--help`` and friends *return* their exit code instead of exiting.
        raise SystemExit(rv or 0)
