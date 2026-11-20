# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import pytest

from dxband.services.environment_check import EnvironmentChecker


def test_auto_device_prefers_cuda_then_mps(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = EnvironmentChecker()
    monkeypatch.setattr(checker, "_probe_cuda", lambda: True)
    monkeypatch.setattr(checker, "_probe_mps", lambda: True)

    assert checker.select_torch_device("auto") == "cuda"


def test_auto_device_uses_mps_when_cuda_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = EnvironmentChecker()
    monkeypatch.setattr(checker, "_probe_cuda", lambda: False)
    monkeypatch.setattr(checker, "_probe_mps", lambda: True)

    assert checker.select_torch_device("auto") == "mps"


def test_requested_unavailable_accelerator_falls_back_to_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = EnvironmentChecker()
    monkeypatch.setattr(checker, "_probe_cuda", lambda: False)
    monkeypatch.setattr(checker, "_probe_mps", lambda: False)

    assert checker.select_torch_device("cuda") == "cpu"
    assert checker.select_torch_device("mps") == "cpu"
