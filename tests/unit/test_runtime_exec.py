# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

from dxband.runtime_exec import EXEC_FLAG, maybe_handle_exec, run_exec


def test_maybe_handle_exec_ignores_normal_launch() -> None:
    assert maybe_handle_exec(["dx-band"]) is None
    assert maybe_handle_exec(["dx-band", "--help"]) is None


def test_run_exec_evaluates_code(capsys) -> None:
    code = run_exec(["-c", "print('ok-from-exec')"])
    assert code == 0
    assert "ok-from-exec" in capsys.readouterr().out


def test_run_exec_runs_module(tmp_path: Path, capsys) -> None:
    package = tmp_path / "sample_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text(
        "print('module-main')\n",
        encoding="utf-8",
    )
    import sys

    sys.path.insert(0, str(tmp_path))
    try:
        code = run_exec(["-m", "sample_pkg"])
    finally:
        sys.path.remove(str(tmp_path))
    assert code == 0
    assert "module-main" in capsys.readouterr().out


def test_run_exec_runs_script(tmp_path: Path, capsys) -> None:
    script = tmp_path / "helper.py"
    script.write_text("print('script-main')\n", encoding="utf-8")
    code = run_exec([str(script)])
    assert code == 0
    assert "script-main" in capsys.readouterr().out


def test_maybe_handle_exec_dispatches_flag() -> None:
    code = maybe_handle_exec(["dx-band", EXEC_FLAG, "-c", "print(2+2)"])
    assert code == 0
