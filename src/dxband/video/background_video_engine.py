# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QObject, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem, QVideoWidget


class BackgroundVideoEngine(QObject):
    """大致跟随音频主时钟的静音背景视频播放器。"""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        video_output: QVideoWidget | QGraphicsVideoItem | None = None,
    ) -> None:
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setMuted(True)
        self.player.setAudioOutput(self.audio_output)
        if video_output is None:
            self.video_sink = QVideoSink(self)
            self.player.setVideoOutput(self.video_sink)
        else:
            self.video_sink = video_output.videoSink()
            self.player.setVideoOutput(video_output)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        # 背景动画无需逐帧对齐音频；频繁 seek 会迫使视频重新解码。
        self._correction_threshold_ms = 1_000
        self._seek_cooldown_ms = 3_000
        self._last_seek = QElapsedTimer()

    def load(self, path: Path) -> None:
        self._last_seek.invalidate()
        self.player.setSource(QUrl.fromLocalFile(str(path.resolve())))

    def clear(self) -> None:
        self._last_seek.invalidate()
        self.player.stop()
        self.player.setSource(QUrl())

    def play(self, master_ms: int) -> None:
        self.player.setPosition(max(0, master_ms))
        self.player.play()

    def pause(self) -> None:
        self.player.pause()

    def stop(self) -> None:
        self.player.stop()

    def synchronize(self, master_ms: int, playing: bool) -> None:
        """跟随主时钟，偏差过大时直接纠偏。"""
        target_ms = max(0, master_ms)
        duration_ms = self.player.duration()
        if duration_ms > 0:
            target_ms %= duration_ms
        can_correct = (
            not self._last_seek.isValid()
            or self._last_seek.elapsed() >= self._seek_cooldown_ms
        )
        if (
            playing
            and duration_ms > 0
            and abs(self.player.position() - target_ms) > self._correction_threshold_ms
            and can_correct
        ):
            self.player.setPosition(target_ms)
            self._last_seek.start()
        expected_state = QMediaPlayer.PlaybackState.PlayingState
        if playing and self.player.playbackState() != expected_state:
            self.player.play()
        if not playing and self.player.playbackState() == expected_state:
            self.player.pause()
