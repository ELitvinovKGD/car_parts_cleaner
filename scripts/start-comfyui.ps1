$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot ".runtime\ComfyUI_windows_portable"
$pythonPath = Join-Path $runtimeRoot "python_embeded\python.exe"
$comfyRoot = Join-Path $runtimeRoot "ComfyUI"
$modelPath = Join-Path $comfyRoot "models\checkpoints\sd_xl_base_1.0.safetensors"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "ComfyUI is not installed. Run: .\scripts\setup-comfyui.ps1"
}
if (-not (Test-Path -LiteralPath $modelPath)) {
    throw "SDXL checkpoint is missing. Run: .\scripts\setup-comfyui.ps1"
}

Set-Location -LiteralPath $comfyRoot
& $pythonPath main.py --windows-standalone-build --listen 127.0.0.1 --port 8188 --lowvram --preview-method none
