; SPDX-License-Identifier: GPL-3.0-or-later
; Inno Setup script for IngeCAD on Windows (#28).
;
; Wraps the PyInstaller one-dir bundle (packaging/ingecad.spec) in an
; installer: multilingual wizard, GPL licence page, Start-menu entry,
; "Open with" for .dwg and .dxf (and, if the user keeps the box ticked,
; double-click), and a clean uninstaller. Mirrors IngeTrazo's.
;
; Local build (Inno Setup 6+), from the repo root:
;     iscc /DMyAppVersion=0.6.6 packaging\windows\ingecad.iss
; CI: .github/workflows/build-windows.yml
;
; The AppId is a FIXED GUID: changing it makes Windows treat every release
; as a different program, and upgrades stop replacing the old one.

#define MyAppName "IngeCAD"
#define MyAppPublisher "Ing. Marco Sumari Tellez"
#define MyAppURL "https://ingecad.org"
#define MyAppExeName "ingecad.exe"

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{7CB5D165-180B-4865-8D0B-832281FBCE36}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL=https://github.com/ingelibre/ingecad/issues
AppUpdatesURL=https://github.com/ingelibre/ingecad/releases
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=CAD 2D libre al estilo del AutoCAD clasico
VersionInfoProductName={#MyAppName}

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

LicenseFile=..\..\LICENSE

OutputDir=..\..\dist
OutputBaseFilename=ingecad-setup-v{#MyAppVersion}

WizardStyle=modern
ShowLanguageDialog=auto
DisableProgramGroupPage=yes
ChangesAssociations=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\..\resources\icons\ingecad.ico

[Languages]
; English first: the fallback when Windows speaks none of the others.
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"

[CustomMessages]
english.FileAssociations=Open with IngeCAD on double-click:
english.DwgDefault=AutoCAD drawings (.dwg)
english.DxfDefault=Drawing exchange files (.dxf)
english.DwgDocument=AutoCAD drawing (IngeCAD)
english.DxfDocument=DXF drawing (IngeCAD)
spanish.FileAssociations=Abrir con IngeCAD al hacer doble clic:
spanish.DwgDefault=Dibujos de AutoCAD (.dwg)
spanish.DxfDefault=Archivos de intercambio (.dxf)
spanish.DwgDocument=Dibujo de AutoCAD (IngeCAD)
spanish.DxfDocument=Dibujo DXF (IngeCAD)
french.FileAssociations=Ouvrir avec IngeCAD par double-clic :
french.DwgDefault=Dessins AutoCAD (.dwg)
french.DxfDefault=Fichiers d'échange (.dxf)
french.DwgDocument=Dessin AutoCAD (IngeCAD)
french.DxfDocument=Dessin DXF (IngeCAD)
portuguese.FileAssociations=Abrir com o IngeCAD com duplo clique:
portuguese.DwgDefault=Desenhos AutoCAD (.dwg)
portuguese.DxfDefault=Ficheiros de intercâmbio (.dxf)
portuguese.DwgDocument=Desenho AutoCAD (IngeCAD)
portuguese.DxfDocument=Desenho DXF (IngeCAD)
czech.FileAssociations=Otevírat v IngeCAD dvojklikem:
czech.DwgDefault=Výkresy AutoCAD (.dwg)
czech.DxfDefault=Výměnné soubory (.dxf)
czech.DwgDocument=Výkres AutoCAD (IngeCAD)
czech.DxfDocument=Výkres DXF (IngeCAD)

[Tasks]
Name: "dwgdefault"; Description: "{cm:DwgDefault}"; GroupDescription: "{cm:FileAssociations}"
Name: "dxfdefault"; Description: "{cm:DxfDefault}"; GroupDescription: "{cm:FileAssociations}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\ingecad\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\resources\icons\mimetypes\ingecad-dwg.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\resources\icons\mimetypes\ingecad-dxf.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; One ProgId per format, always listed under "Open with"; the extension's
; default (double-click) only when its task stays ticked. Uninstalling
; removes both and Windows falls back to the previous program.
Root: HKA; Subkey: "Software\Classes\IngeCAD.dwg"; ValueType: string; \
    ValueData: "{cm:DwgDocument}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\IngeCAD.dwg\DefaultIcon"; \
    ValueType: string; ValueData: "{app}\ingecad-dwg.ico,0"
Root: HKA; Subkey: "Software\Classes\IngeCAD.dwg\shell\open\command"; \
    ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.dwg\OpenWithProgids"; \
    ValueType: string; ValueName: "IngeCAD.dwg"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.dwg"; ValueType: string; \
    ValueData: "IngeCAD.dwg"; Tasks: dwgdefault; Flags: uninsdeletevalue

Root: HKA; Subkey: "Software\Classes\IngeCAD.dxf"; ValueType: string; \
    ValueData: "{cm:DxfDocument}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\IngeCAD.dxf\DefaultIcon"; \
    ValueType: string; ValueData: "{app}\ingecad-dxf.ico,0"
Root: HKA; Subkey: "Software\Classes\IngeCAD.dxf\shell\open\command"; \
    ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.dxf\OpenWithProgids"; \
    ValueType: string; ValueName: "IngeCAD.dxf"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.dxf"; ValueType: string; \
    ValueData: "IngeCAD.dxf"; Tasks: dxfdefault; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent
