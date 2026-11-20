# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dxband.ui.render.singer_widget import SingerWidget


def test_singer_countdown_uses_whole_seconds() -> None:
    assert SingerWidget.format_countdown(12_400) == "13 秒下句"
    assert SingerWidget.format_countdown(12_000) == "12 秒下句"
    assert SingerWidget.format_countdown(1) == "1 秒下句"
