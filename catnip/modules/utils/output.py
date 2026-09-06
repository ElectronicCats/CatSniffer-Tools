"""
output.py - Shared Rich console and output helpers for all modules
"""

import os
import re

from rich.console import Console
from rich.style import Style
from rich.panel import Panel

STYLES = {
    "header": Style(color="cyan", bold=True),
    "success": Style(color="green", bold=True),
    "warning": Style(color="yellow", bold=True),
    "error": Style(color="red", bold=True),
    "info": Style(color="blue", bold=True),
    "dim": Style(dim=True),
    "prompt": Style(color="magenta", bold=True),
    "device": Style(color="cyan"),
}

console = Console()


def print_success(message: str) -> None:
    console.print(f"[green]✓[/green] {message}", style=STYLES["success"])


def print_warning(message: str) -> None:
    console.print(f"[yellow]⚠[/yellow] {message}", style=STYLES["warning"])


def print_error(message: str) -> None:
    console.print(f"[red]✗[/red] {message}", style=STYLES["error"])


def print_info(message: str) -> None:
    console.print(f"[blue]ℹ[/blue] {message}", style=STYLES["info"])


def print_dim(message: str) -> None:
    console.print(f"  {message}", style=STYLES["dim"])


def print_step(step: int, total: int, message: str) -> None:
    console.print(f"[bold]Step {step}/{total}: {message}[/bold]")


def print_section(title: str) -> None:
    sep = "═" * 51
    console.print("")
    console.print(f"[bold]{sep}[/bold]")
    console.print(f"[bold]  {title}[/bold]")
    console.print(f"[bold]{sep}[/bold]")
    console.print("")


def print_empty_line() -> None:
    console.print("")


def print_title(message: str) -> None:
    console.print(f"\n[cyan bold]{message}[/cyan bold]")


def print_subtitle(message: str) -> None:
    console.print(f"\n  [yellow]{message}[/yellow]")


def print_example(command: str, description: str = "") -> None:
    if description:
        # Align descriptions somewhat manually if needed, or just print
        console.print(f"  [green]{command}[/green] {description}")
    else:
        console.print(f"  [green]{command}[/green]")


def print_alias_item(aliases: str, description: str, pad: int = 15) -> None:
    # If multiple aliases separated by '/', split and colorize
    parts = [p.strip() for p in aliases.split("/")]
    colored_aliases = " / ".join(f"[green]{p}[/green]" for p in parts)

    # Calculate visible length for padding
    visible_len = sum(len(p) for p in parts) + 3 * (len(parts) - 1)
    padding = " " * max(0, pad - visible_len)

    console.print(f"    {colored_aliases}{padding} → {description}")


def print_error_panel(
    title: str,
    problem: str,
    why: str = "",
    fix: list[str] | None = None,
    notes: list[str] | None = None,
) -> None:
    """Print a structured, actionable error: problem, cause, numbered fix steps, notes."""
    lines = [f"[bold]Problem:[/bold] {problem}"]
    if why:
        lines.append(f"[bold]Why:[/bold] {why}")
    if fix:
        lines.append("")
        lines.append("[bold]Fix:[/bold]")
        lines.extend(f"  {i}. {step}" for i, step in enumerate(fix, 1))
    if notes:
        lines.append("")
        lines.extend(f"[dim]Note: {note}[/dim]" for note in notes)

    console.print(
        Panel(
            "\n".join(lines),
            title=f"[red bold]✗ {title}[/red bold]",
            border_style=STYLES["error"],
            title_align="left",
            padding=(1, 2),
        )
    )


def print_success_panel(
    title: str, message: str, notes: list[str] | None = None
) -> None:
    """Print a structured success panel, mirroring print_error_panel."""
    lines = [message]
    if notes:
        lines.append("")
        lines.extend(f"[dim]{note}[/dim]" for note in notes)

    console.print(
        Panel(
            "\n".join(lines),
            title=f"[green bold]✓ {title}[/green bold]",
            border_style=STYLES["success"],
            title_align="left",
            padding=(1, 2),
        )
    )


# Field names whose values look like credentials and should never reach a
# terminal, log file, or crash report verbatim.
_SECRET_FIELD = r"(?:psk|password|passwd|secret|token|api[_-]?key|admin[_-]?key)"
_SECRET_PATTERN = re.compile(
    rf'(?i)("{_SECRET_FIELD}"\s*:\s*")([^"]*)(")' rf"|({_SECRET_FIELD}\s*[:=]\s*)(\S+)"
)


def redact_secrets(text: str) -> str:
    """Redact password/PSK/token/key-shaped values from a string.

    Used before printing tracebacks, debug output, or error messages that
    might echo back user-supplied config (e.g. Meshtastic PSKs, WiFi
    passwords) so secrets never land in a terminal scrollback or log file.
    """

    def _redact(match: "re.Match[str]") -> str:
        if match.group(1) is not None:
            return f"{match.group(1)}(redacted){match.group(3)}"
        return f"{match.group(4)}(redacted)"

    return _SECRET_PATTERN.sub(_redact, text)


def print_error_section(title: str) -> None:
    sep = "═" * 51
    console.print("")
    console.print(f"[bold red]{sep}[/bold red]")
    console.print(f"[bold red]  ⚠  {title}[/bold red]")
    console.print(f"[bold red]{sep}[/bold red]")
    console.print("")


def print_success_section(title: str) -> None:
    sep = "═" * 39
    console.print("")
    console.print(f"[green bold]{sep}[/green bold]")
    console.print(f"[green bold]  ✓  {title}[/green bold]")
    console.print(f"[green bold]{sep}[/green bold]")
    console.print("")


def print_instruction_step(step_num: int, instruction: str) -> None:
    # Prints formatted step instruction, keeping rich markup in instruction if passed
    console.print(f"  [white]{step_num}.[/white] {instruction}")


# Test output helpers with quiet mode support
_quiet_mode = False


def set_quiet_mode(quiet: bool) -> None:
    """Set quiet mode - suppresses detailed output."""
    global _quiet_mode
    _quiet_mode = quiet


def is_quiet_mode() -> bool:
    """Check if quiet mode is enabled."""
    return _quiet_mode


def print_test_header(title: str) -> None:
    """Print a test section header with panel."""
    if not _quiet_mode:
        console.print(Panel(f"[bold cyan]{title}[/bold cyan]", border_style="cyan"))


def print_test_step(step_name: str, description: str) -> None:
    """Print a test step header."""
    if not _quiet_mode:
        console.print(f"\n[blue][{step_name.upper()}][/blue] {description}...")


def print_test_pass(details: str = "", max_length: int = 100) -> None:
    """Print a test pass result with optional details."""
    if not _quiet_mode:
        console.print("[green]  ✓ PASS[/green]")
        if details:
            if len(details) > max_length:
                console.print(f"[dim]  Response: {details[:max_length]}...[/dim]")
            else:
                console.print(f"[dim]  Response: {details}[/dim]")


def print_test_fail(details: str = "") -> None:
    """Print a test fail result. Always printed, with optional details."""
    console.print("[red]  ✗ FAIL[/red]")
    if details:
        if len(details) > 100:
            console.print(f"[red]  Got: {details[:100]}[/red]")
        else:
            console.print(f"[red]  Got: {details}[/red]")


def print_test_summary(passed: int, total: int, test_type: str = "") -> None:
    """Print test summary line."""
    msg = f"{passed}/{total}"
    if test_type:
        msg += f" {test_type}"
    msg += " tests passed"
    console.print(f"\n[bold]Summary:[/bold] [green]{msg}[/green]")


def print_next_steps(steps: list[str]) -> None:
    """Print contextual "what to run next" suggestions after a command.

    Mirrors Bombercat's `status`/`relay run` pattern of pointing at the next
    likely command instead of leaving the user to guess (see
    analisis-bombercat-vs-catnip.md, section 3).
    """
    if not steps:
        return
    console.print("\n[bold]Next steps:[/bold]")
    for step in steps:
        console.print(f"  [green]{step}[/green]")


def print_instruction_block(title: str, items: list[str]) -> None:
    """Print an instruction block with title and numbered items."""
    console.print(f"[yellow]  {title}[/yellow]")
    for item in items:
        console.print(f"    {item}")


def print_detail_message(message: str, indent: int = 2) -> None:
    """Print a detail message with optional indentation."""
    indent_str = " " * indent
    console.print(f"{indent_str}{message}")


def print_separator(char: str = "=", width: int = 60) -> None:
    """Print a separator line."""
    console.print(char * width)


def print_raw(text: str) -> None:
    """Print raw text without additional formatting."""
    console.print(text)


def refuse_overwrite(path: str, force: bool = False, mode: str = "warn") -> bool:
    """Guard against silently clobbering or mixing into an existing output file.

    Mirrors Bombercat's ``refuse_overwrite()`` (analisis-bombercat-vs-catnip.md,
    section 6), adapted to the two ways catnip actually writes user-facing
    output files today:

    - ``mode="warn"`` (raw/ascii capture logs, which are opened in append
      mode): never blocks — an existing file is a legitimate "keep
      capturing" use case — but tells the user their new capture will be
      appended to, rather than silently mixing sessions with no visible
      trace. Returns True always.
    - ``mode="block"`` (for a future export that truncates, e.g. CSV/JSON):
      returns False when ``path`` exists and ``force`` is not set, so the
      caller can refuse to proceed unless the user passes ``--force``.

    Returns True when it is safe to proceed (open/write), False when the
    caller should abort.
    """
    if not path or not os.path.exists(path):
        return True
    if mode == "block" and not force:
        print_warning(f"{path} already exists — pass --force to overwrite it")
        return False
    print_warning(f"{path} already exists — new data will be appended to it")
    return True


_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")


def csv_safe(value: str) -> str:
    """Prefix a CSV cell with a single quote if it looks like a spreadsheet
    formula (starts with =, +, -, or @), preventing formula-injection when
    the export is opened in Excel/LibreOffice/Sheets.

    Foundation for the CSV/JSON exports listed as pending in
    analisis-bombercat-vs-catnip.md section 6 — no such export exists in
    catnip yet, so nothing calls this today.
    """
    text = str(value)
    if text.startswith(_CSV_FORMULA_PREFIXES):
        return f"'{text}"
    return text
