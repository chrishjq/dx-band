# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import shutil
from dataclasses import dataclass
from pathlib import Path

from dxband.models.creation_job import CreateSongRequest
from dxband.services.media_probe import AudioMediaInfo, MediaProbe

SUPPORTED_SOURCE_AUDIO_EXTENSIONS = (".mp3", ".aac", ".wav")


class InputValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedCreationInput:
    request: CreateSongRequest
    media: AudioMediaInfo
    lrc_encoding: str | None


class CreationInputValidator:
    def __init__(
        self,
        media_probe: MediaProbe | None = None,
        max_duration_ms: int = 15 * 60 * 1000,
        max_file_size_bytes: int = 500 * 1024 * 1024,
    ) -> None:
        self.media_probe = media_probe or MediaProbe()
        self.max_duration_ms = max_duration_ms
        self.max_file_size_bytes = max_file_size_bytes

    def validate(
        self, request: CreateSongRequest, destination_root: Path
    ) -> ValidatedCreationInput:
        source = request.source_mp3.expanduser().resolve()
        if not source.is_file():
            raise InputValidationError(f"源歌曲不存在：{source}")
        if source.suffix.lower() not in SUPPORTED_SOURCE_AUDIO_EXTENSIONS:
            raise InputValidationError("源歌曲必须是 MP3、AAC 或 WAV 文件（.mp3/.aac/.wav）")
        if source.stat().st_size > self.max_file_size_bytes:
            raise InputValidationError("源歌曲文件超过允许的大小上限")

        media = self.media_probe.probe_audio(source)
        if media.duration_ms <= 3_000:
            raise InputValidationError("源歌曲时长必须大于 3 秒")
        if media.duration_ms > self.max_duration_ms:
            raise InputValidationError("源歌曲超过 15 分钟上限")

        lyrics_text = request.lyrics_text.strip() if request.lyrics_text else ""
        if request.lrc_path is None and not lyrics_text:
            raise InputValidationError("请提供 LRC 歌词文件或输入歌词文本")
        if request.lrc_path is not None and lyrics_text:
            raise InputValidationError("请选择 LRC 文件或输入歌词文本，不要同时提供")
        lrc_path = None
        lrc_encoding = None
        if request.lrc_path is not None:
            lrc_path = request.lrc_path.expanduser().resolve()
            if not lrc_path.is_file() or lrc_path.suffix.lower() != ".lrc":
                raise InputValidationError("LRC 文件不存在或扩展名不正确")
            lrc_encoding = self._detect_lrc_encoding(lrc_path)

        destination_root.mkdir(parents=True, exist_ok=True)
        required_bytes = max(source.stat().st_size * 8, 256 * 1024 * 1024)
        if shutil.disk_usage(destination_root).free < required_bytes:
            raise InputValidationError("歌曲库磁盘空间不足")

        normalized = request.model_copy(
            update={
                "source_mp3": source,
                "lrc_path": lrc_path,
                "lyrics_text": lyrics_text or None,
            }
        )
        return ValidatedCreationInput(normalized, media, lrc_encoding)

    @staticmethod
    def _detect_lrc_encoding(path: Path) -> str:
        data = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                data.decode(encoding)
            except UnicodeDecodeError:
                continue
            return encoding
        raise InputValidationError("LRC 编码无法识别，仅支持 UTF-8、UTF-8 BOM 和 GB18030")
