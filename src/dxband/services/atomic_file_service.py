# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def fsync_directory(path: Path) -> None:
    """Sync a directory entry where the platform supports opening directories."""
    if os.name == "nt":
        return
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def atomic_write_json(path: Path, value: BaseModel | dict[str, Any]) -> None:
    """持久写入 UTF-8 JSON，并原子替换目标文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: Any = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        fsync_directory(path.parent)
    except BaseException:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
