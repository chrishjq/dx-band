# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Serve a local, audio-synchronized view of raw Beat This! and SheetSage2 output.

Example:
    python scripts/preview_raw_score.py song.mp3 --analysis-dir /path/to/raw --analyze

The viewer reads events.json and beat_this.json directly. It never imports the
package's reconciled melody or rhythm_comparison.json.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
from statistics import median
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
PAGE = ROOT / "src" / "dxband" / "resources" / "raw_score_preview" / "index.html"
APP_DISPLAY_PORTS = {8765, 8766}


class PreviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self, audio: Path, analysis_dir: Path, port: int,
        *, bpm: float | None = None, meter: str = "4/4",
        lyrics_json: Path | None = None, lyrics_lrc: Path | None = None,
        asr_json: Path | None = None,
    ) -> None:
        if port in APP_DISPLAY_PORTS:
            raise ValueError(
                f"端口 {port} 已保留给 DX Band 乐手屏或歌手屏；"
                "调试预览请使用 --port 0 或其他独立端口"
            )
        self.audio = audio
        self.analysis_dir = analysis_dir
        self.bpm = bpm
        self.meter = meter
        self.lyrics_json = lyrics_json
        self.lyrics_lrc = lyrics_lrc
        self.asr_json = asr_json
        self.fun_asr_json = analysis_dir / "fun_asr_preview" / "raw_asr.json"
        if not self.fun_asr_json.is_file():
            self.fun_asr_json = analysis_dir / "fun_asr" / "raw_asr.json"
        self.files = {
            "/raw/vocal_pitch/notes.json": analysis_dir / "vocal_pitch_preview" / "notes.json",
            "/raw/sheetsage2/events.json": analysis_dir / "sheetsage2" / "events.json",
            "/raw/sheetsage2_vocals_only/events.json": (
                analysis_dir / "sheetsage2_vocals_only" / "events.json"
            ),
            "/raw/sheetsage2_instrumental/events.json": (
                analysis_dir / "sheetsage2_instrumental" / "events.json"
            ),
            "/raw/beat_this/beat_this.json": analysis_dir / "beat_this" / "beat_this.json",
            "/raw/librosa/analysis.json": analysis_dir / "librosa_preview" / "analysis.json",
        }
        super().__init__(("127.0.0.1", port), PreviewHandler)


class PreviewHandler(BaseHTTPRequestHandler):
    server: PreviewServer

    def do_HEAD(self) -> None:
        self._handle(head_only=True)

    def do_GET(self) -> None:
        self._handle(head_only=False)

    def _handle(self, *, head_only: bool) -> None:
        path = urlsplit(self.path).path
        if path == "/":
            self._send_bytes(PAGE.read_bytes(), "text/html; charset=utf-8", head_only)
        elif path == "/api/meta":
            self._send_bytes(
                json.dumps({
                    "title": self.server.audio.stem,
                    "audio_file": self.server.audio.name,
                    "bpm": self.server.bpm,
                    "meter": self.server.meter,
                    "sources": {
                        "sheetsage2": self.server.files["/raw/sheetsage2/events.json"].is_file(),
                        "sheetsage2_vocals_only": self.server.files[
                            "/raw/sheetsage2_vocals_only/events.json"
                        ].is_file(),
                        "sheetsage2_instrumental": self.server.files[
                            "/raw/sheetsage2_instrumental/events.json"
                        ].is_file(),
                        "beat_this": self.server.files["/raw/beat_this/beat_this.json"].is_file(),
                        "lyrics_json": bool(self.server.lyrics_json and self.server.lyrics_json.is_file()),
                        "lyrics_lrc": bool(self.server.lyrics_lrc and self.server.lyrics_lrc.is_file()),
                        "asr_json": bool(self.server.asr_json and self.server.asr_json.is_file()),
                        "fun_asr_json": self.server.fun_asr_json.is_file(),
                        "vocal_pitch": self.server.files["/raw/vocal_pitch/notes.json"].is_file(),
                        "librosa": self.server.files["/raw/librosa/analysis.json"].is_file(),
                    },
                }, ensure_ascii=False).encode(),
                "application/json; charset=utf-8", head_only,
            )
        elif path in self.server.files:
            file = self.server.files[path]
            if file.is_file():
                self._send_file(file, "application/json; charset=utf-8", head_only)
            else:
                self.send_error(404, f"Raw model output is missing: {file.name}")
        elif path == "/raw/lyrics.json" and self.server.lyrics_json:
            self._send_file(self.server.lyrics_json, "application/json; charset=utf-8", head_only)
        elif path == "/raw/lyrics.lrc" and self.server.lyrics_lrc:
            self._send_file(self.server.lyrics_lrc, "text/plain; charset=utf-8", head_only)
        elif path == "/raw/asr.json" and self.server.asr_json:
            self._send_file(self.server.asr_json, "application/json; charset=utf-8", head_only)
        elif path == "/raw/fun_asr.json":
            self._send_file(self.server.fun_asr_json, "application/json; charset=utf-8", head_only)
        elif path == "/audio":
            self._send_file(
                self.server.audio,
                mimetypes.guess_type(self.server.audio.name)[0] or "application/octet-stream",
                head_only,
                allow_range=True,
            )
        else:
            self.send_error(404)

    def _send_bytes(self, data: bytes, content_type: str, head_only: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def _send_file(
        self, file: Path, content_type: str, head_only: bool, *, allow_range: bool = False
    ) -> None:
        if not file.is_file():
            self.send_error(404)
            return
        size = file.stat().st_size
        first, last = 0, size - 1
        byte_range = self.headers.get("Range") if allow_range else None
        if byte_range:
            try:
                unit, bounds = byte_range.split("=", 1)
                start_text, end_text = bounds.split("-", 1)
                if unit != "bytes" or "," in bounds or not (start_text or end_text):
                    raise ValueError
                if start_text:
                    first = int(start_text)
                    last = min(size - 1, int(end_text)) if end_text else size - 1
                else:
                    first = max(0, size - int(end_text))
                if first < 0 or first > last or first >= size:
                    raise ValueError
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        length = last - first + 1
        self.send_response(206 if byte_range else 200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        if allow_range:
            self.send_header("Accept-Ranges", "bytes")
        if byte_range:
            self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
        self.end_headers()
        if head_only:
            return
        with file.open("rb") as stream:
            stream.seek(first)
            remaining = length
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)

    def log_message(self, format: str, *args: object) -> None:
        if not self.path.startswith("/api/"):
            super().log_message(format, *args)


def ensure_analysis(audio: Path, analysis_dir: Path) -> None:
    from dxband.creation.beat_this_runner import BeatThisRunner
    from dxband.creation.cancellation import CancellationToken
    from dxband.creation.sheetsage2_runner import SheetSage2Runner

    cancellation = CancellationToken()
    if not (analysis_dir / "sheetsage2" / "events.json").is_file():
        print("分析 SheetSage2 原始数据……", flush=True)
        SheetSage2Runner().run(audio, analysis_dir / "sheetsage2", cancellation)
    if not (analysis_dir / "beat_this" / "beat_this.json").is_file():
        print("分析 Beat This! 原始数据……", flush=True)
        BeatThisRunner().run(audio, analysis_dir / "beat_this", cancellation)


def generate_asr_preview(vocals: Path, analysis_dir: Path, language: str) -> Path:
    """Save uncorrected CTC greedy tokens and their frame-derived times."""
    if language != "yue":
        raise ValueError("当前预览的自由 ASR 解码只支持粤语人声模型")
    import librosa
    import torch
    from transformers import AutoModelForCTC, AutoProcessor

    from dxband.creation.ctc_lyrics_aligner import LrcCtcAligner, YUE_REPOSITORY

    root = LrcCtcAligner(language=language)._model_root()
    processor = AutoProcessor.from_pretrained(str(root), local_files_only=True)
    model = AutoModelForCTC.from_pretrained(str(root), local_files_only=True).eval()
    samples, _ = librosa.load(str(vocals), sr=16_000, mono=True)
    blank = processor.tokenizer.pad_token_id
    chunks: list[dict[str, object]] = []
    tokens: list[dict[str, object]] = []
    chunk_samples = 15 * 16_000
    with torch.inference_mode():
        for offset in range(0, len(samples), chunk_samples):
            sample_chunk = samples[offset:offset + chunk_samples]
            inputs = processor(sample_chunk, sampling_rate=16_000, return_tensors="pt")
            ids = model(**inputs).logits[0].argmax(-1).cpu().tolist()
            start_s = offset / 16_000
            end_s = (offset + len(sample_chunk)) / 16_000
            chunks.append({"start_s": start_s, "end_s": end_s,
                           "text": processor.decode(ids)})
            frame_s = (end_s - start_s) / len(ids)
            index = 0
            while index < len(ids):
                last = index + 1
                while last < len(ids) and ids[last] == ids[index]:
                    last += 1
                if ids[index] != blank:
                    tokens.append({
                        "start_s": round(start_s + index * frame_s, 4),
                        "end_s": round(start_s + last * frame_s, 4),
                        "token": processor.tokenizer.convert_ids_to_tokens(ids[index]),
                        "token_id": ids[index],
                    })
                index = last
    output = analysis_dir / "asr_preview" / "raw_asr.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "schema_version": 1, "model": YUE_REPOSITORY, "language": language,
        "method": "uncorrected_ctc_greedy_decode_on_separated_vocals",
        "time_basis": "ctc_output_frames", "chunks": chunks, "tokens": tokens,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def generate_lyric_preview(
    audio: Path, vocals: Path, lrc: Path, analysis_dir: Path, language: str,
) -> Path:
    """Run the current acoustic and score-link aligners without editing a song package."""
    from dxband.creation.ctc_lyrics_aligner import LrcCtcAligner
    from dxband.creation.lrc_parser import LrcParser
    from dxband.creation.score_lyric_alignment import align_lyrics_to_score
    from dxband.models.melody import MelodyBar, MelodyDocument, MelodyNote
    from dxband.services.media_probe import MediaProbe

    duration_ms = MediaProbe().probe_audio(audio).duration_ms
    reference = LrcParser().parse_text_only(lrc, audio.stem, language, duration_ms)
    print("重新运行当前人声 CTC 歌词对齐……", flush=True)
    acoustic = LrcCtcAligner(language=language).align_document(reference, vocals)
    # The aligner pads every first character 350 ms before its acoustic CTC
    # peak. That helps a lyric line cover the attack, but using the padded
    # time to link notes can steal the previous line's sustained last note.
    # Keep the original result for comparison; use the peak as the phrase
    # onset when testing note-to-lyric links in this preview.
    peak_lines = []
    for line in acoustic.lines:
        first = line.words[0]
        peak_start = min(first.end_ms - 1, first.start_ms + 350)
        if peak_start <= first.start_ms:
            peak_lines.append(line)
            continue
        peak_lines.append(line.model_copy(update={
            "start_ms": peak_start,
            "words": [first.model_copy(update={"start_ms": peak_start}), *line.words[1:]],
        }))
    peak_acoustic = acoustic.model_copy(update={"lines": peak_lines})

    raw = json.loads((analysis_dir / "sheetsage2" / "events.json").read_text())
    notes = []
    for event in raw.get("events", []):
        start_ms = round(float(event["time"]) * 1000)
        for note in event.get("values", {}).get("melody", []):
            end_ms = min(duration_ms, round(float(note["end_time"]) * 1000))
            if 0 <= start_ms < end_ms - 80:
                notes.append(MelodyNote(
                    start_ms=start_ms, end_ms=end_ms, midi=int(note["pitch"]),
                    source="vocals" if int(note["track"]) == 0 else "other",
                    evidence=["sheetsage2"],
                ))
    notes.sort(key=lambda note: (note.start_ms, note.midi))
    beats = json.loads((analysis_dir / "beat_this" / "beat_this.json").read_text()).get("beats_s", [])
    intervals = [right - left for left, right in zip(beats, beats[1:]) if 0.3 <= right - left <= 1.5]
    if not intervals or not notes:
        raise ValueError("缺少 Beat This! 拍点或 SheetSage2 音符，无法重新对齐歌词")
    beat_ms = round(median(intervals) * 1000)
    start_ms = max(0, round(float(beats[0]) * 1000))
    bar = MelodyBar(
        start_ms=start_ms, end_ms=start_ms + 4 * beat_ms,
        beat_times_ms=[start_ms + index * beat_ms for index in range(4)],
    )
    melody = MelodyDocument(tonic_midi=60, coverage_end_ms=duration_ms,
                            notes=notes, bars=[bar])
    print("使用 SheetSage2 原始音符运行当前字音关联……", flush=True)
    aligned, linked = align_lyrics_to_score(peak_acoustic, melody)
    payload = aligned.model_dump(mode="json")
    payload["acoustic_lines"] = acoustic.model_dump(mode="json")["lines"]
    payload["peak_acoustic_lines"] = peak_acoustic.model_dump(mode="json")["lines"]
    payload["linked_notes"] = [
        {"start_ms": note.start_ms, "line_id": note.lyric_line_id,
         "character_index": note.lyric_character_index}
        for note in linked.notes if note.lyric_line_id is not None
    ]
    payload["preview_method"] = "ctc_phrase_peaks_and_score_link_from_raw_notes"
    output = analysis_dir / "lyric_preview" / "lyrics.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def relink_lyric_preview_to_vocals_only(audio: Path, analysis_dir: Path) -> Path:
    """Reuse preview acoustic evidence, linking known lyrics to the solo-vocal score."""
    from dxband.creation.score_lyric_alignment import align_lyrics_to_score
    from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming
    from dxband.models.melody import MelodyBar, MelodyDocument, MelodyNote
    from dxband.services.media_probe import MediaProbe

    base = json.loads((analysis_dir / "lyric_preview" / "lyrics.json").read_text())
    source = json.loads((analysis_dir / "sheetsage2_vocals_only" / "events.json").read_text())
    acoustic = LyricsDocument.model_validate({
        key: base[key] for key in ("schema_version", "title", "language", "timing_mode")
    } | {"lines": base["peak_acoustic_lines"]})
    duration_ms = MediaProbe().probe_audio(audio).duration_ms
    notes = []
    for event in source.get("events", []):
        start_ms = round(float(event["time"]) * 1000)
        for note in event.get("values", {}).get("melody", []):
            if int(note["track"]) != 0:
                continue
            end_ms = min(duration_ms, round(float(note["end_time"]) * 1000))
            if 0 <= start_ms < end_ms - 80:
                notes.append(MelodyNote(
                    start_ms=start_ms, end_ms=end_ms, midi=int(note["pitch"]),
                    source="vocals", evidence=["sheetsage2"],
                ))
    notes.sort(key=lambda note: (note.start_ms, note.midi))
    beats = json.loads((analysis_dir / "beat_this" / "beat_this.json").read_text()).get("beats_s", [])
    intervals = [right - left for left, right in zip(beats, beats[1:]) if 0.3 <= right - left <= 1.5]
    if not intervals or not notes:
        raise ValueError("缺少 Beat This! 拍点或纯人声 SheetSage2 音符")
    beat_ms = round(median(intervals) * 1000)
    start_ms = max(0, round(float(beats[0]) * 1000))
    bar = MelodyBar(start_ms=start_ms, end_ms=start_ms + 4 * beat_ms,
                    beat_times_ms=[start_ms + index * beat_ms for index in range(4)])
    melody = MelodyDocument(tonic_midi=60, coverage_end_ms=duration_ms,
                            notes=notes, bars=[bar])
    aligned, linked = align_lyrics_to_score(acoustic, melody)
    links = {
        (note.lyric_line_id, note.lyric_character_index): note.start_ms
        for note in linked.notes if note.lyric_line_id is not None
    }
    proposed = []
    for line in aligned.lines:
        cursor = 0
        starts = []
        for word in line.words:
            index = line.text.find(word.text, cursor)
            if index < 0:
                raise ValueError(f"歌词逐字顺序异常：{line.text}")
            starts.append(links.get((line.id, index), word.start_ms))
            cursor = index + len(word.text)
        proposed.append(starts)
    all_starts = [start for starts in proposed for start in starts]
    note_anchors_usable = all(right > left for left, right in zip(all_starts, all_starts[1:]))
    if note_anchors_usable:
        retimed_lines = []
        for index, (line, starts) in enumerate(zip(aligned.lines, proposed, strict=True)):
            following = proposed[index + 1][0] if index + 1 < len(proposed) else duration_ms
            end_ms = min(max(line.end_ms, starts[-1] + 1), following)
            words = [WordTiming(text=word.text, start_ms=start,
                                end_ms=starts[offset + 1] if offset + 1 < len(starts) else end_ms)
                     for offset, (word, start) in enumerate(zip(line.words, starts, strict=True))]
            retimed_lines.append(LyricLine(id=line.id, start_ms=starts[0], end_ms=end_ms,
                                           text=line.text, words=words))
        aligned = LyricsDocument(schema_version=aligned.schema_version, title=aligned.title,
                                 language=aligned.language, timing_mode=aligned.timing_mode,
                                 lines=retimed_lines)
    payload = aligned.model_dump(mode="json")
    payload["acoustic_lines"] = base["acoustic_lines"]
    payload["peak_acoustic_lines"] = base["peak_acoustic_lines"]
    payload["linked_notes"] = [
        {"start_ms": note.start_ms, "line_id": note.lyric_line_id,
         "character_index": note.lyric_character_index}
        for note in linked.notes if note.lyric_line_id is not None
    ]
    payload["preview_method"] = "ctc_phrase_peaks_and_score_link_from_vocals_only_notes"
    payload["vocal_note_anchored_words"] = len(links) if note_anchors_usable else 0
    output = analysis_dir / "lyric_preview" / "lyrics_vocals_only.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def export_standalone(
    audio: Path, analysis_dir: Path, destination: Path, *, bpm: float | None, meter: str,
    lyrics_json: Path | None = None, lyrics_lrc: Path | None = None,
    asr_json: Path | None = None,
) -> None:
    """Write one file with the original audio and both raw model outputs embedded."""
    beat = json.loads((analysis_dir / "beat_this" / "beat_this.json").read_text())
    sheet = json.loads((analysis_dir / "sheetsage2" / "events.json").read_text())
    instrumental_file = analysis_dir / "sheetsage2_instrumental" / "events.json"
    vocals_only_file = analysis_dir / "sheetsage2_vocals_only" / "events.json"
    instrumental_sheet = (
        json.loads(instrumental_file.read_text()) if instrumental_file.is_file() else None
    )
    vocals_only_sheet = (
        json.loads(vocals_only_file.read_text()) if vocals_only_file.is_file() else None
    )
    aligned_lyrics = json.loads(lyrics_json.read_text()) if lyrics_json and lyrics_json.is_file() else None
    source_lrc = lyrics_lrc.read_text() if lyrics_lrc and lyrics_lrc.is_file() else None
    raw_asr = json.loads(asr_json.read_text()) if asr_json and asr_json.is_file() else None
    fun_asr_file = analysis_dir / "fun_asr_preview" / "raw_asr.json"
    if not fun_asr_file.is_file():
        fun_asr_file = analysis_dir / "fun_asr" / "raw_asr.json"
    fun_asr = json.loads(fun_asr_file.read_text()) if fun_asr_file.is_file() else None
    vocal_pitch_file = analysis_dir / "vocal_pitch_preview" / "notes.json"
    vocal_pitch = json.loads(vocal_pitch_file.read_text()) if vocal_pitch_file.is_file() else None
    librosa_file = analysis_dir / "librosa_preview" / "analysis.json"
    librosa_data = json.loads(librosa_file.read_text()) if librosa_file.is_file() else None
    payload = json.dumps({
        "meta": {"title": audio.stem, "audio_file": audio.name, "bpm": bpm, "meter": meter},
        "beat": beat, "sheet": sheet, "instrumental_sheet": instrumental_sheet,
        "vocals_only_sheet": vocals_only_sheet,
        "aligned_lyrics": aligned_lyrics, "source_lrc": source_lrc,
        "raw_asr": raw_asr, "fun_asr": fun_asr, "vocal_pitch": vocal_pitch,
        "librosa": librosa_data,
    }, ensure_ascii=False).replace("<", "\\u003c")
    mime = mimetypes.guess_type(audio.name)[0] or "application/octet-stream"
    audio_url = f"data:{mime};base64,{base64.b64encode(audio.read_bytes()).decode('ascii')}"
    html = PAGE.read_text().replace('src="/audio"', f'src="{audio_url}"', 1)
    if 'src="/audio"' in html:
        raise ValueError("The preview page audio element was not embedded")
    html = html.replace(
        "<script>\n  const $",
        f'<script id="embedded-preview" type="application/json">{payload}</script>'
        '\n<script>\n  const $',
        1,
    )
    if '<script id="embedded-preview"' not in html:
        raise ValueError("The raw preview data was not embedded")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path, help="Original MP3/WAV/M4A audio file")
    parser.add_argument("--analysis-dir", type=Path, help="Directory containing model subfolders")
    parser.add_argument("--analyze", action="store_true", help="Generate missing raw outputs first")
    parser.add_argument("--port", type=int, default=0, help="Loopback port; 0 chooses a free port")
    parser.add_argument("--bpm", type=float, help="Reference BPM; preview also compares half and double tempo")
    parser.add_argument("--meter", choices=("2/4", "3/4", "4/4", "6/8"), default="4/4")
    parser.add_argument("--align-lyrics", action="store_true", help="Regenerate preview-only lyric timing with the current aligners")
    parser.add_argument("--relink-vocals-only", action="store_true", help="Relink cached preview lyrics to solo-vocal SheetSage2 notes")
    parser.add_argument("--transcribe-asr", action="store_true", help="Decode uncorrected ASR tokens from the separated vocals")
    parser.add_argument("--vocals", type=Path, help="Separated vocal audio for fresh lyric alignment")
    parser.add_argument("--language", choices=("zh", "yue", "en"), default="zh")
    parser.add_argument("--lyrics-lrc", type=Path, help="Original line-timed LRC; auto-detected beside the audio if omitted")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser")
    parser.add_argument("--export-html", type=Path, help="Write a standalone offline preview HTML")
    args = parser.parse_args()
    if args.port in APP_DISPLAY_PORTS:
        parser.error(
            f"端口 {args.port} 已保留给 DX Band 乐手屏或歌手屏；"
            "调试预览请使用 --port 0 或其他独立端口"
        )
    audio = args.audio.expanduser().resolve()
    if not audio.is_file():
        parser.error(f"audio file does not exist: {audio}")
    analysis_dir = (
        args.analysis_dir or audio.parent / f".{audio.stem}-raw-analysis"
    ).expanduser().resolve()
    if args.analyze:
        ensure_analysis(audio, analysis_dir)
    if args.bpm is not None and args.bpm <= 0:
        parser.error("--bpm must be positive")
    lyrics_json = analysis_dir / "lyric_preview" / "lyrics.json"
    matching_lrc = sorted(audio.parent.glob(f"{audio.stem}*.lrc"))
    lyrics_lrc = args.lyrics_lrc.expanduser().resolve() if args.lyrics_lrc else (
        matching_lrc[0] if matching_lrc else None
    )
    if lyrics_lrc and not lyrics_lrc.is_file():
        parser.error(f"LRC file does not exist: {lyrics_lrc}")
    if args.align_lyrics:
        if not lyrics_lrc or not args.vocals:
            parser.error("--align-lyrics requires an LRC and --vocals")
        vocals = args.vocals.expanduser().resolve()
        if not vocals.is_file():
            parser.error(f"vocal track does not exist: {vocals}")
        lyrics_json = generate_lyric_preview(audio, vocals, lyrics_lrc, analysis_dir, args.language)
    if args.relink_vocals_only:
        relink_lyric_preview_to_vocals_only(audio, analysis_dir)
    vocals_only_lyrics = analysis_dir / "lyric_preview" / "lyrics_vocals_only.json"
    if vocals_only_lyrics.is_file():
        lyrics_json = vocals_only_lyrics
    asr_json = analysis_dir / "qwen_asr_preview" / "raw_asr.json"
    if not asr_json.is_file():
        asr_json = analysis_dir / "asr_preview" / "raw_asr.json"
    if args.transcribe_asr:
        if not args.vocals:
            parser.error("--transcribe-asr requires --vocals")
        vocals = args.vocals.expanduser().resolve()
        if not vocals.is_file():
            parser.error(f"vocal track does not exist: {vocals}")
        print("运行人声自由 ASR 解码……", flush=True)
        asr_json = generate_asr_preview(vocals, analysis_dir, args.language)
    if not lyrics_json.is_file():
        lyrics_json = None
    if args.export_html is not None:
        destination = args.export_html.expanduser().resolve()
        export_standalone(audio, analysis_dir, destination, bpm=args.bpm, meter=args.meter,
                          lyrics_json=lyrics_json, lyrics_lrc=lyrics_lrc, asr_json=asr_json)
        print(f"原始曲谱离线预览：{destination}", flush=True)
        if not args.no_open:
            webbrowser.open(destination.as_uri())
        return
    server = PreviewServer(audio, analysis_dir, args.port, bpm=args.bpm, meter=args.meter,
                           lyrics_json=lyrics_json, lyrics_lrc=lyrics_lrc, asr_json=asr_json)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"原始曲谱预览：{url}", flush=True)
    if not args.no_open:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
