# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pytestqt.qtbot import QtBot

from dxband.creation.model_download import ModelRoleStatus
from dxband.ui.pages.settings_page import SettingsPage


def test_settings_page_shows_download_progress_and_row_percent(qtbot: QtBot) -> None:
    page = SettingsPage()
    qtbot.addWidget(page)
    page.set_model_statuses(
        (
            ModelRoleStatus(
                key="lyric_recognition",
                label="歌词识别模型",
                detail="从人声识别歌词文字",
                ready=False,
            ),
        ),
        busy_key="lyric_recognition",
        has_missing=True,
    )

    assert page.download_progress.isHidden()
    page.set_download_progress(-1.0)
    assert not page.download_progress.isHidden()
    assert page.download_progress.minimum() == 0
    assert page.download_progress.maximum() == 0

    page.set_download_progress(0.42)
    page.update_busy_download_progress(0.42)
    assert page.download_progress.maximum() == 100
    assert page.download_progress.value() == 42
    assert page._model_rows["lyric_recognition"].status_label.text() == "42%"
    # Status text keeps the stage only; the progress bar owns the percentage.
    page.show_status("正在下载歌词识别模型", trusted=True)
    assert not page.status_label.isHidden()
    assert page.status_label.text() == "正在下载歌词识别模型"
    assert "（" not in page.status_label.text()
    assert page.download_missing_button.text() == "下载中…"

    page.set_model_statuses(
        (
            ModelRoleStatus(
                key="lyric_recognition",
                label="歌词识别模型",
                detail="从人声识别歌词文字",
                ready=True,
            ),
        ),
        busy_key=None,
        has_missing=False,
    )
    assert page.download_progress.isHidden()
    assert page._model_rows["lyric_recognition"].status_label.text() == "已就绪"
    assert page.download_missing_button.text() == "资源已就绪"
