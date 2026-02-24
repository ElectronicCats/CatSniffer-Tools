from setuptools import setup, find_packages

setup(
    name="cativity",
    version="1.1",
    description="Cativity: A tool for channel activity",
    author="Astrobyte",
    url="https://github.com/ElectronicCats/CatSniffer-Tools",
    packages=find_packages(include=["modules", "modules.*"]),
    py_modules=["cativity"],
    entry_points={
        "console_scripts": [
            "cativity=cativity:main",
        ],
    },
    install_requires=["click", "pyserial", "typer", "scapy", "shellingham"],
    include_package_data=True,
    package_data={"modules": ["*.py"]},
)
