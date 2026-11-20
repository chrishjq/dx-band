# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path

import pytest

from dxband.analysis.sheetsage2_package import SheetSage2Analysis
from dxband.constants import TRACK_FILENAMES, TrackKind
from dxband.creation.cancellation import CancellationToken
from dxband.creation.input_validator import ValidatedCreationInput
from dxband.creation.package_builder import PackageBuilder
from dxband.creation.pipeline import CreationPipeline
from dxband.creation.stem_validator import StemInfo, StemValidationResult
from dxband.models.chord import ChordSegment, ChordTimeline
from dxband.models.creation_job import CreateSongRequest, CreationJobState
from dxband.models.melody import MelodyBar, MelodyDocument, MelodyNote
from dxband.services.media_probe import AudioMediaInfo
from dxband.workers.protocol import ResultEvent


class _AvailableEnvironment:
    @staticmethod
    def inspect():
        return type(
            "Status",
            (),
            {
                "ffmpeg_available": True,
                "demucs_available": True,
                "ctc_segmentation_available": True,
            },
        )()

    @staticmethod
    def select_torch_device(_preference: str = "auto") -> str:
        return "cpu"


class _FakeInputValidator:
    @staticmethod
    def validate(request: CreateSongRequest, _destination: Path) -> ValidatedCreationInput:
        return ValidatedCreationInput(
            request=request,
            media=AudioMediaInfo(
                path=request.source_mp3,
                codec="mp3",
                duration_ms=10_000,
                sample_rate_hz=44_100,
                channels=2,
                bit_rate=320_000,
                size_bytes=request.source_mp3.stat().st_size,
            ),
            lrc_encoding="utf-8" if request.lrc_path is not None else None,
        )


class _FakeWorkerClient:
    def __init__(self, track_root: Path) -> None:
        self.track_root = track_root
        self.calls = 0

    def run(self, _command, _cancellation, _on_event) -> ResultEvent:
        self.calls += 1
        return ResultEvent(
            path=str(self.track_root),
            data={"version": "测试版", "device": "cpu"},
        )


class _FakeStemValidator:
    @staticmethod
    def validate(track_root: Path) -> StemValidationResult:
        tracks = {
            track: StemInfo(
                kind=track,
                path=track_root / TRACK_FILENAMES[track],
                sample_rate_hz=44_100,
                channels=2,
                decoded_frames=441_000,
                duration_ms=10_000,
                sha256=str(index) * 64,
            )
            for index, track in enumerate(TrackKind, start=1)
        }
        return StemValidationResult(
            sample_rate_hz=44_100,
            channels=2,
            canonical_frames=441_000,
            duration_ms=10_000,
            tracks=tracks,
        )


class _FakeScoreRunner:
    @staticmethod
    def check_ready() -> None:
        return

    @staticmethod
    def run(_source: Path, output: Path, _cancellation: CancellationToken) -> Path:
        output.mkdir(parents=True)
        return output


class _FakeBeatRunner:
    @staticmethod
    def check_ready() -> None:
        return

    @staticmethod
    def run(_source: Path, output: Path, _cancellation: CancellationToken) -> Path:
        output.mkdir(parents=True)
        (output / "beat_this.json").write_text("{}")
        return output


def _fake_score(
    _output: Path, _duration: int, _beat_this_output: Path | None = None,
    _source_sha256: str | None = None,
    **_kwargs: object,
) -> SheetSage2Analysis:
    return SheetSage2Analysis(
        original_key="C",
        bpm=120,
        beat_times_ms=list(range(0, 10_000, 500)),
        downbeat_times_ms=list(range(0, 10_000, 2_000)),
        beats_per_bar=4,
        chords=ChordTimeline(segments=[ChordSegment(start_ms=500, end_ms=2_000, chord="C:maj")]),
        melody=MelodyDocument(
            tonic_midi=60,
            coverage_end_ms=10_000,
            notes=[
                MelodyNote(start_ms=start, end_ms=start + 100, midi=60, source="vocals")
                for start in (*range(0, 1_000, 100), *range(5_000, 6_000, 100))
            ],
            bars=[
                MelodyBar(
                    start_ms=start,
                    end_ms=start + 2_000,
                    beat_times_ms=list(range(start, start + 2_000, 500)),
                )
                for start in range(0, 10_000, 2_000)
            ],
        ),
    )


class _FakeLyricAligner:
    def __init__(self, language: str = "zh") -> None:
        self.calls = 0
        self.language = language

    def align_document(self, document, _vocals_path):
        from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming

        self.calls += 1
        lines = []
        for line in document.lines:
            words = [
                WordTiming(
                    text=char,
                    start_ms=line.start_ms + index * 100,
                    end_ms=line.start_ms + (index + 1) * 100,
                )
                for index, char in enumerate(char for char in line.text if not char.isspace())
            ]
            lines.append(
                LyricLine(
                    id=line.id,
                    start_ms=line.start_ms,
                    end_ms=line.end_ms,
                    text=line.text,
                    words=words,
                )
            )
        return LyricsDocument(
            schema_version=1,
            title=document.title,
            language=self.language,
            timing_mode="word",
            lines=lines,
        )


class _FakeAsrRunner:
    def run(
        self, _vocals: Path, output: Path, _cancellation: CancellationToken,
        *, language: str,
    ) -> Path:
        output.mkdir(parents=True, exist_ok=True)
        path = output / "raw_asr.json"
        tokens = [
            {"token": char, "start_s": base + index * 0.1}
            for base, line in ((0, "第一句"), (5, "第二句"))
            for index, char in enumerate(line)
        ]
        path.write_text(json.dumps({"tokens": tokens}, ensure_ascii=False), encoding="utf-8")
        return path


def _patch_score_readers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dxband.creation.pipeline.read_beat_led_analysis", _fake_score)
    monkeypatch.setattr(
        "dxband.creation.song_analysis.read_beat_led_analysis", _fake_score
    )


class _AcceptingPackageValidator:
    @staticmethod
    def validate(_root: Path) -> None:
        return


@pytest.mark.parametrize(
    "language, code", [
        ("zh-CN", "zh"), ("yue", "yue"), ("en", "en"),
        ("auto", "en"), ("auto", "zh"),
    ]
)
def test_lrc_creation_pipeline_uses_acoustic_alignment_for_all_languages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str, code: str
) -> None:
    library = tmp_path / "library"
    source = tmp_path / "source.mp3"
    source.write_bytes(b"fake mp3")
    lrc = tmp_path / "source.lrc"
    lyric_lines = ("First line", "Second line") if code == "en" else ("第一句", "第二句")
    if code == "en":
        lrc.write_text(
            f"[00:00.000]{lyric_lines[0]}\n"
            "[00:05.000]中文翻译\n"
            f"[00:05.000]{lyric_lines[1]}\n"
            "[00:08.000]   \n",
            encoding="utf-8",
        )
    else:
        lrc.write_text(
            f"[00:00.000]{lyric_lines[0]}\n[00:05.000]{lyric_lines[1]}\n",
            encoding="utf-8",
        )
    track_root = tmp_path / "fake-stems"
    track_root.mkdir()
    for filename in TRACK_FILENAMES.values():
        (track_root / filename).write_bytes(b"fake stem")

    pipeline = CreationPipeline(library)
    worker = _FakeWorkerClient(track_root)
    lyric_aligner = _FakeLyricAligner(code)
    monkeypatch.setattr(
        "dxband.creation.pipeline.LrcCtcAligner",
        lambda language: lyric_aligner,
    )
    pipeline.input_validator = _FakeInputValidator()  # type: ignore[assignment]
    pipeline.environment = _AvailableEnvironment()  # type: ignore[assignment]
    pipeline.worker_client = worker  # type: ignore[assignment]
    pipeline.lyric_aligner = lyric_aligner  # type: ignore[assignment]
    pipeline.stem_validator = _FakeStemValidator()  # type: ignore[assignment]
    pipeline.score_runner = _FakeScoreRunner()  # type: ignore[assignment]
    pipeline.beat_runner = _FakeBeatRunner()  # type: ignore[assignment]
    pipeline.asr_runner = _FakeAsrRunner()  # type: ignore[assignment]
    _patch_score_readers(monkeypatch)
    events: list[tuple[str, str]] = []

    job = pipeline.run_to_draft(
        CreateSongRequest(
            source_mp3=source,
            lrc_path=lrc,
            title="测试歌曲",
            artist="测试歌手",
            language=language,
        ),
        CancellationToken(),
        lambda event, message: events.append((event, message)),
    )

    assert job.state == CreationJobState.AWAITING_LYRIC_REVIEW
    assert job.lyrics_source == "lrc"
    assert job.lyrics_draft_path is not None and job.lyrics_draft_path.is_file()
    assert worker.calls == 1
    assert lyric_aligner.calls == (1 if code == "en" else 0)
    if code == "en":
        assert job.request.lrc_path is not None
        assert "中文翻译" in job.request.lrc_path.read_text(encoding="utf-8")
        assert "中文翻译" in lrc.read_text(encoding="utf-8")
    from dxband.models.lyric import LyricsDocument

    lyrics = LyricsDocument.model_validate_json(job.lyrics_draft_path.read_bytes())
    assert lyrics.timing_mode == "word"
    assert lyrics.language == code
    assert [line.text for line in lyrics.lines] == list(lyric_lines)
    assert [line.start_ms for line in lyrics.lines] == [0, 5000]
    assert any(event == ("stage", "正在对齐歌词时间") for event in events)
    assert ("stage", "正在生成整曲简谱") in events
    assert ("stage", "正在核对节奏和小节") in events
    assert events[-1] == ("stage", "歌词与逐字时间已自动生成并校正")

    job = pipeline.finalize_generated_lyrics(job, lyrics)
    builder = PackageBuilder(library)
    builder.validator = _AcceptingPackageValidator()  # type: ignore[assignment]
    destination = builder.build(
        job,
        CancellationToken(),
        lambda event, message: events.append((event, message)),
    )

    assert destination == library / job.job_id
    assert (destination / "chords.json").is_file()
    assert (destination / "melody.json").is_file()
    chords = ChordTimeline.model_validate_json((destination / "chords.json").read_bytes())
    assert chords.segments[0].chord == "C:maj"
    assert any("正在读取 LRC 歌词文字" in event[1] for event in events)
    assert events[-1] == ("stage", f"歌曲包已提交到 {destination}")


def test_wav_and_text_lyrics_creation_reaches_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = tmp_path / "library"
    source = tmp_path / "source.wav"
    source.write_bytes(b"fake wav")
    track_root = tmp_path / "fake-stems"
    track_root.mkdir()
    for filename in TRACK_FILENAMES.values():
        (track_root / filename).write_bytes(b"fake stem")

    pipeline = CreationPipeline(library)
    aligner = _FakeLyricAligner("zh")
    pipeline.input_validator = _FakeInputValidator()  # type: ignore[assignment]
    pipeline.environment = _AvailableEnvironment()  # type: ignore[assignment]
    pipeline.worker_client = _FakeWorkerClient(track_root)  # type: ignore[assignment]
    pipeline.lyric_aligner = aligner  # type: ignore[assignment]
    pipeline.stem_validator = _FakeStemValidator()  # type: ignore[assignment]
    pipeline.score_runner = _FakeScoreRunner()  # type: ignore[assignment]
    pipeline.beat_runner = _FakeBeatRunner()  # type: ignore[assignment]
    pipeline.asr_runner = _FakeAsrRunner()  # type: ignore[assignment]
    _patch_score_readers(monkeypatch)
    events: list[tuple[str, str]] = []

    job = pipeline.run_to_draft(
        CreateSongRequest(source_mp3=source, lyrics_text="第一句\n\n第二句", title="测试歌曲"),
        CancellationToken(),
        lambda event, message: events.append((event, message)),
    )

    assert job.lyrics_source == "text"
    assert job.original_source_filename == "source.wav"
    assert job.request.source_mp3.name == "source.wav"
    assert job.original_lrc_filename is None
    assert aligner.calls == 0
    assert job.lyrics_draft_path is not None
    from dxband.models.lyric import LyricsDocument

    lyrics = LyricsDocument.model_validate_json(job.lyrics_draft_path.read_bytes())
    assert [line.text for line in lyrics.lines] == ["第一句", "第二句"]
    assert ("stage", "正在对齐歌词时间") in events

    job = pipeline.finalize_generated_lyrics(job, lyrics)
    builder = PackageBuilder(library)
    builder.validator = _AcceptingPackageValidator()  # type: ignore[assignment]
    destination = builder.build(job)

    from dxband.models.song import SongConfig

    config = SongConfig.model_validate_json((destination / "song.json").read_bytes())
    assert config.source.original_filename == "source.wav"
    assert config.source.lrc_filename is None
    assert config.lyrics.source == "text"
