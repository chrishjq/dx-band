# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dxband import __main__


def test_console_script_exposes_main_function() -> None:
    assert callable(__main__.main)
