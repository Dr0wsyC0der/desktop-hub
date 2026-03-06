Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Stop-ReleaseProcesses {
    $names = @("backend_service", "esp_widget")
    foreach ($name in $names) {
        $items = Get-Process -Name $name -ErrorAction SilentlyContinue
        if ($null -ne $items) {
            Write-Host "Stopping process: $name"
            $items | Stop-Process -Force -ErrorAction SilentlyContinue
        }
    }
}

function Remove-TreeWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$PathToRemove,
        [int]$Attempts = 6,
        [int]$DelayMs = 600
    )

    if (-not (Test-Path $PathToRemove)) {
        return
    }

    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            Remove-Item -Path $PathToRemove -Recurse -Force -ErrorAction Stop
            return
        } catch {
            if ($i -eq $Attempts) {
                throw
            }
            Start-Sleep -Milliseconds $DelayMs
        }
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

Write-Host "Installing build tooling..."
python -m pip install --upgrade pyinstaller

Write-Host "Stopping running release processes..."
Stop-ReleaseProcesses

Write-Host "Cleaning previous PyInstaller artifacts..."
Remove-TreeWithRetry -PathToRemove "build"
Remove-TreeWithRetry -PathToRemove "dist"

Write-Host "Building backend_service.exe..."
python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --name backend_service `
    pc_service\backend\main.py

Write-Host "Building esp_widget.exe..."
$fletDesktopApp = python -c "import pathlib, flet_desktop; print(pathlib.Path(flet_desktop.__file__).resolve().parent / 'app')"
$fletDesktopApp = $fletDesktopApp.Trim()
if (-not (Test-Path $fletDesktopApp)) {
    throw "Flet runtime executable not found: $fletDesktopApp"
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --name esp_widget `
    --icon pc_service\ui\assets\app.ico `
    --collect-all flet `
    --collect-all flet_desktop `
    --add-data "$fletDesktopApp;flet_desktop" `
    pc_service\ui\app.py

$releaseDir = Join-Path $repoRoot "dist\release"
New-Item -Path $releaseDir -ItemType Directory -Force | Out-Null

Copy-Item "dist\backend_service.exe" $releaseDir -Force
Copy-Item "dist\esp_widget.exe" $releaseDir -Force

$backendDir = Join-Path $releaseDir "backend"
New-Item -Path $backendDir -ItemType Directory -Force | Out-Null
Copy-Item "pc_service\backend\storage" $backendDir -Recurse -Force

Write-Host ""
Write-Host "Release bundle is ready:"
Write-Host "  $releaseDir"
