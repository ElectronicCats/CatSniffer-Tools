"""Typed exception hierarchy for catnip, mapped to documented exit codes.

``main_cli()`` (``modules/core/cli.py``) is the single place that turns these
into a process exit code, so raising the right subclass here is what decides
what the user sees and what the shell gets back.

Exit codes:
    0   success
    1   generic/unexpected error
    2   usage error (Click's own ``ClickException``)
    3   firmware error
    4   device/connection error
    5   not supported on the connected board generation
    130 interrupted (Ctrl-C / Abort)
"""

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_FIRMWARE = 3
EXIT_CONNECTION = 4
EXIT_UNSUPPORTED = 5
EXIT_INTERRUPT = 130


class CatnipError(Exception):
    """Base class for all catnip-specific errors.

    Subclasses may set ``hint`` (a list of numbered steps to show the user)
    so ``main_cli`` can render an actionable panel instead of a bare line.
    """

    exit_code = EXIT_ERROR
    hint: list[str] | None = None

    def __init__(self, message: str, *, hint: list[str] | None = None):
        super().__init__(message)
        if hint is not None:
            self.hint = hint


class ValidationError(CatnipError):
    """User-supplied input is invalid in a way Click's own validators missed."""

    exit_code = EXIT_USAGE


class DeviceError(CatnipError):
    """No suitable CatSniffer device could be found or selected."""

    exit_code = EXIT_CONNECTION


class ConnectionError(CatnipError):
    """Opening or talking to a serial port failed."""

    exit_code = EXIT_CONNECTION


class FirmwareError(CatnipError):
    """Firmware detection, flashing, updating, or verification failed."""

    exit_code = EXIT_FIRMWARE


class UnsupportedOnBoardError(CatnipError):
    """The connected board generation cannot do what was asked.

    Distinct from :class:`FirmwareError` on purpose: nothing went wrong and
    retrying will not help, the hardware simply does not have the part (a
    v2 has no NVS, no RP2040 to run a CMSIS-DAP probe on, and no CC1352P7
    image built for it).  Its own exit code lets a script tell "this board
    cannot" apart from "this failed".
    """

    exit_code = EXIT_UNSUPPORTED


class ProtocolError(CatnipError):
    """A wire protocol (sniffer/shell/vhci handshake, ...) got bad data."""

    exit_code = EXIT_ERROR
