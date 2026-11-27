# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Run a locally configured Beat This! model during song creation."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from dxband.creation.cancellation import CancellationToken
from dxband.creation.model_download import beat_this_checkpoint_path
from dxband.services.application_paths import default_application_data_root
from dxband.services.bundle_paths import helper_script
from dxband.workers.command import (
    python_code_command,
    python_script_command,
    subprocess_creation_flags,
)


class BeatThisRunner:
    def __init__(self, python: Path | None = None, checkpoint: Path | None = None) -> None:
        local_install = default_application_data_root() / "BeatThis"
        configured_python = python or os.environ.get("DX_BAND_BEAT_THIS_PYTHON")
        if configured_python is None and (local_install / ".venv" / "bin" / "python").is_file():
            configured_python = local_install / ".venv" / "bin" / "python"
        self.python = Path(configured_python) if configured_python else Path(sys.executable)
        self._explicit_checkpoint = checkpoint is not None
        self.checkpoint = str(Path(checkpoint).expanduser()) if checkpoint is not None else ""
        self._ready = False
        self._resolve_checkpoint()

    def _resolve_checkpoint(self) -> None:
        if self._explicit_checkpoint:
            return
        if os.environ.get("DX_BAND_BEAT_THIS_CHECKPOINT"):
            self.checkpoint = str(
                Path(os.environ["DX_BAND_BEAT_THIS_CHECKPOINT"]).expanduser()
            )
            return
        managed = beat_this_checkpoint_path()
        self.checkpoint = str(managed) if managed.is_file() else ""

    def check_ready(self) -> None:
        if self._ready:
            return
        self._resolve_checkpoint()
        if not self.checkpoint:
            raise RuntimeError(
                "未配置 Beat This! 模型文件；请自行下载并设置 DX_BAND_BEAT_THIS_CHECKPOINT"
            )
        if not Path(self.checkpoint).is_file():
            raise RuntimeError(f"Beat This! 模型文件不存在：{self.checkpoint}")
        if not self.python.is_file():
            raise RuntimeError(f"Beat This! Python 环境不存在：{self.python}")
        try:
            probe = subprocess.run(
                python_code_command(
                    "import beat_this, torch, torchaudio, soxr",
                    python=self.python,
                ),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                creationflags=subprocess_creation_flags(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"无法启动 Beat This! Python 环境：{exc}") from exc
        if probe.returncode:
            raise RuntimeError("Beat This! Python 环境缺少依赖：" + probe.stderr[-600:])
        self._ready = True

    def run(self, source: Path, output: Path, cancellation: CancellationToken) -> Path:
        self.check_ready()
        output.mkdir(parents=True, exist_ok=True)
        script = helper_script("run_beat_this.py")
        destination = output / "beat_this.json"
        command = python_script_command(
            script,
            [
                str(source),
                str(destination),
                "--checkpoint",
                self.checkpoint,
                "--device",
                "auto",
            ],
            python=self.python,
        )
        with (output / "beat_this.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess_creation_flags(),
            )
            try:
                while process.poll() is None:
                    cancellation.raise_if_cancelled()
                    time.sleep(0.2)
            except BaseException:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise
        if process.returncode:
            tail = (output / "beat_this.log").read_text(encoding="utf-8", errors="replace")[-1500:]
            raise RuntimeError(f"Beat This! 分析失败（{process.returncode}）：{tail}")
        if not destination.is_file():
            raise RuntimeError("Beat This! 未生成 beat_this.json")
        return output
