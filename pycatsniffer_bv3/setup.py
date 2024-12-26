from setuptools import setup, find_packages
import subprocess
import shutil
import platform
import locale
import os


def get_program_path(program_name):
    try:
        program_path = shutil.which(program_name)
        if program_path:
            if platform.system() == "Darwin":
                return program_path.replace("/MacOS/wireshark", "")
            else:
                return os.path.dirname(program_path)

        system_language = locale.getdefaultlocale()[0]
        is_spanish = system_language.startswith("es")

        system = platform.system()
        if system == "Windows":
            common_paths = [
                "C:\\Program Files\\Wireshark\\Wireshark.exe",
                "C:\\Program Files (x86)\\Wireshark\\Wireshark.exe",
            ]
            if is_spanish:
                common_paths.extend(
                    [
                        "C:\\Archivos de programa\\Wireshark\\Wireshark.exe",
                        "C:\\Archivos de programa (x86)\\Wireshark\\Wireshark.exe",
                    ]
                )
            for path in common_paths:
                if shutil.which(path):
                    return path
        elif system == "Darwin":
            result = subprocess.run(
                ["mdfind", "kMDItemFSName=Wireshark"], capture_output=True, text=True
            )
            if result.stdout:
                return result.stdout.strip().split("\n")[0]
        elif system == "Linux":
            for path in ["/usr/bin/wireshark", "/usr/local/bin/wireshark"]:
                if shutil.which(path):
                    return path

        return None
    except Exception:
        return None


def wireshark_files():
    program_name = "wireshark"
    program_path = get_program_path(program_name)
    dissectors_path = ""
    dissector_file = ""
    if not program_path:
        # Si no se encuentra Wireshark, devuelve una lista vacía
        return []

    if platform.system() == "Windows":
        dissectors_path = os.path.join(program_path, "plugins\\wireshark\\4-4")
        dissector_file = "dissectors/windows/catsniffer.dll"
    elif platform.system() == "Darwin":
        dissectors_path = os.path.join(program_path, "PlugIns/wireshark/4-4/epan/")
        dissector_file = "dissectors/mac/catsniffer.so"
    else:
        dissectors_path = os.path.join(program_path, "PlugIns/wireshark/4-4")
        dissector_file = "dissectors/linux/catsniffer.so"

    shutil.copyfile(
        dissector_file, os.path.join(dissectors_path, os.path.basename(dissector_file))
    )
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
