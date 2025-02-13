from setuptools import setup, find_packages
import shutil
import platform
import os
import zipfile

ZIP_FOLDER_NAME = "wireshark_capture_profiles"
TRASH_FOLDER_MAC = "__MACOSX"


def create_path(path):
    if not os.path.exists(path):
        os.makedirs(path)


def wireshark_profiles():
    zip_path_profiles = f"filter_profiles/{ZIP_FOLDER_NAME}.zip"
    extract_path = ""
    if platform.system() == "Darwin":
        extract_path = os.path.join(
            os.getenv("HOME"), ".config", "wireshark", "profiles"
        )
    elif platform.system() == "Windows":
        extract_path = os.path.join(os.getenv("APPDATA"), "Wireshark", "profiles")
    else:
        extract_path = os.path.join(
            os.getenv("HOME"), ".config", "wireshark", "profiles"
        )

    create_path(extract_path)

    with zipfile.ZipFile(zip_path_profiles, "r") as zip_ref:
        zip_ref.extractall(extract_path)

    path_extracted_profiles = os.path.join(extract_path, ZIP_FOLDER_NAME)
    list_extracted_dir = os.listdir(path_extracted_profiles)

    for dir in list_extracted_dir:
        try:
            shutil.move(os.path.join(path_extracted_profiles, dir), extract_path)
        except shutil.Error as e:
            print(e)
            continue

    if os.path.exists(os.path.join(extract_path, TRASH_FOLDER_MAC)):
        shutil.rmtree(os.path.join(extract_path, TRASH_FOLDER_MAC))

    shutil.rmtree(path_extracted_profiles)


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

    # Dissector
    create_path(dissectors_path)
    complete_path = os.path.join(dissectors_path, os.path.basename(dissector_file))
    shutil.copyfile(dissector_file, complete_path)
    # Profiles
    wireshark_profiles()
    return [(dissectors_path, [dissector_file])]


setup(
    name="pycatsniffer",
    version="2.0",
    description="CatSniffer BV3: A tool for sniffing ZigBee, LoRa, and other protocols",
    author="Electronic Cats",
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
