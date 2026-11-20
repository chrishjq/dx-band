# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Application resource locations shared by the desktop presentation layer."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
RESOURCE_ROOT = PACKAGE_ROOT / "resources"
CONTROL_ICON_ROOT = RESOURCE_ROOT / "controls"
INSTRUMENT_ICON_ROOT = RESOURCE_ROOT / "fontawesome"
CUSTOM_INSTRUMENT_ICON_ROOT = RESOURCE_ROOT / "instruments"
AUDIENCE_FONT_ROOT = RESOURCE_ROOT / "fonts" / "audience"
BACKGROUND_VIDEO_ROOT = RESOURCE_ROOT / "background_videos"
WEB_MUSICIAN_ROOT = RESOURCE_ROOT / "web_musician"
WEB_SINGER_ROOT = RESOURCE_ROOT / "web_singer"
