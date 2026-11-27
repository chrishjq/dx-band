# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

def main() -> int:
    """启动源码应用，或在冻结包中转发 ``--dx-band-exec`` 子进程。"""

    from dxband.runtime_exec import maybe_handle_exec

    handled = maybe_handle_exec()
    if handled is not None:
        return handled

    from dxband.app import main as application_main

    return application_main()


if __name__ == "__main__":
    raise SystemExit(main())
