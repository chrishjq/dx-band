# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""The public source version."""

from __future__ import annotations

import json
import re
import tomllib
from datetime import date
from pathlib import Path


def release_version_tuple(value: str) -> tuple[int, ...]:
    """Validate YYYY.M.D[.revision] and return its numeric ordering key."""
    pattern = r"20\d{2}\.(?:0?[1-9]|1[0-2])\.(?:0?[1-9]|[12]\d|3[01])(?:\.[1-9]\d*)?"
    if not re.fullmatch(pattern, value):
        raise ValueError("版本号必须使用 YYYY.M.D 或 YYYY.M.D.修订号 格式")
    parts = tuple(int(part) for part in value.split("."))
    try:
        date(*parts[:3])
    except ValueError as exc:
        raise ValueError("版本号中的日期无效") from exc
    if len(parts) == 4 and parts[3] < 1:
        raise ValueError("修订号必须大于零")
    return parts


def _read_build_info_version(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        version = str(payload["version"])
        release_version_tuple(version)
        return version
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _source_version() -> str:
    package_dir = Path(__file__).resolve().parent
    embedded = _read_build_info_version(package_dir / "_build_info.json")
    if embedded is not None:
        return embedded
    try:
        project = tomllib.loads(
            (package_dir.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )
        version = str(project["project"]["version"])
        release_version_tuple(version)
        return version
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise RuntimeError("无法读取源码项目版本号") from exc


__version__ = _source_version()
