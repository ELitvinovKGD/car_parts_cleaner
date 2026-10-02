$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot ".runtime"
$downloadsRoot = Join-Path $runtimeRoot "downloads"
$toolsRoot = Join-Path $runtimeRoot "tools"
$archivePath = Join-Path $downloadsRoot "ComfyUI_windows_portable_nvidia_cu126.7z"
$sevenZipPath = Join-Path $toolsRoot "7zr.exe"
$portableRoot = Join-Path $runtimeRoot "ComfyUI_windows_portable"
$checkpointRoot = Join-Path $portableRoot "ComfyUI\models\checkpoints"
$modelPath = Join-Path $checkpointRoot "sd_xl_base_1.0.safetensors"
$comfyUrl = "https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia_cu126.7z"
$sevenZipUrl = "https://github.com/ip7z/7zip/releases/download/26.03/7zr.exe"
$modelUrl = "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors"
$modelSha256 = "31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b"

New-Item -ItemType Directory -Force -Path $downloadsRoot, $toolsRoot | Out-Null
if (-not (Test-Path -LiteralPath $portableRoot)) {
    if (-not (Test-Path -LiteralPath $sevenZipPath)) {
        & curl.exe -L --fail --retry 3 --output $sevenZipPath $sevenZipUrl
        if ($LASTEXITCODE -ne 0) { throw "7zr download failed." }
    }
    if (-not (Test-Path -LiteralPath $archivePath)) {
        & curl.exe -L --fail --retry 3 --continue-at - --output $archivePath $comfyUrl
        if ($LASTEXITCODE -ne 0) { throw "ComfyUI download failed." }
    }
    & $sevenZipPath t $archivePath
    if ($LASTEXITCODE -ne 0) { throw "ComfyUI archive integrity check failed." }
    & $sevenZipPath x -y "-o$runtimeRoot" $archivePath
    if ($LASTEXITCODE -ne 0) { throw "ComfyUI extraction failed." }
}

New-Item -ItemType Directory -Force -Path $checkpointRoot | Out-Null
if (-not (Test-Path -LiteralPath $modelPath)) {
    & curl.exe -L --fail --retry 3 --continue-at - --output $modelPath $modelUrl
    if ($LASTEXITCODE -ne 0) { throw "SDXL checkpoint download failed." }
}
$actualModelHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $modelPath).Hash.ToLowerInvariant()
if ($actualModelHash -ne $modelSha256) {
    throw "SDXL checkpoint checksum mismatch. Delete the model file and run setup again."
}

Write-Host "ComfyUI and SDXL are ready in $portableRoot"
