# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from dxband.creation.package_validator import SongPackage
from dxband.ui.page_layout import (
    BUTTON_ROW_SPACING,
    add_page_header,
    create_page_layout,
    set_button_icon,
)
from dxband.ui.public_messages import public_message


class PlaylistPage(QWidget):
    load_requested = Signal(int)
    remove_requested = Signal(int)
    move_requested = Signal(int, int)

    def __init__(self, *, embedded: bool = False) -> None:
        super().__init__()
        self.setObjectName("embeddedPlaylistPage" if embedded else "playlistPage")
        self.setProperty("embedded", embedded)
        layout = create_page_layout(self)
        if embedded:
            layout.setContentsMargins(20, 28, 20, 26)
        add_page_header(
            layout,
            self,
            "播放列表",
            "双击歌曲可切换当前曲目" if embedded else "安排演出顺序；双击歌曲可切换当前曲目",
        )

        self.song_list = QTableWidget(self)
        self.song_list.setObjectName("playlistTable")
        self.song_list.setColumnCount(4)
        self.song_list.setHorizontalHeaderLabels(["顺序", "歌曲名称", "歌手", "时长"])
        self.song_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.song_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.song_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.song_list.setAlternatingRowColors(True)
        self.song_list.verticalHeader().setVisible(False)
        header = self.song_list.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.song_list.cellDoubleClicked.connect(lambda _row, _column: self._request_load())
        layout.addWidget(self.song_list, 1)

        actions = QHBoxLayout()
        actions.setSpacing(BUTTON_ROW_SPACING)
        up_button = QPushButton("上移", self)
        set_button_icon(up_button, "arrow-up.svg")
        down_button = QPushButton("下移", self)
        set_button_icon(down_button, "arrow-down.svg")
        remove_button = QPushButton("从列表移除", self)
        set_button_icon(remove_button, "remove.svg")
        up_button.clicked.connect(lambda: self._request_move(-1))
        down_button.clicked.connect(lambda: self._request_move(1))
        remove_button.clicked.connect(self._request_remove)
        for button in (up_button, down_button, remove_button):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.status_label = QLabel("播放列表为空", self)
        self.status_label.setObjectName("statusBar")
        layout.addWidget(self.status_label)

    def set_songs(
        self,
        song_ids: tuple[str, ...],
        songs: dict[str, SongPackage],
        current_index: int | None = None,
    ) -> None:
        selected_row = self.song_list.currentRow()
        self.song_list.setRowCount(len(song_ids))
        for row, song_id in enumerate(song_ids):
            package = songs.get(song_id)
            if package is None:
                values = (str(row + 1), "歌曲不存在（无法播放）", song_id, "—")
            else:
                seconds = round(package.config.duration_ms / 1000)
                minutes, remaining = divmod(seconds, 60)
                values = (
                    str(row + 1),
                    package.config.title,
                    package.config.artist or "—",
                    f"{minutes:02d}:{remaining:02d}",
                )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, song_id)
                if column in (0, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if row == current_index:
                    item.setBackground(QBrush(QColor("#173a2b")))
                    item.setForeground(QBrush(QColor("#75e6a8")))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.song_list.setItem(row, column, item)
        if 0 <= selected_row < len(song_ids):
            self.song_list.selectRow(selected_row)
        self.status_label.setText(f"播放列表：{len(song_ids)} 首")

    def show_status(self, message: str) -> None:
        self.status_label.setText(public_message(message, "播放列表操作失败，请重试"))

    def _selected_index(self) -> int | None:
        row = self.song_list.currentRow()
        return row if 0 <= row < self.song_list.rowCount() else None

    def _request_load(self) -> None:
        index = self._selected_index()
        if index is not None:
            self.load_requested.emit(index)

    def _request_remove(self) -> None:
        index = self._selected_index()
        if index is not None:
            self.remove_requested.emit(index)

    def _request_move(self, direction: int) -> None:
        index = self._selected_index()
        if index is not None:
            self.move_requested.emit(index, direction)
