# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import http.client
import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from dxband.resource_paths import WEB_MUSICIAN_ROOT
from dxband.services.web_musician_server import (
    WebMusicianServer,
    _RequestHandler,
)


@pytest.mark.parametrize(
    "error",
    [BrokenPipeError(), ConnectionResetError(), ConnectionAbortedError()],
)
def test_web_musician_handler_silences_expected_client_disconnects(
    monkeypatch: MonkeyPatch, error: OSError
) -> None:
    def disconnect(_handler: BaseHTTPRequestHandler) -> None:
        raise error

    monkeypatch.setattr(BaseHTTPRequestHandler, "handle", disconnect)
    handler = object.__new__(_RequestHandler)
    handler.close_connection = False

    handler.handle()

    assert handler.close_connection is True


def test_web_musician_server_streams_current_snapshot_without_token(
    tmp_path: Path,
) -> None:
    page = tmp_path / "index.html"
    page.write_text("<!doctype html><title>musician</title>", encoding="utf-8")
    server = WebMusicianServer(page)
    server.set_transport(state="playing", position_ms=1234)
    server.set_guide_countdown(6, 8)
    server.start(preferred_port=0)
    assert server.port is not None
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
    stream: http.client.HTTPResponse | None = None
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == 200
        assert b"musician" in response.read()
        assert "token=" not in server.url

        connection.request("GET", "/logo.png")
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type") == "image/png"
        assert response.read().startswith(b"\x89PNG\r\n\x1a\n")

        connection.request("GET", "/jianpurender.js")
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type") == "text/javascript; charset=utf-8"
        assert b"JianpuSVGRender" in response.read()

        connection.request("GET", "/events")
        stream = connection.getresponse()
        assert stream.status == 200
        assert stream.readline() == b"event: snapshot\n"
        data_line = stream.readline().decode().removeprefix("data: ")
        snapshot = json.loads(data_line)
        assert snapshot["transport"] == {"state": "playing", "position_ms": 1234}
        assert snapshot["guide"] == {"remaining": 6, "total": 8}
    finally:
        if stream is not None:
            stream.close()
        connection.close()
        server.stop()


def test_web_musician_server_reuses_running_session(tmp_path: Path) -> None:
    page = tmp_path / "index.html"
    page.write_text("ok", encoding="utf-8")
    server = WebMusicianServer(page)
    try:
        first = server.start(preferred_port=0)
        assert server.start(preferred_port=0) == first
        assert server.running
    finally:
        server.stop()
    assert not server.running


def test_multiple_browser_clients_can_subscribe(tmp_path: Path) -> None:
    page = tmp_path / "index.html"
    page.write_text("ok", encoding="utf-8")
    server = WebMusicianServer(page)
    clients = [server.subscribe(), server.subscribe(), server.subscribe(local=True)]
    assert len(set(clients)) == 3
    assert len(server._subscribers) == 3
    for client in clients:
        server.unsubscribe(client)
    assert not server._subscribers


def test_only_local_display_can_save_chord_mode(tmp_path: Path) -> None:
    page = tmp_path / "index.html"
    page.write_text("ok", encoding="utf-8")
    server = WebMusicianServer(page)
    selected: list[str] = []
    server.on_local_chord_mode = selected.append
    server.start(preferred_port=0)
    assert server.port is not None
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
    try:
        for path, body, expected in (
            ("/local-mode", b'{"mode":"chord"}', 403),
            ("/local-mode?local=1", b'{"mode":"invalid"}', 400),
            ("/local-mode?local=1", b'{"mode":"key:D"}', 200),
            ("/local-mode?local=1", b'{"mode":"key:H"}', 400),
        ):
            connection.request("POST", path, body=body)
            response = connection.getresponse()
            assert response.status == expected
            response.read()
        assert selected == ["key:D"]
        connection.request(
            "POST", "/local-mode?local=1", body=b'{"mode":"chord"}',
            headers={"Origin": "http://evil.example"},
        )
        response = connection.getresponse()
        assert response.status == 403
        response.read()
        assert selected == ["key:D"]
    finally:
        connection.close()
        server.stop()


def test_existing_event_url_works_after_server_restart(tmp_path: Path) -> None:
    page = tmp_path / "index.html"
    page.write_text("ok", encoding="utf-8")
    server = WebMusicianServer(page)
    server.start(preferred_port=0)
    port = server.port
    assert port is not None
    server.stop()

    replacement = WebMusicianServer(page)
    try:
        replacement.start(preferred_port=port)
        replacement.set_transport(state="playing", position_ms=900)
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.request("GET", "/events")
            response = connection.getresponse()
            assert response.status == 200
            assert response.readline() == b"event: snapshot\n"
            snapshot = json.loads(response.readline().removeprefix(b"data: "))
            assert snapshot["transport"]["position_ms"] == 900
        finally:
            connection.close()
    finally:
        replacement.stop()


def test_web_musician_page_omits_beat_lights_without_losing_score() -> None:
    page = (WEB_MUSICIAN_ROOT / "index.html").read_text(encoding="utf-8")

    assert 'id="beatLights"' not in page
    assert "cell.append(chords, lyrics)" in page
    assert "cell.append(chords, melody, lyrics)" in page
    assert "window.jr?.mapMidiToJianpu" in page
    assert "const drawMelodyBeams = (scope = elements.score) =>" in page
    assert "const drawMelodyTies = (scope = elements.score) =>" in page
    assert "line.className = 'melody-beam-line'" in page
    assert "color: #aeb5c0" in page
    assert "border-bottom: 1px solid #aeb5c0" in page
    assert "path.setAttribute('stroke', '#aeb5c0')" in page
    assert "#ff6b70" not in page
    assert "thirtysecond" not in page
    assert "beat-dot" not in page
    assert "renderBeatDots" not in page
    assert "#f4fffc" not in page
    assert "0 0 24px 9px" not in page
    assert "state.rows.forEach((row, rowIndex)" not in page
    assert "elements.stage.addEventListener('scroll', () => {" in page
    assert "scheduleVisibleScoreLayout();" in page
    assert "addEventListener('scroll', updateScrollRail" not in page
    assert "if (now - lastAnimationAt < 33) return" in page
    assert "if (window.innerWidth < 700 || window.innerHeight < 600) return 1;" in page
    assert "const widthLimit = usableWidth >= 4 * 145 * fontScale ? 4" in page
    assert "bars.length === barsPerRow" in page
    assert "Math.min(barsPerRow, 2)" not in page
    assert "beats: bars.flatMap((bar) => bar.beats)" in page
    assert "justify-self: center; width: max-content; text-align: center" in page
    assert "const fitLyricFont = () =>" in page
    assert "focus-band" not in page
    assert "const renderGuide = () =>" in page
    assert ".bar-measure.active" in page
    assert "rgba(255, 209, 102, .24)" in page
    assert ".score-row.active" not in page
    assert "opacity: .42" not in page
    assert ".score-row.past" not in page
    assert "min-height: 1.25em; color: #fff;" in page
    assert 'id="guide"' in page
    assert "source.addEventListener('guide'" in page
    assert '<img src="/logo.png" alt="DX Band">' in page
    assert "大象乐队工作站" in page
    assert "www.dx-band.site" in page
    assert 'class="pdf-watermarks"' in page
    assert page.count('class="pdf-watermark"') == 3
    assert 'role="group" aria-label="和弦显示调式"' in page
    assert page.count('class="chord-mode-option"') == 1
    assert 'data-chord-mode="degree"' in page
    assert 'id="chordKeySelect"' in page
    assert (
        "const displayKeys = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']"
        in page
    )
    assert "localStorage.setItem('dx-band-chord-mode', chordMode)" in page
    assert "item.chord_modes?.chord_c" in page
    assert ".chord-sup" in page
    assert "const chordSuperscriptIndices = (label) =>" in page
    assert "character === '#' || character === 'b'" in page
    assert "if (text[index] === '7') indices.add(index)" in page
    assert "character === '#' ? '♯' : character === 'b' ? '♭' : character" in page
    assert "renderChordLabels(chords, chordLabels(beat), ' · ')" in page
    assert 'class="header-controls"' in page
    assert 'class="brand-copy"' not in page
    assert "WEB MUSICIAN" not in page
    assert "grid-template-rows: auto auto" in page
    assert ".song-subtitle { margin-top: 2px; font-size: 11px; }" in page
    assert 'class="toolbar"' not in page
    assert 'id="wake"' not in page
    assert 'id="fullscreen"' in page
    assert 'id="chrome"' not in page
    assert "wakeLock" not in page
    assert "document.documentElement.requestFullscreen()" in page
    assert "document.exitFullscreen()" in page
    assert "简谱${scope}" not in page
    assert "melody_review_pending ? ' · 待复核'" not in page
    assert "chrome-hidden" not in page
    assert "const guideIsActive = () =>" in page
    assert "const progress = countInActive ? 0" in page
    assert "const progress = countInActive ? 0" in page
