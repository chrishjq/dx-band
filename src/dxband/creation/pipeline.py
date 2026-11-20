# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from dxband.analysis.beat_led_score import read_beat_led_analysis
from dxband.creation.asr_lyrics import correct_asr_lyrics
from dxband.creation.beat_this_runner import BeatThisRunner
from dxband.creation.cancellation import CancellationToken, CancelledError
from dxband.creation.ctc_lyrics_aligner import LrcCtcAligner
from dxband.creation.fun_asr_runner import FunAsrRunner
from dxband.creation.input_validator import CreationInputValidator
from dxband.creation.lrc_parser import LrcParser
from dxband.creation.lyric_text_parser import parse_lyric_text
from dxband.creation.lyrics_strategy import timing_language
from dxband.creation.sheetsage2_runner import SheetSage2Runner
from dxband.creation.state_machine import CreationStateMachine
from dxband.creation.stem_validator import StemValidator
from dxband.creation.workspace import CreationWorkspace, JobLog
from dxband.models.creation_job import (
    CreateSongRequest,
    CreationJob,
    CreationJobState,
)
from dxband.models.lyric import LyricsDocument
from dxband.services.atomic_file_service import atomic_write_json
from dxband.services.environment_check import EnvironmentChecker
from dxband.workers.command import worker_command
from dxband.workers.process_client import WorkerProcessClient
from dxband.workers.protocol import (
    ErrorEvent,
    LogEvent,
    ProgressEvent,
    StageEvent,
    WorkerEvent,
)

PipelineEventHandler = Callable[[str, str], None]


class CreationPipeline:
    def __init__(self, library_root: Path) -> None:
        self.workspace = CreationWorkspace(library_root)
        self.input_validator = CreationInputValidator()
        self.state_machine = CreationStateMachine()
        self.environment = EnvironmentChecker()
        self.worker_client = WorkerProcessClient()
        self.stem_validator = StemValidator()
        self.lrc_parser = LrcParser()
        self.lyric_aligner = LrcCtcAligner()
        self.score_runner = SheetSage2Runner()
        self.beat_runner = BeatThisRunner()
        self.asr_runner = FunAsrRunner()

    def finalize_generated_lyrics(
        self,
        job: CreationJob,
        document: LyricsDocument,
    ) -> CreationJob:
        if job.state != CreationJobState.AWAITING_LYRIC_REVIEW:
            raise RuntimeError("当前任务不在歌词定稿阶段")
        if job.duration_ms is None:
            raise RuntimeError("任务缺少歌曲时长")
        if any(line.end_ms > job.duration_ms for line in document.lines):
            raise ValueError("歌词时间超出歌曲时长")
        confirmed_path = job.workspace_dir / "lyrics.json"
        atomic_write_json(confirmed_path, document)
        job.lyrics_confirmed_path = confirmed_path
        job.lyrics_verified_at = datetime.now().astimezone()
        self.state_machine.transition(job, CreationJobState.PACKAGING)
        self.workspace.save(job)
        JobLog(job.workspace_dir).write("stage: 歌词已自动定稿")
        return job

    def run_to_draft(
        self,
        request: CreateSongRequest,
        cancellation: CancellationToken,
        on_event: PipelineEventHandler,
    ) -> CreationJob:
        job: CreationJob | None = None
        try:
            job = self.prepare(request, cancellation, on_event)
            log = JobLog(job.workspace_dir)
            status = self.environment.inspect()
            if not status.ffmpeg_available:
                raise RuntimeError(
                    "未找到 FFmpeg，无法输出 320kbps MP3；macOS 请执行 brew install ffmpeg"
                )
            if not status.demucs_available:
                raise RuntimeError("未安装 Demucs，请执行 uv sync --extra ai --extra dev")
            self.score_runner.check_ready()
            self.beat_runner.check_ready()
            device = self.environment.select_torch_device("auto")
            job.selected_device = device
            self.workspace.save(job)
            self._emit(log, on_event, "stage", "正在分离音轨")

            output_root = job.workspace_dir / "separated"
            command = worker_command(
                "separate",
                [
                    "--source",
                    str(job.request.source_mp3),
                    "--output",
                    str(output_root),
                    "--device",
                    device,
                ],
            )

            def handle_worker_event(event: WorkerEvent) -> None:
                if isinstance(event, StageEvent):
                    self._emit(log, on_event, "stage", "正在分离音轨")
                elif isinstance(event, LogEvent):
                    self._emit(log, on_event, "log", event.message)
                elif isinstance(event, ProgressEvent):
                    self._emit(log, on_event, "progress", str(event.value))
                elif isinstance(event, ErrorEvent):
                    detail = f"：{event.details}" if event.details else ""
                    self._emit(log, on_event, "error", f"{event.message}{detail}")

            result_event = self.worker_client.run(command, cancellation, handle_worker_event)
            job.demucs_version = str(result_event.data.get("version", "未知"))
            job.selected_device = str(result_event.data.get("device", device))
            job.separation_output_dir = Path(result_event.path)
            self.state_machine.transition(job, CreationJobState.VALIDATING_STEMS)
            self.workspace.save(job)
            self._emit(log, on_event, "stage", "正在校验六个轨道")
            validation = self.stem_validator.validate(job.separation_output_dir)
            job.duration_ms = validation.duration_ms
            job.stem_paths = {kind.value: info.path for kind, info in validation.tracks.items()}
            job.stem_metadata = {
                kind.value: {
                    "sample_rate_hz": info.sample_rate_hz,
                    "channels": info.channels,
                    "decoded_frames": info.decoded_frames,
                    "duration_ms": info.duration_ms,
                    "sha256": info.sha256,
                    "trim_start_frames": info.trim_start_frames,
                    "pad_end_frames": info.pad_end_frames,
                }
                for kind, info in validation.tracks.items()
            }
            self._emit(log, on_event, "stage", "正在生成整曲简谱")
            score_dir = self.score_runner.run(
                job.request.source_mp3, job.workspace_dir / "sheetsage2", cancellation
            )
            self._emit(log, on_event, "stage", "正在识别纯人声音符")
            solo_dir = self.score_runner.run(
                job.stem_paths["vocals"], job.workspace_dir / "sheetsage2_vocals_only",
                cancellation,
            )
            self._emit(log, on_event, "stage", "正在核对节奏和小节")
            beat_dir = self.beat_runner.run(
                job.request.source_mp3, job.workspace_dir / "beat_this", cancellation
            )
            music = read_beat_led_analysis(
                score_dir, beat_dir / "beat_this.json", job.duration_ms,
                job.original_source_sha256, solo_output=solo_dir,
            )
            job.score_output_dir = score_dir
            job.solo_score_output_dir = solo_dir
            job.beat_output_dir = beat_dir
            job.original_key = music.original_key
            job.bpm = music.bpm
            job.beat_times_ms = music.beat_times_ms
            job.downbeat_times_ms = music.downbeat_times_ms
            job.beats_per_bar = music.beats_per_bar
            self._emit(
                log,
                on_event,
                "log",
                f"整曲分析完成：{music.original_key}，{music.bpm} BPM，"
                f"{len(music.melody.bars)} 小节，{len(music.melody.notes)} 个音符，"
                "小节采用 Beat This! 连续拍网格",
            )
            import_state = (
                CreationJobState.IMPORTING_LRC
                if job.request.lrc_path is not None
                else CreationJobState.IMPORTING_TEXT
            )
            self.state_machine.transition(job, import_state)
            self.workspace.save(job)
            self._emit(log, on_event, "stage", "六轨验证完成，开始对齐已有歌词")
            self._build_lyrics_draft(job, cancellation, on_event, log)
            return job
        except CancelledError:
            if job is not None and job.state not in {
                CreationJobState.CANCELLED,
                CreationJobState.FAILED,
            }:
                self.state_machine.begin_cancellation(job)
                self.state_machine.finish_cancellation(job)
                self.workspace.save(job)
            raise
        except Exception as exc:
            if job is not None and job.state != CreationJobState.FAILED:
                self.state_machine.fail(job, str(exc))
                self.workspace.save(job)
            raise

    def _build_lyrics_draft(
        self,
        job: CreationJob,
        cancellation: CancellationToken,
        on_event: PipelineEventHandler,
        log: JobLog,
    ) -> None:
        cancellation.raise_if_cancelled()
        if job.duration_ms is None:
            raise RuntimeError("缺少歌曲时长，无法生成歌词草稿")

        if job.state not in (CreationJobState.IMPORTING_LRC, CreationJobState.IMPORTING_TEXT):
            raise RuntimeError(f"当前状态不能处理歌词：{job.state.value}")
        vocals_path = job.stem_paths.get("vocals")
        if vocals_path is None:
            raise RuntimeError("缺少 vocals.mp3，无法识别歌词")
        if job.request.lrc_path is None and not job.request.lyrics_text:
            raise RuntimeError("请提供 LRC 歌词文件或输入歌词文本")
        if job.request.lrc_path is not None:
            self._emit(log, on_event, "stage", "正在读取 LRC 歌词文字")
            reference = self.lrc_parser.parse_text_only(
                job.request.lrc_path, job.request.title, job.request.language, job.duration_ms
            )
        else:
            self._emit(log, on_event, "stage", "正在读取歌词文本")
            reference = parse_lyric_text(
                job.request.lyrics_text or "",
                job.request.title,
                job.request.language,
                job.duration_ms,
            )
        language = timing_language(job.request.language, reference)
        if language == "en" and job.request.lrc_path is not None:
            reference = self.lrc_parser.parse_text_only(
                job.request.lrc_path, job.request.title, "en", job.duration_ms
            )
        reference = reference.model_copy(update={"language": language})
        cancellation.raise_if_cancelled()
        source_label = "LRC" if job.request.lrc_path is not None else "文本"
        self._emit(log, on_event, "stage", "正在对齐歌词时间")
        if language in {"zh", "yue"}:
            self._emit(log, on_event, "stage", "正在识别逐字人声时间")
            asr_path = self.asr_runner.run(
                vocals_path, job.workspace_dir / "fun_asr", cancellation,
                language=language,
            )
            job.asr_output_path = asr_path
            tokens = json.loads(asr_path.read_text(encoding="utf-8")).get("tokens", [])
            document = correct_asr_lyrics(reference, tokens, job.duration_ms)
        else:
            document = LrcCtcAligner(language=language).align_document(reference, vocals_path)
        aligned_lines = sum(bool(line.words) for line in document.lines)
        self._emit(
            log,
            on_event,
            "log",
            f"{source_label}与人声对齐：{aligned_lines}/{len(document.lines)} 行",
        )
        job.lyrics_source = "lrc" if job.request.lrc_path is not None else "text"
        job.resolved_language = language

        self.state_machine.transition(job, CreationJobState.BUILDING_LYRICS_DRAFT)

        cancellation.raise_if_cancelled()
        draft_path = job.workspace_dir / "lyrics.draft.json"
        atomic_write_json(draft_path, document)
        job.lyrics_draft_path = draft_path
        self.state_machine.transition(job, CreationJobState.AWAITING_LYRIC_REVIEW)
        self.workspace.save(job)
        self._emit(log, on_event, "stage", "歌词与逐字时间已自动生成并校正")

    def prepare(
        self,
        request: CreateSongRequest,
        cancellation: CancellationToken,
        on_event: PipelineEventHandler,
    ) -> CreationJob:
        job = self.workspace.create(request)
        log = JobLog(job.workspace_dir)
        try:
            self.state_machine.transition(job, CreationJobState.VALIDATING_INPUT)
            self.workspace.save(job)
            self._emit(log, on_event, "stage", "正在校验输入")
            cancellation.raise_if_cancelled()
            validated = self.input_validator.validate(job.request, self.workspace.library_root)
            job.request = validated.request
            job.duration_ms = validated.media.duration_ms
            self.state_machine.transition(job, CreationJobState.SEPARATING)
            self.workspace.save(job)
            self._emit(log, on_event, "stage", "输入校验完成，等待六轨分离")
            return job
        except CancelledError:
            self.state_machine.begin_cancellation(job)
            self.state_machine.finish_cancellation(job)
            self.workspace.save(job)
            self._emit(log, on_event, "stage", "任务已取消")
            raise
        except Exception as exc:
            self.state_machine.fail(job, str(exc))
            self.workspace.save(job)
            self._emit(log, on_event, "error", str(exc))
            raise

    @staticmethod
    def _emit(
        log: JobLog,
        on_event: PipelineEventHandler,
        event_type: str,
        message: str,
    ) -> None:
        log.write(f"{event_type}: {message}")
        on_event(event_type, message)
