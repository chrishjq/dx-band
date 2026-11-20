# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QLabel, QPushButton
from pytestqt.qtbot import QtBot

from dxband.ui.page_layout import (
    PAGE_CONTENT_MARGINS,
    PAGE_SECTION_SPACING,
)
from dxband.ui.pages.library_page import LibraryPage
from dxband.ui.pages.playback_page import PlaybackPage
from dxband.ui.pages.playlist_page import PlaylistPage
from dxband.ui.pages.settings_page import SettingsPage


def test_primary_pages_share_margins_headings_and_button_icons(
    qtbot: QtBot,
) -> None:
    pages = (LibraryPage(), PlaylistPage(), PlaybackPage(), SettingsPage())
    title_tops: list[int] = []
    subtitle_tops: list[int] = []
    for page in pages:
        qtbot.addWidget(page)
        page.resize(1066, 800)
        page.show()
        layout = page.layout()
        assert layout is not None
        margins = layout.contentsMargins()
        assert (
            margins.left(),
            margins.top(),
            margins.right(),
            margins.bottom(),
        ) == PAGE_CONTENT_MARGINS
        assert layout.spacing() == PAGE_SECTION_SPACING

        title = page.findChild(QLabel, "pageTitle")
        subtitle = page.findChild(QLabel, "pageSubtitle")
        assert title is not None
        assert subtitle is not None
        title_tops.append(title.mapTo(page, QPoint()).y())
        subtitle_tops.append(subtitle.mapTo(page, QPoint()).y())

        buttons = page.findChildren(QPushButton)
        assert buttons
        action_buttons = [button for button in buttons if button.property("role") != "segment"]
        assert all(not button.icon().isNull() for button in action_buttons)
        assert len({button.font().pointSize() for button in buttons}) == 1

    assert len(set(title_tops)) == 1
    assert len(set(subtitle_tops)) == 1


def test_primary_pages_do_not_show_decorative_english_headings(
    qtbot: QtBot,
) -> None:
    pages = (PlaybackPage(), SettingsPage())
    for page in pages:
        qtbot.addWidget(page)
    visible_copy = " ".join(label.text() for page in pages for label in page.findChildren(QLabel))

    for removed_text in (
        "NOW PLAYING",
        "GENERAL",
        "AUDIENCE DISPLAY",
        "LIVE PREVIEW",
        "LOOPS",
        "STRETCH",
    ):
        assert removed_text not in visible_copy
