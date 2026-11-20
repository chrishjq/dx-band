# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import http.client
import json

from dxband.models.lyric import LyricsDocument
from dxband.services.web_singer_server import WebSingerServer, build_web_singer_song


def test_web_singer_streams_lyrics_without_token() -> None:
    server = WebSingerServer()
    server.start(preferred_port=0)
    server.set_song({"title": "测试", "lines": [{"text": "第一句"}]})
    server.set_singer_display(offset_ms=150, font_size=42, music_info_visible=False)
    assert server.port is not None
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == 200
        assert "DX Band 歌手屏" in response.read().decode()
        assert "token=" not in server.url

        connection.request("GET", "/events")
        response = connection.getresponse()
        assert response.status == 200
        assert response.readline() == b"event: snapshot\n"
        snapshot = json.loads(response.readline().removeprefix(b"data: "))
        assert snapshot["song"]["lines"][0]["text"] == "第一句"
        assert snapshot["display"] == {
            "offset_ms": 150,
            "font_size": 42,
            "music_info_visible": False,
        }
    finally:
        connection.close()
        server.stop()


def test_web_singer_song_uses_display_lyrics() -> None:
    lyrics = LyricsDocument.model_validate({
        "schema_version": 1,
        "title": "测试",
        "language": "zh-CN",
        "timing_mode": "line",
        "lines": [{"id": "line-0001", "start_ms": 2000, "end_ms": 4000, "text": "第一句"}],
    })
    song = build_web_singer_song(
        lyrics, title="测试", artist="歌手", original_key="C", bpm=120
    )
    assert song["lines"][0]["text"] == "（前奏）"
    assert song["lines"][1]["text"] == "第一句"
