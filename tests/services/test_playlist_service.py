# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path

import pytest

from dxband.services.playlist_service import PlaylistService


def test_playlist_persists_repeated_songs_and_operates_on_entries(tmp_path: Path) -> None:
    service = PlaylistService(tmp_path)
    assert service.load() == ()
    assert service.add(("song-a", "song-b", "song-a")) == 3
    assert service.add(("song-b", "song-c")) == 2
    assert PlaylistService(tmp_path).load() == ("song-a", "song-b", "song-a", "song-b", "song-c")
    assert service.insert_before("song-a", 3) == 3
    assert service.load() == ("song-a", "song-b", "song-a", "song-a", "song-b", "song-c")
    assert service.move(3, 1) == 4
    service.remove(2)
    assert service.load() == ("song-a", "song-b", "song-b", "song-a", "song-c")


def test_next_song_skips_missing_and_does_not_loop(tmp_path: Path) -> None:
    service = PlaylistService(tmp_path)
    service.add(("song-a", "missing", "song-b"))
    available = {"song-a", "song-b"}
    assert service.next_entry(None, available) == (0, "song-a")
    assert service.next_entry(0, available) == (2, "song-b")
    assert service.next_entry(2, available) is None
    assert service.previous_entry(None, available) is None
    assert service.previous_entry(0, available) is None
    assert service.previous_entry(2, available) == (0, "song-a")


def test_repeated_song_navigation_uses_entry_position(tmp_path: Path) -> None:
    service = PlaylistService(tmp_path)
    service.add(("song-a", "song-b", "song-a"))
    available = {"song-a", "song-b"}
    assert service.next_entry(0, available) == (1, "song-b")
    assert service.next_entry(1, available) == (2, "song-a")
    assert service.previous_entry(2, available) == (1, "song-b")


def test_invalid_playlist_is_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / ".playlist.json"
    path.write_text(json.dumps({"schema_version": 1, "song_ids": ["a", ""]}))
    service = PlaylistService(tmp_path)
    with pytest.raises(ValueError, match="内容无效"):
        service.add(("b",))
    assert json.loads(path.read_text())["song_ids"] == ["a", ""]
