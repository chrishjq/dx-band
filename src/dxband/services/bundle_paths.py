# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Locate helper scripts in a source checkout or a frozen application bundle."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def meipass_root() -> Path:
    root = getattr(sys, "_MEIPASS", None)
    if root is None:
        raise RuntimeError("当前进程不是冻结应用")
    return Path(root)


def repository_root() -> Path:
    """Return the source repository root. Invalid inside a frozen app."""
    if is_frozen():
        raise RuntimeError("冻结应用没有源码仓库根目录")
    return Path(__file__).resolve().parents[3]


def helper_script(name: str) -> Path:
    """Return ``scripts/<name>`` from the source tree or the frozen bundle."""
    if is_frozen():
        return meipass_root() / "scripts" / name
    return repository_root() / "scripts" / name
