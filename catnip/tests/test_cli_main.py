"""
test_cli_main.py
================
Exit-code contract of ``modules.core.cli.main_cli`` (``BOMBERCAT_PARITY.md``
section 2).

``main_cli`` runs Click with ``standalone_mode=False``, which moves the
translation from exception to exit code out of Click and into us.  That is a
sharp edge in two directions, so both are pinned here:

* the codes users already depend on must not move (``0`` for ``--help``, ``2``
  for a usage error, whatever a command's own ``sys.exit()`` says);
* a value *returned* by a command now becomes its exit code, where Click used
  to discard it -- see ``test_no_cli_command_returns_a_value``.

``tests/test_catsniffer.py::TestCLISubprocess`` covers the same ground through
real subprocesses; these tests are the fast, hermetic half.
"""

import ast
import re
from pathlib import Path

import click
import pytest

from modules.core import cli as core_cli


_MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"


@pytest.fixture
def run_main(monkeypatch):
    """Run ``main_cli`` over a one-command CLI and return the exit code.

    The header is not suppressed on purpose: it is printed before Click ever
    runs, so anything that breaks it would break every invocation.
    """

    def run(command, argv):
        group = click.Group("catnip", context_settings={"help_option_names": ["-h", "--help"]})
        if command is not None:
            group.add_command(command)
        monkeypatch.setattr(core_cli, "build_cli", lambda: group)
        monkeypatch.setattr("sys.argv", ["catnip"] + argv)
        with pytest.raises(SystemExit) as excinfo:
            core_cli.main_cli()
        return excinfo.value.code

    return run


def _command(name="boom", **kwargs):
    def decorator(func):
        return click.command(name, **kwargs)(func)

    return decorator


# ─────────────────────────────────────────────────────────────────────────────
# Codes that must not move
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_exits_zero(run_main, flag):
    """``standalone_mode=False`` makes ``--help`` *return*; we must still exit 0."""
    assert run_main(None, [flag]) == 0


@pytest.mark.unit
def test_unknown_command_exits_two(run_main, capsys):
    assert run_main(None, ["nope"]) == 2
    assert "No such command" in capsys.readouterr().err


@pytest.mark.unit
def test_usage_error_is_shown_and_exits_two(run_main, capsys):
    """Click no longer prints these itself; ``main_cli`` has to."""

    @_command()
    def boom():
        raise click.UsageError("bad usage here")

    assert run_main(boom, ["boom"]) == 2
    assert "bad usage here" in capsys.readouterr().err


@pytest.mark.unit
def test_command_sys_exit_travels_through(run_main):
    """``SystemExit`` is not an ``Exception``; the broad handler must miss it."""

    @_command()
    def boom():
        raise SystemExit(3)

    assert run_main(boom, ["boom"]) == 3


@pytest.mark.unit
def test_command_returning_nothing_exits_zero(run_main):
    @_command()
    def boom():
        return None

    assert run_main(boom, ["boom"]) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Codes that the change introduces
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_keyboard_interrupt_exits_130(run_main):
    """Click turns the interrupt into an ``Abort`` before we see it."""

    @_command()
    def boom():
        raise KeyboardInterrupt

    assert run_main(boom, ["boom"]) == 130


@pytest.mark.unit
def test_abort_exits_130(run_main):
    @_command()
    def boom():
        raise click.exceptions.Abort()

    assert run_main(boom, ["boom"]) == 130


@pytest.mark.unit
def test_unexpected_exception_is_one_line(run_main, monkeypatch):
    """A crash becomes one readable line, not a traceback.

    ``print_error`` is recorded rather than captured through ``capsys``:
    ``tests/test_catsniffer.py`` stubs ``rich.console`` in ``sys.modules`` at
    import time, so the shared console is a ``MagicMock`` once the whole suite
    runs together.
    """
    printed = []
    monkeypatch.setattr(core_cli, "print_error", printed.append)

    @_command()
    def boom():
        raise ValueError("something went sideways")

    assert run_main(boom, ["boom"]) == 1
    assert len(printed) == 1
    assert "ValueError: something went sideways" in printed[0]
    assert "CATNIP_DEBUG=1" in printed[0]
    assert "Traceback" not in printed[0]


@pytest.mark.unit
def test_catnip_debug_re_raises(run_main, monkeypatch):
    """The escape hatch: the original exception, with its traceback."""
    monkeypatch.setenv("CATNIP_DEBUG", "1")

    @_command()
    def boom():
        raise ValueError("something went sideways")

    with pytest.raises(ValueError, match="something went sideways"):
        run_main(boom, ["boom"])


# ─────────────────────────────────────────────────────────────────────────────
# The invariant ``standalone_mode=False`` creates
# ─────────────────────────────────────────────────────────────────────────────

_CLI_SOURCES = (
    sorted(_MODULES_DIR.rglob("cli.py"))
    + sorted((_MODULES_DIR / "protocols" / "cli").glob("*.py"))
    + [_MODULES_DIR / "utils" / "completion.py", _MODULES_DIR / "utils" / "system_cli.py"]
)


def _returns_a_value(path):
    """``(function, lineno)`` for every Click callback returning something."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = [ast.unparse(d) for d in node.decorator_list]
        if not any(re.search(r"\.(command|group)\b|^click\.(command|group)", d) for d in decorators):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and child.value is not None:
                yield node.name, child.lineno


@pytest.mark.unit
@pytest.mark.parametrize(
    "path", _CLI_SOURCES, ids=lambda p: str(p.relative_to(_MODULES_DIR))
)
def test_no_cli_command_returns_a_value(path):
    """A returned value is now the process exit code -- say so with ``sys.exit``.

    Click used to drop whatever a callback returned (its own source calls it
    "not safe to ``ctx.exit(rv)``").  With ``standalone_mode=False`` the value
    reaches ``raise SystemExit(rv or 0)``, so ``return 1`` would quietly become
    an exit code and ``return "text"`` would print itself to stderr and exit 1.
    """
    offenders = [f"{path.name}:{lineno} in {name}" for name, lineno in _returns_a_value(path)]
    assert not offenders, f"Click callbacks returning a value: {offenders}"
