# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
from pathlib import Path

from dxband.services.ffmpeg_tools import ensure_ffmpeg_on_path


def configure_runtime_environment() -> None:
    """让本机与托管的 FFmpeg，以及 macOS Homebrew 命令可被查找到。"""
    ensure_ffmpeg_on_path()
    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates.extend((Path("/opt/homebrew/bin"), Path("/usr/local/bin")))

    existing = os.environ.get("PATH", "").split(os.pathsep)
    additions = [str(path) for path in candidates if path.is_dir() and str(path) not in existing]
    if additions:
        os.environ["PATH"] = os.pathsep.join((*additions, *existing))
