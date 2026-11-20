# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile

import pytest
from pytest import MonkeyPatch

from dxband.creation.package_validator import SongPackageValidator
from dxband.models.chord import ChordSegment, ChordTimeline
from dxband.models.melody import MelodyBar, MelodyDocument, MelodyNote
from dxband.models.song import SongConfig
from dxband.services.library_service import (
    DuplicateSongIdError,
    LibraryService,
)


def test_update_song_saves_title_artist_and_matching_lyrics(
    package_factory: Callable[[], Path],
) -> None:
    package_root = package_factory()
    package = SongPackageValidator().validate(package_root, verify_media=False)
    service = LibraryService(package_root.parent)

    updated = service.update_song(
        package,
        package.lyrics,
        "  新歌名  ",
        "  新歌手  ",
        "  F#m  ",
        127,
        beat_times_ms=(0, 472, 945, 1_417),
    )

    assert updated.config.title == "新歌名"
    assert updated.config.artist == "新歌手"
    assert updated.config.musical is not None
    assert updated.config.musical.original_key == "F#m"
    assert updated.config.musical.bpm == 127
    assert updated.lyrics.title == "新歌名"
    assert service.scan("新歌手").songs[0].config.title == "新歌名"


def test_update_song_requires_reanalysis_when_bpm_changes(
    package_factory: Callable[[], Path],
) -> None:
    package_root = package_factory()
    package = SongPackageValidator().validate(package_root, verify_media=False)
    config_payload = package.config.model_dump(mode="python")
    config_payload["musical"] = {
        "original_key": "D",
        "bpm": 76,
        "beat_times_ms": [800, 1_589, 2_378, 3_167],
    }
    package = replace(
        package,
        config=SongConfig.model_validate(config_payload, strict=True),
    )
    service = LibraryService(package_root.parent)

    with pytest.raises(ValueError, match="不能单独修改"):
        service.update_song(
            package,
            package.lyrics,
            package.config.title,
            package.config.artist,
            "E",
            78,
        )

    analyzed_beat_times = (800, 1_569, 2_338, 3_108)
    updated = service.update_song(
        package,
        package.lyrics,
        package.config.title,
        package.config.artist,
        "E",
        78,
        analyzed_beat_times,
    )

    assert updated.config.musical is not None
    assert updated.config.musical.beat_times_ms == list(analyzed_beat_times)


def test_update_song_preserves_existing_beat_grid(
    package_factory: Callable[[], Path],
) -> None:
    package_root = package_factory()
    package = SongPackageValidator().validate(package_root, verify_media=False)
    service = LibraryService(package_root.parent)

    updated = service.update_song(
        package,
        package.lyrics,
        package.config.title,
        package.config.artist,
        "C",
        120,
    )

    assert updated.config.musical.beat_times_ms == [0, 500, 1000, 1500]


def test_update_chords_saves_one_canonical_timeline(
    package_factory: Callable[[], Path],
) -> None:
    package_root = package_factory()
    package = SongPackageValidator().validate(package_root, verify_media=False)
    service = LibraryService(package_root.parent)
    timeline = ChordTimeline(
        segments=[ChordSegment(start_ms=1000, end_ms=2000, chord="G:maj")]
    )

    updated = service.update_chords(package, timeline)

    assert updated.chords == timeline
    assert (package_root / "chords.json").is_file()
    assert not (package_root / "chords-degree.json").exists()
    assert not (package_root / "chords-chord.json").exists()
    assert not (package_root / "chords-chord-c.json").exists()


def test_update_song_saves_lyrics_and_chords_together(
    package_factory: Callable[[], Path],
) -> None:
    package_root = package_factory()
    package = SongPackageValidator().validate(package_root, verify_media=False)
    service = LibraryService(package_root.parent)
    chords = ChordTimeline(
        segments=[ChordSegment(start_ms=1_000, end_ms=2_000, chord="G:maj")]
    )

    updated = service.update_song(
        package,
        package.lyrics,
        "新歌名",
        "新歌手",
        "C",
        120,
        chords=chords,
    )

    assert updated.config.title == updated.lyrics.title == "新歌名"
    assert updated.chords == chords


def test_update_song_persists_reanalyzed_melody(
    package_factory: Callable[[], Path],
) -> None:
    package_root = package_factory()
    package = SongPackageValidator().validate(package_root, verify_media=False)
    service = LibraryService(package_root.parent)
    melody = MelodyDocument(
        tonic_midi=60, coverage_end_ms=2_000,
        notes=[MelodyNote(start_ms=500, end_ms=750, midi=64, source="vocals")],
        bars=[MelodyBar(start_ms=0, end_ms=2_000,
                        beat_times_ms=[0, 500, 1_000, 1_500])],
    )

    service.update_song(
        package, package.lyrics, package.config.title, package.config.artist,
        package.config.musical.original_key, package.config.musical.bpm,
        melody=melody,
    )

    assert MelodyDocument.model_validate_json((package_root / "melody.json").read_bytes()) == melody


def test_delete_song_permanently_removes_only_a_library_song(
    package_factory: Callable[[], Path],
) -> None:
    package_root = package_factory()
    service = LibraryService(package_root.parent)

    with pytest.raises(ValueError, match="播放中的歌曲不能删除"):
        service.delete_song(package_root.name, package_root.name)
    assert package_root.is_dir()

    service.delete_song(package_root.name)

    assert not package_root.exists()
    assert not (service.root / ".trash").exists()


def test_import_song_folder_validates_copies_and_removes_source(
    package_factory: Callable[[], Path],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    package_root = package_factory()
    source = tmp_path / "外部歌曲包"
    package_root.rename(source)
    library_root = tmp_path / "导入歌曲库"
    service = LibraryService(library_root)
    real_validate = service.validator.validate

    def validate_without_media(path: Path, **options: object):
        options["verify_media"] = False
        return real_validate(path, **options)

    monkeypatch.setattr(service.validator, "validate", validate_without_media)

    result = service.import_song_folder(source)

    destination = library_root / "20260930-193000-a1b2c3d4"
    assert result.source_removed
    assert result.warning is None
    assert result.package.root == destination
    assert destination.is_dir()
    assert not source.exists()
    assert service.scan().songs[0].config.title == "测试歌曲"


def test_import_song_folder_rejects_duplicate_without_removing_source(
    package_factory: Callable[[], Path],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    package_root = package_factory()
    source = tmp_path / "待导入歌曲包"
    package_root.rename(source)
    library_root = tmp_path / "已有歌曲库"
    library_root.mkdir()
    duplicate = library_root / "20260930-193000-a1b2c3d4"
    duplicate.mkdir()
    service = LibraryService(library_root)
    real_validate = service.validator.validate

    def validate_without_media(path: Path, **options: object):
        options["verify_media"] = False
        return real_validate(path, **options)

    monkeypatch.setattr(service.validator, "validate", validate_without_media)

    with pytest.raises(DuplicateSongIdError, match="歌曲库已存在歌曲 ID") as error:
        service.import_song_folder(source)

    assert error.value.song_id == "20260930-193000-a1b2c3d4"
    assert source.is_dir()


def test_import_song_folder_can_create_a_new_id_for_duplicate(
    package_factory: Callable[[], Path],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    package_root = package_factory()
    source = tmp_path / "重复歌曲包"
    package_root.rename(source)
    library_root = tmp_path / "歌曲库"
    library_root.mkdir()
    original_destination = library_root / "20260930-193000-a1b2c3d4"
    original_destination.mkdir()
    service = LibraryService(library_root)
    real_validate = service.validator.validate

    def validate_without_media(path: Path, **options: object):
        options["verify_media"] = False
        return real_validate(path, **options)

    monkeypatch.setattr(service.validator, "validate", validate_without_media)
    monkeypatch.setattr(
        service,
        "_new_song_id",
        lambda: "20261001-120000-1234abcd",
    )

    result = service.import_song_folder(source, create_new_id_on_conflict=True)

    assert result.original_song_id == "20260930-193000-a1b2c3d4"
    assert result.package.config.song_id == "20261001-120000-1234abcd"
    assert result.package.root == library_root / "20261001-120000-1234abcd"
    assert original_destination.is_dir()
    assert not source.exists()


def test_song_archive_round_trip_keeps_zip_and_optional_files(
    package_factory: Callable[[], Path],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    package_root = package_factory()
    (package_root / "rhythm_comparison.json").write_text('{"reviewed": true}', encoding="utf-8")
    exporter = LibraryService(package_root.parent)
    destination = tmp_path / "分享歌曲包.zip"
    real_validate = exporter.validator.validate

    def validate_without_media(path: Path, **options: object):
        options["verify_media"] = False
        return real_validate(path, **options)

    monkeypatch.setattr(exporter.validator, "validate", validate_without_media)
    assert exporter.export_song_archive(package_root, destination) == destination
    with ZipFile(destination) as archive:
        assert f"{package_root.name}/song.json" in archive.namelist()
        assert archive.read(f"{package_root.name}/rhythm_comparison.json") == b'{"reviewed": true}'

    importer = LibraryService(tmp_path / "new_library")
    monkeypatch.setattr(importer.validator, "validate", validate_without_media)
    result = importer.import_song_archive(destination)

    assert destination.is_file()
    assert not result.source_removed
    assert result.package.config.song_id == package_root.name
    assert (result.package.root / "rhythm_comparison.json").read_bytes() == (
        package_root / "rhythm_comparison.json"
    ).read_bytes()
    assert (result.package.root / "vocals.mp3").read_bytes() == (
        package_root / "vocals.mp3"
    ).read_bytes()


def test_import_song_archive_rejects_unsafe_paths_without_writing_library(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("song/song.json", "{}")
        archive.writestr("song/../../escape.txt", "bad")
    library = LibraryService(tmp_path / "library")

    with pytest.raises(ValueError, match="不安全"):
        library.import_song_archive(archive_path)

    assert list(library.root.iterdir()) == []
    assert not (tmp_path / "escape.txt").exists()


def test_import_song_archive_can_assign_new_id_on_conflict(
    package_factory: Callable[[], Path],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    package_root = package_factory()
    archive_path = tmp_path / "duplicate.zip"
    with ZipFile(archive_path, "w") as archive:
        for path in package_root.iterdir():
            archive.write(path, f"{package_root.name}/{path.name}")
    library = LibraryService(tmp_path / "library")
    (library.root / package_root.name).mkdir()
    real_validate = library.validator.validate

    def validate_without_media(path: Path, **options: object):
        options["verify_media"] = False
        return real_validate(path, **options)

    monkeypatch.setattr(library.validator, "validate", validate_without_media)
    monkeypatch.setattr(library, "_new_song_id", lambda: "20261001-120000-1234abcd")

    with pytest.raises(DuplicateSongIdError):
        library.import_song_archive(archive_path)
    result = library.import_song_archive(archive_path, create_new_id_on_conflict=True)

    assert result.original_song_id == package_root.name
    assert result.package.config.song_id == "20261001-120000-1234abcd"
    assert archive_path.is_file()


def test_export_song_archive_rejects_output_inside_package(
    package_factory: Callable[[], Path],
    monkeypatch: MonkeyPatch,
) -> None:
    package_root = package_factory()
    library = LibraryService(package_root.parent)
    real_validate = library.validator.validate

    def validate_without_media(path: Path, **options: object):
        options["verify_media"] = False
        return real_validate(path, **options)

    monkeypatch.setattr(library.validator, "validate", validate_without_media)

    with pytest.raises(ValueError, match="歌曲包目录内"):
        library.export_song_archive(package_root, package_root / "self.zip")

    assert not (package_root / "self.zip").exists()
