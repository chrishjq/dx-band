# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import math

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dxband.constants import MUSICIAN_FONT_SIZE_MIN, TrackKind
from dxband.ui.page_layout import (
    add_page_header,
    create_page_layout,
    set_button_icon,
)
from dxband.ui.public_messages import public_message
from dxband.ui.screen import ScreenDescriptor
from dxband.ui.services.audience_font_library import AudienceFontResource
from dxband.ui.services.background_video_library import BackgroundVideoResource
from dxband.ui.services.settings_service import BackgroundVideoSettings
from dxband.ui.widgets.output_screen_button import OutputScreenButton
from dxband.ui.widgets.parameter_spin_box import ParameterSpinBox, PlaybackBpmSpinBox
from dxband.ui.widgets.screen_selector import ScreenSelector
from dxband.ui.widgets.track_mute_button import TrackMuteButton
from dxband.utils.time_format import format_time_ms

TRACK_NAMES: dict[TrackKind, str] = {
    TrackKind.VOCALS: "人声",
    TrackKind.DRUMS: "鼓组",
    TrackKind.BASS: "贝斯",
    TrackKind.GUITAR: "吉他",
    TrackKind.PIANO: "钢琴",
    TrackKind.OTHER: "其他",
}
RANDOM_BACKGROUND_ID = "__random__"


class PlaybackPage(QWidget):
    play_pause_requested = Signal()
    restart_requested = Signal()
    previous_song_requested = Signal()
    next_song_requested = Signal()
    auto_play_next_changed = Signal(bool)
    stop_requested = Signal()
    seek_requested = Signal(int)
    track_mute_requested = Signal(str, bool)
    track_gain_requested = Signal(str, float)
    master_volume_requested = Signal(float)
    playback_bpm_requested = Signal(int)
    audience_output_toggled = Signal(bool)
    singer_output_toggled = Signal(bool)
    musician_output_toggled = Signal(bool)
    musician_offset_changed = Signal(int)
    musician_font_size_changed = Signal(int)
    offsets_changed = Signal(int, int)
    subtitle_font_sizes_changed = Signal(int, int)
    beat_prompt_sound_changed = Signal(bool)
    singer_display_options_changed = Signal(bool, bool)
    musician_beat_lights_changed = Signal(bool)
    web_musician_toggled = Signal(bool)
    web_musician_qr_requested = Signal()
    web_singer_toggled = Signal(bool)
    web_singer_qr_requested = Signal()
    background_video_settings_changed = Signal(object)
    audience_font_changed = Signal(str)

    def __init__(self, playlist_panel: QWidget | None = None) -> None:
        super().__init__()
        self._duration_ms = 0
        self._original_bpm = 0
        if playlist_panel is None:
            layout = create_page_layout(self)
        else:
            page_layout = QHBoxLayout(self)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(0)
            content = QWidget(self)
            content.setObjectName("playbackContent")
            layout = create_page_layout(content)
            page_layout.addWidget(content, 1)
            divider = QFrame(self)
            divider.setObjectName("playbackPlaylistDivider")
            divider.setFrameShape(QFrame.Shape.VLine)
            divider.setFrameShadow(QFrame.Shadow.Plain)
            page_layout.addWidget(divider)
            playlist_panel.setMinimumWidth(360)
            playlist_panel.setMaximumWidth(460)
            page_layout.addWidget(playlist_panel)
        self.state_label = QLabel("未加载歌曲", self)
        self.state_label.setObjectName("stateChip")
        add_page_header(
            layout,
            self,
            "播放控制",
            "六轨混音、时间线与三屏演出输出",
            self.state_label,
        )

        now_playing = QFrame(self)
        now_playing.setObjectName("nowPlayingPanel")
        now_playing_layout = QVBoxLayout(now_playing)
        now_playing_layout.setContentsMargins(18, 13, 18, 13)
        now_playing_layout.setSpacing(4)
        self.song_label = QLabel("播放列表为空，请先添加歌曲", now_playing)
        self.song_label.setObjectName("songTitle")
        song_row = QHBoxLayout()
        song_row.setContentsMargins(0, 0, 0, 0)
        song_row.setSpacing(16)
        song_row.addWidget(self.song_label, 1)
        self.music_info_label = QLabel("", now_playing)
        self.music_info_label.setObjectName("nowPlayingMusicInfo")
        self.music_info_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.music_info_label.hide()
        song_row.addWidget(self.music_info_label)
        now_playing_layout.addLayout(song_row)
        self.next_song_label = QLabel("下一首：播放列表暂无后续歌曲", now_playing)
        self.next_song_label.setObjectName("mutedText")
        now_playing_layout.addWidget(self.next_song_label)
        layout.addWidget(now_playing)

        transport_panel = QFrame(self)
        transport_panel.setObjectName("transportPanel")
        transport_panel_layout = QVBoxLayout(transport_panel)
        transport_panel_layout.setContentsMargins(16, 12, 16, 12)
        transport_panel_layout.setSpacing(9)
        transport = QHBoxLayout()
        transport.setSpacing(8)
        self.previous_song_button = QPushButton(transport_panel)
        set_button_icon(self.previous_song_button, "previous.svg", QSize(18, 18))
        self.previous_song_button.setAccessibleName("上一首")
        self.previous_song_button.setToolTip("播放列表中没有上一首歌曲")
        self.restart_button = QPushButton(transport_panel)
        set_button_icon(self.restart_button, "restart.svg", QSize(18, 18))
        self.restart_button.setAccessibleName("回到歌曲开头")
        self.restart_button.setToolTip("回到当前歌曲开头")
        self.backward_button = QPushButton(transport_panel)
        set_button_icon(self.backward_button, "rewind.svg", QSize(18, 18))
        self.backward_button.setAccessibleName("后退五秒")
        self.backward_button.setToolTip("后退 5 秒")
        self.play_button = QPushButton(transport_panel)
        set_button_icon(self.play_button, "play.svg", QSize(18, 18))
        self.play_button.setProperty("role", "play")
        self.play_button.setAccessibleName("播放")
        self.play_button.setToolTip("播放（空格键）")
        self.forward_button = QPushButton(transport_panel)
        set_button_icon(self.forward_button, "forward.svg", QSize(18, 18))
        self.forward_button.setAccessibleName("前进五秒")
        self.forward_button.setToolTip("前进 5 秒")
        self.stop_button = QPushButton(transport_panel)
        set_button_icon(self.stop_button, "stop.svg", QSize(18, 18))
        self.stop_button.setAccessibleName("停止播放")
        self.stop_button.setToolTip("停止")
        self.next_song_button = QPushButton(transport_panel)
        set_button_icon(self.next_song_button, "next.svg", QSize(18, 18))
        self.next_song_button.setAccessibleName("下一首")
        self.next_song_button.setToolTip("加载下一首歌曲；不会自动播放")
        for button in (
            self.previous_song_button,
            self.restart_button,
            self.backward_button,
            self.forward_button,
            self.stop_button,
            self.next_song_button,
        ):
            button.setProperty("role", "transport")
        for button in (
            self.previous_song_button,
            self.restart_button,
            self.backward_button,
            self.play_button,
            self.forward_button,
            self.stop_button,
            self.next_song_button,
        ):
            transport.addWidget(button)
        transport.addStretch(1)
        speed_label = QLabel("速度", transport_panel)
        speed_label.setObjectName("mutedText")
        transport.addWidget(speed_label)
        self.playback_bpm_spin = PlaybackBpmSpinBox(transport_panel)
        self.playback_bpm_spin.setRange(0, 400)
        self.playback_bpm_spin.setSpecialValueText("— BPM")
        self.playback_bpm_spin.setSuffix(" BPM")
        self.playback_bpm_spin.setKeyboardTracking(False)
        self.playback_bpm_spin.setFixedWidth(94)
        self.playback_bpm_spin.setToolTip("按目标 BPM 调整播放速度（变速会同步改变音高）")
        self.playback_bpm_spin.setEnabled(False)
        transport.addWidget(self.playback_bpm_spin)
        self.auto_play_next_check = QCheckBox("自动播放下一首", transport_panel)
        self.auto_play_next_check.setToolTip("当前歌曲自然结束后，自动加载并播放下一首")
        transport.addWidget(self.auto_play_next_check)
        transport_panel_layout.addLayout(transport)

        timeline = QHBoxLayout()
        self.current_time_label = QLabel("00:00.000", transport_panel)
        self.current_time_label.setObjectName("timeDisplay")
        self.position_slider = QSlider(Qt.Orientation.Horizontal, transport_panel)
        self.position_slider.setRange(0, 0)
        self.duration_label = QLabel("00:00.000", transport_panel)
        self.duration_label.setObjectName("timeDisplay")
        timeline.addWidget(self.current_time_label)
        timeline.addWidget(self.position_slider, 1)
        timeline.addWidget(self.duration_label)
        transport_panel_layout.addLayout(timeline)
        layout.addWidget(transport_panel)

        middle = QHBoxLayout()
        middle.setSpacing(13)
        tracks_box = QGroupBox("六轨混音", self)
        tracks_box.setFixedWidth(280)
        tracks_layout = QVBoxLayout(tracks_box)
        tracks_layout.setSpacing(10)
        track_buttons = QVBoxLayout()
        track_buttons.setContentsMargins(0, 0, 0, 0)
        track_buttons.setSpacing(5)
        self.track_checks: dict[TrackKind, TrackMuteButton] = {}
        self.track_volume_sliders: dict[TrackKind, QSlider] = {}
        self.track_volume_labels: dict[TrackKind, QLabel] = {}
        self._available_tracks = set(TrackKind)
        for track in TrackKind:
            track_row = QHBoxLayout()
            track_row.setContentsMargins(0, 0, 0, 0)
            track_row.setSpacing(7)
            track_button = TrackMuteButton(track, TRACK_NAMES[track], tracks_box)
            track_button.toggled.connect(
                lambda checked, selected=track: self._track_mute_changed(selected, checked)
            )
            self.track_checks[track] = track_button
            track_row.addWidget(track_button)
            track_slider = QSlider(Qt.Orientation.Horizontal, tracks_box)
            track_slider.setRange(0, 150)
            track_slider.setSingleStep(10)
            track_slider.setPageStep(10)
            track_slider.setTickInterval(10)
            track_slider.setValue(100)
            track_slider.setMinimumWidth(62)
            track_slider.setAccessibleName(f"{TRACK_NAMES[track]}轨音量")
            track_slider.setToolTip(f"调整{TRACK_NAMES[track]}轨音量")
            track_slider.valueChanged.connect(
                lambda percentage, selected=track: self._track_volume_changed(selected, percentage)
            )
            self.track_volume_sliders[track] = track_slider
            track_row.addWidget(track_slider, 1)
            track_label = QLabel("100%", tracks_box)
            track_label.setObjectName("volumeValue")
            track_label.setMinimumWidth(34)
            track_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.track_volume_labels[track] = track_label
            track_row.addWidget(track_label)
            track_buttons.addLayout(track_row)
        tracks_layout.addLayout(track_buttons)
        volume_row = QHBoxLayout()
        self.volume_label = QLabel("主音量", tracks_box)
        self.volume_label.setObjectName("volumeLabel")
        volume_row.addWidget(self.volume_label)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal, tracks_box)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(85)
        volume_row.addWidget(self.volume_slider, 1)
        self.volume_value_label = QLabel("85%", tracks_box)
        self.volume_value_label.setObjectName("volumeValue")
        self.volume_value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        volume_row.addWidget(self.volume_value_label)
        tracks_layout.addLayout(volume_row)
        middle.addWidget(tracks_box)

        outputs_box = QGroupBox("舞台三屏输出", self)
        outputs_layout = QVBoxLayout(outputs_box)
        outputs_layout.setSpacing(10)
        self.audience_selector = ScreenSelector()
        self.singer_selector = ScreenSelector()
        self.musician_selector = ScreenSelector()
        self.audience_offset = self._create_offset_spin()
        self.singer_offset = self._create_offset_spin()
        self.singer_offset.setValue(150)
        self.musician_offset = self._create_offset_spin()

        channels = QHBoxLayout()
        channels.setContentsMargins(0, 3, 0, 0)
        channels.setSpacing(9)
        audience_panel = QWidget(outputs_box)
        audience_layout = QVBoxLayout(audience_panel)
        audience_layout.setContentsMargins(0, 0, 0, 0)
        audience_layout.setSpacing(7)
        self.audience_output_button = OutputScreenButton("观众", "#3d8bfd", audience_panel)
        audience_layout.addWidget(self.audience_output_button)
        audience_form = QFormLayout()
        audience_form.setContentsMargins(0, 0, 0, 0)
        audience_form.setSpacing(6)
        self.audience_screen_label = self._create_parameter_label("显示器", audience_panel)
        self.audience_offset_label = self._create_parameter_label("补偿", audience_panel)
        self.audience_font_size_label = self._create_parameter_label("字号", audience_panel)
        audience_form.addRow(self.audience_screen_label, self.audience_selector)
        audience_form.addRow(self.audience_offset_label, self.audience_offset)
        self.audience_font_size = self._create_font_size_spin(36, None, 72)
        audience_form.addRow(self.audience_font_size_label, self.audience_font_size)
        self.audience_background_combo = QComboBox(audience_panel)
        self.audience_background_combo.addItem("随机模式", RANDOM_BACKGROUND_ID)
        audience_form.addRow(
            self._create_parameter_label("播放策略", audience_panel),
            self.audience_background_combo,
        )
        self.audience_font_combo = QComboBox(audience_panel)
        audience_form.addRow(
            self._create_parameter_label("字幕字体", audience_panel),
            self.audience_font_combo,
        )
        audience_layout.addLayout(audience_form)
        audience_layout.addStretch(1)
        channels.addWidget(audience_panel, 1)

        channel_separator = QFrame(outputs_box)
        channel_separator.setObjectName("outputChannelSeparator")
        channel_separator.setFrameShape(QFrame.Shape.VLine)
        channel_separator.setFrameShadow(QFrame.Shadow.Plain)
        channels.addWidget(channel_separator)

        singer_panel = QWidget(outputs_box)
        singer_layout = QVBoxLayout(singer_panel)
        singer_layout.setContentsMargins(0, 0, 0, 0)
        singer_layout.setSpacing(7)
        self.singer_output_button = OutputScreenButton("歌手", "#43cbb4", singer_panel)
        singer_layout.addWidget(self.singer_output_button)
        singer_form = QFormLayout()
        singer_form.setContentsMargins(0, 0, 0, 0)
        singer_form.setSpacing(6)
        self.singer_screen_label = self._create_parameter_label("显示器", singer_panel)
        self.singer_offset_label = self._create_parameter_label("补偿", singer_panel)
        self.singer_font_size_label = self._create_parameter_label("字号", singer_panel)
        singer_form.addRow(self.singer_screen_label, self.singer_selector)
        singer_form.addRow(self.singer_offset_label, self.singer_offset)
        self.singer_font_size = self._create_font_size_spin(24, None, 42)
        singer_form.addRow(self.singer_font_size_label, self.singer_font_size)
        singer_layout.addLayout(singer_form)
        self.singer_beat_lights_checkbox = QCheckBox("显示拍子灯", singer_panel)
        self.singer_music_info_checkbox = QCheckBox("显示歌曲信息", singer_panel)
        self.singer_beat_lights_checkbox.setChecked(False)
        self.singer_beat_lights_checkbox.hide()
        self.singer_music_info_checkbox.setChecked(True)
        singer_layout.addWidget(self.singer_music_info_checkbox)
        singer_web_row = QHBoxLayout()
        singer_web_row.setContentsMargins(0, 2, 0, 0)
        singer_web_row.setSpacing(6)
        self.web_singer_button = QPushButton("开启扫码", singer_panel)
        self.web_singer_button.setCheckable(True)
        self.web_singer_button.setAccessibleName("网页歌手屏开关")
        self.web_singer_button.setToolTip("让同一局域网内的手机或 iPad 打开歌手屏")
        set_button_icon(self.web_singer_button, "playback.svg", QSize(16, 16))
        self.web_singer_qr_button = QPushButton("二维码", singer_panel)
        self.web_singer_qr_button.setToolTip("显示访问二维码和链接")
        set_button_icon(self.web_singer_qr_button, "chord.svg", QSize(16, 16))
        self.web_singer_qr_button.hide()
        singer_web_row.addWidget(self.web_singer_button, 1)
        singer_web_row.addWidget(self.web_singer_qr_button)
        singer_layout.addLayout(singer_web_row)
        singer_layout.addStretch(1)
        channels.addWidget(singer_panel, 1)

        musician_separator = QFrame(outputs_box)
        musician_separator.setObjectName("outputChannelSeparator")
        musician_separator.setFrameShape(QFrame.Shape.VLine)
        musician_separator.setFrameShadow(QFrame.Shadow.Plain)
        channels.addWidget(musician_separator)
        musician_panel = QWidget(outputs_box)
        musician_layout = QVBoxLayout(musician_panel)
        musician_layout.setContentsMargins(0, 0, 0, 0)
        musician_layout.setSpacing(7)
        self.musician_output_button = OutputScreenButton("乐手", "#ffd166", musician_panel)
        musician_layout.addWidget(self.musician_output_button)
        musician_form = QFormLayout()
        musician_form.setContentsMargins(0, 0, 0, 0)
        musician_form.setSpacing(6)
        musician_form.addRow(
            self._create_parameter_label("显示器", musician_panel), self.musician_selector
        )
        self.musician_offset_label = self._create_parameter_label("补偿", musician_panel)
        musician_form.addRow(self.musician_offset_label, self.musician_offset)
        self.musician_font_size_label = self._create_parameter_label("字号", musician_panel)
        self.musician_font_size = self._create_font_size_spin(MUSICIAN_FONT_SIZE_MIN, None, 32)
        self.musician_font_size.setToolTip("调整歌词与和弦字号；有小节拍点时每行显示两小节")
        musician_form.addRow(self.musician_font_size_label, self.musician_font_size)
        musician_layout.addLayout(musician_form)
        self.musician_beat_lights_checkbox = QCheckBox("显示拍子灯", musician_panel)
        self.musician_beat_lights_checkbox.setChecked(False)
        self.musician_beat_lights_checkbox.hide()
        self.beat_prompt_sound_checkbox = QCheckBox("引导拍子声", musician_panel)
        self.beat_prompt_sound_checkbox.setObjectName("beatPromptSoundCheckbox")
        self.beat_prompt_sound_checkbox.setAccessibleName("引导拍子声开关")
        self.beat_prompt_sound_checkbox.setToolTip(
            "打开乐手屏时，从歌曲开头播放前按 BPM 先响两小节；歌曲开始后不再响拍子声"
        )
        musician_layout.addWidget(self.beat_prompt_sound_checkbox)
        web_row = QHBoxLayout()
        web_row.setContentsMargins(0, 2, 0, 0)
        web_row.setSpacing(6)
        self.web_musician_button = QPushButton("开启扫码", musician_panel)
        self.web_musician_button.setCheckable(True)
        set_button_icon(self.web_musician_button, "playback.svg", QSize(16, 16))
        self.web_musician_button.setAccessibleName("网页乐手屏开关")
        self.web_musician_button.setToolTip("让同一局域网内的手机或 iPad 打开乐手谱面")
        self.web_musician_qr_button = QPushButton("二维码", musician_panel)
        set_button_icon(self.web_musician_qr_button, "chord.svg", QSize(16, 16))
        self.web_musician_qr_button.setToolTip("显示访问二维码和链接")
        self.web_musician_qr_button.hide()
        web_row.addWidget(self.web_musician_button, 1)
        web_row.addWidget(self.web_musician_qr_button)
        musician_layout.addLayout(web_row)
        musician_layout.addStretch(1)
        channels.addWidget(musician_panel, 1)
        outputs_layout.addLayout(channels)

        self.audience_output_button.toggled.connect(self.audience_output_toggled)
        self.singer_output_button.toggled.connect(self._singer_output_changed)
        self.musician_output_button.toggled.connect(self.musician_output_toggled)
        middle.addWidget(outputs_box, 1)
        layout.addLayout(middle)

        preview_box = QGroupBox("实时歌词监看", self)
        preview_layout = QVBoxLayout(preview_box)
        self.current_lyric_label = QLabel("当前句：—", preview_box)
        self.next_lyric_label = QLabel("下一句：—", preview_box)
        self.current_lyric_label.setObjectName("currentLyric")
        self.next_lyric_label.setObjectName("nextLyric")
        self.current_lyric_label.setWordWrap(True)
        self.next_lyric_label.setWordWrap(True)
        preview_layout.addWidget(self.current_lyric_label)
        preview_layout.addWidget(self.next_lyric_label)
        layout.addWidget(preview_box)
        self.status_label = QLabel("等待加载", self)
        self.status_label.setObjectName("statusBar")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.previous_song_button.clicked.connect(self.previous_song_requested)
        self.restart_button.clicked.connect(self.restart_requested)
        self.backward_button.clicked.connect(lambda: self._seek_relative(-5_000))
        self.play_button.clicked.connect(self.play_pause_requested)
        self.forward_button.clicked.connect(lambda: self._seek_relative(5_000))
        self.stop_button.clicked.connect(self.stop_requested)
        self.next_song_button.clicked.connect(self.next_song_requested)
        self.auto_play_next_check.toggled.connect(self.auto_play_next_changed)
        self.playback_bpm_spin.valueChanged.connect(self.playback_bpm_requested)
        self.position_slider.sliderReleased.connect(
            lambda: self.seek_requested.emit(self.position_slider.value())
        )
        self.volume_slider.valueChanged.connect(self._volume_changed)
        self.audience_offset.valueChanged.connect(self._emit_offsets)
        self.singer_offset.valueChanged.connect(self._emit_offsets)
        self.musician_offset.valueChanged.connect(self.musician_offset_changed)
        self.audience_font_size.valueChanged.connect(self._emit_font_sizes)
        self.singer_font_size.valueChanged.connect(self._emit_font_sizes)
        self.musician_font_size.valueChanged.connect(self.musician_font_size_changed)
        self.singer_beat_lights_checkbox.toggled.connect(self._emit_singer_display_options)
        self.singer_music_info_checkbox.toggled.connect(self._emit_singer_display_options)
        self.beat_prompt_sound_checkbox.toggled.connect(self.beat_prompt_sound_changed)
        self.musician_beat_lights_checkbox.toggled.connect(self.musician_beat_lights_changed)
        self.web_musician_button.toggled.connect(self.web_musician_toggled)
        self.web_musician_qr_button.clicked.connect(self.web_musician_qr_requested)
        self.web_singer_button.toggled.connect(self.web_singer_toggled)
        self.web_singer_qr_button.clicked.connect(self.web_singer_qr_requested)
        self.audience_background_combo.currentIndexChanged.connect(
            self._background_selection_changed
        )
        self.audience_font_combo.currentIndexChanged.connect(self._audience_font_selected)
        self.set_controls_enabled(False)
        self.previous_song_button.setEnabled(False)
        self.next_song_button.setEnabled(False)
        self.installEventFilter(self)
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)

    @staticmethod
    def _create_offset_spin() -> QSpinBox:
        spin = ParameterSpinBox()
        spin.setRange(-10_000, 10_000)
        spin.setSingleStep(10)
        spin.setSuffix(" ms")
        spin.setToolTip("可用滚轮调整；按 Enter 或点击其他位置后退出编辑")
        return spin

    @staticmethod
    def _create_font_size_spin(minimum: int, maximum: int | None, default: int) -> QSpinBox:
        spin = ParameterSpinBox()
        spin.setMinimum(minimum)
        # 两个输出屏均不设置业务上限，使用 Qt 整数控件支持的最大值。
        spin.setMaximum(maximum if maximum is not None else 2_147_483_647)
        spin.setValue(default)
        spin.setSuffix(" pt")
        spin.setToolTip("可输入或用滚轮调整；按 Enter 或点击其他位置后退出编辑")
        return spin

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            focus_widget = QApplication.focusWidget()
            spin = self._parameter_spin_ancestor(focus_widget)
            target = watched if isinstance(watched, QWidget) else None
            if spin is not None and target is not None:
                clicked_inside_spin = target is spin or spin.isAncestorOf(target)
                if not clicked_inside_spin:
                    spin.clearFocus()
                    spin.lineEdit().deselect()
        return super().eventFilter(watched, event)

    @staticmethod
    def _parameter_spin_ancestor(widget: QWidget | None) -> ParameterSpinBox | None:
        current = widget
        while current is not None:
            if isinstance(current, ParameterSpinBox):
                return current
            current = current.parentWidget()
        return None

    @staticmethod
    def _create_parameter_label(text: str, parent: QWidget) -> QLabel:
        label = QLabel(text, parent)
        label.setProperty("role", "parameterLabel")
        return label

    def set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.restart_button,
            self.backward_button,
            self.play_button,
            self.forward_button,
            self.stop_button,
            self.position_slider,
        ):
            widget.setEnabled(enabled)
        self.playback_bpm_spin.setEnabled(enabled and self._original_bpm > 0)

    def set_next_song(self, title: str | None, artist: str = "") -> None:
        """展示播放队列中的后继歌曲，并同步下一首按钮状态。"""
        if title is None:
            self.next_song_label.setText("下一首：播放列表暂无后续歌曲")
            self.next_song_button.setToolTip("播放列表中没有下一首歌曲")
            self.next_song_button.setEnabled(False)
        else:
            suffix = f" — {artist}" if artist else ""
            self.next_song_label.setText(f"下一首：{title}{suffix}")
            self.next_song_button.setToolTip(f"加载下一首：{title}{suffix}；不会自动播放")
            self.next_song_button.setEnabled(True)

    def set_previous_song(self, title: str | None, artist: str = "") -> None:
        """根据播放列表中的前驱歌曲更新上一首按钮。"""
        if title is None:
            self.previous_song_button.setToolTip("播放列表中没有上一首歌曲")
            self.previous_song_button.setEnabled(False)
        else:
            suffix = f" — {artist}" if artist else ""
            self.previous_song_button.setToolTip(f"加载上一首：{title}{suffix}；不会自动播放")
            self.previous_song_button.setEnabled(True)

    def set_auto_play_next(self, enabled: bool) -> None:
        self.auto_play_next_check.blockSignals(True)
        self.auto_play_next_check.setChecked(enabled)
        self.auto_play_next_check.blockSignals(False)

    def set_background_resources(
        self,
        resources: tuple[BackgroundVideoResource, ...],
        settings: BackgroundVideoSettings,
    ) -> None:
        self.audience_background_combo.blockSignals(True)
        self.audience_background_combo.clear()
        self.audience_background_combo.addItem("随机模式", RANDOM_BACKGROUND_ID)
        for resource in resources:
            self.audience_background_combo.addItem(resource.name, resource.id)
        selected_id = (
            RANDOM_BACKGROUND_ID if settings.mode == "random" else settings.fixed_resource_id
        )
        index = self.audience_background_combo.findData(selected_id)
        if index < 0:
            index = self.audience_background_combo.findData("none")
        self.audience_background_combo.setCurrentIndex(max(0, index))
        self.audience_background_combo.blockSignals(False)

    def set_background_video_settings(self, settings: BackgroundVideoSettings) -> None:
        selected_id = (
            RANDOM_BACKGROUND_ID if settings.mode == "random" else settings.fixed_resource_id
        )
        index = self.audience_background_combo.findData(selected_id)
        if index < 0:
            index = self.audience_background_combo.findData("none")
        self.audience_background_combo.blockSignals(True)
        self.audience_background_combo.setCurrentIndex(max(0, index))
        self.audience_background_combo.blockSignals(False)

    def background_video_settings(self) -> BackgroundVideoSettings:
        selected_id = str(self.audience_background_combo.currentData() or "none")
        if selected_id == RANDOM_BACKGROUND_ID:
            return BackgroundVideoSettings(mode="random", fixed_resource_id="none")
        return BackgroundVideoSettings(mode="fixed", fixed_resource_id=selected_id)

    def _background_selection_changed(self) -> None:
        self.background_video_settings_changed.emit(self.background_video_settings())

    def set_audience_fonts(
        self,
        resources: tuple[AudienceFontResource, ...],
        selected_font_id: str,
    ) -> None:
        self.audience_font_combo.blockSignals(True)
        self.audience_font_combo.clear()
        for resource in resources:
            self.audience_font_combo.addItem(resource.name, resource.id)
            index = self.audience_font_combo.count() - 1
            self.audience_font_combo.setItemData(
                index,
                QFont(resource.family, 14),
                Qt.ItemDataRole.FontRole,
            )
        self.set_audience_font_id(selected_font_id)
        self.audience_font_combo.blockSignals(False)

    def set_audience_font_id(self, font_id: str) -> None:
        index = self.audience_font_combo.findData(font_id)
        self.audience_font_combo.blockSignals(True)
        self.audience_font_combo.setCurrentIndex(max(0, index))
        self.audience_font_combo.blockSignals(False)

    def audience_font_id(self) -> str:
        return str(self.audience_font_combo.currentData() or "default")

    def _audience_font_selected(self) -> None:
        self.audience_font_changed.emit(self.audience_font_id())

    def set_beat_prompt_sound_enabled(self, enabled: bool) -> None:
        self.beat_prompt_sound_checkbox.blockSignals(True)
        self.beat_prompt_sound_checkbox.setChecked(enabled)
        self.beat_prompt_sound_checkbox.blockSignals(False)

    def beat_prompt_sound_enabled(self) -> bool:
        return self.beat_prompt_sound_checkbox.isChecked()

    def set_singer_display_options(self, beat_lights: bool, music_info: bool) -> None:
        for checkbox, checked in (
            (self.singer_beat_lights_checkbox, False),
            (self.singer_music_info_checkbox, music_info),
        ):
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)

    def _emit_singer_display_options(self, _checked: bool) -> None:
        self.singer_display_options_changed.emit(
            self.singer_beat_lights_checkbox.isChecked(),
            self.singer_music_info_checkbox.isChecked(),
        )

    def set_musician_beat_lights_visible(self, visible: bool) -> None:
        self.musician_beat_lights_checkbox.blockSignals(True)
        self.musician_beat_lights_checkbox.setChecked(False)
        self.musician_beat_lights_checkbox.blockSignals(False)

    def set_web_musician_state(self, enabled: bool) -> None:
        self.web_musician_button.blockSignals(True)
        self.web_musician_button.setChecked(enabled)
        self.web_musician_button.setText("关闭扫码" if enabled else "开启扫码")
        self.web_musician_button.blockSignals(False)
        self.web_musician_qr_button.setVisible(enabled)

    def set_web_singer_state(self, enabled: bool) -> None:
        self.web_singer_button.blockSignals(True)
        self.web_singer_button.setChecked(enabled)
        self.web_singer_button.setText("关闭扫码" if enabled else "开启扫码")
        self.web_singer_button.blockSignals(False)
        self.web_singer_qr_button.setVisible(enabled)

    def set_loading(self, title: str, artist: str = "", *, validating: bool = False) -> None:
        suffix = f" — {artist}" if artist else ""
        self.song_label.setText(f"{title}{suffix}")
        self.music_info_label.clear()
        self.music_info_label.hide()
        self.state_label.setText("正在加载")
        self.status_label.setText(
            "正在后台完整校验歌曲包……" if validating else "正在后台解码音轨……"
        )
        self.set_controls_enabled(False)
        self.previous_song_button.setEnabled(False)
        self.next_song_button.setEnabled(False)

    def set_empty_playlist(self, *, unavailable: bool = False) -> None:
        self.song_label.setText(
            "播放列表中没有可播放歌曲" if unavailable else "播放列表为空，请先添加歌曲"
        )
        self.music_info_label.clear()
        self.music_info_label.hide()
        self.state_label.setText("未加载歌曲")
        self.set_controls_enabled(False)
        self.set_previous_song(None)
        self.set_next_song(None)

    def set_loading_failed(self, message: str) -> None:
        self.state_label.setText("加载失败")
        self.status_label.setText(f"错误：{message}")
        self.set_controls_enabled(False)

    def set_song(
        self,
        title: str,
        artist: str,
        duration_ms: int,
        original_key: str = "",
        bpm: int = 0,
    ) -> None:
        suffix = f" — {artist}" if artist else ""
        self.song_label.setText(f"{title}{suffix}")
        normalized_key = original_key.strip()
        self._original_bpm = bpm if bpm > 0 else 0
        self.playback_bpm_spin.blockSignals(True)
        if self._original_bpm:
            self.playback_bpm_spin.setRange(
                max(20, math.ceil(self._original_bpm * 0.2)),
                min(400, self._original_bpm * 2),
            )
            self.playback_bpm_spin.setValue(self._original_bpm)
        else:
            self.playback_bpm_spin.setRange(0, 400)
            self.playback_bpm_spin.setValue(0)
        self.playback_bpm_spin.blockSignals(False)
        if normalized_key and bpm > 0:
            self.music_info_label.setText(f"原KEY {normalized_key}  ·  {bpm} BPM")
            self.music_info_label.show()
        else:
            self.music_info_label.clear()
            self.music_info_label.hide()
        self._duration_ms = duration_ms
        self.position_slider.setRange(0, duration_ms)
        self.duration_label.setText(format_time_ms(duration_ms))
        self.status_label.setText("歌曲已加载")
        self.set_controls_enabled(True)

    def set_position(self, position_ms: int) -> None:
        position_ms = max(0, min(self._duration_ms, position_ms))
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(position_ms)
        self.current_time_label.setText(format_time_ms(position_ms))

    def set_playback_state(self, state: str) -> None:
        names = {
            "empty": "未加载",
            "stopped": "已停止",
            "playing": "播放中",
            "paused": "已暂停",
            "ended": "播放结束",
            "error": "播放错误",
        }
        self.state_label.setText(names.get(state, state))
        playing = state == "playing"
        set_button_icon(
            self.play_button,
            "pause.svg" if playing else "play.svg",
            QSize(18, 18),
        )
        self.play_button.setAccessibleName("暂停" if playing else "播放")
        self.play_button.setToolTip("暂停（空格键）" if playing else "播放（空格键）")

    def set_track_mutes(self, values: dict[TrackKind, bool]) -> None:
        for track, check in self.track_checks.items():
            check.blockSignals(True)
            check.setChecked(values.get(track, False))
            check.blockSignals(False)
            self._update_track_volume_enabled(track)

    def set_track_gains_db(self, values: dict[TrackKind, float]) -> None:
        for track, slider in self.track_volume_sliders.items():
            gain_db = values.get(track, 0.0)
            percentage = 0 if gain_db <= -96.0 else round(100 * math.pow(10.0, gain_db / 20.0))
            percentage = self._snap_track_volume(percentage)
            slider.blockSignals(True)
            slider.setValue(percentage)
            slider.blockSignals(False)
            self.track_volume_labels[track].setText(f"{percentage}%")

    def set_available_tracks(self, tracks: set[TrackKind]) -> None:
        """隐藏旧四轨歌曲包中不存在的六轨控件。"""
        self._available_tracks = set(tracks)
        for track, button in self.track_checks.items():
            available = track in tracks
            button.setEnabled(available)
            button.setVisible(available)
            self.track_volume_sliders[track].setVisible(available)
            self.track_volume_labels[track].setVisible(available)
            self._update_track_volume_enabled(track)

    def set_master_volume(self, value: float) -> None:
        percentage = round(max(0.0, min(1.0, value)) * 100)
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(percentage)
        self.volume_slider.blockSignals(False)
        self.volume_value_label.setText(f"{percentage}%")

    def _track_volume_changed(self, track: TrackKind, percentage: int) -> None:
        percentage = self._snap_track_volume(percentage)
        slider = self.track_volume_sliders[track]
        if slider.value() != percentage:
            slider.blockSignals(True)
            slider.setValue(percentage)
            slider.blockSignals(False)
        self.track_volume_labels[track].setText(f"{percentage}%")
        gain_db = -96.0 if percentage == 0 else 20.0 * math.log10(percentage / 100.0)
        self.track_gain_requested.emit(track.value, gain_db)

    def _track_mute_changed(self, track: TrackKind, muted: bool) -> None:
        self._update_track_volume_enabled(track)
        self.track_mute_requested.emit(track.value, muted)

    def _update_track_volume_enabled(self, track: TrackKind) -> None:
        enabled = (
            track in self._available_tracks
            and not self.track_checks[track].isChecked()
        )
        self.track_volume_sliders[track].setEnabled(enabled)
        self.track_volume_labels[track].setEnabled(enabled)

    @staticmethod
    def _snap_track_volume(percentage: int) -> int:
        return max(0, min(150, ((percentage + 5) // 10) * 10))

    def set_lyrics_preview(self, current: str, next_text: str) -> None:
        self.current_lyric_label.setText(f"当前句：{current or '—'}")
        self.next_lyric_label.setText(f"下一句：{next_text or '—'}")

    def set_screens(
        self,
        screens: tuple[ScreenDescriptor, ...],
        audience_fingerprint: str,
        singer_fingerprint: str,
        musician_fingerprint: str = "",
    ) -> None:
        self.audience_selector.set_screens(screens, audience_fingerprint)
        self.singer_selector.set_screens(screens, singer_fingerprint)
        self.musician_selector.set_screens(screens, musician_fingerprint)
        if not audience_fingerprint and screens:
            self.audience_selector.setCurrentIndex(0)
        if not singer_fingerprint and len(screens) > 1:
            self.singer_selector.setCurrentIndex(1)
        if not musician_fingerprint and screens:
            self.musician_selector.setCurrentIndex(min(2, len(screens) - 1))

    def set_offsets(self, audience_ms: int, singer_ms: int, musician_ms: int = 0) -> None:
        self.audience_offset.blockSignals(True)
        self.singer_offset.blockSignals(True)
        self.musician_offset.blockSignals(True)
        self.audience_offset.setValue(audience_ms)
        self.singer_offset.setValue(singer_ms)
        self.musician_offset.setValue(musician_ms)
        self.audience_offset.blockSignals(False)
        self.singer_offset.blockSignals(False)
        self.musician_offset.blockSignals(False)

    def set_subtitle_font_sizes(self, audience: int, singer: int, musician: int = 32) -> None:
        """更新字号控件，但不触发用户调整信号。"""
        self.audience_font_size.blockSignals(True)
        self.singer_font_size.blockSignals(True)
        self.musician_font_size.blockSignals(True)
        self.audience_font_size.setValue(audience)
        self.singer_font_size.setValue(singer)
        self.musician_font_size.setValue(musician)
        self.audience_font_size.blockSignals(False)
        self.singer_font_size.blockSignals(False)
        self.musician_font_size.blockSignals(False)

    def set_output_states(self, audience_open: bool, singer_open: bool) -> None:
        """同步输出窗口状态，但不回发用户切换信号。"""
        self.audience_output_button.blockSignals(True)
        self.singer_output_button.blockSignals(True)
        self.audience_output_button.setChecked(audience_open)
        self.singer_output_button.setChecked(singer_open)
        self.audience_output_button.blockSignals(False)
        self.singer_output_button.blockSignals(False)

    def set_musician_output_state(self, open_: bool) -> None:
        self.musician_output_button.blockSignals(True)
        self.musician_output_button.setChecked(open_)
        self.musician_output_button.blockSignals(False)

    def show_status(self, message: str) -> None:
        self.status_label.setText(public_message(message, "操作失败，请重试"))

    def _singer_output_changed(self, enabled: bool) -> None:
        self.singer_output_toggled.emit(enabled)

    def _seek_relative(self, delta_ms: int) -> None:
        self.seek_requested.emit(self.position_slider.value() + delta_ms)

    def _volume_changed(self, value: int) -> None:
        self.volume_value_label.setText(f"{value}%")
        self.master_volume_requested.emit(value / 100.0)

    def _emit_offsets(self) -> None:
        self.offsets_changed.emit(self.audience_offset.value(), self.singer_offset.value())

    def _emit_font_sizes(self) -> None:
        self.subtitle_font_sizes_changed.emit(
            self.audience_font_size.value(), self.singer_font_size.value()
        )
