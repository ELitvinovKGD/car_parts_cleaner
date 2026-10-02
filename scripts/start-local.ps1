$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot ".runtime\ComfyUI_windows_portable"
$comfyPython = Join-Path $runtimeRoot "python_embeded\python.exe"
$comfyRoot = Join-Path $runtimeRoot "ComfyUI"
$appPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logsRoot = Join-Path $projectRoot ".runtime\logs"
$comfyProcess = $null

if (-not (Test-Path -LiteralPath $comfyPython)) {
    throw "ComfyUI is not installed. Run: .\scripts\setup-comfyui.ps1"
}
if (-not (Test-Path -LiteralPath $appPython)) {
    throw "Project environment is missing. Create .venv and install the project first."
}

$existingApp = $null
try {
    $existingApp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2
} catch {
    $existingApp = $null
}
if ($null -ne $existingApp) {
    if ($existingApp.backend -eq "comfyui") {
        Write-Host "Body Repair AI is already running with ComfyUI on http://127.0.0.1:8000"
        exit 0
    }
    throw "Port 8000 is occupied by the old $($existingApp.backend) backend. Stop it with Ctrl+C and run this script again."
}

function Test-ComfyUI {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:8188/system_stats" -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-ComfyUI)) {
    New-Item -ItemType Directory -Force -Path $logsRoot | Out-Null
    $comfyProcess = Start-Process `
        -FilePath $comfyPython `
        -ArgumentList @(
            "main.py", "--windows-standalone-build", "--listen", "127.0.0.1",
            "--port", "8188", "--lowvram", "--preview-method", "none"
        ) `
        -WorkingDirectory $comfyRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logsRoot "comfyui.stdout.log") `
        -RedirectStandardError (Join-Path $logsRoot "comfyui.stderr.log") `
        -PassThru

    Write-Host "Starting ComfyUI..."
    $deadline = (Get-Date).AddMinutes(3)
    while (-not (Test-ComfyUI)) {
        if ($comfyProcess.HasExited) {
            throw "ComfyUI exited during startup. See .runtime\logs\comfyui.stderr.log"
        }
        if ((Get-Date) -gt $deadline) {
            throw "ComfyUI did not become ready within 3 minutes."
        }
        Start-Sleep -Seconds 2
    }
}

$env:INFERENCE_BACKEND = "comfyui"
$env:COMFYUI_URL = "http://127.0.0.1:8188"
$env:COMFYUI_WORKFLOW = ".\workflows\sdxl_inpaint_api.json"
$env:COMFYUI_TIMEOUT_SECONDS = "600"

try {
    Set-Location -LiteralPath $projectRoot
    & $appPython -m body_repair_ai
} finally {
    if ($null -ne $comfyProcess -and -not $comfyProcess.HasExited) {
        Stop-Process -Id $comfyProcess.Id
    }
}
