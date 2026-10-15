; Inno Setup script: packages dist\PDFReader\ (built by PDFReader.spec) into
; dist\PDFReader-Setup-<version>.exe.  Build with build.bat or:
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss

#define AppName "PDF Reader"
#define AppVersion "1.2.0"
#define AppExe "PDFReader.exe"
#define ProgId "PDFReader.Document"

[Setup]
AppId={{8C1F6A52-3B7E-4F0E-9D7A-2F5B1C9E4A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription={#AppName} Setup
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Installs for the current user without admin rights by default; the user
; can choose "for all users" in the first dialog.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=dist
OutputBaseFilename=PDFReader-Setup-{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
AppMutex=PDFReaderAppMutex
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
russian.PdfDocument=Документ PDF
russian.AppDescription=Быстрый автономный просмотрщик PDF
russian.UpdateShortcut=Обновить {#AppName}
russian.ChooseDefault=Открыть параметры Windows, чтобы сделать {#AppName} программой по умолчанию для PDF
english.PdfDocument=PDF Document
english.AppDescription=Fast offline PDF viewer
english.UpdateShortcut=Update {#AppName}
english.ChooseDefault=Open Windows Settings to make {#AppName} the default PDF app

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\PDFReader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\Update.cmd"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; files of an older build that no longer exist in the new one
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{cm:UpdateShortcut}"; Filename: "{app}\{#AppExe}"; Parameters: "--update --yes"; IconFilename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Document type (ProgID) used by Explorer for PDF files
Root: HKA; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueName: ""; ValueData: "{cm:PdfDocument}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
; Application entry ("Open with" list, friendly name)
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue
; Registration for Settings > Apps > Default apps
Root: HKA; Subkey: "Software\PDFReader\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\PDFReader\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "{cm:AppDescription}"
Root: HKA; Subkey: "Software\PDFReader\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\PDFReader\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#ProgId}"
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#AppName}"; ValueData: "Software\PDFReader\Capabilities"; Flags: uninsdeletevalue

[Run]
; after a silent self-update (/RELAUNCH=1) start the new version
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: ShouldRelaunch
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
Filename: "ms-settings:defaultapps?registeredAppUser={#AppName}"; Description: "{cm:ChooseDefault}"; Flags: shellexec postinstall skipifsilent unchecked nowait; Check: not IsAdminInstallMode
Filename: "ms-settings:defaultapps?registeredAppMachine={#AppName}"; Description: "{cm:ChooseDefault}"; Flags: shellexec postinstall skipifsilent unchecked nowait; Check: IsAdminInstallMode

[Code]
function ShouldRelaunch: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;
