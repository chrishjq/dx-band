# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import io
import subprocess

import pytest

from dxband.creation.cancellation import CancellationToken
from dxband.workers import process_client
from dxband.workers.process_client import WorkerProcessClient
from dxband.workers.protocol import ResultEvent, encode_event


class _FinishedProcess:
    def __init__(self, output: str) -> None:
        self.stdout = io.StringIO(output)

    def poll(self) -> int:
        return 0

    def wait(self) -> int:
        return 0


def test_gui_worker_does_not_inherit_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    options: dict[str, object] = {}

    def start(_command: list[str], **kwargs: object) -> _FinishedProcess:
        options.update(kwargs)
        return _FinishedProcess(encode_event(ResultEvent(path="ready")) + "\n")

    monkeypatch.setattr(process_client.subprocess, "Popen", start)

    result = WorkerProcessClient()._run_awake(
        ["worker"], CancellationToken(), lambda _event: None
    )

    assert result.path == "ready"
    assert options["stdin"] == subprocess.DEVNULL
