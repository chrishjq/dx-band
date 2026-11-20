# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Run native-timestamp Fun-ASR on the separated vocal stem."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

from dxband.creation.cancellation import CancellationToken
from dxband.services.application_paths import default_application_data_root
from dxband.workers.command import subprocess_creation_flags

MODEL_CODE_SHA256 = "223e24104889df1bd5d7f85fa7584233ad31936ea43b0c57afde37a3d9c90da5"


class FunAsrRunner:
    def __init__(
        self, python: Path | None = None, model_code: Path | None = None,
        model_dir: Path | None = None,
    ) -> None:
        configured = python or os.environ.get("DX_BAND_FUN_ASR_PYTHON")
        self.python = Path(configured) if configured else Path(sys.executable)
        code = model_code or os.environ.get("DX_BAND_FUN_ASR_MODEL_CODE")
        self.managed_code = code is None
        self.model_code = Path(code).expanduser() if code else (
            default_application_data_root() / "Fun-ASR" / "model.py"
        )
        directory = model_dir or os.environ.get("DX_BAND_FUN_ASR_MODEL_DIR")
        self.model_dir = Path(directory).expanduser() if directory else None

    def _prepare_code(self) -> None:
        if not self.model_code.is_file():
            raise RuntimeError(
                "缺少 Fun-ASR 模型代码；请从 https://github.com/QwenAudio/Fun-ASR "
                "自行获取，并设置 DX_BAND_FUN_ASR_MODEL_CODE"
            )
        if self.managed_code and hashlib.sha256(
            self.model_code.read_bytes()
        ).hexdigest() != MODEL_CODE_SHA256:
            raise RuntimeError("Fun-ASR 模型代码版本与当前程序不一致")

    def check_ready(self) -> None:
        if not self.python.is_file():
            raise RuntimeError(f"Fun-ASR Python 环境不存在：{self.python}")
        if self.model_dir is None or not self.model_dir.is_dir() or not any(
            (self.model_dir / name).is_file()
            for name in ("configuration.json", "config.yaml")
        ):
            raise RuntimeError(
                "缺少本机 Fun-ASR 模型；请从 "
                "https://modelscope.cn/models/FunAudioLLM/Fun-ASR-Nano-2512 "
                "自行获取，并设置 DX_BAND_FUN_ASR_MODEL_DIR"
            )
        probe = subprocess.run(
            [str(self.python), "-c", "import funasr, librosa, soundfile"],
            capture_output=True, text=True, check=False, timeout=30,
            creationflags=subprocess_creation_flags(),
        )
        if probe.returncode:
            raise RuntimeError("Fun-ASR 环境缺少依赖：" + probe.stderr[-600:])
        self._prepare_code()

    def run(
        self, vocals: Path, output: Path, cancellation: CancellationToken,
        *, language: str = "yue",
    ) -> Path:
        self.check_ready()
        output.mkdir(parents=True, exist_ok=True)
        destination = output / "raw_asr.json"
        script = Path(__file__).with_name("fun_asr_infer.py")
        environment = os.environ.copy()
        environment["HF_HUB_OFFLINE"] = "1"
        environment["TRANSFORMERS_OFFLINE"] = "1"
        with (output / "fun_asr.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(self.python), str(script), str(vocals), str(destination),
                 "--model-code", str(self.model_code), "--device", "cpu",
                 "--model-dir", str(self.model_dir),
                 "--language", "粤语" if language == "yue" else "中文"],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                env=environment,
                creationflags=subprocess_creation_flags(),
            )
            try:
                while process.poll() is None:
                    cancellation.raise_if_cancelled()
                    time.sleep(.2)
            except BaseException:
                process.terminate()
                process.wait(timeout=10)
                raise
        if process.returncode or not destination.is_file():
            tail = (output / "fun_asr.log").read_text(encoding="utf-8", errors="replace")[-1000:]
            raise RuntimeError(f"Fun-ASR 识别失败：{tail}")
        return destination
