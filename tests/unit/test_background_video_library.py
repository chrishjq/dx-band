# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import subprocess
from pathlib import Path

import pytest

from dxband.ui.services.background_video_library import (
    NO_BACKGROUND_ID,
    BackgroundVideoLibrary,
)


def test_resources_include_none_built_ins_and_uploaded_videos(tmp_path: Path) -> None:
    built_in_root = tmp_path / "built-ins"
    user_root = tmp_path / "uploads"
    built_in_root.mkdir()
    user_root.mkdir()
    (built_in_root / "Ethereal_Wave_1080p_Loop.mp4").write_bytes(b"preset")
    (user_root / "custom.mov").write_bytes(b"custom")
    library = BackgroundVideoLibrary(
        built_in_root=built_in_root,
        user_root=user_root,
    )

    resources = library.resources()

    assert resources[0].id == NO_BACKGROUND_ID
    assert [resource.id for resource in resources[1:]] == [
        "builtin:Ethereal_Wave_4K_Motion_Background_Loop.mp4",
        "user:custom.mov",
    ]
    assert not resources[1].deletable
    assert resources[1].path == built_in_root / "Ethereal_Wave_1080p_Loop.mp4"
    assert resources[2].deletable


def test_import_uses_unique_names_and_only_uploaded_videos_can_be_deleted(
    tmp_path: Path, monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def transcode(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        Path(command[-1]).write_bytes(b"optimized")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "dxband.ui.services.background_video_library.shutil.which",
        lambda _name: "/usr/bin/ffmpeg",
    )
    monkeypatch.setattr(
        "dxband.ui.services.background_video_library.subprocess.run",
        transcode,
    )
    source = tmp_path / "loop.mp4"
    source.write_bytes(b"video")
    library = BackgroundVideoLibrary(
        built_in_root=tmp_path / "built-ins",
        user_root=tmp_path / "uploads",
    )

    first = library.import_file(source)
    second = library.import_file(source)

    assert first.id == "user:loop.mp4"
    assert second.id == "user:loop (2).mp4"
    assert first.path is not None and first.path.read_bytes() == b"optimized"
    assert commands[0][commands[0].index("-vf") + 1] == (
        "fps=15,scale=1920:1080:flags=lanczos:"
        "force_original_aspect_ratio=decrease:force_divisible_by=2"
    )
    library.delete(first.id)
    assert library.find(first.id) is None
    with pytest.raises(ValueError, match="系统预设"):
        library.delete(NO_BACKGROUND_ID)


def test_import_rejects_unsupported_files(tmp_path: Path) -> None:
    source = tmp_path / "background.txt"
    source.write_text("not video", encoding="utf-8")
    library = BackgroundVideoLibrary(
        built_in_root=tmp_path / "built-ins",
        user_root=tmp_path / "uploads",
    )

    with pytest.raises(ValueError, match="仅支持"):
        library.import_file(source)
