# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only
# Build a portable Windows x64 zip. Run from the repository root on Windows.
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
New-Item -ItemType Directory -Force -Path (Join-Path $Root "build") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root "dist") | Out-Null

Write-Host "Syncing AI + packaging dependencies..."
uv sync --extra ai --extra packaging

$Version = uv run --no-sync python -c "import tomllib; from pathlib import Path; print(tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])"
$BuildInfo = Join-Path $Root "src\dxband\_build_info.json"
Set-Content -Path $BuildInfo -Value ("{`"version`":`"$Version`",`"platform`":`"windows-x64`"}") -Encoding utf8

$DistDir = Join-Path $Root "dist"
$AppDirName = "DX Band"
$ZipName = "DX-Band-$Version-windows-x64.zip"
$ZipPath = Join-Path $DistDir $ZipName
$OutDir = Join-Path $Root "out"

Write-Host "Building DX Band $Version for Windows x64 (model weights excluded)..."
uv run --no-sync pyinstaller packaging/windows/dx_band.spec `
  --noconfirm `
  --clean `
  --distpath $DistDir `
  --workpath (Join-Path $Root "build\pyinstaller-windows")

$AppDir = Join-Path $DistDir $AppDirName
if (-not (Test-Path $AppDir)) {
  throw "Expected app folder missing: $AppDir"
}

if (Test-Path $ZipPath) {
  Remove-Item -Force $ZipPath
}
Compress-Archive -Path $AppDir -DestinationPath $ZipPath -CompressionLevel Optimal

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutZip = Join-Path $OutDir $ZipName
Copy-Item -Force $ZipPath $OutZip

Remove-Item -Force $BuildInfo -ErrorAction SilentlyContinue

Write-Host @"
Built:
  $AppDir
  $ZipPath
  $OutZip

Copy the zip from out\ back to the NAS out\ folder if you built on a local disk.
Model weights are not included. After unpacking, open Settings to download models.
FFmpeg: install yourself or use Settings when Windows download support is available.
"@
