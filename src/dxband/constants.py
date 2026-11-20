# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from enum import StrEnum


class TrackKind(StrEnum):
    VOCALS = "vocals"
    DRUMS = "drums"
    BASS = "bass"
    GUITAR = "guitar"
    PIANO = "piano"
    OTHER = "other"


TRACK_FILENAMES: dict[TrackKind, str] = {
    TrackKind.VOCALS: "vocals.mp3",
    TrackKind.DRUMS: "drums.mp3",
    TrackKind.BASS: "bass.mp3",
    TrackKind.GUITAR: "guitar.mp3",
    TrackKind.PIANO: "piano.mp3",
    TrackKind.OTHER: "other.mp3",
}

LEGACY_TRACK_KINDS = frozenset({TrackKind.VOCALS, TrackKind.DRUMS, TrackKind.BASS, TrackKind.OTHER})
SIX_STEM_TRACK_KINDS = frozenset(TrackKind)

# The four legacy stems stay in the fixed core set so a malformed package is
# rejected before song.json is trusted. Schema-aware validation below also
# requires guitar.mp3 and piano.mp3 for new six-stem packages.
CORE_PACKAGE_FILES = frozenset(
    {
        *(TRACK_FILENAMES[track] for track in LEGACY_TRACK_KINDS),
        "lyrics.json",
        "song.json",
    }
)

MUSICIAN_FONT_SIZE_MIN = 18
