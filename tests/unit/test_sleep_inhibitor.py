# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import subprocess

from dxband.services import sleep_inhibitor as module
from dxband.services.sleep_inhibitor import SleepInhibitor


class _FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return 0 if self.terminated or self.killed else None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0


def test_sleep_inhibitor_reuses_process_until_last_reason_is_released(
    monkeypatch,
) -> None:
    commands: list[list[str]] = []
    process = _FakeProcess()

    def fake_popen(command: list[str], **_kwargs: object) -> _FakeProcess:
        commands.append(command)
        return process

    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    inhibitor = SleepInhibitor()

    first = inhibitor.acquire("Demucs")
    second = inhibitor.acquire("正式播放")

    assert len(commands) == 1
    assert commands[0][:2] == ["/usr/bin/caffeinate", "-dimsu"]
    assert commands[0][-2:] == ["-w", str(module.os.getpid())]
    assert inhibitor.active_reasons == ("Demucs", "正式播放")

    inhibitor.release(first)
    assert not process.terminated
    inhibitor.release(second)
    assert process.terminated
    assert inhibitor.active_reasons == ()


def test_sleep_inhibitor_context_releases_after_error(monkeypatch) -> None:
    monkeypatch.setattr(module.sys, "platform", "linux")
    inhibitor = SleepInhibitor()

    try:
        with inhibitor.hold("歌词对齐"):
            assert inhibitor.active_reasons == ("歌词对齐",)
            raise RuntimeError("测试异常")
    except RuntimeError:
        pass

    assert inhibitor.active_reasons == ()


def test_sleep_inhibitor_kills_unresponsive_caffeinate(monkeypatch) -> None:
    process = _FakeProcess()

    def timeout_wait(timeout: float | None = None) -> int:
        if not process.killed:
            raise subprocess.TimeoutExpired("caffeinate", timeout)
        return 0

    process.wait = timeout_wait  # type: ignore[method-assign]
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    inhibitor = SleepInhibitor()

    token = inhibitor.acquire("测试")
    inhibitor.release(token)

    assert process.killed
