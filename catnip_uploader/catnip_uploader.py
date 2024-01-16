import os
import json
import requests
import sys
import io
import argparse
import serial
import time
from serial.tools import list_ports

GITHUB_REPO_URL     = "https://github.com/ElectronicCats/CatSniffer-Firmware/tree/v3.x/CC1352P7"
GITHUB_RELEASE_URL  = "https://github.com/ElectronicCats/CatSniffer-Firmware/releases/tag/board-v3.x-v1.0.0"
GITHUB_RAW_REPO_URL = "https://raw.githubusercontent.com/ElectronicCats/CatSniffer-Firmware/v3.x/CC1352P7/"

START_OF_FRAME = "ñ<"
END_OF_FRAME   = ">ñ"
TMP_FILE       = "firmware.hex"
COMMAND_ENTER_BOOTLOADER = "ñÿ<boot>ÿñ"
COMMAND_EXIT_BOOTLOADER = "ñÿ<exit>ÿñ"

def show_ports():
    for port in list_ports.comports():
        print(f"- {port.device}")

def create_command(payload: str):
    return START_OF_FRAME.encode("utf-8") + payload + END_OF_FRAME.encode("utf-8")

list_releases_version_3 = {
    0: "airtag_scanner_CC1352P_7.hex",
    1: "airtag_spoofer_CC1352P_7.hex",
    2: "sniffer_fw_CC1352P_7.hex",
    3: "sniffle_CC1352P_7.hex"
}
list_releases_version_2 = {
    0: "airtag_scanner_CC1352P_2.hex",
    1: "airtag_spoofer_CC1352P_2.hex",
    2: "sniffer_fw_CC1352P_2.hex",
}
def show_releases():
    print("Version 2.x")
    for i in list_releases_version_2:
        print(f"{i}: {list_releases_version_2[i]}")
    print("Version 3.x")
    for i in list_releases_version_3:
        print(f"{i}: {list_releases_version_3[i]}")
    

def load_firmware():
    try:
        #url = "https://github.com/ElectronicCats/CatSniffer-Firmware/releases/download/board-v3.x-v1.0.0/sniffer_fw_CC1352P_7.hex.hex"
        if int(args.version) == 0:
            print("Loading Firmware for version 2.x")
            url = f"https://github.com/ElectronicCats/CatSniffer-Firmware/releases/download/board-v2.x-v1.0.0/{firmware_selected}"
        elif int(args.version) == 1:
            print("Loading Firmware for version 3.x")
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
        ser = serial.Serial(args.port, 921600, timeout=1)
        ser.write(create_command(b"P"))
        print("Waiting for response:")
        while True:
            readline = ser.read_until("\n")
            print(readline)
            if readline == "BOOT":
                break
            time.sleep(1)
        ser.close()
        return True
    except Exception as e:
        print("Error al enviar ping", e)
        return False

def send_bootloader_mode():
    try:
        ser = serial.Serial(args.port, 921600, timeout=1)
        ser.write(bytes(COMMAND_ENTER_BOOTLOADER.encode()))
        print("Waiting for response:")
        while True:
            readline = ser.read_until("\n")
            print(readline)
            if readline.find("BOOT") != -1:
                break
            time.sleep(1)
        ser.close()
    except Exception as e:
        print("Error al enviar bootloader", e)

def send_exit_bootloader_mode():
    try:
        ser = serial.Serial(args.port, 500000, timeout=1)
        ser.write(bytes(COMMAND_EXIT_BOOTLOADER.encode()))
        print("Waiting for response:")
        while True:
            readline = ser.read_until("\n")
            print(readline)
            if readline.find("PASSTRHOUGH") != -1:
                break
            time.sleep(1)
        ser.close()
    except Exception as e:
        print("Error al enviar exit bootloader", e)

def show_file_release():
    request_release = requests.get("http://localhost:80/releases.json")
    request_release.raise_for_status()
    
    print("Releses: ", request_release.json())
        

def show_json_releases(release):
    string_coso = ""
    for i in release:
        string_coso += f"{i}: {release[i]}"
    return string_coso

parser = argparse.ArgumentParser(description='CatSniffer Firmware Loader')
parser.add_argument('-p', '--port', help='Serial port to use', required=True)
parser.add_argument('-f', '--firmware', help='Firmware to load', required=False)
parser.add_argument('-v', '--version', help='Version to load', required=False)
args = parser.parse_args()
version = int(args.version)

show_file_release()

if args.firmware:
    if version== 0:
        list_releases = list_releases_version_2
    elif version== 1:
        list_releases = list_releases_version_3
    else:
        print("Version not found")
        sys.exit(1)
    
    if int(args.firmware) not in list_releases.keys():
        print("Firmware not found")
        sys.exit(1)
    firmware_selected = list_releases[int(args.firmware)]
    print(firmware_selected)







send_bootloader_mode()
time.sleep(1)
load_firmware()
send_exit_bootloader_mode()