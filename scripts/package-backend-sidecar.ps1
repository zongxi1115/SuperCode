param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [string]$CondaEnv = "supercode-build"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$entrypoint = Join-Path $repoRoot "fastapi_app\desktop_entry.py"
$binariesDir = Join-Path $repoRoot "src-tauri\binaries"
$buildDir = Join-Path $repoRoot ".supercode\pyinstaller-build"
$specDir = Join-Path $repoRoot ".supercode\pyinstaller-spec"
$binaryName = "supercode-backend-$TargetTriple"

if (-not (Test-Path $entrypoint)) {
    throw "Cannot find backend desktop entrypoint: $entrypoint"
}

New-Item -ItemType Directory -Force -Path $binariesDir | Out-Null
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
New-Item -ItemType Directory -Force -Path $specDir | Out-Null

$pyInstallerArgs = @(
    "-m", "PyInstaller",
    "--clean",
    "--noconfirm",
    "--onefile",
    "--windowed",
    "--name", $binaryName,
    "--paths", $repoRoot,
    "--distpath", $binariesDir,
    "--workpath", $buildDir,
    "--specpath", $specDir,
    "--add-data", "$repoRoot\coding_agent\prompts;coding_agent\prompts",
    "--add-data", "$repoRoot\deploy_agent\prompts;deploy_agent\prompts",
    "--add-data", "$repoRoot\plan_agent\prompts;plan_agent\prompts",
    "--collect-all", "tree_sitter_language_pack",
    "--exclude-module", "IPython",
    "--exclude-module", "pytest",
    "--exclude-module", "black",
    "--exclude-module", "matplotlib",
    "--exclude-module", "numpy",
    "--exclude-module", "pandas",
    "--exclude-module", "scipy",
    $entrypoint
)

conda run -n $CondaEnv python @pyInstallerArgs

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Write-Host "Backend sidecar written to $binariesDir\$binaryName.exe" -ForegroundColor Green

<#
Previous direct invocation kept here as a shape reference:
python -m PyInstaller `
    --clean `
    --noconfirm `
    --onefile `
    --windowed `
    --name $binaryName `
    --paths $repoRoot `
    --distpath $binariesDir `
    --workpath $buildDir `
    --specpath $specDir `
    --collect-all tree_sitter_language_pack `
    $entrypoint
#>
