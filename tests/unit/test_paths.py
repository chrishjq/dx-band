# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

import pytest

from dxband.services.paths import UnsafeRelativePathError, resolve_package_path


@pytest.mark.parametrize("path", ["../track.mp3", "/tmp/track.mp3", "a/../../track.mp3", r"..\x"])
def test_unsafe_relative_paths_are_rejected(tmp_path: Path, path: str) -> None:
    with pytest.raises(UnsafeRelativePathError):
        resolve_package_path(tmp_path, path)


def test_safe_relative_path_is_resolved(tmp_path: Path) -> None:
    assert resolve_package_path(tmp_path, "assets/cover.jpg") == tmp_path / "assets" / "cover.jpg"
