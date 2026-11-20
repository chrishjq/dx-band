# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dxband.creation.input_validator import SUPPORTED_SOURCE_AUDIO_EXTENSIONS
from dxband.ui.public_messages import creation_error_message, public_message

TERMINAL_PROGRESS_PATTERN = re.compile(r"(?P<percent>\d{1,3})%\|[^\r\n]*\|")


class PathInput(QWidget):
    def __init__(self, caption: str, file_filter: str, optional: bool = False) -> None:
        super().__init__()
        self.caption = caption
        self.file_filter = file_filter
        self.optional = optional
        self.edit = QLineEdit(self)
        self.button = QPushButton("选择…", self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)
        self.button.clicked.connect(self._choose)

    def _choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.caption, "", self.file_filter)
        if path:
            self.edit.setText(path)

    def path(self) -> Path | None:
        value = self.edit.text().strip()
        return Path(value) if value else None


class CreateSongPage(QWidget):
    back_to_library_requested = Signal()
    start_requested = Signal(object)
    cancel_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._running = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 28, 34, 26)
        layout.setSpacing(13)
        title = QLabel("创建歌曲", self)
        title.setObjectName("pageTitle")
        title_row = QHBoxLayout()
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.back_button = QPushButton("返回歌曲库", self)
        self.back_button.clicked.connect(self.back_to_library_requested)
        title_row.addWidget(self.back_button)
        subtitle = QLabel("导入音频与歌词，生成可演出的六轨歌曲包", self)
        subtitle.setObjectName("pageSubtitle")
        layout.addLayout(title_row)
        layout.addWidget(subtitle)

        source_box = QGroupBox("歌曲信息与素材", self)
        form = QFormLayout(source_box)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        source_patterns = " ".join(f"*{suffix}" for suffix in SUPPORTED_SOURCE_AUDIO_EXTENSIONS)
        self.source_input = PathInput("选择源歌曲", f"音频文件 ({source_patterns})")
        self.lrc_input = PathInput("选择歌词", "LRC 歌词 (*.lrc)")
        self.lyrics_text_input = QPlainTextEdit(self)
        self.lyrics_text_input.setPlaceholderText("每行输入一句歌词，无需时间戳")
        self.lyrics_text_input.setMaximumHeight(120)
        self.title_edit = QLineEdit(self)
        self.artist_edit = QLineEdit(self)
        self.language_combo = QComboBox(self)
        self.language_combo.addItem("自动判断（粤语请手选）", "auto")
        self.language_combo.addItem("国语", "zh")
        self.language_combo.addItem("粤语", "yue")
        self.language_combo.addItem("英文", "en")
        form.addRow("源歌曲音频", self.source_input)
        form.addRow("LRC 歌词文件", self.lrc_input)
        form.addRow("或输入歌词文本", self.lyrics_text_input)
        form.addRow("歌曲名", self.title_edit)
        form.addRow("歌手", self.artist_edit)
        form.addRow("语言", self.language_combo)
        layout.addWidget(source_box)

        actions = QHBoxLayout()
        self.start_button = QPushButton("开始创建", self)
        self.start_button.setProperty("role", "primary")
        self.cancel_button = QPushButton("取消任务", self)
        self.cancel_button.setProperty("role", "danger")
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.start_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        process_box = QGroupBox("处理进度", self)
        process_layout = QVBoxLayout(process_box)
        self.stage_label = QLabel("阶段：等待输入", process_box)
        self.stage_label.setObjectName("stateChip")
        self.stage_label.setWordWrap(True)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        process_layout.addWidget(self.stage_label)
        process_layout.addWidget(self.progress)
        layout.addWidget(process_box)
        layout.addStretch(1)

        self.start_button.clicked.connect(self._request_start)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.source_input.edit.textChanged.connect(self._source_changed)
        self.lrc_input.edit.textChanged.connect(self._sync_lyrics_source_controls)
        self.lyrics_text_input.textChanged.connect(self._sync_lyrics_source_controls)
        self.language_combo.currentIndexChanged.connect(self._sync_lyrics_source_controls)
        self._sync_lyrics_source_controls()

    def _source_changed(self, value: str) -> None:
        if value and not self.title_edit.text().strip():
            self.title_edit.setText(Path(value).stem)

    def _sync_lyrics_source_controls(self, _value: object = "") -> None:
        self.language_combo.setEnabled(True)
        self.language_combo.setToolTip(
            "三种语言均以 LRC 或输入文本为文字依据，自动对齐歌词时间"
        )

    def _request_start(self) -> None:
        source = self.source_input.path()
        if source is None:
            self.show_error("请选择源歌曲音频")
            return
        lrc_path = self.lrc_input.path()
        lyrics_text = self.lyrics_text_input.toPlainText().strip()
        if lrc_path is None and not lyrics_text:
            self.show_error("请选择 LRC 歌词文件或输入歌词文本")
            return
        if lrc_path is not None and lyrics_text:
            self.show_error("请选择 LRC 文件或输入歌词文本，不要同时提供")
            return
        values = {
            "source_mp3": source,
            "lrc_path": lrc_path,
            "lyrics_text": lyrics_text or None,
            "title": self.title_edit.text(),
            "artist": self.artist_edit.text().strip(),
            "language": self.language_combo.currentData(),
        }
        self.start_requested.emit(values)

    def set_running(self, running: bool) -> None:
        self._running = running
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.progress.setRange(0, 0 if running else 100)
        if not running and self.progress.value() < 100:
            self.progress.setValue(0)

    def set_stage(self, message: str) -> None:
        self.stage_label.setText(f"阶段：{public_message(message, '正在处理歌曲')}")
        if self._running:
            self.progress.setRange(0, 0)

    def consume_progress_message(self, message: str) -> None:
        """从后台输出中提取百分比，不在界面显示原始日志。"""
        matches = tuple(TERMINAL_PROGRESS_PATTERN.finditer(message))
        if not matches:
            return
        percentage = int(matches[-1].group("percent"))
        self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, percentage)))

    def set_progress(self, value: float) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, round(value * 100))))

    def reset_for_next_song(self) -> None:
        """清空上一首歌曲的任务内容，并保留用户选择。"""
        self.source_input.edit.clear()
        self.lrc_input.edit.clear()
        self.lyrics_text_input.clear()
        self.title_edit.clear()
        self.artist_edit.clear()
        self.language_combo.setCurrentIndex(self.language_combo.findData("auto"))
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.set_stage("歌曲创建完成，可以创建下一首")
        self.source_input.edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def show_error(self, message: str) -> None:
        self.stage_label.setText(f"阶段：发生错误：{creation_error_message(message)}")
