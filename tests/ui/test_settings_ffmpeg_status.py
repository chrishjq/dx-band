# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from dxband.services.ffmpeg_tools import FFmpegStatus
from dxband.ui.pages.settings_page import SettingsPage


def test_settings_page_shows_ffmpeg_download_row(qtbot: QtBot) -> None:
    page = SettingsPage()
    qtbot.addWidget(page)
    requested: list[bool] = []
    page.ffmpeg_download_requested.connect(lambda: requested.append(True))

    page.set_ffmpeg_status(
        FFmpegStatus(
            ready=False,
            source="missing",
            ffmpeg_path=None,
            ffprobe_path=None,
            download_supported=True,
        )
    )

    assert any(label.text() == "运行组件" for label in page.findChildren(QLabel))
    assert page.ffmpeg_row.title_label.text() == "FFmpeg"
    assert page.ffmpeg_row.download_button.isEnabled()
    page.ffmpeg_row.download_button.click()
    assert requested == [True]

    page.set_ffmpeg_status(
        FFmpegStatus(
            ready=True,
            source="managed",
            ffmpeg_path=None,
            ffprobe_path=None,
            download_supported=True,
        )
    )
    assert page.ffmpeg_row.download_button.text() == "已就绪"
    assert not page.ffmpeg_row.download_button.isEnabled()
