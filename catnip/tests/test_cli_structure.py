"""
test_cli_structure.py
=====================
Safety net for the CLI refactor described in ``CLI_REFACTOR_PLAN.md``.

The refactor moves ~2 300 lines of Click commands out of ``modules/core/cli.py``
into per-feature ``cli.py`` modules.  The one failure mode that a build would
*not* catch is a command that silently stops being registered: the binary still
builds, the tests still pass, and the subcommand is simply gone.

These tests pin the shape of the assembled command tree — every command, every
subcommand and every option flag — so an incomplete migration fails loudly.

Companion tool: ``scripts/dump_cli_tree.py`` dumps the full ``--help`` text of
every command; ``tests/snapshots/cli_tree_linux.txt`` is the Phase 0 reference.
That diff also covers help *wording*, but it is Click-version sensitive, so it
is a manual check rather than a test.
"""

import platform
import re
from pathlib import Path

import click
import pytest

from modules.core.cli import build_cli


# ─────────────────────────────────────────────────────────────────────────────
# Expected tree (captured at Phase 0, on Linux)
#
# Keys are full command paths.  Values are every option flag declared by the
# command, plus ``<name>`` entries for positional arguments, sorted.  The
# implicit ``-h/--help`` is added by Click at render time and never appears
# here.
# ─────────────────────────────────────────────────────────────────────────────

EXPECTED_PARAMS = {
    "catnip": ["--verbose", "-v"],
    "catnip cativity": [
        "--channel",
        "--device",
        "--protocol",
        "--topology",
        "-c",
        "-d",
        "-p",
        "-t",
    ],
    "catnip completion": [],
    "catnip completion install": ["--shell"],
    "catnip devices": ["--debug"],
    "catnip flash": ["--device", "--full", "--list", "-d", "-l", "<firmware>"],
    "catnip identify": ["--device", "-d"],
    "catnip lora": [],
    "catnip lora spectrum": [
        "--baudrate",
        "--device",
        "--end-freq",
        "--offset",
        "--start-freq",
        "-b",
        "-d",
    ],
    "catnip meshtastic": [],
    "catnip meshtastic config": ["<file>"],
    "catnip meshtastic dashboard": [
        "--baudrate",
        "--device",
        "--frequency",
        "--preset",
        "-baud",
        "-d",
        "-f",
        "-ps",
    ],
    "catnip meshtastic decode": ["--input", "--key", "-i", "-k"],
    "catnip meshtastic live": [
        "--baudrate",
        "--device",
        "--frequency",
        "--preset",
        "-baud",
        "-d",
        "-f",
        "-ps",
    ],
    "catnip restore": ["--device", "--tapid", "-d", "<firmware>"],
    "catnip setup-env": [],
    "catnip sniff": ["--verbose", "-v"],
    "catnip sniff airtag_scanner": ["--device", "--putty", "-d"],
    "catnip sniff ble": [
        "--channel",
        "--device",
        "--mode",
        "--wireshark",
        "-c",
        "-d",
        "-m",
        "-ws",
    ],
    "catnip sniff lora": [
        "--ascii",
        "--bandwidth",
        "--coding_rate",
        "--device",
        "--frequency",
        "--raw",
        "--spread_factor",
        "--sync-word",
        "--tx_power",
        "--verbose",
        "-ascii",
        "-bw",
        "-cr",
        "-d",
        "-freq",
        "-pw",
        "-r",
        "-sf",
        "-sw",
        "-v",
        "-ws",
    ],
    "catnip sniff thread": [
        "--ascii",
        "--channel",
        "--device",
        "--raw",
        "-ascii",
        "-c",
        "-d",
        "-r",
        "-ws",
    ],
    "catnip sniff zigbee": [
        "--ascii",
        "--channel",
        "--device",
        "--raw",
        "-ascii",
        "-c",
        "-d",
        "-r",
        "-ws",
    ],
    "catnip status": ["--device", "-d"],
    "catnip update": ["--device", "--force", "-d", "-f"],
    "catnip verify": ["--device", "--quiet", "--test-all", "-d", "-q"],
    "catnip vhci": [],
    "catnip vhci check": [],
    "catnip vhci start": ["--baud", "--device", "--verbose", "-d", "-v"],
}

# Commands that must stay ``click.Group`` (i.e. keep accepting subcommands).
EXPECTED_GROUPS = {
    "catnip",
    "catnip completion",
    "catnip lora",
    "catnip meshtastic",
    "catnip sniff",
    "catnip vhci",
}

# ``build_cli()`` registers these conditionally; mirror that here so the test
# is meaningful on every OS instead of only on Linux.
LINUX_ONLY = ("catnip vhci", "catnip setup-env")
NOT_ON_WINDOWS = ("catnip completion",)


def _is_expected_here(path: str) -> bool:
    system = platform.system()
    if path.startswith(LINUX_ONLY) and system != "Linux":
        return False
    if path.startswith(NOT_ON_WINDOWS) and system not in ("Linux", "Darwin"):
        return False
    return True


def _walk(command, path):
    """Yield ``(path, command)`` for the whole tree, depth first."""
    yield " ".join(path), command
    if isinstance(command, click.Group):
        ctx = click.Context(command)
        for name in command.list_commands(ctx):
            child = command.get_command(ctx, name)
            if child is not None:
                yield from _walk(child, path + [name])


def _actual_tree():
    return dict(_walk(build_cli(), ["catnip"]))


def _param_signature(command):
    """Option flags declared by ``command``, plus ``<arg>`` for arguments."""
    found = []
    for param in command.params:
        if isinstance(param, click.Argument):
            found.append(f"<{param.name}>")
        else:
            found.extend(param.opts + param.secondary_opts)
    return sorted(found)


def _expected_paths():
    return {p for p in EXPECTED_PARAMS if _is_expected_here(p)}


@pytest.mark.unit
def test_every_expected_command_is_registered():
    """No command may disappear while being moved to another module."""
    missing = sorted(_expected_paths() - set(_actual_tree()))
    assert not missing, f"commands no longer registered: {missing}"


@pytest.mark.unit
def test_no_unexpected_command_appeared():
    """A renamed command shows up here as one addition plus one removal."""
    extra = sorted(set(_actual_tree()) - _expected_paths())
    assert not extra, f"unexpected commands registered: {extra}"


@pytest.mark.unit
@pytest.mark.parametrize("path", sorted(_expected_paths()))
def test_options_are_preserved(path):
    """Moving a command must not drop or rename any of its flags."""
    command = _actual_tree().get(path)
    assert command is not None, f"{path!r} is not registered"
    assert _param_signature(command) == sorted(EXPECTED_PARAMS[path])


@pytest.mark.unit
@pytest.mark.parametrize("path", sorted(_expected_paths()))
def test_group_and_command_kinds_are_preserved(path):
    """A group must stay a group, and a leaf command must stay a leaf."""
    command = _actual_tree()[path]
    assert isinstance(command, click.Group) is (path in EXPECTED_GROUPS)


@pytest.mark.unit
@pytest.mark.parametrize("path", sorted(_expected_paths()))
def test_every_command_has_help_text(path):
    """``catnip --help`` lists commands by their docstring; none may be blank."""
    command = _actual_tree()[path]
    assert command.help or command.short_help, f"{path!r} has no help text"


@pytest.mark.unit
def test_build_cli_is_idempotent():
    """``build_cli()`` mutates a module-level group; calling it twice is safe."""
    first = sorted(_actual_tree())
    second = sorted(_actual_tree())
    assert first == second


# ─────────────────────────────────────────────────────────────────────────────
# Packaging invariants the refactor must not break (CLI_REFACTOR_PLAN.md §2)
# ─────────────────────────────────────────────────────────────────────────────

_MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"


@pytest.mark.unit
def test_every_package_under_modules_has_an_init():
    """Rule 2: ``find_packages()`` silently drops a directory without one.

    The .deb/Arch builds would still work (implicit namespace packages), so a
    missing ``__init__.py`` only surfaces as a ``pip install .`` that is short a
    few commands, with a green build.
    """
    missing = sorted(
        str(d.relative_to(_MODULES_DIR.parent))
        for d in _MODULES_DIR.rglob("*")
        if d.is_dir() and d.name != "__pycache__" and not (d / "__init__.py").exists()
    )
    assert not missing, f"packages without __init__.py: {missing}"


@pytest.mark.unit
def test_feature_cli_modules_do_not_import_core_cli():
    """Invariant §2.3: the dependency between CLI modules only points one way.

    ``core/cli.py`` imports the feature CLI modules.  If one of them imports
    back from ``modules.core.cli`` the result is an import cycle; shared
    helpers belong in a Click-free module instead.

    Covers the three layouts in use: ``modules/<feature>/cli.py``, the
    ``modules/protocols/cli/<protocol>.py`` subpackage -- which exists because
    the protocol packages' own ``__init__.py`` eagerly import matplotlib, the
    ``meshtastic`` library and ``fcntl`` -- and the command modules that live
    straight inside ``modules/utils/``.
    """
    candidates = set(_MODULES_DIR.rglob("cli.py"))
    candidates |= set((_MODULES_DIR / "protocols" / "cli").glob("*.py"))
    candidates |= {
        _MODULES_DIR / "utils" / "completion.py",
        _MODULES_DIR / "utils" / "system_cli.py",
    }
    offenders = []
    for path in sorted(candidates):
        if path == _MODULES_DIR / "core" / "cli.py":
            continue
        source = path.read_text(encoding="utf-8")
        if re.search(
            r"^\s*from\s+\S*core\.cli\s+import|^\s*import\s+\S*core\.cli",
            source,
            re.MULTILINE,
        ):
            offenders.append(str(path.relative_to(_MODULES_DIR.parent)))
    assert not offenders, f"modules importing from core.cli: {offenders}"
