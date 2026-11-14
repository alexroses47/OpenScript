; OpenScript installer for Windows (Inno Setup 6).
;
;   ISCC.exe /DAppVersion=1.2.0 /DSourceDir=..\..\dist\OpenScript packaging\windows\openscript.iss
;
; SourceDir is the assembled app folder (OpenScript.exe + app\ + _internal\),
; the same content as the portable zip.

#ifndef AppVersion
  #define AppVersion "dev"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\OpenScript"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif

[Setup]
; Never change AppId: it lets new versions upgrade the existing installation.
AppId={{7E2B6C1A-5F3D-4C8E-9A61-0B4D2F8E1C37}
AppName=OpenScript
AppVersion={#AppVersion}
AppVerName=OpenScript {#AppVersion}
AppPublisher=OpenScript
AppPublisherURL=https://github.com/alexroses47/OpenScript
AppSupportURL=https://github.com/alexroses47/OpenScript/issues
AppUpdatesURL=https://github.com/alexroses47/OpenScript/releases
; Per-user install by default (no administrator rights needed); the user can
; choose "install for all users" in the first page.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\OpenScript
DisableDirPage=no
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=OpenScript-{#AppVersion}-windows-setup
SetupIconFile=..\..\assets\openscript.ico
UninstallDisplayIcon={app}\OpenScript.exe
UninstallDisplayName=OpenScript
WizardStyle=modern
WizardImageFile=wizard.bmp
WizardSmallImageFile=wizard-small.bmp
Compression=lzma2/max
SolidCompression=yes
ChangesAssociations=yes
CloseApplications=yes
; The engine is 32-bit and runs on 64-bit Windows (and Windows on ARM via emulation).
ArchitecturesAllowed=x86compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "associate"; Description: "{cm:AssocCeltx}"; GroupDescription: "{cm:AssocGroup}"

[CustomMessages]
english.AssocCeltx=Open .celtx projects with OpenScript
english.AssocGroup=File types:
spanish.AssocCeltx=Abrir los proyectos .celtx con OpenScript
spanish.AssocGroup=Tipos de archivo:

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\OpenScript"; Filename: "{app}\OpenScript.exe"
Name: "{autodesktop}\OpenScript"; Filename: "{app}\OpenScript.exe"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.celtx"; ValueType: string; ValueName: ""; ValueData: "OpenScript.Project"; Flags: uninsdeletevalue; Tasks: associate
Root: HKA; Subkey: "Software\Classes\OpenScript.Project"; ValueType: string; ValueName: ""; ValueData: "OpenScript project"; Flags: uninsdeletekey; Tasks: associate
Root: HKA; Subkey: "Software\Classes\OpenScript.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\OpenScript.exe,0"; Tasks: associate
Root: HKA; Subkey: "Software\Classes\OpenScript.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\OpenScript.exe"" ""%1"""; Tasks: associate

[Run]
Filename: "{app}\OpenScript.exe"; Description: "{cm:LaunchProgram,OpenScript}"; Flags: nowait postinstall skipifsilent

; Your projects and your OpenScript profile (%APPDATA%\Greyfirst) are not
; removed by the uninstaller.
