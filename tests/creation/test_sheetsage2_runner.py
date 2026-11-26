# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import os
from pathlib import Path

import pytest

from dxband.creation import model_download
from dxband.creation.cancellation import CancellationToken
from dxband.creation.sheetsage2_runner import SheetSage2Runner


def test_check_ready_picks_up_model_downloaded_after_construction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.delenv("DX_BAND_SHEETSAGE2_MODEL_DIR", raising=False)
    monkeypatch.setattr(
        model_download,
        "default_application_data_root",
        lambda: tmp_path / "app-data",
    )
    monkeypatch.setattr(
        "dxband.creation.sheetsage2_runner.default_application_data_root",
        lambda: tmp_path / "app-data",
    )
    runner = SheetSage2Runner(python=tmp_path / "python")
    assert runner.model is None
    with pytest.raises(RuntimeError, match="未配置 SheetSage2 模型目录"):
        runner.check_ready()

    model_dir = tmp_path / "app-data" / "SheetSage2" / "model"
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "python").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "python").chmod(0o755)

    def fake_run(*_args, **_kwargs):
        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr(
        "dxband.creation.sheetsage2_runner.subprocess.run",
        fake_run,
    )
    runner.check_ready()
    assert runner.model == model_dir
    assert runner._ready is True


def test_transcription_uses_external_model_cache(monkeypatch, tmp_path: Path) -> None:
    bundled_cache = tmp_path / "bundled-cache"
    external_cache = tmp_path / "external-cache"
    monkeypatch.setenv("HF_HOME", str(bundled_cache))
    monkeypatch.setenv("HF_HUB_CACHE", str(bundled_cache / "hub"))
    monkeypatch.setenv("DX_BAND_SHEETSAGE2_HF_HOME", str(external_cache))
    observed: dict[str, str] = {}

    def fake_process(
        _command: list[str], _cancellation: CancellationToken,
        _log_path: Path, environment: dict[str, str] | None = None,
    ) -> None:
        assert environment is not None
        observed.update(environment)
        (tmp_path / "events.json").write_text("{}", encoding="utf-8")

    runner = SheetSage2Runner(python=tmp_path / "python", model=tmp_path / "model")
    monkeypatch.setattr(runner, "_run_process", fake_process)
    runner._transcribe(tmp_path / "source.wav", tmp_path, CancellationToken())

    assert observed["HF_HOME"] == str(external_cache)
    assert observed["HF_HUB_CACHE"] == str(external_cache / "hub")
    assert observed["HF_HUB_OFFLINE"] == "1"
    assert os.environ["HF_HOME"] == str(bundled_cache)
