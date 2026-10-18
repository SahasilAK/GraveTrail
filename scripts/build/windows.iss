#ifndef Version
  #error Version is required
#endif
#ifndef Bundle
  #error Bundle is required
#endif
#ifndef Output
  #error Output is required
#endif
#ifndef Publisher
  #define Publisher "GraveTrail contributors"
#endif

[Setup]
AppId={{5F353BCE-C630-44ED-BB75-CE2F19CAD4EF}
AppName=GraveTrail
AppVersion={#Version}
AppPublisher={#Publisher}
VersionInfoVersion={#Version}.0
DefaultDirName={localappdata}\Programs\GraveTrail
DefaultGroupName=GraveTrail
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#Output}
#ifdef Production
OutputBaseFilename=gravetrail-{#Version}-windows-amd64-setup
SignTool=gravetrail
SignedUninstaller=yes
#else
OutputBaseFilename=gravetrail-{#Version}-windows-amd64-setup-unsigned
AppVerName=GraveTrail {#Version} (unsigned development)
#endif
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=Local\GraveTrail.Application
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\gravetrail.exe
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#Bundle}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\GraveTrail"; Filename: "{app}\gravetrail.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\GraveTrail"; Filename: "{app}\gravetrail.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\gravetrail.exe"; Description: "Launch GraveTrail"; Flags: nowait postinstall skipifsilent
