# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

from pytestqt.qtbot import QtBot

from dxband.constants import TrackKind
from dxband.models.lyric import LyricLine, LyricsDocument
from dxband.ui.dialogs.lyric_review_dialog import (
    LyricReviewDialog,
    LyricReviewResult,
)


class FakeTransport:
    def __init__(self) -> None:
        self.position = 0
        self.play_calls = 0
        self.pause_calls = 0
        self.muted = {track: False for track in TrackKind}

    def play(self) -> None:
        self.play_calls += 1

    def pause(self) -> None:
        self.pause_calls += 1

    def stop(self) -> None:
        self.position = 0

    def seek_ms(self, position_ms: int) -> None:
        self.position = position_ms

    def position_ms(self) -> int:
        return self.position

    def duration_ms(self) -> int:
        return 10_000

    def set_track_muted(self, track: TrackKind, muted: bool) -> None:
        self.muted[track] = muted

    def is_track_muted(self, track: TrackKind) -> bool:
        return self.muted[track]


def _document() -> LyricsDocument:
    return LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=1_000,
                end_ms=4_000,
                text="第一句",
                words=[],
            ),
            LyricLine(
                id="line-0002",
                start_ms=5_000,
                end_ms=9_000,
                text="第二句",
                words=[],
            ),
        ],
    )


def test_review_dialog_follows_current_lyric(qtbot: QtBot, tmp_path: Path) -> None:
    player = FakeTransport()
    dialog = LyricReviewDialog(
        document=_document(),
        duration_ms=10_000,
        title="测试歌曲",
        autosave_path=tmp_path / "draft.json",
        player=player,
    )
    qtbot.addWidget(dialog)

    player.position = 1_500
    dialog._refresh_position()
    assert dialog.table.currentRow() == 0
    assert dialog.current_lyric_label.text() == "当前歌词：第一句"

    player.position = 4_500
    dialog._refresh_position()
    assert dialog.current_lyric_label.text() == "当前歌词：间奏（下一句：第二句）"

    player.position = 5_500
    dialog._refresh_position()
    assert dialog.table.currentRow() == 1
    assert dialog.current_lyric_label.text() == "当前歌词：第二句"


def test_review_dialog_starts_with_all_tracks_unmuted(qtbot: QtBot) -> None:
    player = FakeTransport()
    player.muted = {track: True for track in TrackKind}

    dialog = LyricReviewDialog(
        document=_document(),
        duration_ms=10_000,
        title="测试歌曲",
        player=player,
    )
    qtbot.addWidget(dialog)

    assert all(not check.isChecked() for check in dialog.mute_checks.values())
    assert all(not player.is_track_muted(track) for track in TrackKind)


def test_clicking_lyric_row_seeks_without_changing_playback_state(qtbot: QtBot) -> None:
    player = FakeTransport()
    dialog = LyricReviewDialog(
        document=_document(),
        duration_ms=10_000,
        title="测试歌曲",
        player=player,
    )
    qtbot.addWidget(dialog)

    dialog.table.cellClicked.emit(1, 2)

    assert player.position == 5_000
    assert player.play_calls == 0
    assert player.pause_calls == 0
    assert dialog.play_button.text() == "播放"

    dialog.play_button.click()
    dialog.table.cellClicked.emit(0, 2)

    assert player.position == 1_000
    assert player.play_calls == 1
    assert player.pause_calls == 0
    assert dialog.play_button.text() == "暂停"


def test_play_button_toggles_between_play_and_pause(qtbot: QtBot) -> None:
    player = FakeTransport()
    dialog = LyricReviewDialog(
        document=_document(),
        duration_ms=10_000,
        title="测试歌曲",
        player=player,
    )
    qtbot.addWidget(dialog)

    dialog.play_button.click()
    assert player.play_calls == 1
    assert dialog.play_button.text() == "暂停"

    dialog.play_button.click()
    assert player.pause_calls == 1
    assert dialog.play_button.text() == "播放"


def test_loop_current_line_keeps_original_selected_row(qtbot: QtBot) -> None:
    player = FakeTransport()
    dialog = LyricReviewDialog(
        document=_document(),
        duration_ms=10_000,
        title="测试歌曲",
        player=player,
    )
    qtbot.addWidget(dialog)
    dialog.table.selectRow(0)
    dialog.loop_check.setChecked(True)

    player.position = 4_100
    dialog._refresh_position()

    assert player.position == 1_000
    assert player.play_calls == 1
    assert dialog.table.currentRow() == 0
    assert dialog.current_lyric_label.text() == "当前歌词：第一句"


def test_review_dialog_offsets_selected_line_and_all_following_lines(qtbot: QtBot) -> None:
    dialog = LyricReviewDialog(
        document=_document(),
        duration_ms=12_000,
        title="测试歌曲",
    )
    qtbot.addWidget(dialog)

    dialog.table.selectRow(1)
    dialog.offset_spin.setValue(500)
    dialog._apply_offset_from_selected()

    assert dialog.document.lines[0].start_ms == 1_000
    assert dialog.document.lines[1].start_ms == 5_500
    assert "第 2 行及后续歌词整体后移 500 ms" in dialog.status_label.text()

    dialog.undo_stack.undo()
    assert dialog.document.lines[1].start_ms == 5_000


def test_review_dialog_can_edit_title_and_artist(qtbot: QtBot) -> None:
    dialog = LyricReviewDialog(
        document=_document(),
        duration_ms=10_000,
        title="测试歌曲",
        artist="原歌手",
        original_key="D",
        bpm=120,
        beat_times_ms=(0, 500, 1_000),
        require_confirmation=False,
        metadata_editable=True,
    )
    qtbot.addWidget(dialog)
    results: list[LyricReviewResult] = []
    dialog.lyrics_confirmed.connect(results.append)

    dialog.title_edit.setText("  新歌名  ")
    dialog.artist_edit.setText("  新歌手  ")
    dialog.original_key_edit.setText("  F#m  ")
    dialog.confirm_button.click()

    assert len(results) == 1
    assert results[0].title == "新歌名"
    assert results[0].artist == "新歌手"
    assert results[0].original_key == "F#m"
    assert not dialog.bpm_spin.isEnabled()
    assert results[0].bpm == 120
    assert results[0].beat_times_ms == (0, 500, 1_000)
    assert results[0].document.title == "新歌名"


def test_song_edit_can_save_without_listening_confirmation(qtbot: QtBot) -> None:
    dialog = LyricReviewDialog(
        document=_document(),
        duration_ms=10_000,
        title="测试歌曲",
        artist="测试歌手",
        original_key="D",
        bpm=120,
        require_confirmation=False,
        metadata_editable=True,
    )
    qtbot.addWidget(dialog)
    results: list[LyricReviewResult] = []
    dialog.lyrics_confirmed.connect(results.append)

    assert dialog.confirm_check.isHidden()
    dialog.confirm_button.click()

    assert len(results) == 1


def test_song_edit_reanalysis_replaces_key_bpm_and_beat_table(qtbot: QtBot) -> None:
    dialog = LyricReviewDialog(
        document=_document(),
        duration_ms=10_000,
        title="测试歌曲",
        original_key="D",
        bpm=120,
        beat_times_ms=(0, 500, 1_000),
        require_confirmation=False,
        metadata_editable=True,
    )
    qtbot.addWidget(dialog)
    requests: list[bool] = []
    dialog.music_reanalysis_requested.connect(lambda: requests.append(True))

    assert dialog.reanalyze_music_button.text() == "重新分析节奏和KEY"
    dialog.reanalyze_music_button.click()
    assert requests == [True]
    assert not dialog.reanalyze_music_button.isEnabled()
    assert dialog.reanalyze_music_button.text() == "分析中…"
    assert not dialog.music_analysis_progress.isHidden()
    assert not dialog.confirm_button.isEnabled()

    dialog.apply_music_analysis(
        "A",
        65,
        (100, 1_023, 1_946),
        (100,),
        3,
    )

    assert dialog.original_key_edit.text() == "A"
    assert dialog.bpm_spin.value() == 65
    assert dialog.reanalyze_music_button.isEnabled()
    assert dialog.reanalyze_music_button.text() == "重新分析节奏和KEY"
    assert dialog.music_analysis_progress.isHidden()
    assert dialog.confirm_button.isEnabled()
    assert "原 Key A" in dialog.status_label.text()
    assert "共 3 个拍点" in dialog.status_label.text()


def test_song_edit_reanalysis_error_stops_loading_state(qtbot: QtBot) -> None:
    dialog = LyricReviewDialog(
        document=_document(),
        duration_ms=10_000,
        title="测试歌曲",
        original_key="D",
        bpm=120,
        require_confirmation=False,
        metadata_editable=True,
    )
    qtbot.addWidget(dialog)

    dialog.reanalyze_music_button.click()
    dialog.show_music_analysis_error("重新分析失败")

    assert dialog.reanalyze_music_button.isEnabled()
    assert dialog.reanalyze_music_button.text() == "重新分析节奏和KEY"
    assert dialog.music_analysis_progress.isHidden()
    assert dialog.confirm_button.isEnabled()
    assert dialog.status_label.text() == "重新分析失败"


def test_creation_review_hides_unrelated_song_info_editors(qtbot: QtBot) -> None:
    dialog = LyricReviewDialog(
        document=_document(),
        duration_ms=10_000,
        title="测试歌曲",
        bpm=112,
    )
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.title_edit.isHidden()
    assert dialog.artist_edit.isHidden()
    assert dialog.original_key_edit.isHidden()
    assert dialog.bpm_spin.isHidden()
    assert dialog.reanalyze_music_button.isHidden()


def test_review_dialog_initial_focus_is_on_lyrics_table(qtbot: QtBot) -> None:
    dialog = LyricReviewDialog(
        document=_document(),
        duration_ms=10_000,
        title="测试歌曲",
        bpm=112,
    )
    qtbot.addWidget(dialog)

    dialog.show()

    assert dialog.focusWidget() is dialog.table
