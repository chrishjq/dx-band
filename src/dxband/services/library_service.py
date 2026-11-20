# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from dxband.creation.package_validator import (
    PackageValidationError,
    SongPackage,
    SongPackageValidator,
)
from dxband.models.chord import ChordTimeline
from dxband.models.lyric import LyricsDocument
from dxband.models.melody import MelodyDocument
from dxband.models.song import MusicalConfig, SongConfig
from dxband.services.atomic_file_service import atomic_write_json


@dataclass(frozen=True, slots=True)
class BrokenPackage:
    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class LibraryScanResult:
    songs: tuple[SongPackage, ...]
    broken: tuple[BrokenPackage, ...]


@dataclass(frozen=True, slots=True)
class SongImportResult:
    package: SongPackage
    source_removed: bool
    warning: str | None = None
    original_song_id: str | None = None


class DuplicateSongIdError(ValueError):
    def __init__(self, song_id: str, title: str) -> None:
        self.song_id = song_id
        self.title = title
        super().__init__(f"歌曲库已存在歌曲 ID：{song_id}")


class LibraryService:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.validator = SongPackageValidator()

    def scan(self, query: str = "") -> LibraryScanResult:
        songs: list[SongPackage] = []
        broken: list[BrokenPackage] = []
        normalized_query = query.casefold().strip()
        for path in sorted(self.root.iterdir()):
            if not path.is_dir() or path.name.startswith("."):
                continue
            try:
                package = self.validator.validate(path, verify_media=False, verify_hashes=False)
            except PackageValidationError as exc:
                broken.append(BrokenPackage(path=path, message=str(exc)))
                continue
            searchable = f"{package.config.title} {package.config.artist}".casefold()
            if normalized_query and normalized_query not in searchable:
                continue
            songs.append(package)
        songs.sort(key=lambda item: (item.config.title.casefold(), item.config.artist.casefold()))
        return LibraryScanResult(tuple(songs), tuple(broken))

    def load(self, path: Path) -> SongPackage:
        resolved = path.resolve()
        if resolved.parent != self.root:
            raise ValueError("歌曲目录不在当前歌曲库中")
        return self.validator.validate(resolved)

    def set_root(self, root: Path) -> None:
        """切换歌曲库目录。"""
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def update_song(
        self,
        package: SongPackage,
        document: LyricsDocument,
        title: str,
        artist: str,
        original_key: str,
        bpm: int,
        beat_times_ms: tuple[int, ...] | list[int] | None = None,
        downbeat_times_ms: tuple[int, ...] | list[int] | None = None,
        beats_per_bar: int | None = None,
        chords: ChordTimeline | None = None,
        melody: MelodyDocument | None = None,
    ) -> SongPackage:
        """Save song data and optional chords, restoring all files on failure."""
        if package.root.resolve().parent != self.root:
            raise ValueError("歌曲目录不在当前歌曲库中")
        normalized_title = title.strip()
        normalized_artist = artist.strip()
        if not normalized_title:
            raise ValueError("歌名不能为空")
        if document.language != package.config.language:
            raise ValueError("歌词语言与歌曲不一致")
        if any(line.end_ms > package.config.duration_ms for line in document.lines):
            raise ValueError("存在超出歌曲时长的歌词")
        normalized_key = original_key.strip()
        if not normalized_key or bpm <= 0:
            raise ValueError("原Key 和 BPM 不能为空")
        existing_musical = package.config.musical
        if bpm != existing_musical.bpm and beat_times_ms is None:
            raise ValueError("BPM 不能单独修改，请重新分析节奏")
        musical = MusicalConfig(
            original_key=normalized_key,
            bpm=bpm,
            beat_times_ms=(
                list(beat_times_ms)
                if beat_times_ms is not None
                else list(existing_musical.beat_times_ms)
            ),
            downbeat_times_ms=(
                list(downbeat_times_ms)
                if downbeat_times_ms is not None
                else list(existing_musical.downbeat_times_ms)
            ),
            beats_per_bar=(
                beats_per_bar
                if beats_per_bar is not None
                else existing_musical.beats_per_bar
            ),
        )

        config_payload = package.config.model_dump(mode="python")
        config_payload.update(
            title=normalized_title,
            artist=normalized_artist,
            musical=musical.model_dump(mode="python"),
        )
        updated_config = SongConfig.model_validate(config_payload, strict=True)
        document_payload = document.model_dump(mode="python")
        document_payload["title"] = normalized_title
        updated_document = LyricsDocument.model_validate(document_payload, strict=True)
        if chords is not None and any(
            segment.end_ms > package.config.duration_ms for segment in chords.segments
        ):
            raise ValueError("存在超出歌曲时长的和弦")
        if melody is not None and (
            any(note.end_ms > package.config.duration_ms for note in melody.notes)
            or any(bar.end_ms > package.config.duration_ms for bar in melody.bars)
        ):
            raise ValueError("存在超出歌曲时长的简谱音符或小节")

        song_path = package.root / "song.json"
        lyrics_path = package.root / "lyrics.json"
        chords_path = package.root / "chords.json"
        melody_path = package.root / "melody.json"
        previous_chords = (
            chords_path.read_bytes()
            if chords is not None and chords_path.is_file()
            else None
        )
        previous_melody = (
            melody_path.read_bytes()
            if melody is not None and melody_path.is_file()
            else None
        )
        try:
            atomic_write_json(song_path, updated_config)
            atomic_write_json(lyrics_path, updated_document)
            if chords is not None:
                atomic_write_json(chords_path, chords)
            if melody is not None:
                atomic_write_json(melody_path, melody)
            return self.validator.validate(
                package.root,
                verify_media=False,
                verify_hashes=False,
            )
        except Exception:
            atomic_write_json(song_path, package.config)
            atomic_write_json(lyrics_path, package.lyrics)
            if chords is not None:
                if previous_chords is None:
                    chords_path.unlink(missing_ok=True)
                else:
                    chords_path.write_bytes(previous_chords)
            if melody is not None:
                if previous_melody is None:
                    melody_path.unlink(missing_ok=True)
                else:
                    melody_path.write_bytes(previous_melody)
            raise

    def update_chords(self, package: SongPackage, timeline: ChordTimeline) -> SongPackage:
        """将唯一和弦表写入歌曲包。"""
        if package.root.resolve().parent != self.root:
            raise ValueError("歌曲目录不在当前歌曲库中")
        if any(segment.end_ms > package.config.duration_ms for segment in timeline.segments):
            raise ValueError("存在超出歌曲时长的和弦")
        chords_path = package.root / "chords.json"
        previous = chords_path.read_bytes() if chords_path.is_file() else None
        try:
            atomic_write_json(chords_path, timeline)
            return self.validator.validate(
                package.root,
                verify_media=False,
                verify_hashes=False,
            )
        except Exception:
            if previous is None:
                chords_path.unlink(missing_ok=True)
            else:
                chords_path.write_bytes(previous)
            raise

    def import_song_folder(
        self,
        source: Path,
        create_new_id_on_conflict: bool = False,
    ) -> SongImportResult:
        """完整校验外部歌曲包，安全转移到当前歌曲库。"""
        selected_source = source.expanduser()
        if selected_source.is_symlink():
            raise ValueError("不能导入符号链接文件夹")
        resolved_source = selected_source.resolve()
        if not resolved_source.is_dir():
            raise ValueError("选择的歌曲包文件夹不存在")
        if (
            resolved_source == self.root
            or self.root in resolved_source.parents
            or resolved_source in self.root.parents
        ):
            raise ValueError("所选文件夹已经位于当前歌曲库中")

        source_package = self.validator.validate(
            resolved_source,
            verify_media=True,
            verify_hashes=True,
            require_matching_root_name=False,
        )
        original_song_id = source_package.config.song_id
        destination = self.root / original_song_id
        if destination.exists():
            if not create_new_id_on_conflict:
                raise DuplicateSongIdError(original_song_id, source_package.config.title)
            new_song_id = self._new_song_id()
            while (self.root / new_song_id).exists():
                new_song_id = self._new_song_id()
            config_payload = source_package.config.model_dump(mode="python")
            config_payload["song_id"] = new_song_id
            source_package = SongPackage(
                root=source_package.root,
                config=SongConfig.model_validate(config_payload, strict=True),
                lyrics=source_package.lyrics,
                warnings=source_package.warnings,
                chords=source_package.chords,
                melody=source_package.melody,
            )
            destination = self.root / new_song_id

        staging_root = self.root / f".importing-{uuid4().hex}"
        staging_package = staging_root / source_package.config.song_id
        try:
            staging_root.mkdir()
            shutil.copytree(resolved_source, staging_package)
            if source_package.config.song_id != original_song_id:
                atomic_write_json(staging_package / "song.json", source_package.config)
            copied_package = self.validator.validate(
                staging_package,
                verify_media=False,
                verify_hashes=True,
            )
            staging_package.rename(destination)
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

        imported_package = SongPackage(
            root=destination,
            config=copied_package.config,
            lyrics=copied_package.lyrics,
            warnings=copied_package.warnings,
            chords=copied_package.chords,
            melody=copied_package.melody,
        )
        try:
            shutil.rmtree(resolved_source)
        except OSError as exc:
            return SongImportResult(
                package=imported_package,
                source_removed=False,
                warning=f"歌曲已导入，但原文件夹未能移除：{exc}",
                original_song_id=(
                    original_song_id
                    if imported_package.config.song_id != original_song_id
                    else None
                ),
            )
        return SongImportResult(
            package=imported_package,
            source_removed=True,
            original_song_id=(
                original_song_id if imported_package.config.song_id != original_song_id else None
            ),
        )

    def import_song_archive(
        self,
        archive_path: Path,
        create_new_id_on_conflict: bool = False,
    ) -> SongImportResult:
        """从 ZIP 导入完整歌曲目录，保留原始 ZIP。"""
        source = archive_path.expanduser().resolve()
        if source.suffix.lower() != ".zip" or not source.is_file():
            raise ValueError("请选择有效的 .zip 歌曲包文件")
        try:
            with zipfile.ZipFile(source) as archive, tempfile.TemporaryDirectory() as temp:
                entries = archive.infolist()
                if not entries or len(entries) > 10_000:
                    raise ValueError("歌曲包 ZIP 为空或文件数量过多")
                roots: set[str] = set()
                seen: set[str] = set()
                total_size = 0
                for entry in entries:
                    name = entry.filename
                    parts = name.rstrip("/").split("/")
                    normalized_name = name.rstrip("/")
                    if (
                        not name
                        or name.startswith("/")
                        or "\\" in name
                        or any(part in ("", ".", "..") or ":" in part for part in parts)
                        or (len(parts) < 2 and not entry.is_dir())
                        or normalized_name in seen
                        or stat.S_ISLNK(entry.external_attr >> 16)
                    ):
                        raise ValueError("歌曲包 ZIP 含有不安全或重复的路径")
                    seen.add(normalized_name)
                    roots.add(parts[0])
                    total_size += entry.file_size
                    if total_size > 8 * 1024**3:
                        raise ValueError("歌曲包 ZIP 解压后超过 8 GB")
                if len(roots) != 1:
                    raise ValueError("歌曲包 ZIP 必须只包含一个歌曲目录")
                package_root = Path(temp) / next(iter(roots))
                for entry in entries:
                    target = Path(temp).joinpath(*entry.filename.rstrip("/").split("/"))
                    if entry.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(entry) as reader, target.open("xb") as writer:
                            shutil.copyfileobj(reader, writer)
                result = self.import_song_folder(
                    package_root,
                    create_new_id_on_conflict=create_new_id_on_conflict,
                )
        except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise ValueError(f"歌曲包 ZIP 已损坏：{exc}") from exc
        return SongImportResult(
            package=result.package,
            source_removed=False,
            warning=result.warning,
            original_song_id=result.original_song_id,
        )

    def export_song_archive(self, package_path: Path, destination: Path) -> Path:
        """完整校验后将歌曲目录原子导出为 ZIP。"""
        package = self.load(package_path)
        selected_target = destination.expanduser()
        if selected_target.is_symlink():
            raise ValueError("不能覆盖符号链接形式的导出文件")
        target = selected_target.parent.resolve() / selected_target.name
        if target.suffix.lower() != ".zip":
            raise ValueError("导出文件必须使用 .zip 扩展名")
        if package.root == target or package.root in target.parents:
            raise ValueError("不能将 ZIP 导出到歌曲包目录内")
        if not target.parent.is_dir():
            raise ValueError("导出目录不存在")
        files = sorted(package.root.rglob("*"))
        if any(path.is_symlink() for path in files):
            raise ValueError("歌曲包包含符号链接，无法安全导出")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{target.stem}-", suffix=".zip", dir=target.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
                for path in files:
                    if path.is_file():
                        relative_name = path.relative_to(package.root).as_posix()
                        entry_name = f"{package.root.name}/{relative_name}"
                        archive.write(path, entry_name)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target

    @staticmethod
    def _new_song_id() -> str:
        now = datetime.now().astimezone()
        return f"{now:%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"

    def delete_song(self, song_id: str, playing_song_id: str | None = None) -> None:
        """永久删除歌曲目录；仅允许删除当前歌曲库的直接子目录。"""
        if song_id == playing_song_id:
            raise ValueError("播放中的歌曲不能删除")
        source = (self.root / song_id).resolve()
        if source.parent != self.root or not source.is_dir():
            raise ValueError("歌曲目录不存在")
        shutil.rmtree(source)
