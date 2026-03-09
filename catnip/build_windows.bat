@echo off
REM build_windows.bat
REM Script to build CatSniffer Tools for Windows

echo ========================================
echo Building CatSniffer Tools for Windows
echo ========================================

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    exit /b 1
)

REM Check/install dependencies
echo Installing dependencies...
python -m pip install --upgrade pip
python -m pip install pyinstaller
python -m pip install -r requirements.txt
python -m pip install pywin32

REM Install libusb for Windows (required for pyusb)
echo Installing libusb...
if not exist "libusb" (
    mkdir libusb
    cd libusb
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/libusb/libusb/releases/download/v1.0.26/libusb-1.0.26-binaries.7z' -OutFile 'libusb.7z'"
    REM Note: You will need 7-Zip installed
    "C:\Program Files\7-Zip\7z.exe" x libusb.7z
    cd ..
)

REM Build with PyInstaller
echo Building executables...
pyinstaller catnip_windows.spec

REM Verify build
if not exist "dist\catnip" (
    echo ERROR: Build failed
    exit /b 1
)

echo ========================================
echo Build completed successfully
echo The executables are in: dist\catnip\
echo ========================================
