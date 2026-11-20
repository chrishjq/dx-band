# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import logging
import math
import queue
import threading
from enum import StrEnum
from typing import Any

import numpy as np
import sounddevice as sd
from numpy.typing import NDArray
from PySide6.QtCore import QObject, Qt, QTimer, Signal

from dxband.audio.audio_clock import AudioMasterClock
from dxband.audio.gain_ramp import GainRamp
from dxband.audio.pcm_cache import PcmSongData
from dxband.constants import TrackKind

LOGGER = logging.getLogger(__name__)


class PlaybackState(StrEnum):
    EMPTY = "empty"
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    ENDED = "ended"
    ERROR = "error"


class StemMixerEngine(QObject):
    position_changed = Signal(int)
    guide_countdown_changed = Signal(int, int)
    duration_changed = Signal(int)
    state_changed = Signal(object)
    track_mute_changed = Signal(str, bool)
    error_raised = Signal(str)

    def __init__(
        self,
        output_device: int | str | None = None,
        block_size_frames: int = 2048,
        parent: QObject | None = None,
        *,
        output_latency_seconds: float = 0.15,
    ) -> None:
        super().__init__(parent)
        self.output_device = output_device
        self._output_device_name: str | None = None
        self._output_device_hostapi: int | None = None
        self.block_size_frames = block_size_frames
        self.output_latency_seconds = output_latency_seconds
        self._lock = threading.RLock()
        # 音频时钟单独加锁，避免界面读取声卡时间时阻塞实时混音回调。
        self._clock_lock = threading.Lock()
        self._errors: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._retired_streams: queue.SimpleQueue[sd.OutputStream] = queue.SimpleQueue()
        self._pcm: PcmSongData | None = None
        self._stream: sd.OutputStream | None = None
        self._stream_generation = 0
        self._state = PlaybackState.EMPTY
        self._position_frames = 0.0
        self._playback_rate = 1.0
        self._master_gain = 0.85
        self._mute_fade_ms = 12
        self._muted = {track: False for track in TrackKind}
        self._base_gains = {track: 1.0 for track in TrackKind}
        self._ramps = {track: GainRamp(block_size_frames, initial_gain=1.0) for track in TrackKind}
        self._mix_buffer = np.zeros((block_size_frames, 2), dtype=np.float32)
        self._track_buffer = np.zeros((block_size_frames, 2), dtype=np.float32)
        self._mono_buffer = np.zeros(block_size_frames, dtype=np.float32)
        self._gain_buffer = {
            track: np.ones(block_size_frames, dtype=np.float32) for track in TrackKind
        }
        self._guide_enabled = False
        self._count_in_beat_frames = np.empty(0, dtype=np.int64)
        self._count_in_downbeat_frames = np.empty(0, dtype=np.int64)
        self._beat_click = np.empty(0, dtype=np.float32)
        self._downbeat_click = np.empty(0, dtype=np.float32)
        self._count_in_start_frame = 0
        self._count_in_target_frame = 0
        self._count_in_active = False
        self._count_in_session = False
        self._clock = AudioMasterClock(sample_rate_hz=44_100)
        self._underflow_count = 0
        self._last_logged_underflow_count = 0
        self._last_emitted_state = self._state
        self._last_emitted_position_ms = -1
        self._last_emitted_guide_countdown = (0, 0)
        self._publish_timer = QTimer(self)
        # 以接近显示器刷新率发布可听位置，预备拍与歌曲使用同一音频时钟。
        self._publish_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._publish_timer.setInterval(16)
        self._publish_timer.timeout.connect(self._publish_state)
        self._publish_timer.start()

    def load_pcm(
        self,
        pcm: PcmSongData,
        default_muted: dict[TrackKind, bool] | None = None,
        gain_db: dict[TrackKind, float] | None = None,
        mute_fade_ms: int = 12,
        master_volume: float = 0.85,
    ) -> None:
        self.close_stream()
        with self._lock:
            self._pcm = pcm
            self._position_frames = 0.0
            self._state = PlaybackState.STOPPED
            self._count_in_start_frame = 0
            self._count_in_target_frame = 0
            self._count_in_active = False
            self._count_in_session = False
            self._count_in_beat_frames = np.empty(0, dtype=np.int64)
            self._count_in_downbeat_frames = np.empty(0, dtype=np.int64)
            self._mute_fade_ms = max(5, min(20, mute_fade_ms))
            self._master_gain = max(0.0, min(1.0, master_volume))
            with self._clock_lock:
                self._clock = AudioMasterClock(sample_rate_hz=pcm.sample_rate_hz)
                self._clock.set_playback_rate(self._playback_rate)
                self._clock.reset(0)
            self._underflow_count = 0
            self._last_logged_underflow_count = 0
            for track in TrackKind:
                muted = (default_muted or {}).get(track, False)
                gain = math.pow(10.0, (gain_db or {}).get(track, 0.0) / 20.0)
                self._muted[track] = muted
                self._base_gains[track] = gain
                initial = 0.0 if muted else gain
                self._ramps[track] = GainRamp(self.block_size_frames, initial_gain=initial)
        self.duration_changed.emit(pcm.duration_ms)
        self.state_changed.emit(self._state)

    def play(self) -> None:
        stale_stream: sd.OutputStream | None = None
        with self._lock:
            # PortAudio streams cannot be reused after CoreAudio removes their
            # device.  In particular, restarting a stale AUHAL stream keeps
            # returning kAudioUnitErr_InvalidPropertyValue even after a
            # Bluetooth output reconnects.
            if self._state == PlaybackState.ERROR:
                stale_stream = self._stream
                self._stream = None
        if stale_stream is not None:
            self._dispose_stream(stale_stream)
        self._dispose_retired_streams()

        stream_to_start: sd.OutputStream | None = None
        failed_stream: sd.OutputStream | None = None
        startup_failed = False
        with self._lock:
            if self._pcm is None:
                self._errors.put("尚未加载歌曲")
                return
            if self._state == PlaybackState.ENDED or (
                self._state == PlaybackState.STOPPED and self._position_frames == 0
            ):
                self._position_frames = self._count_in_start_frame
                self._count_in_active = self._guide_enabled and bool(
                    self._count_in_beat_frames.size
                )
                self._count_in_session = self._count_in_active
                with self._clock_lock:
                    self._clock.reset(self._position_frames)
            try:
                self._ensure_stream()
                self._state = PlaybackState.PLAYING
                if self._stream is not None and not self._stream.active:
                    stream_to_start = self._stream
            except Exception as exc:
                startup_failed = True
                failed_stream = self._stream
                self._stream = None
                self._state = PlaybackState.ERROR
                self._errors.put(f"音频输出设备不可用：{exc}")
        if startup_failed:
            if failed_stream is not None:
                self._dispose_stream(failed_stream)
            return

        if stream_to_start is not None:
            try:
                # PortAudio may wait for its first callback in start(); that
                # callback needs _lock, so start outside the mixer lock.
                stream_to_start.start()
            except Exception as exc:
                dispose_failed_stream = False
                with self._lock:
                    if self._stream is stream_to_start:
                        self._stream = None
                        self._state = PlaybackState.ERROR
                        self._errors.put(f"音频输出设备不可用：{exc}")
                        dispose_failed_stream = True
                if dispose_failed_stream:
                    self._dispose_stream(stream_to_start)

    def pause(self) -> None:
        with self._lock:
            if self._state != PlaybackState.PLAYING:
                return
            self._position_frames = self._audible_frames_locked()
            self._count_in_active = (
                self._count_in_session and self._position_frames < self._count_in_target_frame
            )
            with self._clock_lock:
                self._clock.reset(self._position_frames)
            self._state = PlaybackState.PAUSED

    def stop(self) -> None:
        with self._lock:
            if self._pcm is None:
                return
            self._position_frames = 0
            with self._clock_lock:
                self._clock.reset(0)
            self._state = PlaybackState.STOPPED
            self._count_in_active = False
            self._count_in_session = False

    def seek_ms(self, position_ms: int) -> None:
        with self._lock:
            if self._pcm is None:
                return
            target_frames = round(position_ms * self._pcm.sample_rate_hz / 1000)
            self._position_frames = max(0, min(self._pcm.canonical_frames, target_frames))
            self._count_in_active = False
            self._count_in_session = False
            with self._clock_lock:
                self._clock.reset(self._position_frames)
            if self._position_frames >= self._pcm.canonical_frames:
                self._state = PlaybackState.ENDED
            elif self._state == PlaybackState.ENDED:
                self._state = PlaybackState.PAUSED

    def set_master_volume(self, value: float) -> None:
        with self._lock:
            self._master_gain = max(0.0, min(1.0, value))

    def set_playback_rate(self, value: float) -> None:
        if not math.isfinite(value) or not 0.2 <= value <= 2.0:
            raise ValueError(f"不支持的播放速度：{value:g}x")
        with self._lock:
            if self._playback_rate == value:
                return
            if self._state == PlaybackState.PLAYING:
                self._position_frames = self._audible_frames_locked()
            self._playback_rate = value
            with self._clock_lock:
                self._clock.set_playback_rate(value)
                self._clock.reset(self._position_frames)

    def playback_rate(self) -> float:
        with self._lock:
            return self._playback_rate

    def set_track_gain_db(self, track: TrackKind, value_db: float) -> None:
        with self._lock:
            gain = math.pow(10.0, max(-96.0, min(24.0, value_db)) / 20.0)
            self._base_gains[track] = gain
            target = 0.0 if self._muted[track] else gain
            self._ramps[track].set_target(target, self._fade_frames_locked())

    def set_track_muted(self, track: TrackKind, muted: bool) -> None:
        with self._lock:
            if self._muted[track] == muted:
                return
            self._muted[track] = muted
            target = 0.0 if muted else self._base_gains[track]
            self._ramps[track].set_target(target, self._fade_frames_locked())
        self.track_mute_changed.emit(track.value, muted)

    def set_guide_beats(
        self,
        enabled: bool,
        *,
        bpm: int | None = None,
        beats_per_bar: int | None = None,
        count_in_bars: int = 2,
        first_beat_ms: int | None = None,
    ) -> None:
        """Place two bars of guide clicks immediately before the song's first beat."""
        with self._lock:
            self._guide_enabled = enabled
            self._count_in_start_frame = 0
            self._count_in_target_frame = 0
            if not enabled:
                self._count_in_active = False
                self._count_in_session = False
                if self._position_frames < 0:
                    self._position_frames = 0
                    with self._clock_lock:
                        self._clock.reset(0)
            if (
                self._pcm is None
                or not enabled
                or not bpm
                or not beats_per_bar
                or count_in_bars <= 0
            ):
                self._count_in_session = False
                self._count_in_beat_frames = np.empty(0, dtype=np.int64)
                self._count_in_downbeat_frames = np.empty(0, dtype=np.int64)
                self._beat_click = np.empty(0, dtype=np.float32)
                self._downbeat_click = np.empty(0, dtype=np.float32)
                return
            sample_rate_hz = self._pcm.sample_rate_hz
            count = beats_per_bar * count_in_bars
            beat_period_frames = sample_rate_hz * 60 / bpm
            first_beat_frame = max(0, round((first_beat_ms or 0) * sample_rate_hz / 1000))
            if first_beat_frame >= self._pcm.canonical_frames:
                first_beat_frame = 0
            self._count_in_target_frame = first_beat_frame
            self._count_in_beat_frames = np.asarray(
                tuple(
                    first_beat_frame - round((count - index) * beat_period_frames)
                    for index in range(count)
                ),
                dtype=np.int64,
            )
            self._count_in_start_frame = min(0, int(self._count_in_beat_frames[0]))
            self._count_in_downbeat_frames = self._count_in_beat_frames[::beats_per_bar]
            self._beat_click = self._create_beat_click(sample_rate_hz)
            self._downbeat_click = np.clip(self._beat_click * 1.35, -1.0, 1.0)

    def is_track_muted(self, track: TrackKind) -> bool:
        with self._lock:
            return self._muted[track]

    def available_tracks(self) -> frozenset[TrackKind]:
        with self._lock:
            if self._pcm is None:
                return frozenset()
            return frozenset(self._pcm.tracks)

    def position_ms(self) -> int:
        """读取可听位置，读取声卡时钟时不占用实时混音锁。"""
        with self._lock:
            if self._pcm is None:
                return 0
            sample_rate_hz = self._pcm.sample_rate_hz
            state = self._state
            submitted_frames = self._position_frames
            stream = self._stream
            clock = self._clock
        if state == PlaybackState.PLAYING:
            stream_time = self._stream_time(stream)
            with self._clock_lock:
                frames = clock.audible_frames(stream_time)
        else:
            frames = submitted_frames
        return max(0, round(frames * 1000 / sample_rate_hz))

    def guide_countdown(self) -> tuple[int, int]:
        """Return audible guide beats remaining and total beats (zero outside the guide)."""
        with self._lock:
            if self._pcm is None or not self._guide_enabled:
                return 0, 0
            beat_frames = self._count_in_beat_frames
            target_frame = self._count_in_target_frame
            total = len(beat_frames)
            if not total:
                return 0, 0
            state = self._state
            submitted_frames = self._position_frames
            stream = self._stream
            clock = self._clock
            count_in_session = self._count_in_session
        if state == PlaybackState.STOPPED and submitted_frames == 0:
            return total, total
        if not count_in_session:
            return 0, 0
        if state not in {PlaybackState.PLAYING, PlaybackState.PAUSED}:
            return 0, 0
        if state == PlaybackState.PLAYING:
            stream_time = self._stream_time(stream)
            with self._clock_lock:
                frames = clock.audible_frames(stream_time)
        else:
            frames = submitted_frames
        if frames >= target_frame or frames < int(beat_frames[0]):
            return 0, 0
        elapsed = int(np.searchsorted(beat_frames, frames, side="right"))
        return total - elapsed + 1, total

    @property
    def underflow_count(self) -> int:
        """返回当前歌曲播放期间声卡报告的输出欠载次数。"""
        return self._underflow_count

    def duration_ms(self) -> int:
        with self._lock:
            return self._pcm.duration_ms if self._pcm is not None else 0

    def state(self) -> PlaybackState:
        with self._lock:
            return self._state

    def close_stream(self) -> None:
        stream: sd.OutputStream | None
        with self._lock:
            stream = self._stream
            self._stream = None
        if stream is not None:
            self._dispose_stream(stream)

    def close(self) -> None:
        self._publish_timer.stop()
        self.close_stream()
        self._dispose_retired_streams()

    def _ensure_stream(self) -> None:
        if self._stream is not None or self._pcm is None:
            return
        device, channels = self._resolve_output_device()
        self._stream_generation += 1
        generation = self._stream_generation
        self._stream = sd.OutputStream(
            samplerate=self._pcm.sample_rate_hz,
            channels=channels,
            dtype="float32",
            blocksize=self.block_size_frames,
            # 显示器重绘会短暂争用 Python 运行时间；显式留出输出缓冲，
            # 避免部分声卡默认约 20 ms 的“高延迟”缓冲仍然欠载。
            latency=self.output_latency_seconds,
            device=device,
            callback=self._audio_callback,
            finished_callback=lambda: self._stream_finished(generation),
        )

    def _resolve_output_device(self) -> tuple[int | str | None, int]:
        """Resolve a reconnected device by identity instead of its volatile index."""
        configured_device = self.output_device
        if configured_device is None:
            return None, 2

        if self._output_device_name is not None:
            for index, raw in enumerate(sd.query_devices()):
                if (
                    str(raw["name"]) == self._output_device_name
                    and int(raw["hostapi"]) == self._output_device_hostapi
                    and int(raw["max_output_channels"]) > 0
                ):
                    resolved_index = int(raw.get("index", index))
                    self.output_device = resolved_index
                    return resolved_index, min(2, int(raw["max_output_channels"]))
            raise RuntimeError(f"所选音频输出设备“{self._output_device_name}”尚未连接")

        raw = sd.query_devices(configured_device)
        output_channels = int(raw["max_output_channels"])
        if output_channels <= 0:
            raise RuntimeError("所选设备不是音频输出设备，请在设置中重新选择")
        self._output_device_name = str(raw["name"])
        self._output_device_hostapi = int(raw["hostapi"])
        return configured_device, min(2, output_channels)

    def _audio_callback(
        self,
        outdata: NDArray[np.float32],
        frames: int,
        time_info: Any,
        status: Any,
    ) -> None:
        outdata.fill(0.0)
        if getattr(status, "output_underflow", False):
            self._underflow_count += 1
        try:
            with self._lock:
                if self._pcm is None or self._state != PlaybackState.PLAYING:
                    return
                start_frames = self._position_frames
                available_frames = min(
                    frames,
                    math.ceil((self._pcm.canonical_frames - start_frames) / self._playback_rate),
                )
                if available_frames <= 0:
                    self._state = PlaybackState.ENDED
                    return
                mix = self._mix_buffer[:available_frames]
                mix.fill(0.0)
                if self._playback_rate == 1.0:
                    self._mix_normal_speed(mix, start_frames, available_frames)
                else:
                    self._mix_slow_speed(mix, start_frames, available_frames)
                self._mix_guide_beats(
                    mix,
                    start_frames,
                    available_frames,
                    self._playback_rate,
                )
                np.clip(mix, -1.0, 1.0, out=mix)
                if outdata.shape[1] == 1:
                    mono = self._mono_buffer[:available_frames]
                    np.add(mix[:, 0], mix[:, 1], out=mono)
                    np.multiply(mono, 0.5, out=mono)
                    outdata[:available_frames, 0] = mono
                else:
                    outdata[:available_frames] = mix
                self._position_frames = min(
                    float(self._pcm.canonical_frames),
                    start_frames + available_frames * self._playback_rate,
                )
                dac_time_raw = getattr(time_info, "outputBufferDacTime", None)
                dac_time = float(dac_time_raw) if dac_time_raw is not None else None
                with self._clock_lock:
                    self._clock.update_submission(start_frames, self._position_frames, dac_time)
                if self._position_frames >= self._pcm.canonical_frames:
                    self._state = PlaybackState.ENDED
        except Exception as exc:
            outdata.fill(0.0)
            with self._lock:
                self._state = PlaybackState.ERROR
            self._errors.put(f"音频回调失败：{exc}")

    def _mix_normal_speed(
        self,
        mix: NDArray[np.float32],
        start_frame: float,
        frame_count: int,
    ) -> None:
        """按原速混音，保留原有的零拷贝切片路径。"""
        if self._pcm is None:
            return
        music_offset = min(frame_count, max(0, math.ceil(-start_frame)))
        music_frames = frame_count - music_offset
        if music_frames <= 0:
            return
        source_start = max(0, int(start_frame))
        music_mix = mix[music_offset : music_offset + music_frames]
        for track, source in self._pcm.tracks.items():
            gain = self._gain_buffer[track][:music_frames]
            self._ramps[track].render_into(gain, music_frames)
            track_buffer = self._track_buffer[:music_frames]
            np.multiply(
                source[source_start : source_start + music_frames],
                gain[:, np.newaxis],
                out=track_buffer,
            )
            np.add(music_mix, track_buffer, out=music_mix)
        np.multiply(music_mix, self._master_gain, out=music_mix)

    def _mix_slow_speed(
        self,
        mix: NDArray[np.float32],
        start_frame: float,
        frame_count: int,
    ) -> None:
        """线性重采样实现慢速播放，各轨始终共用同一时间轴。"""
        if self._pcm is None:
            return
        positions = start_frame + np.arange(frame_count, dtype=np.float64) * self._playback_rate
        music_offset = int(np.searchsorted(positions, 0.0, side="left"))
        if music_offset >= frame_count:
            return
        source_positions = np.clip(
            positions[music_offset:],
            0.0,
            float(self._pcm.canonical_frames - 1),
        )
        left = np.floor(source_positions).astype(np.int64)
        right = np.minimum(left + 1, self._pcm.canonical_frames - 1)
        fraction = np.asarray(source_positions - left, dtype=np.float32)[:, np.newaxis]
        music_frames = frame_count - music_offset
        music_mix = mix[music_offset:]
        for track, source in self._pcm.tracks.items():
            gain = self._gain_buffer[track][:music_frames]
            self._ramps[track].render_into(gain, music_frames)
            track_buffer = self._track_buffer[:music_frames]
            np.subtract(source[right], source[left], out=track_buffer)
            np.multiply(track_buffer, fraction, out=track_buffer)
            np.add(track_buffer, source[left], out=track_buffer)
            np.multiply(track_buffer, gain[:, np.newaxis], out=track_buffer)
            np.add(music_mix, track_buffer, out=music_mix)
        np.multiply(music_mix, self._master_gain, out=music_mix)

    def _mix_guide_beats(
        self,
        mix: NDArray[np.float32],
        start_frame: float,
        frame_count: int,
        playback_rate: float,
    ) -> None:
        if not self._guide_enabled or not self._count_in_active or self._beat_click.size == 0:
            return
        self._mix_click_frames(
            mix,
            start_frame,
            frame_count,
            self._count_in_beat_frames,
            self._count_in_downbeat_frames,
            playback_rate,
        )
        if start_frame + frame_count * playback_rate >= self._count_in_target_frame:
            self._count_in_active = False

    def _mix_click_frames(
        self,
        mix: NDArray[np.float32],
        start_frame: float,
        frame_count: int,
        beat_frames: NDArray[np.int64],
        accent_frames: NDArray[np.int64],
        playback_rate: float = 1.0,
    ) -> None:
        if beat_frames.size == 0:
            return
        end_frame = start_frame + frame_count * playback_rate
        click_frames = self._beat_click.size
        first = int(
            np.searchsorted(
                beat_frames,
                start_frame - click_frames * playback_rate + playback_rate,
                side="left",
            )
        )
        last = int(np.searchsorted(beat_frames, end_frame, side="left"))
        for beat_frame in beat_frames[first:last]:
            beat_frame_value = int(beat_frame)
            accent_index = int(np.searchsorted(accent_frames, beat_frame_value))
            is_accent = (
                accent_index < accent_frames.size
                and accent_frames[accent_index] == beat_frame_value
            )
            click = self._downbeat_click if is_accent else self._beat_click
            target_start = max(0, math.ceil((beat_frame_value - start_frame) / playback_rate))
            source_start = max(
                0,
                math.floor((start_frame - beat_frame_value) / playback_rate),
            )
            sample_count = min(frame_count - target_start, click_frames - source_start)
            if sample_count <= 0:
                continue
            target_end = target_start + sample_count
            source_end = source_start + sample_count
            mix[target_start:target_end] += (
                click[source_start:source_end, np.newaxis] * self._master_gain
            )

    @staticmethod
    def _create_beat_click(sample_rate_hz: int) -> NDArray[np.float32]:
        """合成清晰的木鱼感短音，不改变原伴奏增益。"""
        frame_count = max(1, round(sample_rate_hz * 0.055))
        time = np.arange(frame_count, dtype=np.float32) / sample_rate_hz
        envelope = np.exp(-time * 52.0)
        fundamental = np.sin(2.0 * np.pi * 920.0 * time)
        overtone = np.sin(2.0 * np.pi * 1_480.0 * time + 0.35)
        click = envelope * (0.62 * fundamental + 0.25 * overtone)
        # 首帧保留明确瞬态；否则强伴奏中的短正弦容易被最终削波掩盖。
        click[0] = -0.9
        np.clip(click, -0.9, 0.9, out=click)
        return np.asarray(click, dtype=np.float32)

    def _stream_finished(self, generation: int | None = None) -> None:
        retired_stream: sd.OutputStream | None = None
        with self._lock:
            if (
                self._stream is None
                or self._state != PlaybackState.PLAYING
                or (generation is not None and generation != self._stream_generation)
            ):
                return
            retired_stream = self._stream
            self._stream = None
            self._state = PlaybackState.ERROR
        # The finished callback runs on PortAudio's thread.  Closing the stream
        # there can deadlock the backend, so hand it to the Qt timer thread.
        if retired_stream is not None:
            self._retired_streams.put(retired_stream)
        self._errors.put("播放期间音频输出设备已断开或停止响应")

    def _dispose_retired_streams(self) -> None:
        while True:
            try:
                stream = self._retired_streams.get_nowait()
            except queue.Empty:
                return
            self._dispose_stream(stream)

    @staticmethod
    def _dispose_stream(stream: sd.OutputStream) -> None:
        try:
            # Song changes should discard queued audio rather than wait for
            # PortAudio to drain it on the Qt event thread.
            abort = getattr(stream, "abort", None)
            if abort is not None:
                abort()
            else:
                stream.stop()
        except Exception:
            LOGGER.warning("中止音频输出流失败", exc_info=True)
        try:
            stream.close()
        except Exception:
            LOGGER.warning("关闭音频输出流失败", exc_info=True)

    def _audible_frames_locked(self) -> float:
        stream_time = self._stream_time(self._stream)
        with self._clock_lock:
            return self._clock.audible_frames(stream_time)

    @staticmethod
    def _stream_time(stream: sd.OutputStream | None) -> float | None:
        if stream is None:
            return None
        try:
            return float(stream.time)
        except Exception:
            return None

    def _fade_frames_locked(self) -> int:
        sample_rate_hz = self._pcm.sample_rate_hz if self._pcm is not None else 44_100
        return max(1, round(self._mute_fade_ms * sample_rate_hz / 1000))

    def _publish_state(self) -> None:
        self._dispose_retired_streams()
        underflow_count = self._underflow_count
        if underflow_count > self._last_logged_underflow_count:
            LOGGER.warning(
                "检测到音频输出欠载，当前歌曲累计 %d 次",
                underflow_count,
            )
            self._last_logged_underflow_count = underflow_count
        while True:
            try:
                message = self._errors.get_nowait()
            except queue.Empty:
                break
            self.error_raised.emit(message)
        position_ms = self.position_ms()
        if position_ms != self._last_emitted_position_ms:
            self._last_emitted_position_ms = position_ms
            self.position_changed.emit(position_ms)
        guide_countdown = self.guide_countdown()
        if guide_countdown != self._last_emitted_guide_countdown:
            self._last_emitted_guide_countdown = guide_countdown
            self.guide_countdown_changed.emit(*guide_countdown)
        current_state = self.state()
        if current_state != self._last_emitted_state:
            self._last_emitted_state = current_state
            self.state_changed.emit(current_state)
