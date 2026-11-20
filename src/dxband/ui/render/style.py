# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import dataclass, field

from PySide6.QtGui import QColor


@dataclass(frozen=True, slots=True)
class AudienceStyle:
    base_color: QColor = field(default_factory=lambda: QColor("#FFFFFF"))
    highlight_color: QColor = field(default_factory=lambda: QColor("#FFFFFF"))
    shadow_color: QColor = field(default_factory=lambda: QColor(0, 0, 0, 185))
    shadow_offset: tuple[float, float] = (3.0, 4.0)
    shadow_blur_width: float = 5.0
    font_family: str = "PingFang SC"


@dataclass(frozen=True, slots=True)
class SingerStyle:
    previous_color: QColor = field(default_factory=lambda: QColor("#888888"))
    current_color: QColor = field(default_factory=lambda: QColor("#FFD34E"))
    next_color: QColor = field(default_factory=lambda: QColor("#FFFFFF"))
    countdown_color: QColor = field(default_factory=lambda: QColor("#888888"))
    font_family: str = "PingFang SC"
