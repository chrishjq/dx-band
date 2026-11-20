# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import dataclass
from pathlib import Path

import av

from dxband.constants import TRACK_FILENAMES, TrackKind
from dxband.services.hash_service import sha256_file


class StemValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StemInfo:
    kind: TrackKind
    path: Path
    sample_rate_hz: int
    channels: int
    decoded_frames: int
    duration_ms: int
    sha256: str
    trim_start_frames: int = 0
    pad_end_frames: int = 0


@dataclass(frozen=True, slots=True)
class StemValidationResult:
    sample_rate_hz: int
    channels: int
    canonical_frames: int
    duration_ms: int
    tracks: dict[TrackKind, StemInfo]


class StemValidator:
    def __init__(self, maximum_duration_difference_ms: int = 100) -> None:
        self.maximum_duration_difference_ms = maximum_duration_difference_ms

    def validate(
        self,
        track_directory: Path,
        track_kinds: set[TrackKind] | frozenset[TrackKind] | None = None,
    ) -> StemValidationResult:
        selected_tracks = set(TrackKind) if track_kinds is None else set(track_kinds)
        infos: dict[TrackKind, StemInfo] = {}
        for kind in TrackKind:
            if kind not in selected_tracks:
                continue
            filename = TRACK_FILENAMES[kind]
            path = track_directory / filename
            if not path.is_file():
                raise StemValidationError(f"缺少轨道文件：{filename}")
            if path.stat().st_size < 1024:
                raise StemValidationError(f"轨道文件过小：{filename}")
            infos[kind] = self._inspect(kind, path)

        sample_rates = {info.sample_rate_hz for info in infos.values()}
        if len(sample_rates) != 1:
            raise StemValidationError("音轨采样率不一致")
        sample_rate_hz = sample_rates.pop()
        if sample_rate_hz <= 0:
            raise StemValidationError("轨道采样率无效")
        if any(info.channels < 1 or info.channels > 8 for info in infos.values()):
            raise StemValidationError("存在无法规范化为双声道的轨道")

        canonical_frames = max(info.decoded_frames for info in infos.values())
        minimum_frames = min(info.decoded_frames for info in infos.values())
        difference_ms = round((canonical_frames - minimum_frames) * 1000 / sample_rate_hz)
        if difference_ms > self.maximum_duration_difference_ms:
            raise StemValidationError(f"音轨时长差异过大：{difference_ms}ms")

        aligned = {
            kind: StemInfo(
                kind=info.kind,
                path=info.path,
                sample_rate_hz=info.sample_rate_hz,
                channels=info.channels,
                decoded_frames=info.decoded_frames,
                duration_ms=info.duration_ms,
                sha256=info.sha256,
                trim_start_frames=0,
                pad_end_frames=canonical_frames - info.decoded_frames,
            )
            for kind, info in infos.items()
        }
        duration_ms = round(canonical_frames * 1000 / sample_rate_hz)
        return StemValidationResult(
            sample_rate_hz=sample_rate_hz,
            channels=2,
            canonical_frames=canonical_frames,
            duration_ms=duration_ms,
            tracks=aligned,
        )

    @staticmethod
    def _inspect(kind: TrackKind, path: Path) -> StemInfo:
        try:
            with av.open(str(path)) as container:
                if not container.streams.audio:
                    raise StemValidationError(f"轨道没有音频流：{path.name}")
                stream = container.streams.audio[0]
                sample_rate_hz = int(stream.codec_context.sample_rate or 0)
                channels = int(stream.codec_context.channels or 0)
                decoded_frames = sum(frame.samples for frame in container.decode(stream))
        except (av.error.FFmpegError, OSError) as exc:
            raise StemValidationError(f"轨道无法解码：{path.name}") from exc
        if decoded_frames <= 0 or sample_rate_hz <= 0:
            raise StemValidationError(f"轨道没有可用采样：{path.name}")
        return StemInfo(
            kind=kind,
            path=path,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
            decoded_frames=decoded_frames,
            duration_ms=round(decoded_frames * 1000 / sample_rate_hz),
            sha256=sha256_file(path),
        )
