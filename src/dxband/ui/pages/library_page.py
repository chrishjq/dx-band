# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from dxband.services.library_service import LibraryScanResult
from dxband.ui.page_layout import (
    BUTTON_ROW_SPACING,
    add_page_header,
    create_page_layout,
    set_button_icon,
)
from dxband.ui.public_messages import public_message


class SortableTableWidgetItem(QTableWidgetItem):
    def __init__(self, text: str, sort_key: str) -> None:
        super().__init__(text)
        self.sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, SortableTableWidgetItem):
            return self.sort_key < other.sort_key
        return super().__lt__(other)


class LibraryPage(QWidget):
    create_requested = Signal()
    refresh_requested = Signal()
    import_requested = Signal()
    export_requested = Signal(object)
    search_changed = Signal(str)
    load_requested = Signal(object)
    add_to_playlist_requested = Signal(object)
    edit_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._playlist_song_ids: frozenset[str] = frozenset()
        layout = create_page_layout(self)
        add_page_header(
            layout,
            self,
            "歌曲库",
            "管理本地歌曲包，试听并修改歌词、节奏与和弦",
        )

        tools_card = QFrame(self)
        tools_card.setObjectName("toolbarCard")
        tools = QHBoxLayout(tools_card)
        tools.setContentsMargins(12, 10, 12, 10)
        tools.setSpacing(BUTTON_ROW_SPACING)
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("搜索歌曲名、歌手或歌曲包…")
        self.create_button = QPushButton("创建歌曲", self)
        set_button_icon(self.create_button, "create.svg")
        self.create_button.setProperty("role", "primary")
        refresh_button = QPushButton("刷新", self)
        set_button_icon(refresh_button, "refresh.svg")
        import_button = QPushButton("导入歌曲包", self)
        set_button_icon(import_button, "import.svg")
        self.create_button.clicked.connect(self.create_requested)
        import_button.clicked.connect(self.import_requested)
        refresh_button.clicked.connect(self.refresh_requested)
        self.search_edit.textChanged.connect(self.search_changed)
        tools.addWidget(self.search_edit, 1)
        tools.addWidget(self.create_button)
        tools.addWidget(import_button)
        tools.addWidget(refresh_button)
        layout.addWidget(tools_card)

        self.song_list = QTableWidget(self)
        self.song_list.setObjectName("songLibraryTable")
        self.song_list.setColumnCount(7)
        self.song_list.setHorizontalHeaderLabels(
            [
                "歌曲名称",
                "歌手",
                "时长",
                "原KEY",
                "BPM",
                "创建日期",
                "播放列表",
            ]
        )
        self.song_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.song_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.song_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.song_list.setAlternatingRowColors(True)
        self.song_list.setToolTip("双击歌曲可进入修改界面")
        vertical_header = self.song_list.verticalHeader()
        vertical_header.setVisible(False)
        vertical_header.setDefaultSectionSize(42)
        header = self.song_list.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.song_list.setColumnWidth(6, 112)
        header.setSortIndicator(5, Qt.SortOrder.DescendingOrder)
        self.song_list.setSortingEnabled(True)
        self.song_list.cellDoubleClicked.connect(
            lambda row, _column: self._request_edit_row(row)
        )
        layout.addWidget(self.song_list, 1)

        actions = QHBoxLayout()
        actions.setSpacing(BUTTON_ROW_SPACING)
        self.add_button = self._create_action_button("添加到播放列表", "playlist-add.svg")
        self.edit_button = self._create_action_button("修改", "edit.svg")
        self.export_button = self._create_action_button("导出歌曲包", "upload.svg")
        self.delete_button = self._create_action_button("删除", "delete.svg")
        self.delete_button.setProperty("role", "danger")
        self.add_button.clicked.connect(self._request_add_to_playlist)
        self.edit_button.clicked.connect(self._request_edit)
        self.export_button.clicked.connect(self._request_export)
        self.delete_button.clicked.connect(self._request_delete)
        actions.addWidget(self.add_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.export_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.status_label = QLabel("尚未扫描歌曲库", self)
        self.status_label.setObjectName("statusBar")
        layout.addWidget(self.status_label)

    def show_scan_result(self, result: LibraryScanResult) -> None:
        header = self.song_list.horizontalHeader()
        sort_column = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        self.song_list.setSortingEnabled(False)
        self.song_list.setRowCount(len(result.songs))
        for row, package in enumerate(result.songs):
            musical = package.config.musical
            duration = self._format_duration(package.config.duration_ms)
            in_playlist = package.config.song_id in self._playlist_song_ids
            values = (
                (package.config.title, f"0{package.config.title.casefold()}"),
                (
                    package.config.artist or "—",
                    (f"0{package.config.artist.casefold()}" if package.config.artist else "1"),
                ),
                (duration, f"0{package.config.duration_ms:020d}"),
                (
                    musical.original_key,
                    f"0{musical.original_key.casefold()}",
                ),
                (
                    str(musical.bpm),
                    f"0{musical.bpm:010d}",
                ),
                (
                    package.config.created_at.strftime("%Y.%m.%d %H:%M:%S"),
                    f"0{int(package.config.created_at.timestamp() * 1_000_000):020d}",
                ),
                ("已加入" if in_playlist else "未加入", "0" if in_playlist else "1"),
            )
            for column, (value, sort_key) in enumerate(values):
                item = SortableTableWidgetItem(value, sort_key)
                item.setToolTip(str(package.root))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, str(package.root))
                if 2 <= column <= 4:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif column == 5:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    )
                elif column == 6:
                    item.setData(Qt.ItemDataRole.UserRole, package.config.song_id)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.song_list.setItem(row, column, item)
                if column == 6:
                    self._sync_playlist_cell(row, item, in_playlist)
        self.song_list.setSortingEnabled(True)
        self.song_list.sortItems(sort_column, sort_order)
        self.status_label.setText(
            f"可播放歌曲：{len(result.songs)}；损坏或不完整歌曲包：{len(result.broken)}"
        )

    def set_playlist_song_ids(self, song_ids: Iterable[str]) -> None:
        self._playlist_song_ids = frozenset(song_ids)
        header = self.song_list.horizontalHeader()
        sort_column = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        self.song_list.setSortingEnabled(False)
        for row in range(self.song_list.rowCount()):
            item = self.song_list.item(row, 6)
            if not isinstance(item, SortableTableWidgetItem):
                continue
            song_id = item.data(Qt.ItemDataRole.UserRole)
            self._sync_playlist_cell(
                row,
                item,
                isinstance(song_id, str) and song_id in self._playlist_song_ids,
            )
        self.song_list.setSortingEnabled(True)
        self.song_list.sortItems(sort_column, sort_order)

    @staticmethod
    def _apply_playlist_status(
        item: SortableTableWidgetItem,
        in_playlist: bool,
    ) -> None:
        item.setText("已加入" if in_playlist else "未加入")
        item.sort_key = "0" if in_playlist else "1"
        item.setForeground(QBrush(QColor("#4fd18b" if in_playlist else "#687383")))

    def _sync_playlist_cell(
        self,
        row: int,
        item: SortableTableWidgetItem,
        in_playlist: bool,
    ) -> None:
        self._apply_playlist_status(item, in_playlist)
        existing = self.song_list.cellWidget(row, 6)
        if existing is not None:
            self.song_list.removeCellWidget(row, 6)
            existing.deleteLater()
        if in_playlist:
            return
        path_item = self.song_list.item(row, 0)
        if path_item is None:
            return
        path = Path(str(path_item.data(Qt.ItemDataRole.UserRole)))
        cell = QWidget(self.song_list)
        cell.setObjectName("libraryPlaylistActionCell")
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(4, 1, 4, 1)
        cell_layout.setSpacing(0)
        button = QPushButton("加入", cell)
        button.setObjectName("libraryRowAddButton")
        button.setProperty("role", "tableAction")
        set_button_icon(button, "playlist-add.svg", QSize(15, 15))
        button.setAccessibleName(f"将{path_item.text()}加入播放列表")
        button.setToolTip(f"将《{path_item.text()}》加入播放列表")
        button.clicked.connect(
            lambda _checked=False, selected=path: self.add_to_playlist_requested.emit(
                (selected,)
            )
        )
        cell_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignCenter)
        self.song_list.setCellWidget(row, 6, cell)

    def show_error(self, message: str) -> None:
        self.status_label.setText(f"错误：{public_message(message, '操作失败，请重试')}")

    def set_creation_active(self, active: bool) -> None:
        self.create_button.setText("查看创建进度" if active else "创建歌曲")

    def _create_action_button(self, text: str, icon_name: str) -> QPushButton:
        button = QPushButton(text, self)
        set_button_icon(button, icon_name)
        return button

    def _selected_path(self) -> Path | None:
        row = self.song_list.currentRow()
        item = self.song_list.item(row, 0) if row >= 0 else None
        if item is None:
            self.status_label.setText("请先选择歌曲")
            return None
        return Path(str(item.data(Qt.ItemDataRole.UserRole)))

    @staticmethod
    def _format_duration(duration_ms: int) -> str:
        total_seconds = max(0, round(duration_ms / 1000))
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _request_load(self) -> None:
        path = self._selected_path()
        if path is not None:
            self.load_requested.emit(path)

    def _request_edit_row(self, row: int) -> None:
        item = self.song_list.item(row, 0)
        if item is not None:
            self.edit_requested.emit(Path(str(item.data(Qt.ItemDataRole.UserRole))))

    def _request_add_to_playlist(self) -> None:
        paths: list[Path] = []
        for index in sorted(
            self.song_list.selectionModel().selectedRows(), key=lambda value: value.row()
        ):
            item = self.song_list.item(index.row(), 0)
            if item is not None:
                paths.append(Path(str(item.data(Qt.ItemDataRole.UserRole))))
        if paths:
            self.add_to_playlist_requested.emit(tuple(paths))
        else:
            self.status_label.setText("请先选择要加入播放列表的歌曲")

    def _request_delete(self) -> None:
        path = self._selected_path()
        if path is not None:
            self.delete_requested.emit(path)

    def _request_export(self) -> None:
        path = self._selected_path()
        if path is not None:
            self.export_requested.emit(path)

    def _request_edit(self) -> None:
        path = self._selected_path()
        if path is not None:
            self.edit_requested.emit(path)
