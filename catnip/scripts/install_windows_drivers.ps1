# scripts\install_windows_drivers.ps1
param(
    [switch]$Silent = $false
)

function Write-Status {
    param($Message, $Color = "White")
    Write-Host "[*] $Message" -ForegroundColor $Color
}

function Write-Success {
    param($Message)
    Write-Host "[+] $Message" -ForegroundColor Green
}

function Write-Error {
    param($Message)
    Write-Host "[-] $Message" -ForegroundColor Red
}

Write-Status "Installing drivers for CatSniffer..." "Blue"

# Check if running as administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "This script must be run as Administrator"
    exit 1
}

# Register the device with Zadig or install CDC driver
Write-Status "Configuring serial ports..." "Blue"

# Create .inf file for the device
$infContent = @"
; CatSniffer USB Driver Installation
[Version]
Signature="$Windows NT$"
Class=Ports
ClassGuid={4d36e978-e325-11ce-bfc1-08002be10318}
Provider=%Provider%
DriverVer=10/01/2023,1.0.0.0

[Manufacturer]
%Provider%=DeviceList

[DeviceList]
%DeviceName%=USB_Install, USB\VID_1B4F&PID_0016

[USB_Install]
Include=mdmcpq.inf
CopyFiles=FakeModemCopyFileSection
AddReg=UpperFilterAddReg

[USB_Install.Services]
Include=mdmcpq.inf
AddService=usbser, 0x0002, LowerFilter_Service_Inst

[UpperFilterAddReg]
HKR, , UpperFilters, 0x00010000, "usbser"

[Strings]
Provider="Electronic Cats"
DeviceName="CatSniffer"
"@

$infPath = "$env:TEMP\catsniffer.inf"
Set-Content -Path $infPath -Value $infContent

# Install the driver using pnputil
Write-Status "Installing USB driver..." "Blue"
try {
    pnputil /add-driver $infPath /install
    Write-Success "Driver installed successfully"
} catch {
    Write-Error "Error installing driver: $_"
}

# Add firewall rules (if needed for Wireshark)
Write-Status "Configuring firewall for Wireshark..." "Blue"
try {
    New-NetFirewallRule -DisplayName "CatSniffer" -Direction Inbound -Program "$env:ProgramFiles\Wireshark\Wireshark.exe" -Action Allow -ErrorAction SilentlyContinue
    Write-Success "Firewall rules configured"
} catch {
    Write-Error "Error configuring firewall: $_"
}

Write-Success "Driver installation completed"
Write-Status "Please reconnect your CatSniffer to apply the changes" "Yellow"
