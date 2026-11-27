# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from dxband.creation.model_download import ModelRoleStatus
from dxband.ui.pages.settings_page import SettingsPage


def test_settings_page_shows_functional_model_status_and_unified_download(
    qtbot: QtBot,
) -> None:
    page = SettingsPage()
    qtbot.addWidget(page)
    requested: list[bool] = []
    page.missing_resources_download_requested.connect(lambda: requested.append(True))

    page.set_model_statuses(
        (
            ModelRoleStatus(
                key="beat",
                label="节拍模型",
                detail="分析拍点与小节",
                ready=False,
            ),
            ModelRoleStatus(
                key="lyric_align_zh",
                label="中文歌词适配模型",
                detail="对齐国语歌词时间",
                ready=True,
            ),
        ),
        has_missing=True,
    )

    assert any(label.text() == "创建所需资源" for label in page.findChildren(QLabel))
    titles = {row.title_label.text() for row in page._model_rows.values()}
    assert titles == {"节拍模型", "中文歌词适配模型"}
    assert "SheetSage2" not in " ".join(titles)
    assert page._model_rows["beat"].status_label.text() == "未下载"
    assert page._model_rows["lyric_align_zh"].status_label.text() == "已就绪"
    assert not hasattr(page._model_rows["beat"], "download_button")
    assert page.download_missing_button.isEnabled()
    assert page.download_missing_button.text() == "下载缺失资源"

    page.download_missing_button.click()
    assert requested == [True]

    page.set_model_statuses(
        (
            ModelRoleStatus(
                key="beat",
                label="节拍模型",
                detail="分析拍点与小节",
                ready=False,
            ),
        ),
        busy_key="beat",
        has_missing=True,
    )
    assert page._model_rows["beat"].status_label.text() == "下载中"
    assert page.download_missing_button.text() == "下载中…"
    assert not page.download_missing_button.isEnabled()
