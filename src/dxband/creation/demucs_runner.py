# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import importlib.metadata
import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dxband.constants import TRACK_FILENAMES, TrackKind
from dxband.creation.cancellation import CancellationToken, CancelledError
from dxband.workers.command import python_module_command, subprocess_creation_flags

DEMUCS_MODEL = "htdemucs_6s"
DEMUCS_REPOSITORY = "adefossez/HTDemucs-6s"
DEMUCS_FILES = ("htdemucs_6s.yaml", "5c90dfd2.safetensors")


class DemucsError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DemucsResult:
    model: str
    version: str
    device: str
    output_dir: Path
    tracks: dict[TrackKind, Path]
    command: tuple[str, ...]


class DemucsRunner:
    def __init__(self, terminate_timeout_seconds: float = 8.0) -> None:
        self.terminate_timeout_seconds = terminate_timeout_seconds

    def run(
        self,
        source_mp3: Path,
        output_root: Path,
        device: str,
        cancellation: CancellationToken,
        on_log: Callable[[str], None],
    ) -> DemucsResult:
        try:
            version = importlib.metadata.version("demucs")
        except importlib.metadata.PackageNotFoundError as exc:
            raise DemucsError("未安装 Demucs，请安装项目的 ai 依赖") from exc

        from huggingface_hub import hf_hub_download

        try:
            for filename in DEMUCS_FILES:
                hf_hub_download(DEMUCS_REPOSITORY, filename, local_files_only=True)
        except Exception as exc:
            raise DemucsError(
                "缺少本机 Demucs htdemucs_6s 权重；请先从 "
                "https://huggingface.co/adefossez/HTDemucs-6s 自行下载到 Hugging Face 缓存"
            ) from exc

        command = python_module_command(
            "demucs",
            [
                "-n",
                f"hf://{DEMUCS_MODEL}",
                "--mp3",
                "--mp3-bitrate",
                "320",
                "--mp3-preset",
                "2",
                "-d",
                device,
                "--out",
                str(output_root),
                str(source_mp3),
            ],
        )
        self._run_process(command, cancellation, on_log)
        track_dir = self._find_track_directory(output_root)
        tracks = {kind: track_dir / filename for kind, filename in TRACK_FILENAMES.items()}
        missing = [path.name for path in tracks.values() if not path.is_file()]
        if missing:
            raise DemucsError(f"Demucs 未生成完整六轨：{', '.join(sorted(missing))}")
        return DemucsResult(
            model=DEMUCS_MODEL,
            version=version,
            device=device,
            output_dir=track_dir,
            tracks=tracks,
            command=tuple(command),
        )

    def _run_process(
        self,
        command: list[str],
        cancellation: CancellationToken,
        on_log: Callable[[str], None],
    ) -> None:
        environment = os.environ.copy()
        environment["HF_HUB_OFFLINE"] = "1"
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            env=environment,
            creationflags=subprocess_creation_flags(),
        )
        lines: queue.Queue[str | None] = queue.Queue()

        def read_lines() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.put(line.rstrip("\r\n"))
            lines.put(None)

        reader = threading.Thread(target=read_lines, name="demucs-output", daemon=True)
        reader.start()
        reader_finished = False
        terminate_deadline: float | None = None
        while not reader_finished or process.poll() is None:
            if cancellation.is_cancelled and process.poll() is None:
                if terminate_deadline is None:
                    process.terminate()
                    terminate_deadline = time.monotonic() + self.terminate_timeout_seconds
                elif time.monotonic() >= terminate_deadline:
                    process.kill()
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                reader_finished = True
            elif line:
                on_log(line)

        return_code = process.wait()
        if cancellation.is_cancelled:
            raise CancelledError("六轨分离已取消")
        if return_code != 0:
            raise DemucsError(f"Demucs 异常退出，返回码：{return_code}")

    @staticmethod
    def _find_track_directory(output_root: Path) -> Path:
        model_root = output_root / DEMUCS_MODEL
        if not model_root.is_dir():
            raise DemucsError(f"Demucs 未生成固定模型目录：{DEMUCS_MODEL}")
        candidates = sorted(path for path in model_root.iterdir() if path.is_dir())
        if len(candidates) != 1:
            raise DemucsError("无法确定 Demucs 六轨输出目录")
        return candidates[0]
