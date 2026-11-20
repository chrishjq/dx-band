# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Callable

from PySide6.QtGui import QUndoCommand

from dxband.lyrics.word_timing_edit import retime_edited_text
from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming


class LyricsEditError(ValueError):
    pass


class ReplaceLyricsCommand(QUndoCommand):
    def __init__(
        self,
        description: str,
        before: LyricsDocument,
        after: LyricsDocument,
        apply_document: Callable[[LyricsDocument], None],
    ) -> None:
        super().__init__(description)
        self.before = before
        self.after = after
        self.apply_document = apply_document

    def redo(self) -> None:
        self.apply_document(self.after)

    def undo(self) -> None:
        self.apply_document(self.before)


class LyricsEditor:
    def __init__(self, duration_ms: int) -> None:
        self.duration_ms = duration_ms

    def replace_text(self, document: LyricsDocument, row: int, text: str) -> LyricsDocument:
        text = text.strip()
        if not text:
            raise LyricsEditError("歌词文本不能为空")
        lines = list(document.lines)
        line = lines[row]
        try:
            words = retime_edited_text(line, text)
        except ValueError as exc:
            raise LyricsEditError(str(exc)) from exc
        lines[row] = line.model_copy(update={"text": text, "words": words})
        return self._document(document, lines)

    def replace_timing(
        self,
        document: LyricsDocument,
        row: int,
        start_ms: int,
        end_ms: int,
    ) -> LyricsDocument:
        if start_ms < 0 or end_ms <= start_ms or end_ms > self.duration_ms:
            raise LyricsEditError("歌词时间超出歌曲范围或起止时间无效")
        if row > 0 and start_ms < document.lines[row - 1].end_ms:
            raise LyricsEditError("当前行与上一行重叠")
        if row + 1 < len(document.lines) and end_ms > document.lines[row + 1].start_ms:
            raise LyricsEditError("当前行与下一行重叠")
        lines = list(document.lines)
        line = lines[row]
        start_delta_ms = start_ms - line.start_ms
        end_delta_ms = end_ms - line.end_ms
        shifted_words: list[WordTiming] = []
        for word in line.words:
            shifted_words.append(
                word.model_copy(
                    update={
                        "start_ms": word.start_ms + start_delta_ms,
                        "end_ms": word.end_ms + end_delta_ms,
                    }
                )
            )
        try:
            lines[row] = line.model_copy(
                update={"start_ms": start_ms, "end_ms": end_ms, "words": shifted_words}
            )
            return self._document(document, lines)
        except ValueError:
            lines[row] = line.model_copy(
                update={"start_ms": start_ms, "end_ms": end_ms, "words": []}
            )
            return self._document(document, lines)

    def split_line(self, document: LyricsDocument, row: int) -> LyricsDocument:
        line = document.lines[row]
        split_ms = line.start_ms + (line.end_ms - line.start_ms) // 2
        text = line.text.strip()
        split_index = max(1, len(text) // 2)
        left_text = text[:split_index].strip()
        right_text = text[split_index:].strip()
        if not left_text or not right_text or split_ms <= line.start_ms:
            raise LyricsEditError("当前行太短，无法自动拆分")
        lines = list(document.lines)
        lines[row : row + 1] = [
            LyricLine(
                id="line-0001",
                start_ms=line.start_ms,
                end_ms=split_ms,
                text=left_text,
                words=[],
            ),
            LyricLine(
                id="line-0002",
                start_ms=split_ms,
                end_ms=line.end_ms,
                text=right_text,
                words=[],
            ),
        ]
        return self._document(document, lines)

    def merge_with_previous(self, document: LyricsDocument, row: int) -> LyricsDocument:
        if row <= 0:
            raise LyricsEditError("第一行没有上一行")
        return self._merge(document, row - 1, row)

    def merge_with_next(self, document: LyricsDocument, row: int) -> LyricsDocument:
        if row + 1 >= len(document.lines):
            raise LyricsEditError("最后一行没有下一行")
        return self._merge(document, row, row + 1)

    def apply_offset_from_row(
        self, document: LyricsDocument, row: int, offset_ms: int
    ) -> LyricsDocument:
        if row < 0 or row >= len(document.lines):
            raise LyricsEditError("请先选择有效的歌词行")
        return self._apply_offset(document, row, offset_ms, "从当前行起偏移")

    def _apply_offset(
        self,
        document: LyricsDocument,
        first_row: int,
        offset_ms: int,
        operation_name: str,
    ) -> LyricsDocument:
        if not offset_ms:
            return document
        lines = list(document.lines[:first_row])
        for line in document.lines[first_row:]:
            start_ms = line.start_ms + offset_ms
            end_ms = line.end_ms + offset_ms
            if start_ms < 0 or end_ms > self.duration_ms:
                raise LyricsEditError(f"{operation_name}会使歌词超出歌曲范围")
            words = [
                word.model_copy(
                    update={
                        "start_ms": word.start_ms + offset_ms,
                        "end_ms": word.end_ms + offset_ms,
                    }
                )
                for word in line.words
            ]
            lines.append(
                line.model_copy(update={"start_ms": start_ms, "end_ms": end_ms, "words": words})
            )
        try:
            return self._document(document, lines)
        except ValueError as exc:
            if first_row > 0 and lines[first_row].start_ms < lines[first_row - 1].end_ms:
                raise LyricsEditError(f"{operation_name}会与上一句重叠") from exc
            raise LyricsEditError(f"{operation_name}后的歌词时间无效") from exc

    def _merge(self, document: LyricsDocument, first_row: int, second_row: int) -> LyricsDocument:
        first = document.lines[first_row]
        second = document.lines[second_row]
        merged = LyricLine(
            id="line-0001",
            start_ms=first.start_ms,
            end_ms=second.end_ms,
            text=f"{first.text} {second.text}".strip(),
            words=[],
        )
        lines = list(document.lines)
        lines[first_row : second_row + 1] = [merged]
        return self._document(document, lines)

    @staticmethod
    def _document(
        source: LyricsDocument,
        lines: list[LyricLine],
    ) -> LyricsDocument:
        normalized = [
            line.model_copy(update={"id": f"line-{index + 1:04d}"})
            for index, line in enumerate(lines)
        ]
        payload = source.model_dump(mode="python")
        payload["timing_mode"] = "word" if all(line.words for line in normalized) else "line"
        payload["lines"] = [line.model_dump(mode="python") for line in normalized]
        return LyricsDocument.model_validate(
            payload,
            strict=True,
        )
