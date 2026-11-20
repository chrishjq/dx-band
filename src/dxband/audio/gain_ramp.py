# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import numpy as np
from numpy.typing import NDArray


class GainRamp:
    def __init__(self, maximum_frames: int, initial_gain: float = 1.0) -> None:
        self.current_gain = initial_gain
        self.target_gain = initial_gain
        self.remaining_frames = 0
        self._step = 0.0
        self._indices = np.arange(maximum_frames, dtype=np.float32)

    def set_target(self, target_gain: float, ramp_frames: int) -> None:
        self.target_gain = float(target_gain)
        if ramp_frames <= 0:
            self.current_gain = self.target_gain
            self.remaining_frames = 0
            self._step = 0.0
            return
        self.remaining_frames = ramp_frames
        self._step = (self.target_gain - self.current_gain) / ramp_frames

    def render_into(self, output: NDArray[np.float32], frames: int) -> None:
        ramp_frames = min(frames, self.remaining_frames)
        if ramp_frames:
            np.multiply(self._indices[:ramp_frames], self._step, out=output[:ramp_frames])
            np.add(output[:ramp_frames], self.current_gain, out=output[:ramp_frames])
            self.current_gain += self._step * ramp_frames
            self.remaining_frames -= ramp_frames
            if self.remaining_frames == 0:
                self.current_gain = self.target_gain
        if ramp_frames < frames:
            output[ramp_frames:frames].fill(self.target_gain)
