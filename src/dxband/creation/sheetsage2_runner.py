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
from dxband.workers.command import subprocess_creation_flags


class SheetSage2Runner:
    def __init__(self, python: Path | None = None, model: Path | None = None) -> None:
        local_install = Path.home() / "Library" / "Application Support" / "DXBand" / "SheetSage2"
        configured_python = python or os.environ.get("DX_BAND_SHEETSAGE2_PYTHON")
        if configured_python is None and (local_install / ".venv" / "bin" / "python").is_file():
            configured_python = local_install / ".venv" / "bin" / "python"
        self.python = Path(configured_python) if configured_python else Path(sys.executable)
        model_value = model or os.environ.get("DX_BAND_SHEETSAGE2_MODEL_DIR")
        if model_value is None and (local_install / "model" / "config.json").is_file():
            model_value = local_install / "model"
        self.model = Path(model_value).expanduser() if model_value else None
        self._ready = False

    def check_ready(self) -> None:
        if self._ready:
            return
        if self.model is None or not (self.model / "config.json").is_file():
            raise RuntimeError(
                "未配置 SheetSage2 模型目录；请设置 DX_BAND_SHEETSAGE2_MODEL_DIR"
            )
        if not self.python.is_file():
            raise RuntimeError(f"SheetSage2 Python 环境不存在：{self.python}")
        try:
            probe = subprocess.run(
                [str(self.python), "-c", "import torch, transformers, mir_eval"],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=30,
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
        try:
            self._run_process(
                ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source),
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
        try:
            inputs = [part for stem in stems for part in ("-i", str(stem))]
            self._run_process(
                ["ffmpeg", "-nostdin", "-v", "error", "-y", *inputs,
                 "-filter_complex", "amix=inputs=6:duration=longest:normalize=0,volume=0.5",
                 "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(wav)],
                cancellation, output / "ffmpeg.log",
            )
            self._transcribe(wav, output, cancellation)
        finally:
            wav.unlink(missing_ok=True)
        return output

    def _transcribe(self, wav: Path, output: Path, cancellation: CancellationToken) -> None:
        root = Path(__file__).resolve().parents[3]
        script = root / "scripts" / "run_sheetsage2.py"
        # SheetSage2 and MERT are provided by the user in a separate local cache.
        external_home = Path(
            os.environ.get(
                "DX_BAND_SHEETSAGE2_HF_HOME",
                str(Path.home() / ".cache" / "huggingface"),
            )
        ).expanduser()
        environment = os.environ.copy()
        environment["HF_HOME"] = str(external_home)
        environment["HF_HUB_CACHE"] = str(external_home / "hub")
        environment["HF_HUB_OFFLINE"] = "1"
        command = [str(self.python), str(script)]
        self._run_process(
            [*command, str(wav), str(output),
             "--model", str(self.model), "--device", "auto"],
            cancellation, output / "sheetsage2.log", environment,
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
