# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Canonical user-data locations independent of the desktop UI implementation."""

import os
import sys
from pathlib import Path


def default_library_root() -> Path:
    music_root = Path.home() / "Music"
    current = music_root / "DXBandLibrary"
    previous = music_root / "DXStageLibrary"
    return previous if not current.exists() and previous.exists() else current


def default_log_directory() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "DXBand"
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return root / "DXBand" / "logs"
    state_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_root / "dx-band" / "logs"


def default_application_data_root() -> Path:
    """Return the writable per-user application data directory."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DXBand"
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return root / "DXBand"
    data_root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_root / "dx-band"
