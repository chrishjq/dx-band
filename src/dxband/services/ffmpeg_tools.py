# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Locate, download, and expose managed FFmpeg / FFprobe binaries.

System PATH installs remain preferred. When missing, macOS and Windows users
can download a pinned ffmpeg-static build into the per-user application data
directory from Settings. Model weights are unrelated and stay separate.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dxband.services.application_paths import default_application_data_root
from dxband.services.bundle_paths import is_frozen, meipass_root
from dxband.services.download_mirrors import urlopen_with_mirrors
from dxband.workers.command import subprocess_creation_flags

ProgressCallback = Callable[[str, float | None], None]

FFMPEG_LABEL = "多媒体组件"
FFMPEG_DETAIL = "转码与探测音频视频"

# Pinned https://github.com/eugeneware/ffmpeg-static release assets.
FFMPEG_STATIC_VERSION = "b6.1.1"
FFMPEG_STATIC_BASE = (
    f"https://github.com/eugeneware/ffmpeg-static/releases/download/{FFMPEG_STATIC_VERSION}"
)
_PLATFORM_ASSETS: dict[str, dict[str, tuple[str, str]]] = {
    "darwin-arm64": {
        "ffmpeg": (
            f"{FFMPEG_STATIC_BASE}/ffmpeg-darwin-arm64.gz",
            "8923876afa8db5585022d7860ec7e589af192f441c56793971276d450ed3bbfa",
        ),
        "ffprobe": (
            f"{FFMPEG_STATIC_BASE}/ffprobe-darwin-arm64.gz",
            "d986a8ec7b030899fe66a8a288ed809a3543338705a3ce178cfb85869c5d80be",
        ),
    },
    "darwin-x86_64": {
        "ffmpeg": (
            f"{FFMPEG_STATIC_BASE}/ffmpeg-darwin-x64.gz",
            "929b375c1182d956c51f7ac25e0b2b0411fb01f6f407aa15c9758efeb4242106",
        ),
        "ffprobe": (
            f"{FFMPEG_STATIC_BASE}/ffprobe-darwin-x64.gz",
            "d4da574d6e2e197bd259b47d69cf262df9e312af24ad960444f6d806d3d4c186",
        ),
    },
    "win32-x86_64": {
        "ffmpeg": (
            f"{FFMPEG_STATIC_BASE}/ffmpeg-win32-x64.gz",
            "8883a3dffbd0a16cf4ef95206ea05283f78908dbfb118f73c83f4951dcc06d77",
        ),
        "ffprobe": (
            f"{FFMPEG_STATIC_BASE}/ffprobe-win32-x64.gz",
            "f309e6223ad89d2fe54bccd420a7709b66fd27540674e92309578ed491a43c8d",
        ),
    },
}


@dataclass(frozen=True, slots=True)
class FFmpegStatus:
    ready: bool
    source: str
    ffmpeg_path: Path | None
    ffprobe_path: Path | None
    download_supported: bool
    managed_present: bool = False


def managed_bin_dir() -> Path:
    override = os.environ.get("DX_BAND_FFMPEG_DIR")
    if override:
        return Path(override).expanduser()
    return default_application_data_root() / "ffmpeg" / "bin"


def bundled_bin_dir() -> Path | None:
    if not is_frozen():
        return None
    candidate = meipass_root() / "ffmpeg" / "bin"
    return candidate if candidate.is_dir() else None


def managed_ffmpeg_path() -> Path:
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    return managed_bin_dir() / name


def managed_ffprobe_path() -> Path:
    name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    return managed_bin_dir() / name


def managed_binaries_present() -> bool:
    return managed_ffmpeg_path().is_file() and managed_ffprobe_path().is_file()


def resolve_ffmpeg() -> Path | None:
    return _resolve_tool("ffmpeg", managed_ffmpeg_path())


def resolve_ffprobe() -> Path | None:
    return _resolve_tool("ffprobe", managed_ffprobe_path())


def ffmpeg_status() -> FFmpegStatus:
    ffmpeg = resolve_ffmpeg()
    ffprobe = resolve_ffprobe()
    ready = ffmpeg is not None and ffprobe is not None
    source = "missing"
    if ready:
        managed = managed_bin_dir()
        bundled = bundled_bin_dir()
        if bundled is not None and _is_under(ffmpeg, bundled) and _is_under(ffprobe, bundled):
            source = "bundled"
        elif _is_under(ffmpeg, managed) or _is_under(ffprobe, managed):
            source = "managed"
        else:
            source = "system"
    return FFmpegStatus(
        ready=ready,
        source=source,
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        download_supported=_asset_key() is not None,
        managed_present=managed_binaries_present(),
    )


def ensure_ffmpeg_on_path() -> None:
    """Prepend managed/bundled bin dirs so bare ``ffmpeg`` lookups succeed."""
    additions: list[str] = []
    for directory in (bundled_bin_dir(), managed_bin_dir()):
        if directory is None or not directory.is_dir():
            continue
        path = str(directory)
        if path not in additions:
            additions.append(path)
    if not additions:
        return
    existing = os.environ.get("PATH", "").split(os.pathsep)
    merged = [path for path in additions if path not in existing]
    if merged:
        os.environ["PATH"] = os.pathsep.join((*merged, *existing))


def repair_ffmpeg(on_progress: ProgressCallback | None = None) -> Path:
    """Fix permissions, quarantine, and PATH for an existing managed install."""
    progress = on_progress or (lambda _stage, _ratio: None)
    ffmpeg = managed_ffmpeg_path()
    ffprobe = managed_ffprobe_path()
    if not ffmpeg.is_file() or not ffprobe.is_file():
        raise RuntimeError(f"{FFMPEG_LABEL}尚未下载到本机，请先处理安装")
    progress(f"正在修复{FFMPEG_LABEL}", 0.2)
    for path in (ffmpeg, ffprobe):
        with contextlib.suppress(OSError):
            path.chmod(0o755)
        _clear_macos_quarantine(path)
    progress(f"正在校验{FFMPEG_LABEL}", 0.6)
    _verify_binary(ffmpeg, "ffmpeg")
    _verify_binary(ffprobe, "ffprobe")
    ensure_ffmpeg_on_path()
    progress(f"{FFMPEG_LABEL}已就绪", 1.0)
    return ffmpeg


def ensure_ffmpeg_ready(on_progress: ProgressCallback | None = None) -> Path:
    """Download when missing; otherwise repair the managed install and PATH."""
    progress = on_progress or (lambda _stage, _ratio: None)
    status = ffmpeg_status()
    if status.ready:
        ensure_ffmpeg_on_path()
        progress(f"{FFMPEG_LABEL}已就绪", 1.0)
        path = status.ffmpeg_path
        assert path is not None
        return path
    if managed_binaries_present():
        return repair_ffmpeg(on_progress=progress)
    return download_ffmpeg(on_progress=progress)


def download_ffmpeg(on_progress: ProgressCallback | None = None) -> Path:
    """Download FFmpeg and FFprobe into the managed location."""
    progress = on_progress or (lambda _stage, _ratio: None)
    asset_key = _asset_key()
    if asset_key is None:
        raise RuntimeError(f"当前系统暂不支持在应用内下载{FFMPEG_LABEL}，请先自行安装")
    assets = _PLATFORM_ASSETS[asset_key]
    destination = managed_bin_dir()
    destination.mkdir(parents=True, exist_ok=True)
    installed_ffmpeg = managed_ffmpeg_path()
    installed_ffprobe = managed_ffprobe_path()
    with tempfile.TemporaryDirectory(prefix="dx-band-ffmpeg-") as temporary_root:
        temp_root = Path(temporary_root)
        progress(f"正在下载{FFMPEG_LABEL}", 0.05)
        ffmpeg_gz = temp_root / "ffmpeg.gz"
        ffprobe_gz = temp_root / "ffprobe.gz"
        _download_file(
            assets["ffmpeg"][0],
            ffmpeg_gz,
            assets["ffmpeg"][1],
            progress,
            f"正在下载{FFMPEG_LABEL}",
            ratio_span=(0.05, 0.45),
        )
        _download_file(
            assets["ffprobe"][0],
            ffprobe_gz,
            assets["ffprobe"][1],
            progress,
            f"正在下载{FFMPEG_LABEL}探测组件",
            ratio_span=(0.45, 0.85),
        )
        progress(f"正在安装{FFMPEG_LABEL}", 0.9)
        ffmpeg_raw = temp_root / "ffmpeg.bin"
        ffprobe_raw = temp_root / "ffprobe.bin"
        _gunzip_to(ffmpeg_gz, ffmpeg_raw)
        _gunzip_to(ffprobe_gz, ffprobe_raw)
        _install_binary(ffmpeg_raw, installed_ffmpeg)
        _install_binary(ffprobe_raw, installed_ffprobe)
    _verify_binary(installed_ffmpeg, "ffmpeg")
    _verify_binary(installed_ffprobe, "ffprobe")
    (destination / "VERSION").write_text(f"{FFMPEG_STATIC_VERSION}\n", encoding="utf-8")
    ensure_ffmpeg_on_path()
    progress(f"{FFMPEG_LABEL}已就绪", 1.0)
    return installed_ffmpeg


def _asset_key() -> str | None:
    machine = platform.machine().lower()
    if machine in {"aarch64"}:
        machine = "arm64"
    elif machine in {"amd64"}:
        machine = "x86_64"
    if sys.platform == "darwin" and machine in {"arm64", "x86_64"}:
        return f"darwin-{machine}"
    if sys.platform == "win32" and machine == "x86_64":
        return "win32-x86_64"
    return None


def _macos_asset_key() -> str | None:
    """Compatibility wrapper used by older tests."""
    key = _asset_key()
    if key == "darwin-arm64":
        return "arm64"
    if key == "darwin-x86_64":
        return "x86_64"
    return None


def _resolve_tool(name: str, managed: Path) -> Path | None:
    override_key = "DX_BAND_FFMPEG" if name == "ffmpeg" else "DX_BAND_FFPROBE"
    override = os.environ.get(override_key)
    if override:
        path = Path(override).expanduser()
        return path if path.is_file() and os.access(path, os.X_OK) else None

    bundled = bundled_bin_dir()
    if bundled is not None:
        candidate = bundled / (f"{name}.exe" if sys.platform == "win32" else name)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    if managed.is_file() and os.access(managed, os.X_OK):
        return managed

    found = shutil.which(name)
    return Path(found) if found else None


def _is_under(path: Path | None, root: Path) -> bool:
    if path is None:
        return False
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _download_file(
    url: str,
    destination: Path,
    expected_sha256: str,
    progress: ProgressCallback,
    stage: str,
    *,
    ratio_span: tuple[float, float],
) -> None:
    start, end = ratio_span
    temporary = destination.with_suffix(destination.suffix + ".partial")
    try:
        with urlopen_with_mirrors(url, timeout=180) as response:
            total_header = response.headers.get("Content-Length")
            expected_size = int(total_header) if total_header and total_header.isdigit() else None
            hasher = hashlib.sha256()
            received = 0
            with temporary.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    hasher.update(chunk)
                    received += len(chunk)
                    if expected_size:
                        fraction = min(1.0, received / expected_size)
                        progress(stage, start + (end - start) * fraction)
        digest = hasher.hexdigest()
        if expected_sha256 and digest != expected_sha256:
            raise RuntimeError(f"{FFMPEG_LABEL}校验失败，请稍后重试")
        temporary.replace(destination)
    except urllib.error.URLError as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"下载{FFMPEG_LABEL}失败：{exc}") from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _gunzip_to(source: Path, destination: Path) -> None:
    with gzip.open(source, "rb") as compressed, destination.open("wb") as handle:
        shutil.copyfileobj(compressed, handle)


def _install_binary(source: Path, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".partial")
    shutil.copy2(source, temporary)
    temporary.chmod(0o755)
    _clear_macos_quarantine(temporary)
    temporary.replace(destination)
    _clear_macos_quarantine(destination)


def _clear_macos_quarantine(path: Path) -> None:
    if sys.platform != "darwin":
        return
    subprocess.run(
        ["xattr", "-dr", "com.apple.quarantine", str(path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=subprocess_creation_flags(),
    )


def _verify_binary(path: Path, expected_name: str) -> None:
    try:
        completed = subprocess.run(
            [str(path), "-version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            creationflags=subprocess_creation_flags(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{FFMPEG_LABEL}安装后无法运行：{exc}") from exc
    combined = (completed.stdout + completed.stderr).lower()
    if completed.returncode != 0 or expected_name not in combined:
        raise RuntimeError(f"{FFMPEG_LABEL}安装后自检失败")
