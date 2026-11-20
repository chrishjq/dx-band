# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import dataclass


@dataclass(slots=True)
class AudioMasterClock:
    sample_rate_hz: int
    submitted_frames: float = 0
    anchor_frames: float = 0
    anchor_dac_time: float | None = None
    playback_rate: float = 1.0

    def reset(self, position_frames: float) -> None:
        self.submitted_frames = position_frames
        self.anchor_frames = position_frames
        self.anchor_dac_time = None

    def set_playback_rate(self, value: float) -> None:
        self.playback_rate = value

    def update_submission(
        self,
        block_start_frames: float,
        block_end_frames: float,
        output_dac_time: float | None,
    ) -> None:
        self.anchor_frames = block_start_frames
        self.anchor_dac_time = output_dac_time
        self.submitted_frames = block_end_frames

    def audible_frames(self, stream_time: float | None) -> float:
        if self.anchor_dac_time is None or stream_time is None:
            return self.submitted_frames
        elapsed_seconds = max(0.0, stream_time - self.anchor_dac_time)
        estimated = self.anchor_frames + elapsed_seconds * self.sample_rate_hz * self.playback_rate
        return min(self.submitted_frames, max(self.anchor_frames, estimated))
