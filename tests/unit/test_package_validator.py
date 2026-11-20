# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from dxband.creation.package_validator import (
    PackageValidationError,
    SongPackageValidator,
)
from dxband.models.chord import ChordSegment, ChordTimeline
from dxband.services.atomic_file_service import atomic_write_json


def test_valid_package_is_accepted(package_factory: Callable[[], Path]) -> None:
    package_root = package_factory()

    package = SongPackageValidator().validate(package_root, verify_media=False)

    assert package.root == package_root.resolve()
    assert package.config.title == "测试歌曲"
    assert package.lyrics.lines[0].text == "第一句歌词"


def test_optional_chord_timeline_is_loaded(package_factory: Callable[[], Path]) -> None:
    root = package_factory()
    atomic_write_json(
        root / "chords.json",
        ChordTimeline(segments=[ChordSegment(start_ms=0, end_ms=1000, chord="C:maj")]),
    )
    package = SongPackageValidator().validate(root, verify_media=False)
    assert package.chords is not None
    assert package.chords.segments[0].chord == "C:maj"


def test_external_package_can_use_a_different_folder_name(
    package_factory: Callable[[], Path],
) -> None:
    package_root = package_factory()
    renamed_root = package_root.with_name("外部导入文件夹")
    package_root.rename(renamed_root)

    package = SongPackageValidator().validate(
        renamed_root,
        verify_media=False,
        require_matching_root_name=False,
    )

    assert package.config.song_id == "20260930-193000-a1b2c3d4"


def test_missing_track_is_rejected(package_factory: Callable[[], Path]) -> None:
    package_root = package_factory()
    (package_root / "bass.mp3").unlink()

    with pytest.raises(PackageValidationError, match=r"missing core files: bass\.mp3"):
        SongPackageValidator().validate(package_root, verify_media=False)


def test_missing_six_stem_track_is_rejected(package_factory: Callable[[], Path]) -> None:
    package_root = package_factory()
    (package_root / "guitar.mp3").unlink()

    with pytest.raises(PackageValidationError, match=r"missing track file: guitar\.mp3"):
        SongPackageValidator().validate(package_root, verify_media=False)


def test_hash_mismatch_is_rejected(package_factory: Callable[[], Path]) -> None:
    package_root = package_factory()
    (package_root / "vocals.mp3").write_bytes(b"tampered")

    with pytest.raises(PackageValidationError, match=r"sha256 mismatch: vocals\.mp3"):
        SongPackageValidator().validate(package_root, verify_media=False)


def test_invalid_lyric_timing_is_rejected(package_factory: Callable[[], Path]) -> None:
    package_root = package_factory()
    lyrics_path = package_root / "lyrics.json"
    lyrics = json.loads(lyrics_path.read_text(encoding="utf-8"))
    lyrics["lines"][0]["end_ms"] = 500
    lyrics_path.write_text(json.dumps(lyrics), encoding="utf-8")

    with pytest.raises(PackageValidationError, match=r"invalid lyrics\.json"):
        SongPackageValidator().validate(package_root, verify_media=False)


def test_symlink_path_escape_is_rejected(
    package_factory: Callable[[], Path], tmp_path: Path
) -> None:
    package_root = package_factory()
    outside = tmp_path / "outside.mp3"
    outside.write_bytes((package_root / "vocals.mp3").read_bytes())
    (package_root / "vocals.mp3").unlink()
    (package_root / "vocals.mp3").symlink_to(outside)

    with pytest.raises(PackageValidationError, match="path leaves package root"):
        SongPackageValidator().validate(package_root, verify_media=False)


def test_internal_track_symlink_is_rejected(package_factory: Callable[[], Path]) -> None:
    package_root = package_factory()
    target = package_root / "stored-vocals.bin"
    target.write_bytes((package_root / "vocals.mp3").read_bytes())
    (package_root / "vocals.mp3").unlink()
    (package_root / "vocals.mp3").symlink_to(target.name)

    with pytest.raises(PackageValidationError, match="track must not be a symbolic link"):
        SongPackageValidator().validate(package_root, verify_media=False)
