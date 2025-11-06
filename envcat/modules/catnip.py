
# Internal
from .catsniffer import Catsniffer
from .cc2538 import CommandInterface, FirmwareFile, CC26xx, CC2538, CHIP_ID_STRS
# External
from rich.console import Console

__version__ = "1.0"

console = Console()
  
class CCLoader:
  def __init__(self, firmware=None):
    self.cmd = CommandInterface()
    self.firmware = FirmwareFile(firmware)

  def init(self):
    cat_port = Catsniffer().get_port()
    cat_baud = 500000
    
    console.log(f"[*] Opening port {cat_port} at baud: {cat_baud}")
    self.cmd.open(cat_port, cat_baud)
  
  def enter_bootloader(self):
    self.cmd._write(Catsniffer.cmd_bootloader_enter())
  def exit_bootloader(self):
    self.cmd._write(Catsniffer.cmd_bootloader_exit())
    
  def sync_device(self) -> None:
    console.log("[*] Connecting to target...")
    if not self.cmd.sendSynch():
      console.log("[X] Error: Can't connect to target. Ensure boot loader is started. (no answer on synch sequence)", style="red")
      self.close_exit()

  def close(self) -> None:
    self.cmd.close()

  def close_exit(self) -> None:
    self.cmd.close()
    exit(1)
  
  def close_reset(self) -> None:
    self.cmd.cmdReset()
    self.cmd.close()
  
  def get_chip_info(self):
    chip_id = self.cmd.cmdGetChipId()
    chip_id_str = CHIP_ID_STRS.get(chip_id, None)
    
    if chip_id_str == None:
      console.log(f"[-] Unrecognized chip ID. Trying CC13xx/CC26xx", style="yellow")
      return CC26xx(self.cmd)
    else:
      console.log(f"[*] Chip ID: 0x{chip_id} ({chip_id_str})", style="green")
      return CC2538(self.cmd)

  def erase_firmware(self, device) -> None:
    console.log(f"[*] Performing mass erase")
    if device.erase():
      console.log(f"[*] Erase done", style="green")
    else:
      console.log(f"[X] Error: Erase failed", style="red")
      self.close_exit()
  
  def write_firmware(self, device) -> None:
    address = device.flash_start_addr
    if self.cmd.writeMemory(address, self.firmware.bytes):
      console.log(f"[*] Write done", style="green")
    else:
      console.log(f"[X] Error: Erase failed", style="red")
      self.close_exit()
  
  def verify_crc(self, device) -> None:
    console.log(f"[*] Verifying by comparing CRC32 calculations.")
    address = device.flash_start_addr
    crc_local = self.firmware.crc32()
    crc_target = device.crc(address=address, size=len(self.firmware.bytes))
    if crc_local == crc_target:
      console.log(f"[*] Verified match: 0x%08x" % crc_local, style="green")
    else:
      console.log(f"[X] NO CRC32 match: Local = 0x%x, Target = 0x%x" % (crc_local, crc_target), style="red")
      self.close_exit()

class Catnip:
  def __init__(self):
    pass
  
  def flash_firmware(self, firmware) -> None:
    try:
      ccloader = CCLoader(firmware=firmware)
      ccloader.init()
      ccloader.enter_bootloader()
      ccloader.sync_device()
      device = ccloader.get_chip_info()
      ccloader.erase_firmware(device)
      with console.status("[bold magenta][*] Writing bytes..."):
        ccloader.write_firmware(device)
      ccloader.verify_crc(device)
      ccloader.exit_bootloader()
      ccloader.close()
    except Exception as e:
      console.log(e, style="red")
    