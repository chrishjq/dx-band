# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtGui import QFont, QFontMetrics


def fitting_font(
    text: str,
    family: str,
    maximum_size: int,
    minimum_size: int,
    available_width: int,
) -> QFont:
    # 字号设置没有业务上限，但超过可用宽度数倍的字号不可能容纳非空歌词。
    # 先收紧搜索上界，再用二分查找，避免极大字号造成数十亿次递减循环。
    upper_bound = min(maximum_size, max(minimum_size, available_width * 2))
    best_size = minimum_size
    low = minimum_size
    high = upper_bound
    while low <= high:
        point_size = (low + high) // 2
        font = QFont(family, point_size)
        font.setWeight(QFont.Weight.Bold)
        if QFontMetrics(font).horizontalAdvance(text) <= available_width:
            best_size = point_size
            low = point_size + 1
        else:
            high = point_size - 1
    font = QFont(family, best_size)
    font.setWeight(QFont.Weight.Bold)
    return font
