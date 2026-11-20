# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Local-network singer display using the shared browser transport."""

from dxband.lyrics.instrumental_markers import with_instrumental_markers
from dxband.models.lyric import LyricsDocument
from dxband.resource_paths import WEB_SINGER_ROOT
from dxband.services.web_musician_server import WebMusicianServer


class WebSingerServer(WebMusicianServer):
    def __init__(self, *, language: str = "zh") -> None:
        super().__init__(WEB_SINGER_ROOT / "index.html", language=language)

    def start(self, preferred_port: int = 8766) -> str:
        return super().start(preferred_port)

    def set_singer_display(
        self, *, offset_ms: int, font_size: int, music_info_visible: bool
    ) -> None:
        self._set_and_publish(
            "display",
            {
                "offset_ms": offset_ms,
                "font_size": font_size,
                "music_info_visible": music_info_visible,
            },
        )


def build_web_singer_song(
    lyrics: LyricsDocument, *, title: str, artist: str, original_key: str, bpm: int
) -> dict[str, object]:
    display_lyrics = with_instrumental_markers(lyrics)
    return {
        "title": title,
        "artist": artist,
        "original_key": original_key,
        "bpm": bpm,
        "lines": [
            {
                "id": line.id,
                "start_ms": line.start_ms,
                "end_ms": line.end_ms,
                "text": line.text,
            }
            for line in display_lyrics.lines
        ],
    }
