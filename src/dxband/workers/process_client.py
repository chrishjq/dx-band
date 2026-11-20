# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import queue
import subprocess
import threading
import time
from collections.abc import Callable, Sequence

from dxband.creation.cancellation import CancellationToken, CancelledError
from dxband.services.sleep_inhibitor import sleep_inhibitor
from dxband.workers.command import subprocess_creation_flags
from dxband.workers.protocol import LogEvent, ResultEvent, WorkerEvent, parse_event


class WorkerProcessError(RuntimeError):
    pass


class WorkerProcessClient:
    def __init__(self, terminate_timeout_seconds: float = 5.0) -> None:
        self.terminate_timeout_seconds = terminate_timeout_seconds

    def run(
        self,
        command: Sequence[str],
        cancellation: CancellationToken,
        on_event: Callable[[WorkerEvent], None],
    ) -> ResultEvent:
        with sleep_inhibitor.hold("AI 子进程"):
            return self._run_awake(command, cancellation, on_event)

    def _run_awake(
        self,
        command: Sequence[str],
        cancellation: CancellationToken,
        on_event: Callable[[WorkerEvent], None],
    ) -> ResultEvent:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            creationflags=subprocess_creation_flags(),
        )
        output_queue: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            assert process.stdout is not None
            for output_line in process.stdout:
                output_queue.put(output_line.rstrip("\r\n"))
            output_queue.put(None)

        reader = threading.Thread(target=read_output, name="worker-output", daemon=True)
        reader.start()
        result: ResultEvent | None = None
        reader_finished = False
        terminate_deadline: float | None = None

        while not reader_finished or process.poll() is None:
            if cancellation.is_cancelled and process.poll() is None:
                if terminate_deadline is None:
                    process.terminate()
                    terminate_deadline = time.monotonic() + self.terminate_timeout_seconds
                elif time.monotonic() >= terminate_deadline:
                    process.kill()

            try:
                line = output_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                reader_finished = True
                continue
            event = parse_event(line)
            if event is None:
                on_event(LogEvent(level="warning", message=line))
            else:
                on_event(event)
                if isinstance(event, ResultEvent):
                    result = event

        return_code = process.wait()
        if cancellation.is_cancelled:
            raise CancelledError("任务已取消")
        if return_code != 0:
            raise WorkerProcessError(f"子进程异常退出，返回码：{return_code}")
        if result is None:
            raise WorkerProcessError("子进程未返回结构化结果")
        return result
