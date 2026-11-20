# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

import pytest

from dxband.creation.input_validator import (
    CreationInputValidator,
    InputValidationError,
)
from dxband.creation.workspace import CreationWorkspace
from dxband.models.creation_job import CreateSongRequest
from dxband.services.media_probe import AudioMediaInfo


class _AudioProbe:
    @staticmethod
    def probe_audio(path: Path) -> AudioMediaInfo:
        return AudioMediaInfo(
            path=path,
            codec={".aac": "aac", ".wav": "pcm_s16le"}.get(path.suffix.lower(), "mp3"),
            duration_ms=10_000,
            sample_rate_hz=44_100,
            channels=2,
            bit_rate=256_000,
            size_bytes=path.stat().st_size,
        )


def _request(source: Path) -> CreateSongRequest:
    lrc = source.parent / "source.lrc"
    lrc.write_text("[00:01.00]测试歌词\n", encoding="utf-8")
    return CreateSongRequest(source_mp3=source, lrc_path=lrc, title="测试歌曲")


def test_creation_input_requires_lrc(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"audio")
    validator = CreationInputValidator(media_probe=_AudioProbe())  # type: ignore[arg-type]

    with pytest.raises(InputValidationError, match="LRC"):
        validator.validate(
            CreateSongRequest(source_mp3=source, title="测试歌曲"), tmp_path / "library"
        )


@pytest.mark.parametrize("extension", [".mp3", ".aac", ".AAC", ".wav", ".WAV"])
def test_creation_input_accepts_supported_audio_extensions(
    tmp_path: Path,
    extension: str,
) -> None:
    source = tmp_path / f"source{extension}"
    source.write_bytes(b"audio")
    validator = CreationInputValidator(media_probe=_AudioProbe())  # type: ignore[arg-type]

    validated = validator.validate(_request(source), tmp_path / "library")

    assert validated.request.source_mp3 == source.resolve()


def test_creation_input_rejects_unsupported_audio_extension(tmp_path: Path) -> None:
    source = tmp_path / "source.flac"
    source.write_bytes(b"audio")
    validator = CreationInputValidator(media_probe=_AudioProbe())  # type: ignore[arg-type]

    with pytest.raises(InputValidationError, match="MP3、AAC 或 WAV"):
        validator.validate(_request(source), tmp_path / "library")


def test_creation_input_accepts_text_lyrics_without_lrc(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    request = CreateSongRequest(
        source_mp3=source, lyrics_text="  第一句\n第二句  ", title="测试歌曲"
    )
    validator = CreationInputValidator(media_probe=_AudioProbe())  # type: ignore[arg-type]

    validated = validator.validate(request, tmp_path / "library")

    assert validated.request.lyrics_text == "第一句\n第二句"
    assert validated.request.lrc_path is None


def test_creation_input_rejects_ambiguous_lyrics(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"audio")
    request = _request(source).model_copy(update={"lyrics_text": "另一份歌词"})
    validator = CreationInputValidator(media_probe=_AudioProbe())  # type: ignore[arg-type]

    with pytest.raises(InputValidationError, match="不要同时提供"):
        validator.validate(request, tmp_path / "library")


def test_creation_workspace_preserves_aac_source_extension(tmp_path: Path) -> None:
    source = tmp_path / "original.aac"
    source.write_bytes(b"audio")

    job = CreationWorkspace(tmp_path / "library").create(_request(source))

    assert job.request.source_mp3.name == "source.aac"
    assert job.request.source_mp3.read_bytes() == b"audio"
    assert job.original_source_filename == "original.aac"


def test_creation_workspace_preserves_wav_and_text_lyrics(tmp_path: Path) -> None:
    source = tmp_path / "original.wav"
    source.write_bytes(b"audio")
    request = CreateSongRequest(source_mp3=source, lyrics_text="第一句\n第二句", title="测试歌曲")

    job = CreationWorkspace(tmp_path / "library").create(request)

    assert job.request.source_mp3.name == "source.wav"
    assert job.original_source_filename == "original.wav"
    assert job.request.lyrics_text == request.lyrics_text
    assert job.original_lrc_filename is None
