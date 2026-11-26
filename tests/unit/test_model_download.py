# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

import pytest

from dxband.creation import model_download
from dxband.creation.model_download import (
    list_model_role_status,
    missing_model_download_key,
    model_role,
)


def test_model_roles_use_functional_labels_only() -> None:
    labels = {role.label for role in model_download.MODEL_ROLES}
    assert "节拍模型" in labels
    assert "歌词识别模型" in labels
    assert "中文歌词适配模型" in labels
    joined = " ".join(labels)
    assert "SheetSage2" not in joined
    assert "Demucs" not in joined
    assert "Fun-ASR" not in joined
    assert "Beat This" not in joined


def test_missing_model_key_maps_backend_errors_to_roles() -> None:
    assert missing_model_download_key("未配置 SheetSage2 模型目录") == "score_analysis"
    assert missing_model_download_key("Beat This! 模型文件不存在：x") == "beat"
    assert missing_model_download_key("缺少本机 Demucs htdemucs_6s 权重") == "stem_separation"
    assert missing_model_download_key("缺少 Fun-ASR 模型代码") == "lyric_recognition"
    assert missing_model_download_key("其他错误") is None


def test_fun_asr_code_download_includes_companion_modules(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    root = tmp_path / "app-data" / "Fun-ASR"
    payloads = {
        "model.py": b"print('model')\n",
        "ctc.py": b"class CTC: ...\n",
        "tools/__init__.py": b"",
        "tools/utils.py": b"def forced_align(*args): ...\n",
    }

    class FakeResponse:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_urlopen(url: str, timeout: int = 60) -> FakeResponse:
        relative = url.rsplit("/main/", 1)[1]
        return FakeResponse(payloads[relative])

    monkeypatch.setattr(
        model_download,
        "default_application_data_root",
        lambda: tmp_path / "app-data",
    )
    monkeypatch.setattr(model_download, "MODEL_CODE_SHA256", __import__("hashlib").sha256(payloads["model.py"]).hexdigest())
    monkeypatch.setattr(model_download.urllib.request, "urlopen", fake_urlopen)

    path = model_download._download_fun_asr_code(lambda *_args: None, "歌词识别模型")
    assert path == root / "model.py"
    assert model_download.fun_asr_code_bundle_present(root)


def test_list_model_role_status_reports_managed_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("DX_BAND_SHEETSAGE2_MODEL_DIR", raising=False)
    monkeypatch.delenv("DX_BAND_BEAT_THIS_CHECKPOINT", raising=False)
    monkeypatch.delenv("DX_BAND_FUN_ASR_MODEL_CODE", raising=False)
    monkeypatch.delenv("DX_BAND_FUN_ASR_MODEL_DIR", raising=False)
    monkeypatch.setattr(
        model_download,
        "default_application_data_root",
        lambda: tmp_path / "app-data",
    )
    monkeypatch.setattr(model_download, "_demucs_ready", lambda: False)
    monkeypatch.setattr(model_download, "_mert_ready", lambda: False)
    monkeypatch.setattr(
        model_download, "_aligner_ready", lambda *_args, **_kwargs: False
    )

    statuses = {item.key: item for item in list_model_role_status()}
    assert statuses["beat"].ready is False
    assert statuses["beat"].label == "节拍模型"

    checkpoint = tmp_path / "app-data" / "BeatThis" / "model" / "final0.ckpt"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"ckpt")
    statuses = {item.key: item for item in list_model_role_status()}
    assert statuses["beat"].ready is True
    assert model_role("beat").detail == "分析拍点与小节"
