# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from dxband.creation.model_download import ModelRoleStatus
from dxband.ui.pages.settings_page import SettingsPage


def test_settings_page_shows_functional_model_status_and_download(
    qtbot: QtBot,
) -> None:
    page = SettingsPage()
    qtbot.addWidget(page)
    requested: list[str] = []
    page.model_download_requested.connect(requested.append)

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
        )
    )

    assert any(label.text() == "创建歌曲模型" for label in page.findChildren(QLabel))
    titles = {row.title_label.text() for row in page._model_rows.values()}
    assert titles == {"节拍模型", "中文歌词适配模型"}
    assert "SheetSage2" not in " ".join(titles)
    assert page._model_rows["beat"].download_button.isEnabled()
    assert page._model_rows["lyric_align_zh"].download_button.text() == "已下载"
    assert not page._model_rows["lyric_align_zh"].download_button.isEnabled()

    page._model_rows["beat"].download_button.click()
    assert requested == ["beat"]

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
    )
    assert page._model_rows["beat"].status_label.text() == "下载中"
    assert not page._model_rows["beat"].download_button.isEnabled()
