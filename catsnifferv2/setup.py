import platform
from setuptools import setup, find_packages

setup(
    name="catsniffer",
    version="2.0.0",
    packages=find_packages(include=["modules", "modules.*", "protocol", "protocol.*"]),
    description="All in one CatSniffer tools",
    long_description_content_type="text/markdown",
    install_requires=[
        "rich",
        "pyserial",
        "requests",
        "python-magic",
        "intelhex",
        "pywin32" if platform.system() == "Windows" else "",
    ],
    py_modules=["catsniffer"],
    entry_points={
        "console_scripts": ["catsniffer=catsniffer:main_cli"],
    },
    url="https://github.com/ElectronicCats/CatSniffer-Tools/",
    author="JahazielLem, Electronic Cats",
    python_requires=">=3",
    classifiers=[
        "Development Status :: 2 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License (GPL)",
        "Programming Language :: Python",
        "Operating System :: OS Independent",
    ],
)
