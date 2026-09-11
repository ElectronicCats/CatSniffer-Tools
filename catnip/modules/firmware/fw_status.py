"""
Parsing the Cat-Shell ``status`` reply.
======================================

``status`` is the one shell command whose *shape* differs between board
generations. Both firmwares answer with the same two first lines::

    Mode: 0, Band: 0, Radio: LoRa, LoRa: initialized, LoRa Mode: Stream,
    FW: v2.1.0.0, CC1352 FW: unset (n/a)
    CC1352 loss: uart_overrun=0, ring_dropped=0 bytes[, dma_regress=0]

and the SAMD21 build adds what its 16 KB of SRAM make worth watching
(``SAMD21/catsniffer/src/shell_commands.c``, ``cmd_status``): a trace ring
dump, stack headroom, the last fault, and one line per Zephyr thread::

    Trace(4557): 01 03 04 30 ...
    Stack unused: main=200 lora=56 isr=440 bytes
    Last fault: none
      thread 0x20000a20 prio=-11 stack=1024 unused=56

So the parser is *line-based and order-independent*: it recognises the lines
it knows and keeps every other one verbatim in ``unparsed``. A firmware that
grows a line must never make this raise, and one that drops a line must never
make it lie — which is why every section is optional.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# "  thread 0x20000a20 prio=-11 stack=1024 unused=56"
_THREAD_RE = re.compile(
    r"thread\s+(?P<id>0x[0-9a-fA-F]+)\s+prio=(?P<prio>-?\d+)\s+"
    r"stack=(?P<stack>\d+)\s+unused=(?P<unused>\d+)"
)
_PAIRS_RE = re.compile(r"(\w+)=(\d+)")
# "Mode: 0", "CC1352 FW: unset (n/a)" — keys may contain spaces and digits.
_FIELD_RE = re.compile(r"([A-Za-z][A-Za-z0-9 ]*?):\s*([^,]+)")


@dataclass(frozen=True)
class ThreadInfo:
    ident: str
    priority: int
    stack: int
    unused: int


@dataclass(frozen=True)
class ShellStatus:
    """What a ``status`` reply said, with everything generation-specific
    optional. Empty sections mean "this firmware did not report it", never
    "it reported zero"."""

    fields: Dict[str, str] = field(default_factory=dict)
    counters: Dict[str, int] = field(default_factory=dict)
    stacks: Dict[str, int] = field(default_factory=dict)
    threads: Tuple[ThreadInfo, ...] = ()
    last_fault: Optional[str] = None
    trace: Optional[str] = None
    unparsed: Tuple[str, ...] = ()

    @property
    def has_diagnostics(self) -> bool:
        """True when the firmware reported the extended (SAMD21) block."""
        return bool(self.stacks or self.threads or self.last_fault or self.trace)

    @property
    def tightest_stack(self) -> Optional[Tuple[str, int]]:
        """The (name, unused bytes) of the stack with the least headroom.

        On a 16 KB part this is the number that says how close the board is
        to a stack overflow, and it is the reason the extended block exists.
        """
        candidates = list(self.stacks.items())
        candidates += [(t.ident, t.unused) for t in self.threads]
        return min(candidates, key=lambda item: item[1]) if candidates else None


def parse_status_response(text: Optional[str]) -> Optional[ShellStatus]:
    """Parse a ``status`` reply, or return None when there is nothing to read."""
    if not text or not text.strip():
        return None

    fields: Dict[str, str] = {}
    counters: Dict[str, int] = {}
    stacks: Dict[str, int] = {}
    threads: List[ThreadInfo] = []
    last_fault: Optional[str] = None
    trace: Optional[str] = None
    unparsed: List[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line == "status":  # the shell echoes the command
            continue

        thread = _THREAD_RE.search(line)
        if thread:
            threads.append(
                ThreadInfo(
                    ident=thread.group("id"),
                    priority=int(thread.group("prio")),
                    stack=int(thread.group("stack")),
                    unused=int(thread.group("unused")),
                )
            )
            continue
        if line.startswith("Trace("):
            trace = line
            continue
        if line.startswith("CC1352 loss:"):
            counters.update({key: int(value) for key, value in _PAIRS_RE.findall(line)})
            continue
        if line.startswith("Stack unused:"):
            stacks.update({key: int(value) for key, value in _PAIRS_RE.findall(line)})
            continue
        if line.startswith("Last fault:"):
            last_fault = line.split(":", 1)[1].strip()
            continue
        if line.startswith("Mode:"):
            fields.update(
                {key.strip(): value.strip() for key, value in _FIELD_RE.findall(line)}
            )
            continue
        unparsed.append(line)

    return ShellStatus(
        fields=fields,
        counters=counters,
        stacks=stacks,
        threads=tuple(threads),
        last_fault=last_fault,
        trace=trace,
        unparsed=tuple(unparsed),
    )


def read_status(shell_port: Optional[str], timeout: float = 2.0):
    """Ask a board for its ``status``, or return None if it cannot answer."""
    if not shell_port:
        return None
    from ..core.usb_connection import ShellConnection

    shell = None
    try:
        shell = ShellConnection(port=shell_port, timeout=timeout)
        if not shell.connect():
            return None
        return parse_status_response(shell.send_command("status", timeout=timeout))
    except Exception:
        return None
    finally:
        if shell is not None:
            try:
                shell.disconnect()
            except Exception:
                pass


def read_loss_counters(
    shell_port: Optional[str], timeout: float = 2.0
) -> Optional[Dict[str, int]]:
    """The firmware's loss counters right now, or None when it could not be asked.

    Three outcomes, and the difference between them is the whole point:
    ``None`` means *unknown* (no config port, port busy, no reply), ``{}``
    means the firmware answered but reported no loss line, and a populated
    dict is the only one that licenses a claim about the capture. Neither of
    the first two is zero.
    """
    status = read_status(shell_port, timeout=timeout)
    return None if status is None else dict(status.counters)
