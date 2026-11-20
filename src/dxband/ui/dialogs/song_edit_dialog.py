# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""One editing workspace for song metadata, lyrics, rhythm, and chords."""

from dataclasses import dataclass

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dxband.audio.transport import AudioTransport
from dxband.creation.package_validator import SongPackage
from dxband.models.chord import ChordTimeline
from dxband.models.lyric import LyricsDocument
from dxband.models.melody import MelodyDocument
from dxband.ui.dialogs.chord_edit_dialog import ChordEditDialog
from dxband.ui.dialogs.lyric_review_dialog import (
    LyricReviewDialog,
    LyricReviewResult,
)
from dxband.ui.page_layout import set_button_icon
from dxband.ui.public_messages import public_message
from dxband.ui.widgets.analysis_progress import analysis_progress


@dataclass(frozen=True, slots=True)
class SongEditResult:
    lyrics: LyricReviewResult
    chords: ChordTimeline | None
    melody: MelodyDocument | None = None


class SongEditDialog(QDialog):
    saved = Signal(object)
    lyric_timing_reanalysis_requested = Signal()
    full_reanalysis_requested = Signal()

    def __init__(
        self,
        package: SongPackage,
        player: AudioTransport,
        chord_mode: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.package = package
        self.player = player
        self._reanalyzed_melody: MelodyDocument | None = None
        self.setObjectName("songEditDialog")
        self.setWindowTitle(f"修改歌曲 · {package.config.title}")
        self.setModal(False)
        self.setMinimumSize(1280, 700)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.resize(min(1720, area.width() - 40), min(900, area.height() - 40))
        else:
            self.resize(1720, 900)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        heading = QLabel("修改歌曲", self)
        heading.setObjectName("pageTitle")
        root.addWidget(heading)
        musical = package.config.musical
        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("songEditTabs")
        self.lyric_editor = LyricReviewDialog(
            document=package.lyrics,
            duration_ms=package.config.duration_ms,
            title=package.config.title,
            artist=package.config.artist,
            original_key=musical.original_key,
            bpm=musical.bpm,
            beat_times_ms=musical.beat_times_ms,
            downbeat_times_ms=musical.downbeat_times_ms,
            beats_per_bar=musical.beats_per_bar,
            player=player,
            require_confirmation=False,
            metadata_editable=True,
            show_metadata_panel=False,
            show_analysis_controls=False,
            embedded=True,
            parent=self.tabs,
        )
        self.chord_editor = ChordEditDialog(
            timeline=package.chords,
            document=package.lyrics,
            title=package.config.title,
            original_key=musical.original_key,
            duration_ms=package.config.duration_ms,
            initial_mode=chord_mode,
            show_analysis_controls=True,
            embedded=True,
            parent=self.tabs,
            beat_times_ms=musical.beat_times_ms,
            downbeat_times_ms=musical.downbeat_times_ms,
            beats_per_bar=musical.beats_per_bar,
        )
        self.chord_editor.lyrics_changed.connect(self._apply_beat_lyrics)
        self.metadata_panel = QFrame(self)
        self.metadata_panel.setObjectName("editorPanel")
        metadata_row = QHBoxLayout(self.metadata_panel)
        metadata_row.setContentsMargins(16, 12, 16, 12)
        metadata_row.setSpacing(10)
        metadata_label = QLabel("歌曲信息和节奏", self.metadata_panel)
        metadata_label.setObjectName("sectionLabel")
        metadata_row.addWidget(metadata_label)
        metadata_row.addWidget(QLabel("歌名", self.metadata_panel))
        metadata_row.addWidget(self.lyric_editor.title_edit, 2)
        metadata_row.addWidget(QLabel("歌手", self.metadata_panel))
        metadata_row.addWidget(self.lyric_editor.artist_edit, 1)
        metadata_row.addWidget(QLabel("原Key", self.metadata_panel))
        metadata_row.addWidget(self.lyric_editor.original_key_edit)
        metadata_row.addWidget(QLabel("BPM", self.metadata_panel))
        metadata_row.addWidget(self.lyric_editor.bpm_spin)
        metadata_row.addStretch(1)
        self.reanalyze_button = QPushButton("重新分析全部", self.metadata_panel)
        set_button_icon(self.reanalyze_button, "analyze.svg")
        self.reanalyze_button.setToolTip("重新分析节奏、Key、和弦及歌词字词时间")
        self.reanalyze_button.clicked.connect(self._reanalyze_all)
        metadata_row.addWidget(self.reanalyze_button)
        self.analysis_progress = analysis_progress(self.metadata_panel)
        metadata_row.addWidget(self.analysis_progress)
        root.addWidget(self.metadata_panel)

        self.preview_panel = self.lyric_editor.preview_panel
        lyric_layout = self.lyric_editor.layout()
        if lyric_layout is not None:
            lyric_layout.removeWidget(self.preview_panel)
        self.preview_panel.setParent(self)
        root.addWidget(self.preview_panel)

        self.tabs.addTab(self.lyric_editor, "歌词")
        self.tabs.addTab(self.chord_editor, "和弦")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.lyric_editor.preview_position_changed.connect(self._preview_position_changed)
        self.lyric_editor.play_button.clicked.connect(
            self.chord_editor.resume_position_follow
        )
        self.lyric_editor.position_slider.sliderPressed.connect(
            self.chord_editor.resume_position_follow
        )
        root.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel("", self)
        self.status_label.setObjectName("statusBar")
        self.status_label.hide()
        footer.addWidget(self.status_label, 1)
        footer.addStretch(1)
        close_button = QPushButton("取消", self)
        set_button_icon(close_button, "remove.svg")
        close_button.clicked.connect(self.reject)
        footer.addWidget(close_button)
        self.save_button = QPushButton("保存修改", self)
        set_button_icon(self.save_button, "save.svg")
        self.save_button.setProperty("role", "primary")
        self.save_button.clicked.connect(self._save)
        footer.addWidget(self.save_button)
        root.addLayout(footer)

        self._music_running = False
        self._chord_running = False
        self._lyrics_running = False
        self.chord_editor.status_changed.connect(self.show_status)
        self.lyric_editor.analysis_running_changed.connect(self._set_music_running)
        self.chord_editor.analysis_running_changed.connect(self._set_chord_running)

    def show_status(self, message: str) -> None:
        self.status_label.setText(public_message(message, "歌曲处理失败，请重试"))
        self.status_label.setVisible(bool(message))

    def _reanalyze_all(self) -> None:
        if self._music_running or self._chord_running or self._lyrics_running:
            return
        self._lyrics_running = True
        self._update_save_state()
        self.show_status("正在重新分析节奏、KEY、和弦和歌词字词时间……")
        self._sync_chord_context()
        self.full_reanalysis_requested.emit()

    def apply_full_reanalysis(
        self, score: object, lyrics: LyricsDocument, melody: MelodyDocument,
    ) -> None:
        from dxband.analysis.sheetsage2_package import SheetSage2Analysis

        if not isinstance(score, SheetSage2Analysis):
            self.show_lyric_timing_analysis_error("分析结果无效")
            return
        self.lyric_editor.apply_music_analysis(
            score.original_key, score.bpm, tuple(score.beat_times_ms),
            tuple(score.downbeat_times_ms), score.beats_per_bar,
        )
        self.chord_editor.apply_reanalysis(score.chords)
        self._reanalyzed_melody = melody
        self.apply_lyric_timing_analysis(lyrics)

    def show_full_reanalysis_error(self, message: str) -> None:
        self._lyrics_running = False
        self._update_save_state()
        self.show_status(f"重新分析失败：{message}")

    def apply_lyric_timing_analysis(self, aligned: LyricsDocument) -> None:
        try:
            count = sum(bool(line.words) for line in aligned.lines)
            if count == 0:
                status = "未能生成可靠的逐字时间，请检查歌词和人声轨"
            else:
                status = (
                    f"已将 {count}/{len(aligned.lines)} 行歌词按人声对齐；"
                    "请试听核对后保存修改"
                )
            self.lyric_editor._push_change("对齐歌词时间", aligned)
            self._sync_chord_context()
            self.show_status(status)
        except Exception as exc:
            self.show_status(f"字词时间对齐失败：{exc}")
        finally:
            self._lyrics_running = False
            self._update_save_state()

    def show_lyric_timing_analysis_error(self, message: str) -> None:
        self._lyrics_running = False
        self._update_save_state()
        self.show_status(f"字词时间识别失败：{message}")

    def _sync_chord_context(self) -> None:
        title = self.lyric_editor.title_edit.text().strip() or self.package.config.title
        document = self.lyric_editor.document.model_copy(update={"title": title})
        self.chord_editor.update_context(
            document,
            title,
            self.lyric_editor.original_key_edit.text().strip(),
            beat_times_ms=self.lyric_editor._beat_times_ms,
            downbeat_times_ms=self.lyric_editor._downbeat_times_ms,
            beats_per_bar=self.lyric_editor._beats_per_bar,
        )

    def _apply_beat_lyrics(self, document: LyricsDocument) -> None:
        if document != self.lyric_editor.document:
            self.lyric_editor._push_change("按拍修改歌词", document)

    def _tab_changed(self, index: int) -> None:
        if index != 1:
            return
        self._sync_chord_context()
        position_ms = self.player.position_ms()
        QTimer.singleShot(
            0,
            self.chord_editor,
            lambda: self.chord_editor.set_position_ms(position_ms, force_reveal=True),
        )

    def _preview_position_changed(self, position_ms: int) -> None:
        if self.tabs.currentIndex() == 1:
            self.chord_editor.set_position_ms(position_ms)

    def _set_music_running(self, running: bool) -> None:
        self._music_running = running
        if not running:
            self._sync_chord_context()
        self._update_save_state()

    def _set_chord_running(self, running: bool) -> None:
        self._chord_running = running
        self._update_save_state()

    def _update_save_state(self) -> None:
        running = self._music_running or self._chord_running or self._lyrics_running
        self.save_button.setEnabled(not running)
        self.reanalyze_button.setEnabled(not running)
        self.reanalyze_button.setText("分析中…" if running else "重新分析全部")
        self.analysis_progress.setVisible(running)

    def _save(self) -> None:
        if not self.save_button.isEnabled():
            return
        focused = self.focusWidget()
        if isinstance(focused, QLineEdit) and focused.objectName() in {
            "chordInlineEditor", "lyricBeatEditor"
        }:
            focused.clearFocus()
        if not self.chord_editor.commit_pending_lyric_inputs():
            self.tabs.setCurrentIndex(1)
            return
        try:
            lyrics = self.lyric_editor.review_result()
        except ValueError as exc:
            self.tabs.setCurrentIndex(0)
            self.show_status(str(exc))
            return
        chords = self.chord_editor.timeline
        changed_chords = chords if chords != (self.package.chords or ChordTimeline()) else None
        if changed_chords is not None:
            if any(
                segment.end_ms > self.package.config.duration_ms
                for segment in changed_chords.segments
            ):
                self.tabs.setCurrentIndex(1)
                self.show_status("存在超出歌曲时长的和弦")
                return
            if not changed_chords.segments:
                answer = QMessageBox.question(
                    self,
                    "保存空和弦表",
                    "当前和弦表为空，确定保存吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
        self.saved.emit(SongEditResult(
            lyrics=lyrics, chords=changed_chords,
            melody=self._reanalyzed_melody,
        ))

    def closeEvent(self, event: QCloseEvent) -> None:
        self.player.pause()
        super().closeEvent(event)
