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
from .device_utils import get_device_or_exit
from .catnip import catnip_get_devices
from .usb_connection import ShellConnection, CATSNIFFER_VID, CATSNIFFER_PID

# Command groups assembled by build_cli()
from ..sniff.cli import sniff as _sniff
from ..firmware.cli import flash as _flash
from ..firmware.cli import update as _update
from ..firmware.cli import restore as _restore
from ..firmware.cli import verify as _verify
from ..protocols.cli.cativity import cativity as _cativity
from ..protocols.cli.meshtastic import meshtastic as _meshtastic
from ..protocols.cli.sx1262 import lora as _lora
from ..protocols.cli.vhci import vhci as _vhci

# External
import click
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich import box

from ..utils.output import (
    console,
    STYLES,
    print_success,
    print_warning,
    print_error,
    print_info,
    print_dim,
    print_empty_line,
    print_example,
)

import subprocess
import platform
from pathlib import Path

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


@click.group("catnip", context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-v", "--verbose", is_flag=True, help="Show Verbose mode")
def cli(verbose):
    """CatSniffer: All in one catnip tools environment."""
    if verbose:
        logger.level = logging.INFO
    pass


@cli.command()
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Show raw USB port info for each interface (useful for diagnosing Windows port mapping).",
)
def devices(debug: bool) -> None:
    """List connected CatSniffer devices"""
    devs = catnip_get_devices()
    if not devs:
        print_warning("No CatSniffer devices found.")
        if debug:
            _print_raw_port_debug()
        return

    # Add a table to display devices
    table = Table(title=f"Found {len(devs)} CatSniffer device(s)", box=box.ROUNDED)
    table.add_column("Device", style=STYLES["device"], justify="left")
    table.add_column("Cat-Bridge (CC1352)", style="cyan", justify="left")
    table.add_column("Cat-LoRa (SX1262)", style="cyan", justify="left")
    table.add_column("Cat-Shell (Config)", style="cyan", justify="left")

    for dev in devs:
        bridge_status = dev.bridge_port or "[red]Not found[/red]"
        lora_status = dev.lora_port or "[red]Not found[/red]"
        shell_status = dev.shell_port or "[red]Not found[/red]"

        table.add_row(str(dev), bridge_status, lora_status, shell_status)

    print_empty_line()
    console.print(table)

    if debug:
        _print_raw_port_debug()


def _print_raw_port_debug() -> None:
    """Print raw pyserial port info for all CatSniffer interfaces."""
    from serial.tools import list_ports

    cat_ports = [
        p
        for p in list_ports.comports()
        if p.vid == CATSNIFFER_VID and p.pid == CATSNIFFER_PID
    ]

    if not cat_ports:
        console.print("[red]No CatSniffer USB interfaces visible to pyserial.[/red]")
        return

    raw = Table(title="Raw USB port info (debug)", box=box.SIMPLE)
    raw.add_column("Port", style="cyan")
    raw.add_column("Description")
    raw.add_column("HWID")
    raw.add_column("Location")
    raw.add_column("Interface")
    raw.add_column("Serial#")

    for p in sorted(cat_ports, key=lambda x: x.device):
        raw.add_row(
            p.device,
            p.description or "",
            p.hwid or "",
            p.location or "",
            getattr(p, "interface", None) or "",
            p.serial_number or "",
        )

    console.print(raw)


@cli.command()
@click.option(
    "--device",
    "-d",
    default=None,
    type=int,
    help="Device ID (for multiple CatSniffers)",
)
def identify(device) -> None:
    """Send identification command to CatSniffer device"""
    dev = get_device_or_exit(device)

    if not dev.shell_port:
        print_error("Shell port not available for this device!")
        exit(1)

    print_info(f"Sending 'Identify' command to {dev} on port {dev.shell_port}...")

    try:
        shell = ShellConnection(port=dev.shell_port, timeout=1.0)
        with shell:
            response = shell.send_command("identify", timeout=1.0)
            if response:
                print_info(f"Response: {response}")

        print_success("Identification command sent successfully!")

    except Exception as e:
        print_error(f"Failed to send identification command: {str(e)}")
        exit(1)


# ===================== Shell Completion Commands =====================


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def completion():
    """Install shell tab completion for catnip."""
    pass


@completion.command("install")
@click.option(
    "--shell",
    type=click.Choice(["bash", "zsh", "fish"]),
    default=None,
    help="Shell to install completion for (auto-detected if omitted)",
)
def completion_install(shell):
    """Install tab completion for your shell.

    Run this once, then restart your shell (or source your rc file).

    \b
        catnip completion install          # auto-detect shell
        catnip completion install --shell zsh
    """
    if platform.system() == "Windows":
        print_error("Shell completion is not supported on Windows.")
        sys.exit(1)

    import subprocess as _sp
    from pathlib import Path

    # Auto-detect shell
    if shell is None:
        shell_env = os.environ.get("SHELL", "")
        if "zsh" in shell_env:
            shell = "zsh"
        elif "fish" in shell_env:
            shell = "fish"
        elif "bash" in shell_env:
            shell = "bash"
        else:
            print_error("Could not detect shell. Use --shell bash|zsh|fish.")
            sys.exit(1)
        print_info(f"Detected shell: {shell}")

    env_var = "_CATNIP_COMPLETE"

    # Absolute path to this script and the Python interpreter running it.
    # We always want completions to call "python /abs/path/to/catnip.py" so
    # that they work regardless of whether catnip is on PATH.
    script_abs = str(Path(sys.argv[0]).resolve())
    python_abs = str(Path(sys.executable).resolve())
    # The full command string that the completion script will execute
    cmd_to_call = f"{python_abs} {script_abs}"

    if shell == "bash":
        target = (
            Path.home()
            / ".local"
            / "share"
            / "bash-completion"
            / "completions"
            / "catnip"
        )
        source_flag = "bash_source"
        rc_note = None
    elif shell == "zsh":
        target = Path.home() / ".zfunc" / "_catnip"
        source_flag = "zsh_source"
        rc_note = "fpath=(~/.zfunc $fpath)\nautoload -Uz compinit && compinit"
    elif shell == "fish":
        target = Path.home() / ".config" / "fish" / "completions" / "catnip.fish"
        source_flag = "fish_source"
        rc_note = None

    try:
        result = _sp.run(
            [python_abs, script_abs],
            env={**os.environ, env_var: source_flag},
            capture_output=True,
            text=True,
        )
        script = result.stdout
    except OSError as e:
        print_error(f"Failed to generate completion script: {e}")
        sys.exit(1)

    if not script.strip():
        print_error(
            "Empty completion script generated.\n"
            "Make sure you are running this command via:\n"
            f"  python {script_abs} completion install"
        )
        if result.stderr.strip():
            print_dim(result.stderr.strip())
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # Post-process: replace the bare 'catnip' program name that Click      #
    # embeds in the script with the full "python /abs/path/catnip.py"      #
    # invocation.  We handle every pattern Click 7.x / 8.x can emit.      #
    # ------------------------------------------------------------------ #
    if shell == "zsh":
        # 1. #compdef directive — register for all the names a user might type
        script = script.replace(
            "#compdef catnip", "#compdef catnip catnip.py ./catnip.py"
        )
        # 2. The guard that aborts when the command is not found in $commands[].
        #    We neutralise it because we use an absolute path, not a PATH entry.
        script = script.replace(
            "(( ! $+commands[catnip] ))",
            "false",  # 'false' evaluates to 1 so the (( )) block never returns
        )
        # 3. The line that actually calls the program to obtain completions.
        #    Click 8 emits:  _CATNIP_COMPLETE=zsh_complete catnip
        script = script.replace(
            f"{env_var}=zsh_complete catnip", f"{env_var}=zsh_complete {cmd_to_call}"
        )
        # 4. The compdef registration at the bottom of the script
        script = script.replace(
            "compdef _catnip_completion catnip",
            f"compdef _catnip_completion catnip catnip.py ./catnip.py",
        )

        # 5. Append an explicit wrapper so that "python catnip.py <TAB>" and
        #    "./catnip.py <TAB>" also trigger completion.  zsh matches on the
        #    last component of $words[1], so we register a catch-all that
        #    delegates to our function.
        extra = (
            "\n"
            "# Enable completion when invoked as 'python catnip.py' or './catnip.py'\n"
            "_catnip_completion_python_wrapper() {\n"
            "  local script_name=${words[2]:t}  # basename of the script argument\n"
            "  if [[ $script_name == catnip.py ]]; then\n"
            f"    (( ! $+functions[_catnip_completion] )) && source {target}\n"
            '    words=(catnip "${words[@]:2}")\n'
            "    (( CURRENT-- ))\n"
            "    _catnip_completion\n"
            "  else\n"
            "    _files\n"
            "  fi\n"
            "}\n"
            "compdef _catnip_completion_python_wrapper python python3\n"
        )
        script += extra

    elif shell == "bash":
        # Click <=8.0 emits:  _CATNIP_COMPLETE=bash_complete catnip
        # Click >=8.1 emits:  _CATNIP_COMPLETE=bash_complete $1
        script = script.replace(
            f"{env_var}=bash_complete catnip", f"{env_var}=bash_complete {cmd_to_call}"
        )
        script = script.replace(
            f"{env_var}=bash_complete $1", f"{env_var}=bash_complete {cmd_to_call}"
        )
        # Register for both 'catnip' and 'catnip.py' (Click 8.1 adds -o nosort)
        script = script.replace(
            "complete -F _catnip_completion catnip",
            "complete -F _catnip_completion catnip catnip.py",
        )
        script = script.replace(
            "complete -o nosort -F _catnip_completion catnip",
            "complete -o nosort -F _catnip_completion catnip catnip.py",
        )
        # Append a wrapper that intercepts 'python catnip.py <TAB>'
        extra = (
            "\n"
            "# Enable completion when invoked as 'python catnip.py'\n"
            "_catnip_completion_python_wrapper() {\n"
            "    local cur script_arg\n"
            '    cur="${COMP_WORDS[COMP_CWORD]}"\n'
            '    script_arg="${COMP_WORDS[1]}"\n'
            '    if [[ "$(basename "$script_arg")" == "catnip.py" ]]; then\n'
            "        # Rebuild COMP_WORDS without the leading 'python' / path\n"
            '        local new_words=(catnip "${COMP_WORDS[@]:2}")\n'
            '        COMP_WORDS=("${new_words[@]}")\n'
            "        COMP_CWORD=$(( COMP_CWORD - 1 ))\n"
            "        _catnip_completion\n"
            "    fi\n"
            "}\n"
            "complete -F _catnip_completion_python_wrapper python python3\n"
        )
        script += extra

    elif shell == "fish":
        # Fish uses a different mechanism; just replace the bare program name.
        # Click <=8.0 puts it right after the env var, >=8.1 after COMP_CWORD.
        script = script.replace(
            f"{env_var}=fish_complete catnip", f"{env_var}=fish_complete {cmd_to_call}"
        )
        script = script.replace(
            "COMP_CWORD=(commandline -t) catnip)",
            f"COMP_CWORD=(commandline -t) {cmd_to_call})",
        )
        # Also complete when invoked as './catnip.py'
        script += (
            "\ncomplete --no-files --command catnip.py "
            '--arguments "(_catnip_completion)"\n'
        )

    # Write script
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(script, encoding="utf-8")
    except OSError as e:
        print_error(f"could not write completion script to {target}: {e}")
        sys.exit(1)
    print_success(f"Completion script written to: {target}")

    # zsh needs fpath entry in .zshrc
    if rc_note:
        zshrc = Path.home() / ".zshrc"
        try:
            existing = zshrc.read_text(encoding="utf-8") if zshrc.exists() else ""
        except OSError as e:
            print_error(f"could not read {zshrc}: {e}")
            sys.exit(1)
        if "~/.zfunc" not in existing and ".zfunc" not in existing:
            try:
                if zshrc.exists():
                    backup = zshrc.with_name(".zshrc.bak-catnip")
                    backup.write_text(existing, encoding="utf-8")
                with zshrc.open("a", encoding="utf-8") as f:
                    f.write(f"\n# catnip tab completion\n{rc_note}\n")
            except OSError as e:
                print_error(f"could not update {zshrc}: {e}")
                sys.exit(1)
            print_success(f"Added fpath entry to {zshrc}")
        else:
            print_dim("~/.zfunc already in fpath — skipping .zshrc edit")

    print_empty_line()
    if shell == "bash":
        print_info("Restart your shell or run:")
        print_example(f"source {target}")
    elif shell == "zsh":
        print_info("Restart your shell or run:")
        print_example("source ~/.zshrc && compinit -u")
    elif shell == "fish":
        print_info("Completion is active immediately in new fish sessions.")


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


def build_cli() -> click.Group:
    """Register every command on the root group and return it assembled.

    Kept apart from :func:`main_cli` so the command tree can be inspected
    without running it (tests, snapshot dumps).
    """
    cli.add_command(_sniff)
    cli.add_command(_cativity)
    cli.add_command(_meshtastic)
    cli.add_command(_flash)
    cli.add_command(_update)
    cli.add_command(_restore)
    cli.add_command(_lora)
    if platform.system() == "Linux":
        cli.add_command(_vhci)
        cli.add_command(setup_env)
    cli.add_command(_verify)
    if platform.system() in ["Linux", "Darwin"]:
        cli.add_command(completion)
    return cli


def main_cli() -> None:
    if not os.environ.get("_CATNIP_COMPLETE"):
        module = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
        print_header(module)
    build_cli()(prog_name="catnip")
