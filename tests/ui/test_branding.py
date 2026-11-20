# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import sys

import pytest
from pytestqt.qtbot import QtBot

from dxband.ui import branding


def test_windows_application_icon_loads_ico(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    icon = branding.application_icon()

    assert not icon.isNull()
    assert not icon.pixmap(32, 32).isNull()
