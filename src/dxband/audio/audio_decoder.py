# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

import av
import numpy as np
from numpy.typing import NDArray


class AudioDecodeError(RuntimeError):
    pass


class AudioDecoder:
    def __init__(self, sample_rate_hz: int = 44_100, channels: int = 2) -> None:
        self.sample_rate_hz = sample_rate_hz
        self.channels = channels

    def decode(self, path: Path) -> NDArray[np.float32]:
        chunks: list[NDArray[np.float32]] = []
        try:
            with av.open(str(path)) as container:
                if not container.streams.audio:
                    raise AudioDecodeError(f"没有音频流：{path.name}")
                stream = container.streams.audio[0]
                resampler = av.AudioResampler(
                    format="fltp",
                    layout="stereo",
                    rate=self.sample_rate_hz,
                )
                for frame in container.decode(stream):
                    for converted in resampler.resample(frame):
                        chunks.append(self._frame_array(converted))
                for converted in resampler.resample(None):
                    chunks.append(self._frame_array(converted))
        except (av.error.FFmpegError, OSError) as exc:
            raise AudioDecodeError(f"音频解码失败：{path.name}") from exc
        if not chunks:
            raise AudioDecodeError(f"音频没有可解码采样：{path.name}")
        pcm = np.ascontiguousarray(np.concatenate(chunks, axis=0), dtype=np.float32)
        if pcm.ndim != 2 or pcm.shape[1] != self.channels:
            raise AudioDecodeError(f"音频未能规范化为双声道：{path.name}")
        return pcm

    @staticmethod
    def _frame_array(frame: av.AudioFrame) -> NDArray[np.float32]:
        array = frame.to_ndarray()
        if array.ndim != 2:
            raise AudioDecodeError("解码器返回了无效 PCM 形状")
        return np.ascontiguousarray(array.T, dtype=np.float32)
