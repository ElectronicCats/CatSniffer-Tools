"""
Board generation support for CatSniffer.
========================================

CatSniffer boards come in two generations that share the same USB VID/PID,
the same three CDC ports and the same shell command set, but differ in the
host MCU, the CC1352 variant and the bootloader:

    v1.x / v2.x : SAMD21E17 + CC1352P1 (352 KB flash), uf2-samdx1 bootloader,
                  UF2 volume "SNIFFER", firmware releases tagged v2.X.Y.Z
    v3.x        : RP2040 + CC1352P7 (704 KB flash), RP2040 boot ROM,
                  UF2 volume "RPI-RP2", firmware releases tagged v3.X.Y.Z

A CC1352P7 image flashed on a CC1352P1 (or the other way round) disables
the serial bootloader and needs a cJTAG programmer to recover, so every
flash path must know which generation it is talking to.

Detection uses the "Board:" line of the fw_version shell command, e.g.
"Board: v2 SAMD21 CC1352P1". The SAMD21 firmware has emitted that line since
its first release (tests/test_board_support.py checks the invariant against
the firmware tree), so the only builds that can answer without it are RP2040
ones that predate it -- and those name an explicit "FW: v3.X" tag. Any other
reply is *unknown*: this module never guesses a generation, because guessing
v3 on a v2 is exactly what lets a CC1352P7 image brick a CC1352P1.

Every rule that differs between generations lives in BoardInfo as data. No
module outside this one may compare ``board.generation`` against a literal;
tests/test_board_support.py enforces that with an AST check.
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

CC1352P1_FLASH_SIZE = 0x58000  # 352 KB
CC1352P7_FLASH_SIZE = 0xB0000  # 704 KB


@dataclass(frozen=True)
class BoardInfo:
    generation: str  # "v2" or "v3"
    mcu: str  # host MCU
    cc_chip: str  # CC1352 variant
    cc_flash_size: int  # CC1352 flash size in bytes
    uf2_volume: str  # name of the bootloader mass-storage volume
    tag_prefix: str  # firmware release tags start with this
    uf2_pattern: str  # substring identifying this board's UF2 release asset

    # Capabilities. These replace the scattered ``generation == "v3"`` checks:
    # each one states *why* a code path differs, not *which board* it is.
    has_fw_id_storage: bool  # NVS to persist the CC1352 firmware ID
    can_self_program_cc1352: bool  # host MCU can act as a CMSIS-DAP probe
    ships_cc1352_hex_assets: bool  # its releases carry CC1352 .hex assets
    accepts_unnamed_images: bool  # images whose name omits the variant are its
    bridge_ring_bytes: int  # CC1352 bridge ring buffer size in the firmware

    @property
    def label(self) -> str:
        return f"{self.generation} ({self.mcu} + {self.cc_chip})"

    @property
    def firmware_series(self) -> int:
        """The ``A`` of a ``vA.X.Y.Z`` firmware version, for this board.

        Firmware is versioned ``vA.X.Y.Z`` where ``A`` names the board the
        image is built for, and releases are tagged per generation, so ``A``
        *is* the generation number (a v3 board runs v3.X.Y.Z images). Deriving
        it from ``tag_prefix`` keeps this the only place the two numbering
        schemes meet, so no caller needs a generation literal to check a
        firmware version against the hardware in front of it.
        """
        return int(self.tag_prefix.strip("v."))


BOARD_V2 = BoardInfo(
    generation="v2",
    mcu="SAMD21",
    cc_chip="CC1352P1",
    cc_flash_size=CC1352P1_FLASH_SIZE,
    uf2_volume="SNIFFER",
    tag_prefix="v2.",
    uf2_pattern="catsniffer-v2",
    has_fw_id_storage=False,  # prj.conf has no CONFIG_NVS: 16 KB of SRAM
    can_self_program_cc1352=False,  # no RP2040 to load free_dap onto
    ships_cc1352_hex_assets=False,  # tools/get_hex_files.py only emits board_v3
    accepts_unnamed_images=False,  # unnamed images are historically P7 builds
    bridge_ring_bytes=256,
)

BOARD_V3 = BoardInfo(
    generation="v3",
    mcu="RP2040",
    cc_chip="CC1352P7",
    cc_flash_size=CC1352P7_FLASH_SIZE,
    uf2_volume="RPI-RP2",
    tag_prefix="v3.",
    uf2_pattern="catsniffer-v3",
    has_fw_id_storage=True,
    can_self_program_cc1352=True,
    ships_cc1352_hex_assets=True,
    accepts_unnamed_images=True,  # every image in the bundle is a P7 build
    bridge_ring_bytes=16384,
)

BOARDS = {"v2": BOARD_V2, "v3": BOARD_V3}

# Filename fragments that identify a CC1352 image as built for one variant.
_P7_MARKERS = ("cc1352p7", "cc1352p_7", "p7_1", "_p7", "cc1352p7_1m")
_P1_MARKERS = ("cc1352p1", "cc1352p_1", "cc2652p1", "_p1")


def parse_board_line(fw_version_text: Optional[str]) -> Optional[BoardInfo]:
    """
    Return the BoardInfo described by a fw_version reply, or None.

    The reply is the raw text of the "fw_version" shell command:

    * a "Board:" line names the generation outright;
    * without it, only an explicit "FW: v3.X" tag identifies the board, and
      it identifies it as the RP2040 build that predates the line;
    * anything else is unknown.

    None means "do not guess": no caller may run a destructive operation on
    an unknown board. Returning BOARD_V3 here instead is what would let a
    CC1352P7 image reach a CC1352P1 and disable its serial bootloader.
    """
    if not fw_version_text:
        return None
    match = re.search(r"Board:\s*(v[23])\b", fw_version_text, re.IGNORECASE)
    if match:
        return BOARDS[match.group(1).lower()]
    if re.search(r"FW:\s*v3\.", fw_version_text, re.IGNORECASE):
        return BOARD_V3
    return None


def board_from_generation(generation: Optional[str]) -> Optional[BoardInfo]:
    """Resolve a "v2"/"v3" string (a --board override) to a BoardInfo."""
    if not generation:
        return None
    key = generation.strip().lower()
    if not key.startswith("v"):
        key = "v" + key
    return BOARDS.get(key)


def detect_board(
    shell_port: Optional[str], timeout: float = 2.0
) -> Optional[BoardInfo]:
    """
    Query the board generation through its Cat-Shell port.

    Returns None when the shell cannot be reached; callers must treat None as
    "unknown" and refuse any action that depends on the generation.
    """
    if not shell_port:
        return None
    # Imported here to keep this module importable in unit tests without
    # hardware dependencies.
    from ..core.usb_connection import ShellConnection

    shell = None
    try:
        shell = ShellConnection(port=shell_port, timeout=timeout)
        if not shell.connect():
            return None
        conn = getattr(shell, "connection", None)
        if conn is not None and hasattr(conn, "reset_input_buffer"):
            conn.reset_input_buffer()
        response = shell.send_command("fw_version", timeout=timeout)
        if not response or "FW:" not in response:
            return None
        return parse_board_line(response)
    except Exception:
        return None
    finally:
        if shell is not None:
            try:
                shell.disconnect()
            except Exception:
                pass


def image_variant(filename: str) -> Optional[str]:
    """
    Guess the CC1352 variant a firmware file was built for from its name.

    Returns "CC1352P7", "CC1352P1" or None when the name does not say.
    """
    name = (filename or "").lower()
    if any(marker in name for marker in _P7_MARKERS):
        return "CC1352P7"
    if any(marker in name for marker in _P1_MARKERS):
        return "CC1352P1"
    return None


def image_allowed_for_board(
    filename: str, board: Optional[BoardInfo]
) -> Tuple[bool, str]:
    """
    Decide from the file name whether an image may be flashed on a board.

    Returns (allowed, reason). An unknown board is never allowed, and an
    image whose name says nothing about the variant is allowed only on a v3
    (the historical default of every image in the release bundle).
    """
    if board is None:
        return False, "board generation unknown (fw_version gave no answer)"
    variant = image_variant(filename)
    if variant is None:
        if board.accepts_unnamed_images:
            return (
                True,
                f"image variant not named, assuming {board.generation} bundle image",
            )
        return False, (
            f"'{filename}' does not name a CC1352 variant; only images built for "
            f"{board.cc_chip} may be flashed on a {board.generation} board"
        )
    if variant != board.cc_chip:
        return False, (
            f"'{filename}' is a {variant} image but this {board.generation} board "
            f"has a {board.cc_chip}; flashing it would disable the CC1352 bootloader"
        )
    return True, f"{variant} image matches the board"


def image_fits_chip(image_size: int, chip_flash_size: int) -> Tuple[bool, str]:
    """Check that the image does not extend past the chip's flash."""
    if chip_flash_size <= 0:
        return False, "chip flash size unknown"
    if image_size > chip_flash_size:
        return False, (
            f"image is {image_size} bytes but the chip has {chip_flash_size} bytes "
            f"of flash ({chip_flash_size >> 10} KB); this image is for a larger part"
        )
    return True, "image fits in flash"


def board_for_chip_size(chip_flash_size: int) -> Optional[BoardInfo]:
    """Map a CC1352 flash size reported by the bootloader to a board."""
    for board in BOARDS.values():
        if board.cc_flash_size == chip_flash_size:
            return board
    return None


# ── preconditions ────────────────────────────────────────────────────────
#
# Everything below turns the capability data above into the single sentence
# a user should read *before* a command touches the hardware, instead of
# letting them find out halfway through a flash.

# What each capability means when it is missing, phrased as the reason the
# board cannot do it.
_CAPABILITY_REASON = {
    "has_fw_id_storage": "has no non-volatile storage for the CC1352 firmware id",
    "can_self_program_cc1352": "has no RP2040 to run the CMSIS-DAP probe on",
    "ships_cc1352_hex_assets": "publishes no CC1352 .hex assets in its releases",
    "accepts_unnamed_images": "only accepts images that name their CC1352 variant",
}

_UNKNOWN_BOARD_HINT = [
    "Connect the Cat-Shell port and run 'catnip devices' to confirm it answers.",
    "Or name the board by hand: --board v2 / --board v3.",
]


def require_capability(
    board: Optional[BoardInfo], capability: str, feature: str
) -> BoardInfo:
    """
    Assert that ``board`` can do ``feature``, or raise.

    ``capability`` is the name of a BoardInfo capability field. An unknown
    board (None) raises too: a command that depends on the generation may
    not run on a board that never said which one it is.

    Returns the board, so callers can keep using it in one expression.
    """
    from ..core.exceptions import UnsupportedOnBoardError

    if board is None:
        raise UnsupportedOnBoardError(
            f"{feature} needs to know the board generation, and this board did "
            "not answer.",
            hint=list(_UNKNOWN_BOARD_HINT),
        )
    if not getattr(board, capability):
        reason = _CAPABILITY_REASON.get(capability, f"lacks '{capability}'")
        raise UnsupportedOnBoardError(
            f"{feature} is not supported on a CatSniffer {board.label}: it {reason}.",
            hint=[f"This needs a CatSniffer {BOARD_V3.label}."],
        )
    return board


def require_firmware_for_board(
    board: Optional[BoardInfo], official_id: str, feature: str
) -> None:
    """
    Assert that a CC1352 image for ``official_id`` exists for ``board``.

    Unlike :func:`require_capability`, an unknown board is *not* an error
    here: this is an early, informative check, and the flashing path refuses
    an unknown board on its own (see ``flasher.find_flash_firmware``). Its
    job is to turn "sniff zigbee fails halfway through a flash on a v2" into
    one sentence printed before anything is touched.
    """
    from ..core.exceptions import UnsupportedOnBoardError
    from .fw_aliases import official_ids_for_board

    if board is None:
        return
    available = official_ids_for_board(board.generation)
    if official_id in available:
        return
    raise UnsupportedOnBoardError(
        f"{feature} needs the '{official_id}' firmware, which is not built for a "
        f"CatSniffer {board.label}.",
        hint=[
            f"Images available for {board.generation}: {', '.join(sorted(available))}.",
            f"This needs a CatSniffer {BOARD_V3.label}.",
        ],
    )


def file_available_for_board(filename: str, board: Optional[BoardInfo]) -> bool:
    """
    Whether a file in the release folder is meant for ``board``.

    Covers both kinds of asset the folder holds: CC1352 images, judged by the
    variant in their name, and host UF2 bundles, judged by the board's own
    release-asset pattern (a v2 UF2 names no CC1352 variant, so the image
    rule alone would hide the very firmware that board runs).

    An unknown board makes everything visible: this only decides what to
    *show*, never what to write.
    """
    if board is None:
        return True
    if filename.lower().endswith(".uf2"):
        return board.uf2_pattern in filename.lower()
    return image_allowed_for_board(filename, board)[0]


# How each capability reads when it is being *listed* rather than refused.
_CAPABILITY_LABEL = {
    "has_fw_id_storage": "Stores the CC1352 firmware id",
    "can_self_program_cc1352": "Can self-program the CC1352 (catnip restore)",
    "ships_cc1352_hex_assets": "Its releases ship CC1352 .hex assets",
}


def capability_rows(board: Optional[BoardInfo]) -> List[Tuple[str, bool]]:
    """(label, supported) for every capability worth showing to a user.

    ``accepts_unnamed_images`` is deliberately absent: it is an internal rule
    about how the release bundle is named, not something a user can act on.
    """
    if board is None:
        return []
    return [
        (label, bool(getattr(board, name))) for name, label in _CAPABILITY_LABEL.items()
    ]
