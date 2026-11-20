# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import sys

from dxband.workers.command import (
    python_module_command,
    subprocess_creation_flags,
    worker_command,
)


def test_worker_command_uses_module_in_source_environment() -> None:
    command = worker_command("separate", ["--device", "cpu"])

    assert command == [
        sys.executable,
        "-m",
        "dxband.workers",
        "separate",
        "--device",
        "cpu",
    ]


def test_windows_worker_does_not_open_console(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("subprocess.CREATE_NO_WINDOW", 0x08000000, raising=False)

    assert subprocess_creation_flags() == 0x08000000


def test_python_module_command_uses_source_python() -> None:
    command = python_module_command("demucs", ["-n", "htdemucs_ft"])

    assert command == [
        sys.executable,
        "-m",
        "demucs",
        "-n",
        "htdemucs_ft",
    ]
