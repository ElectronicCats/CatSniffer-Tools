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

for port in list_ports.comports():
    print("CatSniffer found in port: ", port.device, port.hwid)


def create_command(payload: str):
    return START_OF_FRAME.encode("utf-8") + payload + END_OF_FRAME.encode("utf-8")

list_releases = {
    0: "airtag_scanner_CC1352P_7.hex",
    1: "airtag_spoofer_CC1352P_7.hex",
    2: "sniffer_fw_CC1352P_7.hex",
    3: "sniffle_CC1352P_7.hex"
}

for i in list_releases:
    print(f"{i}: {list_releases[i]}")

parser = argparse.ArgumentParser(description='CatSniffer Firmware Loader')
parser.add_argument('-p', '--port', help='Serial port to use', required=True)
parser.add_argument('-f', '--firmware', help='Firmware to load', required=True)
args = parser.parse_args()

print("Port: ", args.port)
print("Firmware: ", args.firmware)

if int(args.firmware) not in list_releases.keys():
    print("Firmware not found")
    sys.exit(1)

firmware_selected = list_releases[int(args.firmware)]
print(firmware_selected)

try:
    #url = "https://github.com/ElectronicCats/CatSniffer-Firmware/releases/download/board-v3.x-v1.0.0/sniffer_fw_CC1352P_7.hex.hex"
    url = f"https://github.com/ElectronicCats/CatSniffer-Firmware/releases/download/board-v3.x-v1.0.0/{firmware_selected}"
    response = requests.get(url)
    response.raise_for_status()
    content = response.content#.decode("utf-8").split("\n")
    #content = "".join(content)
    content_bytes = io.BytesIO(content)

    with open("firmware.hex", "w") as f:
        f.write(content_bytes.read().decode("utf-8"))
    #command_firmware_loader = f"python3 cc2538.py -e -w -v -p {args.port} firmware.hex"
    #os.system(command_firmware_loader)

    os.remove("firmware.hex")
    print("Opening serial connection")
    print("SENDING PING", create_command(b"P"))
    ser = serial.Serial(args.port, 500000, timeout=1)
    ser.write(create_command(b"P"))
    ser.close()
    print("Entering BOOTLOADER: ", create_command(b"B"))
    #print(content_in_memory)

except requests.exceptions.RequestException as e:
    print("Error al hacer la solicitud:", e)