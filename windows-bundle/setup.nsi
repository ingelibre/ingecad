Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!include "FileFunc.nsh"
Name "IngeCAD AI Bundle"
OutFile "dist\IngeCAD-AI-Setup-0.6.5-0.3.2-x64.exe"
InstallDir "$LOCALAPPDATA\Programs\IngeCAD-AI"
RequestExecutionLevel user
SetCompressor zlib
ShowInstDetails show
ShowUninstDetails show
VIProductVersion "0.6.5.32"
VIAddVersionKey "ProductName" "IngeCAD AI Bundle"
VIAddVersionKey "FileDescription" "IngeCAD 0.6.5 + Python + LibreDWG + AI/MCP 0.3.2 offline setup"
VIAddVersionKey "FileVersion" "0.6.5.32"
VIAddVersionKey "LegalCopyright" "IngeCAD contributors; see installed licenses"
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "stage\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
Var Brand
Var IsTest
Var Result
Var Params

Function .onInit
  SetShellVarContext current
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "This bundle requires 64-bit Windows." /SD IDOK
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_ICONSTOP "This bundle requires Windows 10 or later." /SD IDOK
    Abort
  ${EndIf}
  StrCpy $Brand "IngeCAD AI Bundle"
  ${GetParameters} $Params
  ClearErrors
  ${GetOptions} $Params "/TESTMODE" $IsTest
  ${IfNot} ${Errors}
    StrCpy $Brand "IngeCAD AI Bundle Test"
  ${EndIf}
FunctionEnd

Section "IngeCAD + Python + DWG + AI/MCP"
  ; Refuse to overwrite an unrelated populated folder.
  IfFileExists "$INSTDIR\bundle-manifest.json" folder_ok
  IfFileExists "$INSTDIR\*.*" 0 folder_ok
  MessageBox MB_ICONSTOP "Choose a new empty folder, or the folder of an existing IngeCAD AI Bundle installation." /SD IDOK
  Abort
folder_ok:
  !include "payload-files.nsh"
  ExecWait '"$INSTDIR\runtime\python.exe" -B "$INSTDIR\install_checks.py"' $Result
  ${If} $Result != 0
    MessageBox MB_ICONSTOP "The offline runtime check failed. Installation did not finish. See the installation details and install_checks.py." /SD IDOK
    Abort
  ${EndIf}
  WriteINIStr "$INSTDIR\bundle-install.ini" "Install" "Brand" "$Brand"
  WriteINIStr "$INSTDIR\bundle-install.ini" "Install" "Directory" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\$Brand"
  CreateShortcut "$DESKTOP\$Brand.lnk" "$INSTDIR\IngeCAD.exe" "" "$INSTDIR\IngeCAD.exe"
  CreateShortcut "$SMPROGRAMS\$Brand\$Brand.lnk" "$INSTDIR\IngeCAD.exe" "" "$INSTDIR\IngeCAD.exe"
  CreateShortcut "$SMPROGRAMS\$Brand\MCP configuration.lnk" "$INSTDIR\MCP-config"
  CreateShortcut "$SMPROGRAMS\$Brand\Installation guide.lnk" "$INSTDIR\README-TH.txt"
  CreateShortcut "$SMPROGRAMS\$Brand\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\$Brand" "DisplayName" "$Brand"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\$Brand" "DisplayVersion" "0.6.5 + AI/MCP 0.3.2"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\$Brand" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\$Brand" "DisplayIcon" "$INSTDIR\IngeCAD.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\$Brand" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\$Brand" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\$Brand" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\$Brand" "NoRepair" 1
SectionEnd

Function un.onInit
  SetShellVarContext current
  ReadINIStr $Brand "$INSTDIR\bundle-install.ini" "Install" "Brand"
  ReadINIStr $Result "$INSTDIR\bundle-install.ini" "Install" "Directory"
  ${If} $Brand != "IngeCAD AI Bundle"
  ${AndIf} $Brand != "IngeCAD AI Bundle Test"
    Abort
  ${EndIf}
  ${If} $Result != $INSTDIR
    MessageBox MB_ICONSTOP "Installation location changed. Run setup again in this folder before uninstalling." /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Section "Uninstall"
  ; No recursive directory deletion: unknown files, drawings and user credentials survive.
  !include "payload-uninstall.nsh"
  Delete "$INSTDIR\plugins\ingecad_mcp\connection.json"
  Delete "$INSTDIR\MCP-config\client-config.json"
  Delete "$INSTDIR\MCP-config\vscode-mcp.json"
  Delete "$INSTDIR\MCP-config\codex-config.toml"
  Delete "$INSTDIR\MCP-config\commands.txt"
  Delete "$INSTDIR\install-check.json"
  Delete "$INSTDIR\bundle-install.ini"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR\plugins\ingecad_mcp"
  RMDir "$INSTDIR\plugins"
  RMDir "$INSTDIR\MCP-config"
  RMDir "$INSTDIR"
  Delete "$DESKTOP\$Brand.lnk"
  Delete "$SMPROGRAMS\$Brand\$Brand.lnk"
  Delete "$SMPROGRAMS\$Brand\MCP configuration.lnk"
  Delete "$SMPROGRAMS\$Brand\Installation guide.lnk"
  Delete "$SMPROGRAMS\$Brand\Uninstall.lnk"
  RMDir "$SMPROGRAMS\$Brand"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\$Brand"
SectionEnd
