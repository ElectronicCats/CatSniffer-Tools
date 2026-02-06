import io
import os
import json
import time
import hashlib
import logging
from datetime import datetime

# Internal
from .catsniffer import (
    catsniffer_get_port,
    catsniffer_get_device,
    CatSnifferDevice,
    ShellConnection,
)
from .cc2538 import (
    CommandInterface,
    FirmwareFile,
    CC26xx,
    CC2538,
    CmdException,
    CHIP_ID_STRS,
)

# External
import requests
from rich.console import Console
from rich.table import Table

GITHUB_RELEASE_URL = (
    "https://api.github.com/repos/ElectronicCats/CatSniffer-Firmware/releases/latest"
)
GITHUB_RELEASE_URL_SNIFFLE = (
    "https://api.github.com/repos/nccgroup/Sniffle/releases/latest"
)
GITHUB_SNIFFLE_HEX = "sniffle_cc1352p7_1M"
RELEASE_FOLDER_NAME = "release"
RELEASE_METADATA_NAME = "releases.json"
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CURRENT_DIR)

logger = logging.getLogger("rich")
console = Console()


class CCLoader:
    """CC1352 firmware loader using new multi-port architecture."""

    def __init__(self, firmware=None, device: CatSnifferDevice = None):
        """
        Initialize CCLoader.

        Args:
            firmware: Path to firmware file
            device: CatSnifferDevice with bridge_port and shell_port
        """
        self.cmd = CommandInterface()
        self.firmware = FirmwareFile(firmware)
        self.device = device
        self.shell = None

        # For backwards compatibility, accept port string
        if device is None:
            self.bridge_port = catsniffer_get_port()
            self.shell_port = None
        else:
            self.bridge_port = device.bridge_port
            self.shell_port = device.shell_port

    def init(self):
        """Initialize the bootloader connection."""
        cat_baud = 500000

        console.print(f"[*] Opening bridge port {self.bridge_port} at baud: {cat_baud}")
        self.cmd.open(self.bridge_port, cat_baud)

    def enter_bootloader(self):
        """Send boot command via shell port to enter CC1352 bootloader mode."""
        if self.shell_port:
            console.print(f"[*] Sending boot command via shell port: {self.shell_port}")
            self.shell = ShellConnection(port=self.shell_port)
            if self.shell.connect():
                result = self.shell.enter_bootloader()
                time.sleep(0.5)  # Give time for bootloader to start
                if result:
                    console.print("[*] Boot command sent successfully")
                else:
                    console.print("[yellow][!] Boot command may have failed[/yellow]")
            else:
                console.print(f"[yellow][!] Could not connect to shell port[/yellow]")
        else:
            console.print(
                "[yellow][!] No shell port available, skipping boot command[/yellow]"
            )

    def exit_bootloader(self):
        """Send exit command via shell port to exit CC1352 bootloader mode."""
        if self.shell_port:
            console.print(f"[*] Sending exit command via shell port")
            if self.shell is None:
                self.shell = ShellConnection(port=self.shell_port)
                self.shell.connect()

            if self.shell:
                result = self.shell.exit_bootloader()
                time.sleep(0.3)
                self.shell.disconnect()
                if result:
                    console.print("[*] Exit command sent successfully")
                else:
                    console.print("[yellow][!] Exit command may have failed[/yellow]")
        else:
            console.print(
                "[yellow][!] No shell port available, skipping exit command[/yellow]"
            )

    def sync_device(self) -> None:
        logger.info("[*] Connecting to target...")
        if not self.cmd.sendSynch():
            logger.error(
                "[X] Error: Can't connect to target. Ensure boot loader is started. (no answer on synch sequence)",
            )
            self.close_exit()

    def close(self) -> None:
        self.cmd.close()
        if self.shell:
            self.shell.disconnect()

    def close_exit(self) -> None:
        self.cmd.close()
        if self.shell:
            self.shell.disconnect()
        exit(1)

    def close_reset(self) -> None:
        self.cmd.cmdReset()
        self.cmd.close()

    def get_chip_info(self):
        chip_id = self.cmd.cmdGetChipId()
        chip_id_str = CHIP_ID_STRS.get(chip_id, None)

        if chip_id_str == None:
            logger.warning(f"[-] Unrecognized chip ID. Trying CC13xx/CC26xx")
            return CC26xx(self.cmd)
        else:
            console.print(f"[*] Chip ID: 0x{chip_id} ({chip_id_str})")
            return CC2538(self.cmd)

    def show_chip_details(self, device) -> None:
        console.print("[*] Chip details:")
        console.print(
            f"\tPackage: {device.chipid} - {device.size >> 10} KB Flash - {device.sram} SRAM - CCFG.BL_CONFIG at 0x%08X"
            % device.bootloader_address
        )
        console.print(
            "\tPrimary IEEE Address: %s"
            % (":".join("%02X" % x for x in device.ieee_addr))
        )

    def erase_firmware(self, device) -> None:
        console.print(f"[*] Performing mass erase")
        if device.erase():
            console.print(f"[*] Erase done", style="green")
        else:
            logger.error(f"[X] Error: Erase failed")
            self.close_exit()

    def write_firmware(self, device) -> None:
        address = device.flash_start_addr
        if self.cmd.writeMemory(address, self.firmware.bytes):
            console.print(f"[*] Write done", style="green")
        else:
            logger.error(f"[X] Error: Write failed")
            self.close_exit()

    def verify_crc(self, device) -> None:
        console.print(f"[*] Verifying by comparing CRC32 calculations.")
        address = device.flash_start_addr
        crc_local = self.firmware.crc32()
        crc_target = device.crc(address=address, size=len(self.firmware.bytes))
        if crc_local == crc_target:
            console.print(f"[*] Verified match: 0x%08x" % crc_local, style="green")
        else:
            logger.error(
                f"[X] NO CRC32 match: Local = 0x%x, Target = 0x%x"
                % (crc_local, crc_target),
            )
            self.close_exit()


class Catnip:
    def __init__(self):
        self.release_assets = []
        self.release_tag = None
        self.release_published_date = None
        self.release_description = None
        self.release_dir_path = os.path.join(ROOT_DIR, RELEASE_FOLDER_NAME)
        self.last_date = datetime.now().strftime("%d/%m/%Y")

        self.load_contex()

    def get_remove_firmware(self) -> None:
        self.get_remote_firmware()
        self.create_release_dir()
        self.create_local_metadata()
        self.download_remote_firmware()

    def load_contex(self) -> None:
        logger.info("[*] Looking for local releases")
        if self.find_local_release():
            logger.info("[*] Local release folder found!")
            self.load_metadata()
            if self.last_date != datetime.now().strftime("%d/%m/%Y"):
                if self.check_new_remote_version():
                    logger.info("[*] Updating version")
                    self.remove_release_dir()
                    self.get_remove_firmware()
        else:
            logger.info("[*] No Local release folder found!")
            with console.status("[bold magenta][*] Fetching remote firmware..."):
                self.get_remove_firmware()

        logger.info(
            f"[*] Current Release {self.release_tag} - {self.release_published_date}"
        )

    def __create_release_path(self):
        return f"{self.release_dir_path}_{self.release_tag}"

    def calculate_checksum(self, data) -> str:
        h = hashlib.new("sha256")
        h.update(data)
        return h.hexdigest()

    def parse_descriptions(self) -> dict:
        description = self.release_description.strip().split("\n")
        descriptions_dict = {}
        for line in description:
            try:
                key, desc = line.split(": ", 1)
                if key.endswith(".hex"):
                    descriptions_dict[key.lower()] = desc
                if key.endswith(".uf2"):
                    key = key.replace("- ", "")
                    descriptions_dict[key.lower()] = desc
            except ValueError:
                pass
        return descriptions_dict

    def get_releases_path(self) -> str:
        return os.path.join(ROOT_DIR, f"{RELEASE_FOLDER_NAME}_{self.release_tag}")

    def get_local_firmware(self):
        try:
            dir_list = os.listdir(self.get_releases_path())
            dir_list.pop(dir_list.index(RELEASE_METADATA_NAME))
            return dir_list
        except Exception as e:
            logger.error(f"[X] Error. {e}")
            exit(1)

    def show_releases(self) -> None:
        table = Table(title=f"Releases {self.release_tag}")
        description = self.parse_descriptions()

        table.add_column("No.")
        table.add_column("Firmware")
        table.add_column("Microcontroller")
        table.add_column("Description")

        for i, firmware in enumerate(self.get_local_firmware()):
            try:
                if firmware.lower().endswith(".uf2"):
                    table.add_row(
                        str(i), firmware, "RP2040", description[firmware.lower()]
                    )
                else:
                    table.add_row(
                        str(i), firmware, "CC1352", description[firmware.lower()]
                    )
            except Exception:
                if firmware.lower().endswith(".uf2"):
                    table.add_row(str(i), firmware, "RP2040", "Description not found")
                else:
                    table.add_row(str(i), firmware, "CC1352", "Description not found")

        console.print(table)

    def load_metadata(self):
        dir_list = os.listdir(ROOT_DIR)
        for f in dir_list:
            if f.startswith(RELEASE_FOLDER_NAME):
                self.release_tag = f.replace(f"{RELEASE_FOLDER_NAME}_", "")
                folder_path = os.path.join(
                    self.__create_release_path(), RELEASE_METADATA_NAME
                )
                metadata = open(folder_path, "r")
                json_data = json.loads(metadata.readlines()[0])

                self.release_tag = json_data["tag"]
                self.release_published_date = json_data["published_date"]
                self.release_description = json_data["description"]
                self.release_assets = json_data["assets"]
                if not "last_date" in json_data:
                    self.create_local_metadata()
                else:
                    self.last_date = datetime.now().strftime("%d/%m/%Y")
                logger.info("[*] Local metadata loaded")
                return

        logger.error("[X] Error: Release folder not found")

    def create_local_metadata(self) -> None:
        folder_path = os.path.join(self.__create_release_path(), RELEASE_METADATA_NAME)
        metadata = open(folder_path, "w")
        meta_dict = {
            "tag": self.release_tag,
            "published_date": self.release_published_date,
            "description": self.release_description,
            "assets": self.release_assets,
            "last_date": datetime.now().strftime("%d/%m/%Y"),
        }
        metadata.write(json.dumps(meta_dict))
        metadata.close()
        logger.info("[*] Local metadata created")

    def check_release_dir_content(self) -> bool:
        folder_path = self.__create_release_path()
        if os.path.exists(folder_path):
            dir_list = os.listdir(folder_path)
            if len(dir_list) > 0:
                return True
        return False

    def create_release_dir(self) -> None:
        try:
            folder_path = self.__create_release_path()
            if os.path.exists(folder_path):
                logger.info("[-] Local release folder already exists")
                return

            os.mkdir(folder_path)
            logger.info(f"[*] Local release folder created: {folder_path}")
        except Exception as e:
            logger.error(f"[X] Error: {e}")

    def remove_release_dir(self) -> None:
        folder_path = self.__create_release_path()
        if os.path.exists(folder_path):
            files = os.listdir(folder_path)
            for f in files:
                path = os.path.join(folder_path, f)
                if os.path.isfile(path):
                    os.remove(path)
            os.removedirs(folder_path)

    def get_firmware_cc_uf2(self, asset) -> bool:
        name = asset["name"]
        if name.endswith(".hex") or name.endswith(".uf2"):
            return True
        return False

    def save_firmware(self, name, content) -> str:
        f_writer = open(os.path.join(self.__create_release_path(), name), "wb")
        content_bytes = io.BytesIO(content)
        f_writer.write(content_bytes.read())
        content_bytes.close()
        return self.calculate_checksum(content)

    def compare_checksum(self, name, local_digest, remote_digest):
        local_checksum = local_digest
        remote_checksum = remote_digest.replace("sha256:", "")
        if local_checksum == remote_checksum:
            logger.info(f"[*] {name} Checksum SHA256 verified")
        else:
            logger.warning(f"[X] {name} Checksum SHA256 Failed")

    def check_new_remote_version(self) -> bool:
        try:
            fetch_releases = requests.get(GITHUB_RELEASE_URL, timeout=1)
            fetch_releases.raise_for_status()

            data = fetch_releases.json()
            remote_tag = data.get("tag_name")
            if remote_tag != self.release_tag:
                return True
            return False
        except Exception as e:
            logger.error(f"[X] Error. {e}")
            return False

    def download_remote_firmware(self) -> None:
        for asset in self.release_assets:
            if self.get_firmware_cc_uf2(asset):
                fname = asset["name"]
                try:
                    request_content = requests.get(
                        asset["browser_download_url"], timeout=5
                    )
                    request_content.raise_for_status()
                    local_checksum = self.save_firmware(fname, request_content.content)

                    logger.info(f"[*] Firmware [bold white]{fname}[/bold white] done.")

                    self.compare_checksum(fname, local_checksum, asset["digest"])
                    time.sleep(0.5)
                except requests.exceptions.ConnectionError as e:
                    logger.error("[X] Error: No internet connection.")
                    continue
                except requests.exceptions.RequestException as e:
                    logger.error(f"[X] HTTP Error: {e}")
                    continue
                except Exception as e:
                    logger.error(f"[X] Error: {e}")
                    continue

    def get_remote_firmware(self) -> None:
        try:
            fetch_releases = requests.get(GITHUB_RELEASE_URL, timeout=1)
            fetch_releases.raise_for_status()

            data = fetch_releases.json()
            self.release_tag = data.get("tag_name")
            self.release_published_date = data.get("published_at")
            self.release_description = data.get("body", "")
            self.release_assets = data.get("assets", [])

            # Sniffle release
            fetch_releases = requests.get(GITHUB_RELEASE_URL_SNIFFLE, timeout=1)
            fetch_releases.raise_for_status()
            sniffle_assets = fetch_releases.json().get("assets", [])

            for asset in sniffle_assets:
                if GITHUB_SNIFFLE_HEX.lower() in asset["name"].lower():
                    self.release_assets.append(asset)
        except requests.exceptions.ConnectionError as e:
            logger.error("[X] Error: No internet connection.")
            exit(1)
        except requests.exceptions.RequestException as e:
            logger.error(f"[X] HTTP Error: {e}")
            exit(1)
        except Exception as e:
            logger.error(f"[X] Error: {e}")
            exit(1)

    def find_local_release(self) -> bool:
        dir_files = os.listdir(ROOT_DIR)
        for dir_name in dir_files:
            if dir_name.startswith(RELEASE_FOLDER_NAME):
                return True
        return False

    def find_flash_firmware(self, firmware_str, device: CatSnifferDevice = None):
        """
        Find and flash firmware.

        Args:
            firmware_str: Firmware name, path, or alias
            device: CatSnifferDevice (optional, will auto-detect if not provided)
        """
        firmwares = self.get_local_firmware()

        # Get device if not provided
        if device is None:
            device = catsniffer_get_device()

        # Check if it's a direct file path
        if os.path.exists(firmware_str):
            return self.flash_firmware(firmware_str, device)

        # Alias inversos - mapear nombres comunes a nombres de archivo
        REVERSE_ALIASES = {
            "airtag_scanner": "airtag_scanner",
            "airtag_spoofer": "airtag_spoofer",
            "justworks": "justworks_scanner",
            "sniffle": "sniffle_cc1352p7_1M",
            "lora_sniffer": "LoraSniffer",
            "lora_cli": "LoRa-CLI",
            "lora_cad": "LoRa-CAD",
            "lora_freq": "LoRa-Freq",
        }

        # Verificar si es un alias conocido
        firmware_lower = firmware_str.lower()
        for alias, pattern in REVERSE_ALIASES.items():
            if alias.lower() in firmware_lower:
                # Buscar el archivo que coincida con el patrón
                for firm in firmwares:
                    if pattern.lower() in firm.lower():
                        path = os.path.join(self.get_releases_path(), firm)
                        console.print(
                            f"[dim]Alias '{firmware_str}' matched to: {firm}[/dim]"
                        )
                        return self.flash_firmware(path, device)

        # First, try exact match
        for firm in firmwares:
            if firm == firmware_str:
                path = os.path.join(self.get_releases_path(), firm)
                return self.flash_firmware(path, device)

        # Try match without extension
        firmware_no_ext = os.path.splitext(firmware_str)[0]
        for firm in firmwares:
            firm_no_ext = os.path.splitext(firm)[0]
            if firm_no_ext == firmware_no_ext:
                path = os.path.join(self.get_releases_path(), firm)
                return self.flash_firmware(path, device)

        # Try partial match (case insensitive)
        firmware_lower = firmware_str.lower()
        matches = []
        for firm in firmwares:
            firm_lower = firm.lower()
            if firmware_lower in firm_lower:
                matches.append(firm)

        if len(matches) == 1:
            # Single match found
            path = os.path.join(self.get_releases_path(), matches[0])
            return self.flash_firmware(path, device)
        elif len(matches) > 1:
            # Multiple matches - show options
            console.print(
                f"[yellow]Multiple firmwares match '{firmware_str}':[/yellow]"
            )
            for i, match in enumerate(matches, 1):
                console.print(f"  {i}. {match}")
            console.print("[yellow]Please be more specific.[/yellow]")
            return False

        # No match found
        console.print(f"[red]No firmware found matching '{firmware_str}'[/red]")
        console.print(f"Available firmwares: {', '.join(firmwares[:5])}...")
        return False

    def flash_firmware(self, firmware, device: CatSnifferDevice = None) -> bool:
        """
        Flash firmware to CC1352.

        Workflow:
        1. Send 'boot' command via Shell port → CC1352 enters bootloader
        2. Flash firmware via Bridge port using cc2538 bootloader protocol
        3. Send 'exit' command via Shell port → CC1352 exits bootloader

        Args:
            firmware: Path to firmware file
            device: CatSnifferDevice with bridge_port and shell_port
        """
        try:
            ccloader = CCLoader(firmware=firmware, device=device)
            ccloader.init()
            ccloader.enter_bootloader()
            ccloader.sync_device()
            chip_device = ccloader.get_chip_info()
            ccloader.show_chip_details(chip_device)
            ccloader.erase_firmware(chip_device)
            with console.status("[bold magenta][*] Writing bytes..."):
                ccloader.write_firmware(chip_device)
            ccloader.verify_crc(chip_device)
            ccloader.exit_bootloader()
            ccloader.close()
            return True
        except CmdException as e:
            logger.warning(
                f"[X] Please reset your board manually, [bold white]disconnect and reconnect[/bold white] or press the [bold white]RESET_CC1 and RESET1[/bold white] buttons.",
            )
            logger.error(f"Error: {e}")
            return False
        except Exception as e:
            logger.error(e)
            return False
