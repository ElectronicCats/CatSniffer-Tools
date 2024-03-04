import os
import time
import platform
import re
import uuid


def validate_access_address(access_address):
    regex = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$|^[0-9a-fA-F]{12}$")
    return bool(regex.match(access_address))


def clear_screen():
    """Function to clear the screen."""
    if platform.system() == "Windows":
        os.system("cls")
    else:
        os.system("clear")


def create_folders(path):
    """Function to create folders."""
    if not os.path.exists(path):
        os.makedirs(path)


def generate_filename():
    """Function to generate a filename."""
    return time.strftime("%Y%m%d%H%M%S") + "_" + str(uuid.uuid4())[:8]
