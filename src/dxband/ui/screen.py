# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import dataclass

from PySide6.QtCore import QRect
from PySide6.QtGui import QScreen


@dataclass(frozen=True, slots=True)
class ScreenDescriptor:
    fingerprint: str
    name: str
    manufacturer: str
    model: str
    serial_number: str
    geometry: QRect
    screen: QScreen

    @property
    def display_name(self) -> str:
        size = self.geometry.size()
        details = " ".join(part for part in (self.manufacturer, self.model) if part)
        suffix = f" · {details}" if details else ""
        return f"{self.name} ({size.width()}×{size.height()}){suffix}"
