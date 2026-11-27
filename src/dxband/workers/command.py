# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from dxband.runtime_exec import EXEC_FLAG
from dxband.services.bundle_paths import is_frozen


def subprocess_creation_flags() -> int:
    """Windows 后台 worker 保留输出管道，但不弹出控制台窗口。"""
    if sys.platform == "win32":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def _python_prefix(python: str | Path | None = None) -> list[str]:
    executable = str(python) if python is not None else sys.executable
    prefix = [executable]
    if executable == sys.executable and is_frozen():
        prefix.append(EXEC_FLAG)
    return prefix


def worker_command(
    worker: str,
    arguments: Sequence[str],
    *,
    python: str | Path | None = None,
) -> list[str]:
    """通过当前 Python 环境或冻结应用启动 worker 子进程。"""
    return [*_python_prefix(python), "-m", "dxband.workers", worker, *arguments]


def python_module_command(
    module: str,
    arguments: Sequence[str],
    *,
    python: str | Path | None = None,
) -> list[str]:
    """通过当前 Python 环境或冻结应用启动模块命令。"""
    return [*_python_prefix(python), "-m", module, *arguments]


def python_code_command(
    code: str,
    *,
    python: str | Path | None = None,
) -> list[str]:
    """通过当前 Python 环境或冻结应用执行一段代码。"""
    return [*_python_prefix(python), "-c", code]


def python_script_command(
    script: Path | str,
    arguments: Sequence[str],
    *,
    python: str | Path | None = None,
) -> list[str]:
    """通过当前 Python 环境或冻结应用执行脚本文件。"""
    return [*_python_prefix(python), str(script), *arguments]
