# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from dxband.constants import CORE_PACKAGE_FILES, TRACK_FILENAMES
from dxband.creation.stem_validator import StemValidationError, StemValidator
from dxband.models.chord import ChordTimeline
from dxband.models.lyric import LyricsDocument
from dxband.models.melody import MelodyDocument
from dxband.models.song import SongConfig
from dxband.services.hash_service import sha256_file
from dxband.services.paths import UnsafeRelativePathError, resolve_package_path

ModelT = TypeVar("ModelT", bound=BaseModel)


class PackageValidationError(ValueError):
    """可向用户展示的一组歌曲包校验错误。"""

    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("invalid song package:\n- " + "\n- ".join(errors))


@dataclass(frozen=True, slots=True)
class SongPackage:
    root: Path
    config: SongConfig
    lyrics: LyricsDocument
    warnings: tuple[str, ...] = ()
    chords: ChordTimeline | None = None
    melody: MelodyDocument | None = None


class SongPackageValidator:
    """校验歌曲包达到可播放状态前所需的全部持久化数据。"""

    lyric_end_tolerance_ms = 2_000

    def validate(
        self,
        package_root: Path,
        verify_media: bool = True,
        verify_hashes: bool = True,
        require_matching_root_name: bool = True,
    ) -> SongPackage:
        root = package_root.resolve()
        errors: list[str] = []
        warnings: list[str] = []
        if not root.is_dir():
            raise PackageValidationError([f"package directory does not exist: {root}"])

        missing = sorted(name for name in CORE_PACKAGE_FILES if not (root / name).is_file())
        if missing:
            errors.append(f"missing core files: {', '.join(missing)}")
        if errors:
            raise PackageValidationError(errors)

        config = self._load_model(root / "song.json", SongConfig, errors)
        lyrics = self._load_model(root / "lyrics.json", LyricsDocument, errors)
        if config is None or lyrics is None:
            raise PackageValidationError(errors)

        if require_matching_root_name and root.name != config.song_id:
            errors.append("package directory name must match song_id")
        if not config.lyrics.verified:
            errors.append("formal song packages require verified lyrics")
        if config.title != lyrics.title:
            errors.append("song and lyrics titles must match")
        if config.language != lyrics.language:
            errors.append("song and lyrics languages must match")

        for track_kind, track in config.audio.tracks.items():
            expected_filename = TRACK_FILENAMES[track_kind]
            if track.file != expected_filename:
                errors.append(f"{track_kind.value} path must be {expected_filename}")
                continue
            try:
                track_entry_path = root / track.file
                track_path = resolve_package_path(root, track.file)
            except UnsafeRelativePathError as exc:
                errors.append(str(exc))
                continue
            if track_entry_path.is_symlink():
                errors.append(f"track must not be a symbolic link: {track.file}")
            elif not track_path.is_file():
                errors.append(f"missing track file: {track.file}")
            elif verify_hashes and track_path.is_file() and sha256_file(track_path) != track.sha256:
                errors.append(f"sha256 mismatch: {track.file}")

        try:
            lyrics_path = resolve_package_path(root, config.lyrics.file)
            if lyrics_path != root / "lyrics.json":
                errors.append("lyrics file must be lyrics.json")
        except UnsafeRelativePathError as exc:
            errors.append(str(exc))

        if verify_media:
            try:
                stem_result = StemValidator().validate(root, set(config.audio.tracks))
                if stem_result.sample_rate_hz != config.audio.sample_rate_hz:
                    errors.append("song.json 的采样率与实际轨道不一致")
                if stem_result.canonical_frames != config.audio.canonical_frames:
                    errors.append("song.json 的标准帧数与实际轨道不一致")
                for track_kind, actual in stem_result.tracks.items():
                    configured = config.audio.tracks[track_kind]
                    if actual.sha256 != configured.sha256:
                        errors.append(f"轨道复验哈希不一致：{configured.file}")
            except StemValidationError as exc:
                errors.append(f"音轨媒体校验失败：{exc}")

        if lyrics.lines:
            final_end_ms = lyrics.lines[-1].end_ms
            if final_end_ms > config.duration_ms + self.lyric_end_tolerance_ms:
                errors.append("last lyric line ends more than 2000ms after the song")
            elif final_end_ms > config.duration_ms:
                warnings.append("last lyric line ends slightly after the song")

        if errors:
            raise PackageValidationError(errors)
        chords = None
        chords_path = root / "chords.json"
        if chords_path.is_file() and not chords_path.is_symlink():
            try:
                chords = ChordTimeline.model_validate_json(chords_path.read_bytes(), strict=True)
            except (OSError, ValidationError, ValueError) as exc:
                warnings.append(f"chords.json 无效，可在歌曲编辑中重新分析：{exc}")
        melody = None
        melody_path = root / "melody.json"
        if melody_path.is_file() and not melody_path.is_symlink():
            try:
                melody = MelodyDocument.model_validate_json(melody_path.read_bytes(), strict=True)
                if (
                    (melody.coverage_end_ms or 0) > config.duration_ms
                    or any(
                        note.end_ms > config.duration_ms
                        or (note.display_ms or 0) > config.duration_ms
                        for note in melody.notes
                    )
                    or any(gap.end_ms > config.duration_ms for gap in melody.gaps)
                    or any(chord.at_ms > config.duration_ms for chord in melody.chords)
                    or any(change.at_ms >= config.duration_ms for change in melody.key_changes)
                    or any(bar.end_ms > config.duration_ms for bar in melody.bars)
                ):
                    raise ValueError("简谱事件超出歌曲时长")
            except (OSError, ValidationError, ValueError) as exc:
                melody = None
                warnings.append(f"melody.json 无效，乐手屏将不显示简谱：{exc}")
        return SongPackage(
            root=root,
            config=config,
            lyrics=lyrics,
            warnings=tuple(warnings),
            chords=chords,
            melody=melody,
        )

    @staticmethod
    def _load_model(
        path: Path,
        model_type: type[ModelT],
        errors: list[str],
    ) -> ModelT | None:
        try:
            return model_type.model_validate_json(path.read_bytes(), strict=True)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            errors.append(f"invalid {path.name}: {exc}")
            return None
