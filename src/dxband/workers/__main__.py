# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from dxband.workers.protocol import WorkerEvent, encode_event
from dxband.workers.separate_worker import run_separation


def _emit(event: WorkerEvent) -> None:
    print(encode_event(event), flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dx-band-worker")
    subparsers = parser.add_subparsers(dest="worker", required=True)
    separate = subparsers.add_parser("separate", help="执行 Demucs 六轨分离")
    separate.add_argument("--source", type=Path, required=True)
    separate.add_argument("--output", type=Path, required=True)
    separate.add_argument("--device", choices=("cuda", "mps", "cpu"), required=True)
    arguments = parser.parse_args(argv)
    if arguments.worker == "separate":
        return run_separation(arguments.source, arguments.output, arguments.device, _emit)
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
