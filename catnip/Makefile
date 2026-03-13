# CatSniffer Makefile
# Simplified installation and management

PYTHON=python3
PIP=pip
PREFIX=/usr/local
BIN_DIR=$(PREFIX)/bin

.PHONY: all install compile-install uninstall clean help

help:
	@echo "CatSniffer-Tools catnip Makefile"
	@echo "Usage:"
	@echo "  make install         Install catnip as a python package and create global symlink"
	@echo "  make compile-install Compile with Nukita and install globally"
	@echo "  make uninstall       Remove catnip from the system"
	@echo "  make clean           Remove build artifacts"

install:
	@echo "[*] Installing catnip package..."
	$(PIP) install .
	@echo "[*] Setting up global access (requires sudo)..."
	sudo bash ./scripts/install.sh $(shell which catnip)

compile-install:
	@echo "[*] Compiling catnip with Nuitka..."
	bash ./compile.sh
	@echo "[*] Installing compiled binary to $(BIN_DIR)..."
	sudo cp dist/catnip.dist/catnip $(BIN_DIR)/catnip
	@echo "[+] Compiled binary installed to $(BIN_DIR)/catnip"

uninstall:
	@echo "[*] Uninstalling catnip package..."
	$(PIP) uninstall -y catnip
	@echo "[*] Removing global symlink/binary..."
	sudo rm -f $(BIN_DIR)/catnip
	@echo "[+] Uninstalled successfully"

clean:
	rm -rf build/ dist/ catnip.egg-info/
	find . -type d -name "__pycache__" -exec rm -rf {} +
