@echo off
REM build_windows.bat
REM Script para construir CatSniffer Tools para Windows

echo ========================================
echo Construyendo CatSniffer Tools para Windows
echo ========================================

REM Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no está instalado o no está en el PATH
    exit /b 1
)

REM Verificar/instalar dependencias
echo Instalando dependencias...
python -m pip install --upgrade pip
python -m pip install pyinstaller
python -m pip install -r requirements.txt
python -m pip install pywin32

REM Instalar libusb para Windows (necesario para pyusb)
echo Instalando libusb...
if not exist "libusb" (
    mkdir libusb
    cd libusb
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/libusb/libusb/releases/download/v1.0.26/libusb-1.0.26-binaries.7z' -OutFile 'libusb.7z'"
    REM Nota: Necesitarás 7-Zip instalado
    "C:\Program Files\7-Zip\7z.exe" x libusb.7z
    cd ..
)

REM Construir con PyInstaller
echo Construyendo ejecutables...
pyinstaller catnip_windows.spec

REM Verificar construcción
if not exist "dist\catnip" (
    echo ERROR: La construcción falló
    exit /b 1
)

echo ========================================
echo Construcción completada exitosamente
echo Los ejecutables están en: dist\catnip\
echo ========================================
