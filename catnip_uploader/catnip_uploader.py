import os
import requests
import magic
import binascii
import sys
import io
import argparse
import serial
from serial.tools import list_ports

GITHUB_REPO_URL = "https://github.com/ElectronicCats/CatSniffer-Firmware/tree/v3.x/CC1352P7"
GITHUB_RELEASE_URL = "https://github.com/ElectronicCats/CatSniffer-Firmware/releases/tag/board-v3.x-v1.0.0"
GITHUB_RAW_REPO_URL = "https://raw.githubusercontent.com/ElectronicCats/CatSniffer-Firmware/v3.x/CC1352P7/"

START_OF_FRAME = "ñ<"
END_OF_FRAME = ">ñ"
TMP_FILE = "firmware.hex"

def show_ports():
    for port in list_ports.comports():
        print(f"- {port.device}")


def create_command(payload: str):
    return START_OF_FRAME.encode("utf-8") + payload + END_OF_FRAME.encode("utf-8")

list_releases = {
    0: "airtag_scanner_CC1352P_7.hex",
    1: "airtag_spoofer_CC1352P_7.hex",
    2: "sniffer_fw_CC1352P_7.hex",
    3: "sniffle_CC1352P_7.hex"
}
def show_releases():
    for i in list_releases:
        print(f"{i}: {list_releases[i]}")

def load_firmware():
    try:
        #url = "https://github.com/ElectronicCats/CatSniffer-Firmware/releases/download/board-v3.x-v1.0.0/sniffer_fw_CC1352P_7.hex.hex"
        url = f"https://github.com/ElectronicCats/CatSniffer-Firmware/releases/download/board-v3.x-v1.0.0/{firmware_selected}"
        response = requests.get(url)
        response.raise_for_status()
        content = response.content
        content_bytes = io.BytesIO(content)

        with open(TMP_FILE, "w") as f:
            f.write(content_bytes.read().decode("utf-8"))
        
        command_firmware_loader = f"python3 cc2538.py -e -w -v -p {args.port} firmware.hex"
        os.system(command_firmware_loader)

        os.remove(TMP_FILE)

    except requests.exceptions.RequestException as e:
        print("Error al hacer la solicitud:", e)
    
def send_ping():
    try:
        ser = serial.Serial(args.port, 500000, timeout=1)
        ser.write(create_command(b"P"))
        ser.close()
        return True
    except Exception as e:
        print("Error al enviar ping", e)
        return False

def send_bootloader_mode():
    try:
        ser = serial.Serial(args.port, 500000, timeout=1)
        ser.write(create_command(b"B"))
        ser.close()
    except Exception as e:
        print("Error al enviar bootloader", e)

parser = argparse.ArgumentParser(description='CatSniffer Firmware Loader', )
parser.add_argument('-p', '--port', help='Serial port to use', required=True)
parser.add_argument('-f', '--firmware', help='Firmware to load', required=True)
args = parser.parse_args()

if int(args.firmware) not in list_releases.keys():
    print("Firmware not found")
    sys.exit(1)

firmware_selected = list_releases[int(args.firmware)]

print(firmware_selected)
is_valid = send_ping()
if is_valid:
    print("CatSniffer found")
    send_bootloader_mode()
    load_firmware()