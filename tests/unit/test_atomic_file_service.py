# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dxband.creation import package_builder
from dxband.creation.package_builder import PackageBuilder
from dxband.services import atomic_file_service
from dxband.services.atomic_file_service import atomic_write_json


def test_atomic_write_json_replaces_existing_file(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "data.json"
    atomic_write_json(destination, {"version": 1})
    atomic_write_json(destination, {"version": 2, "title": "中文"})

    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "version": 2,
        "title": "中文",
    }
    assert list(destination.parent.glob("*.tmp")) == []


def test_windows_atomic_write_keeps_file_fsync_without_opening_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory_open = Mock(side_effect=AssertionError("Windows cannot open a directory"))
    file_fsync = Mock(wraps=os.fsync)
    monkeypatch.setattr(
        atomic_file_service,
        "os",
        SimpleNamespace(name="nt", open=directory_open, fsync=file_fsync, replace=os.replace),
    )
    destination = tmp_path / "job" / "job.json"

    atomic_write_json(destination, {"state": "idle"})

    assert json.loads(destination.read_text(encoding="utf-8")) == {"state": "idle"}
    file_fsync.assert_called_once()
    directory_open.assert_not_called()


def test_windows_package_sync_keeps_files_without_opening_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory_open = Mock(side_effect=AssertionError("Windows cannot open a directory"))

    def fsync_like_windows(descriptor: int) -> None:
        os.write(descriptor, b"")
        os.fsync(descriptor)

    file_fsync = Mock(side_effect=fsync_like_windows)
    monkeypatch.setattr(
        atomic_file_service,
        "os",
        SimpleNamespace(name="nt", open=directory_open),
    )
    monkeypatch.setattr(package_builder, "os", SimpleNamespace(name="nt", fsync=file_fsync))
    (tmp_path / "song.json").write_text("{}", encoding="utf-8")

    PackageBuilder._fsync_package(tmp_path)
    atomic_file_service.fsync_directory(tmp_path)

    file_fsync.assert_called_once()
    directory_open.assert_not_called()
