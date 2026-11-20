# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import queue
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from dxband.analysis.sheetsage2_package import (
    SheetSage2Analysis,
    read_sheetsage2_chords,
    read_sheetsage2_package,
)
from dxband.audio.pcm_cache import PcmCacheService, PcmSongData
from dxband.audio.stem_mixer import StemMixerEngine
from dxband.constants import TrackKind
from dxband.creation.beat_this_runner import BeatThisRunner
from dxband.creation.cancellation import CancellationToken
from dxband.creation.ctc_lyrics_aligner import LrcCtcAligner
from dxband.creation.fun_asr_runner import FunAsrRunner
from dxband.creation.lyrics_strategy import timing_language
from dxband.creation.package_validator import SongPackage
from dxband.creation.sheetsage2_runner import SheetSage2Runner
from dxband.creation.song_analysis import SongAnalysis, assemble_song_analysis
from dxband.models.chord import ChordTimeline
from dxband.models.lyric import LyricsDocument
from dxband.services.library_service import (
    DuplicateSongIdError,
    LibraryService,
    SongImportResult,
)
from dxband.services.paths import resolve_package_path
from dxband.ui.dialogs.confirmation_dialog import (
    DestructiveConfirmationDialog,
)
from dxband.ui.dialogs.song_edit_dialog import SongEditDialog, SongEditResult
from dxband.ui.pages.library_page import LibraryPage
from dxband.ui.public_messages import public_message
from dxband.ui.services.settings_service import SettingsService


class LibraryController(QObject):
    song_load_requested = Signal(object)
    song_load_failed = Signal(str)
    song_lyrics_updated = Signal(object)
    song_chords_updated = Signal(object)

    def __init__(
        self,
        page: LibraryPage,
        service: LibraryService,
        settings_service: SettingsService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.page = page
        self.service = service
        self.settings_service = settings_service
        self.playing_song_id: str | None = None
        self._load_generation = 0
        self._edit_generation = 0
        self._pcm_cache = PcmCacheService()
        self._edit_engine: StemMixerEngine | None = None
        self._edit_dialog: SongEditDialog | None = None
        self._editing_package: SongPackage | None = None
        self._messages: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._drain_messages)
        self._timer.start()
        self.page.refresh_requested.connect(self.refresh)
        self.page.import_requested.connect(self._import_song)
        self.page.export_requested.connect(self._export_song)
        self.page.search_changed.connect(self.refresh)
        self.page.load_requested.connect(self._load)
        self.page.edit_requested.connect(self._edit_song)
        self.page.delete_requested.connect(self._delete)
        self.refresh()

    def refresh(self, query: str | None = None) -> None:
        try:
            search = self.page.search_edit.text() if query is None else query
            self.page.show_scan_result(self.service.scan(search))
        except Exception as exc:
            self.page.show_error(str(exc))

    def _load(self, value: object) -> None:
        if not isinstance(value, Path):
            self.page.show_error("歌曲路径无效")
            return
        self.load_path(value)

    def load_path(self, path: Path, auto_play: bool = False) -> None:
        """在后台校验歌曲；自动续播时保留播放意图。"""
        self._load_generation += 1
        generation = self._load_generation
        self.page.status_label.setText("正在后台完整校验歌曲包……")
        threading.Thread(
            target=self._load_in_background,
            args=(generation, path, auto_play),
            name="library-package-load",
            daemon=True,
        ).start()

    def _load_in_background(self, generation: int, path: Path, auto_play: bool) -> None:
        try:
            package = self.service.load(path)
            self._messages.put(("loaded", (generation, (package, auto_play))))
        except Exception as exc:
            self._messages.put(("load_failed", (generation, str(exc))))

    def _drain_messages(self) -> None:
        while True:
            try:
                event, payload = self._messages.get_nowait()
            except queue.Empty:
                return
            if not isinstance(payload, tuple) or len(payload) != 2:
                continue
            generation, value = payload
            editing_event = event in {
                "edit_loaded",
                "edit_failed",
                "music_analyzed",
                "music_analysis_failed",
                "chords_reanalyzed",
                "chord_reanalysis_failed",
                "lyric_timing_recognized",
                "lyric_timing_failed",
                "full_analyzed",
                "full_analysis_failed",
            }
            current_generation = self._edit_generation if editing_event else self._load_generation
            if generation != current_generation:
                continue
            if event == "loaded":
                self.song_load_requested.emit(value)
            elif event == "load_failed":
                self.page.show_error(str(value))
                self.song_load_failed.emit(str(value))
            elif event == "edit_loaded" and isinstance(value, tuple):
                package, pcm = value
                if isinstance(package, SongPackage) and isinstance(pcm, PcmSongData):
                    self._open_song_editor(package, pcm)
            elif event == "edit_failed":
                self.page.show_error(f"加载歌曲修改工作区失败：{value}")
            elif event == "music_analyzed" and isinstance(value, SheetSage2Analysis):
                if self._edit_dialog is not None:
                    self._edit_dialog.lyric_editor.apply_music_analysis(
                        value.original_key,
                        value.bpm,
                        tuple(value.beat_times_ms),
                        tuple(value.downbeat_times_ms),
                        value.beats_per_bar,
                    )
            elif event == "music_analysis_failed":
                detail = public_message(str(value), "请重试或检查歌曲文件")
                message = f"重新分析节奏和 KEY 失败：{detail}"
                if self._edit_dialog is not None:
                    self._edit_dialog.lyric_editor.show_music_analysis_error(message)
                self.page.show_error(message)
            elif event == "chords_reanalyzed" and isinstance(value, ChordTimeline):
                if self._edit_dialog is not None:
                    self._edit_dialog.chord_editor.apply_reanalysis(value)
            elif event == "chord_reanalysis_failed":
                detail = public_message(str(value), "请重试或检查歌曲文件")
                message = f"重新识别和弦失败：{detail}"
                if self._edit_dialog is not None:
                    self._edit_dialog.chord_editor.show_reanalysis_error(message)
                self.page.show_error(message)
            elif event == "lyric_timing_recognized" and isinstance(value, LyricsDocument):
                if self._edit_dialog is not None:
                    self._edit_dialog.apply_lyric_timing_analysis(value)
            elif event == "lyric_timing_failed":
                message = public_message(str(value), "请重试或检查歌词文件")
                if self._edit_dialog is not None:
                    self._edit_dialog.show_lyric_timing_analysis_error(message)
                self.page.show_error(f"字词时间识别失败：{message}")
            elif event == "full_analyzed" and isinstance(value, SongAnalysis):
                if self._edit_dialog is not None:
                    self._edit_dialog.apply_full_reanalysis(
                        value.score, value.lyrics, value.melody,
                    )
            elif event == "full_analysis_failed":
                message = public_message(str(value), "请检查音频和模型")
                if self._edit_dialog is not None:
                    self._edit_dialog.show_full_reanalysis_error(message)
                self.page.show_error(f"重新分析全部失败：{message}")
            elif event == "imported" and isinstance(value, SongImportResult):
                self.refresh()
                if value.warning:
                    self.page.status_label.setText(value.warning)
                elif value.original_song_id:
                    self.page.status_label.setText(
                        "已创建新歌曲 ID 并导入："
                        f"{value.package.config.title}（{value.package.config.song_id}）"
                    )
                else:
                    self.page.status_label.setText(f"已导入歌曲：{value.package.config.title}")
            elif event == "duplicate_import" and isinstance(value, tuple):
                source, error = value
                if isinstance(source, Path) and isinstance(error, DuplicateSongIdError):
                    self._resolve_duplicate_import(generation, source, error)
            elif event == "exported" and isinstance(value, Path):
                self.page.status_label.setText(f"歌曲包已导出：{value}")
            elif event == "failed":
                self.page.show_error(str(value))

    def _import_song(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self.page,
            "选择要导入的歌曲包 ZIP",
            str(Path.home()),
            "ZIP 文件 (*.zip)",
        )
        if not selected:
            return
        self._load_generation += 1
        generation = self._load_generation
        self.page.status_label.setText("正在校验并导入歌曲包……")
        threading.Thread(
            target=self._import_in_background,
            args=(generation, Path(selected)),
            name="library-song-import",
            daemon=True,
        ).start()

    def _import_in_background(self, generation: int, source: Path) -> None:
        try:
            result = self.service.import_song_archive(source)
            self._messages.put(("imported", (generation, result)))
        except DuplicateSongIdError as exc:
            self._messages.put(("duplicate_import", (generation, (source, exc))))
        except Exception as exc:
            self._messages.put(("failed", (generation, f"导入歌曲失败：{exc}")))

    def _resolve_duplicate_import(
        self,
        generation: int,
        source: Path,
        error: DuplicateSongIdError,
    ) -> None:
        dialog = QMessageBox(self.page)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("歌曲 ID 已存在")
        dialog.setText(f"歌曲“{error.title}”的 ID 已存在")
        dialog.setInformativeText(
            f"重复 ID：{error.song_id}\n请选择停止导入，或创建新歌曲 ID 后继续。"
        )
        stop_button = dialog.addButton(
            "停止导入",
            QMessageBox.ButtonRole.RejectRole,
        )
        continue_button = dialog.addButton(
            "创建新歌曲 ID 并继续",
            QMessageBox.ButtonRole.AcceptRole,
        )
        dialog.setEscapeButton(stop_button)
        dialog.exec()
        if dialog.clickedButton() is not continue_button:
            self.page.status_label.setText("已停止导入，原歌曲包未改动")
            return
        if generation != self._load_generation:
            return
        self.page.status_label.setText("正在创建新歌曲 ID 并继续导入……")
        threading.Thread(
            target=self._import_with_new_id_in_background,
            args=(generation, source),
            name="library-song-import-new-id",
            daemon=True,
        ).start()

    def _import_with_new_id_in_background(self, generation: int, source: Path) -> None:
        try:
            result = self.service.import_song_archive(
                source,
                create_new_id_on_conflict=True,
            )
            self._messages.put(("imported", (generation, result)))
        except Exception as exc:
            self._messages.put(("failed", (generation, f"导入歌曲失败：{exc}")))

    def _export_song(self, value: object) -> None:
        if not isinstance(value, Path):
            self.page.show_error("歌曲路径无效")
            return
        try:
            package = self.service.validator.validate(
                value, verify_media=False, verify_hashes=False
            )
        except Exception as exc:
            self.page.show_error(f"读取歌曲信息失败：{exc}")
            return
        filename = self._export_archive_name(package.config.title, package.config.artist)
        selected, _ = QFileDialog.getSaveFileName(
            self.page,
            "导出歌曲包 ZIP",
            str(Path.home() / filename),
            "ZIP 文件 (*.zip)",
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        self._load_generation += 1
        generation = self._load_generation
        self.page.status_label.setText("正在校验并导出歌曲包……")
        threading.Thread(
            target=self._export_in_background,
            args=(generation, value, destination),
            name="library-song-export",
            daemon=True,
        ).start()

    @staticmethod
    def _export_archive_name(title: str, artist: str) -> str:
        def safe_part(value: str) -> str:
            return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")

        song_title = safe_part(title) or "歌曲包"
        singer = safe_part(artist)
        stem = f"{song_title}-{singer}" if singer else song_title
        stem = stem[:60].rstrip(" .")
        if stem.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(
            r"(?:COM|LPT)[1-9]", stem.upper()
        ):
            stem = f"_{stem}"
        return f"{stem}.zip"

    def _export_in_background(self, generation: int, source: Path, destination: Path) -> None:
        try:
            result = self.service.export_song_archive(source, destination)
            self._messages.put(("exported", (generation, result)))
        except Exception as exc:
            self._messages.put(("failed", (generation, f"导出歌曲失败：{exc}")))

    def _edit_song(self, value: object) -> None:
        if not isinstance(value, Path):
            self.page.show_error("歌曲路径无效")
            return
        self.edit_path(value)

    def edit_path(self, path: Path) -> None:
        """加载并打开唯一的歌曲修改工作区。"""
        if self._edit_dialog is not None and self._edit_dialog.isVisible():
            self._edit_dialog.raise_()
            self._edit_dialog.activateWindow()
            return
        self._edit_generation += 1
        generation = self._edit_generation
        self.page.status_label.setText("正在后台加载歌曲修改工作区……")
        threading.Thread(
            target=self._prepare_edit_in_background,
            args=(generation, path),
            name="library-song-edit-load",
            daemon=True,
        ).start()

    def _prepare_edit_in_background(self, generation: int, path: Path) -> None:
        try:
            package = self.service.load(path)
            track_paths = {
                track: resolve_package_path(package.root, package.config.audio.tracks[track].file)
                for track in package.config.audio.tracks
            }
            pcm = self._pcm_cache.load(track_paths)
            self._messages.put(("edit_loaded", (generation, (package, pcm))))
        except Exception as exc:
            self._messages.put(("edit_failed", (generation, str(exc))))

    def _open_song_editor(self, package: SongPackage, pcm: PcmSongData) -> None:
        self._close_edit_engine(0)
        self._editing_package = package
        self._edit_engine = StemMixerEngine(parent=self)
        default_mutes = {track: False for track in TrackKind}
        self._edit_engine.load_pcm(
            pcm,
            default_muted=default_mutes,
            gain_db={track: 0.0 for track in TrackKind},
            mute_fade_ms=12,
            master_volume=self.settings_service.load_mixer_settings().master_volume,
        )
        self._edit_engine.error_raised.connect(self.page.show_error)
        self._edit_dialog = SongEditDialog(
            package=package,
            player=self._edit_engine,
            chord_mode=self.settings_service.load_musician_display_settings().chord_mode,
            parent=self.page.window(),
        )
        self._edit_dialog.saved.connect(self._save_edited_song)
        self._edit_dialog.lyric_editor.music_reanalysis_requested.connect(
            self._reanalyze_edit_music
        )
        self._edit_dialog.chord_editor.reanalysis_requested.connect(self._reanalyze_chords)
        self._edit_dialog.lyric_timing_reanalysis_requested.connect(self._reanalyze_lyric_timing)
        self._edit_dialog.full_reanalysis_requested.connect(self._reanalyze_all)
        self._edit_dialog.finished.connect(self._close_edit_engine)
        self._edit_dialog.show()
        self.page.status_label.setText("歌曲修改窗口已打开")

    def _reanalyze_edit_music(self) -> None:
        package = self._editing_package
        if package is None:
            if self._edit_dialog is not None:
                self._edit_dialog.lyric_editor.show_music_analysis_error("当前歌曲数据无效")
            return
        generation = self._edit_generation
        threading.Thread(
            target=self._reanalyze_music_in_background,
            args=(generation, package),
            name="library-music-reanalysis",
            daemon=True,
        ).start()

    def _reanalyze_all(self) -> None:
        package, dialog = self._editing_package, self._edit_dialog
        if package is None or dialog is None:
            return
        generation = self._edit_generation
        reference = dialog.lyric_editor.document
        threading.Thread(
            target=self._reanalyze_all_in_background,
            args=(generation, package, reference),
            name="library-full-reanalysis", daemon=True,
        ).start()

    def _reanalyze_all_in_background(
        self, generation: int, package: SongPackage, reference: LyricsDocument,
    ) -> None:
        try:
            result = self._analyze_package_full(package, reference)
            self._messages.put(("full_analyzed", (generation, result)))
        except Exception as exc:
            self._messages.put(("full_analysis_failed", (generation, str(exc))))

    @staticmethod
    def _analyze_package_full(
        package: SongPackage, reference: LyricsDocument,
    ) -> SongAnalysis:
        stems = [resolve_package_path(package.root, package.config.audio.tracks[track].file)
                 for track in TrackKind]
        vocals = resolve_package_path(
            package.root, package.config.audio.tracks[TrackKind.VOCALS].file,
        )
        cancellation = CancellationToken()
        language = timing_language(package.lyrics.language, reference)
        reference = reference.model_copy(update={"language": language})
        with tempfile.TemporaryDirectory(prefix="dx-band-full-analysis-") as workdir:
            root = Path(workdir)
            mixed = root / "full-mix.wav"
            command = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
            for stem in stems:
                command.extend(("-i", str(stem)))
            command.extend((
                "-filter_complex", "amix=inputs=6:duration=longest:normalize=0,volume=0.5",
                "-ac", "1", "-ar", "44100", str(mixed),
            ))
            subprocess.run(command, check=True, capture_output=True, timeout=300)
            score = SheetSage2Runner()
            score_output = score.run(mixed, root / "sheetsage2", cancellation)
            solo_output = score.run(vocals, root / "sheetsage2_vocals_only", cancellation)
            beat_output = BeatThisRunner().run(mixed, root / "beat_this", cancellation)
            asr_output = None
            if language in {"zh", "yue"}:
                asr_output = FunAsrRunner().run(
                    vocals, root / "fun_asr", cancellation, language=language,
                )
            else:
                reference = LrcCtcAligner(language=language).align_document(reference, vocals)
            return assemble_song_analysis(
                score_output, solo_output, beat_output / "beat_this.json",
                reference, package.config.duration_ms, asr_output=asr_output,
            )

    def _reanalyze_music_in_background(
        self,
        generation: int,
        package: SongPackage,
    ) -> None:
        try:
            result = self._analyze_package_score(package)
            self._messages.put(("music_analyzed", (generation, result)))
        except Exception as exc:
            self._messages.put(("music_analysis_failed", (generation, str(exc))))

    def _save_edited_song(self, value: object) -> None:
        package = self._editing_package
        if package is None or not isinstance(value, SongEditResult):
            self.page.show_error("歌曲修改数据无效")
            return
        try:
            updated_package = self.service.update_song(
                package,
                value.lyrics.document,
                value.lyrics.title,
                value.lyrics.artist,
                value.lyrics.original_key,
                value.lyrics.bpm,
                value.lyrics.beat_times_ms,
                value.lyrics.downbeat_times_ms,
                value.lyrics.beats_per_bar,
                chords=value.chords,
                melody=value.melody,
            )
        except Exception as exc:
            self.page.show_error(f"保存歌曲修改失败：{exc}")
            if self._edit_dialog is not None:
                self._edit_dialog.show_status(f"保存失败：{exc}")
            return
        self._editing_package = updated_package
        self.song_lyrics_updated.emit(updated_package)
        if value.chords is not None:
            self.song_chords_updated.emit(updated_package)
        self.refresh()
        self.page.status_label.setText("歌曲信息、歌词与和弦修改已写入歌曲包")
        if self._edit_dialog is not None:
            self._edit_dialog.accept()

    def _close_edit_engine(self, _result: int) -> None:
        self._edit_generation += 1
        if self._edit_engine is not None:
            self._edit_engine.close()
            self._edit_engine.deleteLater()
            self._edit_engine = None
        self._edit_dialog = None
        self._editing_package = None

    def _reanalyze_chords(self) -> None:
        package = self._editing_package
        if package is None:
            if self._edit_dialog is not None:
                self._edit_dialog.chord_editor.show_reanalysis_error("当前歌曲数据无效")
            return
        generation = self._edit_generation
        threading.Thread(
            target=self._reanalyze_chords_in_background,
            args=(generation, package),
            name="library-chord-reanalysis",
            daemon=True,
        ).start()

    def _reanalyze_chords_in_background(self, generation: int, package: SongPackage) -> None:
        try:
            timeline = self._recognize_chords(package)
            self._messages.put(("chords_reanalyzed", (generation, timeline)))
        except Exception as exc:
            self._messages.put(("chord_reanalysis_failed", (generation, str(exc))))

    @staticmethod
    def _recognize_chords(package: SongPackage) -> ChordTimeline:
        """Shared chord recognition used by reanalysis and library backfill."""
        stems = [
            resolve_package_path(package.root, track.file)
            for track in package.config.audio.tracks.values()
        ]
        with tempfile.TemporaryDirectory(prefix="dx-band-chords-") as workdir:
            output = SheetSage2Runner().run_stems(
                stems, Path(workdir), CancellationToken()
            )
            return read_sheetsage2_chords(output, package.config.duration_ms)

    @staticmethod
    def _analyze_package_score(package: SongPackage) -> SheetSage2Analysis:
        stems = [
            resolve_package_path(package.root, track.file)
            for track in package.config.audio.tracks.values()
        ]
        with tempfile.TemporaryDirectory(prefix="dx-band-score-") as workdir:
            output = SheetSage2Runner().run_stems(
                stems, Path(workdir), CancellationToken()
            )
            return read_sheetsage2_package(output, package.config.duration_ms)

    def _reanalyze_lyric_timing(self) -> None:
        package = self._editing_package
        dialog = self._edit_dialog
        if package is None or dialog is None:
            if self._edit_dialog is not None:
                self._edit_dialog.show_lyric_timing_analysis_error("当前歌曲数据无效")
            return
        generation = self._edit_generation
        reference = dialog.lyric_editor.document
        vocals_path = resolve_package_path(
            package.root,
            package.config.audio.tracks[TrackKind.VOCALS].file,
        )
        threading.Thread(
            target=self._reanalyze_lyric_timing_in_background,
            args=(
                generation,
                vocals_path,
                reference,
                self._transcription_language(
                    package.lyrics.language,
                    "".join(line.text for line in package.lyrics.lines),
                ),
            ),
            name="library-lyric-timing-reanalysis",
            daemon=True,
        ).start()

    @staticmethod
    def _transcription_language(language: str, lyrics_text: str = "") -> str:
        code = language.strip().lower().replace("_", "-").split("-", 1)[0]
        if code in {"", "und"}:
            chinese_characters = sum("\u3400" <= char <= "\u9fff" for char in lyrics_text)
            return "zh" if chinese_characters >= 4 else "auto"
        return code

    def _reanalyze_lyric_timing_in_background(
        self,
        generation: int,
        vocals_path: Path,
        reference: LyricsDocument,
        language: str,
    ) -> None:
        try:
            selected_language = timing_language(language, reference)
            aligned = LrcCtcAligner(language=selected_language).align_document(
                reference, vocals_path
            )
            self._messages.put(("lyric_timing_recognized", (generation, aligned)))
        except Exception as exc:
            self._messages.put(("lyric_timing_failed", (generation, str(exc))))

    def _delete(self, value: object) -> None:
        if not isinstance(value, Path):
            return
        song_name = value.name
        selected_item = self.page.song_list.item(self.page.song_list.currentRow(), 0)
        if selected_item is not None:
            selected_path = Path(str(selected_item.data(Qt.ItemDataRole.UserRole)))
            if selected_path == value:
                song_name = selected_item.text()
        dialog = DestructiveConfirmationDialog(
            title="删除歌曲",
            message=f"确定永久删除“{song_name}”吗？",
            detail="此操作无法撤销。",
            confirm_text="永久删除",
            parent=self.page,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.delete_song(value.name, self.playing_song_id)
        except Exception as exc:
            self.page.show_error(str(exc))
            return
        self.refresh()
        self.page.status_label.setText(f"已永久删除歌曲：{song_name}")
