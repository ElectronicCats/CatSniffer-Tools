import typer
import os
import platform
import subprocess
import sys
import requests
import io
import serial
import time
from serial.tools.list_ports import comports
from rich.console import Console
from rich.table import Table
from typing_extensions import Annotated
from rich.progress import track


if platform.system() == "Windows":
    DEFAULT_COMPORT = "COM1"
elif platform.system() == "Darwin":
    DEFAULT_COMPORT = "/dev/tty.usbmodem0001"
else:
    DEFAULT_COMPORT = "/dev/ttyACM0"
GITHUB_RELEASE_URL = (
    "https://api.github.com/repos/ElectronicCats/CatSniffer-Firmware/releases/latest"
)
GITHUB_RELEASE_URL_SNIFFLE = (
    "https://api.github.com/repos/nccgroup/Sniffle/releases/latest"
)
GITHUB_SNIFFLE_HEX = "sniffle_cc1352p7_1M"
DESCRIPTION_FILE = "descriptions.txt"
COMMAND_ENTER_BOOTLOADER = "ñÿ<boot>ÿñ"
COMMAND_EXIT_BOOTLOADER = "ñÿ<exit>ÿñ"
UPLOADER_FILE_NAME = "cc2538.py"
RELEASE_FOLDER_NAME = "releases_"
CATSNIFFER_VID = 11914
CATSNIFFER_PID = 192
TIMEOUT_FETCH = 5
ABS_FILE_PATH = os.path.dirname(os.path.abspath(__file__))


def LOG_INFO(message):
    """Function to log information."""
    print(f"[INFO] {message}")


def LOG_ERROR(message):
    """Function to log error."""
    print(f"\x1b[31;1m[ERROR] {message}\x1b[0m")


def LOG_WARNING(message):
    """Function to log warning."""
    print(f"\x1b[33;1m[WARNING] {message}\x1b[0m")


def LOG_SUCCESS(message):
    """Function to log success."""
    print(f"\x1b[32;1m[SUCCESS] {message}\x1b[0m")


app = typer.Typer(
    name="Catnip Uploader",
    help="Upload firmware to CatSniffer boards V3.",
    add_completion=True,
    no_args_is_help=True,
)


class Release:
    def __init__(self) -> None:
        self.release_path = None
        self.tag_version = None
        self.description = None
        self.releases = self.__get_releases()

    def get_releases(self):
        return self.releases

    def get_release_path(self):
        return self.release_path

    def validate_file(self, firmware):
        if os.path.isfile(firmware):
            return os.path.abspath(firmware)

        for release in self.releases:
            if release.startswith(firmware) or firmware in release:
                return os.path.join(
                    ABS_FILE_PATH, f"{RELEASE_FOLDER_NAME}{self.tag_version}/{release}"
                )

        return None

    def __get_releases(self):
        has_local_release = self.__find_local_release()
        if has_local_release == None:
            LOG_WARNING("No releases found. Fetching from GitHub.")
            self.download_remote_release()
            has_local_release = self.__find_local_release()
        self.release_path = f"{ABS_FILE_PATH}/{RELEASE_FOLDER_NAME}{self.tag_version}"
        LOG_INFO(
            f"Using local releases: {self.release_path} with tag version: {self.tag_version}"
        )
        return has_local_release

    def __find_local_release(self):
        """Find the releases folder."""
        dir_files = os.listdir(ABS_FILE_PATH)
        for dir_name in dir_files:
            if dir_name.startswith(RELEASE_FOLDER_NAME):
                if self.__is_valid_release_content():
                    self.tag_version = dir_name.replace(RELEASE_FOLDER_NAME, "")
                    files = os.listdir(os.path.join(ABS_FILE_PATH, dir_name))
                    filtered_files = [
                        file for file in files if file != DESCRIPTION_FILE
                    ]
                    return filtered_files
                else:
                    return None
        return None

    def __is_valid_release_content(self) -> bool:
        """Check if the release folder is empty."""
        dir_files = os.listdir(ABS_FILE_PATH)
        for dir_name in dir_files:
            if dir_name.startswith(RELEASE_FOLDER_NAME):
                list_files = os.listdir(os.path.join(ABS_FILE_PATH, dir_name))
                if len(list_files) == 0:
                    LOG_WARNING("Empty release folder.")
                    self.__remove_local_files_releases(
                        os.path.join(ABS_FILE_PATH, dir_name)
                    )
                    return False
        return True

    def __remove_local_files_releases(self, release_folder: str) -> None:
        """Clean up the local releases folder."""
        list_files = os.listdir(release_folder)
        for file in list_files:
            os.remove(os.path.join(release_folder, file))
        os.rmdir(release_folder)

    def __get_assets_links(self, assets):
        """Get the assets links."""
        assets_links = []
        for asset in assets:
            assets_links.append(
                {"name": asset["name"], "url": asset["browser_download_url"]}
            )
        return assets_links

    def __create_release_folder(self):
        """Create the release folder."""
        if os.path.exists(f"{ABS_FILE_PATH}/{RELEASE_FOLDER_NAME}{self.tag_version}"):
            LOG_WARNING("Warning: Release folder already exists.")
            if self.__is_valid_release_content():
                return
        try:
            os.mkdir(f"{ABS_FILE_PATH}/{RELEASE_FOLDER_NAME}{self.tag_version}")
        except OSError:
            LOG_ERROR("Error: Could not create release folder.")
            sys.exit(1)

    def __create_description_file(self, content):
        with open(
            f"{ABS_FILE_PATH}/{RELEASE_FOLDER_NAME}{self.tag_version}/{DESCRIPTION_FILE}",
            "w",
        ) as f:
            f.write(content)
            f.close()

    def __fetch_remote_assets(self):
        try:
            request_release = requests.get(
                f"{GITHUB_RELEASE_URL}", timeout=TIMEOUT_FETCH
            )
            request_release.raise_for_status()
            if request_release.status_code != 200:
                LOG_ERROR("Could not fetch firmware.")
                sys.exit(1)
            req_release_data = request_release.json()
            self.tag_version = req_release_data["tag_name"]
            self.description = request_release.json()["body"]

            # Sniffle
            request_release_sniffle = requests.get(
                f"{GITHUB_RELEASE_URL_SNIFFLE}", timeout=TIMEOUT_FETCH
            )
            request_release_sniffle.raise_for_status()
            if request_release.status_code == 200:
                req_release_data_sniffle = request_release_sniffle.json()
                req_release_data["assets"].extend(req_release_data_sniffle["assets"])
            else:
                LOG_ERROR("Could not fetch Sniffle firwmare.")
            return self.__get_assets_links(req_release_data["assets"])
        except requests.exceptions.ConnectionError as e:
            # No internet connection
            LOG_ERROR(f"No Internet Connection")
            return None
        except Exception as e:
            # Entropy error unlocked
            LOG_ERROR(f"Error Exception: {e}")
            return None

    def __write_firmware_hex(self, name, content):
        content_bytes = io.BytesIO(content)
        with open(
            f"{ABS_FILE_PATH}/{RELEASE_FOLDER_NAME}{self.tag_version}/{name}", "wb"
        ) as f:
            content_bytes = io.BytesIO(content)
            f.write(content_bytes.read())
            content_bytes.close()

    def __dissect_firmware(self, asset):
        if asset["name"].endswith(".hex"):
            if "sniffle" in asset["name"]:
                if GITHUB_SNIFFLE_HEX in asset["name"]:
                    return asset
            else:
                return asset
        return None

    def download_remote_release(self):
        get_assets = self.__fetch_remote_assets()
        if get_assets == None:
            LOG_ERROR(
                "Error: Could not fetch firmware. Please check your internet connection."
            )
            sys.exit(1)

        self.__create_release_folder()
        firmware_count = 0
        firmware_saved = 0
        for asset in track(get_assets, description="Downloading firmware..."):
            if self.__dissect_firmware(asset) == None:
                continue
            request_content = requests.get(asset["url"], timeout=TIMEOUT_FETCH)
            request_content.raise_for_status()
            firmware_count += 1
            if request_content.status_code == 200:
                self.__write_firmware_hex(asset["name"], request_content.content)
                firmware_saved += 1
            else:
                LOG_ERROR(f"Could not fetch firmware: {asset['name']}")
                continue
        self.__create_description_file(self.description)
        LOG_SUCCESS(f"Firmware {firmware_saved}/{firmware_count} downloaded.")

    @staticmethod
    def find_folder_releases() -> str:
        """Find the releases folder."""
        dir_files = os.listdir(ABS_FILE_PATH)
        for dir_name in dir_files:
            if dir_name.startswith(RELEASE_FOLDER_NAME):
                return dir_name
        return None

    @staticmethod
    def normalize_firmware_name(name):
        name = name.lower()
        name = name.split("_v")[0]
        return name

    def get_descriptions_file(self):
        with open(
            f"{ABS_FILE_PATH}/{RELEASE_FOLDER_NAME}{self.tag_version}/{DESCRIPTION_FILE}",
            "r",
        ) as f:
            description = f.read()
            f.close()
        return description

    def parse_descriptions(self):
        description = self.get_descriptions_file()
        descriptions_dict = {}
        for line in description.strip().split("\n"):
            try:
                key, description = line.split(": ", 1)
                descriptions_dict[self.normalize_firmware_name(key)] = description
            except ValueError:
                pass
        return descriptions_dict


class BoardUart:
    def __init__(self, serial_port: str = DEFAULT_COMPORT):
        self.serial_worker = serial.Serial()
        self.serial_worker.port = serial_port
        self.serial_worker.baudrate = 921600
        self.firmware_selected = 0
        self.command_to_send = f"-e -w -v -p {self.serial_worker.port}"
        self.python_command = self.validate_python_call()

    def validate_connection(self):
        try:
            self.serial_worker.open()
            self.serial_worker.close()
            return True
        except serial.SerialException:
            return False

    def send_connect_boot(self):
        self.serial_worker.open()
        self.serial_worker.write(COMMAND_ENTER_BOOTLOADER.encode())
        self.serial_worker.close()

    def send_disconnect_boot(self):
        self.serial_worker.open()
        self.serial_worker.write(COMMAND_EXIT_BOOTLOADER.encode())
        self.serial_worker.close()

    def send_firmware(self, firmware_path):
        self.send_connect_boot()
        time.sleep(1)
        # TODO: Add a check to see if the command was successful
        # Get path to python script
        script_path = os.path.join(ABS_FILE_PATH, UPLOADER_FILE_NAME)
        os.system(
            f"{self.python_command} {script_path} {self.command_to_send} {firmware_path}"
        )
        time.sleep(1)
        self.send_disconnect_boot()
        return True

    def validate_python_call(self):
        try:
            output = subprocess.check_output(
                ["python", "--version"], stderr=subprocess.STDOUT
            )
            output = output.decode("utf-8").strip()
            if output.startswith("Python 3."):
                return "python"
        except Exception:
            pass
        try:
            output = subprocess.check_output(
                ["python3", "--version"], stderr=subprocess.STDOUT
            )
            output = output.decode("utf-8").strip()
            if output.startswith("Python 3."):
                return "python3"
        except Exception:
            pass
        LOG_ERROR("Error: Python 3 is required to run this program.")
        sys.exit(1)

    @staticmethod
    def find_catsniffer():
        for port in comports():
            if port.vid == CATSNIFFER_VID and port.pid == CATSNIFFER_PID:
                return port.device
        return DEFAULT_COMPORT


class CatnipUploader:
    def __init__(self) -> None:
        self.app = typer.Typer(
            name="Catnip Uploader",
            help="Upload firmware to CatSniffer boards V3.",
            add_completion=False,
            no_args_is_help=True,
        )
        self.app.command("load")(self.load_firmware)
        self.app.command("releases")(self.get_firmwares)
        self.releases = Release()

    def load_firmware(
        self,
        firmware: str = typer.Argument(
            help="Name of the firmware to load, or the path to the firmware file."
        ),
        comport: str = typer.Argument(
            help="COM port", default=BoardUart.find_catsniffer
        ),
        validate: bool = typer.Option(help="Bypass validation", default=False),
    ):
        """Load firmware to CatSniffer boards V3."""
        validate_firmware = self.releases.validate_file(firmware)
        if validate_firmware == None:
            LOG_ERROR(f"Firmware {firmware} not found.")
            sys.exit(1)

        board_uart = BoardUart(comport)
        if not board_uart.validate_connection():
            LOG_ERROR(f"Error: Could not connect to {comport}.")
            sys.exit(1)

        LOG_SUCCESS(f"Connected to {comport}")

        if not validate:
            LOG_WARNING(f"{'='*15} Validation is enabled. {'='*15}")
            confirm_load = typer.confirm(
                f"Are you sure you want to load the firmware: {validate_firmware}?\n",
                abort=True,
            )
            if not confirm_load:
                sys.exit(1)

        LOG_SUCCESS(f"Loading firmware: {validate_firmware}")
        if board_uart.send_firmware(validate_firmware.replace("\r", "")):
            LOG_SUCCESS("Firmware loaded successfully.")

    def get_firmwares(self):
        """Get the latest firmware releases."""
        description = self.releases.parse_descriptions()
        if description:
            table = Table(title="Releases")
            table.add_column("Firmware")
            table.add_column("Description")
            for key, value in description.items():
                table.add_row(key, value)
            console = Console()
            console.print(table)
        else:
            LOG_ERROR("No releases found.")


if __name__ == "__main__":
    catnip_uploader = CatnipUploader()
    catnip_uploader.app()
