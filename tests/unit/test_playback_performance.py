# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

import numpy as np
from PySide6.QtGui import QColor, QImage
from PySide6.QtMultimedia import QVideoFrame
from pytestqt.qtbot import QtBot

from dxband.audio.pcm_cache import PcmSongData
from dxband.audio.stem_mixer import PlaybackState, StemMixerEngine
from dxband.constants import TrackKind
from dxband.models.lyric import LyricLine, LyricsDocument
from dxband.ui.render.audience_widget import AudienceWidget
from dxband.ui.render.singer_widget import SingerWidget


def _lyrics() -> LyricsDocument:
    return LyricsDocument(
        schema_version=1,
        title="性能测试",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=0, end_ms=4_000, text="第一句", words=[]),
            LyricLine(id="line-0002", start_ms=4_000, end_ms=8_000, text="第二句", words=[]),
        ],
    )


class _CountingAudienceWidget(AudienceWidget):
    def __init__(self) -> None:
        self.update_count = 0
        super().__init__()

    def update(self, *args: object) -> None:
        self.update_count += 1
        super().update(*args)


class _CountingSingerWidget(SingerWidget):
    def __init__(self) -> None:
        self.update_count = 0
        super().__init__()

    def update(self, *args: object) -> None:
        self.update_count += 1
        super().update(*args)


def test_audience_only_repaints_when_visible_lines_change(qtbot: QtBot) -> None:
    window = _CountingAudienceWidget()
    qtbot.addWidget(window)
    window.set_document(_lyrics())
    window.set_position_ms(1_000)
    repaint_count = window.update_count

    window.set_position_ms(1_040)
    window.set_position_ms(3_000)
    assert window.update_count == repaint_count

    window.set_position_ms(4_000)
    assert window.update_count == repaint_count + 1


def test_audience_video_frames_do_not_repaint_the_lyric_window(
    qtbot: QtBot, tmp_path: Path
) -> None:
    window = _CountingAudienceWidget()
    qtbot.addWidget(window)
    window.show()
    sample = tmp_path / "background.mp4"
    sample.write_bytes(b"test video placeholder")
    window.set_background_video(sample)
    assert window.background_video.player.videoOutput() is window._video_item
    assert window._video_overlay.isVisible()
    source = QImage(960, 540, QImage.Format.Format_RGB32)
    source.fill(QColor("blue"))
    frame = QVideoFrame(source)
    baseline = window.update_count

    window.background_video.video_sink.setVideoFrame(frame)
    qtbot.wait(20)
    assert window.update_count == baseline
    window.set_document(_lyrics())
    window.set_position_ms(1_000)
    assert window.update_count == baseline

    window.set_background_video(None)
    assert window._video_view.isHidden()


def test_singer_only_repaints_when_lines_or_countdown_second_change(
    qtbot: QtBot,
) -> None:
    window = _CountingSingerWidget()
    qtbot.addWidget(window)
    window.set_document(_lyrics())
    window.set_position_ms(1_100)
    repaint_count = window.update_count

    window.set_position_ms(1_200)
    assert window.update_count == repaint_count

    window.set_position_ms(2_100)
    assert window.update_count == repaint_count + 1


def test_position_query_does_not_hold_mixer_lock_when_reading_stream_time(
    qtbot: QtBot,
) -> None:
    del qtbot
    engine = StemMixerEngine()
    samples = np.zeros((4_410, 2), dtype=np.float32)
    engine._pcm = PcmSongData(
        sample_rate_hz=44_100,
        channels=2,
        canonical_frames=len(samples),
        tracks={track: samples for track in TrackKind},
    )
    engine._state = PlaybackState.PLAYING
    engine._position_frames = len(samples)

    class _CheckingStream:
        lock_was_available = False

        @property
        def time(self) -> float:
            self.lock_was_available = engine._lock.acquire(blocking=False)
            if self.lock_was_available:
                engine._lock.release()
            return 0.0

        def stop(self) -> None:
            return

        def close(self) -> None:
            return

    stream = _CheckingStream()
    engine._stream = stream  # type: ignore[assignment]

    engine.position_ms()

    assert stream.lock_was_available
    engine.close()


def test_audio_device_open_failure_becomes_visible_engine_error(
    qtbot: QtBot,
    monkeypatch,
) -> None:
    engine = StemMixerEngine()
    samples = np.zeros((4_410, 2), dtype=np.float32)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=44_100,
            channels=2,
            canonical_frames=len(samples),
            tracks={track: samples for track in TrackKind},
        )
    )
    errors: list[str] = []
    engine.error_raised.connect(errors.append)

    def fail_open(**_kwargs: object) -> None:
        raise RuntimeError("设备不存在")

    monkeypatch.setattr("dxband.audio.stem_mixer.sd.OutputStream", fail_open)
    engine.play()
    engine._publish_state()

    assert engine.state() == PlaybackState.ERROR
    assert errors == ["音频输出设备不可用：设备不存在"]
    engine.close()


def test_audio_stream_reserves_output_buffer_for_display_redraws(
    qtbot: QtBot,
    monkeypatch,
) -> None:
    del qtbot
    engine = StemMixerEngine()
    samples = np.zeros((4_410, 2), dtype=np.float32)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=44_100,
            channels=2,
            canonical_frames=len(samples),
            tracks={track: samples for track in TrackKind},
        )
    )
    options: dict[str, object] = {}

    class _FakeStream:
        def stop(self) -> None:
            return

        def close(self) -> None:
            return

    def open_stream(**kwargs: object) -> _FakeStream:
        options.update(kwargs)
        return _FakeStream()

    monkeypatch.setattr("dxband.audio.stem_mixer.sd.OutputStream", open_stream)
    engine._ensure_stream()

    assert options["latency"] == 0.15
    assert options["blocksize"] == engine.block_size_frames
    engine.close()


def test_unexpected_stream_finish_marks_device_as_disconnected(qtbot: QtBot) -> None:
    del qtbot
    engine = StemMixerEngine()
    samples = np.zeros((4_410, 2), dtype=np.float32)
    engine._pcm = PcmSongData(
        sample_rate_hz=44_100,
        channels=2,
        canonical_frames=len(samples),
        tracks={track: samples for track in TrackKind},
    )
    engine._state = PlaybackState.PLAYING

    class _ActiveStream:
        active = True

        def stop(self) -> None:
            return

        def close(self) -> None:
            return

    engine._stream = _ActiveStream()  # type: ignore[assignment]
    errors: list[str] = []
    engine.error_raised.connect(errors.append)

    engine._stream_finished()
    engine._publish_state()

    assert engine.state() == PlaybackState.ERROR
    assert engine._stream is None
    assert errors == ["播放期间音频输出设备已断开或停止响应"]
    engine.close()


def test_disposing_output_stream_discards_pending_audio() -> None:
    calls: list[str] = []

    class _Stream:
        def abort(self) -> None:
            calls.append("abort")

        def stop(self) -> None:
            calls.append("stop")

        def close(self) -> None:
            calls.append("close")

    StemMixerEngine._dispose_stream(_Stream())  # type: ignore[arg-type]

    assert calls == ["abort", "close"]


def test_play_reopens_output_stream_after_device_reconnect(
    qtbot: QtBot,
    monkeypatch,
) -> None:
    del qtbot
    engine = StemMixerEngine()
    samples = np.zeros((4_410, 2), dtype=np.float32)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=44_100,
            channels=2,
            canonical_frames=len(samples),
            tracks={track: samples for track in TrackKind},
        )
    )

    class _ReconnectableStream:
        def __init__(self, **kwargs: object) -> None:
            self.active = False
            self.finished_callback = kwargs["finished_callback"]
            self.closed = False
            streams.append(self)

        def start(self) -> None:
            self.active = True

        def stop(self) -> None:
            self.active = False

        def close(self) -> None:
            self.closed = True

    streams: list[_ReconnectableStream] = []

    monkeypatch.setattr(
        "dxband.audio.stem_mixer.sd.OutputStream",
        _ReconnectableStream,
    )

    engine.play()
    first_stream = streams[-1]
    first_stream.active = False
    first_stream.finished_callback()

    assert engine.state() == PlaybackState.ERROR
    assert engine._stream is None

    engine.play()

    assert len(streams) == 2
    assert first_stream.closed
    assert streams[-1].active
    assert engine.state() == PlaybackState.PLAYING
    engine.close()


def test_reconnected_output_device_is_found_by_name_after_its_index_changes(
    qtbot: QtBot,
    monkeypatch,
) -> None:
    del qtbot
    engine = StemMixerEngine(output_device=4)
    samples = np.zeros((4_410, 2), dtype=np.float32)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=44_100,
            channels=2,
            canonical_frames=len(samples),
            tracks={track: samples for track in TrackKind},
        )
    )
    device_index = 4
    stream_options: list[dict[str, object]] = []

    def query_devices(device: object = None) -> object:
        info = {
            "index": device_index,
            "name": "蓝牙音箱",
            "hostapi": 0,
            "max_output_channels": 2,
        }
        if device is None:
            return [
                {
                    "index": 0,
                    "name": "内置麦克风",
                    "hostapi": 0,
                    "max_output_channels": 0,
                },
                info,
            ]
        return info

    class _Stream:
        def __init__(self, **kwargs: object) -> None:
            self.active = False
            self.finished_callback = kwargs["finished_callback"]
            stream_options.append(kwargs)

        def start(self) -> None:
            self.active = True

        def stop(self) -> None:
            self.active = False

        def close(self) -> None:
            return

    monkeypatch.setattr("dxband.audio.stem_mixer.sd.query_devices", query_devices)
    monkeypatch.setattr("dxband.audio.stem_mixer.sd.OutputStream", _Stream)

    engine.play()
    first_stream = engine._stream
    assert first_stream is not None
    first_stream.active = False
    first_stream.finished_callback()
    device_index = 1
    engine.play()

    assert stream_options[0]["device"] == 4
    assert stream_options[1]["device"] == 1
    assert engine.output_device == 1
    assert engine.state() == PlaybackState.PLAYING
    engine.close()


def test_mono_output_device_downmixes_stereo_without_callback_error(
    qtbot: QtBot,
    monkeypatch,
) -> None:
    del qtbot
    engine = StemMixerEngine(output_device=2, block_size_frames=100)
    samples = np.full((100, 2), 0.1, dtype=np.float32)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=44_100,
            channels=2,
            canonical_frames=len(samples),
            tracks={track: samples for track in TrackKind},
        )
    )
    options: dict[str, object] = {}

    monkeypatch.setattr(
        "dxband.audio.stem_mixer.sd.query_devices",
        lambda _device: {
            "name": "单声道输出",
            "hostapi": 0,
            "max_output_channels": 1,
        },
    )

    class _MonoStream:
        active = False

        def __init__(self, **kwargs: object) -> None:
            options.update(kwargs)

        def start(self) -> None:
            self.active = True

        def stop(self) -> None:
            self.active = False

        def close(self) -> None:
            return

    monkeypatch.setattr("dxband.audio.stem_mixer.sd.OutputStream", _MonoStream)

    engine.play()
    outdata = np.zeros((100, 1), dtype=np.float32)
    callback = options["callback"]
    callback(outdata, 100, object(), object())

    assert options["channels"] == 1
    assert np.any(outdata)
    assert engine.state() == PlaybackState.ENDED
    engine.close()
