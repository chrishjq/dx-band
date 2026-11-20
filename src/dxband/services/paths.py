# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path, PurePosixPath


class UnsafeRelativePathError(ValueError):
    """歌曲包相对路径越过包根目录时抛出。"""


def resolve_package_path(package_root: Path, relative_path: str) -> Path:
    """解析 POSIX 包内路径，并拒绝绝对路径和目录穿越。"""
    pure_path = PurePosixPath(relative_path)
    if pure_path.is_absolute() or not pure_path.parts:
        raise UnsafeRelativePathError(f"path must be relative: {relative_path!r}")
    if any(part in {"", ".", ".."} for part in pure_path.parts) or "\\" in relative_path:
        raise UnsafeRelativePathError(f"unsafe path component: {relative_path!r}")

    resolved_root = package_root.resolve()
    candidate = (resolved_root / Path(*pure_path.parts)).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise UnsafeRelativePathError(f"path leaves package root: {relative_path!r}")
    return candidate
