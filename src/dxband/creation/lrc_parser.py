# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import re
from dataclasses import dataclass
from pathlib import Path

from dxband.creation.lyric_text_parser import parse_lyric_text
from dxband.lyrics.metadata import is_lyric_metadata
from dxband.models.lyric import LyricLine, LyricsDocument

_TIMESTAMP_PATTERN = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_METADATA_PATTERN = re.compile(r"^\[([A-Za-z]+):(.*)\]$")
_HAN_PATTERN = re.compile(r"[\u3400-\u9fff]")
_HAN_AND_CJK_PUNCTUATION = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uff65]+")


class LrcParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LrcConflict:
    start_ms: int
    source_lines: tuple[int, ...]
    texts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LrcParseResult:
    document: LyricsDocument
    encoding: str
    metadata: dict[str, str]
    conflicts: tuple[LrcConflict, ...]


class LrcParser:
    def parse_text_only(
        self, path: Path, title: str, language: str, duration_ms: int
    ) -> LyricsDocument:
        """Read lyrics in file order, using timestamps only to identify an intro title."""
        source, _encoding = self._read_text(path)
        phrases: list[str] = []
        english = language.strip().lower().replace("_", "-").split("-", 1)[0] == "en"
        for raw_line in source.splitlines():
            line = raw_line.strip()
            if not line or _METADATA_PATTERN.fullmatch(line):
                continue
            if not _TIMESTAMP_PATTERN.search(line):
                if line.startswith(("#", ";", "//")):
                    continue
                raise LrcParseError(f"无法解析 LRC 歌词行：{line}")
            timestamp = _TIMESTAMP_PATTERN.search(line)
            phrase = _TIMESTAMP_PATTERN.sub("", line).strip()
            if timestamp and is_lyric_metadata(phrase, title, self._timestamp_to_ms(timestamp, 0)):
                continue
            if english and _HAN_PATTERN.search(phrase):
                phrase = " ".join(_HAN_AND_CJK_PUNCTUATION.sub(" ", phrase).split())
            if phrase:
                phrases.append(phrase)
        return parse_lyric_text("\n".join(phrases), title, language, duration_ms)

    def parse(
        self,
        path: Path,
        title: str,
        language: str,
        duration_ms: int,
    ) -> LrcParseResult:
        text, encoding = self._read_text(path)
        metadata: dict[str, str] = {}
        raw_entries: list[tuple[int, str, int]] = []
        invalid_lines: list[int] = []
        offset_ms = 0
        english = language.strip().lower().replace("_", "-").split("-", 1)[0] == "en"

        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            metadata_match = _METADATA_PATTERN.fullmatch(line)
            if metadata_match and not _TIMESTAMP_PATTERN.search(line):
                key = metadata_match.group(1).lower()
                value = metadata_match.group(2).strip()
                metadata[key] = value
                if key == "offset":
                    try:
                        offset_ms = int(value)
                    except ValueError as exc:
                        raise LrcParseError(f"第 {line_number} 行 offset 不是整数") from exc
                continue

            timestamps = list(_TIMESTAMP_PATTERN.finditer(line))
            if not timestamps:
                if line.startswith(("#", ";", "//")):
                    continue
                invalid_lines.append(line_number)
                continue
            start_times = [
                self._timestamp_to_ms(timestamp, line_number) for timestamp in timestamps
            ]
            lyric_text = _TIMESTAMP_PATTERN.sub("", line).strip()
            if not lyric_text:
                continue  # A timed blank line marks a pause between verses.
            if all(is_lyric_metadata(lyric_text, title, start_ms) for start_ms in start_times):
                continue
            if english and _HAN_PATTERN.search(lyric_text):
                lyric_text = " ".join(_HAN_AND_CJK_PUNCTUATION.sub(" ", lyric_text).split())
                if not lyric_text or not any(char.isalpha() for char in lyric_text):
                    continue  # Chinese translation, not an English vocal line.
            for start_ms in start_times:
                if not is_lyric_metadata(lyric_text, title, start_ms):
                    raw_entries.append((start_ms, lyric_text, line_number))

        if invalid_lines:
            numbers = "、".join(str(number) for number in invalid_lines)
            raise LrcParseError(f"以下非空行无法解析：{numbers}")
        if not raw_entries:
            raise LrcParseError("LRC 中没有有效时间戳歌词")

        grouped: dict[int, list[tuple[str, int]]] = {}
        for start_ms, lyric_text, line_number in raw_entries:
            adjusted_ms = max(0, start_ms + offset_ms)
            if adjusted_ms > duration_ms:
                continue
            grouped.setdefault(adjusted_ms, []).append((lyric_text, line_number))
        if not grouped:
            raise LrcParseError("全部歌词时间戳都超出歌曲时长")

        conflicts: list[LrcConflict] = []
        normalized: list[tuple[int, str]] = []
        for start_ms in sorted(grouped):
            entries = grouped[start_ms]
            unique_texts = list(dict.fromkeys(text for text, _line in entries))
            if len(unique_texts) > 1:
                conflicts.append(
                    LrcConflict(
                        start_ms=start_ms,
                        source_lines=tuple(line for _text, line in entries),
                        texts=tuple(unique_texts),
                    )
                )
            normalized.append((start_ms, " / ".join(unique_texts)))

        lines: list[LyricLine] = []
        for index, (start_ms, lyric_text) in enumerate(normalized):
            next_start_ms = normalized[index + 1][0] if index + 1 < len(normalized) else duration_ms
            end_ms = max(start_ms + 1, min(next_start_ms, duration_ms))
            lines.append(
                LyricLine(
                    id=f"line-{index + 1:04d}",
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=lyric_text,
                    words=[],
                )
            )

        document = LyricsDocument(
            schema_version=1,
            title=title,
            language=language if language != "auto" else "und",
            timing_mode="line",
            lines=lines,
        )
        return LrcParseResult(
            document=document,
            encoding=encoding,
            metadata=metadata,
            conflicts=tuple(conflicts),
        )

    @staticmethod
    def _read_text(path: Path) -> tuple[str, str]:
        data = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        raise LrcParseError("LRC 编码无法识别")

    @staticmethod
    def _timestamp_to_ms(match: re.Match[str], line_number: int) -> int:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        if seconds >= 60:
            raise LrcParseError(f"第 {line_number} 行秒数必须小于 60")
        fraction = match.group(3) or "0"
        fraction_ms = int(fraction.ljust(3, "0")[:3])
        return minutes * 60_000 + seconds * 1000 + fraction_ms
