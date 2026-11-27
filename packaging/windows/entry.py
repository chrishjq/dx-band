# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""PyInstaller entry point for the Windows portable build."""

from dxband.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
