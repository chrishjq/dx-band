# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

from dxband.services import application_paths


def test_default_library_uses_existing_previous_location(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(application_paths.Path, "home", lambda: tmp_path)
    previous = tmp_path / "Music" / "DXStageLibrary"
    previous.mkdir(parents=True)

    assert application_paths.default_library_root() == previous

    current = tmp_path / "Music" / "DXBandLibrary"
    current.mkdir()
    assert application_paths.default_library_root() == current


def test_default_library_uses_new_name_on_clean_machine(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(application_paths.Path, "home", lambda: tmp_path)
    assert application_paths.default_library_root() == tmp_path / "Music" / "DXBandLibrary"
