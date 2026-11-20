# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Correct ASR characters from supplied lyrics without moving recognized onsets."""

from __future__ import annotations

from typing import Any, cast

from opencc import OpenCC

from dxband.lyrics.instrumental_markers import instrumental_marker_label
from dxband.lyrics.metadata import is_lyric_metadata
from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming


def correct_asr_lyrics(
    reference: LyricsDocument, tokens: list[dict[str, Any]], duration_ms: int,
) -> LyricsDocument:
    """Use ASR for time and user lyrics for text, with monotone character matching.

    The LRC time is deliberately ignored.  Missing ASR characters are placed
    between their recognized neighbors; recognized character starts stay put.
    """
    convert = OpenCC("t2s")
    lines = [line for line in reference.lines if not (
        is_lyric_metadata(line.text, reference.title, line.start_ms)
        or instrumental_marker_label(line)
    )]
    units = [(line, index, char) for line in lines
             for index, char in enumerate(line.text) if char.isalnum()]
    recognized = [token for token in tokens if len(str(token.get("token", ""))) == 1
                  and str(token["token"]).isalnum() and token.get("start_s") is not None]
    recognized.sort(key=lambda token: float(token["start_s"]))
    if not units or not recognized:
        raise ValueError("ASR 没有可用于校正的逐字时间")
    left = [str(convert.convert(char)).casefold() for _, _, char in units]
    right = [str(convert.convert(str(token["token"]))).casefold()
             for token in recognized]
    count, total = len(left), len(right)
    prior = [index * .62 for index in range(total + 1)]
    choices = [bytearray(total + 1) for _ in range(count + 1)]
    for i in range(1, count + 1):
        current = [i * .62]
        choices[i][0] = 1
        for j in range(1, total + 1):
            cost, action = prior[j] + .62, 1
            if current[j - 1] + .62 < cost:
                cost, action = current[j - 1] + .62, 2
            paired = prior[j - 1] + (0 if left[i - 1] == right[j - 1] else .85)
            if paired <= cost:
                cost, action = paired, 3
            current.append(cost)
            choices[i][j] = action
        prior = current
    matched: dict[tuple[str, int], int] = {}
    i, j = count, total
    while i and j:
        action = choices[i][j]
        if action == 3:
            line, char_index, _ = units[i - 1]
            matched[line.id, char_index] = round(float(recognized[j - 1]["start_s"]) * 1000)
            i -= 1
            j -= 1
        elif action == 2:
            j -= 1
        else:
            i -= 1
    if len(matched) < max(3, round(len(units) * .45)):
        raise ValueError("ASR 与提供的歌词差异过大，无法可靠校正")
    global_times = [matched.get((line.id, index)) for line, index, _ in units]
    for index, time in enumerate(global_times):
        if time is not None:
            continue
        before = next((offset for offset in range(index - 1, -1, -1)
                       if global_times[offset] is not None), None)
        after = next((offset for offset in range(index + 1, len(global_times))
                      if global_times[offset] is not None), None)
        if before is not None and after is not None:
            fraction = (index - before) / (after - before)
            left_ms = cast(int, global_times[before])
            right_ms = cast(int, global_times[after])
            global_times[index] = round(left_ms + fraction * (right_ms - left_ms))
        elif before is not None:
            global_times[index] = cast(int, global_times[before]) + 120 * (index - before)
        else:
            assert after is not None
            global_times[index] = max(0, cast(int, global_times[after]) - 120 * (after - index))
    assembled = []
    offset = 0
    for line in lines:
        chars = [char for char in line.text if char.isalnum()]
        if not chars:
            continue
        raw_starts = [cast(int, value) for value in global_times[offset:offset + len(chars)]]
        offset += len(chars)
        starts: list[int] = []
        for time in raw_starts:
            starts.append(min(duration_ms - 1, max(starts[-1] + 1 if starts else 0, time)))
        assembled.append((line, chars, starts))
    result = []
    for index, (line, chars, starts) in enumerate(assembled):
        following = assembled[index + 1][2][0] if index + 1 < len(assembled) else duration_ms
        end = min(duration_ms, max(starts[-1] + 60, min(following, starts[-1] + 700)))
        if index + 1 < len(assembled):
            end = min(end, following)
        if end <= starts[-1]:
            end = starts[-1] + 1
        words = [WordTiming(
            text=char, start_ms=start,
            end_ms=starts[part + 1] if part + 1 < len(starts) else end,
        ) for part, (char, start) in enumerate(zip(chars, starts, strict=True))]
        result.append(LyricLine(id=line.id, start_ms=starts[0], end_ms=end,
                                text=line.text, words=words))
    return LyricsDocument(schema_version=1, title=reference.title,
                          language=reference.language, timing_mode="word", lines=result)
