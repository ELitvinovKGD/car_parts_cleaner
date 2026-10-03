$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".runtime\ComfyUI_windows_portable\python_embeded\python.exe"
$modelPath = Join-Path $projectRoot ".runtime\sam2\models\sam2.1-hiera-tiny"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "ComfyUI portable runtime is missing. Run: .\scripts\setup-comfyui.ps1"
}

New-Item -ItemType Directory -Force -Path $modelPath | Out-Null
$downloadCode = @'
import os
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="facebook/sam2.1-hiera-tiny",
    local_dir=os.environ["BODY_REPAIR_SAM2_MODEL"],
    allow_patterns=["*.json", "*.safetensors", "*.yaml"],
)
'@
$env:BODY_REPAIR_SAM2_MODEL = $modelPath
$env:HF_HUB_DISABLE_TELEMETRY = "1"
& $pythonPath -c $downloadCode
if ($LASTEXITCODE -ne 0) {
    throw "SAM 2 model download failed."
}

Write-Host "SAM 2.1 tiny is ready at $modelPath"
