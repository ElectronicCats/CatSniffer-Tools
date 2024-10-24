#!/usr/bin/env python
# Catnip Uploader is a Python script that allows you to upload firmware to CatSniffer boards V3.
# This file is part of the CatSniffer project, http://electroniccats.com/
# GNU GENERAL PUBLIC LICENSE
# Version 1 2024
# Kevin Leon <@kevlem97>

# Copyright (C) 2007 Free Software Foundation, Inc. https://fsf.org/
# Everyone is permitted to copy and distribute verbatim copies
# of this license document, but changing it is not allowed.

import typer
import serial
import platform
import requests
import io
import os
import time
import json
import sys
import subprocess
from rich.console import Console
from rich.table import Table

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
RELEASE_JSON_FILENAME = "board_release.json"
TMP_FILE = "firmware.hex"
COMMAND_ENTER_BOOTLOADER = "ñÿ<boot>ÿñ"
COMMAND_EXIT_BOOTLOADER = "ñÿ<exit>ÿñ"
UPLOADER_FILE_NAME = "cc2538.py"

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


def validate_python_call():
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
    print("Error: Python 3 is required to run this program.")
    sys.exit(1)


def validate_firmware_selected(firmware_selected: int):
    get_release = release_handler.get_local_releases_dict()
    LOG_INFO(
        f"Validating selected firmware: {firmware_selected} - {get_release[firmware_selected]}"
    )
    if firmware_selected not in get_release:
        LOG_ERROR(f"Selected firmware invalid: {firmware_selected}")
        sys.exit(1)

    LOG_SUCCESS(f"Valid firmware selected: {firmware_selected}")


class Release:
    def __init__(self):
        self.release_data = None
        self.temp_filename = "releases.json"
        self.tag_version = None
        self.release_json = self.__fetch_release()
        self.description = None

    def __fetch_assets(self):
        """Fetch the assets from the release."""
        try:
            request_release = requests.get(f"{GITHUB_RELEASE_URL}")
            request_release.raise_for_status()

            if request_release.status_code != 200:
                LOG_ERROR(f"Error fetching assets: {request_release.status_code}")
                sys.exit(1)

            req_release_data = request_release.json()
            LOG_INFO(f"Fetching assets from {GITHUB_RELEASE_URL}")
            LOG_INFO(f"Release: {req_release_data['tag_name']}")

            self.tag_version = req_release_data["tag_name"]
            body_description = request_release.json()["body"]
            self.description = body_description

            # Sniffle
            request_release_sniffle = requests.get(f"{GITHUB_RELEASE_URL_SNIFFLE}")
            request_release_sniffle.raise_for_status()
            req_release_data_sniffle = request_release_sniffle.json()
            LOG_INFO(f"Fetching assets from {GITHUB_RELEASE_URL_SNIFFLE}")
            LOG_INFO(f"Release: {req_release_data_sniffle['tag_name']}")
            req_release_data["assets"].extend(req_release_data_sniffle["assets"])

            return req_release_data["assets"]
        except requests.exceptions.ConnectionError as e:
            has_local_release = self.find_folder_releases()
            if has_local_release is not None:
                return None
            LOG_ERROR(
                "Error. You need internet connection for the first use to download the firmware"
            )
            sys.exit(1)
        except Exception as e:
            has_local_release = self.find_folder_releases()
            if has_local_release is not None:
                return None
            LOG_ERROR(f"Error fetching assets: {e}")
            sys.exit(1)

    def __fetch_release(self):
        """Fetch the release data from the repo."""
        try:
            firmware_releases = []
            repo_assets = self.__fetch_assets()
            if repo_assets is None:
                return self.get_local_releases_dict()
            # Check if the lasted release is already downloaded
            has_local_release = self.find_folder_releases()
            if has_local_release is not None:
                # The local release is found
                LOG_INFO(f"Found local release: {has_local_release}")
                has_lasted_release = self.has_lasted_release(self.tag_version)
                if has_lasted_release:
                    if self.is_empty_release_folder():
                        LOG_INFO(
                            f"A local folder is empty, updating to {self.tag_version}"
                        )
                        self.remove_local_files_releases(has_local_release)
                        os.rmdir(os.path.join(ABS_FILE_PATH, has_local_release))
                    else:
                        LOG_SUCCESS(f"Local release is up to date: {self.tag_version}")
                        firmware_releases = self.get_local_releases_dict()
                        return firmware_releases
                else:
                    LOG_WARNING(
                        f"Updating local release: {has_local_release} to {self.tag_version}"
                    )

            LOG_INFO("Fetching release data")

            self.create_release_folder(self.tag_version)

            for asset in repo_assets:
                if asset["name"] == RELEASE_JSON_FILENAME:
                    req_release_data = asset["browser_download_url"]
                    request_release = requests.get(req_release_data)
                    content = request_release.content
                    content_bytes = io.BytesIO(content)

                    self.write_json_file(
                        self.temp_filename, content_bytes.read().decode()
                    )
                    self.release_data = self.read_json_file(self.temp_filename)
                else:
                    with open(
                        os.path.join(
                            ABS_FILE_PATH,
                            f"releases_{self.tag_version}",
                            "descriptions.txt",
                        ),
                        "w",
                    ) as ft:
                        ft.write(self.description)
                        ft.close()
                    # To avoid the uf3 files until we have a way to upload them
                    if (
                        asset["url"].find("nccgroup") != -1
                        and asset["name"] != f"{GITHUB_SNIFFLE_HEX}.hex"
                    ):
                        continue
                    if (
                        asset["url"].find("nccgroup") != -1
                        and asset["name"] == f"{GITHUB_SNIFFLE_HEX}.hex"
                    ):
                        firmware_name = f"nccgroup_{asset['browser_download_url'].split('/')[-2]}_{asset['name']}"
                        with open(
                            os.path.join(
                                ABS_FILE_PATH,
                                f"releases_{self.tag_version}",
                                firmware_name,
                            ),
                            "wb",
                        ) as f:
                            request_release = requests.get(
                                asset["browser_download_url"]
                            )
                            content_bytes = io.BytesIO(request_release.content)
                            f.write(content_bytes.read())
                            firmware_releases.append(firmware_name)
                        continue
                    if asset["name"].endswith(".hex"):
                        with open(
                            os.path.join(
                                ABS_FILE_PATH,
                                f"releases_{self.tag_version}",
                                asset["name"],
                            ),
                            "wb",
                        ) as f:
                            request_release = requests.get(
                                asset["browser_download_url"]
                            )
                            content_bytes = io.BytesIO(request_release.content)
                            f.write(content_bytes.read())
                            firmware_releases.append(asset["name"])
            return self.__create_dict_release(firmware_releases)
        except Exception as e:
            print(e)
            LOG_ERROR(
                f"Error with the repo assets. Please check the current version of the script and the release: {e}"
            )
            sys.exit(1)

    def __create_dict_release(self, release_data: dict = None):
        """Create a dictionary with the release data."""
        release_dict = {}
        for index, release in enumerate(release_data):
            release_dict[index] = release
        return release_dict

    def get_release(self):
        """Return the release data. If it's not available, return the local release data."""
        if self.release_json is None:
            self.release_json = self.get_local_releases_dict()
        return self.release_json

    def read_json_file(self, filename: str):
        with open(filename, "r") as f:
            return json.load(f)

    def write_json_file(self, filename: str, data) -> None:
        with open(filename, "w") as f:
            f.write(json.dumps(data))

    def remove_local_files_releases(self, release_folder: str) -> None:
        """Clean up the local releases folder."""
        list_files = os.listdir(release_folder)
        for file in list_files:
            os.remove(os.path.join(release_folder, file))

    def has_lasted_release(self, lasted_release) -> bool:
        """Check if the lasted release is already downloaded."""
        dir_files = os.listdir(ABS_FILE_PATH)
        for dir_name in dir_files:
            if dir_name.startswith("releases_"):
                if dir_name.replace("releases_", "") == lasted_release:
                    return True
        return False

    def is_empty_release_folder(self) -> bool:
        """Check if the release folder is empty."""
        dir_files = os.listdir(ABS_FILE_PATH)
        for dir_name in dir_files:
            if dir_name.startswith("releases_"):
                list_files = os.listdir(os.path.join(ABS_FILE_PATH, dir_name))
                if len(list_files) == 0:
                    return True
        return False

    def get_local_releases_dict(self) -> dict:
        """Get the local releases."""
        release_folder = self.find_folder_releases()
        if release_folder is not None:
            list_files = os.listdir(os.path.join(ABS_FILE_PATH, release_folder))
            for lis in list_files:
                if lis == "descriptions.txt":
                    list_files.remove(lis)
            return self.__create_dict_release(list_files)
        return {}

    def find_folder_releases(self) -> str:
        """Find the releases folder."""
        dir_files = os.listdir(ABS_FILE_PATH)
        for dir_name in dir_files:
            if dir_name.startswith("releases_"):
                return dir_name
        return None

    def create_release_folder(self, tag_version):
        """Create the release folder."""
        if tag_version is None:
            return
        exist_prev_release = self.find_folder_releases()
        release_path = os.path.join(ABS_FILE_PATH, f"releases_{tag_version}")
        if exist_prev_release is None:
            if not os.path.exists(release_path):
                os.mkdir(release_path)
        else:
            LOG_WARNING(
                f"Previous release found: {exist_prev_release} updating to {tag_version}"
            )
            self.remove_local_files_releases(os.path)
            os.rename(exist_prev_release, release_path)

    def get_firmware_releases(self, firmware_selected: int):
        """Get the firmware releases."""
        releases_firmware = self.get_local_releases_dict()
        print(releases_firmware[firmware_selected])
        if releases_firmware is None:
            LOG_ERROR(f"Error with the releases folder")
            return None

        return os.path.join(
            ABS_FILE_PATH,
            self.find_folder_releases(),
            releases_firmware[firmware_selected],
        )

    def normalize_firmware_name(self, name):
        name = name.lower()
        name = name.split("_v")[0]
        return name

    def get_firmware_description(self, firmware_key, descriptions):
        normalized_name = self.normalize_firmware_name(firmware_key)
        for line in descriptions.strip().split("\n"):
            try:
                key, description = line.split(": ", 1)
                if normalized_name.startswith("nccgroup"):
                    if key.startswith("Sniffle"):
                        return description
                if self.normalize_firmware_name(key) == normalized_name:
                    return description
            except ValueError:
                pass
        return "Description not found"


class BoardUart:
    def __init__(self, serial_port: str = DEFAULT_COMPORT):
        self.serial_worker = serial.Serial()
        self.serial_worker.port = serial_port
        self.serial_worker.baudrate = 921600
        self.firmware_selected = 0
        self.command_to_send = f"-e -w -v -p {self.serial_worker.port}"
        self.python_command = validate_python_call()

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
        LOG_INFO(
            f"Getting {self.firmware_selected} - {release_handler.get_release()[self.firmware_selected]}"
        )
        firmware_bytes = release_handler.get_firmware_releases(self.firmware_selected)
        if firmware_bytes is None:
            LOG_ERROR(f"Error reading firmware: {self.firmware_selected}")
            sys.exit(1)

        LOG_INFO(
            f"Uploading {release_handler.get_release()[self.firmware_selected]} to {self.serial_worker.port}"
        )

        self.send_connect_boot()
        time.sleep(1)
        # TODO: Add a check to see if the command was successful
        # Get path to python script
        script_path = os.path.join(ABS_FILE_PATH, UPLOADER_FILE_NAME)
        os.system(
            f"{self.python_command} {script_path} {self.command_to_send} {firmware_bytes}"
        )
        time.sleep(1)
        self.send_disconnect_boot()
        LOG_SUCCESS(
            f"Done uploading {self.firmware_selected} to {self.serial_worker.port}"
        )

    def create_tmp_file(self, content_bytes):
        with open(TMP_FILE, "w") as f:
            f.write(content_bytes)

    def remove_tmp_file(self):
        os.remove(TMP_FILE)


release_handler = Release()

app = typer.Typer(
    name="Catnip Uploader",
    help="Upload firmware to CatSniffer boards V3.",
    add_completion=False,
    no_args_is_help=True,
)


@app.command("releases")
def list_releases():
    """List all available releases"""
    LOG_SUCCESS("Available releases:")
    table = Table(title="Releases")
    table.add_column("Index", style="cyan")
    table.add_column("Release", style="cyan")
    table.add_column("Description", style="cyan")
    get_release = release_handler.get_release()
    exist_prev_release = release_handler.find_folder_releases()
    description = ""
    with open(
        os.path.join(ABS_FILE_PATH, exist_prev_release, "descriptions.txt"), "r"
    ) as ft:
        description = ft.read()
        ft.close()
    for release in get_release:
        find_description = release_handler.get_firmware_description(
            get_release[release].replace(".hex", ""), description
        )
        table.add_row(str(release), get_release[release], find_description)
    console = Console()
    console.print(table)


@app.command("load")
def load_firmware(
    firmware_selected: int = typer.Argument(
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
