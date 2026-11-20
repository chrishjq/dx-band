# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton
from pytestqt.qtbot import QtBot

from dxband.analysis.sheetsage2_package import SheetSage2Analysis
from dxband.constants import TrackKind
from dxband.creation.package_validator import SongPackage, SongPackageValidator
from dxband.models.chord import ChordSegment, ChordTimeline
from dxband.models.lyric import WordTiming
from dxband.models.melody import MelodyBar, MelodyDocument, MelodyNote
from dxband.models.song import MusicalConfig
from dxband.ui.dialogs.song_edit_dialog import SongEditDialog, SongEditResult


class FakeTransport:
    def __init__(self) -> None:
        self.paused = False
        self.position = 0

    def pause(self) -> None:
        self.paused = True

    def position_ms(self) -> int:
        return self.position

    def duration_ms(self) -> int:
        return 10_000

    def set_track_muted(self, _track: TrackKind, _muted: bool) -> None:
        return


def test_song_edit_workspace_has_two_tabs_and_shared_loading_style(
    qtbot: QtBot, package_factory: Callable[[], Path]
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    player = FakeTransport()
    dialog = SongEditDialog(package, player, "degree")  # type: ignore[arg-type]
    qtbot.addWidget(dialog)

    assert dialog.tabs.count() == 2
    assert [dialog.tabs.tabText(index) for index in range(2)] == ["歌词", "和弦"]
    assert dialog.tabs.isTabEnabled(1)
    assert dialog.width() >= 1280
    assert dialog.height() >= 700
    assert isinstance(dialog.analysis_progress, QProgressBar)
    assert dialog.analysis_progress.objectName() == "analysisProgress"
    assert dialog.lyric_editor.reanalyze_music_button.isHidden()
    assert dialog.lyric_editor.music_analysis_progress.isHidden()
    assert not dialog.chord_editor.reanalyze_button.isHidden()
    assert dialog.chord_editor.reanalyze_button.text() == "重新识别和弦"
    assert dialog.chord_editor.progress.isHidden()
    assert dialog.layout().indexOf(dialog.metadata_panel) < dialog.layout().indexOf(dialog.tabs)
    assert dialog.layout().indexOf(dialog.metadata_panel) < dialog.layout().indexOf(
        dialog.preview_panel
    )
    assert dialog.layout().indexOf(dialog.preview_panel) < dialog.layout().indexOf(dialog.tabs)
    assert dialog.preview_panel.parentWidget() is dialog
    assert dialog.lyric_editor.layout().indexOf(dialog.preview_panel) == -1
    assert dialog.lyric_editor.current_lyric_label.isHidden()
    dialog.show()
    for tab_index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(tab_index)
        assert dialog.preview_panel.isVisibleTo(dialog)
        assert dialog.lyric_editor.play_button.isVisibleTo(dialog.preview_panel)
    assert dialog.reanalyze_button.text() == "重新分析全部"
    assert not dialog.reanalyze_button.icon().isNull()
    assert not dialog.save_button.icon().isNull()
    assert not dialog.lyric_editor.play_button.icon().isNull()
    assert not dialog.lyric_editor.stop_button.icon().isNull()
    assert not dialog.chord_editor.reanalyze_button.icon().isNull()
    assert (
        dialog.reanalyze_button.icon().cacheKey()
        != dialog.chord_editor.reanalyze_button.icon().cacheKey()
    )
    assert not dialog.lyric_editor.undo_button.icon().isNull()
    assert not dialog.lyric_editor.redo_button.icon().isNull()
    assert (
        dialog.lyric_editor.undo_button.icon().cacheKey()
        != dialog.lyric_editor.redo_button.icon().cacheKey()
    )
    assert not any(
        button.text() == "识别字词时间" for button in dialog.findChildren(QPushButton)
    )
    removed_buttons = {
        "全部歌词偏移", "开始 -100ms", "开始 +100ms", "结束 -100ms", "结束 +100ms"
    }
    assert not any(
        button.text() in removed_buttons for button in dialog.findChildren(QPushButton)
    )

    music_requests: list[bool] = []
    chord_requests: list[bool] = []
    lyric_timing_requests: list[bool] = []
    full_requests: list[bool] = []
    dialog.lyric_editor.music_reanalysis_requested.connect(
        lambda: music_requests.append(True)
    )
    dialog.chord_editor.reanalysis_requested.connect(lambda: chord_requests.append(True))
    dialog.lyric_timing_reanalysis_requested.connect(
        lambda: lyric_timing_requests.append(True)
    )
    dialog.full_reanalysis_requested.connect(lambda: full_requests.append(True))
    dialog.reanalyze_button.click()
    assert full_requests == [True]
    assert music_requests == []
    assert chord_requests == []
    assert lyric_timing_requests == []
    assert not dialog.save_button.isEnabled()
    assert not dialog.analysis_progress.isHidden()
    dialog.show_full_reanalysis_error("test")
    assert dialog.save_button.isEnabled()
    assert dialog.analysis_progress.isHidden()

    labels = {label.text() for label in dialog.findChildren(QLabel)}
    assert "歌曲信息和节奏" in labels
    assert "选择第一行即可偏移全部歌词" not in labels
    assert "修改完成后可直接保存" not in labels
    assert "编辑完成后统一保存歌词、歌曲信息和和弦" not in labels
    assert not any(
        label.text().startswith("原 Key：")
        for label in dialog.chord_editor.findChildren(QLabel)
    )


def test_both_song_edit_tabs_can_search_lyrics(
    qtbot: QtBot, package_factory: Callable[[], Path]
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    musical = MusicalConfig(
        original_key="C",
        bpm=120,
        beat_times_ms=list(range(0, 10_000, 500)),
        downbeat_times_ms=list(range(0, 10_000, 2_000)),
        beats_per_bar=4,
    )
    package = SongPackage(
        root=package.root,
        config=package.config.model_copy(update={"musical": musical}),
        lyrics=package.lyrics,
        chords=package.chords,
    )
    dialog = SongEditDialog(package, FakeTransport(), "degree")  # type: ignore[arg-type]
    qtbot.addWidget(dialog)

    dialog.lyric_editor.lyric_search_edit.setText("句歌词")
    assert dialog.lyric_editor.table.currentRow() == 0
    assert dialog.lyric_editor.lyric_search_result_label.text() == "1/2"
    dialog.lyric_editor.lyric_search_next_button.click()
    assert dialog.lyric_editor.table.currentRow() == 1
    assert dialog.lyric_editor.lyric_search_result_label.text() == "2/2"
    dialog.lyric_editor.lyric_search_previous_button.click()
    assert dialog.lyric_editor.table.currentRow() == 0

    dialog.tabs.setCurrentIndex(1)
    dialog.chord_editor.lyric_search_edit.setText("句歌词")
    assert dialog.chord_editor.lyric_search_result_label.text() == "1/2"
    assert dialog.chord_editor._lyric_search_highlight is not None
    assert dialog.chord_editor._lyric_search_highlight.property("searchMatch")
    first_highlight = dialog.chord_editor._lyric_search_highlight
    dialog.chord_editor.lyric_search_next_button.click()
    assert dialog.chord_editor.lyric_search_result_label.text() == "2/2"
    assert dialog.chord_editor._lyric_search_highlight is not first_highlight
    assert not first_highlight.property("searchMatch")


def test_song_edit_workspace_syncs_lyrics_and_saves_one_result(
    qtbot: QtBot, package_factory: Callable[[], Path]
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    player = FakeTransport()
    dialog = SongEditDialog(package, player, "degree")  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    results: list[SongEditResult] = []
    dialog.saved.connect(results.append)

    dialog.lyric_editor.title_edit.setText("新歌名")
    dialog.lyric_editor.table.selectRow(1)
    dialog.lyric_editor.offset_spin.setValue(250)
    dialog.lyric_editor._apply_offset_from_selected()
    dialog.tabs.setCurrentIndex(1)
    assert dialog.chord_editor.title == "新歌名"
    assert dialog.chord_editor.document.lines[1].start_ms == 6_250

    chords = ChordTimeline(
        segments=[ChordSegment(start_ms=1_000, end_ms=2_000, chord="G:maj")]
    )
    dialog.chord_editor.timeline = chords
    dialog.save_button.click()

    assert len(results) == 1
    assert results[0].lyrics.title == "新歌名"
    assert results[0].lyrics.document.lines[1].start_ms == 6_250
    assert results[0].chords == chords


def test_first_lyric_row_offset_moves_all_lines(
    qtbot: QtBot, package_factory: Callable[[], Path]
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    dialog = SongEditDialog(package, FakeTransport(), "degree")  # type: ignore[arg-type]
    qtbot.addWidget(dialog)

    dialog.lyric_editor.table.selectRow(0)
    dialog.lyric_editor.offset_spin.setValue(300)
    dialog.lyric_editor._apply_offset_from_selected()

    assert [line.start_ms for line in dialog.lyric_editor.document.lines] == [1_300, 6_300]


def test_chord_modes_follow_draft_original_key(
    qtbot: QtBot, package_factory: Callable[[], Path]
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    dialog = SongEditDialog(package, FakeTransport(), "degree")  # type: ignore[arg-type]
    qtbot.addWidget(dialog)

    dialog.lyric_editor.original_key_edit.setText("not a key")
    dialog.tabs.setCurrentIndex(1)
    assert dialog.chord_editor.current_mode() == "chord"
    assert not dialog.chord_editor.mode_combo.model().item(0).isEnabled()

    dialog.tabs.setCurrentIndex(0)
    dialog.lyric_editor.original_key_edit.setText("D")
    dialog.tabs.setCurrentIndex(1)
    assert dialog.chord_editor.mode_combo.model().item(0).isEnabled()


def test_existing_song_can_realign_word_times_without_replacing_lyrics(
    qtbot: QtBot, package_factory: Callable[[], Path]
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    dialog = SongEditDialog(package, FakeTransport(), "degree")  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    requests: list[bool] = []
    dialog.full_reanalysis_requested.connect(lambda: requests.append(True))

    dialog.reanalyze_button.click()
    assert requests == [True]
    assert not dialog.save_button.isEnabled()

    reference = dialog.lyric_editor.document
    first_line = reference.lines[0]
    words = [
        WordTiming(text=text, start_ms=1_500 + index * 200, end_ms=1_700 + index * 200)
        for index, text in enumerate("第一句歌词")
    ]
    aligned = reference.model_copy(
        update={"lines": [first_line.model_copy(update={"words": words}), *reference.lines[1:]]}
    )
    dialog.apply_lyric_timing_analysis(aligned)

    first = dialog.lyric_editor.document.lines[0]
    assert first.text == "第一句歌词"
    assert len(first.words) == len(first.text)
    assert first.words[0].start_ms == 1_500
    dialog.lyric_editor.show_music_analysis_error("test")
    dialog.chord_editor.show_reanalysis_error("test")
    assert dialog.save_button.isEnabled()
    dialog.lyric_editor.undo_stack.undo()
    assert dialog.lyric_editor.document.lines[0].words == []


def test_full_reanalysis_saves_rebuilt_melody(
    qtbot: QtBot, package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    dialog = SongEditDialog(package, FakeTransport(), "degree")  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    melody = MelodyDocument(
        tonic_midi=60, coverage_end_ms=2_000,
        notes=[MelodyNote(start_ms=500, end_ms=750, midi=64, source="vocals")],
        bars=[MelodyBar(start_ms=0, end_ms=2_000,
                        beat_times_ms=[0, 500, 1_000, 1_500])],
    )
    score = SheetSage2Analysis(
        original_key="C", bpm=120,
        beat_times_ms=list(range(0, 10_000, 500)),
        downbeat_times_ms=list(range(0, 10_000, 2_000)),
        beats_per_bar=4, chords=ChordTimeline(), melody=melody,
    )
    saved: list[SongEditResult] = []
    dialog.saved.connect(saved.append)

    dialog.reanalyze_button.click()
    dialog.apply_full_reanalysis(score, package.lyrics, melody)
    dialog.save_button.click()

    assert len(saved) == 1
    assert saved[0].melody == melody


def test_beat_lyric_changes_sync_to_song_save(
    qtbot: QtBot, package_factory: Callable[[], Path]
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    musical = MusicalConfig(
        original_key="C",
        bpm=120,
        beat_times_ms=list(range(0, 10_000, 500)),
        downbeat_times_ms=list(range(0, 10_000, 2_000)),
        beats_per_bar=4,
    )
    package = SongPackage(
        root=package.root,
        config=package.config.model_copy(update={"musical": musical}),
        lyrics=package.lyrics,
        chords=package.chords,
    )
    player = FakeTransport()
    dialog = SongEditDialog(package, player, "degree")  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    results: list[SongEditResult] = []
    dialog.saved.connect(results.append)
    dialog.tabs.setCurrentIndex(1)
    assert dialog.chord_editor.beat_rows
    player.position = 4_500
    dialog.lyric_editor._refresh_position()
    assert dialog.chord_editor._active_measure_index == 2
    assert dialog.chord_editor.beat_rows[0].measures[2].property("currentMeasure")
    assert not dialog.chord_editor.beat_rows[0].measures[0].property("currentMeasure")
    editor = next(
        editor
        for row in dialog.chord_editor.beat_rows
        for editor in row.lyric_editors
        if editor.text().startswith("第")
    )
    editor.setText("新" + editor.text()[1:])
    editor.editingFinished.emit()

    assert dialog.lyric_editor.document.lines[0].text.startswith("新")
    dialog.save_button.click()
    assert len(results) == 1
    assert results[0].lyrics.document.lines[0].text.startswith("新")


def test_save_keeps_visible_lyrics_after_cut_without_paste(
    qtbot: QtBot, package_factory: Callable[[], Path]
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    musical = MusicalConfig(
        original_key="C",
        bpm=120,
        beat_times_ms=list(range(0, 10_000, 500)),
        downbeat_times_ms=list(range(0, 10_000, 2_000)),
        beats_per_bar=4,
    )
    package = SongPackage(
        root=package.root,
        config=package.config.model_copy(update={"musical": musical}),
        lyrics=package.lyrics,
        chords=package.chords,
    )
    dialog = SongEditDialog(package, FakeTransport(), "degree")  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    results: list[SongEditResult] = []
    dialog.saved.connect(results.append)
    dialog.tabs.setCurrentIndex(1)
    original = dialog.lyric_editor.document.lines[0].text
    source = next(
        editor
        for row in dialog.chord_editor.beat_rows
        for editor in row.lyric_editors
        if editor.text() and editor.text() in original and len(editor.text()) < len(original)
    )
    removed = source.text()
    source.clear()
    source.editingFinished.emit()

    assert source.text() == ""
    assert dialog.chord_editor.status_label.isHidden()
    assert dialog.status_label.isHidden()
    dialog.save_button.click()

    assert len(results) == 1
    assert removed not in results[0].lyrics.document.lines[0].text
    assert results[0].lyrics.document.lines[0].text != original
