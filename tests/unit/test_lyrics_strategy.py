# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from opencc import OpenCC

from dxband.creation.ctc_lyrics_aligner import LrcCtcAligner, _alignment_character
from dxband.creation.lyrics_strategy import timing_language
from dxband.models.lyric import LyricLine, LyricsDocument


def _document(text: str) -> LyricsDocument:
    return LyricsDocument(
        schema_version=1,
        title="测试",
        language="und",
        timing_mode="line",
        lines=[LyricLine(id="line-0001", start_ms=0, end_ms=10_000, text=text)],
    )


def test_explicit_languages_select_their_own_acoustic_backend() -> None:
    document = _document("你好世界")
    assert timing_language("zh-CN", document) == "zh"
    assert timing_language("yue", document) == "yue"
    assert timing_language("en", document) == "en"


def test_auto_language_uses_lrc_script() -> None:
    assert timing_language("auto", _document("你好世界")) == "zh"
    assert timing_language("auto", _document("Hello world")) == "en"


def test_auto_language_uses_first_sung_line_in_bilingual_lrc() -> None:
    document = LyricsDocument(
        schema_version=1,
        title="Let It Go",
        language="und",
        timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=0, end_ms=3000,
                      text="Let It Go - Idina Menzel"),
            LyricLine(id="line-0002", start_ms=3000, end_ms=14000,
                      text="Lyricist：Robert Lopez"),
            LyricLine(id="line-0003", start_ms=14000, end_ms=17000,
                      text="The snow glows white"),
            LyricLine(id="line-0004", start_ms=17000, end_ms=21000,
                      text="皑皑白雪 / Not a footprint"),
        ],
    )

    assert timing_language("auto", document) == "en"


def test_credit_lines_are_excluded_from_acoustic_alignment() -> None:
    aligner = LrcCtcAligner()
    assert aligner._is_credit("词：张三", "珊瑚颂")
    assert aligner._is_credit("歌手 - 珊瑚颂", "珊瑚颂")
    assert aligner._is_credit("Lyricist：Robert Lopez", "Let It Go")
    assert aligner._is_credit("Composer: Kristen Anderson-Lopez", "Let It Go")
    assert aligner._is_credit("Producer：Robert Lopez", "Let It Go")
    assert aligner._is_credit("Let It Go", "Let It Go", 0)
    assert not aligner._is_credit("Let It Go", "Let It Go", 60_000)
    assert not aligner._is_credit("一树红花照碧海", "珊瑚颂")


def test_ctc_blank_id_uses_the_models_actual_padding_token() -> None:
    assert LrcCtcAligner._blank_id({"[PAD]": 0, "字": 7}) == 0
    assert LrcCtcAligner._blank_id({"<pad>": 0, "a": 7}) == 0
    assert LrcCtcAligner._blank_id({"字": 7, " ": 8}) == 8


def test_cantonese_interjection_uses_supported_alignment_character() -> None:
    vocabulary = {"喔": 1, "我": 2}
    convert = OpenCC("s2t")
    assert _alignment_character("呵", "yue", vocabulary, convert) == "喔"
    assert _alignment_character("我", "yue", vocabulary, convert) == "我"
    assert _alignment_character("呵", "zh", vocabulary, convert) is None
    assert _alignment_character("呵", "yue", {"我": 2}, convert) is None
