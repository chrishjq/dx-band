# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Re-enter the frozen application binary as a CLI helper process.

Packaged builds cannot rely on ``python -m`` / ``python -c``. Callers append
``--dx-band-exec`` plus a normal Python argv shape; this module runs that work
before the Qt UI starts.
"""

from __future__ import annotations

import runpy
import sys
from collections.abc import Sequence

EXEC_FLAG = "--dx-band-exec"


def maybe_handle_exec(argv: Sequence[str] | None = None) -> int | None:
    """Handle ``--dx-band-exec`` when present; otherwise return ``None``."""
    arguments = list(sys.argv if argv is None else argv)
    if len(arguments) < 2 or arguments[1] != EXEC_FLAG:
        return None
    return run_exec(arguments[2:])


def run_exec(argv: Sequence[str]) -> int:
    if not argv:
        print("dx-band: --dx-band-exec 缺少参数", file=sys.stderr)
        return 2

    if argv[0] == "-m":
        if len(argv) < 2:
            print("dx-band: -m 需要模块名", file=sys.stderr)
            return 2
        module = argv[1]
        sys.argv = [module, *argv[2:]]
        runpy.run_module(module, run_name="__main__")
        return 0

    if argv[0] == "-c":
        if len(argv) < 2:
            print("dx-band: -c 需要代码", file=sys.stderr)
            return 2
        sys.argv = ["-c", *argv[2:]]
        exec(argv[1], {"__name__": "__main__"})
        return 0

    script = argv[0]
    sys.argv = list(argv)
    runpy.run_path(script, run_name="__main__")
    return 0
