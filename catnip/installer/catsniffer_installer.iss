; catsniffer_installer.iss
; Script for Inno Setup

[Setup]
AppId={{3F8E3E2D-2C5B-4A1F-8E3B-1C4D5E6F7A8B}
AppName=Catnip
AppVersion=3.3.1.0
AppPublisher=Electronic Cats
AppPublisherURL=https://github.com/ElectronicCats/CatSniffer-Tools
AppSupportURL=https://github.com/ElectronicCats/CatSniffer-Tools/issues
AppComments=Universal tool for wireless protocols analysis and cat sniffer functionality
AppCopyright=Copyright © 2024 Electronic Cats
DefaultDirName={autopf}\Catnip
DefaultGroupName=Catnip
UninstallDisplayIcon={app}\catnip.exe
Compression=lzma2
SolidCompression=yes
OutputDir=..\dist
OutputBaseFilename=Catnip-Setup
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "Add Catnip to PATH"; GroupDescription: "Configuration:"; Flags: checkedonce
Name: "installdrivers"; Description: "Install USB drivers (recommended)"; GroupDescription: "Configuration:"; Flags: checkedonce

[Files]
Source: "..\dist\catnip\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\scripts\install_windows_drivers.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
; Include libusb if necessary
; (libusb-1.0.dll is now bundled dynamically by PyInstaller in dist\catnip\)

[Icons]
Name: "{group}\Catnip CLI"; Filename: "{cmd}"; Parameters: "/k ""{app}\catnip.exe"""; IconFilename: "{app}\catnip.exe"
Name: "{group}\Catnip Documentation"; Filename: "{app}\README.md"
Name: "{group}\Uninstall Catnip"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Catnip CLI"; Filename: "{cmd}"; Parameters: "/k ""{app}\catnip.exe"""; IconFilename: "{app}\catnip.exe"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\scripts\install_windows_drivers.ps1"" -Silent"; Flags: runhidden; StatusMsg: "Installing USB drivers..."; Tasks: installdrivers
Filename: "{app}\catnip.exe"; Parameters: "--help"; Description: "Verify installation"; Flags: postinstall runhidden

[Registry]
; Add to system PATH if the task was selected
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', OrigPath)
  then begin
    Result := True;
    exit;
  end;
  Result := Pos(Param, OrigPath) = 0;
end;

[UninstallRun]
; Clean up drivers on uninstall (optional)
; Filename: "pnputil"; Parameters: "/delete-driver catsniffer.inf"; Flags: runhidden
