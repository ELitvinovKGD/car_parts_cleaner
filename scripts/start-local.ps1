$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot ".runtime\ComfyUI_windows_portable"
$comfyPython = Join-Path $runtimeRoot "python_embeded\python.exe"
$comfyRoot = Join-Path $runtimeRoot "ComfyUI"
$appPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logsRoot = Join-Path $projectRoot ".runtime\logs"
$samModel = Join-Path $projectRoot ".runtime\sam2\models\sam2.1-hiera-tiny\model.safetensors"
$comfyProcess = $null
$samProcess = $null

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

function Test-SAM2 {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:8190/health" -TimeoutSec 2 | Out-Null
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

if (-not (Test-SAM2)) {
    if (Test-Path -LiteralPath $samModel) {
        New-Item -ItemType Directory -Force -Path $logsRoot | Out-Null
        $env:SAM2_MODEL_PATH = Split-Path -Parent $samModel
        $env:SAM2_HOST = "127.0.0.1"
        $env:SAM2_PORT = "8190"
        $env:SAM2_KEEP_GPU = "0"
        $env:HF_HUB_DISABLE_TELEMETRY = "1"
        $samProcess = Start-Process `
            -FilePath $comfyPython `
            -ArgumentList @(".\scripts\sam2_service.py") `
            -WorkingDirectory $projectRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $logsRoot "sam2.stdout.log") `
            -RedirectStandardError (Join-Path $logsRoot "sam2.stderr.log") `
            -PassThru
        Write-Host "Starting SAM 2 microservice..."
        $samDeadline = (Get-Date).AddMinutes(2)
        while (-not (Test-SAM2)) {
            if ($samProcess.HasExited) {
                throw "SAM 2 exited during startup. See .runtime\logs\sam2.stderr.log"
            }
            if ((Get-Date) -gt $samDeadline) {
                throw "SAM 2 did not become ready within 2 minutes."
            }
            Start-Sleep -Seconds 2
        }
    } else {
        Write-Warning "SAM 2 model is not installed. Manual masks still work. Run .\scripts\setup-sam2.ps1"
    }
}

$env:INFERENCE_BACKEND = "comfyui"
$env:COMFYUI_URL = "http://127.0.0.1:8188"
$env:COMFYUI_WORKFLOW = ".\workflows\sdxl_inpaint_api.json"
$env:COMFYUI_TIMEOUT_SECONDS = "600"
$env:SAM2_URL = "http://127.0.0.1:8190"

try {
    Set-Location -LiteralPath $projectRoot
    & $appPython -m body_repair_ai
} finally {
    if ($null -ne $comfyProcess -and -not $comfyProcess.HasExited) {
        Stop-Process -Id $comfyProcess.Id
    }
    if ($null -ne $samProcess -and -not $samProcess.HasExited) {
        Stop-Process -Id $samProcess.Id
    }
}
