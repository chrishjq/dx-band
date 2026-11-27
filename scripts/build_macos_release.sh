#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p "$ROOT/build" "$ROOT/dist"

echo "Syncing AI + packaging dependencies…"
uv sync --extra ai --extra packaging

VERSION="$(
  uv run --no-sync python - <<'PY'
import tomllib
from pathlib import Path
print(tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])
PY
)"

BUILD_INFO="src/dxband/_build_info.json"
printf '{"version":"%s","platform":"macos-arm64"}\n' "$VERSION" >"$BUILD_INFO"
trap 'rm -f "$BUILD_INFO"' EXIT

DIST_DIR="$ROOT/dist"
APP_NAME="DX Band.app"
DMG_NAME="DX-Band-${VERSION}-macos-arm64.dmg"

echo "Building DX Band ${VERSION} for macOS arm64 (model weights excluded)…"
uv run --no-sync pyinstaller packaging/macos/dx_band.spec \
  --noconfirm \
  --clean \
  --distpath "$DIST_DIR" \
  --workpath "$ROOT/build/pyinstaller"

if [[ ! -d "$DIST_DIR/$APP_NAME" ]]; then
  echo "error: expected $DIST_DIR/$APP_NAME" >&2
  exit 1
fi

rm -f "$DIST_DIR/$DMG_NAME"

STAGE="$ROOT/build/dmg-stage"
rm -rf "$STAGE"
mkdir -p "$STAGE"
ditto "$DIST_DIR/$APP_NAME" "$STAGE/$APP_NAME"
ln -s /Applications "$STAGE/Applications"
hdiutil create \
  -volname "DX Band" \
  -srcfolder "$STAGE" \
  -ov \
  -format UDZO \
  "$DIST_DIR/$DMG_NAME"
rm -rf "$STAGE"

cat <<EOF
Built:
  $DIST_DIR/$APP_NAME
  $DIST_DIR/$DMG_NAME

Upload only the .dmg to GitHub Releases. Model weights are not included;
after install, open Settings to download models and FFmpeg if needed.
EOF
