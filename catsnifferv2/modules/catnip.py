import io
import os
import json
import time
import hashlib
import logging
from datetime import datetime

# Internal
from .catsniffer import catsniffer_get_port, cmd_bootloader_enter, cmd_bootloader_exit
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
    def __init__(self, firmware=None, port=catsniffer_get_port()):
        self.cmd = CommandInterface()
        self.firmware = FirmwareFile(firmware)
        self.cat_port = port

    def init(self):
        cat_baud = 500000

        logger.info(f"[*] Opening port {self.cat_port} at baud: {cat_baud}")
        self.cmd.open(self.cat_port, cat_baud)

    def enter_bootloader(self):
        self.cmd._write(cmd_bootloader_enter())

    def exit_bootloader(self):
        self.cmd._write(cmd_bootloader_exit())

    def sync_device(self) -> None:
        logger.info("[*] Connecting to target...")
        if not self.cmd.sendSynch():
            logger.error(
                "[X] Error: Can't connect to target. Ensure boot loader is started. (no answer on synch sequence)",
            )
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
            logger.warning(
                f"[-] Unrecognized chip ID. Trying CC13xx/CC26xx", style="yellow"
            )
            return CC26xx(self.cmd)
        else:
            logger.info(f"[*] Chip ID: 0x{chip_id} ({chip_id_str})", style="green")
            return CC2538(self.cmd)

    def show_chip_details(self, device) -> None:
        logger.info("[*] Chip details:")
        logger.info(
            f"\tPackage: {device.chipid} - {device.size >> 10} KB Flash - {device.sram} SRAM - CCFG.BL_CONFIG at 0x%08X"
            % device.bootloader_address
        )
        logger.info(
            "\tPrimary IEEE Address: %s"
            % (":".join("%02X" % x for x in device.ieee_addr))
        )

    def erase_firmware(self, device) -> None:
        logger.info(f"[*] Performing mass erase")
        if device.erase():
            logger.info(f"[*] Erase done", style="green")
        else:
            logger.error(f"[X] Error: Erase failed", style="red")
            self.close_exit()

    def write_firmware(self, device) -> None:
        address = device.flash_start_addr
        if self.cmd.writeMemory(address, self.firmware.bytes):
            logger.info(f"[*] Write done", style="green")
        else:
            logger.error(f"[X] Error: Erase failed", style="red")
            self.close_exit()

    def verify_crc(self, device) -> None:
        logger.info(f"[*] Verifying by comparing CRC32 calculations.")
        address = device.flash_start_addr
        crc_local = self.firmware.crc32()
        crc_target = device.crc(address=address, size=len(self.firmware.bytes))
        if crc_local == crc_target:
            logger.info(f"[*] Verified match: 0x%08x" % crc_local, style="green")
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
            logger.info("[*] Local release folder found!", style="green")
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
            f"[*] Current Release {self.release_tag} - {self.release_published_date}",
            style="magenta",
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

                    logger.info(
                        f"[*] Firmware [bold white]{fname}[/bold white] done.",
                        style="cyan",
                    )

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

    def find_flash_firmware(self, firmware_str, port):
        firmwares = self.get_local_firmware()
        for firm in firmwares:
            if firm.startswith(firmware_str):
                path = os.path.join(self.get_releases_path(), firm)
                return self.flash_firmware(path, port)
        return False

    def flash_firmware(self, firmware, port) -> bool:
        try:
            ccloader = CCLoader(firmware=firmware, port=port)
            ccloader.init()
            ccloader.enter_bootloader()
            ccloader.sync_device()
            device = ccloader.get_chip_info()
            ccloader.show_chip_details(device)
            ccloader.erase_firmware(device)
            with console.status("[bold magenta][*] Writing bytes..."):
                ccloader.write_firmware(device)
            ccloader.verify_crc(device)
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
