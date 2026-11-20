# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

def main() -> int:
    """启动源码应用。"""

    from dxband.app import main as application_main

    return application_main()


if __name__ == "__main__":
    raise SystemExit(main())
