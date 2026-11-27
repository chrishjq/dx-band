# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import gzip
from pathlib import Path

import pytest

from dxband.services import ffmpeg_tools


def test_resolve_prefers_managed_over_missing_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ffmpeg = bin_dir / "ffmpeg"
    ffprobe = bin_dir / "ffprobe"
    ffmpeg.write_bytes(b"#!/bin/sh\n")
    ffprobe.write_bytes(b"#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    ffprobe.chmod(0o755)
    monkeypatch.setattr(ffmpeg_tools, "managed_bin_dir", lambda: bin_dir)
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda _name: None)
    monkeypatch.delenv("DX_BAND_FFMPEG", raising=False)
    monkeypatch.delenv("DX_BAND_FFPROBE", raising=False)
    monkeypatch.setattr(ffmpeg_tools, "bundled_bin_dir", lambda: None)

    assert ffmpeg_tools.resolve_ffmpeg() == ffmpeg
    assert ffmpeg_tools.resolve_ffprobe() == ffprobe
    status = ffmpeg_tools.ffmpeg_status()
    assert status.ready
    assert status.source == "managed"
    assert status.managed_present is True


def test_ensure_ffmpeg_on_path_prepends_managed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setattr(ffmpeg_tools, "managed_bin_dir", lambda: bin_dir)
    monkeypatch.setattr(ffmpeg_tools, "bundled_bin_dir", lambda: None)
    monkeypatch.setenv("PATH", "/usr/bin")

    ffmpeg_tools.ensure_ffmpeg_on_path()

    assert Path(ffmpeg_tools.os.environ["PATH"].split(ffmpeg_tools.os.pathsep)[0]) == bin_dir


def test_download_ffmpeg_installs_gunzipped_binaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "managed"
    monkeypatch.setattr(ffmpeg_tools, "managed_bin_dir", lambda: destination)
    monkeypatch.setattr(ffmpeg_tools, "_asset_key", lambda: "darwin-arm64")
    monkeypatch.setattr(ffmpeg_tools.sys, "platform", "darwin")

    payloads = {
        "ffmpeg": b"fake-ffmpeg-bytes",
        "ffprobe": b"fake-ffprobe-bytes",
    }

    class _Response:
        def __init__(self, data: bytes) -> None:
            self._data = data
            self.headers = {"Content-Length": str(len(data))}

        def read(self, size: int = -1) -> bytes:
            if not self._data:
                return b""
            if size < 0:
                chunk, self._data = self._data, b""
                return chunk
            chunk, self._data = self._data[:size], self._data[size:]
            return chunk

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_urlopen(request: object, timeout: float = 0) -> _Response:
        url = request.full_url if hasattr(request, "full_url") else str(request)
        name = "ffmpeg" if "ffmpeg-darwin" in url else "ffprobe"
        return _Response(gzip.compress(payloads[name]))

    verified: list[str] = []

    def fake_verify(path: Path, expected_name: str) -> None:
        verified.append(expected_name)
        assert path.is_file()

    monkeypatch.setattr(
        "dxband.services.download_mirrors.urllib.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(ffmpeg_tools, "_verify_binary", fake_verify)
    monkeypatch.setattr(ffmpeg_tools, "_clear_macos_quarantine", lambda _path: None)
    # Skip sha by emptying expected digests for this unit test.
    monkeypatch.setitem(
        ffmpeg_tools._PLATFORM_ASSETS["darwin-arm64"],
        "ffmpeg",
        (ffmpeg_tools._PLATFORM_ASSETS["darwin-arm64"]["ffmpeg"][0], ""),
    )
    monkeypatch.setitem(
        ffmpeg_tools._PLATFORM_ASSETS["darwin-arm64"],
        "ffprobe",
        (ffmpeg_tools._PLATFORM_ASSETS["darwin-arm64"]["ffprobe"][0], ""),
    )

    path = ffmpeg_tools.download_ffmpeg()

    assert path == destination / "ffmpeg"
    assert (destination / "ffmpeg").read_bytes() == payloads["ffmpeg"]
    assert (destination / "ffprobe").read_bytes() == payloads["ffprobe"]
    assert verified == ["ffmpeg", "ffprobe"]


def test_ensure_ffmpeg_ready_repairs_existing_managed_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ffmpeg = bin_dir / "ffmpeg"
    ffprobe = bin_dir / "ffprobe"
    ffmpeg.write_bytes(b"#!/bin/sh\n")
    ffprobe.write_bytes(b"#!/bin/sh\n")
    monkeypatch.setattr(ffmpeg_tools, "managed_bin_dir", lambda: bin_dir)
    monkeypatch.setattr(ffmpeg_tools, "bundled_bin_dir", lambda: None)
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda _name: None)
    monkeypatch.delenv("DX_BAND_FFMPEG", raising=False)
    monkeypatch.delenv("DX_BAND_FFPROBE", raising=False)

    # Present but not executable until repair chmods them.
    assert not ffmpeg_tools.ffmpeg_status().ready
    assert ffmpeg_tools.managed_binaries_present()

    reports: list[tuple[str, float | None]] = []

    def fake_verify(path: Path, expected_name: str) -> None:
        assert path.is_file()
        assert os_access_ok(path)

    def os_access_ok(path: Path) -> bool:
        return path.stat().st_mode & 0o111 != 0

    monkeypatch.setattr(ffmpeg_tools, "_verify_binary", fake_verify)
    monkeypatch.setattr(ffmpeg_tools, "_clear_macos_quarantine", lambda _path: None)

    path = ffmpeg_tools.ensure_ffmpeg_ready(
        on_progress=lambda stage, ratio: reports.append((stage, ratio))
    )
    assert path == ffmpeg
    assert ffmpeg_tools.ffmpeg_status().ready
    assert any("修复" in stage for stage, _ratio in reports)


def test_ensure_ffmpeg_ready_downloads_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "managed"
    monkeypatch.setattr(ffmpeg_tools, "managed_bin_dir", lambda: destination)
    monkeypatch.setattr(ffmpeg_tools, "bundled_bin_dir", lambda: None)
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda _name: None)
    monkeypatch.delenv("DX_BAND_FFMPEG", raising=False)
    monkeypatch.delenv("DX_BAND_FFPROBE", raising=False)

    called: list[bool] = []

    def fake_download(on_progress=None):  # type: ignore[no-untyped-def]
        called.append(True)
        destination.mkdir(parents=True, exist_ok=True)
        ffmpeg = destination / "ffmpeg"
        ffprobe = destination / "ffprobe"
        ffmpeg.write_bytes(b"ffmpeg")
        ffprobe.write_bytes(b"ffprobe")
        ffmpeg.chmod(0o755)
        ffprobe.chmod(0o755)
        if on_progress:
            on_progress("正在下载多媒体组件", 1.0)
        return ffmpeg

    monkeypatch.setattr(ffmpeg_tools, "download_ffmpeg", fake_download)
    path = ffmpeg_tools.ensure_ffmpeg_ready()
    assert called == [True]
    assert path == destination / "ffmpeg"
