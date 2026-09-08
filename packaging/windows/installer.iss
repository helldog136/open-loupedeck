; Inno Setup script for open-loupedeck (Windows installer).
;
; Build the PyInstaller onedir bundle first (from the repo root):
;   pyinstaller packaging/pyinstaller.spec --noconfirm
; Then compile this script (pass the version explicitly so it matches pyproject.toml, e.g. from CI):
;   iscc packaging\windows\installer.iss /DMyAppVersion=0.1.0
; Output: packaging\windows\output\open-loupedeck-Setup-<version>.exe

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

#define MyAppName "open-loupedeck"
#define MyAppExeName "open-loupedeck.exe"
#define DistDir "..\..\dist\open-loupedeck"

[Setup]
AppId={{7F3D9E9E-9C7A-4C3B-9B0E-3B1E9E7B7B41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=open-loupedeck
AppUpdatesURL=https://github.com/helldog136/open-loupedeck/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Detected by tray_app.py's CreateMutexW at startup, so /CLOSEAPPLICATIONS (used by the
; in-app auto-updater) can find and close a running instance via the Restart Manager.
AppMutex=OpenLoupedeckTrayMutex
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=output
OutputBaseFilename=open-loupedeck-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\..\src\open_loupedeck\icons\app.ico
WizardStyle=modern

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

[Run]
; No `skipifsilent`: this must still relaunch the app after a *silent* install, which is how
; the in-app auto-updater invokes this installer (updater.apply_windows_update).
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall

[Code]
// Best-effort WebView2 Runtime check: pywebview's Windows backend needs it. It ships with
// Windows 10 1809+ and Windows 11 via Windows Update, so this only matters on older/locked-down
// systems. If missing, offer to fetch Microsoft's small evergreen bootstrapper.
function IsWebView2RuntimeInstalled(): Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
end;

procedure InitializeWizard();
var
  ErrorCode: Integer;
begin
  if not IsWebView2RuntimeInstalled() then
  begin
    if MsgBox('open-loupedeck a besoin du runtime Microsoft Edge WebView2, absent sur cette machine.' + #13#10 +
               'Ouvrir la page de téléchargement Microsoft maintenant ?', mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', 'https://developer.microsoft.com/microsoft-edge/webview2/', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
  end;
end;
