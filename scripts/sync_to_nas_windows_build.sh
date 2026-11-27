#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only
# Sync this repository to the NAS Windows build folder.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAS_ROOT="${1:-/Volumes/ssd-2/song}"

if [[ ! -d "$NAS_ROOT" ]]; then
  echo "error: NAS path not found: $NAS_ROOT" >&2
  exit 1
fi

mkdir -p "$NAS_ROOT/out"

# SMB shares often reject rsync's temp-rename; write in place instead.
rsync -a --inplace \
  --exclude '.venv/' \
  --exclude 'dist/' \
  --exclude 'build/' \
  --exclude '.git/' \
  --exclude '.mypy_cache/' \
  --exclude '.pytest_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '__pycache__/' \
  --exclude 'promo-output/' \
  --exclude '.DS_Store' \
  --exclude '*.dmg' \
  --exclude '*.zip' \
  --exclude 'out/' \
  "$ROOT/" "$NAS_ROOT/"

# Keep the output drop folder.
mkdir -p "$NAS_ROOT/out"
# Do not delete existing Windows build products in out/.

cat <<EOF
Synced source to: $NAS_ROOT
Put finished Windows zip into: $NAS_ROOT/out/

On Windows:
  1. Prefer copying this folder to a local disk (D:\\dx-band-build) for speed.
  2. Install Python 3.12 + uv: https://docs.astral.sh/uv/getting-started/installation/
  3. In PowerShell:  .\\scripts\\build_windows_release.ps1
  4. Copy out\\DX-Band-*-windows-x64.zip back to the NAS out\\ folder.
EOF
