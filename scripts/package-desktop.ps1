param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [string]$CondaEnv = "supercode-build",
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$SkipStopProcesses
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendDir = Join-Path $repoRoot "frontend"
$tauriDir = Join-Path $repoRoot "src-tauri"
$backendPackageScript = Join-Path $PSScriptRoot "package-backend-sidecar.ps1"
$tauriCli = Join-Path $frontendDir "node_modules\.bin\tauri.CMD"
$nsisInstaller = Join-Path $tauriDir "target\release\bundle\nsis\SuperCode_0.1.0_x64-setup.exe"
$msiInstaller = Join-Path $tauriDir "target\release\bundle\msi\SuperCode_0.1.0_x64_en-US.msi"

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Script
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Script
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

function Stop-SuperCodeProcesses {
    $processNames = @("supercode-desktop", "supercode-backend")
    $processes = Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $processNames -contains $_.ProcessName }

    if (-not $processes) {
        Write-Host "No running SuperCode desktop processes found." -ForegroundColor DarkGray
        return
    }

    foreach ($process in $processes) {
        Write-Host "Stopping $($process.ProcessName) ($($process.Id))" -ForegroundColor Yellow
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }

    Start-Sleep -Seconds 1
}

if (-not (Test-Path $frontendDir)) {
    throw "Cannot find frontend directory: $frontendDir"
}
if (-not (Test-Path $tauriDir)) {
    throw "Cannot find Tauri directory: $tauriDir"
}
if (-not (Test-Path $tauriCli)) {
    throw "Cannot find Tauri CLI: $tauriCli. Run pnpm install in the frontend first."
}

Write-Host "SuperCode desktop packaging" -ForegroundColor Green
Write-Host "Repo: $repoRoot" -ForegroundColor DarkGray

if (-not $SkipStopProcesses) {
    Invoke-Step "Stop old desktop processes" {
        Stop-SuperCodeProcesses
    }
}

if (-not $SkipBackend) {
    Invoke-Step "Build Python backend sidecar" {
        & powershell -ExecutionPolicy Bypass -File $backendPackageScript `
            -TargetTriple $TargetTriple `
            -CondaEnv $CondaEnv
    }
}

if (-not $SkipFrontend) {
    Invoke-Step "Build frontend" {
        & pnpm --dir $frontendDir build
    }
}

Invoke-Step "Build Tauri desktop bundles" {
    Push-Location $tauriDir
    try {
        & $tauriCli build
    }
    finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "Desktop packaging finished." -ForegroundColor Green
Write-Host "NSIS: $nsisInstaller" -ForegroundColor Green
Write-Host "MSI : $msiInstaller" -ForegroundColor Green
