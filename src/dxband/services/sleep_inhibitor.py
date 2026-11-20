# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import logging
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

LOGGER = logging.getLogger(__name__)


class SleepInhibitor:
    """在 AI 任务或正式播放期间阻止 macOS 进入休眠。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, str] = {}
        self._process: subprocess.Popen[bytes] | None = None

    def acquire(self, reason: str) -> str:
        token = uuid4().hex
        with self._lock:
            self._tokens[token] = reason
            if len(self._tokens) == 1:
                self._start_locked()
        return token

    def release(self, token: str | None) -> None:
        if token is None:
            return
        with self._lock:
            self._tokens.pop(token, None)
            if not self._tokens:
                self._stop_locked()

    @contextmanager
    def hold(self, reason: str) -> Iterator[None]:
        token = self.acquire(reason)
        try:
            yield
        finally:
            self.release(token)

    def close(self) -> None:
        with self._lock:
            self._tokens.clear()
            self._stop_locked()

    @property
    def active_reasons(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._tokens.values())

    def _start_locked(self) -> None:
        if sys.platform != "darwin" or self._process is not None:
            return
        try:
            self._process = subprocess.Popen(
                ["/usr/bin/caffeinate", "-dimsu", "-w", str(os.getpid())],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        except OSError:
            LOGGER.exception("启动 macOS 防休眠失败")

    def _stop_locked(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                LOGGER.exception("停止 macOS 防休眠进程失败")


sleep_inhibitor = SleepInhibitor()
