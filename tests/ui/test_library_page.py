# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QPushButton
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from dxband.creation.package_validator import SongPackage, SongPackageValidator
from dxband.creation.sheetsage2_runner import SheetSage2Runner
from dxband.models.chord import ChordSegment, ChordTimeline
from dxband.models.song import MusicalConfig, SongConfig
from dxband.services.library_service import LibraryScanResult, LibraryService
from dxband.ui.controllers.library_controller import LibraryController
from dxband.ui.dialogs.confirmation_dialog import (
    DestructiveConfirmationDialog,
)
from dxband.ui.pages.library_page import LibraryPage
from dxband.ui.services.settings_service import SettingsService


def test_existing_song_language_is_normalized_for_word_timing_recognition() -> None:
    assert LibraryController._transcription_language("und") == "auto"
    assert LibraryController._transcription_language("und", "我像是一颗棋子") == "zh"
    assert LibraryController._transcription_language("zh-CN") == "zh"
    assert LibraryController._transcription_language("yue") == "yue"


def test_library_table_shows_song_properties(
    qtbot: QtBot,
    package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    config_payload = package.config.model_dump(mode="python")
    config_payload["musical"] = MusicalConfig(
        original_key="F#m",
        bpm=127,
    ).model_dump(mode="python")
    package = package.__class__(
        root=package.root,
        config=SongConfig.model_validate(config_payload, strict=True),
        lyrics=package.lyrics,
        warnings=package.warnings,
    )
    page = LibraryPage()
    qtbot.addWidget(page)

    page.show_scan_result(LibraryScanResult(songs=(package,), broken=()))

    assert page.song_list.columnCount() == 7
    assert [page.song_list.horizontalHeaderItem(column).text() for column in range(7)] == [
        "歌曲名称",
        "歌手",
        "时长",
        "原KEY",
        "BPM",
        "创建日期",
        "播放列表",
    ]
    assert [page.song_list.item(0, column).text() for column in range(7)] == [
        "测试歌曲",
        "测试歌手",
        "00:10",
        "F#m",
        "127",
        "2026.09.30 19:30:00",
        "未加入",
    ]
    assert page.song_list.item(0, 5).textAlignment() & Qt.AlignmentFlag.AlignLeft


def test_library_table_updates_colored_playlist_status(
    qtbot: QtBot,
    package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    page = LibraryPage()
    qtbot.addWidget(page)
    page.show_scan_result(LibraryScanResult(songs=(package,), broken=()))
    status_item = page.song_list.item(0, 6)
    missing_color = status_item.foreground().color()
    action_cell = page.song_list.cellWidget(0, 6)
    assert action_cell is not None
    add_button = action_cell.findChild(QPushButton, "libraryRowAddButton")
    assert add_button is not None
    assert add_button.text() == "加入"
    assert not add_button.icon().isNull()
    assert page.song_list.columnWidth(6) == 112
    assert page.song_list.rowHeight(0) >= 42
    page.resize(1066, 800)
    page.show()
    qtbot.wait(1)
    assert action_cell.rect().contains(add_button.geometry())

    page.set_playlist_song_ids((package.config.song_id,))

    status_item = page.song_list.item(0, 6)
    assert status_item.text() == "已加入"
    assert status_item.foreground().color() != missing_color
    assert page.song_list.cellWidget(0, 6) is None

    page.set_playlist_song_ids(())
    assert page.song_list.item(0, 6).text() == "未加入"
    assert page.song_list.cellWidget(0, 6) is not None


def test_library_row_add_button_emits_only_its_song_path(
    qtbot: QtBot,
    package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    page = LibraryPage()
    qtbot.addWidget(page)
    requested: list[tuple[Path, ...]] = []
    page.add_to_playlist_requested.connect(requested.append)
    page.show_scan_result(LibraryScanResult(songs=(package,), broken=()))

    action_cell = page.song_list.cellWidget(0, 6)
    assert action_cell is not None
    add_button = action_cell.findChild(QPushButton, "libraryRowAddButton")
    assert add_button is not None
    add_button.click()

    assert requested == [(package.root,)]


def test_library_actions_have_one_edit_button(qtbot: QtBot) -> None:
    page = LibraryPage()
    qtbot.addWidget(page)

    buttons = (
        page.add_button,
        page.edit_button,
        page.delete_button,
    )
    assert [button.text() for button in buttons] == [
        "添加到播放列表",
        "修改",
        "删除",
    ]
    assert all(not button.icon().isNull() for button in buttons)
    assert not any(button.text() == "加载当前歌曲" for button in page.findChildren(QPushButton))


def test_library_editor_emits_selected_song_path(
    qtbot: QtBot,
    package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    page = LibraryPage()
    qtbot.addWidget(page)
    requested: list[Path] = []
    page.edit_requested.connect(requested.append)
    page.show_scan_result(LibraryScanResult(songs=(package,), broken=()))

    page.song_list.selectRow(0)
    page.edit_button.click()

    assert requested == [package.root]


def test_library_export_emits_selected_song_path(
    qtbot: QtBot,
    package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    page = LibraryPage()
    qtbot.addWidget(page)
    requested: list[Path] = []
    page.export_requested.connect(requested.append)
    page.show_scan_result(LibraryScanResult(songs=(package,), broken=()))

    page.song_list.selectRow(0)
    page.export_button.click()

    assert requested == [package.root]


def test_export_dialog_defaults_to_song_title_and_artist(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    package_factory: Callable[[], Path],
) -> None:
    package_root = package_factory()
    page = LibraryPage()
    qtbot.addWidget(page)
    settings = QSettings(str(tmp_path / "export.ini"), QSettings.Format.IniFormat)
    controller = LibraryController(
        page, LibraryService(package_root.parent), SettingsService(settings), parent=page
    )
    suggested: list[str] = []

    def capture_dialog(_parent: object, _caption: str, path: str, _filter: str):
        suggested.append(path)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", capture_dialog)
    controller._export_song(package_root)

    assert Path(suggested[0]).name == "测试歌曲-测试歌手.zip"
    assert LibraryController._export_archive_name("歌/曲", "歌:手") == "歌_曲-歌_手.zip"


def test_library_double_click_emits_edit_request(
    qtbot: QtBot,
    package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    page = LibraryPage()
    qtbot.addWidget(page)
    requested: list[Path] = []
    page.edit_requested.connect(requested.append)
    page.show_scan_result(LibraryScanResult(songs=(package,), broken=()))

    page.song_list.cellDoubleClicked.emit(0, 0)

    assert requested == [package.root]
    assert page.song_list.toolTip() == "双击歌曲可进入修改界面"


def test_library_delete_requires_confirmation_and_permanently_removes_song(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    package_factory: Callable[[], Path],
) -> None:
    package_root = package_factory()
    service = LibraryService(package_root.parent)
    page = LibraryPage()
    qtbot.addWidget(page)
    settings = QSettings(str(tmp_path / "delete.ini"), QSettings.Format.IniFormat)
    controller = LibraryController(
        page,
        service,
        SettingsService(settings),
        parent=page,
    )
    page.song_list.selectRow(0)
    responses = [QDialog.DialogCode.Rejected, QDialog.DialogCode.Accepted]
    prompts: list[DestructiveConfirmationDialog] = []

    def answer(dialog: DestructiveConfirmationDialog) -> QDialog.DialogCode:
        prompts.append(dialog)
        return responses.pop(0)

    monkeypatch.setattr(DestructiveConfirmationDialog, "exec", answer)

    controller._delete(package_root)
    assert package_root.is_dir()
    controller._delete(package_root)

    assert not package_root.exists()
    assert not (service.root / ".trash").exists()
    assert prompts[0].windowTitle() == "删除歌曲"
    assert prompts[0].findChild(QLabel, "confirmationMessage").text() == (
        "确定永久删除“测试歌曲”吗？"
    )
    assert prompts[0].findChild(QLabel, "confirmationDetail").text() == "此操作无法撤销。"
    assert prompts[0].cancel_button.text() == "取消"
    assert prompts[0].confirm_button.text() == "永久删除"
    assert not prompts[0].cancel_button.icon().isNull()
    assert not prompts[0].confirm_button.icon().isNull()
    assert prompts[0].cancel_button.isDefault()
    assert page.status_label.text() == "已永久删除歌曲：测试歌曲"


def test_library_table_emits_selected_song_path(
    qtbot: QtBot,
    package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    page = LibraryPage()
    qtbot.addWidget(page)
    requested: list[Path] = []
    page.load_requested.connect(requested.append)
    page.show_scan_result(LibraryScanResult(songs=(package,), broken=()))

    page.song_list.selectRow(0)
    page._request_load()

    assert requested == [package.root]


def test_library_can_add_multiple_selected_songs(
    qtbot: QtBot,
    package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    second = package.__class__(
        root=package.root.parent / "second",
        config=package.config,
        lyrics=package.lyrics,
        warnings=package.warnings,
    )
    page = LibraryPage()
    qtbot.addWidget(page)
    requested: list[tuple[Path, ...]] = []
    page.add_to_playlist_requested.connect(requested.append)
    page.show_scan_result(LibraryScanResult(songs=(package, second), broken=()))

    page.song_list.selectRow(0)
    page.song_list.selectionModel().select(
        page.song_list.model().index(1, 0),
        page.song_list.selectionModel().SelectionFlag.Select
        | page.song_list.selectionModel().SelectionFlag.Rows,
    )
    page._request_add_to_playlist()

    assert requested == [(package.root, second.root)]


def test_library_table_sorts_numeric_columns_by_value(
    qtbot: QtBot,
    package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    slow_payload = package.config.model_dump(mode="python")
    slow_payload.update(title="慢歌", musical=MusicalConfig(original_key="C", bpm=90))
    slow = package.__class__(
        root=package.root.parent / "slow",
        config=SongConfig.model_validate(slow_payload, strict=True),
        lyrics=package.lyrics,
        warnings=package.warnings,
    )
    fast_payload = package.config.model_dump(mode="python")
    fast_payload.update(title="快歌", musical=MusicalConfig(original_key="D", bpm=100))
    fast = package.__class__(
        root=package.root.parent / "fast",
        config=SongConfig.model_validate(fast_payload, strict=True),
        lyrics=package.lyrics,
        warnings=package.warnings,
    )
    page = LibraryPage()
    qtbot.addWidget(page)
    page.show_scan_result(LibraryScanResult(songs=(fast, slow), broken=()))

    assert page.song_list.isSortingEnabled()
    assert page.song_list.horizontalHeader().sectionsClickable()

    page.song_list.sortItems(4, Qt.SortOrder.AscendingOrder)
    assert [page.song_list.item(row, 4).text() for row in range(2)] == ["90", "100"]

    page.song_list.sortItems(4, Qt.SortOrder.DescendingOrder)
    assert [page.song_list.item(row, 4).text() for row in range(2)] == ["100", "90"]


def test_library_table_defaults_to_newest_created_song_first(
    qtbot: QtBot,
    package_factory: Callable[[], Path],
) -> None:
    older = SongPackageValidator().validate(package_factory(), verify_media=False)
    newer_payload = older.config.model_dump(mode="python")
    newer_payload.update(
        title="较新的歌曲",
        created_at=older.config.created_at + timedelta(days=1),
    )
    newer = older.__class__(
        root=older.root.parent / "newer",
        config=SongConfig.model_validate(newer_payload, strict=True),
        lyrics=older.lyrics,
        warnings=older.warnings,
    )
    page = LibraryPage()
    qtbot.addWidget(page)

    page.show_scan_result(LibraryScanResult(songs=(older, newer), broken=()))

    header = page.song_list.horizontalHeader()
    assert header.sortIndicatorSection() == 5
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    assert [page.song_list.item(row, 0).text() for row in range(2)] == [
        "较新的歌曲",
        older.config.title,
    ]


def test_chord_backfill_reuses_recognition_without_opening_editor(
    qtbot: QtBot,
    package_factory: Callable[[], Path],
    monkeypatch: MonkeyPatch,
) -> None:
    package_root = package_factory()
    service = LibraryService(package_root.parent)
    page = LibraryPage()
    qtbot.addWidget(page)
    controller = LibraryController(page, service, SettingsService())
    recognized: list[Path] = []
    timeline = ChordTimeline(
        segments=[ChordSegment(start_ms=0, end_ms=1000, chord="C")]
    )

    def recognize(package: SongPackage) -> ChordTimeline:
        recognized.append(package.root)
        return timeline

    monkeypatch.setattr(controller, "_recognize_chords", recognize)
    missing = controller.missing_chord_packages()

    assert len(missing) == 1
    with qtbot.waitSignal(controller.chord_batch_finished, timeout=3000) as finished:
        assert controller.start_chord_backfill(missing)

    assert finished.args[:2] == [1, 0]
    assert recognized == [package_root]
    assert service.scan().songs[0].chords == timeline
    assert controller._edit_dialog is None


def test_chord_reanalysis_uses_timed_chords_without_score_bars(
    package_factory: Callable[[], Path], monkeypatch: MonkeyPatch,
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)

    def run_stems(_runner: SheetSage2Runner, _stems: object, output: Path,
                  _cancellation: object) -> Path:
        (output / "chord.lab").write_text("0 1 C:maj\n", encoding="utf-8")
        return output

    monkeypatch.setattr(SheetSage2Runner, "run_stems", run_stems)

    timeline = LibraryController._recognize_chords(package)

    assert [(item.start_ms, item.end_ms, item.chord) for item in timeline.segments] == [
        (0, 1000, "C:maj"),
    ]
