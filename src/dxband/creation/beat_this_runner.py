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
from dxband.workers.command import subprocess_creation_flags


class BeatThisRunner:
    def __init__(self, python: Path | None = None, checkpoint: Path | None = None) -> None:
        local_install = Path.home() / "Library" / "Application Support" / "DXBand" / "BeatThis"
        configured_python = python or os.environ.get("DX_BAND_BEAT_THIS_PYTHON")
        if configured_python is None and (local_install / ".venv" / "bin" / "python").is_file():
            configured_python = local_install / ".venv" / "bin" / "python"
        self.python = Path(configured_python) if configured_python else Path(sys.executable)
        model_value = checkpoint or os.environ.get("DX_BAND_BEAT_THIS_CHECKPOINT")
        if model_value is None and (local_install / "model" / "final0.ckpt").is_file():
            model_value = local_install / "model" / "final0.ckpt"
        self.checkpoint = str(Path(model_value).expanduser()) if model_value else ""
        self._ready = False

    def check_ready(self) -> None:
        if self._ready:
            return
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
                [str(self.python), "-c", "import beat_this, torch, torchaudio, soxr"],
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
        root = Path(__file__).resolve().parents[3]
        script = root / "scripts" / "run_beat_this.py"
        destination = output / "beat_this.json"
        command = [str(self.python), str(script)]
        with (output / "beat_this.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    *command,
                    str(source),
                    str(destination),
                    "--checkpoint",
                    self.checkpoint,
                    "--device",
                    "auto",
                ],
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
