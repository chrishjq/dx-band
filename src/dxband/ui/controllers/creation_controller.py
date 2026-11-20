# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import queue
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import QObject, QTimer, Signal

from dxband.creation.cancellation import CancellationToken, CancelledError
from dxband.creation.package_builder import PackageBuilder
from dxband.creation.pipeline import CreationPipeline
from dxband.models.creation_job import (
    CreateSongRequest,
    CreationJob,
    CreationJobState,
)
from dxband.models.lyric import LyricsDocument
from dxband.services.application_paths import default_library_root
from dxband.ui.pages.create_song_page import CreateSongPage


class CreationController(QObject):
    song_created = Signal(object)
    creation_active_changed = Signal(bool)

    def __init__(
        self,
        page: CreateSongPage,
        library_root: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.page = page
        self.pipeline = CreationPipeline(library_root or default_library_root())
        self.package_builder = PackageBuilder(self.pipeline.workspace.library_root)
        self._messages: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._cancellation: CancellationToken | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._drain_messages)
        self._timer.start()
        self.page.start_requested.connect(self.start)
        self.page.cancel_requested.connect(self.cancel)

    def start(self, values: object) -> None:
        if self._thread is not None and self._thread.is_alive():
            self.page.show_error("已有创建任务正在运行")
            return
        try:
            if not isinstance(values, dict):
                raise ValueError("创建参数格式错误")
            request = CreateSongRequest.model_validate(values, strict=True)
        except (ValidationError, ValueError) as exc:
            self.page.show_error(str(exc))
            return

        self._cancellation = CancellationToken()
        self.page.set_running(True)
        self.creation_active_changed.emit(True)
        self._thread = threading.Thread(
            target=self._prepare_in_background,
            args=(request, self._cancellation),
            name="creation-prepare",
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        if self._cancellation is not None:
            self._cancellation.cancel()
            self.page.set_stage("正在取消任务……")

    def set_library_root(self, library_root: Path) -> None:
        """在无任务运行时切换创建目标歌曲库。"""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("创建任务运行中，暂时不能切换歌曲库")
        self.pipeline = CreationPipeline(library_root)
        self.package_builder = PackageBuilder(self.pipeline.workspace.library_root)

    def _prepare_in_background(
        self, request: CreateSongRequest, cancellation: CancellationToken
    ) -> None:
        job: CreationJob | None = None
        try:
            job = self.pipeline.run_to_draft(
                request,
                cancellation,
                self._enqueue_pipeline_event,
            )
            if job.lyrics_draft_path is None:
                raise RuntimeError("任务缺少自动生成的歌词")
            document = LyricsDocument.model_validate_json(
                job.lyrics_draft_path.read_bytes(), strict=True
            )
            job = self.pipeline.finalize_generated_lyrics(job, document)
            self._enqueue_pipeline_event("stage", "歌词已自动定稿，正在生成歌曲包")
            destination = self.package_builder.build(
                job,
                cancellation,
                self._enqueue_pipeline_event,
            )
            self._messages.put(("package_completed", destination))
        except CancelledError:
            if job is not None and job.state not in {
                CreationJobState.CANCELLED,
                CreationJobState.FAILED,
            }:
                try:
                    self.pipeline.state_machine.begin_cancellation(job)
                    self.pipeline.state_machine.finish_cancellation(job)
                    self.pipeline.workspace.save(job)
                except Exception as state_exc:
                    self._messages.put(("log", f"取消状态保存失败：{state_exc}"))
            self._messages.put(("cancelled", None))
        except Exception as exc:
            if job is not None and job.state not in {
                CreationJobState.COMPLETED,
                CreationJobState.CANCELLED,
                CreationJobState.FAILED,
            }:
                try:
                    self.pipeline.state_machine.fail(job, str(exc))
                    self.pipeline.workspace.save(job)
                except Exception as state_exc:
                    self._messages.put(("log", f"失败状态保存失败：{state_exc}"))
            self._messages.put(("failed", str(exc)))

    def _enqueue_pipeline_event(self, event_type: str, message: str) -> None:
        self._messages.put((event_type, message))

    def _drain_messages(self) -> None:
        while True:
            try:
                event_type, payload = self._messages.get_nowait()
            except queue.Empty:
                return
            if event_type == "stage":
                self.page.set_stage(str(payload))
            elif event_type == "log":
                self.page.consume_progress_message(str(payload))
            elif event_type == "progress":
                with suppress(TypeError, ValueError):
                    self.page.set_progress(float(payload))
            elif event_type == "error":
                self.page.show_error(str(payload))
            elif event_type == "package_completed" and isinstance(payload, Path):
                self.page.set_running(False)
                self.creation_active_changed.emit(False)
                self.page.reset_for_next_song()
                self._cancellation = None
                self.song_created.emit(payload)
            elif event_type == "cancelled":
                self.page.set_running(False)
                self.creation_active_changed.emit(False)
                self.page.set_stage("已取消")
            elif event_type == "failed":
                self.page.set_running(False)
                self.creation_active_changed.emit(False)
                self.page.show_error(str(payload))
