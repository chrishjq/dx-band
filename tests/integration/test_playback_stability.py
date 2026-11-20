# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import threading
from types import SimpleNamespace

import numpy as np
import pytest
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from dxband.audio.audio_clock import AudioMasterClock
from dxband.audio.pcm_cache import PcmSongData
from dxband.audio.stem_mixer import PlaybackState, StemMixerEngine
from dxband.constants import TrackKind
from dxband.lyrics.timeline import LyricTimeline
from dxband.models.lyric import LyricLine, LyricsDocument


class _CallbackStatus:
    output_underflow = False


def test_play_does_not_hold_mix_lock_while_starting_output_stream(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    del qtbot
    samples = np.zeros((4_096, 2), dtype=np.float32)
    engine = StemMixerEngine(block_size_frames=2_048)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=44_100,
            channels=2,
            canonical_frames=len(samples),
            tracks={TrackKind.VOCALS: samples},
        )
    )

    class _StartWaitsForCallback:
        active = False

        def start(self) -> None:
            finished = threading.Event()

            def run_callback() -> None:
                try:
                    engine._audio_callback(
                        np.empty((2_048, 2), dtype=np.float32),
                        2_048,
                        SimpleNamespace(outputBufferDacTime=0.0),
                        _CallbackStatus(),
                    )
                finally:
                    finished.set()

            threading.Thread(target=run_callback, daemon=True).start()
            if not finished.wait(0.5):
                raise RuntimeError("audio callback blocked during stream startup")
            self.active = True

        def stop(self) -> None:
            self.active = False

        def close(self) -> None:
            pass

    stream = _StartWaitsForCallback()
    monkeypatch.setattr(engine, "_ensure_stream", lambda: setattr(engine, "_stream", stream))
    engine.play()

    assert stream.active
    assert engine.state() == PlaybackState.PLAYING
    engine.close()


@pytest.mark.parametrize("rate", [0.5, 0.75, 1.25])
def test_variable_bpm_playback_resamples_all_stems_on_one_timeline(
    qtbot: QtBot, rate: float
) -> None:
    del qtbot
    source_values = np.arange(8, dtype=np.float32) / 10
    source = np.column_stack((source_values, source_values)).astype(np.float32)
    engine = StemMixerEngine(block_size_frames=6)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=1_000,
            channels=2,
            canonical_frames=len(source),
            tracks={TrackKind.VOCALS: source},
        ),
        master_volume=1.0,
    )
    engine.set_playback_rate(rate)
    engine._state = PlaybackState.PLAYING
    output = np.empty((6, 2), dtype=np.float32)

    engine._audio_callback(
        output,
        6,
        SimpleNamespace(outputBufferDacTime=0.0),
        _CallbackStatus(),
    )

    assert np.allclose(output[:, 0], np.arange(6) * rate / 10)
    assert engine._position_frames == 6 * rate
    assert engine.playback_rate() == rate
    engine.close()


def test_playback_rate_accepts_bpm_ratios_within_supported_range(qtbot: QtBot) -> None:
    del qtbot
    engine = StemMixerEngine()
    engine.set_playback_rate(0.25)
    assert engine.playback_rate() == 0.25
    engine.set_playback_rate(1.25)
    assert engine.playback_rate() == 1.25
    for rate in (0.19, 2.01, float("nan")):
        with pytest.raises(ValueError, match="\u4e0d\u652f\u6301"):
            engine.set_playback_rate(rate)
    engine.close()


def test_two_bar_count_in_uses_audio_clock_before_song_starts(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    del qtbot
    sample_rate = 1_000
    samples = np.full((2_000, 2), 0.2, dtype=np.float32)
    engine = StemMixerEngine(block_size_frames=1_000)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=sample_rate,
            channels=2,
            canonical_frames=len(samples),
            tracks={track: samples for track in TrackKind},
        ),
        master_volume=1.0,
    )
    engine.set_guide_beats(True, bpm=120, beats_per_bar=4, count_in_bars=2)
    assert engine._count_in_start_frame == -4_000
    assert tuple(engine._count_in_beat_frames) == tuple(range(-4_000, 0, 500))
    countdown_events: list[tuple[int, int]] = []
    engine.guide_countdown_changed.connect(
        lambda remaining, total: countdown_events.append((remaining, total))
    )
    monkeypatch.setattr(engine, "_ensure_stream", lambda: None)
    engine.play()
    assert engine._position_frames == -4_000
    assert engine.guide_countdown() == (8, 8)
    engine._publish_state()
    output = np.empty((1_000, 2), dtype=np.float32)
    for block in range(4):
        engine._audio_callback(
            output,
            1_000,
            SimpleNamespace(outputBufferDacTime=float(block)),
            _CallbackStatus(),
        )
        assert engine.position_ms() == 0
        expected_countdown = (6 - block * 2, 8) if block < 3 else (0, 0)
        assert engine.guide_countdown() == expected_countdown
        engine._publish_state()
        assert output[0, 0] < -0.8
        assert output[500, 0] < -0.8
        if block in {0, 2}:
            assert output[0, 0] < output[500, 0]
        assert output[100, 0] == 0.0
        if block == 0:
            engine.pause()
            assert engine._position_frames == -3_000
            assert engine.guide_countdown() == (6, 8)
            engine.play()
            assert engine._position_frames == -3_000

    engine._audio_callback(
        output,
        1_000,
        SimpleNamespace(outputBufferDacTime=4.0),
        _CallbackStatus(),
    )
    assert np.allclose(output, 1.0)
    assert engine.position_ms() == 1_000
    engine.stop()
    assert engine.guide_countdown() == (8, 8)
    engine.play()
    assert engine._position_frames == -4_000
    assert engine.guide_countdown() == (8, 8)
    assert countdown_events == [(8, 8), (6, 8), (4, 8), (2, 8), (0, 0)]
    engine.close()


def test_guide_to_song_transition_inside_one_audio_block_has_no_song_click(qtbot: QtBot) -> None:
    del qtbot
    samples = np.full((1_000, 2), 0.2, dtype=np.float32)
    engine = StemMixerEngine(block_size_frames=750)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=1_000,
            channels=2,
            canonical_frames=len(samples),
            tracks={track: samples for track in TrackKind},
        ),
        master_volume=1.0,
    )
    engine.set_guide_beats(True, bpm=120, beats_per_bar=4)
    engine._state = PlaybackState.PLAYING
    engine._position_frames = -500
    engine._count_in_active = True
    output = np.empty((750, 2), dtype=np.float32)
    engine._audio_callback(
        output,
        750,
        SimpleNamespace(outputBufferDacTime=0.0),
        _CallbackStatus(),
    )
    assert output[0, 0] < -0.8
    assert np.allclose(output[100:500], 0.0)
    assert np.allclose(output[500:], 1.0)
    assert not engine._count_in_active
    engine.close()


def test_guide_countdown_uses_audible_not_submitted_audio_frames(qtbot: QtBot) -> None:
    del qtbot
    silence = np.zeros((2_000, 2), dtype=np.float32)
    engine = StemMixerEngine()
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=1_000,
            channels=2,
            canonical_frames=len(silence),
            tracks={track: silence for track in TrackKind},
        )
    )
    engine.set_guide_beats(True, bpm=120, beats_per_bar=4)
    engine._state = PlaybackState.PLAYING
    engine._count_in_session = True
    engine._position_frames = -2_500
    engine._stream = SimpleNamespace(time=1.0)
    with engine._clock_lock:
        engine._clock.reset(-4_000)
        engine._clock.update_submission(-4_000, -2_500, 1.0)
    assert engine.guide_countdown() == (8, 8)
    engine._stream.time = 1.5
    assert engine.guide_countdown() == (7, 8)
    engine._stream.time = 2.5
    assert engine.guide_countdown() == (5, 8)
    engine._stream = None
    engine.close()


def test_guide_beats_lead_directly_into_delayed_first_song_beat(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    del qtbot
    samples = np.full((2_000, 2), 0.2, dtype=np.float32)
    engine = StemMixerEngine(block_size_frames=500)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=1_000,
            channels=2,
            canonical_frames=len(samples),
            tracks={track: samples for track in TrackKind},
        ),
        master_volume=1 / 3,
    )
    engine.set_guide_beats(True, bpm=120, beats_per_bar=4, first_beat_ms=1_400)
    assert engine._count_in_target_frame == 1_400
    assert tuple(engine._count_in_beat_frames) == tuple(range(-2_600, 1_400, 500))
    monkeypatch.setattr(engine, "_ensure_stream", lambda: None)
    engine.play()
    assert engine._position_frames == -2_600
    assert engine.guide_countdown() == (8, 8)

    # Song PCM has begun, but the last guide click is still one beat before its first beat.
    engine._position_frames = 500
    with engine._clock_lock:
        engine._clock.reset(500)
    output = np.empty((500, 2), dtype=np.float32)
    engine._audio_callback(output, 500, SimpleNamespace(outputBufferDacTime=0.0), _CallbackStatus())
    assert np.isclose(output[0, 0], 0.4)
    assert output[400, 0] < output[0, 0]  # last click at song time 900 ms
    assert engine.guide_countdown() == (1, 8)
    engine.pause()
    assert engine.guide_countdown() == (1, 8)
    engine.play()
    engine._audio_callback(output, 500, SimpleNamespace(outputBufferDacTime=0.5), _CallbackStatus())
    assert np.allclose(output[400:], 0.4)  # first song beat at 1400 ms has no guide click
    assert engine.guide_countdown() == (0, 0)
    engine.seek_ms(0)
    assert engine.guide_countdown() == (0, 0)
    engine.close()


def test_guide_uses_bpm_and_seek_skips_it(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    del qtbot
    silence = np.zeros((3_000, 2), dtype=np.float32)
    engine = StemMixerEngine(block_size_frames=100)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=1_000,
            channels=2,
            canonical_frames=len(silence),
            tracks={track: silence for track in TrackKind},
        )
    )
    engine.set_guide_beats(True, bpm=71, beats_per_bar=4, count_in_bars=2)
    assert engine._count_in_start_frame == -round(8 * 60_000 / 71)
    assert len(engine._count_in_beat_frames) == 8
    assert all(frame < 0 for frame in engine._count_in_beat_frames)
    assert np.all(np.abs(np.diff(engine._count_in_beat_frames) - 60_000 / 71) <= 1)
    engine.seek_ms(200)
    assert engine._position_frames == 200
    assert not engine._count_in_active
    engine._state = PlaybackState.PLAYING
    output = np.empty((1_000, 2), dtype=np.float32)
    engine._audio_callback(
        output,
        1_000,
        SimpleNamespace(outputBufferDacTime=0.0),
        _CallbackStatus(),
    )
    assert np.allclose(output, 0.0)
    engine.set_guide_beats(True, bpm=120, beats_per_bar=3)
    assert engine._count_in_start_frame == -3_000
    assert len(engine._count_in_beat_frames) == 6
    assert tuple(engine._count_in_downbeat_frames) == (-3_000, -1_500)
    engine.stop()
    monkeypatch.setattr(engine, "_ensure_stream", lambda: None)
    engine.play()
    assert engine.guide_countdown() == (6, 6)
    engine.close()


def test_thirty_minute_four_stem_clock_has_no_accumulated_drift(qtbot: QtBot) -> None:
    """用零步长视图模拟 30 分钟四轨，避免为测试分配数 GB 内存。"""
    del qtbot
    sample_rate = 44_100
    block_size = sample_rate
    duration_seconds = 30 * 60
    canonical_frames = sample_rate * duration_seconds
    silent_sample = np.zeros((1, 2), dtype=np.float32)
    silent_track = np.broadcast_to(silent_sample, (canonical_frames, 2))
    engine = StemMixerEngine(block_size_frames=block_size)
    engine._pcm = PcmSongData(
        sample_rate_hz=sample_rate,
        channels=2,
        canonical_frames=canonical_frames,
        tracks={track: silent_track for track in TrackKind},
    )
    engine._state = PlaybackState.PLAYING
    engine._clock = AudioMasterClock(sample_rate_hz=sample_rate)
    output = np.empty((block_size, 2), dtype=np.float32)
    status = _CallbackStatus()

    for second in range(duration_seconds):
        engine._audio_callback(
            output,
            block_size,
            SimpleNamespace(outputBufferDacTime=float(second)),
            status,
        )

    assert engine._position_frames == canonical_frames
    assert engine.position_ms() == 30 * 60 * 1000
    assert engine.state() == PlaybackState.ENDED
    assert engine.underflow_count == 0
    engine.close()


def test_mixer_and_lyrics_share_the_same_seeked_master_position(qtbot: QtBot) -> None:
    del qtbot
    sample_rate = 1_000
    canonical_frames = 10_000
    values = {
        track: np.full((canonical_frames, 2), index + 1, dtype=np.float32)
        for index, track in enumerate(TrackKind)
    }
    engine = StemMixerEngine(block_size_frames=100)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=sample_rate,
            channels=2,
            canonical_frames=canonical_frames,
            tracks=values,
        ),
        master_volume=0.05,
    )
    document = LyricsDocument(
        schema_version=1,
        title="集成测试",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=0, end_ms=5_000, text="第一句", words=[]),
            LyricLine(
                id="line-0002",
                start_ms=5_000,
                end_ms=10_000,
                text="第二句",
                words=[],
            ),
        ],
    )
    timeline = LyricTimeline(document)
    engine.seek_ms(5_000)
    engine._state = PlaybackState.PLAYING
    output = np.empty((100, 2), dtype=np.float32)

    engine._audio_callback(
        output,
        100,
        SimpleNamespace(outputBufferDacTime=5.0),
        _CallbackStatus(),
    )

    position_ms = engine.position_ms()
    context = timeline.context_at(position_ms)
    assert engine._position_frames == 5_100
    assert position_ms == 5_100
    assert context.current is not None
    assert context.current.id == "line-0002"
    assert np.allclose(output, 1.0)
    engine.close()


def test_guide_beats_stop_at_song_start(qtbot: QtBot) -> None:
    del qtbot
    sample_rate = 1_000
    frame_count = 200
    silence = np.zeros((frame_count, 2), dtype=np.float32)
    engine = StemMixerEngine(block_size_frames=100)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=sample_rate,
            channels=2,
            canonical_frames=frame_count,
            tracks={track: silence for track in TrackKind},
        ),
        master_volume=1.0,
    )
    engine.set_guide_beats(True, bpm=120, beats_per_bar=4)
    engine._state = PlaybackState.PLAYING
    output = np.empty((100, 2), dtype=np.float32)

    engine._audio_callback(
        output,
        100,
        SimpleNamespace(outputBufferDacTime=0.0),
        _CallbackStatus(),
    )

    assert np.allclose(output, 0.0)
    engine.close()


def test_guide_beats_do_not_alter_backing_mix_after_song_starts(
    qtbot: QtBot,
) -> None:
    del qtbot
    sample_rate = 1_000
    frame_count = 200
    loud_track = np.full((frame_count, 2), 0.4, dtype=np.float32)
    engine = StemMixerEngine(block_size_frames=100)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=sample_rate,
            channels=2,
            canonical_frames=frame_count,
            tracks={track: loud_track for track in TrackKind},
        ),
        master_volume=1.0,
    )
    engine.set_guide_beats(True, bpm=120, beats_per_bar=4)
    engine._state = PlaybackState.PLAYING
    output = np.empty((100, 2), dtype=np.float32)

    engine._audio_callback(
        output,
        100,
        SimpleNamespace(outputBufferDacTime=0.0),
        _CallbackStatus(),
    )

    assert np.allclose(output, 1.0)
    engine.close()
