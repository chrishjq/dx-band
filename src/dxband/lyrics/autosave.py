# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from dxband.models.lyric import LyricsDocument
from dxband.services.atomic_file_service import atomic_write_json


class LyricsAutosaver(QObject):
    def __init__(self, path: Path, delay_ms: int = 600, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self._pending: LyricsDocument | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self.flush)

    def schedule(self, document: LyricsDocument) -> None:
        self._pending = document
        self._timer.start()

    def flush(self) -> None:
        if self._pending is None:
            return
        atomic_write_json(self.path, self._pending)
        self._pending = None
