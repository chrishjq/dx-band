# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the macOS DX Band.app (no model weights)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).resolve().parents[1]
SRC = ROOT / "src"
RESOURCES = SRC / "dxband" / "resources"
SCRIPTS = ROOT / "scripts"
BUILD_INFO = SRC / "dxband" / "_build_info.json"

if BUILD_INFO.is_file():
    VERSION = str(json.loads(BUILD_INFO.read_text(encoding="utf-8"))["version"])
else:
    VERSION = str(
        tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
            "version"
        ]
    )

datas: list[tuple[str, str]] = [
    (str(RESOURCES), "dxband/resources"),
    (str(SCRIPTS / "run_beat_this.py"), "scripts"),
    (str(SCRIPTS / "run_sheetsage2.py"), "scripts"),
]
if BUILD_INFO.is_file():
    datas.append((str(BUILD_INFO), "dxband"))

binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = [
    "dxband.creation.fun_asr_infer",
    "dxband.workers",
    "dxband.workers.separate_worker",
    "demucs",
    "demucs.separate",
    "beat_this",
    "funasr",
    "torchaudio",
    "librosa",
    "ctc_segmentation",
    "transformers",
    "qrcode",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
]

for package in (
    "PySide6",
    "torch",
    "torchaudio",
    "demucs",
    "beat_this",
    "funasr",
    "librosa",
    "transformers",
    "onnxruntime",
    "av",
    "sounddevice",
    "scipy",
    "numba",
    "llvmlite",
):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception:
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

try:
    datas += collect_data_files("ctc_segmentation")
except Exception:
    pass

block_cipher = None

a = Analysis(
    [str(ROOT / "packaging" / "macos" / "entry.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib.tests",
        "torch.testing",
        "torch.utils.tensorboard",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
        "mypy",
        "ruff",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DX Band",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(RESOURCES / "dx_band_icon.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DX Band",
)

app = BUNDLE(
    coll,
    name="DX Band.app",
    icon=str(RESOURCES / "dx_band_icon.icns"),
    bundle_identifier="site.dx-band.app",
    version=VERSION,
    info_plist={
        "CFBundleName": "DX Band",
        "CFBundleDisplayName": "大象乐队工作站",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.music",
    },
)
