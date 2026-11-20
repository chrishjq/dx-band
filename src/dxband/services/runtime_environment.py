# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import os
import sys
from pathlib import Path


def configure_runtime_environment() -> None:
    """让 macOS 源码运行时能够找到常见的 Homebrew 命令。"""
    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates.extend((Path("/opt/homebrew/bin"), Path("/usr/local/bin")))

    existing = os.environ.get("PATH", "").split(os.pathsep)
    additions = [str(path) for path in candidates if path.is_dir() and str(path) not in existing]
    if additions:
        os.environ["PATH"] = os.pathsep.join((*additions, *existing))
