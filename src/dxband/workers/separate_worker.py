# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import shutil
import signal
from pathlib import Path

from dxband.creation.cancellation import CancellationToken, CancelledError
from dxband.creation.demucs_runner import DEMUCS_MODEL, DemucsError, DemucsRunner
from dxband.workers.protocol import ErrorEvent, LogEvent, ResultEvent, StageEvent


def run_separation(source: Path, output: Path, device: str, emit: object) -> int:
    if not callable(emit):
        raise TypeError("emit 必须可调用")
    cancellation = CancellationToken()

    def cancel_worker(_signum: int, _frame: object) -> None:
        cancellation.cancel()

    signal.signal(signal.SIGTERM, cancel_worker)
    signal.signal(signal.SIGINT, cancel_worker)
    runner = DemucsRunner()
    active_device = device
    try:
        emit(StageEvent(value="separating"))
        try:
            result = runner.run(
                source,
                output,
                active_device,
                cancellation,
                lambda message: emit(LogEvent(message=message)),
            )
        except DemucsError:
            if active_device == "cpu" or cancellation.is_cancelled:
                raise
            emit(
                LogEvent(
                    level="warning",
                    message=f"{active_device.upper()} 分离失败，正在回退到 CPU",
                )
            )
            model_output = output / DEMUCS_MODEL
            if model_output.is_dir():
                shutil.rmtree(model_output)
            active_device = "cpu"
            result = runner.run(
                source,
                output,
                active_device,
                cancellation,
                lambda message: emit(LogEvent(message=message)),
            )
        emit(
            ResultEvent(
                path=str(result.output_dir),
                data={
                    "model": result.model,
                    "version": result.version,
                    "device": result.device,
                    "tracks": {kind.value: str(path) for kind, path in result.tracks.items()},
                    "command": list(result.command),
                },
            )
        )
        return 0
    except CancelledError as exc:
        emit(ErrorEvent(message=str(exc)))
        return 130
    except Exception as exc:
        emit(ErrorEvent(message="六轨分离失败", details=str(exc)))
        return 1
