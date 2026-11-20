# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import os
from pathlib import Path

from dxband.services import runtime_environment


def test_runtime_environment_adds_existing_homebrew_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    tool_directory = tmp_path / "homebrew" / "bin"
    tool_directory.mkdir(parents=True)
    original_is_dir = Path.is_dir

    def fake_is_dir(path: Path) -> bool:
        if path == Path("/opt/homebrew/bin"):
            return True
        return original_is_dir(path)

    monkeypatch.setattr(runtime_environment.sys, "platform", "darwin")
    monkeypatch.setattr(runtime_environment.Path, "is_dir", fake_is_dir)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    runtime_environment.configure_runtime_environment()

    assert os.environ["PATH"].split(os.pathsep)[0] == "/opt/homebrew/bin"
