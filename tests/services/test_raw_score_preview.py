# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""The raw-model preview must serve the original audio and untouched model files."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from scripts.preview_raw_score import PreviewServer, export_standalone


@pytest.mark.parametrize("port", [8765, 8766])
def test_preview_rejects_application_display_ports(tmp_path: Path, port: int) -> None:
    with pytest.raises(ValueError, match="已保留给 DX Band"):
        PreviewServer(tmp_path / "song.mp3", tmp_path / "analysis", port)


def test_preview_serves_original_files_and_seekable_audio(tmp_path: Path) -> None:
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"0123456789")
    analysis = tmp_path / "analysis"
    (analysis / "sheetsage2").mkdir(parents=True)
    (analysis / "sheetsage2_instrumental").mkdir()
    (analysis / "sheetsage2_vocals_only").mkdir()
    (analysis / "beat_this").mkdir()
    (analysis / "librosa_preview").mkdir()
    events = b'{"events":[{"time":0.5}]}'
    instrumental_events = b'{"events":[{"time":0.6}]}'
    vocals_only_events = b'{"events":[{"time":0.7}]}'
    beats = b'{"beats_s":[0.5],"downbeats_s":[0.5]}'
    librosa_data = b'{"tempo_bpm":129.2,"beats_s":[0.47]}'
    lyrics = b'{"lines":[{"text":"test"}]}'
    lrc = b'[00:00.50]test'
    (analysis / "sheetsage2" / "events.json").write_bytes(events)
    (analysis / "sheetsage2_instrumental" / "events.json").write_bytes(instrumental_events)
    (analysis / "sheetsage2_vocals_only" / "events.json").write_bytes(vocals_only_events)
    (analysis / "beat_this" / "beat_this.json").write_bytes(beats)
    (analysis / "librosa_preview" / "analysis.json").write_bytes(librosa_data)
    (analysis / "lyric_preview").mkdir()
    (analysis / "lyric_preview" / "lyrics.json").write_bytes(lyrics)
    (analysis / "asr_preview").mkdir()
    raw_asr = b'{"tokens":[{"start_s":0.5,"token":"x"}]}'
    (analysis / "asr_preview" / "raw_asr.json").write_bytes(raw_asr)
    (analysis / "source.lrc").write_bytes(lrc)
    server = PreviewServer(audio, analysis, 0, bpm=63, meter="4/4",
                           lyrics_json=analysis / "lyric_preview" / "lyrics.json",
                           lyrics_lrc=analysis / "source.lrc",
                           asr_json=analysis / "asr_preview" / "raw_asr.json")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/") as response:
            assert b"SheetSage2" in response.read()
        with urlopen(base + "/api/meta") as response:
            meta = json.load(response)
            assert meta["bpm"] == 63
            assert meta["meter"] == "4/4"
            assert meta["sources"] == {
                "sheetsage2": True, "sheetsage2_instrumental": True,
                "sheetsage2_vocals_only": True,
                "beat_this": True, "lyrics_json": True, "lyrics_lrc": True,
                "asr_json": True, "fun_asr_json": False, "vocal_pitch": False,
                "librosa": True,
            }
        with urlopen(base + "/raw/lyrics.json") as response:
            assert response.read() == lyrics
        with urlopen(base + "/raw/lyrics.lrc") as response:
            assert response.read() == lrc
        with urlopen(base + "/raw/asr.json") as response:
            assert response.read() == raw_asr
        with urlopen(base + "/raw/sheetsage2/events.json") as response:
            assert response.read() == events
        with urlopen(base + "/raw/beat_this/beat_this.json") as response:
            assert response.read() == beats
        with urlopen(base + "/raw/librosa/analysis.json") as response:
            assert response.read() == librosa_data
        with urlopen(base + "/raw/sheetsage2_instrumental/events.json") as response:
            assert response.read() == instrumental_events
        with urlopen(base + "/raw/sheetsage2_vocals_only/events.json") as response:
            assert response.read() == vocals_only_events
        with urlopen(Request(base + "/audio", headers={"Range": "bytes=3-6"})) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == "bytes 3-6/10"
            assert response.read() == b"3456"
        try:
            urlopen(Request(base + "/audio", headers={"Range": "bytes=99-"}))
        except HTTPError as error:
            assert error.code == 416
        else:
            raise AssertionError("invalid audio range was accepted")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_standalone_preview_embeds_original_data(tmp_path: Path) -> None:
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"original audio")
    analysis = tmp_path / "analysis"
    (analysis / "sheetsage2").mkdir(parents=True)
    (analysis / "sheetsage2_instrumental").mkdir()
    (analysis / "sheetsage2_vocals_only").mkdir()
    (analysis / "beat_this").mkdir()
    (analysis / "librosa_preview").mkdir()
    (analysis / "sheetsage2" / "events.json").write_text('{"events":[{"time":0.5}]}')
    (analysis / "sheetsage2_instrumental" / "events.json").write_text(
        '{"events":[{"time":0.6}]}'
    )
    (analysis / "sheetsage2_vocals_only" / "events.json").write_text(
        '{"events":[{"time":0.7}]}'
    )
    (analysis / "beat_this" / "beat_this.json").write_text(
        '{"beats_s":[0.5],"downbeats_s":[0.5]}'
    )
    (analysis / "librosa_preview" / "analysis.json").write_text(
        '{"tempo_bpm":129.2,"beats_s":[0.47]}'
    )
    (analysis / "lyric_preview").mkdir()
    (analysis / "lyric_preview" / "lyrics.json").write_text('{"lines":[{"text":"新词"}]}')
    (analysis / "asr_preview").mkdir()
    (analysis / "asr_preview" / "raw_asr.json").write_text(
        '{"tokens":[{"start_s":0.5,"token":"声"}]}'
    )
    lrc = tmp_path / "source.lrc"
    lrc.write_text('[00:00.50]新词')
    destination = tmp_path / "preview.html"
    export_standalone(audio, analysis, destination, bpm=63, meter="4/4",
                      lyrics_json=analysis / "lyric_preview" / "lyrics.json", lyrics_lrc=lrc,
                      asr_json=analysis / "asr_preview" / "raw_asr.json")
    page = destination.read_text()
    assert 'src="data:audio/mpeg;base64,b3JpZ2luYWwgYXVkaW8="' in page
    assert '"downbeats_s": [0.5]' in page
    assert '"vocals_only_sheet": {"events": [{"time": 0.7}]}' in page
    assert '"events": [{"time": 0.5}]' in page
    assert '"instrumental_sheet": {"events": [{"time": 0.6}]}' in page
    assert '"bpm": 63' in page
    assert '"meter": "4/4"' in page
    assert '"aligned_lyrics": {"lines": [{"text": "新词"}]}' in page
    assert '"source_lrc": "[00:00.50]新词"' in page
    assert '"raw_asr": {"tokens": [{"start_s": 0.5, "token": "声"}]}' in page
    assert '"librosa": {"tempo_bpm": 129.2, "beats_s": [0.47]}' in page
