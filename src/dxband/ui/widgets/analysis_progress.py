# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Shared busy indicator for long running music and chord analysis."""

from PySide6.QtWidgets import QProgressBar, QWidget


def analysis_progress(parent: QWidget) -> QProgressBar:
    progress = QProgressBar(parent)
    progress.setObjectName("analysisProgress")
    progress.setRange(0, 0)
    progress.setFixedWidth(104)
    progress.hide()
    return progress
