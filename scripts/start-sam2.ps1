$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".runtime\ComfyUI_windows_portable\python_embeded\python.exe"
$modelPath = Join-Path $projectRoot ".runtime\sam2\models\sam2.1-hiera-tiny"

if (-not (Test-Path -LiteralPath (Join-Path $modelPath "model.safetensors"))) {
    throw "SAM 2 is not installed. Run: .\scripts\setup-sam2.ps1"
}

$env:SAM2_MODEL_PATH = $modelPath
$env:SAM2_HOST = "127.0.0.1"
$env:SAM2_PORT = "8190"
$env:SAM2_KEEP_GPU = "0"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
Set-Location -LiteralPath $projectRoot
& $pythonPath ".\scripts\sam2_service.py"
