# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QHideEvent, QPixmap, QShowEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dxband.audio.output_device import AudioOutputDevice
from dxband.ui.page_layout import (
    BUTTON_ROW_SPACING,
    add_page_header,
    create_page_layout,
    set_button_icon,
)
from dxband.ui.public_messages import public_message
from dxband.ui.services.audience_font_library import AudienceFontResource
from dxband.ui.services.background_video_library import BackgroundVideoResource
from dxband.ui.services.settings_service import (
    ApplicationSettings,
)


class SettingsPage(QWidget):
    save_requested = Signal(object)
    chord_backfill_requested = Signal()
    refresh_output_devices_requested = Signal()
    background_video_upload_requested = Signal(object)
    background_video_delete_requested = Signal(str)
    audience_font_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = create_page_layout(self)
        add_page_header(
            layout,
            self,
            "设置",
            "工作站、音频设备与演出显示 · 更改自动保存",
        )

        workspace = QHBoxLayout()
        workspace.setSpacing(14)

        audio_panel = QFrame(self)
        audio_panel.setObjectName("settingsPanel")
        audio_panel.setFixedWidth(350)
        audio_layout = QVBoxLayout(audio_panel)
        audio_layout.setContentsMargins(17, 16, 17, 17)
        audio_layout.setSpacing(12)
        audio_title = QLabel("通用与音频", audio_panel)
        audio_title.setObjectName("settingsPanelTitle")
        audio_subtitle = QLabel("管理本地歌曲库和监听设备", audio_panel)
        audio_subtitle.setObjectName("settingsPanelSubtitle")
        audio_layout.addWidget(audio_title)
        audio_layout.addWidget(audio_subtitle)
        audio_layout.addSpacing(7)

        library_caption = QLabel("歌曲库目录", audio_panel)
        library_caption.setObjectName("settingsFieldLabel")
        audio_layout.addWidget(library_caption)
        library_row = QHBoxLayout()
        library_row.setSpacing(BUTTON_ROW_SPACING)
        self.library_edit = QLineEdit(self)
        self.library_edit.setPlaceholderText("选择歌曲资料库目录")
        choose_button = QPushButton("选择…", audio_panel)
        set_button_icon(choose_button, "folder.svg")
        choose_button.setObjectName("settingsCompactButton")
        choose_button.clicked.connect(self._choose_library)
        library_row.addWidget(self.library_edit, 1)
        library_row.addWidget(choose_button)
        audio_layout.addLayout(library_row)
        audio_layout.addSpacing(10)

        output_caption = QLabel("音频输出设备", audio_panel)
        output_caption.setObjectName("settingsFieldLabel")
        audio_layout.addWidget(output_caption)
        self.output_combo = QComboBox(audio_panel)
        output_row = QHBoxLayout()
        output_row.setSpacing(BUTTON_ROW_SPACING)
        output_row.addWidget(self.output_combo, 1)
        self.refresh_output_devices_button = QPushButton("刷新", audio_panel)
        set_button_icon(self.refresh_output_devices_button, "refresh.svg")
        self.refresh_output_devices_button.setObjectName("settingsCompactButton")
        self.refresh_output_devices_button.setToolTip("重新扫描音频输出设备")
        self.refresh_output_devices_button.clicked.connect(self.refresh_output_devices_requested)
        output_row.addWidget(self.refresh_output_devices_button)
        audio_layout.addLayout(output_row)
        audio_layout.addStretch(1)
        self.chord_fill_button = QPushButton("补充缺失和弦", audio_panel)
        set_button_icon(self.chord_fill_button, "chord.svg")
        self.chord_fill_button.clicked.connect(self.chord_backfill_requested)
        audio_layout.addWidget(self.chord_fill_button)
        self.chord_fill_status = QLabel("", audio_panel)
        self.chord_fill_status.setObjectName("settingsFieldLabel")
        self.chord_fill_status.setWordWrap(True)
        self.chord_fill_status.hide()
        self.chord_fill_progress = QProgressBar(audio_panel)
        self.chord_fill_progress.setObjectName("chordFillProgress")
        self.chord_fill_progress.setTextVisible(False)
        self.chord_fill_progress.hide()
        audio_layout.addWidget(self.chord_fill_status)
        audio_layout.addWidget(self.chord_fill_progress)
        workspace.addWidget(audio_panel)

        display_panel = QFrame(self)
        display_panel.setObjectName("settingsPanel")
        display_layout = QVBoxLayout(display_panel)
        display_layout.setContentsMargins(17, 16, 17, 14)
        display_layout.setSpacing(11)
        display_heading = QVBoxLayout()
        display_heading.setSpacing(2)
        display_title = QLabel("观众屏视觉", display_panel)
        display_title.setObjectName("settingsPanelTitle")
        display_subtitle = QLabel("管理背景素材并预览观众屏字幕字体", display_panel)
        display_subtitle.setObjectName("settingsPanelSubtitle")
        display_heading.addWidget(display_title)
        display_heading.addWidget(display_subtitle)
        display_layout.addLayout(display_heading)

        resource_browser = QHBoxLayout()
        resource_browser.setSpacing(10)
        resource_panel = QFrame(display_panel)
        resource_panel.setObjectName("settingsResourcePane")
        resource_layout = QVBoxLayout(resource_panel)
        resource_layout.setContentsMargins(11, 10, 11, 10)
        resource_layout.setSpacing(8)
        font_caption = QLabel("字幕字体", resource_panel)
        font_caption.setObjectName("settingsFieldLabel")
        resource_layout.addWidget(font_caption)
        self.audience_font_combo = QComboBox(resource_panel)
        resource_layout.addWidget(self.audience_font_combo)
        resource_layout.addSpacing(6)
        resource_title = QLabel("背景资源", resource_panel)
        resource_title.setObjectName("settingsBrowserTitle")
        resource_layout.addWidget(resource_title)
        self.background_resource_list = QListWidget(resource_panel)
        self.background_resource_list.setObjectName("backgroundResourceList")
        self.background_resource_list.setMinimumSize(215, 190)
        resource_layout.addWidget(self.background_resource_list, 1)
        resource_actions = QHBoxLayout()
        resource_actions.setSpacing(BUTTON_ROW_SPACING)
        self.upload_background_button = QPushButton("添加", resource_panel)
        set_button_icon(self.upload_background_button, "upload.svg")
        self.upload_background_button.setObjectName("settingsCompactButton")
        self.delete_background_button = QPushButton("移除", resource_panel)
        set_button_icon(self.delete_background_button, "delete.svg")
        self.delete_background_button.setObjectName("settingsCompactButton")
        self.delete_background_button.setProperty("role", "danger")
        self.delete_background_button.setEnabled(False)
        resource_actions.addWidget(self.upload_background_button)
        resource_actions.addWidget(self.delete_background_button)
        resource_actions.addStretch(1)
        resource_layout.addLayout(resource_actions)
        resource_browser.addWidget(resource_panel, 2)

        preview_panel = QFrame(display_panel)
        preview_panel.setObjectName("settingsPreviewPane")
        self._background_preview_panel = preview_panel
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(12, 10, 12, 11)
        preview_layout.setSpacing(8)
        preview_header = QHBoxLayout()
        preview_title = QLabel("画面监看", preview_panel)
        preview_title.setObjectName("settingsBrowserTitle")
        preview_ratio = QLabel("16:9", preview_panel)
        preview_ratio.setObjectName("settingsBrowserMeta")
        preview_header.addWidget(preview_title)
        preview_header.addStretch(1)
        preview_header.addWidget(preview_ratio)
        preview_layout.addLayout(preview_header)
        self.background_preview_stack = QStackedWidget(preview_panel)
        self.background_preview_stack.setObjectName("settingsPreviewMonitor")
        self.background_preview_stack.setFixedSize(512, 288)
        self.background_preview_placeholder = QLabel("无背景视频", preview_panel)
        self.background_preview_placeholder.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.background_preview_placeholder.setContentsMargins(10, 8, 10, 8)
        self.background_preview_placeholder.setStyleSheet(
            "background: qlineargradient("
            "x1: 0, y1: 0, x2: 1, y2: 1,"
            "stop: 0 #11162B, stop: 0.5 #2A1645, stop: 1 #071D2B"
            "); color: #8e97a8;"
        )
        self.background_preview_video = QLabel(preview_panel)
        self.background_preview_video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.background_preview_video.setStyleSheet("background: #05070a; border: none;")
        self.background_preview_stack.addWidget(self.background_preview_placeholder)
        self.background_preview_stack.addWidget(self.background_preview_video)
        self.audience_font_preview = QLabel("字幕字体预览", self.background_preview_stack)
        self.audience_font_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.audience_font_preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.audience_font_preview.setGeometry(self.background_preview_stack.rect())
        self.audience_font_preview.setStyleSheet(
            "background: transparent; border: none; color: #ffffff;"
            "font-size: 32pt; font-weight: 600;"
        )
        preview_shadow = QGraphicsDropShadowEffect(self.audience_font_preview)
        preview_shadow.setBlurRadius(8)
        preview_shadow.setOffset(3, 4)
        preview_shadow.setColor(QColor(0, 0, 0, 210))
        self.audience_font_preview.setGraphicsEffect(preview_shadow)
        self.audience_font_preview.raise_()
        preview_layout.addWidget(
            self.background_preview_stack,
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
        preview_detail = QLabel("视频按窗口尺寸拉伸铺满 · 字幕位置按歌曲随机", preview_panel)
        preview_detail.setObjectName("settingsPreviewDetail")
        preview_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(preview_detail)
        preview_layout.addStretch(1)
        resource_browser.addWidget(preview_panel, 3)
        display_layout.addLayout(resource_browser, 1)

        self._preview_audio_output = QAudioOutput(self)
        self._preview_audio_output.setMuted(True)
        self._preview_player = QMediaPlayer(self)
        self._preview_player.setAudioOutput(self._preview_audio_output)
        self._preview_video_sink = QVideoSink(self)
        self._preview_video_sink.videoFrameChanged.connect(self._preview_frame_changed)
        self._preview_player.setVideoOutput(self._preview_video_sink)
        self._preview_player.setLoops(QMediaPlayer.Loops.Infinite)
        self._preview_player.errorOccurred.connect(self._preview_failed)
        self._preview_path: Path | None = None
        hint = QLabel(
            "支持 MP4、MOV、M4V、WebM · 上传后自动优化为最高 1080p/15 FPS · 系统预设不可删除",
            display_panel,
        )
        hint.setObjectName("settingsFooterHint")
        hint.setWordWrap(True)
        display_layout.addWidget(hint)
        workspace.addWidget(display_panel, 1)
        layout.addLayout(workspace, 1)

        self.library_edit.editingFinished.connect(self._request_save)
        self.output_combo.currentIndexChanged.connect(self._request_save)
        self.audience_font_combo.currentIndexChanged.connect(self._audience_font_changed)
        self.background_resource_list.currentItemChanged.connect(
            self._background_resource_selection_changed
        )
        self.upload_background_button.clicked.connect(self._choose_background_video)
        self.delete_background_button.clicked.connect(self._request_background_delete)

        self.status_label = QLabel("", self)
        self.status_label.setObjectName("statusBar")
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.status_label.hide()
        layout.addWidget(self.status_label)
        self._screen_values = ("", "", 0, 150, "", 0)
        self._background_preview_panel.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._background_preview_panel and event.type() == QEvent.Type.Resize:
            available_width = max(240, self._background_preview_panel.width() - 24)
            width = min(640, available_width)
            height = round(width * 9 / 16)
            if self.background_preview_stack.size() != QSize(width, height):
                self.background_preview_stack.setFixedSize(width, height)
                self.audience_font_preview.setGeometry(self.background_preview_stack.rect())
        return super().eventFilter(watched, event)

    def set_values(
        self,
        settings: ApplicationSettings,
        devices: tuple[AudioOutputDevice, ...],
    ) -> None:
        self.library_edit.setText(str(settings.library_root))
        self.set_output_devices(devices, settings.audio_output_device)
        self._screen_values = (
            settings.audience_screen_fingerprint,
            settings.singer_screen_fingerprint,
            settings.audience_offset_ms,
            settings.singer_offset_ms,
            settings.musician_screen_fingerprint,
            settings.musician_offset_ms,
        )

    def set_output_devices(
        self,
        devices: tuple[AudioOutputDevice, ...],
        selected_device: int | None = None,
    ) -> None:
        """刷新设备列表，并尽量保留刷新前的选择。"""
        preferred_device = (
            self.output_combo.currentData()
            if selected_device is None and self.output_combo.count() > 0
            else selected_device
        )
        self.output_combo.blockSignals(True)
        self.output_combo.clear()
        self.output_combo.addItem("系统默认设备", None)
        selected_index = 0
        for index, device in enumerate(devices, start=1):
            self.output_combo.addItem(f"{device.name}（{device.channels} 声道）", device.index)
            if device.index == preferred_device:
                selected_index = index
        self.output_combo.setCurrentIndex(selected_index)
        self.output_combo.blockSignals(False)

    def set_screen_values(
        self,
        audience_fingerprint: str,
        singer_fingerprint: str,
        audience_offset_ms: int,
        singer_offset_ms: int,
        musician_fingerprint: str | None = None,
        musician_offset_ms: int | None = None,
    ) -> None:
        self._screen_values = (
            audience_fingerprint,
            singer_fingerprint,
            audience_offset_ms,
            singer_offset_ms,
            self._screen_values[4] if musician_fingerprint is None else musician_fingerprint,
            self._screen_values[5] if musician_offset_ms is None else musician_offset_ms,
        )

    def set_background_resources(
        self,
        resources: tuple[BackgroundVideoResource, ...],
        selected_resource_id: str = "none",
    ) -> None:
        self.background_resource_list.blockSignals(True)
        self.background_resource_list.clear()
        selected_index = 0
        for index, resource in enumerate(resources):
            item = QListWidgetItem(resource.name)
            item.setData(256, resource.id)
            item.setData(257, resource.deletable)
            item.setData(258, str(resource.path) if resource.path is not None else "")
            item.setToolTip(str(resource.path) if resource.path is not None else "使用默认渐变背景")
            self.background_resource_list.addItem(item)
            if resource.id == selected_resource_id:
                selected_index = index
        if self.background_resource_list.count() > 0:
            self.background_resource_list.setCurrentRow(selected_index)
        self.background_resource_list.blockSignals(False)
        self._background_resource_selection_changed()

    def select_background_resource(self, resource_id: str) -> None:
        for row in range(self.background_resource_list.count()):
            item = self.background_resource_list.item(row)
            if item is not None and item.data(256) == resource_id:
                self.background_resource_list.setCurrentRow(row)
                return

    def set_audience_fonts(
        self,
        resources: tuple[AudienceFontResource, ...],
        selected_font_id: str,
    ) -> None:
        self.audience_font_combo.blockSignals(True)
        self.audience_font_combo.clear()
        selected_index = 0
        for index, resource in enumerate(resources):
            self.audience_font_combo.addItem(resource.name, resource.id)
            self.audience_font_combo.setItemData(
                index,
                QFont(resource.family, 14),
                Qt.ItemDataRole.FontRole,
            )
            self.audience_font_combo.setItemData(
                index,
                resource.family,
                Qt.ItemDataRole.UserRole + 1,
            )
            if resource.id == selected_font_id:
                selected_index = index
        self.audience_font_combo.setCurrentIndex(selected_index)
        self.audience_font_combo.blockSignals(False)
        self._update_audience_font_preview()

    def audience_font_id(self) -> str:
        return str(self.audience_font_combo.currentData() or "default")

    def set_audience_font_id(self, font_id: str) -> None:
        index = self.audience_font_combo.findData(font_id)
        self.audience_font_combo.blockSignals(True)
        self.audience_font_combo.setCurrentIndex(max(0, index))
        self.audience_font_combo.blockSignals(False)
        self._update_audience_font_preview()

    def show_status(self, message: str) -> None:
        self.status_label.setText(public_message(message, "设置操作失败，请重试"))
        self.status_label.setVisible(bool(message))

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._play_background_preview()

    def hideEvent(self, event: QHideEvent) -> None:
        self._preview_player.stop()
        super().hideEvent(event)

    def _choose_library(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "选择歌曲库目录", self.library_edit.text()
        )
        if selected:
            self.library_edit.setText(selected)
            self._request_save()

    def _choose_background_video(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "上传背景循环视频",
            "",
            "视频文件 (*.mp4 *.mov *.m4v *.webm)",
        )
        if selected:
            self.background_video_upload_requested.emit(Path(selected))

    def _request_background_delete(self) -> None:
        item = self.background_resource_list.currentItem()
        if item is not None and bool(item.data(257)):
            self.background_video_delete_requested.emit(str(item.data(256)))

    def _background_resource_selection_changed(
        self,
        current: QListWidgetItem | None = None,
        _previous: QListWidgetItem | None = None,
    ) -> None:
        item = current or self.background_resource_list.currentItem()
        self.delete_background_button.setEnabled(item is not None and bool(item.data(257)))
        if item is None:
            self._set_background_preview(None, "请选择背景视频")
            return
        raw_path = str(item.data(258) or "")
        self._set_background_preview(
            Path(raw_path) if raw_path else None,
            item.text(),
        )

    def _audience_font_changed(self) -> None:
        self._update_audience_font_preview()
        font_id = self.audience_font_id()
        if font_id:
            self.audience_font_changed.emit(font_id)

    def _update_audience_font_preview(self) -> None:
        family = str(
            self.audience_font_combo.currentData(Qt.ItemDataRole.UserRole + 1) or "PingFang SC"
        )
        font = QFont(family, 32)
        font.setWeight(QFont.Weight.DemiBold)
        self.audience_font_preview.setFont(font)
        self.audience_font_preview.raise_()

    def _set_background_preview(self, path: Path | None, label: str) -> None:
        self._preview_path = path
        self.background_preview_placeholder.setText(label)
        if path is None:
            self._preview_player.stop()
            self._preview_player.setSource(QUrl())
            self.background_preview_video.clear()
            self.background_preview_stack.setCurrentWidget(self.background_preview_placeholder)
            self.audience_font_preview.raise_()
            return
        if self.isVisible():
            self._play_background_preview()

    def _play_background_preview(self) -> None:
        if self._preview_path is None:
            return
        source = QUrl.fromLocalFile(str(self._preview_path.resolve()))
        if self._preview_player.source() != source:
            self._preview_player.setSource(source)
        self.background_preview_stack.setCurrentWidget(self.background_preview_video)
        self.audience_font_preview.raise_()
        self._preview_player.play()

    def _preview_failed(self) -> None:
        self.background_preview_placeholder.setText("此视频无法预览")
        self.background_preview_stack.setCurrentWidget(self.background_preview_placeholder)
        self.audience_font_preview.raise_()

    def _preview_frame_changed(self, frame: QVideoFrame) -> None:
        image = frame.toImage()
        if image.isNull():
            return
        preview = image.scaled(
            self.background_preview_video.size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.background_preview_video.setPixmap(QPixmap.fromImage(preview))
        self.background_preview_stack.setCurrentWidget(self.background_preview_video)
        self.audience_font_preview.raise_()

    def _request_save(self) -> None:
        root_text = self.library_edit.text().strip()
        if not root_text:
            self.show_status("歌曲库目录不能为空")
            return
        audience, singer, audience_offset, singer_offset, musician, musician_offset = (
            self._screen_values
        )
        value = ApplicationSettings(
            library_root=Path(root_text),
            audio_output_device=self.output_combo.currentData(),
            audience_screen_fingerprint=audience,
            singer_screen_fingerprint=singer,
            audience_offset_ms=audience_offset,
            singer_offset_ms=singer_offset,
            musician_screen_fingerprint=musician,
            musician_offset_ms=musician_offset,
        )
        self.save_requested.emit(value)

    def begin_chord_fill(self, total: int) -> None:
        self.chord_fill_status.setText(f"准备补充和弦数据（0/{total}）")
        self.chord_fill_progress.setRange(0, total)
        self.chord_fill_progress.setValue(0)
        self.chord_fill_status.show()
        self.chord_fill_progress.show()

    def update_chord_fill(self, completed: int, total: int, title: str) -> None:
        self.chord_fill_status.setText(
            f"正在补充和弦：{title}（{completed}/{total}）"
        )
        self.chord_fill_progress.setRange(0, total)
        self.chord_fill_progress.setValue(completed)
        self.chord_fill_status.show()
        self.chord_fill_progress.show()

    def finish_chord_fill(self, succeeded: int, failed: int) -> None:
        total = succeeded + failed
        self.chord_fill_progress.setRange(0, max(1, total))
        self.chord_fill_progress.setValue(total)
        if failed:
            self.chord_fill_status.setText(
                f"和弦数据补充完成：成功 {succeeded} 首，失败 {failed} 首"
            )
        else:
            self.chord_fill_status.setText(f"和弦数据补充完成：共 {succeeded} 首")
        self.chord_fill_status.show()
        self.chord_fill_progress.show()
