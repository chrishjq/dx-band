# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Run a locally configured SheetSage2 model."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from dxband.creation.cancellation import CancellationToken
from dxband.creation.model_download import huggingface_home, sheetsage2_model_dir
from dxband.services.application_paths import default_application_data_root
from dxband.services.bundle_paths import helper_script
from dxband.services.ffmpeg_tools import resolve_ffmpeg
from dxband.workers.command import (
    python_code_command,
    python_script_command,
    subprocess_creation_flags,
)


class SheetSage2Runner:
    def __init__(self, python: Path | None = None, model: Path | None = None) -> None:
        local_install = default_application_data_root() / "SheetSage2"
        configured_python = python or os.environ.get("DX_BAND_SHEETSAGE2_PYTHON")
        if configured_python is None and (local_install / ".venv" / "bin" / "python").is_file():
            configured_python = local_install / ".venv" / "bin" / "python"
        self.python = Path(configured_python) if configured_python else Path(sys.executable)
        self._explicit_model = model is not None
        self.model = Path(model).expanduser() if model is not None else None
        self._ready = False
        self._resolve_model()

    def _resolve_model(self) -> None:
        if self._explicit_model:
            return
        if os.environ.get("DX_BAND_SHEETSAGE2_MODEL_DIR"):
            self.model = Path(os.environ["DX_BAND_SHEETSAGE2_MODEL_DIR"]).expanduser()
            return
        managed = sheetsage2_model_dir()
        self.model = managed if (managed / "config.json").is_file() else None

    def check_ready(self) -> None:
        if self._ready:
            return
        self._resolve_model()
        if self.model is None or not (self.model / "config.json").is_file():
            raise RuntimeError(
                "未配置 SheetSage2 模型目录；请设置 DX_BAND_SHEETSAGE2_MODEL_DIR"
            )
        if not self.python.is_file():
            raise RuntimeError(f"SheetSage2 Python 环境不存在：{self.python}")
        try:
            probe = subprocess.run(
                python_code_command(
                    "import torch, transformers, mir_eval",
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
            raise RuntimeError(f"无法启动 SheetSage2 Python 环境：{exc}") from exc
        if probe.returncode:
            raise RuntimeError(
                "SheetSage2 Python 环境缺少所需依赖：" + probe.stderr[-600:]
            )
        self._ready = True

    def run(
        self, source: Path, output: Path, cancellation: CancellationToken
    ) -> Path:
        self.check_ready()
        output.mkdir(parents=True, exist_ok=True)
        wav = output / "source-24k.wav"
        ffmpeg = self._ffmpeg_executable()
        try:
            self._run_process(
                [ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(source),
                 "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(wav)],
                cancellation, output / "ffmpeg.log",
            )
            self._transcribe(wav, output, cancellation)
        finally:
            wav.unlink(missing_ok=True)
        if not (output / "events.json").is_file():
            raise RuntimeError("SheetSage2 未生成 events.json")
        return output

    def run_stems(
        self, stems: list[Path], output: Path, cancellation: CancellationToken
    ) -> Path:
        self.check_ready()
        if len(stems) != 6:
            raise ValueError("SheetSage2 需要完整六轨")
        output.mkdir(parents=True, exist_ok=True)
        wav = output / "source-24k.wav"
        ffmpeg = self._ffmpeg_executable()
        try:
            inputs = [part for stem in stems for part in ("-i", str(stem))]
            self._run_process(
                [ffmpeg, "-nostdin", "-v", "error", "-y", *inputs,
                 "-filter_complex", "amix=inputs=6:duration=longest:normalize=0,volume=0.5",
                 "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(wav)],
                cancellation, output / "ffmpeg.log",
            )
            self._transcribe(wav, output, cancellation)
        finally:
            wav.unlink(missing_ok=True)
        return output

    @staticmethod
    def _ffmpeg_executable() -> str:
        path = resolve_ffmpeg()
        if path is None:
            raise RuntimeError("未找到 FFmpeg。请到设置页下载到本机后重试。")
        return str(path)

    def _transcribe(self, wav: Path, output: Path, cancellation: CancellationToken) -> None:
        script = helper_script("run_sheetsage2.py")
        # SheetSage2 and MERT are provided by the user in a separate local cache.
        external_home = huggingface_home()
        environment = os.environ.copy()
        environment["HF_HOME"] = str(external_home)
        environment["HF_HUB_CACHE"] = str(external_home / "hub")
        environment["HF_HUB_OFFLINE"] = "1"
        command = python_script_command(
            script,
            [str(wav), str(output), "--model", str(self.model), "--device", "auto"],
            python=self.python,
        )
        self._run_process(
            command,
            cancellation,
            output / "sheetsage2.log",
            environment,
        )
        if not (output / "events.json").is_file():
            raise RuntimeError("SheetSage2 未生成 events.json")

    @staticmethod
    def _run_process(
        command: list[str], cancellation: CancellationToken, log_path: Path,
        environment: dict[str, str] | None = None,
    ) -> None:
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, env=environment,
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
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
                raise RuntimeError(f"SheetSage2 命令失败（{process.returncode}）：{tail}")
