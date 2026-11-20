# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import logging
from pathlib import Path

from dxband.services.application_paths import default_log_directory


def configure_logging(log_directory: Path | None = None) -> Path:
    """配置控制台和文件日志。"""
    directory = log_directory or default_log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "application.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )
    return log_path
