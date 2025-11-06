import time
import asyncio
# Internal
from .catnip import Catnip
from .pipes import DEFAULT_UNIX_PATH
from .bridge import main_serial_pipeline
# External
import click
from rich.console import Console

__version__ = "1.0"

console = Console()

@click.group()
def cli():
  """CatSniffer: All in one catsniffer tools environment."""
  pass

@cli.command()
def cativity() -> None:
  """IQ Activity Monitor"""
  console.print("[*] Monitoring IQ activity")

@cli.command()
@click.option("--path", "-p", type=str, help="Path for the pipeline")
def pipeline(path) -> None:
  """Build a Pipeline for wireshark"""
  if path is None:
    path = DEFAULT_UNIX_PATH
  console.print(f"[*] Building pipe: {path}")
  asyncio.run(main_serial_pipeline())

@cli.command()
@click.argument("firmware")
@click.option("--firmware", "-f", default="sniffle", help="Firmware name or path.")
def flash(firmware) -> None:
  """Flash firmware"""
  console.print(f"[*] Flashing firmware: {firmware}")
  Catnip().flash_firmware(firmware)

@cli.command()
def releases() -> None:
  """Show Firmware releases"""
  console.print(f"[*] Releases")

def main_cli() -> None:
  cli()
  