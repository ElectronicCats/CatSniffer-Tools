from setuptools import setup, find_packages
import shutil
import platform
import os

def create_path(path):
    if not os.path.exists(path):
        os.makedirs(path)

def wireshark_files():
    dissectors_path = ""
    dissectors_wireshark = ""
    dissector_file = ""

    if platform.system() == "Windows":
        dissectors_path = os.path.join("src", "pycatsniffer", "dissectors", "windows")
        dissectors_wireshark = os.path.join(
            os.getenv("APPDATA"), "Wireshark", "plugins", "4.4", "epan"
        )
        dissector_file = "catsniffer.dll"
    elif platform.system() == "Darwin":
        dissectors_path = os.path.join("src", "pycatsniffer", "dissectors", "mac")
        dissectors_wireshark = os.path.join(
            os.getenv("HOME"), ".local", "lib", "wireshark", "plugins", "4-4", "epan"
        )
        dissector_file = "catsniffer.so"
    else:
        dissectors_path = os.path.join("src", "pycatsniffer", "dissectors", "linux")
        dissectors_wireshark = os.path.join(
            os.getenv("HOME"), ".local", "lib", "wireshark", "plugins", "4.4", "epan"
        )
        dissector_file = "catsniffer.so"

    create_path(dissectors_wireshark)
    shutil.copyfile(os.path.join(dissectors_path, dissector_file), os.path.join(dissectors_wireshark, dissector_file))
    return [("dissectors", [])]

setup(
    name="pycatsniffer",
    version="2.0",
    description="Cross-platform (Windows, Mac and Linux) modular script for packet sniffing using catsniffer supporting the following protocols: BLE, IEEE 802.15, Zigbee.",
    author="Electronic Cats",
    url="https://github.com/ElectronicCats/CatSniffer-Tools",
    packages=find_packages(where='src'),
    package_dir={"": "src"},
    entry_points={
        "console_scripts": [
            "pycatsniffer=pycatsniffer.cat_sniffer:main",
        ],
    },
    install_requires=[
        "click",
        "pyserial",
        "typer",
        "pywin32" if platform.system() == "Windows" else "",
    ],
    include_package_data=True,
    package_data={"Modules": ["*.py"]},
    data_files=wireshark_files(),
)
