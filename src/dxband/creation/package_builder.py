# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from dxband.analysis.beat_this_reconciliation import comparison_payload
from dxband.analysis.sheetsage2_package import SheetSage2Analysis
from dxband.constants import TRACK_FILENAMES, TrackKind
from dxband.creation.cancellation import CancellationToken
from dxband.creation.package_validator import SongPackageValidator
from dxband.creation.song_analysis import assemble_song_analysis
from dxband.creation.state_machine import CreationStateMachine
from dxband.creation.workspace import CreationWorkspace, JobLog
from dxband.models.creation_job import CreationJob, CreationJobState
from dxband.models.lyric import LyricsDocument
from dxband.models.song import (
    AudioConfig,
    LyricsConfig,
    MusicalConfig,
    SeparationConfig,
    SongConfig,
    SourceConfig,
)
from dxband.models.track import TrackConfig
from dxband.services.atomic_file_service import atomic_write_json, fsync_directory


class PackageBuildError(RuntimeError):
    pass


class PackageBuilder:
    def __init__(
        self,
        library_root: Path,
    ) -> None:
        self.library_root = library_root.expanduser().resolve()
        self.validator = SongPackageValidator()
        self.state_machine = CreationStateMachine()

    def build(
        self,
        job: CreationJob,
        cancellation: CancellationToken | None = None,
        on_event: Callable[[str, str], None] | None = None,
    ) -> Path:
        if job.state != CreationJobState.PACKAGING:
            raise PackageBuildError("任务尚未进入正式打包阶段")
        if job.lyrics_confirmed_path is None or job.lyrics_verified_at is None:
            raise PackageBuildError("歌词尚未自动定稿")
        if job.duration_ms is None or job.resolved_language is None:
            raise PackageBuildError("任务缺少歌曲时长或语言")
        if set(job.stem_paths) != {track.value for track in TrackKind}:
            raise PackageBuildError("任务没有完整六轨")
        if job.score_output_dir is None:
            raise PackageBuildError("任务缺少 SheetSage2 整曲转谱结果")
        if job.beat_output_dir is None:
            raise PackageBuildError("任务缺少 Beat This! 拍点分析结果")
        if job.solo_score_output_dir is None:
            raise PackageBuildError("任务缺少 SheetSage2 纯人声音符")

        ready_root = job.workspace_dir / "package-ready"
        package_ready = ready_root / job.job_id
        if ready_root.exists():
            shutil.rmtree(ready_root)
        package_ready.mkdir(parents=True)
        self._check_cancelled(cancellation)

        for track, filename in TRACK_FILENAMES.items():
            source = job.stem_paths[track.value]
            shutil.copy2(source, package_ready / filename)
            self._check_cancelled(cancellation)
        lyrics = LyricsDocument.model_validate_json(
            job.lyrics_confirmed_path.read_bytes(), strict=True
        )
        analysis = assemble_song_analysis(
            job.score_output_dir, job.solo_score_output_dir,
            job.beat_output_dir / "beat_this.json", lyrics, job.duration_ms,
            asr_output=job.asr_output_path, source_sha256=job.original_source_sha256,
            corrected_lyrics=lyrics,
        )
        score = analysis.score
        aligned_lyrics, aligned_melody = analysis.lyrics, analysis.melody
        config = self._build_config(job, score)
        atomic_write_json(package_ready / "song.json", config)
        self._check_cancelled(cancellation)
        atomic_write_json(package_ready / "lyrics.json", aligned_lyrics)
        atomic_write_json(package_ready / "chords.json", score.chords)
        atomic_write_json(package_ready / "melody.json", aligned_melody)
        if score.rhythm_comparison is not None and job.original_source_sha256 is not None:
            atomic_write_json(
                package_ready / "rhythm_comparison.json",
                comparison_payload(score.rhythm_comparison, job.original_source_sha256),
            )
        self._emit(
            job,
            on_event,
            "log",
            f"简谱已写入：{len(score.melody.bars)} 小节，"
            f"{len(score.melody.notes)} 个音符，{len(score.chords.segments)} 段和弦，"
            f"{sum(note.lyric_line_id is not None for note in aligned_melody.notes)} 个字音关联",
        )
        self._check_cancelled(cancellation)
        self._fsync_package(package_ready)
        self.validator.validate(package_ready)

        destination = self.library_root / job.job_id
        if destination.exists():
            raise PackageBuildError(f"正式歌曲目录已存在：{destination}")
        os.replace(package_ready, destination)
        fsync_directory(self.library_root)

        job.package_path = destination
        self.state_machine.transition(job, CreationJobState.COMPLETED)
        CreationWorkspace.save(job)
        self._emit(job, on_event, "stage", f"歌曲包已提交到 {destination}")
        CreationWorkspace(self.library_root).cleanup(job)
        return destination

    @staticmethod
    def _emit(
        job: CreationJob,
        on_event: Callable[[str, str], None] | None,
        event_type: str,
        message: str,
    ) -> None:
        JobLog(job.workspace_dir).write(f"{event_type}: {message}")
        if on_event is not None:
            on_event(event_type, message)

    def _build_config(self, job: CreationJob, score: SheetSage2Analysis) -> SongConfig:
        if job.duration_ms is None or job.resolved_language is None:
            raise PackageBuildError("任务缺少歌曲时长或语言")
        duration_ms = job.duration_ms
        resolved_language = job.resolved_language
        track_configs: dict[TrackKind, TrackConfig] = {}
        canonical_frames = 0
        sample_rate_hz: Literal[44100] = 44_100
        for track in TrackKind:
            metadata = job.stem_metadata[track.value]
            canonical_frames = max(canonical_frames, self._metadata_int(metadata["decoded_frames"]))
            actual_sample_rate = self._metadata_int(metadata["sample_rate_hz"])
            if actual_sample_rate != sample_rate_hz:
                raise PackageBuildError("六轨采样率必须是 44100 Hz")
            track_configs[track] = TrackConfig(
                file=TRACK_FILENAMES[track],
                sha256=str(metadata["sha256"]),
                duration_ms=self._metadata_int(metadata["duration_ms"]),
                trim_start_frames=self._metadata_int(metadata["trim_start_frames"]),
                pad_end_frames=self._metadata_int(metadata["pad_end_frames"]),
            )
        musical = MusicalConfig(
            original_key=score.original_key,
            bpm=score.bpm,
            beat_times_ms=score.beat_times_ms,
            downbeat_times_ms=score.downbeat_times_ms,
            beats_per_bar=score.beats_per_bar,
        )
        return SongConfig(
            schema_version=3,
            song_id=job.job_id,
            title=job.request.title,
            artist=job.request.artist,
            language=resolved_language,
            created_at=job.created_at,
            duration_ms=duration_ms,
            source=SourceConfig(
                original_filename=job.original_source_filename or "source.mp3",
                sha256=job.original_source_sha256 or "0" * 64,
                original_copied=False,
                lrc_filename=job.original_lrc_filename,
                lrc_sha256=job.original_lrc_sha256,
            ),
            separation=SeparationConfig(
                engine="demucs",
                model="htdemucs_6s",
                demucs_version=job.demucs_version or "未知",
                device=job.selected_device or "cpu",
                output_format="mp3",
                bitrate_kbps=320,
                mp3_preset=2,
            ),
            audio=AudioConfig(
                sample_rate_hz=sample_rate_hz,
                channels=2,
                canonical_frames=canonical_frames,
                tracks=track_configs,
            ),
            musical=musical,
            lyrics=LyricsConfig(
                file="lyrics.json",
                source=job.lyrics_source or "lrc",
                verified=True,
                verified_at=job.lyrics_verified_at,
                language=resolved_language,
            ),
        )

    @staticmethod
    def _metadata_int(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise PackageBuildError("音轨元数据中存在无效整数")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise PackageBuildError("音轨元数据中存在无效整数") from exc

    @staticmethod
    def _check_cancelled(cancellation: CancellationToken | None) -> None:
        if cancellation is not None:
            cancellation.raise_if_cancelled()

    @staticmethod
    def _fsync_package(package_root: Path) -> None:
        for path in package_root.iterdir():
            if path.is_file():
                # Windows cannot fsync a descriptor opened read-only by its CRT.
                mode = "r+b" if os.name == "nt" else "rb"
                with path.open(mode) as stream:
                    os.fsync(stream.fileno())
        fsync_directory(package_root)
