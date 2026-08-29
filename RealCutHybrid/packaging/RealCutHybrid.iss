#ifndef SourceDir
  #error SourceDir must be supplied with /DSourceDir=...
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif
#ifndef AppVersion
  #define AppVersion "2026.08.28"
#endif

[Setup]
AppId={{EC5C0B01-7BF2-4C91-8D2C-43F206545A16}
AppName=RealCut Hybrid
AppVersion={#AppVersion}
AppPublisher=JT
DefaultDirName={localappdata}\RealCutHybrid
DefaultGroupName=RealCut Hybrid
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=RealCutHybrid-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
DiskSpanning=yes
DiskSliceSize=1900000000
SlicesPerDisk=1
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayIcon={app}\bin\web_server.exe

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\RealCut Hybrid"; Filename: "{app}\Start-RealCutHybridWeb.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\RealCut Hybrid"; Filename: "{app}\Start-RealCutHybridWeb.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Start-RealCutHybridWeb.bat"; Description: "启动 RealCut Hybrid"; Flags: nowait postinstall skipifsilent
