from setuptools import setup, find_packages

setup(
    name="catnip",
    version="2.0",
    description="Catnip: A tool for uploading firmware to CatSniffer BV3",
    author="Electronic Cats",
    url="https://github.com/ElectronicCats/CatSniffer-Tools",
    packages=find_packages(include=["modules", "modules.*"]),
    py_modules=["catnip_uploader", "cc2538"],
    entry_points={
        "console_scripts": [
            "catnip=catnip_uploader:main",
        ],
    },
    install_requires=[
        "click",
        "pyserial",
        "typer",
        "python-magic",
        "intelhex",
        "requests",
    ],
    include_package_data=True,
    package_data={"modules": ["*.py"]},
)
