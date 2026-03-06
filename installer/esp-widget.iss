[Setup]
AppId={{F8BFD4A6-6B2D-4888-9B5F-DF0935897496}
AppName=ESP Widget
AppVersion=1.0.0
DefaultDirName={autopf}\ESP Widget
DefaultGroupName=ESP Widget
PrivilegesRequired=admin
OutputDir=..\dist
OutputBaseFilename=ESPWidgetInstaller
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\release\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ESP Widget"; Filename: "{app}\esp_widget.exe"
Name: "{autodesktop}\ESP Widget"; Filename: "{app}\esp_widget.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\esp_widget.exe"; Description: "Launch ESP Widget"; Flags: nowait postinstall skipifsilent

[Code]
function RunSchtasks(const Params: string; var ExitCode: Integer): Boolean;
begin
  Result := Exec(ExpandConstant('{sys}\schtasks.exe'), Params, '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
end;

procedure CreateBackendAutostartTask();
var
  ExitCode: Integer;
  Params: string;
begin
  Params :=
    '/Create /F /SC ONLOGON /RL LIMITED ' +
    '/TN "ESPWidgetBackend" ' +
    '/TR "' + ExpandConstant('{app}\backend_service.exe') + '"';

  if (not RunSchtasks(Params, ExitCode)) or (ExitCode <> 0) then
  begin
    MsgBox(
      'Не удалось создать задачу автозапуска backend (ESPWidgetBackend).' + #13#10 +
      'Можно включить автозапуск в самом приложении при первом запуске.',
      mbError,
      MB_OK
    );
  end;
end;

procedure DeleteBackendAutostartTask();
var
  ExitCode: Integer;
begin
  RunSchtasks('/Delete /F /TN "ESPWidgetBackend"', ExitCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    CreateBackendAutostartTask();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    DeleteBackendAutostartTask();
  end;
end;
