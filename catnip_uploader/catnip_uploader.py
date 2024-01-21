import typer
import serial
import platform
import requests
import io
import os
import time

if platform.system() == "Windows":
    DEFAULT_COMPORT = "COM1"
else:
    DEFAULT_COMPORT = "/dev/ttyACM0"

GITHUB_URL_RELEASE       = "https://github.com/ElectronicCats/CatSniffer-Firmware/releases/download/board-v3.x-v1.0.0"
TMP_FILE                 = "firmware.hex"
COMMAND_ENTER_BOOTLOADER = "ñÿ<boot>ÿñ"
COMMAND_EXIT_BOOTLOADER  = "ñÿ<exit>ÿñ"
RELEASE_BOARD_V3         = {
    0: "airtag_scanner_CC1352P_7.hex",
    1: "airtag_spoofer_CC1352P_7.hex",
    2: "sniffer_fw_CC1352P_7.hex",
    3: "sniffle_CC1352P_7.hex"
}


class BoardUart:
    def __init__(self, serial_port: str = DEFAULT_COMPORT):
        self.serial_worker          = serial.Serial()
        self.serial_worker.port     = serial_port
        self.serial_worker.baudrate = 921600
        self.firmware_selected      = ""
        self.command_to_send        = f"cc2538.py -e -w -v -p {self.serial_worker.port} {TMP_FILE}"
        self.python_command         = "python3"
    
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
        typer.echo(f"Downloading {self.firmware_selected}")
        url = f"{GITHUB_URL_RELEASE}/{self.firmware_selected}"
        response = requests.get(url)
        response.raise_for_status()
        content = response.content
        content_bytes = io.BytesIO(content)
        self.create_tmp_file(content_bytes.read().decode())

        typer.echo(f"Uploading {self.firmware_selected} to {self.serial_worker.port}")
        self.send_connect_boot()
        time.sleep(1)
        os.system(f"{self.python_command} {self.command_to_send}")
        time.sleep(1)
        self.send_disconnect_boot()
        self.remove_tmp_file()
        typer.echo(f"Done uploading {self.firmware_selected} to {self.serial_worker.port}")
    
    def create_tmp_file(self, content_bytes):
        with open(TMP_FILE, "w") as f:
            f.write(content_bytes)

    def remove_tmp_file(self):
        os.remove(TMP_FILE)
    
def validate_firmware_selected(firmware_selected: int):
    if firmware_selected not in RELEASE_BOARD_V3:
        raise typer.BadParameter(f"Invalid firmware selected: {firmware_selected}")


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
    for release in RELEASE_BOARD_V3:
        typer.echo(f"{release}: {RELEASE_BOARD_V3[release]}")

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

    serial_connection.set_firmware_selected(RELEASE_BOARD_V3[firmware_selected])

    if not serial_connection.validate_connection():
        raise typer.BadParameter(f"Invalid serial port: {comport}")
    
    typer.echo(f"Uploading {RELEASE_BOARD_V3[firmware_selected]} to {comport}")
    serial_connection.send_firmware()



if __name__ == "__main__":
    app()