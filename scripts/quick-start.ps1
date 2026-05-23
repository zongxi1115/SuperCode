param(
    [switch]$InstallOnly,
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$SkipEnvCopy,
    [switch]$AutoInstallTools,
    [switch]$StartBackend,
    [switch]$StartFrontend,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendDir = Join-Path $repoRoot "frontend"
$requirementsFile = Join-Path $repoRoot "fastapi_app\requirements.txt"
$envExampleFile = Join-Path $repoRoot ".env.example"
$envFile = Join-Path $repoRoot ".env"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Fail {
    param([string]$Message)
    Write-Error $Message
    exit 1
}

function Test-CommandExists {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-Command {
    param(
        [string]$Name,
        [string]$InstallHint
    )

    if (-not (Test-CommandExists $Name)) {
        Fail "$Name 未安装或不在 PATH 中。$InstallHint"
    }
}

function Install-WithWinget {
    param(
        [string]$PackageId,
        [string]$DisplayName
    )

    if (-not (Test-CommandExists "winget")) {
        Fail "缺少 $DisplayName，且当前系统没有 winget，无法自动安装。请手动安装后重试。"
    }

    Write-Step "自动安装 $DisplayName"
    & winget install --id $PackageId --exact --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Fail "$DisplayName 自动安装失败，请手动安装后重试。"
    }

    Write-Host "$DisplayName 已调用 winget 安装。若当前终端仍识别不到该命令，请关闭后重新打开终端再执行脚本。" -ForegroundColor Yellow
}

function Ensure-BaseTool {
    param(
        [string]$Name,
        [string]$InstallHint,
        [string]$WingetPackageId = ""
    )

    if (Test-CommandExists $Name) {
        return
    }

    if ($AutoInstallTools -and $WingetPackageId) {
        Install-WithWinget -PackageId $WingetPackageId -DisplayName $Name
        return
    }

    Fail "$Name 未安装或不在 PATH 中。$InstallHint"
}

function Ensure-Pnpm {
    if (Test-CommandExists "pnpm") {
        return
    }

    if (-not $AutoInstallTools) {
        Fail "pnpm 未安装或不在 PATH 中。请先安装 pnpm，例如执行 npm install -g pnpm，或使用 -AutoInstallTools 自动安装。"
    }

    if (Test-CommandExists "npm") {
        Write-Step "自动安装 pnpm"
        & npm install -g pnpm
        if ($LASTEXITCODE -eq 0 -and (Test-CommandExists "pnpm")) {
            return
        }
    }

    if (Test-CommandExists "winget") {
        Install-WithWinget -PackageId "pnpm.pnpm" -DisplayName "pnpm"
        if (Test-CommandExists "pnpm") {
            return
        }

        Fail "pnpm 已尝试通过 winget 安装，但当前终端还未识别到 pnpm。请重新打开终端后再次执行脚本。"
    }

    Fail "pnpm 自动安装失败。请手动安装 pnpm 后重试。"
}

function Ensure-NodeVersion {
    $nodeVersionOutput = & node --version
    if ($LASTEXITCODE -ne 0) {
        Fail "无法读取 Node 版本。"
    }

    $versionText = $nodeVersionOutput.TrimStart("v")
    $majorVersion = [int]($versionText.Split(".")[0])
    if ($majorVersion -lt 18) {
        Fail "检测到 Node 版本为 $nodeVersionOutput，当前项目要求 Node >= 18。"
    }
}

function Ensure-PythonVersion {
    $pythonVersionOutput = & python --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Fail "无法读取 Python 版本。"
    }

    if ($pythonVersionOutput -notmatch "Python\s+(\d+)\.(\d+)") {
        Fail "无法解析 Python 版本：$pythonVersionOutput"
    }

    $majorVersion = [int]$Matches[1]
    $minorVersion = [int]$Matches[2]
    if ($majorVersion -lt 3 -or ($majorVersion -eq 3 -and $minorVersion -lt 10)) {
        Fail "检测到 Python 版本为 $pythonVersionOutput，当前项目要求 Python >= 3.10。"
    }
}

function Warn-IfNotInCondaBase {
    if ($env:CONDA_DEFAULT_ENV -ne "base") {
        Write-Host "当前不是 conda 的 base 环境。建议先执行 conda activate base 再继续。" -ForegroundColor Yellow
    }
}

function Install-BackendDependencies {
    Write-Step "安装后端依赖"
    Push-Location $repoRoot
    try {
        & python -m pip install -r $requirementsFile
        if ($LASTEXITCODE -ne 0) {
            Fail "后端依赖安装失败。"
        }
    }
    finally {
        Pop-Location
    }
}

function Install-FrontendDependencies {
    Write-Step "安装前端依赖"
    Push-Location $frontendDir
    try {
        & pnpm install
        if ($LASTEXITCODE -ne 0) {
            Fail "前端依赖安装失败。"
        }
    }
    finally {
        Pop-Location
    }
}

function Ensure-EnvFile {
    if ($SkipEnvCopy) {
        return
    }

    if ((-not (Test-Path $envFile)) -and (Test-Path $envExampleFile)) {
        Write-Step "创建 .env 文件"
        Copy-Item $envExampleFile $envFile
        Write-Host ".env 已根据 .env.example 创建，请按需填写真实模型配置。" -ForegroundColor Yellow
    }
}

function Show-NextSteps {
    Write-Host ""
    Write-Host "准备完成，可使用以下命令启动：" -ForegroundColor Green
    Write-Host "后端: python -m uvicorn fastapi_app.main:app --host 0.0.0.0 --port $BackendPort --reload"
    Write-Host "前端: cd frontend; pnpm dev --host 0.0.0.0 --port $FrontendPort"
    Write-Host ""
    Write-Host "如果你只想跑 CLI demo：" -ForegroundColor Green
    Write-Host "python examples/run_demo.py"
}

function Start-BackendServer {
    Write-Step "启动后端服务"
    $backendCommand = "Set-Location '$repoRoot'; python -m uvicorn fastapi_app.main:app --host 0.0.0.0 --port $BackendPort --reload"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCommand -WindowStyle Normal | Out-Null
}

function Start-FrontendServer {
    Write-Step "启动前端服务"
    $frontendCommand = "Set-Location '$frontendDir'; pnpm dev --host 0.0.0.0 --port $FrontendPort"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCommand -WindowStyle Normal | Out-Null
}

if ($BackendOnly -and $FrontendOnly) {
    Fail "不能同时指定 -BackendOnly 和 -FrontendOnly。"
}

Write-Step "检查基础环境"
Ensure-BaseTool -Name "python" -InstallHint "请先安装 Python，并确保可以直接执行 python；也可以使用 -AutoInstallTools 自动安装。" -WingetPackageId "Python.Python.3.11"
Ensure-BaseTool -Name "node" -InstallHint "请先安装 Node.js 18+；也可以使用 -AutoInstallTools 自动安装。" -WingetPackageId "OpenJS.NodeJS.LTS"
Ensure-Pnpm
Warn-IfNotInCondaBase
Ensure-PythonVersion
Ensure-NodeVersion
Ensure-EnvFile

$runBackend = -not $FrontendOnly
$runFrontend = -not $BackendOnly

if ($runBackend) {
    Install-BackendDependencies
}

if ($runFrontend) {
    Install-FrontendDependencies
}

if ($InstallOnly) {
    Write-Step "依赖安装完成"
    Show-NextSteps
    exit 0
}

Write-Step "依赖安装完成"

if ($StartBackend) {
    Start-BackendServer
}

if ($StartFrontend) {
    Start-FrontendServer
}

Show-NextSteps
