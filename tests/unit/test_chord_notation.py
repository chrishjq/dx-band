# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dxband.analysis.chord_notation import (
    DISPLAY_KEYS,
    capo_for_c_chords,
    capo_for_display_key,
    chord_for_mode,
    chord_from_mode,
    chord_reference_key,
    chord_to_c_symbol,
    chord_to_degree,
    chord_to_key_symbol,
    chord_to_symbol,
    transpose_for_display_key,
)


def test_degree_chords_and_bass_in_d_major() -> None:
    assert chord_to_degree("G:maj", "D") == "4"
    assert chord_to_degree("D:maj/3", "D") == "1/3"
    assert chord_to_degree("E:min", "D") == "2m"
    assert chord_to_degree("E:min7", "D") == "2m7"
    assert chord_to_degree("A:maj", "D") == "5"
    assert chord_to_degree("B:min/b3", "D") == "6m/1"
    assert chord_to_degree("G#:maj", "D") == "#4"
    assert chord_to_degree("Bb:maj", "D") == "#5"


def test_minor_keys_use_the_relative_major_for_numbered_chords() -> None:
    assert chord_to_degree("F#:min", "F#m") == "6m"
    assert chord_to_degree("B:min", "F#m") == "2m"
    assert chord_to_degree("G:min", "Gm") == "6m"
    assert chord_from_mode("6m", "F#m", "degree") == "F#:min"
    assert chord_from_mode("1", "F#m", "degree") == "A:maj"
    assert chord_from_mode("1", "Gm", "degree") == "Bb:maj"


def test_absolute_chord_mode_uses_note_names_and_slash_bass() -> None:
    assert chord_to_symbol("D:maj/3", "D") == "D/F#"
    assert chord_to_symbol("F#:min7", "D") == "F#m7"
    assert chord_to_symbol("Bb:maj", "F") == "Bb"


def test_c_chord_mode_transposes_roots_and_slash_bass() -> None:
    assert chord_to_c_symbol("D:maj", "D") == "C"
    assert chord_to_c_symbol("G:maj", "D") == "F"
    assert chord_to_c_symbol("B:min", "D") == "Am"
    assert chord_to_c_symbol("D:maj/3", "D") == "C/E"
    assert chord_to_c_symbol("Bb:aug", "D") == "G#aug"
    assert chord_to_c_symbol("F#:min", "F#m") == "Am"
    assert chord_from_mode("Am", "F#m", "chord_c") == "F#:min"


def test_any_key_mode_transposes_chord_quality_and_slash_bass() -> None:
    assert chord_to_key_symbol("D:maj/3", "D", "C") == "C/E"
    assert chord_to_key_symbol("D:maj/3", "D", "Eb") == "Eb/G"
    assert chord_to_key_symbol("B:min7", "D", "G") == "Em7"
    assert chord_for_mode("F#:min", "F#m", "key:F#") == "F#m"
    assert chord_for_mode("F#:min", "F#m", "key:A") == "Am"
    assert chord_for_mode("N", "D", "key:B") == ""
    for target in DISPLAY_KEYS:
        assert chord_for_mode("C:maj", "C", f"key:{target}") == target


def test_no_chord_and_unknown_key() -> None:
    assert chord_to_degree("N", "D") == ""
    assert chord_to_degree("D:maj", "") == "D:maj"


def test_capo_for_c_chords_uses_the_numbered_chord_reference_key() -> None:
    assert capo_for_c_chords("C") == 0
    assert capo_for_c_chords("D") == 2
    assert capo_for_c_chords("F") == 5
    assert capo_for_c_chords("F#m") == 9
    assert capo_for_c_chords("Bb") == 10
    assert capo_for_c_chords("invalid") is None
    assert chord_reference_key("F#m") == "A"
    assert chord_reference_key("Gm") == "Bb"
    assert capo_for_display_key("D", "C") == 2
    assert transpose_for_display_key("D", "C") == 2
    assert capo_for_display_key("D", "G") == 7
    assert transpose_for_display_key("D", "G") == -5
    assert capo_for_display_key("F#m", "A") == 0
    assert chord_to_key_symbol("F:min", "Fm", "F") == "Fm"
    assert chord_to_key_symbol("F:min", "Fm", "G") == "Gm"


def test_each_editing_mode_round_trips_to_one_absolute_chord_format() -> None:
    examples = {
        "degree": "4m7/6",
        "chord": "Gm7/B",
        "chord_c": "Fm7/A",
    }

    for mode, label in examples.items():
        canonical = chord_from_mode(label, "D", mode)
        assert chord_for_mode(canonical, "D", mode) == label

    assert chord_from_mode("4", "D", "degree") == "G:maj"
    assert chord_from_mode("F", "D", "chord_c") == "G:maj"
    assert chord_from_mode("G", "D", "chord") == "G:maj"
    assert chord_from_mode("Dbmin7/Bb", "D", "chord") == "Db:min7/Bb"
