import typer
import serial
import platform
import requests
import io
import os
import time
import json
import sys

if platform.system() == "Windows":
    DEFAULT_COMPORT = "COM1"
else:
    DEFAULT_COMPORT = "/dev/ttyACM0"

GITHUB_RELEASE_URL               = "https://api.github.com/repos/ElectronicCats/CatSniffer-Firmware/releases/latest"
RELEASE_JSON_FILENAME = "board_release.json"
TMP_FILE                 = "firmware.hex"
COMMAND_ENTER_BOOTLOADER = "ñÿ<boot>ÿñ"
COMMAND_EXIT_BOOTLOADER  = "ñÿ<exit>ÿñ"

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

def validate_python_call():
    command = "python --version"
    output = os.popen(command).read()
    if output.find("Python 3.") == -1:
        command = "python3 --version"
        output = os.popen(command).read()
        if output.find("Python 3.") == -1:
            LOG_ERROR("Python 3 is required to run this program.")
            sys.exit(1)
        
        return "python3"
    
    return "python"

def validate_firmware_selected(firmware_selected: int):
    get_release = release_handler.get_release()
    LOG_INFO(f"Validating firmware selected: {firmware_selected}")
    if firmware_selected not in get_release:
        LOG_ERROR(f"Invalid firmware selected: {firmware_selected}")
        sys.exit(1)
    
    LOG_SUCCESS(f"Valid firmware selected: {firmware_selected}")
class Release:
    def __init__(self):
        self.release_data = None
        self.temp_filename = "releases.json"
        self.release_json = self.__fetch_release()

    def __fetch_assets(self):
        request_release = requests.get(f"{GITHUB_RELEASE_URL}")
        request_release.raise_for_status()
        req_release_data = request_release.json()
        LOG_INFO(f"Fetching assets from {GITHUB_RELEASE_URL}")
        LOG_INFO(f"Release: {req_release_data['tag_name']}")
        return req_release_data["assets"]

    def __fetch_release(self):
        repo_assets = self.__fetch_assets()
        
        for asset in repo_assets:
            if asset["name"] == RELEASE_JSON_FILENAME:
                req_release_data = asset["browser_download_url"]
                request_release = requests.get(req_release_data)
                content = request_release.content
                content_bytes = io.BytesIO(content)
                
                self.write_json_file(self.temp_filename, content_bytes.read().decode())
                self.release_data = self.read_json_file(self.temp_filename)
                
        json_release = json.loads(self.release_data)["board_v3"]
        return self.__create_dict_release(json_release)

    def __create_dict_release(self, release_data: dict = None):
        release_dict = {}
        for index, release in enumerate(release_data):
            release_dict[index] = release
        return release_dict

    def get_release(self):
        return self.release_json
    
    def read_json_file(self, filename: str):
        with open(filename, "r") as f:
            return json.load(f)
    
    def write_json_file(self, filename: str, data):
        with open(filename, "w") as f:
            f.write(json.dumps(data))
    
    def download_firmware(self, firmware_selected: int):
        repo_assets = self.__fetch_assets()
        print(self.release_json[int(firmware_selected)])
        for asset in repo_assets:
            if asset["name"] == self.release_json[firmware_selected]:
                req_release_data = asset["browser_download_url"]
                request_release = requests.get(req_release_data)
                content = request_release.content
                return content
        return None


class BoardUart:
    def __init__(self, serial_port: str = DEFAULT_COMPORT):
        self.serial_worker          = serial.Serial()
        self.serial_worker.port     = serial_port
        self.serial_worker.baudrate = 921600
        self.firmware_selected      = 0
        self.command_to_send        = f"cc2538.py -e -w -v -p {self.serial_worker.port} {TMP_FILE}"
        self.python_command         = validate_python_call()
    
    def validate_connection(self):
        try:
            self.serial_worker.open()
            self.serial_worker.close()
            return True
        except serial.SerialException:
            return False
    
    def set_firmware_selected(self, firmware_selected: str):
        self.firmware_selected = firmware_selected

    def send_connect_boot(self):
        self.serial_worker.open()
        self.serial_worker.write(COMMAND_ENTER_BOOTLOADER.encode())
        self.serial_worker.close()
    
    def send_disconnect_boot(self):
        self.serial_worker.open()
        self.serial_worker.write(COMMAND_EXIT_BOOTLOADER.encode())
        self.serial_worker.close()
    
    def send_firmware(self):
        LOG_INFO(f"Downloading {self.firmware_selected} - {release_handler.get_release()[self.firmware_selected]}")
        firmware = release_handler.download_firmware(self.firmware_selected)
        if firmware is None:
            LOG_ERROR(f"Error downloading firmware: {self.firmware_selected}")
            sys.exit(1)
        
        LOG_SUCCESS(f"Downloaded {self.firmware_selected}")
        
        content_bytes = io.BytesIO(firmware)
        self.create_tmp_file(content_bytes.read().decode())
        
        LOG_INFO(f"Uploading {release_handler.get_release()[self.firmware_selected]} to {self.serial_worker.port}")
        
        self.send_connect_boot()
        time.sleep(1)
        #TODO: Add a check to see if the command was successful
        os.system(f"{self.python_command} {self.command_to_send}")
        time.sleep(1)
        self.send_disconnect_boot()
        self.remove_tmp_file()
        LOG_SUCCESS(f"Done uploading {self.firmware_selected} to {self.serial_worker.port}")
    
    def create_tmp_file(self, content_bytes):
        with open(TMP_FILE, "w") as f:
            f.write(content_bytes)

    def remove_tmp_file(self):
        os.remove(TMP_FILE)
    

release_handler = Release()

app = typer.Typer(
    name = "Catnip Uploader",
    help = "Upload firmware to CatSniffer boards V3.",
    add_completion = False,
    no_args_is_help = True
)

@app.command("releases")
def list_releases():
    """List all releases available"""
    typer.echo("Releases available:")
    get_release = release_handler.get_release()
    for release in get_release:
        typer.echo(f"{release}: {get_release[release]}")

@app.command("load")
def load_firmware(firmware_selected: int = typer.Argument(
        default=0,
        help=f"Set the firmware to load.",
    ),
    comport: str = typer.Argument(
        default=DEFAULT_COMPORT,
        help="Serial port to use for uploading.",
    ),
):
    """Load firmware to the board"""
    validate_firmware_selected(firmware_selected)
    serial_connection = BoardUart(comport)

    serial_connection.set_firmware_selected(firmware_selected)

    if not serial_connection.validate_connection():
        LOG_ERROR(f"Invalid serial port: {comport}")
        sys.exit(1)
    
    serial_connection.send_firmware()

if __name__ == "__main__":
    app()