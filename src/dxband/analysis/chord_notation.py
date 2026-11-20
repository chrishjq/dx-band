# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Convert absolute chord labels to movable-do scale degrees."""

import re

_PITCH = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_MAJOR = {0: "1", 2: "2", 4: "3", 5: "4", 7: "5", 9: "6", 11: "7"}
_MAJOR_CHROMATIC = {1: "b2", 3: "b3", 6: "#4", 8: "#5", 10: "b7"}
_SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")

CHORD_DISPLAY_MODES = ("degree", "chord", "chord_c")
DISPLAY_KEYS = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")


def valid_display_mode(mode: str) -> bool:
    return mode in CHORD_DISPLAY_MODES or (mode.startswith("key:") and mode[4:] in DISPLAY_KEYS)


def _pitch(name: str) -> int | None:
    match = re.match(r"^([A-G])([#b]?)$", name)
    if match is None:
        return None
    return (_PITCH[match.group(1)] + {"#": 1, "b": -1, "": 0}[match.group(2)]) % 12


def _degree(note: str, tonic: int) -> str:
    pitch = _pitch(note)
    if pitch is None:
        return note
    interval = (pitch - tonic) % 12
    if interval in _MAJOR:
        return _MAJOR[interval]
    return _MAJOR_CHROMATIC[interval]


def _bass_note(root: str, bass: str, prefer_flats: bool) -> str:
    if not re.fullmatch(r"[#b]?[1-9]", bass):
        return bass
    root_pitch = _pitch(root)
    if root_pitch is None:
        return bass
    interval = {"1": 0, "2": 2, "3": 4, "4": 5, "5": 7, "6": 9, "7": 11, "8": 12, "9": 14}[bass[-1]]
    interval += {"#": 1, "b": -1}.get(bass[0], 0)
    names = _FLAT_NAMES if prefer_flats else _SHARP_NAMES
    return names[(root_pitch + interval) % 12]


def _quality_suffix(quality: str) -> str:
    if quality in {"maj", "major"}:
        return ""
    if quality.startswith("min"):
        return "m" + quality[3:]
    return quality


def _canonical_quality(suffix: str) -> str:
    if not suffix or suffix in {"maj", "major"}:
        return "maj"
    if suffix == "m":
        return "min"
    if suffix.startswith("min"):
        return suffix
    if suffix.startswith("m") and not suffix.startswith("maj"):
        return "min" + suffix[1:]
    return suffix


def _note_name(pitch: int, prefer_flats: bool) -> str:
    return (_FLAT_NAMES if prefer_flats else _SHARP_NAMES)[pitch % 12]


def _symbol_to_chord(label: str, transpose: int = 0, prefer_flats: bool = False) -> str:
    normalized = label.strip().replace("♯", "#").replace("♭", "b")
    if normalized == "N":
        return "N"
    match = re.fullmatch(r"([A-G][#b]?)([^/\s:]*)(?:/([A-G][#b]?))?", normalized)
    if match is None:
        raise ValueError(f"无法识别和弦：{label}")
    root, suffix, bass = match.groups()
    root_pitch = _pitch(root)
    if root_pitch is None:
        raise ValueError(f"无法识别和弦根音：{root}")
    rendered_root = root if transpose == 0 else _note_name(root_pitch + transpose, prefer_flats)
    chord = f"{rendered_root}:{_canonical_quality(suffix)}"
    if bass:
        bass_pitch = _pitch(bass)
        if bass_pitch is None:
            raise ValueError(f"无法识别和弦低音：{bass}")
        chord += "/" + (
            bass if transpose == 0 else _note_name(bass_pitch + transpose, prefer_flats)
        )
    return chord


def _key_details(key: str) -> tuple[int, bool, bool]:
    match = re.fullmatch(r"([A-G][#b]?)(?:m|min)?", key.strip())
    if match is None:
        raise ValueError("缺少有效的原 Key，无法在当前模式下编辑")
    tonic = _pitch(match.group(1))
    if tonic is None:
        raise ValueError("缺少有效的原 Key，无法在当前模式下编辑")
    return tonic, "b" in match.group(1), bool(re.search(r"(?:m|min)$", key.strip()))


def _degree_key_details(key: str) -> tuple[int, bool]:
    """Return the major-key reference used by numbered chord notation.

    Minor songs use their relative major as degree 1.  For example, F# minor
    uses A major as the reference, so F#m is rendered as 6m.
    """
    tonic, prefer_flats, minor = _key_details(key)
    if not minor:
        return tonic, prefer_flats

    key_root = re.match(r"^([A-G][#b]?)", key.strip())
    root_name = key_root.group(1) if key_root is not None else ""
    prefer_flats = prefer_flats or root_name in {"C", "F", "G"}
    return (tonic + 3) % 12, prefer_flats


def degree_reference_offset(key: str) -> int | None:
    """Return the pitch offset from the stored key tonic to numbered degree 1."""
    try:
        _tonic, _prefer_flats, minor = _key_details(key)
    except ValueError:
        return None
    return 3 if minor else 0


def chord_reference_key(key: str) -> str:
    """Return the major-key label used by numbered and C-shape chord modes."""
    try:
        tonic, prefer_flats = _degree_key_details(key)
    except ValueError:
        return key.strip()
    return _note_name(tonic, prefer_flats)


def chord_key_is_valid(key: str) -> bool:
    try:
        _key_details(key)
    except ValueError:
        return False
    return True


def capo_for_c_chords(key: str) -> int | None:
    """Return the capo fret needed for C-family shapes in the chord reference key."""
    return capo_for_display_key(key, "C")


def capo_for_display_key(original_key: str, display_key: str) -> int | None:
    """Return the capo fret that makes target-key shapes sound in the original key."""
    try:
        tonic, _prefer_flats = _degree_key_details(original_key)
    except ValueError:
        return None
    display_tonic = _pitch(display_key)
    if display_tonic is None:
        return None
    return (tonic - display_tonic) % 12


def transpose_for_display_key(original_key: str, display_key: str) -> int | None:
    """Return the shortest signed transposition from display shapes to original key."""
    capo = capo_for_display_key(original_key, display_key)
    if capo is None:
        return None
    return capo if capo <= 5 else capo - 12


def capo_for_selected_tonic(original_key: str, display_key: str) -> int | None:
    """Capo for a key selector whose labels name the song's actual tonic."""
    try:
        tonic, _flats, _minor = _key_details(original_key)
    except ValueError:
        return None
    display_tonic = _pitch(display_key)
    return (tonic - display_tonic) % 12 if display_tonic is not None else None


def chord_from_symbol(label: str) -> str:
    """将普通和弦谱文字转换为单一持久化格式。"""
    return _symbol_to_chord(label)


def chord_from_c_symbol(label: str, key: str) -> str:
    """将 C 调显示下输入的和弦转回歌曲原调。"""
    tonic, prefer_flats = _degree_key_details(key)
    return _symbol_to_chord(label, transpose=tonic, prefer_flats=prefer_flats)


def chord_from_degree(label: str, key: str) -> str:
    """将级数谱和弦转回绝对和弦。"""
    normalized = label.strip().replace("♯", "#").replace("♭", "b")
    if normalized == "N":
        return "N"
    match = re.fullmatch(r"([#b]?[1-7])([^/\s:]*)(?:/([#b]?[1-7]))?", normalized)
    if match is None:
        raise ValueError(f"无法识别级数谱和弦：{label}")
    tonic, prefer_flats = _degree_key_details(key)
    root_degree, suffix, bass_degree = match.groups()
    by_degree = {degree: interval for interval, degree in _MAJOR.items()}

    def degree_pitch(value: str) -> int:
        accidental = {"#": 1, "b": -1}.get(value[0], 0)
        number = value[-1]
        if number not in by_degree:
            raise ValueError(f"无法识别级数：{value}")
        return tonic + by_degree[number] + accidental

    root = _note_name(degree_pitch(root_degree), prefer_flats)
    chord = f"{root}:{_canonical_quality(suffix or '')}"
    if bass_degree:
        chord += "/" + _note_name(degree_pitch(bass_degree), prefer_flats)
    return chord


def chord_for_mode(chord: str, key: str, mode: str) -> str:
    if mode == "degree":
        return chord_to_degree(chord, key)
    if mode == "chord_c":
        return chord_to_c_symbol(chord, key)
    if mode == "chord":
        return chord_to_symbol(chord, key)
    if mode.startswith("key:") and mode[4:] in DISPLAY_KEYS:
        return chord_to_key_symbol(chord, key, mode[4:])
    raise ValueError("无效的和弦显示模式")


def chord_to_key_symbol(chord: str, original_key: str, target_key: str) -> str:
    """Transpose chord shapes to the selected major or minor tonic."""
    if target_key not in DISPLAY_KEYS:
        raise ValueError("无效的目标调")
    c_symbol = chord_to_c_symbol(chord, original_key)
    if not c_symbol:
        return c_symbol
    match = re.fullmatch(r"([A-G][#b]?)([^/]*)(?:/([A-G][#b]?))?", c_symbol)
    if match is None:
        return c_symbol
    root, suffix, bass = match.groups()
    target_pitch = _pitch(target_key)
    if target_pitch is None:
        raise ValueError("无效的目标调")
    original_tonic, _flats, minor = _key_details(original_key)
    offset = (target_pitch + (3 if minor else 0)) % 12
    prefer_flats = (
        "b" in target_key
        or (minor and target_key in {"C", "F", "G"})
        or ("b" in original_key and original_tonic == target_pitch)
    )
    transposed = _note_name((_pitch(root) or 0) + offset, prefer_flats) + suffix
    if bass:
        transposed += "/" + _note_name((_pitch(bass) or 0) + offset, prefer_flats)
    return transposed


def chord_from_mode(label: str, key: str, mode: str) -> str:
    if mode == "degree":
        return chord_from_degree(label, key)
    if mode == "chord_c":
        return chord_from_c_symbol(label, key)
    if mode == "chord":
        return chord_from_symbol(label)
    raise ValueError("无效的和弦显示模式")


def chord_to_symbol(chord: str, key: str = "") -> str:
    """Convert lv-chordia labels to familiar letter chord symbols."""
    if chord == "N":
        return ""
    match = re.fullmatch(r"([A-G][#b]?)(?::([^/]+))?(?:/([^/]+))?", chord.strip())
    if match is None:
        return chord
    root, quality, bass = match.groups()
    label = root + _quality_suffix(quality or "maj")
    if bass:
        label += "/" + _bass_note(root, bass, "b" in key or "b" in root)
    return label


def chord_to_c_symbol(chord: str, key: str) -> str:
    """Transpose a chord from its numbered reference key to C-family shapes."""
    if chord == "N":
        return ""
    chord_match = re.fullmatch(r"([A-G][#b]?)(?::([^/]+))?(?:/([^/]+))?", chord.strip())
    if chord_match is None:
        return chord_to_symbol(chord, key)
    try:
        tonic, _prefer_flats = _degree_key_details(key)
    except ValueError:
        return chord_to_symbol(chord, key)
    root = chord_match.group(1)
    root_pitch = _pitch(root)
    if root_pitch is None:
        return chord_to_symbol(chord, key)

    quality = chord_match.group(2) or "maj"
    bass = chord_match.group(3)
    transpose = -tonic
    label = _SHARP_NAMES[(root_pitch + transpose) % 12] + _quality_suffix(quality)
    if bass:
        absolute_bass = _bass_note(root, bass, "b" in key or "b" in root)
        bass_pitch = _pitch(absolute_bass)
        if bass_pitch is not None:
            label += "/" + _SHARP_NAMES[(bass_pitch + transpose) % 12]
        else:
            label += "/" + absolute_bass
    return label


def chord_to_degree(chord: str, key: str) -> str:
    """Convert a chord to numbered notation, using relative major for minor keys."""
    chord_match = re.match(r"^([A-G][#b]?)(?::([^/]+))?(?:/([^/]+))?$", chord.strip())
    if chord_match is None:
        return chord if chord != "N" else ""
    try:
        tonic, _prefer_flats = _degree_key_details(key)
    except ValueError:
        return chord
    root = _degree(chord_match.group(1), tonic)
    suffix = _quality_suffix(chord_match.group(2) or "maj")
    bass = chord_match.group(3)
    if bass:
        bass = _degree(_bass_note(chord_match.group(1), bass, "b" in key), tonic)
        return f"{root}{suffix}/{bass}"
    return f"{root}{suffix}"
