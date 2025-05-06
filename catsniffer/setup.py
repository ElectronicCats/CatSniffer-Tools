from setuptools import setup, find_packages

setup(
    name="catsniffer",
    version="1.0",
    description="Catsniffer: Interface to comunicate with catsniffer",
    author="Kevin Leon",
    url="https://github.com/ElectronicCats/CatSniffer-Tools",
    py_modules=["catsniffer"],
    entry_points={
        "console_scripts": [
            "catsniffer=catsniffer:main",
        ],
    },
    install_requires=["pyserial"],
)
