# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path

from dxband.services.atomic_file_service import atomic_write_json


class PlaylistService:
    """在歌曲库中保存有序演出播放列表，允许同一歌曲重复出现。"""

    def __init__(self, library_root: Path) -> None:
        self.set_root(library_root)

    def set_root(self, library_root: Path) -> None:
        self.path = library_root.expanduser().resolve() / ".playlist.json"

    def load(self) -> tuple[str, ...]:
        if not self.path.exists():
            return ()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("播放列表文件版本不受支持")
        values = payload.get("song_ids")
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value for value in values
        ):
            raise ValueError("播放列表文件内容无效")
        return tuple(values)

    def add(self, song_ids: tuple[str, ...]) -> int:
        values = list(self.load())
        if any(not song_id for song_id in song_ids):
            raise ValueError("歌曲 ID 不能为空")
        values.extend(song_ids)
        if song_ids:
            self._save(values)
        return len(song_ids)

    def insert_before(self, song_id: str, index: int | None) -> int:
        """把歌曲插入指定条目之前；没有当前条目时追加到末尾。"""
        if not song_id:
            raise ValueError("歌曲 ID 不能为空")
        values = list(self.load())
        position = len(values) if index is None else index
        if not 0 <= position <= len(values):
            raise IndexError("播放列表位置无效")
        values.insert(position, song_id)
        self._save(values)
        return position

    def remove(self, index: int) -> None:
        values = list(self.load())
        if 0 <= index < len(values):
            values.pop(index)
            self._save(values)

    def move(self, index: int, direction: int) -> int:
        values = list(self.load())
        if not 0 <= index < len(values):
            return index
        target = index + direction
        if 0 <= target < len(values):
            values[index], values[target] = values[target], values[index]
            self._save(values)
            return target
        return index

    def next_entry(
        self, current_index: int | None, available_ids: set[str]
    ) -> tuple[int, str] | None:
        values = self.load()
        start = current_index + 1 if current_index is not None else 0
        return next(
            (
                (index, value)
                for index in range(start, len(values))
                if (value := values[index]) in available_ids
            ),
            None,
        )

    def previous_entry(
        self, current_index: int | None, available_ids: set[str]
    ) -> tuple[int, str] | None:
        """查找当前歌曲之前最近的可用歌曲，不循环到列表末尾。"""
        values = self.load()
        if current_index is None:
            return None
        return next(
            (
                (index, value)
                for index in range(current_index - 1, -1, -1)
                if (value := values[index]) in available_ids
            ),
            None,
        )

    def _save(self, values: list[str]) -> None:
        atomic_write_json(self.path, {"schema_version": 1, "song_ids": values})
