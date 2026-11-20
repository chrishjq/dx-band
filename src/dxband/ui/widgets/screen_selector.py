# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox

from dxband.ui.screen import ScreenDescriptor


class ScreenSelector(QComboBox):
    fingerprint_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.currentIndexChanged.connect(self._emit_fingerprint)

    def set_screens(
        self, screens: tuple[ScreenDescriptor, ...], selected_fingerprint: str | None = None
    ) -> None:
        self.blockSignals(True)
        self.clear()
        selected_index = -1
        for index, descriptor in enumerate(screens):
            self.addItem(descriptor.display_name, descriptor.fingerprint)
            if descriptor.fingerprint == selected_fingerprint:
                selected_index = index
        if selected_index >= 0:
            self.setCurrentIndex(selected_index)
        self.blockSignals(False)

    def fingerprint(self) -> str:
        value = self.currentData()
        return str(value) if value is not None else ""

    def _emit_fingerprint(self, _index: int) -> None:
        self.fingerprint_changed.emit(self.fingerprint())
