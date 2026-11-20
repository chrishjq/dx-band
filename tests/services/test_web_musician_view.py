# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
from dataclasses import replace
from pathlib import Path

from dxband.creation.package_validator import SongPackageValidator
from dxband.models.chord import ChordSegment, ChordTimeline
from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming
from dxband.models.melody import (
    MelodyBar,
    MelodyChord,
    MelodyDocument,
    MelodyKeyChange,
    MelodyNote,
)
from dxband.services.web_musician_view import build_web_musician_song


def test_web_musician_view_serializes_bar_rows_and_selected_chord_mode(
    package_factory: object,
) -> None:
    assert callable(package_factory)
    package_path = package_factory()
    assert isinstance(package_path, Path)
    package = SongPackageValidator().validate(package_path, verify_media=False)
    package = replace(
        package,
        chords=ChordTimeline(segments=[ChordSegment(start_ms=0, end_ms=4_000, chord="C:maj")]),
    )

    payload = build_web_musician_song(package, "degree")

    assert payload["id"] == package.config.song_id
    assert payload["title"] == "测试歌曲"
    assert payload["beats_per_bar"] == 4
    rows = payload["rows"]
    assert isinstance(rows, list)
    assert rows[0]["layout"] == "bars"
    assert rows[0]["beats"][0]["chords"] == ["1"]
    assert rows[0]["beats"][0]["chord_modes"] == {
        "degree": ["1"],
        "chord": ["C"],
        "chord_c": ["C"],
    }
    assert payload["capo"] == 0
    assert build_web_musician_song(package, "key:D")["rows"][0]["beats"][0]["chords"] == ["D"]


def test_empty_grid_after_score_is_removed_but_late_lyrics_remain(
    package_factory: object,
) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    score = MelodyDocument(
        tonic_midi=60, coverage_end_ms=6000,
        bars=[
            MelodyBar(
                start_ms=start, end_ms=start + 2000,
                beat_times_ms=[start, start + 500, start + 1000, start + 1500],
                start_16th=index * 16, end_16th=(index + 1) * 16,
            )
            for index, start in enumerate((0, 2000, 4000))
        ],
    )
    early = LyricLine(id="line-0001", start_ms=1000, end_ms=1500, text="唱")
    lyrics = LyricsDocument(
        schema_version=1,
        title=package.config.title, language=package.config.language,
        timing_mode="line", lines=[early],
    )
    package = replace(package, melody=score, lyrics=lyrics)

    rows = build_web_musician_song(package, "degree")["rows"]
    assert [(row["start_ms"], row["end_ms"]) for row in rows] == [
        (0, 2000), (2000, 4000), (4000, 6000),
    ]

    late = LyricLine(id="line-0002", start_ms=8000, end_ms=8500, text="再唱")
    package = replace(package, lyrics=lyrics.model_copy(update={"lines": [early, late]}))
    rows = build_web_musician_song(package, "degree")["rows"]
    assert any(row["start_ms"] >= 6000 and any(beat.get("lyrics") for beat in row["beats"])
               for row in rows)


def test_score_chord_and_linked_lyric_use_model_positions_instead_of_beat_times(
    package_factory: object,
) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    lyrics = LyricsDocument(
        schema_version=1, title="测试歌曲", language="zh-CN", timing_mode="word",
        lines=[LyricLine(
            id="line-0001", start_ms=900, end_ms=1200, text="唱",
            words=[WordTiming(text="唱", start_ms=900, end_ms=1200)],
        )],
    )
    melody = MelodyDocument(
        tonic_midi=60, coverage_end_ms=4000,
        bars=[MelodyBar(
            start_ms=0, end_ms=4000, beat_times_ms=[0, 1000, 2000, 3000],
            start_16th=0, end_16th=16,
        )],
        notes=[MelodyNote(
            start_ms=700, end_ms=1100, midi=60, source="vocals",
            lyric_line_id="line-0001", lyric_character_index=0,
            start_16th=2, duration_16ths=2,
        )],
        chords=[MelodyChord(at_ms=700, chord="C:maj", start_16th=2)],
    )
    package = replace(
        package, lyrics=lyrics, melody=melody,
        chords=ChordTimeline(segments=[ChordSegment(start_ms=0, end_ms=4000, chord="G:maj")]),
    )

    beats = build_web_musician_song(package, "chord")["rows"][0]["beats"]

    assert beats[0]["chords"] == ["C"]
    assert beats[0]["chord_units"] == [{
        "start_16th": 2,
        "chord": "C:maj",
        "chord_modes": {"degree": ["1"], "chord": ["C"], "chord_c": ["C"]},
    }]
    assert beats[0]["lyric_units"] == [{"text": "唱", "at_ms": 700, "start_16th": 2}]
    assert all(not beat["chords"] for beat in beats[1:])


def test_score_hides_repeated_chords_until_the_harmony_changes(
    package_factory: object,
) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    melody = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=8_000,
        bars=[
            MelodyBar(
                start_ms=0, end_ms=4_000,
                beat_times_ms=[0, 1_000, 2_000, 3_000],
                start_16th=0, end_16th=16,
            ),
            MelodyBar(
                start_ms=4_000, end_ms=8_000,
                beat_times_ms=[4_000, 5_000, 6_000, 7_000],
                start_16th=16, end_16th=32,
            ),
        ],
        chords=[
            MelodyChord(at_ms=0, chord="C:maj", start_16th=0),
            MelodyChord(at_ms=2_000, chord="C:maj", start_16th=8),
            MelodyChord(at_ms=4_000, chord="C:maj", start_16th=16),
            MelodyChord(at_ms=5_000, chord="G:maj", start_16th=20),
            MelodyChord(at_ms=6_000, chord="G:maj", start_16th=24),
            MelodyChord(at_ms=7_000, chord="N", start_16th=28),
            MelodyChord(at_ms=7_500, chord="G:maj", start_16th=30),
        ],
    )
    package = replace(package, melody=melody)

    rows = build_web_musician_song(package, "degree")["rows"]
    units = [
        unit
        for row in rows
        for beat in row.get("beats", [])
        for unit in beat.get("chord_units", [])
    ]

    assert [(unit["start_16th"], unit["chord"]) for unit in units] == [
        (0, "C:maj"),
        (20, "G:maj"),
        (30, "G:maj"),
    ]


def test_short_score_bars_expose_their_meter(package_factory: object) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    melody = MelodyDocument(
        tonic_midi=60, coverage_end_ms=5000,
        bars=[
            MelodyBar(start_ms=0, end_ms=400, beat_times_ms=[0], start_16th=0, end_16th=2),
            MelodyBar(start_ms=400, end_ms=1200, beat_times_ms=[400], start_16th=2, end_16th=6),
            MelodyBar(
                start_ms=1200, end_ms=2800, beat_times_ms=[1200, 2000],
                start_16th=6, end_16th=14,
            ),
            MelodyBar(
                start_ms=2800, end_ms=5000, beat_times_ms=[2800, 3350, 3900, 4450],
                start_16th=14, end_16th=30,
            ),
        ],
    )
    package = replace(package, melody=melody)

    rows = build_web_musician_song(package, "degree")["rows"]

    assert [row["meter"] for row in rows if row.get("score_bar")] == ["1/8", "1/4", "2/4", "4/4"]


def test_web_musician_view_uses_relative_major_degrees_for_minor_song(
    package_factory: object,
) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    musical = package.config.musical.model_copy(update={"original_key": "F#m"})
    package = replace(
        package,
        config=package.config.model_copy(update={"musical": musical}),
        chords=ChordTimeline(segments=[ChordSegment(start_ms=0, end_ms=4_000, chord="F#:min")]),
        melody=MelodyDocument(
            tonic_midi=66,
            coverage_end_ms=4_000,
            notes=[MelodyNote(start_ms=0, end_ms=500, midi=66, source="piano")],
            key_changes=[MelodyKeyChange(at_ms=0, tonic_midi=66)],
        ),
    )

    payload = build_web_musician_song(package, "degree")

    assert payload["rows"][0]["beats"][0]["chords"] == ["6m"]
    assert payload["rows"][0]["beats"][0]["chord_modes"]["degree"] == ["6m"]
    assert payload["numbered_key"] == "A"
    assert payload["capo"] == 9
    assert payload["melody_transpose"] == -3
    assert payload["melody_reference"] == "A4"
    assert payload["melody_key"] == 9
    assert payload["melody_tonic_midi"] == 69
    assert payload["rows"][0]["beats"][0]["melody_notes"][0]["melody_key"] == 9


def test_web_musician_view_fills_leading_partial_bar_with_rests(
    package_factory: object,
) -> None:
    assert callable(package_factory)
    package_path = package_factory()
    package = SongPackageValidator().validate(package_path, verify_media=False)
    musical = package.config.musical.model_copy(
        update={
            "beat_times_ms": [500, 1000, 1500, 2000, 2500, 3000, 3500],
            "downbeat_times_ms": [1500, 3500],
        }
    )
    package = replace(package, config=package.config.model_copy(update={"musical": musical}))

    payload = build_web_musician_song(package, "degree")
    rows = payload["rows"]
    assert isinstance(rows, list)
    pickup = rows[0]
    assert pickup["pickup"] is True
    assert [beat["at_ms"] for beat in pickup["beats"]] == [-500, 0, 500, 1000]
    assert [beat.get("rest", False) for beat in pickup["beats"]] == [True, True, False, False]
    assert rows[1]["beats"][0]["at_ms"] == 1500


def test_score_opening_rest_beats_share_the_first_measure(package_factory: object) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    musical = package.config.musical.model_copy(
        update={
            "beat_times_ms": [500, 1400, 2300, 3200],
            "downbeat_times_ms": [2300],
        }
    )
    melody = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=2300,
        bars=[
            MelodyBar(
                start_ms=500, end_ms=2300, beat_times_ms=[500, 1400],
                leading_rest_beats=2, start_16th=0, end_16th=16,
            )
        ],
        notes=[
            MelodyNote(
                start_ms=at, end_ms=at + 450, midi=pitch, source="other",
                start_16th=8 + index * 2, duration_16ths=2,
            )
            for index, (at, pitch) in enumerate(
                zip((500, 950, 1400, 1850), (64, 67, 72, 76), strict=True)
            )
        ],
    )
    package = replace(
        package,
        config=package.config.model_copy(update={"musical": musical}),
        melody=melody,
    )

    rows = build_web_musician_song(package, "degree")["rows"]

    assert rows[0]["score_bar"] is True
    assert [beat["at_ms"] for beat in rows[0]["beats"]] == [-1300, -400, 500, 1400]
    assert [
        [(event["kind"], event["duration_16ths"]) for event in beat["melody_events"]]
        for beat in rows[0]["beats"]
    ] == [
        [("rest", 4)], [("rest", 4)],
        [("note", 2), ("note", 2)], [("note", 2), ("note", 2)],
    ]


def test_web_musician_view_loads_timed_melody_and_review_gaps(package_factory: object) -> None:
    assert callable(package_factory)
    package_path = package_factory()
    assert isinstance(package_path, Path)
    (package_path / "melody.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tonic_midi": 57,
                "coverage_end_ms": 4000,
                "notes": [
                    {
                        "start_ms": 900,
                        "end_ms": 1600,
                        "display_ms": 100,
                        "midi": 76,
                        "source": "piano",
                        "review": "candidate",
                    },
                    {
                        "start_ms": 1200,
                        "end_ms": 1500,
                        "display_ms": 100,
                        "lyric_line_id": "line-0001",
                        "lyric_character_index": 0,
                        "midi": 57,
                        "source": "vocals",
                        "review": "candidate",
                    },
                ],
                "gaps": [{"start_ms": 2000, "end_ms": 3500, "label": "前奏待校"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    package = SongPackageValidator().validate(package_path, verify_media=False)
    payload = build_web_musician_song(package, "degree")
    assert payload["melody_key"] == 9
    assert payload["melody_reference"] == "A3"
    assert payload["melody_transpose"] == 0
    assert payload["melody_coverage_end_ms"] == 4000
    assert payload["melody_review_pending"] is True
    rows = payload["rows"]
    assert isinstance(rows, list)
    assert rows[0]["beats"][0]["melody_notes"] == [
        {"midi": 76, "review": "candidate", "at_ms": 900}
    ]
    assert rows[0]["beats"][1]["melody_hold"] is True
    assert rows[0]["beats"][2]["melody_notes"] == [
        {"midi": 57, "review": "candidate", "at_ms": 1200}
    ]
    assert rows[0]["beats"][4]["melody_gap"] == "前奏待校"

    assert package.melody is not None
    raised_melody = package.melody.model_copy(update={"tonic_midi": 62})
    d_musical = package.config.musical.model_copy(update={"original_key": "D"})
    d_config = package.config.model_copy(update={"musical": d_musical})
    raised_payload = build_web_musician_song(
        replace(package, config=d_config, melody=raised_melody), "degree"
    )
    assert raised_payload["melody_reference"] == "D4"
    assert raised_payload["melody_transpose"] == 2

    for original_key, expected in (("F", 5), ("F#", -6), ("G", -5)):
        musical = package.config.musical.model_copy(update={"original_key": original_key})
        config = package.config.model_copy(update={"musical": musical})
        key_payload = build_web_musician_song(replace(package, config=config), "degree")
        assert key_payload["melody_transpose"] == expected


def test_score_bars_regroup_chords_and_snap_early_note_to_its_bar(package_factory: object) -> None:
    assert callable(package_factory)
    package_path = package_factory()
    assert isinstance(package_path, Path)
    package = SongPackageValidator().validate(package_path, verify_media=False)
    musical = package.config.musical.model_copy(
        update={
            "beat_times_ms": list(range(0, 4000, 500)),
            "downbeat_times_ms": [0, 2000],
        }
    )
    package = replace(
        package,
        config=package.config.model_copy(update={"musical": musical}),
        chords=ChordTimeline(
            segments=[
                ChordSegment(start_ms=0, end_ms=1000, chord="C:maj"),
                ChordSegment(start_ms=1000, end_ms=4000, chord="G:maj"),
            ]
        ),
        melody=MelodyDocument(
            tonic_midi=60,
            coverage_end_ms=4000,
            notes=[MelodyNote(start_ms=1980, end_ms=2200, midi=67, source="piano")],
            bars=[
                MelodyBar(start_ms=0, end_ms=2000, beat_times_ms=[0, 1000]),
                MelodyBar(start_ms=2000, end_ms=4000, beat_times_ms=[2000, 3000]),
            ],
        ),
    )
    payload = build_web_musician_song(package, "degree")
    score_rows = payload["rows"][:2]
    assert [len(row["beats"]) for row in score_rows] == [2, 2]
    assert score_rows[0]["beats"][0]["chords"] == ["1"]
    assert score_rows[0]["beats"][1]["chords"] == ["5"]
    assert score_rows[1]["beats"][0]["melody_notes"] == [
        {"midi": 67, "review": "candidate", "at_ms": 1980}
    ]
    assert payload["melody_bpm"] == 120


def test_score_bar_uses_vocal_onset_when_lyric_timestamp_leads_downbeat(
    package_factory: object,
) -> None:
    assert callable(package_factory)
    package_path = package_factory()
    assert isinstance(package_path, Path)
    package = SongPackageValidator().validate(package_path, verify_media=False)
    musical = package.config.musical.model_copy(
        update={"beat_times_ms": list(range(0, 4000, 500)), "downbeat_times_ms": [0, 2000]}
    )
    lyrics = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=1850,
                end_ms=2500,
                text="终点",
                words=[
                    WordTiming(text="终", start_ms=1850, end_ms=2150),
                    WordTiming(text="点", start_ms=2150, end_ms=2500),
                ],
            )
        ],
    )
    melody = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=4000,
        notes=[
            MelodyNote(
                start_ms=2110,
                end_ms=2350,
                display_ms=1850,
                lyric_line_id="line-0001",
                lyric_character_index=0,
                midi=60,
                source="vocals",
            )
        ],
        bars=[
            MelodyBar(start_ms=0, end_ms=2000, beat_times_ms=[0, 1000]),
            MelodyBar(start_ms=2000, end_ms=4000, beat_times_ms=[2000, 3000]),
        ],
    )
    package = replace(
        package,
        config=package.config.model_copy(update={"musical": musical}),
        lyrics=lyrics,
        melody=melody,
    )

    score_rows = build_web_musician_song(package, "degree")["rows"][:2]

    assert "终" not in "".join(beat["lyrics"] for beat in score_rows[0]["beats"])
    assert score_rows[1]["beats"][0]["lyrics"].startswith("终")
    assert score_rows[1]["beats"][0]["melody_notes"] == [
        {"midi": 60, "review": "candidate", "at_ms": 2110}
    ]


def test_score_bars_keep_lyrics_in_three_eighth_meter(package_factory: object) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    bars = [
        MelodyBar(
            start_ms=start,
            end_ms=min(start + 1500, 10000),
            beat_times_ms=[start, start + 1000] if start < 9000 else [start],
            start_16th=index * 6,
            end_16th=index * 6 + (6 if start < 9000 else 4),
        )
        for index, start in enumerate(range(0, 10000, 1500))
    ]
    musical = package.config.musical.model_copy(
        update={
            "beat_times_ms": [beat for bar in bars for beat in bar.beat_times_ms],
            "downbeat_times_ms": [bar.start_ms for bar in bars],
            "beats_per_bar": 2,
        }
    )
    package = replace(
        package,
        config=package.config.model_copy(update={"musical": musical}),
        melody=MelodyDocument(tonic_midi=60, coverage_end_ms=10000, bars=bars),
    )

    rows = build_web_musician_song(package, "degree")["rows"]

    assert any("第" in beat["lyrics"] for row in rows for beat in row["beats"])


def test_english_score_keeps_words_in_source_order(package_factory: object) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    lyrics = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="en",
        timing_mode="line",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=1000,
                end_ms=4000,
                text="Not a footprint to be seen",
            )
        ],
    )
    bars = [
        MelodyBar(start_ms=start, end_ms=start + 2000, beat_times_ms=[start, start + 1000])
        for start in (0, 2000, 4000)
    ]
    musical = package.config.musical.model_copy(
        update={
            "beat_times_ms": [beat for bar in bars for beat in bar.beat_times_ms],
            "downbeat_times_ms": [bar.start_ms for bar in bars],
            "beats_per_bar": 2,
        }
    )
    melody = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=6000,
        notes=[
            MelodyNote(
                start_ms=2500,
                end_ms=2800,
                midi=60,
                source="vocals",
                lyric_line_id="line-0001",
                lyric_character_index=0,
            )
        ],
        bars=bars,
    )
    package = replace(
        package,
        config=package.config.model_copy(update={"musical": musical}),
        lyrics=lyrics,
        melody=melody,
    )

    rows = build_web_musician_song(package, "degree")["rows"]
    displayed = "".join(beat["lyrics"] for row in rows for beat in row["beats"])

    assert displayed.strip() == "Not a footprint to be seen"


def test_score_uses_recorded_key_change_for_later_notes(package_factory: object) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    bars = [
        MelodyBar(
            start_ms=start,
            end_ms=start + 4000,
            beat_times_ms=[start + offset for offset in (0, 1000, 2000, 3000)],
            start_16th=index * 16,
            end_16th=(index + 1) * 16,
        )
        for index, start in enumerate((0, 4000))
    ]
    melody = MelodyDocument(
        tonic_midi=69,
        coverage_end_ms=8000,
        bars=bars,
        key_changes=[MelodyKeyChange(at_ms=4000, start_16th=16, tonic_midi=71)],
        notes=[
            MelodyNote(
                start_ms=3000,
                end_ms=4000,
                midi=81,
                source="vocals",
                start_16th=12,
                duration_16ths=4,
            ),
            MelodyNote(
                start_ms=4000,
                end_ms=5000,
                midi=83,
                source="vocals",
                start_16th=16,
                duration_16ths=4,
            ),
        ],
    )
    package = replace(package, melody=melody)

    rows = build_web_musician_song(package, "degree")["rows"]

    assert rows[0]["beats"][3]["melody_events"][0]["melody_key"] == 9
    assert rows[1]["beats"][0]["melody_key_change"] == "1=B"
    assert rows[1]["beats"][0]["melody_events"][0]["melody_key"] == 11
    assert rows[1]["beats"][0]["melody_events"][0]["melody_tonic_midi"] == 71


def test_score_grid_places_early_note_by_position_instead_of_milliseconds(
    package_factory: object,
) -> None:
    assert callable(package_factory)
    package_path = package_factory()
    package = SongPackageValidator().validate(package_path, verify_media=False)
    package = replace(
        package,
        melody=MelodyDocument(
            tonic_midi=60,
            coverage_end_ms=4000,
            bars=[
                MelodyBar(
                    start_ms=0,
                    end_ms=4000,
                    beat_times_ms=[0, 1000, 2000, 3000],
                    start_16th=0,
                    end_16th=16,
                )
            ],
            notes=[
                MelodyNote(
                    start_ms=900,
                    end_ms=1150,
                    midi=67,
                    source="vocals",
                    start_16th=4,
                    duration_16ths=1,
                )
            ],
        ),
    )

    score_beat = build_web_musician_song(package, "degree")["rows"][0]["beats"][1]

    assert score_beat["melody_notes"] == [
        {
            "midi": 67,
            "review": "candidate",
            "at_ms": 900,
            "start_16th": 4,
            "duration_16ths": 1,
        }
    ]


def test_score_note_crossing_barline_has_two_tied_glyphs(package_factory: object) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    package = replace(
        package,
        melody=MelodyDocument(
            tonic_midi=60,
            coverage_end_ms=4000,
            bars=[
                MelodyBar(
                    start_ms=0,
                    end_ms=2000,
                    beat_times_ms=[0, 500, 1000, 1500],
                    start_16th=0,
                    end_16th=16,
                ),
                MelodyBar(
                    start_ms=2000,
                    end_ms=4000,
                    beat_times_ms=[2000, 2500, 3000, 3500],
                    start_16th=16,
                    end_16th=32,
                ),
            ],
            notes=[
                MelodyNote(
                    start_ms=1875,
                    end_ms=2250,
                    midi=67,
                    source="vocals",
                    start_16th=15,
                    duration_16ths=3,
                )
            ],
        ),
    )

    rows = build_web_musician_song(package, "degree")["rows"]
    first = rows[0]["beats"][3]["melody_notes"][0]
    second = rows[1]["beats"][0]["melody_notes"][0]
    assert (first["start_16th"], first["duration_16ths"], first["tie_in"], first["tie_out"]) == (
        15,
        1,
        False,
        True,
    )
    assert (
        second["start_16th"],
        second["duration_16ths"],
        second["tie_in"],
        second["tie_out"],
    ) == (16, 2, True, False)
    assert first["tie_id"] == second["tie_id"]


def test_syncopated_dotted_note_uses_tie_at_beat_boundary(package_factory: object) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    package = replace(
        package,
        melody=MelodyDocument(
            tonic_midi=60,
            coverage_end_ms=4000,
            bars=[
                MelodyBar(
                    start_ms=0,
                    end_ms=4000,
                    beat_times_ms=[0, 1000, 2000, 3000],
                    start_16th=0,
                    end_16th=16,
                )
            ],
            notes=[
                MelodyNote(
                    start_ms=750,
                    end_ms=1500,
                    midi=67,
                    source="other",
                    start_16th=3,
                    duration_16ths=3,
                )
            ],
        ),
    )

    beats = build_web_musician_song(package, "degree")["rows"][0]["beats"]
    first = beats[0]["melody_notes"][0]
    second = beats[1]["melody_notes"][0]
    assert (first["start_16th"], first["duration_16ths"], first["tie_out"]) == (3, 1, True)
    assert (second["start_16th"], second["duration_16ths"], second["tie_in"]) == (4, 2, True)
    assert first["tie_id"] == second["tie_id"]


def test_score_rhythm_fills_every_unoccupied_sixteenth_without_moving_early_lyric(
    package_factory: object,
) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    lyrics = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=0,
                end_ms=900,
                text="晚",
                words=[WordTiming(text="晚", start_ms=0, end_ms=900)],
            )
        ],
    )
    melody = MelodyDocument(
        tonic_midi=69,
        coverage_end_ms=4000,
        bars=[
            MelodyBar(
                start_ms=0,
                end_ms=4000,
                beat_times_ms=[0, 1000, 2000, 3000],
                start_16th=0,
                end_16th=16,
            )
        ],
        notes=[
            MelodyNote(
                start_ms=750, end_ms=1250, midi=66, source="vocals", start_16th=3, duration_16ths=2
            ),
            MelodyNote(
                start_ms=1500, end_ms=2500, midi=69, source="vocals", start_16th=6, duration_16ths=4
            ),
        ],
    )
    package = replace(package, lyrics=lyrics, melody=melody)

    payload = build_web_musician_song(package, "degree")
    beats = payload["rows"][0]["beats"]

    assert payload["melody_tonic_midi"] == 69
    assert [
        (event["kind"], event["start_16th"], event["duration_16ths"])
        for event in beats[0]["melody_events"]
    ] == [
        ("rest", 0, 3),
        ("note", 3, 1),
    ]
    assert [
        (event["kind"], event["start_16th"], event["duration_16ths"])
        for event in beats[1]["melody_events"]
    ] == [
        ("note", 4, 1),
        ("rest", 5, 1),
        ("note", 6, 2),
    ]
    assert [
        (event["kind"], event["start_16th"], event["duration_16ths"])
        for event in beats[2]["melody_events"]
    ] == [
        ("note", 8, 2),
        ("rest", 10, 2),
    ]
    assert beats[3]["melody_events"] == [{"kind": "rest", "start_16th": 12, "duration_16ths": 4}]
    assert beats[0]["lyric_units"] == [{"text": "晚", "at_ms": 0}]


def test_score_uses_acoustic_gap_to_distinguish_quantization_from_rest(
    package_factory: object,
) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    melody = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=4000,
        bars=[MelodyBar(
            start_ms=0, end_ms=4000, beat_times_ms=[0, 1000, 2000, 3000],
            start_16th=0, end_16th=16,
        )],
        notes=[
            MelodyNote(start_ms=start, end_ms=end, midi=60, source="vocals",
                       start_16th=step, duration_16ths=duration)
            for start, end, step, duration in (
                (0, 720, 0, 2), (750, 1290, 3, 2), (1500, 2000, 6, 2),
            )
        ],
    )
    beats = build_web_musician_song(replace(package, melody=melody), "degree")["rows"][0]["beats"]

    assert [event["kind"] for event in beats[0]["melody_events"]] == ["note", "note"]
    assert [event["kind"] for event in beats[1]["melody_events"]] == ["note", "rest", "note"]


def test_score_lyrics_use_nearest_beat_without_attaching_to_distant_note(
    package_factory: object,
) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    lyrics = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=650,
                end_ms=2150,
                text="一起",
                words=[
                    WordTiming(text="一", start_ms=650, end_ms=1000),
                    WordTiming(text="起", start_ms=1750, end_ms=2150),
                ],
            )
        ],
    )
    melody = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=4000,
        bars=[
            MelodyBar(
                start_ms=0,
                end_ms=4000,
                beat_times_ms=[0, 1000, 2000, 3000],
                start_16th=0,
                end_16th=16,
            )
        ],
        notes=[
            MelodyNote(
                start_ms=0,
                end_ms=500,
                midi=60,
                source="vocals",
                start_16th=0,
                duration_16ths=2,
            )
        ],
    )
    package = replace(package, lyrics=lyrics, melody=melody)

    beats = build_web_musician_song(package, "degree")["rows"][0]["beats"]

    assert [beat["lyrics"] for beat in beats] == ["", "一", "起", ""]
    assert beats[1]["lyric_units"] == [{"text": "一", "at_ms": 650}]
    assert beats[2]["lyric_units"] == [{"text": "起", "at_ms": 1750}]

    close_note = MelodyNote(
        start_ms=750,
        end_ms=1000,
        midi=62,
        source="vocals",
        start_16th=3,
        duration_16ths=1,
    )
    package = replace(package, melody=melody.model_copy(update={"notes": [close_note]}))
    beats = build_web_musician_song(package, "degree")["rows"][0]["beats"]

    assert beats[0]["lyric_units"] == [{"text": "一", "at_ms": 750, "start_16th": 3}]
    assert beats[2]["lyric_units"] == [{"text": "起", "at_ms": 1750}]

    linked_note = close_note.model_copy(
        update={"lyric_line_id": "line-0001", "lyric_character_index": 0}
    )
    unlinked_note = MelodyNote(
        start_ms=1750,
        end_ms=2000,
        midi=64,
        source="vocals",
        start_16th=7,
        duration_16ths=1,
    )
    package = replace(
        package, melody=melody.model_copy(update={"notes": [linked_note, unlinked_note]})
    )
    beats = build_web_musician_song(package, "degree")["rows"][0]["beats"]

    assert beats[0]["lyric_units"] == [{"text": "一", "at_ms": 750, "start_16th": 3}]
    assert beats[2]["lyric_units"] == [{"text": "起", "at_ms": 1750}]


def test_note_releasing_mid_beat_is_tied_before_the_following_rest(
    package_factory: object,
) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    melody = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=4000,
        bars=[
            MelodyBar(
                start_ms=0,
                end_ms=4000,
                beat_times_ms=[0, 1000, 2000, 3000],
                start_16th=0,
                end_16th=16,
            )
        ],
        notes=[
            MelodyNote(
                start_ms=0, end_ms=1500, midi=60, source="piano", start_16th=0, duration_16ths=6
            ),
        ],
    )
    package = replace(package, melody=melody)

    beats = build_web_musician_song(package, "degree")["rows"][0]["beats"]

    first = beats[0]["melody_events"][0]
    second = beats[1]["melody_events"][0]
    assert (first["kind"], first["duration_16ths"], first["tie_out"]) == (
        "note",
        4,
        True,
    )
    assert (second["kind"], second["duration_16ths"], second["tie_in"]) == (
        "note",
        2,
        True,
    )
    assert beats[1]["melody_events"][1] == {
        "kind": "rest",
        "start_16th": 6,
        "duration_16ths": 2,
    }


def test_new_lead_attack_truncates_an_overlapping_model_sustain(
    package_factory: object,
) -> None:
    assert callable(package_factory)
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    melody = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=4000,
        bars=[
            MelodyBar(
                start_ms=0,
                end_ms=4000,
                beat_times_ms=[0, 1000, 2000, 3000],
                start_16th=0,
                end_16th=16,
            )
        ],
        notes=[
            MelodyNote(
                start_ms=0, end_ms=2500, midi=60, source="vocals", start_16th=0, duration_16ths=10
            ),
            MelodyNote(
                start_ms=1500, end_ms=2000, midi=62, source="vocals", start_16th=6, duration_16ths=2
            ),
        ],
    )
    package = replace(package, melody=melody)

    beats = build_web_musician_song(package, "degree")["rows"][0]["beats"]

    assert beats[0]["melody_notes"][0]["duration_16ths"] == 4
    assert beats[1]["melody_notes"][0]["duration_16ths"] == 2
    assert beats[1]["melody_notes"][1]["start_16th"] == 6
    assert beats[1]["melody_events"][-1]["kind"] == "note"
