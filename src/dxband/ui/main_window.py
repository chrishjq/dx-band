# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent, QIcon, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dxband import __version__
from dxband.audio.output_device import AudioOutputDevice, list_output_devices
from dxband.creation.package_validator import SongPackage
from dxband.resource_paths import CONTROL_ICON_ROOT
from dxband.services.library_service import LibraryService
from dxband.services.playlist_service import PlaylistService
from dxband.ui.branding import APP_WINDOW_TITLE, application_icon, sidebar_logo
from dxband.ui.controllers.creation_controller import CreationController
from dxband.ui.controllers.library_controller import LibraryController
from dxband.ui.controllers.playback_controller import PlaybackController
from dxband.ui.pages.create_song_page import CreateSongPage
from dxband.ui.pages.library_page import LibraryPage
from dxband.ui.pages.playback_page import PlaybackPage
from dxband.ui.pages.playlist_page import PlaylistPage
from dxband.ui.pages.settings_page import SettingsPage
from dxband.ui.public_messages import public_message
from dxband.ui.services.audience_font_library import AudienceFontLibrary
from dxband.ui.services.background_video_library import (
    BackgroundVideoLibrary,
    BackgroundVideoResource,
)
from dxband.ui.services.settings_service import (
    ApplicationSettings,
    BackgroundVideoSettings,
    SettingsService,
)

NAVIGATION_ICON_DIR = CONTROL_ICON_ROOT


class MainWindow(QMainWindow):
    """串联歌曲库、创建流程、播放和设置的主窗口。"""

    background_video_imported = Signal(object)
    background_video_import_failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_WINDOW_TITLE)
        self.setWindowIcon(application_icon())
        self.resize(1600, 900)
        self.setMinimumSize(1360, 760)

        container = QWidget(self)
        container.setObjectName("applicationRoot")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QWidget(container)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(214)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 24, 16, 18)
        sidebar_layout.setSpacing(4)

        brand = QHBoxLayout()
        brand.setSpacing(6)
        self.brand_icon = QLabel(sidebar)
        self.brand_icon.setObjectName("brandIcon")
        self.brand_icon.setFixedSize(48, 36)
        self.brand_icon.setPixmap(
            sidebar_logo().scaled(
                self.brand_icon.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_text = QVBoxLayout()
        brand_text.setContentsMargins(0, 1, 0, 1)
        brand_text.setSpacing(1)
        self.brand_title = QLabel("DX BAND", sidebar)
        self.brand_title.setObjectName("brandTitle")
        self.brand_subtitle = QLabel("大象乐队工作站", sidebar)
        self.brand_subtitle.setObjectName("brandSubtitle")
        brand_text.addWidget(self.brand_title)
        brand_text.addWidget(self.brand_subtitle)
        brand.addWidget(self.brand_icon)
        brand.addLayout(brand_text, 1)
        sidebar_layout.addLayout(brand)
        sidebar_layout.addSpacing(24)

        section_label = QLabel("工作区", sidebar)
        section_label.setObjectName("sectionLabel")
        sidebar_layout.addWidget(section_label)
        sidebar_layout.addSpacing(3)

        self.navigation = QListWidget(sidebar)
        self.navigation.setObjectName("primaryNavigation")
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.settings_service = SettingsService()
        self.background_video_library = BackgroundVideoLibrary()
        self.audience_font_library = AudienceFontLibrary()
        settings = self.settings_service.load()
        library_root = settings.library_root
        self.pages = QStackedWidget(container)
        self.pages.setObjectName("pageStack")
        self.library_page = LibraryPage()
        self.create_song_page = CreateSongPage()
        self.playlist_page = PlaylistPage(embedded=True)
        self.playback_page = PlaybackPage(self.playlist_page)
        self.settings_page = SettingsPage()
        page_specs: list[tuple[str, str, QWidget]] = [
            ("播放控制", "playback.svg", self.playback_page),
            ("歌曲库", "library.svg", self.library_page),
            ("设置", "settings.svg", self.settings_page),
        ]
        self._navigation_pages = tuple(page for _title, _icon, page in page_specs)
        for page in (
            self.playback_page,
            self.library_page,
            self.create_song_page,
            self.settings_page,
        ):
            self.pages.addWidget(page)
        self.navigation.setIconSize(QSize(18, 18))
        for title, icon_name, _page in page_specs:
            item = QListWidgetItem(QIcon(str(NAVIGATION_ICON_DIR / icon_name)), title)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.navigation.addItem(item)

        self.navigation.currentRowChanged.connect(self._navigation_changed)
        self.navigation.itemClicked.connect(
            lambda item: self._navigation_changed(self.navigation.row(item))
        )
        sidebar_layout.addWidget(self.navigation, 1)
        self.version_label = QLabel(f"版本 {__version__}", sidebar)
        self.version_label.setObjectName("sidebarVersion")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addSpacing(8)
        sidebar_layout.addWidget(self.version_label)

        layout.addWidget(sidebar)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(container)
        self.library_service = LibraryService(library_root)
        self.playlist_service = PlaylistService(library_root)
        self._available_songs: dict[str, SongPackage] = {}
        self._current_playlist_index: int | None = None
        self._pending_playlist_entry: tuple[int, str] | None = None
        self._song_load_in_progress = False
        self.library_controller = LibraryController(
            self.library_page, self.library_service, self.settings_service,
            parent=self,
        )
        self.creation_controller = CreationController(
            self.create_song_page, library_root=library_root, parent=self,
        )
        self.playback_controller = PlaybackController(
            self.playback_page,
            self.settings_service,
            self.background_video_library,
            self.audience_font_library,
            parent=self,
        )
        previous_output_device = settings.audio_output_device
        try:
            devices = list_output_devices()
        except Exception:
            devices = ()
        else:
            settings = self._reconcile_output_device(settings, devices)
        self.settings_page.set_values(
            settings,
            devices,
        )
        if previous_output_device is not None and settings.audio_output_device is None:
            self.settings_page.show_status("原音频输出设备已断开，已切换为系统默认设备")
        self.playback_page.set_beat_prompt_sound_enabled(
            self.settings_service.load_beat_prompt_sound_enabled()
        )
        singer_display = self.settings_service.load_singer_display_settings()
        self.playback_page.set_singer_display_options(
            singer_display.beat_lights_visible,
            singer_display.music_info_visible,
        )
        musician_display = self.settings_service.load_musician_display_settings()
        self.playback_page.set_musician_beat_lights_visible(musician_display.beat_lights_visible)
        background_resources = self.background_video_library.resources()
        background_settings = self.settings_service.load_background_video_settings()
        self.settings_page.set_background_resources(
            background_resources,
            background_settings.fixed_resource_id,
        )
        self.playback_page.set_background_resources(
            background_resources,
            background_settings,
        )
        audience_fonts = self.audience_font_library.resources()
        audience_font_id = self.settings_service.load_audience_font_id()
        self.settings_page.set_audience_fonts(audience_fonts, audience_font_id)
        self.playback_page.set_audience_fonts(audience_fonts, audience_font_id)
        self.library_controller.song_load_requested.connect(self._load_for_playback)
        self.library_controller.song_load_failed.connect(self._song_load_failed)
        self.library_controller.song_lyrics_updated.connect(
            self.playback_controller.update_package_lyrics
        )
        self.library_controller.song_chords_updated.connect(
            self.playback_controller.update_package_chords
        )
        self.library_controller.chord_batch_progress.connect(
            self.settings_page.update_chord_fill
        )
        self.library_controller.chord_batch_finished.connect(
            self._chord_backfill_finished
        )
        self.playback_controller.song_loaded.connect(self._song_loaded)
        self.playback_controller.song_load_failed.connect(self._song_load_failed)
        self.playback_controller.song_finished.connect(self._song_finished)
        self.playback_controller.settings_changed.connect(self._runtime_settings_changed)
        self.playback_page.next_song_requested.connect(self._manual_next_song)
        self.playback_page.previous_song_requested.connect(self._manual_previous_song)
        self.playback_page.auto_play_next_changed.connect(self._set_auto_play_next)
        self.playback_page.set_auto_play_next(self.settings_service.load_auto_play_next())
        self.settings_page.save_requested.connect(self._save_settings)
        self.settings_page.chord_backfill_requested.connect(self._offer_chord_backfill)
        self.playback_page.background_video_settings_changed.connect(
            self._background_video_settings_changed
        )
        self.settings_page.refresh_output_devices_requested.connect(self._refresh_output_devices)
        self.settings_page.background_video_upload_requested.connect(self._upload_background_video)
        self.background_video_imported.connect(self._background_video_imported)
        self.background_video_import_failed.connect(self._background_video_import_failed)
        self._background_video_import_busy = False
        self.settings_page.background_video_delete_requested.connect(self._delete_background_video)
        self.settings_page.audience_font_changed.connect(self._audience_font_changed)
        self.playback_page.audience_font_changed.connect(self._audience_font_changed)
        self.playback_page.beat_prompt_sound_changed.connect(self._beat_prompt_sound_changed)
        self.playback_page.singer_display_options_changed.connect(
            self._singer_display_options_changed
        )
        self.playback_page.musician_beat_lights_changed.connect(self._musician_beat_lights_changed)
        self.library_page.create_requested.connect(self._show_create_song)
        self.library_page.load_requested.connect(self._clear_pending_playlist_entry)
        self.create_song_page.back_to_library_requested.connect(self._show_library)
        self.creation_controller.creation_active_changed.connect(
            self.library_page.set_creation_active
        )
        self.library_page.add_to_playlist_requested.connect(self._add_to_playlist)
        self.playlist_page.load_requested.connect(self._load_playlist_song)
        self.playlist_page.remove_requested.connect(self._remove_from_playlist)
        self.playlist_page.move_requested.connect(self._move_playlist_song)
        self.creation_controller.song_created.connect(self._created_song_ready_for_editing)
        # Qt WebEngine creates short-lived native widgets. A Python event filter on
        # QApplication can receive them while they are being destroyed and crash
        # inside PySide's QObject wrapper. The Space shortcut only belongs to the
        # playback window, so install the filter on its widgets instead.
        self.installEventFilter(self)
        self.playback_page.installEventFilter(self)
        for child in self.playback_page.findChildren(QWidget):
            child.installEventFilter(self)
        self.navigation.setCurrentRow(self._navigation_index(self.playback_page))
        self.playback_controller.restore_web_displays()

    def _offer_chord_backfill(self) -> None:
        try:
            missing = self.library_controller.missing_chord_packages()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "检查和弦数据失败",
                public_message(str(exc), "请重试或检查歌曲库"),
            )
            return
        if not missing:
            return
        answer = QMessageBox.question(
            self,
            "补充和弦数据",
            f"歌曲库中有 {len(missing)} 首歌曲缺少和弦数据，是否现在批量补充？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.settings_page.begin_chord_fill(len(missing))
        if not self.library_controller.start_chord_backfill(missing):
            self.settings_page.finish_chord_fill(0, len(missing))

    def _chord_backfill_finished(
        self, succeeded: int, failed: int, failures: object
    ) -> None:
        self.settings_page.finish_chord_fill(succeeded, failed)
        self.library_controller.refresh()
        if failed and isinstance(failures, tuple):
            details = "\n".join(str(item) for item in failures[:5])
            if len(failures) > 5:
                details += f"\n另有 {len(failures) - 5} 首失败"
            QMessageBox.warning(
                self,
                "部分和弦数据补充失败",
                f"成功 {succeeded} 首，失败 {failed} 首。\n{details}",
            )

    def _load_for_playback(self, package: object) -> None:
        self._song_load_in_progress = True
        if isinstance(package, tuple) and len(package) == 2:
            song_package, auto_play = package
            if isinstance(song_package, SongPackage):
                self._select_loaded_playlist_entry(song_package.config.song_id)
            self.playback_controller.load_package(song_package, auto_play=auto_play)
        else:
            if isinstance(package, SongPackage):
                self._select_loaded_playlist_entry(package.config.song_id)
            self.playback_controller.load_package(package)
        self.navigation.setCurrentRow(self._navigation_index(self.playback_page))

    def _select_loaded_playlist_entry(self, song_id: str) -> None:
        try:
            values = self.playlist_service.load()
        except Exception as exc:
            self._pending_playlist_entry = None
            self._current_playlist_index = None
            self.playlist_page.show_status(f"播放列表读取失败：{exc}")
            return
        pending = self._pending_playlist_entry
        self._pending_playlist_entry = None
        if pending is not None and pending[1] == song_id:
            index = pending[0]
            if 0 <= index < len(values) and values[index] == song_id:
                self._current_playlist_index = index
                return
        current = self._current_playlist_index
        if current is not None and 0 <= current < len(values) and values[current] == song_id:
            return
        self._current_playlist_index = values.index(song_id) if song_id in values else None

    def _clear_pending_playlist_entry(self, value: object) -> None:
        self._pending_playlist_entry = None
        self._song_load_in_progress = True
        if isinstance(value, Path):
            package = next(
                (song for song in self._available_songs.values() if song.root == value),
                None,
            )
            if package is not None:
                self.playback_page.set_loading(
                    package.config.title, package.config.artist, validating=True
                )

    def _song_load_failed(self, message: str) -> None:
        self._pending_playlist_entry = None
        self._song_load_in_progress = False
        if self.playback_controller.current_song_id is None:
            self.playback_page.set_loading_failed(message)
        else:
            self.playback_page.show_status(f"加载歌曲失败：{message}")

    def _song_loaded(self, song_id: str) -> None:
        self._song_load_in_progress = False
        self.library_controller.playing_song_id = song_id
        self._refresh_playlist()

    def _navigation_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._navigation_pages):
            return
        page = self._navigation_pages[row]
        self.pages.setCurrentWidget(page)
        if page is self.playback_page:
            self._refresh_playlist()

    def _navigation_index(self, page: QWidget) -> int:
        return self._navigation_pages.index(page)

    def _toggle_playback_from_space(self) -> None:
        if self.pages.currentWidget() is not self.playback_page:
            return
        focused = QApplication.focusWidget()
        if isinstance(
            focused,
            (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox),
        ):
            return
        self.playback_page.play_button.click()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() != QEvent.Type.KeyPress
            or not isinstance(event, QKeyEvent)
            or event.key() != Qt.Key.Key_Space
            or event.modifiers() != Qt.KeyboardModifier.NoModifier
        ):
            return super().eventFilter(watched, event)
        active_window = QApplication.activeWindow()
        if (
            (active_window is not None and active_window is not self)
            or self.pages.currentWidget() is not self.playback_page
        ):
            return super().eventFilter(watched, event)
        focused = QApplication.focusWidget()
        input_types = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox)
        if isinstance(watched, input_types) or isinstance(focused, input_types):
            return super().eventFilter(watched, event)
        if event.isAutoRepeat():
            return True
        self.playback_page.play_button.click()
        return True

    def _show_create_song(self) -> None:
        self.pages.setCurrentWidget(self.create_song_page)

    def _show_library(self) -> None:
        self.navigation.setCurrentRow(self._navigation_index(self.library_page))
        self.pages.setCurrentWidget(self.library_page)

    def _created_song_ready_for_editing(self, value: object) -> None:
        if not isinstance(value, Path):
            self.library_page.show_error("创建完成的歌曲路径无效")
            return
        self.library_controller.refresh()
        self._show_library()
        self.library_controller.edit_path(value)

    def _refresh_playlist(self) -> None:
        try:
            self._available_songs = {
                package.config.song_id: package for package in self.library_service.scan().songs
            }
            song_ids = self.playlist_service.load()
            current_index = (
                self._current_queue_index()
                if self.playback_controller.current_song_id is not None
                else None
            )
            self.playlist_page.set_songs(
                song_ids,
                self._available_songs,
                current_index=current_index,
            )
            self.library_page.set_playlist_song_ids(song_ids)
            if self.pages.currentWidget() is self.playback_page:
                self._ensure_playlist_song_loaded(song_ids)
            self._update_queue_controls()
        except Exception as exc:
            self.playlist_page.show_status(f"播放列表读取失败：{exc}")

    def _ensure_playlist_song_loaded(self, song_ids: tuple[str, ...]) -> None:
        """首次进入播放控制时加载播放列表第一首，但保持停止状态。"""
        if (
            self.playback_controller.current_song_id is not None
            or self._pending_playlist_entry is not None
            or self._song_load_in_progress
        ):
            return
        entry = next(
            (
                (index, song_id)
                for index, song_id in enumerate(song_ids)
                if song_id in self._available_songs
            ),
            None,
        )
        if entry is None:
            self.playback_page.set_empty_playlist(unavailable=bool(song_ids))
            return
        package = self._available_songs[entry[1]]
        self._pending_playlist_entry = entry
        self._song_load_in_progress = True
        self.playback_page.set_loading(package.config.title, package.config.artist, validating=True)
        self.library_controller.load_path(package.root, auto_play=False)

    def _current_queue_index(self) -> int | None:
        current_id = self.playback_controller.current_song_id
        if current_id is None:
            pending = self._pending_playlist_entry
            if pending is not None:
                values = self.playlist_service.load()
                if 0 <= pending[0] < len(values) and values[pending[0]] == pending[1]:
                    return pending[0]
            return None
        values = self.playlist_service.load()
        index = self._current_playlist_index
        if index is not None and 0 <= index < len(values) and values[index] == current_id:
            return index
        return values.index(current_id) if current_id in values else None

    def _add_to_playlist(self, value: object) -> None:
        if not isinstance(value, tuple):
            return
        self._refresh_playlist()
        paths = set(value)
        song_ids = tuple(
            song_id for song_id, package in self._available_songs.items() if package.root in paths
        )
        if len(song_ids) != len(paths):
            self.library_page.show_error("部分歌曲已不存在，请刷新歌曲库后重试")
            return
        try:
            added = self.playlist_service.add(song_ids)
        except Exception as exc:
            self.library_page.show_error(f"添加到播放列表失败：{exc}")
            return
        self._refresh_playlist()
        self.library_page.status_label.setText(f"已加入 {added} 首歌曲")

    def _remove_from_playlist(self, index: int) -> None:
        try:
            self.playlist_service.remove(index)
            if self._current_playlist_index == index:
                self._current_playlist_index = None
            elif self._current_playlist_index is not None and self._current_playlist_index > index:
                self._current_playlist_index -= 1
            self._refresh_playlist()
        except Exception as exc:
            self.playlist_page.show_status(f"移除失败：{exc}")

    def _move_playlist_song(self, index: int, direction: int) -> None:
        try:
            target = self.playlist_service.move(index, direction)
            if self._current_playlist_index == index:
                self._current_playlist_index = target
            elif self._current_playlist_index == target:
                self._current_playlist_index = index
            self._refresh_playlist()
            self.playlist_page.song_list.selectRow(target)
        except Exception as exc:
            self.playlist_page.show_status(f"调整顺序失败：{exc}")

    def _load_playlist_song(self, index: int) -> None:
        values = self.playlist_service.load()
        if not 0 <= index < len(values):
            self.playlist_page.show_status("播放列表位置无效")
            return
        song_id = values[index]
        package = self._available_songs.get(song_id)
        if package is None:
            self.playlist_page.show_status("歌曲不存在，请从播放列表移除")
            return
        self._pending_playlist_entry = (index, song_id)
        self.library_controller.load_path(package.root)

    def _update_queue_controls(self) -> None:
        current_index = self._current_queue_index()
        available_ids = set(self._available_songs)
        next_entry = self.playlist_service.next_entry(current_index, available_ids)
        previous_entry = self.playlist_service.previous_entry(current_index, available_ids)
        next_id = next_entry[1] if next_entry is not None else None
        previous_id = previous_entry[1] if previous_entry is not None else None
        package = self._available_songs.get(next_id) if next_id is not None else None
        self.playback_page.set_next_song(
            package.config.title if package is not None else None,
            package.config.artist if package is not None else "",
        )
        previous = self._available_songs.get(previous_id) if previous_id is not None else None
        self.playback_page.set_previous_song(
            previous.config.title if previous is not None else None,
            previous.config.artist if previous is not None else "",
        )

    def _manual_previous_song(self) -> None:
        self._refresh_playlist()
        try:
            previous_entry = self.playlist_service.previous_entry(
                self._current_queue_index(),
                set(self._available_songs),
            )
        except Exception as exc:
            self.playback_page.show_status(f"读取播放列表失败：{exc}")
            return
        package = (
            self._available_songs.get(previous_entry[1]) if previous_entry is not None else None
        )
        if package is None:
            self.playback_page.show_status("播放列表中没有上一首歌曲")
            return
        self.playback_controller.stop_for_song_change()
        self._pending_playlist_entry = previous_entry
        self.library_controller.load_path(package.root, auto_play=False)
        self.playback_page.show_status("正在加载上一首，加载后请手动播放")

    def _manual_next_song(self) -> None:
        self._advance_to_next(auto_play=False)

    def _song_finished(self) -> None:
        if self.playback_page.auto_play_next_check.isChecked():
            self._advance_to_next(auto_play=True)

    def _advance_to_next(self, auto_play: bool) -> None:
        self._refresh_playlist()
        try:
            next_entry = self.playlist_service.next_entry(
                self._current_queue_index(),
                set(self._available_songs),
            )
        except Exception as exc:
            self.playback_page.show_status(f"读取播放列表失败：{exc}")
            return
        package = self._available_songs.get(next_entry[1]) if next_entry is not None else None
        if package is None:
            self.playback_page.show_status("播放列表中没有下一首歌曲")
            return
        if not auto_play:
            self.playback_controller.stop_for_song_change()
        self._pending_playlist_entry = next_entry
        self.library_controller.load_path(package.root, auto_play=auto_play)
        self.playback_page.show_status(
            "正在加载下一首，加载后将自动播放" if auto_play else "正在加载下一首，加载后请手动播放"
        )

    def _set_auto_play_next(self, enabled: bool) -> None:
        try:
            self.settings_service.save_auto_play_next(enabled)
        except Exception as exc:
            self.playback_page.set_auto_play_next(not enabled)
            self.playback_page.show_status(f"保存自动播放设置失败：{exc}")

    def _beat_prompt_sound_changed(self, enabled: bool) -> None:
        try:
            self.settings_service.save_beat_prompt_sound_enabled(enabled)
            self.playback_controller.apply_beat_prompt_sound_enabled(enabled)
        except Exception as exc:
            self.playback_page.set_beat_prompt_sound_enabled(not enabled)
            self.playback_page.show_status(f"保存引导拍子声设置失败：{exc}")
            return
        self.playback_page.show_status(
            "引导拍子声已开启；打开乐手屏时，从歌曲开头播放前响两小节"
            if enabled
            else "引导拍子声已关闭"
        )

    def _singer_display_options_changed(self, beat_lights: bool, music_info: bool) -> None:
        self.playback_controller.apply_singer_display_options(beat_lights, music_info)
        self.playback_page.show_status("歌手屏显示选项已保存")

    def _musician_beat_lights_changed(self, visible: bool) -> None:
        self.playback_controller.apply_musician_beat_lights_visible(visible)
        state = "显示" if visible else "隐藏"
        self.playback_page.show_status(f"乐手屏拍子灯已{state}")

    def _runtime_settings_changed(self, value: object) -> None:
        if not isinstance(value, ApplicationSettings):
            return
        self.settings_page.set_screen_values(
            value.audience_screen_fingerprint,
            value.singer_screen_fingerprint,
            value.audience_offset_ms,
            value.singer_offset_ms,
            value.musician_screen_fingerprint,
            value.musician_offset_ms,
        )

    def _refresh_output_devices(self) -> None:
        try:
            devices = list_output_devices()
        except Exception as exc:
            self.settings_page.show_status(f"刷新音频输出设备失败：{exc}")
            return
        previous_device = self.playback_controller.settings.audio_output_device
        self._reconcile_output_device(self.playback_controller.settings, devices)
        self.settings_page.set_output_devices(devices)
        if (
            previous_device is not None
            and self.playback_controller.settings.audio_output_device is None
        ):
            self.settings_page.show_status("原音频输出设备已断开，已切换为系统默认设备")
        else:
            self.settings_page.show_status(f"已刷新音频输出设备：发现 {len(devices)} 个设备")

    def _reconcile_output_device(
        self,
        settings: ApplicationSettings,
        devices: tuple[AudioOutputDevice, ...],
    ) -> ApplicationSettings:
        selected = settings.audio_output_device
        if selected is None or any(device.index == selected for device in devices):
            return settings
        updated = replace(settings, audio_output_device=None)
        self.settings_service.save(updated)
        self.playback_controller.apply_settings(updated)
        return updated

    def _save_settings(self, value: object) -> None:
        if not isinstance(value, ApplicationSettings):
            self.settings_page.show_status("设置数据无效")
            return
        previous_output_device = self.playback_controller.settings.audio_output_device
        try:
            root = value.library_root.expanduser().resolve()
            library_root_changed = root != self.library_service.root
            output_device_changed = value.audio_output_device != previous_output_device
            normalized = ApplicationSettings(
                library_root=root,
                audio_output_device=value.audio_output_device,
                audience_screen_fingerprint=value.audience_screen_fingerprint,
                singer_screen_fingerprint=value.singer_screen_fingerprint,
                audience_offset_ms=value.audience_offset_ms,
                singer_offset_ms=value.singer_offset_ms,
                musician_screen_fingerprint=value.musician_screen_fingerprint,
                musician_offset_ms=value.musician_offset_ms,
            )
            if library_root_changed:
                self.creation_controller.set_library_root(root)
                self.library_service.set_root(root)
                self.playlist_service.set_root(root)
                self._current_playlist_index = None
                self._pending_playlist_entry = None
            self.settings_service.save(normalized)
            self.playback_controller.apply_settings(normalized)
            if library_root_changed:
                self.library_controller.refresh()
                self._refresh_playlist()
        except Exception as exc:
            self.settings_page.show_status(f"保存失败：{exc}")
            return
        if library_root_changed:
            self.settings_page.show_status("歌曲库目录已自动保存并应用")
        else:
            self.settings_page.show_status("音频输出设备已自动保存，将在下次加载歌曲时生效")
        if output_device_changed:
            QMessageBox.information(
                self,
                "音频输出设备已更改",
                "新设备已保存，将在下次加载歌曲时生效。\n当前歌曲仍使用原来的音频输出设备。",
            )

    def _background_video_settings_changed(self, value: object) -> None:
        if not isinstance(value, BackgroundVideoSettings):
            self.playback_page.show_status("背景视频设置数据无效")
            return
        normalized = value
        if (
            value.fixed_resource_id != "none"
            and self.background_video_library.find(value.fixed_resource_id) is None
        ):
            normalized = BackgroundVideoSettings(
                mode=value.mode,
                fixed_resource_id="none",
            )
        try:
            self.settings_service.save_background_video_settings(normalized)
            self.playback_controller.apply_background_video_settings(normalized)
        except Exception as exc:
            self.playback_page.set_background_video_settings(
                self.settings_service.load_background_video_settings()
            )
            self.playback_page.show_status(f"保存背景视频设置失败：{exc}")
            return
        self.playback_page.set_background_video_settings(normalized)
        if normalized.mode == "random":
            self.playback_page.show_status("观众屏背景已设为随机模式")
        else:
            resource = self.background_video_library.find(normalized.fixed_resource_id)
            self.settings_page.select_background_resource(normalized.fixed_resource_id)
            name = resource.name if resource is not None else "无背景视频"
            self.playback_page.show_status(f"观众屏背景已固定为：{name}")

    def _upload_background_video(self, value: object) -> None:
        if not isinstance(value, Path):
            self.settings_page.show_status("上传的背景视频路径无效")
            return
        if self._background_video_import_busy:
            self.settings_page.show_status("正在优化上一段背景视频，请稍候")
            return
        self._background_video_import_busy = True
        self.settings_page.show_status("正在后台优化背景视频，完成后会自动应用")
        threading.Thread(
            target=self._import_background_video_worker,
            args=(value,),
            name="background-video-import",
            daemon=True,
        ).start()

    def _import_background_video_worker(self, source: Path) -> None:
        try:
            imported = self.background_video_library.import_file(source)
        except Exception as exc:
            self.background_video_import_failed.emit(str(exc))
        else:
            self.background_video_imported.emit(imported)

    def _background_video_imported(self, imported: object) -> None:
        self._background_video_import_busy = False
        if not isinstance(imported, BackgroundVideoResource):
            self.settings_page.show_status("上传背景视频失败：资源无效")
            return
        resources = self.background_video_library.resources()
        current = BackgroundVideoSettings(mode="fixed", fixed_resource_id=imported.id)
        self.settings_page.set_background_resources(resources, imported.id)
        self.playback_page.set_background_resources(resources, current)
        self._background_video_settings_changed(current)
        self.settings_page.show_status(f"已优化并应用背景视频：{imported.name}")

    def _background_video_import_failed(self, message: str) -> None:
        self._background_video_import_busy = False
        self.settings_page.show_status(f"上传背景视频失败：{message}")

    def _delete_background_video(self, resource_id: str) -> None:
        current = self.settings_service.load_background_video_settings()
        try:
            self.background_video_library.delete(resource_id)
        except Exception as exc:
            self.settings_page.show_status(f"删除背景视频失败：{exc}")
            return
        if current.fixed_resource_id == resource_id:
            current = BackgroundVideoSettings(
                mode=current.mode,
                fixed_resource_id="none",
            )
            self.settings_service.save_background_video_settings(current)
        self.playback_controller.apply_background_video_settings(current)
        resources = self.background_video_library.resources()
        self.settings_page.set_background_resources(resources, current.fixed_resource_id)
        self.playback_page.set_background_resources(resources, current)
        self.settings_page.show_status("已删除所选用户背景视频")

    def _audience_font_changed(self, font_id: str) -> None:
        resource = self.audience_font_library.find(font_id)
        try:
            self.settings_service.save_audience_font_id(resource.id)
            self.playback_controller.apply_audience_font(resource.id)
        except Exception as exc:
            self.settings_page.show_status(f"应用观众屏字体失败：{exc}")
            return
        self.settings_page.set_audience_font_id(resource.id)
        self.playback_page.set_audience_font_id(resource.id)
        self.settings_page.show_status(f"观众屏字体已应用：{resource.name}")
        self.playback_page.show_status(f"观众屏字体已应用：{resource.name}")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.playback_controller.close()
        super().closeEvent(event)
