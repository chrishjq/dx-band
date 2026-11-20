# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtCore import QRectF, Qt
from pytestqt.qtbot import QtBot

from dxband.constants import TrackKind
from dxband.ui.widgets.track_mute_button import TRACK_ICON_PATHS, TrackMuteButton


def test_track_button_uses_checked_state_for_mute(qtbot: QtBot) -> None:
    button = TrackMuteButton(TrackKind.VOCALS, "人声")
    qtbot.addWidget(button)
    values: list[bool] = []
    button.toggled.connect(values.append)
    button.show()

    assert not button.isChecked()
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert button.isChecked()
    assert values == [True]
    assert "彩色为启用，灰色为静音" in button.toolTip()
    assert button._icon_renderer.isValid()


def test_each_track_button_has_its_own_instrument_mode(qtbot: QtBot) -> None:
    buttons = {
        track: TrackMuteButton(track, label)
        for track, label in {
            TrackKind.VOCALS: "人声",
            TrackKind.DRUMS: "鼓组",
            TrackKind.BASS: "贝斯",
            TrackKind.GUITAR: "吉他",
            TrackKind.PIANO: "钢琴",
            TrackKind.OTHER: "其他",
        }.items()
    }
    for track, button in buttons.items():
        qtbot.addWidget(button)
        assert button.track is track
        assert button.property("track") == track.value
        assert button._icon_renderer.isValid()

    assert TRACK_ICON_PATHS[TrackKind.BASS].name == "bass-clef.svg"
    assert TRACK_ICON_PATHS[TrackKind.PIANO].name == "piano-keys.svg"
    assert TRACK_ICON_PATHS[TrackKind.BASS] != TRACK_ICON_PATHS[TrackKind.GUITAR]
    assert TRACK_ICON_PATHS[TrackKind.PIANO] != TRACK_ICON_PATHS[TrackKind.OTHER]


def test_microphone_icon_keeps_original_aspect_ratio(qtbot: QtBot) -> None:
    button = TrackMuteButton(TrackKind.VOCALS, "人声")
    qtbot.addWidget(button)

    target = button._fitted_icon_rect(QRectF(6, 6, 84, 84))

    assert abs(target.width() / target.height() - 0.75) < 0.001
    assert target.height() == 84


def test_track_button_places_icon_and_title_in_one_row(qtbot: QtBot) -> None:
    button = TrackMuteButton(TrackKind.VOCALS, "人声")
    qtbot.addWidget(button)

    card = QRectF(1, 1, button.sizeHint().width() - 2, button.sizeHint().height() - 2)
    icon_rect, label_rect = button._content_rects(card)

    assert button.sizeHint().width() > button.sizeHint().height()
    assert label_rect.left() > icon_rect.right()
    assert label_rect.center().y() == icon_rect.center().y()
