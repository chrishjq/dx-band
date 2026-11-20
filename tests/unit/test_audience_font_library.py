# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pytestqt.qtbot import QtBot

from dxband.ui.services.audience_font_library import AudienceFontLibrary


def test_bundled_audience_fonts_register_with_ofl_licenses(qtbot: QtBot) -> None:
    del qtbot  # QApplication must exist before application fonts can be registered.
    library = AudienceFontLibrary()

    resources = library.resources()

    assert [resource.id for resource in resources] == [
        "default",
        "mashanzheng",
        "longcang",
        "zcoolxiaowei",
        "zcoolqingkehuangyou",
    ]
    assert all(resource.family for resource in resources)
    ofl_resource_ids = {
        "mashanzheng",
        "longcang",
        "zcoolxiaowei",
        "zcoolqingkehuangyou",
    }
    for resource in resources:
        if resource.id not in ofl_resource_ids:
            continue
        assert resource.path is not None
        license_path = resource.path.parent / "OFL.txt"
        assert "SIL Open Font License" in license_path.read_text(encoding="utf-8")
    assert library.find("yshi_written").id == "default"
    assert library.find("lemi_shiguang").id == "default"


def test_unknown_audience_font_falls_back_to_default(qtbot: QtBot) -> None:
    del qtbot
    library = AudienceFontLibrary()

    assert library.find("missing").id == "default"
