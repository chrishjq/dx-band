# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dxband.constants import TRACK_FILENAMES
from dxband.services.hash_service import sha256_file


@pytest.fixture
def package_factory(tmp_path: Path) -> Callable[[], Path]:
    def make_package() -> Path:
        song_id = "20260930-193000-a1b2c3d4"
        package_root = tmp_path / song_id
        package_root.mkdir()
        track_data = {
            filename: f"synthetic-{filename}".encode() for filename in TRACK_FILENAMES.values()
        }
        for filename, data in track_data.items():
            (package_root / filename).write_bytes(data)

        lyrics: dict[str, Any] = {
            "schema_version": 1,
            "title": "测试歌曲",
            "language": "zh-CN",
            "timing_mode": "line",
            "lines": [
                {
                    "id": "line-0001",
                    "start_ms": 1000,
                    "end_ms": 5000,
                    "text": "第一句歌词",
                    "words": [],
                },
                {
                    "id": "line-0002",
                    "start_ms": 6000,
                    "end_ms": 9000,
                    "text": "第二句歌词",
                    "words": [],
                },
            ],
        }
        (package_root / "lyrics.json").write_text(
            json.dumps(lyrics, ensure_ascii=False), encoding="utf-8"
        )

        tracks = {
            kind.value: {
                "file": filename,
                "sha256": sha256_file(package_root / filename),
                "duration_ms": 10000,
                "trim_start_frames": 0,
                "pad_end_frames": 0,
            }
            for kind, filename in TRACK_FILENAMES.items()
        }
        song: dict[str, Any] = {
            "schema_version": 3,
            "song_id": song_id,
            "title": "测试歌曲",
            "artist": "测试歌手",
            "language": "zh-CN",
            "created_at": "2026-09-30T19:30:00+08:00",
            "duration_ms": 10000,
            "source": {
                "original_filename": "source.mp3",
                "sha256": "a" * 64,
                "original_copied": False,
                "lrc_filename": "source.lrc",
                "lrc_sha256": "b" * 64,
            },
            "separation": {
                "engine": "demucs",
                "model": "htdemucs_6s",
                "demucs_version": "4.1.0",
                "device": "mps",
                "output_format": "mp3",
                "bitrate_kbps": 320,
                "mp3_preset": 2,
            },
            "audio": {
                "sample_rate_hz": 44100,
                "channels": 2,
                "canonical_frames": 441000,
                "tracks": tracks,
            },
            "musical": {
                "original_key": "C",
                "bpm": 120,
                "beat_times_ms": [0, 500, 1000, 1500],
                "downbeat_times_ms": [0],
                "beats_per_bar": 4,
            },
            "lyrics": {
                "file": "lyrics.json",
                "source": "lrc",
                "verified": True,
                "verified_at": "2026-09-30T19:50:00+08:00",
                "language": "zh-CN",
            },
        }
        (package_root / "song.json").write_text(
            json.dumps(song, ensure_ascii=False), encoding="utf-8"
        )
        return package_root

    return make_package
