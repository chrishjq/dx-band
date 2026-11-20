# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from dxband.audio.audio_decoder import AudioDecoder
from dxband.constants import LEGACY_TRACK_KINDS, SIX_STEM_TRACK_KINDS, TrackKind
from dxband.creation.cancellation import CancellationToken


@dataclass(frozen=True, slots=True)
class PcmSongData:
    sample_rate_hz: int
    channels: int
    canonical_frames: int
    tracks: dict[TrackKind, NDArray[np.float32]]

    @property
    def duration_ms(self) -> int:
        return round(self.canonical_frames * 1000 / self.sample_rate_hz)


class PcmCacheService:
    def __init__(self, decoder: AudioDecoder | None = None) -> None:
        self.decoder = decoder or AudioDecoder()

    def load(
        self,
        paths: Mapping[TrackKind, Path],
        cancellation: CancellationToken | None = None,
        on_progress: Callable[[TrackKind, int, int], None] | None = None,
    ) -> PcmSongData:
        selected_tracks = set(paths)
        if selected_tracks not in (LEGACY_TRACK_KINDS, SIX_STEM_TRACK_KINDS):
            raise ValueError("PCM 缓存必须加载完整的旧四轨或新六轨")
        decoded: dict[TrackKind, NDArray[np.float32]] = {}
        ordered_tracks = [track for track in TrackKind if track in selected_tracks]
        for index, track in enumerate(ordered_tracks, start=1):
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            decoded[track] = self.decoder.decode(paths[track])
            if on_progress is not None:
                on_progress(track, index, len(ordered_tracks))

        canonical_frames = max(len(pcm) for pcm in decoded.values())
        aligned: dict[TrackKind, NDArray[np.float32]] = {}
        for track, pcm in decoded.items():
            if len(pcm) < canonical_frames:
                padding = np.zeros((canonical_frames - len(pcm), 2), dtype=np.float32)
                pcm = np.concatenate((pcm, padding), axis=0)
            elif len(pcm) > canonical_frames:
                pcm = pcm[:canonical_frames]
            pcm = np.ascontiguousarray(pcm, dtype=np.float32)
            pcm.setflags(write=False)
            aligned[track] = pcm
        return PcmSongData(
            sample_rate_hz=self.decoder.sample_rate_hz,
            channels=self.decoder.channels,
            canonical_frames=canonical_frames,
            tracks=aligned,
        )
