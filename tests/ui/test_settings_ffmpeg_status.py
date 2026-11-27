# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from dxband.services.ffmpeg_tools import FFmpegStatus
from dxband.ui.pages.settings_page import SettingsPage


def test_settings_page_shows_ffmpeg_in_unified_resources(qtbot: QtBot) -> None:
    page = SettingsPage()
    qtbot.addWidget(page)
    requested: list[bool] = []
    page.missing_resources_download_requested.connect(lambda: requested.append(True))

    page.set_ffmpeg_status(
        FFmpegStatus(
            ready=False,
            source="missing",
            ffmpeg_path=None,
            ffprobe_path=None,
            download_supported=True,
            managed_present=False,
        )
    )
    page.set_model_statuses((), has_missing=True)

    assert any(label.text() == "创建所需资源" for label in page.findChildren(QLabel))
    assert page.ffmpeg_row.title_label.text() == "多媒体组件"
    assert page.ffmpeg_row.status_label.text() == "未下载"
    assert not hasattr(page.ffmpeg_row, "download_button")
    assert page.download_missing_button.isEnabled()
    assert page.download_missing_button.text() == "下载缺失资源"
    page.download_missing_button.click()
    assert requested == [True]

    page.set_ffmpeg_status(
        FFmpegStatus(
            ready=True,
            source="managed",
            ffmpeg_path=None,
            ffprobe_path=None,
            download_supported=True,
            managed_present=True,
        )
    )
    page.set_model_statuses((), has_missing=False)
    assert page.ffmpeg_row.status_label.text() == "已就绪"
    assert page.download_missing_button.text() == "资源已就绪"
    assert not page.download_missing_button.isEnabled()


def test_settings_page_marks_ffmpeg_needs_repair(qtbot: QtBot) -> None:
    page = SettingsPage()
    qtbot.addWidget(page)

    page.set_ffmpeg_status(
        FFmpegStatus(
            ready=False,
            source="missing",
            ffmpeg_path=None,
            ffprobe_path=None,
            download_supported=True,
            managed_present=True,
        )
    )
    assert page.ffmpeg_row.status_label.text() == "需修复"
    assert "自动修复" in page.ffmpeg_row.detail_label.text()
    assert page.download_missing_button.isEnabled()
