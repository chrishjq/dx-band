# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

import pytest

from dxband.services import bundle_paths


def test_helper_script_uses_repository_in_source() -> None:
    path = bundle_paths.helper_script("run_beat_this.py")
    assert path.name == "run_beat_this.py"
    assert path.is_file()
    assert path.parent.name == "scripts"


def test_helper_script_uses_meipass_when_frozen(monkeypatch, tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    target = scripts / "run_sheetsage2.py"
    target.write_text("# test\n", encoding="utf-8")
    monkeypatch.setattr(bundle_paths, "is_frozen", lambda: True)
    monkeypatch.setattr(bundle_paths, "meipass_root", lambda: tmp_path)

    assert bundle_paths.helper_script("run_sheetsage2.py") == target


def test_repository_root_rejects_frozen(monkeypatch) -> None:
    monkeypatch.setattr(bundle_paths, "is_frozen", lambda: True)
    with pytest.raises(RuntimeError):
        bundle_paths.repository_root()
