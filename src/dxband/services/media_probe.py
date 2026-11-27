# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dxband.services.ffmpeg_tools import resolve_ffprobe
from dxband.workers.command import subprocess_creation_flags


class MediaProbeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AudioMediaInfo:
    path: Path
    codec: str
    duration_ms: int
    sample_rate_hz: int
    channels: int
    bit_rate: int | None
    size_bytes: int


class MediaProbe:
    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable

    def probe_audio(self, path: Path) -> AudioMediaInfo:
        executable: str | None = self.executable
        if executable is None:
            resolved = resolve_ffprobe()
            executable = str(resolved) if resolved is not None else None
        if executable is None:
            raise MediaProbeError("未找到 FFmpeg。请到设置页下载到本机后重试。")
        command = [
            executable,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "format=duration,size,bit_rate:stream=codec_name,sample_rate,channels,bit_rate",
            "-of",
            "json",
            str(path),
        ]
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            creationflags=subprocess_creation_flags(),
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "ffprobe 无法读取文件"
            raise MediaProbeError(detail)
        try:
            payload: dict[str, Any] = json.loads(completed.stdout)
            streams = payload["streams"]
            if not streams:
                raise KeyError("streams")
            stream = streams[0]
            media_format = payload["format"]
            duration_ms = round(float(media_format["duration"]) * 1000)
            size_bytes = int(media_format.get("size", path.stat().st_size))
            bit_rate_raw = stream.get("bit_rate") or media_format.get("bit_rate")
            return AudioMediaInfo(
                path=path,
                codec=str(stream["codec_name"]),
                duration_ms=duration_ms,
                sample_rate_hz=int(stream["sample_rate"]),
                channels=int(stream["channels"]),
                bit_rate=int(bit_rate_raw) if bit_rate_raw else None,
                size_bytes=size_bytes,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MediaProbeError("ffprobe 返回了无法识别的音频信息") from exc
