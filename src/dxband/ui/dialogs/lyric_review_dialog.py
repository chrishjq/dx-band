# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QShowEvent, QUndoStack
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dxband.audio.transport import AudioTransport
from dxband.constants import TrackKind
from dxband.lyrics.autosave import LyricsAutosaver
from dxband.lyrics.editor_commands import (
    LyricsEditError,
    LyricsEditor,
    ReplaceLyricsCommand,
)
from dxband.lyrics.timeline import LyricTimeline
from dxband.models.lyric import LyricsDocument
from dxband.ui.page_layout import set_button_icon
from dxband.ui.public_messages import public_message
from dxband.ui.widgets.analysis_progress import analysis_progress
from dxband.utils.time_format import format_time_ms, parse_time_ms


@dataclass(frozen=True, slots=True)
class LyricReviewResult:
    document: LyricsDocument
    title: str
    artist: str
    original_key: str
    bpm: int
    beat_times_ms: tuple[int, ...]
    downbeat_times_ms: tuple[int, ...]
    beats_per_bar: int | None


class LyricReviewDialog(QDialog):
    lyrics_confirmed = Signal(object)
    music_reanalysis_requested = Signal()
    analysis_running_changed = Signal(bool)
    preview_position_changed = Signal(int)

    def __init__(
        self,
        document: LyricsDocument,
        duration_ms: int,
        title: str,
        artist: str = "",
        original_key: str = "",
        bpm: int = 0,
        beat_times_ms: tuple[int, ...] | list[int] = (),
        downbeat_times_ms: tuple[int, ...] | list[int] = (),
        beats_per_bar: int | None = None,
        autosave_path: Path | None = None,
        player: AudioTransport | None = None,
        confirmation_text: str = "我已试听并核对歌词",
        confirm_button_text: str = "确认歌词并完成创建",
        require_confirmation: bool = True,
        metadata_editable: bool = False,
        show_metadata_panel: bool = True,
        show_analysis_controls: bool = True,
        embedded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if duration_ms <= 0:
            raise ValueError("歌词校对缺少有效歌曲时长")
        self.document = document
        self.duration_ms = duration_ms
        self.player = player
        self.require_confirmation = require_confirmation
        self.embedded = embedded
        self.show_analysis_controls = show_analysis_controls
        self._beat_times_ms = tuple(beat_times_ms)
        self._downbeat_times_ms = tuple(downbeat_times_ms)
        self._beats_per_bar = beats_per_bar
        self.editor = LyricsEditor(duration_ms)
        self.autosaver = (
            LyricsAutosaver(autosave_path, parent=self) if autosave_path is not None else None
        )
        self.timeline = LyricTimeline(document)
        self._row_by_line_id = {line.id: index for index, line in enumerate(document.lines)}
        self.undo_stack = QUndoStack(self)
        self._refreshing = False
        self._dragging_slider = False
        self._last_follow_position_ms: int | None = None
        self._active_line_id = ""
        self._loop_row: int | None = None
        self._preview_playing = False
        self._lyric_search_matches: list[int] = []
        self._lyric_search_index = -1
        self.setWindowTitle(f"歌词试听校对 - {title}")
        self.resize(1240, 820)
        self.setModal(False)
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)

        root = QVBoxLayout(self)
        root.setContentsMargins(16 if embedded else 24, 16, 16 if embedded else 24, 14)
        root.setSpacing(12)
        if not embedded:
            heading = (
                "歌曲信息与歌词校对"
                if metadata_editable
                else (f"{title} - {artist}" if artist else title)
            )
            heading_label = QLabel(heading, self)
            heading_label.setObjectName("pageTitle")
            if not metadata_editable:
                heading_label.setProperty("i18n_skip", True)
            root.addWidget(heading_label)
        self.title_edit = QLineEdit(title, self)
        self.artist_edit = QLineEdit(artist, self)
        self.original_key_edit = QLineEdit(original_key, self)
        self.original_key_edit.setMaximumWidth(100)
        self.bpm_spin = QSpinBox(self)
        self.bpm_spin.setRange(0, 400)
        self.bpm_spin.setSingleStep(1)
        self.bpm_spin.setSpecialValueText("未设置")
        self.bpm_spin.setValue(bpm)
        self.bpm_spin.setMaximumWidth(120)
        self.reanalyze_music_button = QPushButton("重新分析节奏和KEY", self)
        set_button_icon(self.reanalyze_music_button, "refresh.svg")
        self.reanalyze_music_button.clicked.connect(self._request_music_reanalysis)
        self.music_analysis_progress = analysis_progress(self)
        if metadata_editable and show_metadata_panel:
            metadata_panel = QFrame(self)
            metadata_panel.setObjectName("editorPanel")
            metadata_layout = QVBoxLayout(metadata_panel)
            metadata_layout.setContentsMargins(16, 12, 16, 14)
            metadata_layout.setSpacing(8)
            metadata_label = QLabel("歌曲信息与节奏", metadata_panel)
            metadata_label.setObjectName("sectionLabel")
            metadata_layout.addWidget(metadata_label)
            metadata_row = QHBoxLayout()
            metadata_row.setSpacing(10)
            metadata_row.addWidget(QLabel("歌名", self))
            metadata_row.addWidget(self.title_edit, 2)
            metadata_row.addWidget(QLabel("歌手", self))
            metadata_row.addWidget(self.artist_edit, 1)
            metadata_row.addWidget(QLabel("原Key", self))
            metadata_row.addWidget(self.original_key_edit)
            metadata_row.addWidget(QLabel("BPM", self))
            metadata_row.addWidget(self.bpm_spin)
            self.bpm_spin.setEnabled(False)
            self.bpm_spin.setToolTip("原 Key、BPM 和逐拍时间表由音乐分析生成；如有错误，请重新分析")
            metadata_row.addWidget(self.reanalyze_music_button)
            metadata_row.addWidget(self.music_analysis_progress)
            metadata_layout.addLayout(metadata_row)
            root.addWidget(metadata_panel)
        elif not metadata_editable:
            for editor in (
                self.title_edit,
                self.artist_edit,
                self.original_key_edit,
                self.bpm_spin,
            ):
                editor.hide()
            self.reanalyze_music_button.hide()
        if not show_analysis_controls:
            self.reanalyze_music_button.hide()
            self.music_analysis_progress.hide()
        self.preview_panel = QFrame(self)
        self.preview_panel.setObjectName("editorPanel")
        preview_layout = QVBoxLayout(self.preview_panel)
        preview_layout.setContentsMargins(16, 12, 16, 12)
        preview_layout.setSpacing(10)
        preview_label = QLabel("音轨试听", self.preview_panel)
        preview_label.setObjectName("sectionLabel")
        preview_layout.addWidget(preview_label)
        preview_layout.addLayout(self._build_transport())
        preview_layout.addLayout(self._build_track_controls())
        root.addWidget(self.preview_panel)

        self.current_lyric_label = QLabel("当前歌词：—", self)
        self.current_lyric_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_lyric_label.setObjectName("currentLyric")
        self.current_lyric_label.setWordWrap(True)
        root.addWidget(self.current_lyric_label)
        self.current_lyric_label.setVisible(not embedded)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_row.addWidget(QLabel("搜索歌词", self))
        self.lyric_search_edit = QLineEdit(self)
        self.lyric_search_edit.setObjectName("lyricSearchEdit")
        self.lyric_search_edit.setPlaceholderText("输入歌词关键词")
        self.lyric_search_edit.setClearButtonEnabled(True)
        self.lyric_search_edit.setMaximumWidth(360)
        search_row.addWidget(self.lyric_search_edit)
        self.lyric_search_previous_button = QPushButton("上一处", self)
        set_button_icon(self.lyric_search_previous_button, "previous.svg")
        self.lyric_search_next_button = QPushButton("下一处", self)
        set_button_icon(self.lyric_search_next_button, "next.svg")
        search_row.addWidget(self.lyric_search_previous_button)
        search_row.addWidget(self.lyric_search_next_button)
        self.lyric_search_result_label = QLabel("", self)
        self.lyric_search_result_label.setObjectName("lyricSearchResult")
        search_row.addWidget(self.lyric_search_result_label)
        search_row.addStretch(1)
        root.addLayout(search_row)
        self.lyric_search_edit.textChanged.connect(self._update_lyric_search)
        self.lyric_search_edit.returnPressed.connect(self._next_lyric_search_match)
        self.lyric_search_previous_button.clicked.connect(self._previous_lyric_search_match)
        self.lyric_search_next_button.clicked.connect(self._next_lyric_search_match)

        self.table = QTableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["开始时间", "结束时间", "歌词"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._item_changed)
        self.table.cellClicked.connect(self._seek_to_row)
        self.table.setObjectName("songEditLyricTable")
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnWidth(0, 132)
        self.table.setColumnWidth(1, 132)
        root.addWidget(self.table, 1)
        self.edit_panel = QFrame(self)
        self.edit_panel.setObjectName("editorPanel")
        edit_layout = QHBoxLayout(self.edit_panel)
        edit_layout.setContentsMargins(16, 10, 16, 10)
        edit_layout.setSpacing(8)
        self.edit_controls_layout = self._build_edit_controls()
        edit_layout.addLayout(self.edit_controls_layout)
        root.addWidget(self.edit_panel)

        footer = QHBoxLayout()
        status_text = "请试听并核对歌词" if require_confirmation else ""
        self.status_label = QLabel(status_text, self)
        self.status_label.setObjectName("statusBar")
        self.status_label.setVisible(bool(status_text))
        self.confirm_check = QCheckBox(confirmation_text, self)
        self.confirm_button = QPushButton(confirm_button_text, self)
        set_button_icon(self.confirm_button, "save.svg")
        self.confirm_button.setProperty("role", "primary")
        self.confirm_button.clicked.connect(self._confirm)
        footer.addWidget(self.status_label, 1)
        if require_confirmation:
            footer.addWidget(self.confirm_check)
        else:
            self.confirm_check.hide()
        if not embedded:
            footer.addWidget(self.confirm_button)
        else:
            self.confirm_button.hide()
        root.addLayout(footer)

        self.position_timer = QTimer(self)
        self.position_timer.setInterval(33)
        self.position_timer.timeout.connect(self._refresh_position)
        self.position_timer.start()
        self._render_document()
        self._configure_preview_defaults()

    def _show_status(self, message: str) -> None:
        self.status_label.setText(public_message(message, "歌词处理失败，请重试"))
        self.status_label.setVisible(bool(message))

    def _build_transport(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        buttons = QHBoxLayout()
        position = QHBoxLayout()
        self.play_button = QPushButton("播放", self)
        set_button_icon(self.play_button, "play.svg")
        self.play_button.setProperty("role", "play")
        self.stop_button = QPushButton("停止", self)
        set_button_icon(self.stop_button, "stop.svg")
        back_second = QPushButton("-1秒", self)
        set_button_icon(back_second, "rewind.svg")
        forward_second = QPushButton("+1秒", self)
        set_button_icon(forward_second, "forward.svg")
        back_precise = QPushButton("-100ms", self)
        set_button_icon(back_precise, "rewind.svg")
        forward_precise = QPushButton("+100ms", self)
        set_button_icon(forward_precise, "forward.svg")
        self.loop_check = QCheckBox("循环当前行", self)
        self.loop_check.toggled.connect(self._loop_toggled)
        self.position_label = QLabel("00:00.000 / 00:00.000", self)
        self.position_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.position_slider.setRange(0, self.duration_ms)
        self.position_slider.sliderPressed.connect(self._slider_pressed)
        self.position_slider.sliderReleased.connect(self._slider_released)
        self.play_button.clicked.connect(self._toggle_playback)
        self.stop_button.clicked.connect(self._stop_playback)
        back_second.clicked.connect(lambda: self._relative_seek(-1000))
        forward_second.clicked.connect(lambda: self._relative_seek(1000))
        back_precise.clicked.connect(lambda: self._relative_seek(-100))
        forward_precise.clicked.connect(lambda: self._relative_seek(100))
        for button in (
            self.play_button,
            self.stop_button,
            back_second,
            forward_second,
            back_precise,
            forward_precise,
        ):
            button.setEnabled(self.player is not None)
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.loop_check)
        position.addWidget(self.position_slider, 1)
        position.addWidget(self.position_label)
        layout.addLayout(buttons)
        layout.addLayout(position)
        return layout

    def _build_track_controls(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(QLabel("试听轨道：", self))
        self.mute_checks: dict[TrackKind, QCheckBox] = {}
        labels = {
            TrackKind.VOCALS: "人声",
            TrackKind.DRUMS: "鼓组",
            TrackKind.BASS: "贝斯",
            TrackKind.GUITAR: "吉他",
            TrackKind.PIANO: "钢琴",
            TrackKind.OTHER: "其他",
        }
        available_tracks = (
            self.player.available_tracks()
            if self.player is not None and hasattr(self.player, "available_tracks")
            else frozenset(TrackKind)
        )
        for track in TrackKind:
            check = QCheckBox(f"静音{labels[track]}", self)
            check.setProperty("track", track.value)
            check.setChecked(False)
            check.setEnabled(self.player is not None and track in available_tracks)
            check.setVisible(track in available_tracks)
            check.toggled.connect(
                lambda muted, current_track=track: self._set_track_muted(current_track, muted)
            )
            self.mute_checks[track] = check
            layout.addWidget(check)
        layout.addStretch(1)
        return layout

    def _build_edit_controls(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        controls: list[tuple[str, str, object]] = [
            ("拆分行", "edit.svg", self._split_selected),
            ("合并上一行", "arrow-up.svg", self._merge_previous),
            ("合并下一行", "arrow-down.svg", self._merge_next),
        ]
        for text, icon_name, callback in controls:
            button = QPushButton(text, self)
            set_button_icon(button, icon_name)
            button.clicked.connect(callback)
            layout.addWidget(button)

        self.offset_spin = QSpinBox(self)
        self.offset_spin.setRange(-self.duration_ms, self.duration_ms)
        self.offset_spin.setSuffix(" ms")
        self.offset_spin.setToolTip("正数使歌词延后，负数使歌词提前")
        offset_from_selected_button = QPushButton("从选中行起偏移", self)
        set_button_icon(offset_from_selected_button, "forward.svg")
        offset_from_selected_button.setToolTip("将选中行及其后的全部歌词整体偏移")
        offset_from_selected_button.clicked.connect(self._apply_offset_from_selected)
        self.undo_button = QPushButton("撤销", self)
        set_button_icon(self.undo_button, "undo.svg")
        self.redo_button = QPushButton("重做", self)
        set_button_icon(self.redo_button, "redo.svg")
        self.undo_button.clicked.connect(self.undo_stack.undo)
        self.redo_button.clicked.connect(self.undo_stack.redo)
        layout.addSpacing(12)
        layout.addWidget(QLabel("偏移量", self))
        layout.addWidget(self.offset_spin)
        layout.addWidget(offset_from_selected_button)
        layout.addSpacing(12)
        layout.addWidget(self.undo_button)
        layout.addWidget(self.redo_button)
        layout.addStretch(1)
        return layout

    def _configure_preview_defaults(self) -> None:
        if self.player is None:
            self._show_status("音频引擎尚未加载，可先编辑歌词")
            return
        state_changed = getattr(self.player, "state_changed", None)
        connect = getattr(state_changed, "connect", None)
        if callable(connect):
            connect(self._playback_state_changed)
        available_tracks = (
            self.player.available_tracks()
            if hasattr(self.player, "available_tracks")
            else frozenset(TrackKind)
        )
        for track in TrackKind:
            if track in available_tracks:
                self.player.set_track_muted(track, False)

    def _playback_state_changed(self, state: object) -> None:
        value = getattr(state, "value", state)
        if value == "playing":
            self._set_preview_playing(True)
        elif value in {"paused", "stopped", "ended", "error", "empty"}:
            self._set_preview_playing(False)

    def _render_document(self) -> None:
        self._refreshing = True
        selected = self.table.currentRow() if hasattr(self, "table") else 0
        self.table.setRowCount(len(self.document.lines))
        for row, line in enumerate(self.document.lines):
            self.table.setItem(row, 0, QTableWidgetItem(format_time_ms(line.start_ms)))
            self.table.setItem(row, 1, QTableWidgetItem(format_time_ms(line.end_ms)))
            self.table.setItem(row, 2, QTableWidgetItem(line.text))
        if self.document.lines:
            self.table.selectRow(max(0, min(selected, len(self.document.lines) - 1)))
        self._refreshing = False
        self._update_lyric_search(reveal=False)

    def _update_lyric_search(
        self,
        _text: str = "",
        *,
        reveal: bool = True,
    ) -> None:
        query = self.lyric_search_edit.text().strip().casefold()
        self._lyric_search_matches = (
            [row for row, line in enumerate(self.document.lines) if query in line.text.casefold()]
            if query
            else []
        )
        self._lyric_search_index = 0 if self._lyric_search_matches else -1
        self._update_lyric_search_controls()
        if reveal and self._lyric_search_index >= 0:
            self._reveal_lyric_search_match()

    def _update_lyric_search_controls(self) -> None:
        count = len(self._lyric_search_matches)
        enabled = count > 0
        self.lyric_search_previous_button.setEnabled(enabled)
        self.lyric_search_next_button.setEnabled(enabled)
        if not self.lyric_search_edit.text().strip():
            result = ""
        elif not enabled:
            result = "无匹配"
        else:
            result = f"{self._lyric_search_index + 1}/{count}"
        self.lyric_search_result_label.setText(result)

    def _reveal_lyric_search_match(self) -> None:
        if self._lyric_search_index < 0:
            return
        row = self._lyric_search_matches[self._lyric_search_index]
        self.table.setCurrentCell(row, 2)
        item = self.table.item(row, 2)
        if item is not None:
            self.table.scrollToItem(item)
        self._update_lyric_search_controls()

    def _next_lyric_search_match(self) -> None:
        if not self._lyric_search_matches:
            return
        self._lyric_search_index = (self._lyric_search_index + 1) % len(self._lyric_search_matches)
        self._reveal_lyric_search_match()

    def _previous_lyric_search_match(self) -> None:
        if not self._lyric_search_matches:
            return
        self._lyric_search_index = (self._lyric_search_index - 1) % len(self._lyric_search_matches)
        self._reveal_lyric_search_match()

    def _apply_document(self, document: LyricsDocument) -> None:
        self.document = document
        self.timeline = LyricTimeline(document)
        self._row_by_line_id = {line.id: index for index, line in enumerate(document.lines)}
        self._active_line_id = ""
        self._last_follow_position_ms = None
        self._render_document()
        if self.autosaver is not None:
            self.autosaver.schedule(document)
            self._show_status("草稿已修改，将自动保存")
        else:
            self._show_status("歌词已修改，保存后写入歌曲库")

    def _push_change(self, description: str, after: LyricsDocument) -> None:
        self.undo_stack.push(
            ReplaceLyricsCommand(description, self.document, after, self._apply_document)
        )

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._refreshing:
            return
        row = item.row()
        try:
            if item.column() == 2:
                after = self.editor.replace_text(self.document, row, item.text())
                self._push_change("修改歌词文本", after)
                return
            start_item = self.table.item(row, 0)
            end_item = self.table.item(row, 1)
            if start_item is None or end_item is None:
                raise LyricsEditError("歌词时间单元格缺失")
            start_ms = parse_time_ms(start_item.text())
            end_ms = parse_time_ms(end_item.text())
            after = self.editor.replace_timing(self.document, row, start_ms, end_ms)
            self._push_change("修改歌词时间", after)
        except (LyricsEditError, ValueError) as exc:
            self._show_status(str(exc))
            self._render_document()

    def _selected_row(self) -> int:
        row = self.table.currentRow()
        if row < 0:
            raise LyricsEditError("请先选择歌词行")
        return row

    def _split_selected(self) -> None:
        self._run_selected_edit("拆分歌词行", self.editor.split_line)

    def _merge_previous(self) -> None:
        self._run_selected_edit("合并上一行", self.editor.merge_with_previous)

    def _merge_next(self) -> None:
        self._run_selected_edit("合并下一行", self.editor.merge_with_next)

    def _run_selected_edit(self, description: str, operation: object) -> None:
        if not callable(operation):
            return
        try:
            after = operation(self.document, self._selected_row())
            self._push_change(description, after)
        except LyricsEditError as exc:
            self._show_status(str(exc))

    def _apply_offset_from_selected(self) -> None:
        try:
            row = self._selected_row()
            offset_ms = self.offset_spin.value()
            if offset_ms == 0:
                self._show_status("请输入非零偏移量；正数后移，负数前移")
                return
            after = self.editor.apply_offset_from_row(self.document, row, offset_ms)
            self._push_change("从选中行起应用时间偏移", after)
            self.offset_spin.setValue(0)
            direction = "后移" if offset_ms > 0 else "前移"
            self._show_status(f"已将第 {row + 1} 行及后续歌词整体{direction} {abs(offset_ms)} ms")
        except LyricsEditError as exc:
            self._show_status(str(exc))

    def _seek_to_row(self, row: int, _column: int) -> None:
        if self.player is None or not 0 <= row < len(self.document.lines):
            return
        if self.loop_check.isChecked():
            self._loop_row = row
        self.player.seek_ms(self.document.lines[row].start_ms)

    def _loop_toggled(self, checked: bool) -> None:
        row = self.table.currentRow()
        self._loop_row = row if checked and 0 <= row < len(self.document.lines) else None

    def _relative_seek(self, delta_ms: int) -> None:
        if self.player is None:
            return
        target_ms = max(0, min(self.player.duration_ms(), self.player.position_ms() + delta_ms))
        self.player.seek_ms(target_ms)

    def _slider_pressed(self) -> None:
        self._dragging_slider = True

    def _slider_released(self) -> None:
        self._dragging_slider = False
        if self.player is not None:
            self.player.seek_ms(self.position_slider.value())

    def _set_preview_playing(self, playing: bool) -> None:
        self._preview_playing = playing
        self.play_button.setText("暂停" if playing else "播放")
        set_button_icon(self.play_button, "pause.svg" if playing else "play.svg")

    def _toggle_playback(self) -> None:
        if self.player is None:
            return
        if self._preview_playing:
            self.player.pause()
            self._set_preview_playing(False)
        else:
            self.player.play()
            self._set_preview_playing(True)

    def _stop_playback(self) -> None:
        if self.player is None:
            return
        self.player.stop()
        self._set_preview_playing(False)

    def _set_track_muted(self, track: TrackKind, muted: bool) -> None:
        if self.player is not None:
            self.player.set_track_muted(track, muted)

    def _refresh_position(self) -> None:
        if self.player is None:
            return
        position_ms = self.player.position_ms()
        if self.loop_check.isChecked() and self._loop_row is not None:
            if 0 <= self._loop_row < len(self.document.lines):
                loop_line = self.document.lines[self._loop_row]
                if position_ms < loop_line.start_ms or position_ms >= loop_line.end_ms:
                    self.player.seek_ms(loop_line.start_ms)
                    self.player.play()
                    self._set_preview_playing(True)
                    position_ms = loop_line.start_ms
            else:
                self._loop_row = None
        if not self._dragging_slider:
            self.position_slider.setValue(position_ms)
        self.position_label.setText(
            f"{format_time_ms(position_ms)} / {format_time_ms(self.player.duration_ms())}"
        )
        self.preview_position_changed.emit(position_ms)
        if position_ms != self._last_follow_position_ms:
            self._last_follow_position_ms = position_ms
            self._follow_current_lyric(position_ms)

    def _follow_current_lyric(self, position_ms: int) -> None:
        context = self.timeline.context_at(position_ms)
        current = context.current
        if current is None:
            next_text = context.next.text if context.next is not None else ""
            suffix = f"（下一句：{next_text}）" if next_text else ""
            self.current_lyric_label.setText(f"当前歌词：间奏{suffix}")
            self._active_line_id = ""
            return
        self.current_lyric_label.setText(f"当前歌词：{current.text}")
        if current.id == self._active_line_id:
            return
        self._active_line_id = current.id
        row = self._row_by_line_id.get(current.id)
        if row is None:
            return
        self.table.selectRow(row)
        item = self.table.item(row, 2)
        if item is not None:
            self.table.scrollToItem(item)

    def _request_music_reanalysis(self) -> None:
        self._set_music_analysis_running(True)
        self._show_status("正在重新分析原 Key、BPM 和节拍表……")
        self.music_reanalysis_requested.emit()

    def _set_music_analysis_running(self, running: bool) -> None:
        self.reanalyze_music_button.setEnabled(not running)
        self.reanalyze_music_button.setText("分析中…" if running else "重新分析节奏和KEY")
        self.music_analysis_progress.setVisible(running and self.show_analysis_controls)
        self.confirm_button.setEnabled(not running)
        self.analysis_running_changed.emit(running)

    def apply_music_analysis(
        self,
        original_key: str,
        bpm: int,
        beat_times_ms: tuple[int, ...],
        downbeat_times_ms: tuple[int, ...],
        beats_per_bar: int,
    ) -> None:
        """应用音乐属性分析结果，保存时一并写入歌曲包。"""
        self.original_key_edit.setText(original_key)
        self.bpm_spin.setValue(bpm)
        self._beat_times_ms = beat_times_ms
        self._downbeat_times_ms = downbeat_times_ms
        self._beats_per_bar = beats_per_bar
        self._set_music_analysis_running(False)
        self._show_status(
            "音乐属性分析完成（尚未保存）："
            f"原 Key {original_key}，{bpm} BPM，共 {len(beat_times_ms)} 个拍点，"
            f"每小节 {beats_per_bar} 拍"
        )

    def show_music_analysis_error(self, message: str) -> None:
        self._set_music_analysis_running(False)
        self._show_status(message)

    def review_result(self) -> LyricReviewResult:
        if self.require_confirmation and not self.confirm_check.isChecked():
            raise LyricsEditError("请先勾选“我已试听并核对歌词”")
        title = self.title_edit.text().strip()
        artist = self.artist_edit.text().strip()
        original_key = self.original_key_edit.text().strip()
        bpm = self.bpm_spin.value()
        if not title:
            raise LyricsEditError("歌名不能为空")
        if bool(original_key) != (bpm > 0):
            raise LyricsEditError("原Key 和 BPM 需要同时填写，或同时留空")
        payload = self.document.model_dump(mode="python")
        payload["title"] = title
        document = LyricsDocument.model_validate(payload, strict=True)
        if any(line.end_ms > self.duration_ms for line in document.lines):
            raise LyricsEditError("存在超出歌曲时长的歌词")
        return LyricReviewResult(
            document=document,
            title=title,
            artist=artist,
            original_key=original_key,
            bpm=bpm,
            beat_times_ms=self._beat_times_ms,
            downbeat_times_ms=self._downbeat_times_ms,
            beats_per_bar=self._beats_per_bar,
        )

    def _confirm(self) -> None:
        try:
            result = self.review_result()
        except (ValueError, LyricsEditError) as exc:
            QMessageBox.warning(
                self, "歌词校验失败", public_message(str(exc), "请检查歌词内容后重试")
            )
            return
        if self.autosaver is not None:
            self.autosaver.flush()
        self.lyrics_confirmed.emit(result)
        if not self.embedded:
            self.accept()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.table.setFocus(Qt.FocusReason.OtherFocusReason)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.autosaver is not None:
            self.autosaver.flush()
        if self.player is not None:
            self.player.pause()
        super().closeEvent(event)
