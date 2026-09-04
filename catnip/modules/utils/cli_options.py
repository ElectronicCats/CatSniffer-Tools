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
