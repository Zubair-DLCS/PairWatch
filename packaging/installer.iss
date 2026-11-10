; Inno Setup script: builds PairWatch-Setup.exe from dist\PairWatch (PyInstaller output + bundled MinGW)
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{3F1C9D52-8B7A-4E0B-A6C4-2D9E71B5F0A3}
AppName=PairWatch
AppVersion={#AppVersion}
AppPublisher=Malak Zubair, G.C.M.S Timergara
AppPublisherURL=https://github.com/Zubair-DLCS/PairWatch
DefaultDirName={localappdata}\Programs\PairWatch
DefaultGroupName=PairWatch
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PairWatch-Setup-{#AppVersion}
SetupIconFile=pairwatch.ico
UninstallDisplayIcon={app}\PairWatch.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\PairWatch\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PairWatch"; Filename: "{app}\PairWatch.exe"
Name: "{group}\Uninstall PairWatch"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PairWatch"; Filename: "{app}\PairWatch.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PairWatch.exe"; Description: "Start PairWatch now"; Flags: nowait postinstall skipifsilent
