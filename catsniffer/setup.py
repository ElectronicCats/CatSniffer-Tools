from pathlib import Path
from setuptools import setup, find_packages

long_description = Path("README.md").read_text(encoding="utf-8")

setup(
    name="catsniffer",
    version="3.0.0",
    packages=find_packages(include=["modules", "modules.*", "protocol", "protocol.*"]),
    description="All in one CatSniffer tools — multi-protocol RF sniffer CLI",
    long_description=long_description,
    long_description_content_type="text/markdown",
    install_requires=[
        "click>=8.0.0",
        "cryptography>=42.0.0",
        "intelhex>=2.3.0",
        "matplotlib>=3.8.0",
        "meshtastic>=2.5.0",
        "numpy>=1.26.0",
        "pyserial>=3.5",
        "pyusb>=1.2.1",
        "requests>=2.32.5",
        "rich>=14.0.0",
        "scapy>=2.5.0",
        "textual>=0.50.0",
        # python-magic requires libmagic system library.
        # On Windows use the bundled binary variant instead.
        "python-magic>=0.4.27; sys_platform != 'win32'",
        "python-magic-bin>=0.4.14; sys_platform == 'win32'",
        # pywin32 is required for named-pipe support on Windows.
        "pywin32>=306; sys_platform == 'win32'",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
        ],
    },
    py_modules=["catsniffer"],
    scripts=["lora_extcap.py"],
    entry_points={
        "console_scripts": ["catsniffer=catsniffer:main_cli"],
    },
    url="https://github.com/ElectronicCats/CatSniffer-Tools/",
    author="Electronic Cats",
    author_email="support@electroniccats.com",
    license="GPL-3.0",
    python_requires=">=3.9",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
        "Topic :: Security",
        "Topic :: System :: Networking :: Monitoring",
    ],
)
