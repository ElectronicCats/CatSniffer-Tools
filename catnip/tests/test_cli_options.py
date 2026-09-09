"""
test_cli_options.py
===================
Invariants for the shared Click options in ``modules/utils/cli_options.py``
(``BOMBERCAT_PARITY.md`` section 1).

``--device`` used to be declared 15 times across 7 modules.  Consolidating the
declaration is only worth something if it stays consolidated, so these tests
pin both halves of that: the *rendered* option is identical everywhere, and no
module re-declares it by hand.

Companion: ``test_cli_structure.py`` pins which flags each command has; this
file pins that the device selector always means the same thing.
"""

import re
from pathlib import Path

import click
import pytest

from modules.core.cli import build_cli
from modules.utils.cli_options import (
    ASCII_HELP,
    DEVICE_HELP,
    PCAP_HELP,
    RAW_HELP,
    device_option,
)


_MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"

# Commands that deliberately narrow the meaning of ``-d/--device`` and so carry
# their own help text.  Everything else must use the canonical wording.
CUSTOM_DEVICE_HELP = {
    "catnip flash",
    "catnip restore",
    "catnip verify",
}


def _walk(command, path):
    yield " ".join(path), command
    if isinstance(command, click.Group):
        ctx = click.Context(command)
        for name in command.list_commands(ctx):
            child = command.get_command(ctx, name)
            if child is not None:
                yield from _walk(child, path + [name])


def _commands_with_device():
    """``(path, param)`` for every command that takes a device selector."""
    for path, command in _walk(build_cli(), ["catnip"]):
        for param in command.params:
            if param.name == "device":
                yield path, param


@pytest.mark.unit
def test_at_least_one_command_uses_the_device_option():
    """Guards the two tests below against silently iterating over nothing."""
    assert len(list(_commands_with_device())) >= 15


@pytest.mark.unit
@pytest.mark.parametrize(
    "path,param", sorted(_commands_with_device(), key=lambda pair: pair[0])
)
def test_device_option_is_uniform(path, param):
    """Same flags, same type and same default in every command."""
    assert param.opts == ["--device", "-d"], path
    assert param.type is click.INT, path
    assert param.default is None, path
    assert not param.required, path


@pytest.mark.unit
@pytest.mark.parametrize(
    "path,param", sorted(_commands_with_device(), key=lambda pair: pair[0])
)
def test_device_help_is_canonical_unless_listed(path, param):
    """A command may override the help text, but not by accident."""
    if path in CUSTOM_DEVICE_HELP:
        assert param.help != DEVICE_HELP, f"{path} no longer needs an override"
    else:
        assert param.help == DEVICE_HELP, path


@pytest.mark.unit
def test_no_module_redeclares_the_device_option():
    """A hand-rolled ``click.option("--device", ...)`` is how the drift starts.

    ``firmware/verify.py`` is exempt: its ``--device`` belongs to an
    ``argparse`` parser used when the module is run standalone, not to the CLI.
    """
    exempt = {
        _MODULES_DIR / "utils" / "cli_options.py",
        _MODULES_DIR / "firmware" / "verify.py",
    }
    offenders = []
    for path in sorted(_MODULES_DIR.rglob("*.py")):
        if path in exempt:
            continue
        source = path.read_text(encoding="utf-8")
        if re.search(r'click\.option\(\s*\n?\s*"-(?:-device|d)"', source):
            offenders.append(str(path.relative_to(_MODULES_DIR.parent)))
    assert not offenders, f"modules declaring --device by hand: {offenders}"


@pytest.mark.unit
def test_device_option_forwards_extra_keywords():
    """The factory has to stay a thin wrapper over ``click.option``."""

    @click.command()
    @device_option(help="custom", show_default=True)
    def command(device):  # pragma: no cover - never invoked
        pass

    param = command.params[0]
    assert param.help == "custom"
    assert param.show_default is True


# ─────────────────────────────────────────────────────────────────────────────
# Capture-file options (``sniff zigbee|thread|lora``)
# ─────────────────────────────────────────────────────────────────────────────

# ``sniff lora`` records carry an extra SNR field, so its help text differs.
CUSTOM_CAPTURE_HELP = {"catnip sniff lora"}

_CAPTURE_PARAMS = {"raw_file": RAW_HELP, "ascii_file": ASCII_HELP}


def _commands_with_capture_files():
    for path, command in _walk(build_cli(), ["catnip"]):
        for param in command.params:
            if param.name in _CAPTURE_PARAMS:
                yield path, param


@pytest.mark.unit
def test_every_sniffer_with_capture_files_has_both():
    """``--raw`` and ``--ascii`` are a pair; one without the other is a bug."""
    found = {}
    for path, param in _commands_with_capture_files():
        found.setdefault(path, set()).add(param.name)
    assert found, "no command declares the capture-file options"
    for path, names in sorted(found.items()):
        assert names == set(_CAPTURE_PARAMS), path


@pytest.mark.unit
@pytest.mark.parametrize(
    "path,param", sorted(_commands_with_capture_files(), key=lambda pair: pair[0])
)
def test_capture_file_options_are_uniform(path, param):
    """Same flags, same type and same default in every sniffer."""
    expected_opts = {
        "raw_file": ["--raw", "-r"],
        "ascii_file": ["-ascii", "--ascii"],
    }[param.name]
    assert param.opts == expected_opts, path
    assert isinstance(param.type, click.Path), path
    assert param.default is None, path
    if path in CUSTOM_CAPTURE_HELP:
        assert param.help != _CAPTURE_PARAMS[param.name], f"{path} override is stale"
    else:
        assert param.help == _CAPTURE_PARAMS[param.name], path


# ─────────────────────────────────────────────────────────────────────────────
# PCAP capture-file options (``sniff zigbee|thread|lora``)
# ─────────────────────────────────────────────────────────────────────────────


def _commands_with_pcap_file():
    for path, command in _walk(build_cli(), ["catnip"]):
        for param in command.params:
            if param.name == "pcap_file":
                yield path, param


@pytest.mark.unit
def test_every_sniffer_that_logs_text_also_writes_pcap():
    """``--raw``/``--ascii`` without ``-w`` means a protocol lost its capture file.

    The text logs and the PCAP sink cover the same commands on purpose: one is
    for eyeballing, the other is the reusable artefact.  A sniffer that grew
    the first pair but not the second is the drift this catches.
    """
    with_text = {path for path, _ in _commands_with_capture_files()}
    with_pcap = {path for path, _ in _commands_with_pcap_file()}
    assert with_text, "no command declares the capture-file options"
    assert with_text == with_pcap


@pytest.mark.unit
@pytest.mark.parametrize(
    "path,param", sorted(_commands_with_pcap_file(), key=lambda pair: pair[0])
)
def test_pcap_file_option_is_uniform(path, param):
    """Same flags, same type, same help in every sniffer."""
    assert param.opts == ["--write", "-w"], path
    assert isinstance(param.type, click.Path), path
    assert param.default is None, path
    assert param.help == PCAP_HELP, path


@pytest.mark.unit
@pytest.mark.parametrize(
    "path,param", sorted(_commands_with_pcap_file(), key=lambda pair: pair[0])
)
def test_pcap_file_option_comes_with_force(path, param):
    """``-w`` truncates, so the command has to offer a way to opt into that.

    Without ``--force`` the refusal message (``pass --force to overwrite it``)
    would name a flag that does not exist.
    """
    command = dict(_walk(build_cli(), ["catnip"]))[path]
    force = next((p for p in command.params if p.name == "force"), None)
    assert force is not None, f"{path} has --write but no --force"
    assert force.opts == ["--force", "-f"], path
    assert force.is_flag, path
    assert force.default is False, path


# ─────────────────────────────────────────────────────────────────────────────
# Choice defaults
# ─────────────────────────────────────────────────────────────────────────────


def _choice_params():
    for path, command in _walk(build_cli(), ["catnip"]):
        for param in command.params:
            if isinstance(param.type, click.Choice):
                yield path, param


@pytest.mark.unit
def test_at_least_one_command_uses_a_choice_option():
    """Guards the test below against silently iterating over nothing."""
    assert len(list(_choice_params())) >= 5


@pytest.mark.unit
@pytest.mark.parametrize(
    "path,param", sorted(_choice_params(), key=lambda pair: (pair[0], pair[1].name))
)
def test_choice_defaults_are_one_of_the_choices(path, param):
    """A default outside its own ``Choice`` breaks the command on Click 8.0/8.1.

    ``sniff lora`` shipped ``default=125`` against ``Choice(["125", ...])``.
    Click <8.2 matches the default against the choices without stringifying it,
    so the command failed with *"125 is not one of '125', '250', '500'"* unless
    the user passed ``-bw`` explicitly — i.e. it was unusable at its own
    defaults.  Click >=8.2 coerces first and hides it, which is exactly why
    this needs a test rather than a passing manual run.  ``setup.py`` allows
    ``click>=8.0.0``, so both behaviours are in scope.
    """
    if param.default is None:
        return
    assert param.default in param.type.choices, (
        f"{path} {param.opts}: default {param.default!r} "
        f"({type(param.default).__name__}) is not one of {param.type.choices}"
    )
