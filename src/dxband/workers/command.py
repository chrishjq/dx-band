# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import subprocess
import sys
from collections.abc import Sequence


def subprocess_creation_flags() -> int:
    """Windows 后台 worker 保留输出管道，但不弹出控制台窗口。"""
    if sys.platform == "win32":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def worker_command(worker: str, arguments: Sequence[str]) -> list[str]:
    """通过当前 Python 环境启动源码 worker 子进程。"""
    return [sys.executable, "-m", "dxband.workers", worker, *arguments]


def python_module_command(module: str, arguments: Sequence[str]) -> list[str]:
    """通过当前 Python 环境启动模块命令。"""
    return [sys.executable, "-m", module, *arguments]
