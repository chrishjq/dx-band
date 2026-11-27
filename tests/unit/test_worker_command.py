# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import sys
from pathlib import Path

from dxband.runtime_exec import EXEC_FLAG
from dxband.workers.command import (
    python_code_command,
    python_module_command,
    python_script_command,
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


def test_frozen_commands_insert_exec_flag(monkeypatch) -> None:
    monkeypatch.setattr("dxband.workers.command.is_frozen", lambda: True)

    assert worker_command("separate", ["--device", "cpu"]) == [
        sys.executable,
        EXEC_FLAG,
        "-m",
        "dxband.workers",
        "separate",
        "--device",
        "cpu",
    ]
    assert python_module_command("demucs", ["-n", "htdemucs_6s"]) == [
        sys.executable,
        EXEC_FLAG,
        "-m",
        "demucs",
        "-n",
        "htdemucs_6s",
    ]
    assert python_code_command("import torch") == [
        sys.executable,
        EXEC_FLAG,
        "-c",
        "import torch",
    ]
    script = Path("/tmp/run_beat_this.py")
    assert python_script_command(script, ["a.wav", "out.json"]) == [
        sys.executable,
        EXEC_FLAG,
        str(script),
        "a.wav",
        "out.json",
    ]


def test_custom_python_skips_exec_flag_even_when_frozen(monkeypatch) -> None:
    monkeypatch.setattr("dxband.workers.command.is_frozen", lambda: True)
    custom = "/opt/custom/bin/python"

    assert python_module_command("demucs", ["-n", "x"], python=custom) == [
        custom,
        "-m",
        "demucs",
        "-n",
        "x",
    ]
