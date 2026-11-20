# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import os
from pathlib import Path

from dxband.creation.cancellation import CancellationToken
from dxband.creation.sheetsage2_runner import SheetSage2Runner


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
