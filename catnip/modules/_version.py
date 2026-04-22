from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

try:
    __version__ = version("catnip")
except PackageNotFoundError:
    # Fallback for development (package not installed)
    __version__ = (Path(__file__).parent.parent / "VERSION").read_text().strip()
