from setuptools import setup, find_packages
import shutil
import platform
import os


def create_path(path):
    if not os.path.exists(path):
        os.makedirs(path)


def wireshark_files():
    dissectors_path = ""
    dissector_file = ""

    if platform.system() == "Windows":
        dissectors_path = os.path.join(
            os.getenv("APPDATA"), "Wireshark", "plugins", "4.4", "epan"
        )
        dissector_file = "dissectors/windows/catsniffer.dll"
    elif platform.system() == "Darwin":
        dissectors_path = os.path.join(
            os.getenv("HOME"), ".local", "lib", "wireshark", "plugins", "4-4", "epan"
        )
        dissector_file = "dissectors/mac/catsniffer.so"
    else:
        dissectors_path = os.path.join(
            os.getenv("HOME"), ".local", "lib", "wireshark", "plugins", "4.4", "epan"
        )
        dissector_file = "dissectors/linux/catsniffer.so"

    create_path(dissectors_path)
    complete_path = os.path.join(dissectors_path, os.path.basename(dissector_file))
    shutil.copyfile(dissector_file, complete_path)
    return [(dissectors_path, [dissector_file])]


setup(
    name="pycatsniffer",
    version="1.0",
    description="CatSniffer BV3: A tool for sniffing ZigBee, LoRa, and other protocols",
    author="Kevin Leon",
    url="https://github.com/ElectronicCats/CatSniffer-Tools",
    packages=find_packages(include=["Modules", "Modules.*"]),
    py_modules=["cat_sniffer"],
    entry_points={
        "console_scripts": [
            "pycatsniffer=cat_sniffer:main",
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
