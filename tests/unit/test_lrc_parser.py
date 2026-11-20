# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

import pytest

from dxband.creation.lrc_parser import LrcParser
from dxband.creation.lyric_text_parser import parse_lyric_text


def test_english_lrc_skips_timed_blanks_and_chinese_translations(tmp_path: Path) -> None:
    lrc = tmp_path / "bilingual.lrc"
    lrc.write_text(
        "[00:03.00]   \n"
        "[00:14.00]The snow glows white\n"
        "[00:17.00]皑皑白雪\n"
        "[00:17.00]Not a footprint to be seen\n"
        "[00:21.00]Hello（你好）world\n",
        encoding="utf-8",
    )

    parsed = LrcParser().parse(lrc, "Let It Go", "en", 30_000)

    assert [(line.start_ms, line.text) for line in parsed.document.lines] == [
        (14_000, "The snow glows white"),
        (17_000, "Not a footprint to be seen"),
        (21_000, "Hello world"),
    ]
    assert parsed.conflicts == ()


def test_chinese_lrc_keeps_chinese_lyrics(tmp_path: Path) -> None:
    lrc = tmp_path / "chinese.lrc"
    lrc.write_text("[00:01.00]中文歌词\n", encoding="utf-8")

    parsed = LrcParser().parse(lrc, "歌名", "zh", 3_000)

    assert [line.text for line in parsed.document.lines] == ["中文歌词"]


def test_text_only_lrc_keeps_file_order_when_timestamps_are_wrong(tmp_path: Path) -> None:
    lrc = tmp_path / "wrong-times.lrc"
    lrc.write_text(
        "[ti:歌名]\n[03:30.00]第一句\n[02:00.00]第二句\n[04:50.00]第三句\n",
        encoding="utf-8",
    )

    document = LrcParser().parse_text_only(lrc, "歌名", "zh", 240_000)

    assert [line.text for line in document.lines] == ["第一句", "第二句", "第三句"]
    assert [line.start_ms for line in document.lines] == [0, 80_000, 160_000]


def test_instrumental_labels_are_not_sung_lyric_text(tmp_path: Path) -> None:
    lrc = tmp_path / "with-markers.lrc"
    lrc.write_text(
        "[00:00.00]（前奏）\n[00:31.00]第一句\n[01:03.00]（间奏）\n[01:25.00]第二句\n",
        encoding="utf-8",
    )

    from_lrc = LrcParser().parse_text_only(lrc, "歌名", "zh", 100_000)
    from_text = parse_lyric_text("（前奏）\n第一句\n（间奏）\n第二句", "歌名", "zh", 100_000)

    assert [line.text for line in from_lrc.lines] == ["第一句", "第二句"]
    assert [line.text for line in from_text.lines] == ["第一句", "第二句"]


def test_song_credits_are_removed_before_creating_lyrics(tmp_path: Path) -> None:
    lrc = tmp_path / "credits.lrc"
    lrc.write_text(
        "[00:00.00]去有风的地方 (《去有风的地方》电视剧主题曲) - 郁可唯\n"
        "[00:04.00]词：汪拾米\n"
        "[00:05.00]曲：汪拾米\n"
        "[00:05.00]编曲：何山\n"
        "[00:05.00]制作人：金大洲D-Jin\n"
        "[00:06.00]项目统筹：刘晓倩\n"
        "[00:06.00]吉他：Andrew Synowiec/D-Jin\n"
        "[00:06.00]弦乐：国际首席爱乐乐团\n"
        "[00:07.00]小提琴：颜柯/张浩\n"
        "[00:08.00]中提琴：毕芳\n"
        "[00:08.00]大提琴：郎莹\n"
        "[00:08.00]弦乐录音：王小四@金田录音棚\n"
        "[00:09.00]弦乐监制：胡静宸\n"
        "[00:09.00]合声编写/合声：走走\n"
        "[00:09.00]人声录音：于文豪@D-Jin Music Studio\n"
        "[00:10.00]人声编辑：D-Jin/张德龙@D-Jin Music Studio\n"
        "[00:10.00]混音/母带处理：George Dum\n"
        "[00:11.00]制作统筹：黄宇弘\n"
        "[00:12.00]OP：D-Jin Music\n"
        "[00:13.00]发行：华策音乐（天津）有限公司\n"
        "[00:17.00]听落雨掉进寂静的森林\n"
        "[00:24.00]看夕阳之下远山的风景\n",
        encoding="utf-8",
    )

    parser = LrcParser()
    text_only = parser.parse_text_only(lrc, "去有风的地方", "zh", 30_000)
    timed = parser.parse(lrc, "去有风的地方", "zh", 30_000)

    assert [line.text for line in text_only.lines] == [
        "听落雨掉进寂静的森林",
        "看夕阳之下远山的风景",
    ]
    assert [(line.start_ms, line.text) for line in timed.document.lines] == [
        (17_000, "听落雨掉进寂静的森林"),
        (24_000, "看夕阳之下远山的风景"),
    ]


def test_lyric_with_colon_is_not_treated_as_credit(tmp_path: Path) -> None:
    lrc = tmp_path / "dialogue.lrc"
    lrc.write_text(
        "[00:00.00]歌名\n[00:02.00]你说：等我回来\n",
        encoding="utf-8",
    )

    document = LrcParser().parse_text_only(lrc, "歌名", "zh", 10_000)

    assert [line.text for line in document.lines] == ["你说：等我回来"]


def test_english_lrc_filters_chinese_credit_before_stripping_chinese(tmp_path: Path) -> None:
    lrc = tmp_path / "english-credits.lrc"
    lrc.write_text(
        "[00:00.00]制作人：John Smith\n[00:05.00]Hello world\n",
        encoding="utf-8",
    )

    parser = LrcParser()
    assert [line.text for line in parser.parse_text_only(lrc, "Song", "en", 10_000).lines] == [
        "Hello world"
    ]
    assert [line.text for line in parser.parse(lrc, "Song", "en", 10_000).document.lines] == [
        "Hello world"
    ]


@pytest.mark.parametrize(
    ("title", "heading", "lyric"),
    [
        ("夜机-陈慧娴", "夜机 - 陈慧娴 (Priscilla Chan)", "回头再看 微微灯光"),
        ("傻女-陈慧娴", "傻女 (Album Version) - 陈慧娴", "这夜我又再独对夜半"),
        ("两个人的幸运-电影原声", "梁咏琪 - 两个人的幸运", "明明像两点水"),
    ],
)
def test_title_card_is_filtered_when_song_title_contains_artist_or_version(
    tmp_path: Path, title: str, heading: str, lyric: str
) -> None:
    lrc = tmp_path / "title-card.lrc"
    lrc.write_text(f"[00:00.00]{heading}\n[00:16.00]{lyric}\n", encoding="utf-8")

    parser = LrcParser()
    assert [line.text for line in parser.parse_text_only(lrc, title, "zh", 30_000).lines] == [lyric]
    timed = parser.parse(lrc, title, "zh", 30_000)
    assert [(line.start_ms, line.text) for line in timed.document.lines] == [(16_000, lyric)]


def test_variant_credit_labels_are_filtered(tmp_path: Path) -> None:
    lrc = tmp_path / "more-credits.lrc"
    credits = [
        "配唱制作：常石磊",
        "人声录音师：赵靖/倪涵文",
        "人声录音棚：薛峰工作室",
        "贝斯：韩阳",
        "鼓：武勇恒",
        "录音师：李杨",
        "录音棚：55TEC Studio",
        "乐队监制：李超/彭华锐",
        "弦乐录音棚：九紫天诚",
        "弦乐编写/监制：李超/吴应特",
        "乐谱：彭华锐",
        "主唱：汤令山",
        "词Lyrics：黄伟文 Wyman Wong",
        "曲Composer：汤令山 Gareth.T",
        "编曲Arrangement：汤令山 Gareth.T",
        "监制Producer：汤令山 Gareth.T",
        "配唱制作人 Vocal Producer：HINS CHEUNG",
        "音乐编辑 Vocal Edited by：HINS CHEUNG",
        "和声编写及和声 Backing Vocal and Arrangement：刘祖德",
        "录音师 Recording Engineer：HINS CHEUNG",
        "录音室 Recording Studio：Avon Recording Studios",
        "混音 Mixed by：RICHARD FURCH",
    ]
    lrc.write_text(
        "".join(f"[00:{index:02d}.00]{credit}\n" for index, credit in enumerate(credits))
        + "[00:25.00]有人放烟花 有人追晚风\n",
        encoding="utf-8",
    )

    parser = LrcParser()
    assert [line.text for line in parser.parse_text_only(lrc, "歌名", "zh", 30_000).lines] == [
        "有人放烟花 有人追晚风"
    ]
    assert [line.text for line in parser.parse(lrc, "歌名", "zh", 30_000).document.lines] == [
        "有人放烟花 有人追晚风"
    ]
