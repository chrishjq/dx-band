# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import importlib.util
import subprocess
from dataclasses import dataclass

from dxband.services.ffmpeg_tools import resolve_ffmpeg, resolve_ffprobe
from dxband.workers.command import python_code_command, subprocess_creation_flags


@dataclass(frozen=True, slots=True)
class EnvironmentStatus:
    ffmpeg_available: bool
    ffprobe_available: bool
    demucs_available: bool
    ctc_segmentation_available: bool
    torch_available: bool
    cuda_usable: bool
    mps_usable: bool


class EnvironmentChecker:
    def inspect(self) -> EnvironmentStatus:
        torch_available = importlib.util.find_spec("torch") is not None
        return EnvironmentStatus(
            ffmpeg_available=resolve_ffmpeg() is not None,
            ffprobe_available=resolve_ffprobe() is not None,
            demucs_available=importlib.util.find_spec("demucs") is not None,
            ctc_segmentation_available=(
                importlib.util.find_spec("ctc_segmentation") is not None
            ),
            torch_available=torch_available,
            cuda_usable=torch_available and self._probe_cuda(),
            mps_usable=torch_available and self._probe_mps(),
        )

    def select_torch_device(self, preference: str = "auto") -> str:
        if preference == "cpu":
            return "cpu"
        if preference not in {"auto", "cuda", "mps"}:
            raise ValueError(f"不支持的计算设备：{preference}")
        if preference in {"auto", "cuda"} and self._probe_cuda():
            return "cuda"
        if preference in {"auto", "mps"} and self._probe_mps():
            return "mps"
        return "cpu"

    @staticmethod
    def _probe_cuda() -> bool:
        code = (
            "import torch; "
            "assert torch.cuda.is_available(); "
            "x=torch.ones((8,8), device='cuda'); "
            "y=x@x; "
            "assert float(y[0,0].cpu()) == 8.0; "
            "torch.cuda.synchronize()"
        )
        return EnvironmentChecker._run_torch_probe(code)

    @staticmethod
    def _probe_mps() -> bool:
        code = (
            "import torch; "
            "assert torch.backends.mps.is_available(); "
            "x=torch.ones((8,8), device='mps'); "
            "y=x@x; "
            "assert float(y[0,0].cpu()) == 8.0; "
            "torch.mps.synchronize()"
        )
        return EnvironmentChecker._run_torch_probe(code)

    @staticmethod
    def _run_torch_probe(code: str) -> bool:
        try:
            completed = subprocess.run(
                python_code_command(code),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                creationflags=subprocess_creation_flags(),
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0
