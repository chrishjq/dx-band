# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

import pytest

from dxband.creation import model_download
from dxband.creation.model_download import (
    format_download_error,
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

    def fake_urlopen(url: object, timeout: int = 60) -> FakeResponse:
        target = url.full_url if hasattr(url, "full_url") else str(url)
        relative = target.rsplit("/main/", 1)[1]
        return FakeResponse(payloads[relative])

    monkeypatch.setattr(
        model_download,
        "default_application_data_root",
        lambda: tmp_path / "app-data",
    )
    digest = __import__("hashlib").sha256(payloads["model.py"]).hexdigest()
    monkeypatch.setattr(model_download, "MODEL_CODE_SHA256", digest)
    monkeypatch.setattr(
        "dxband.services.download_mirrors.urllib.request.urlopen",
        fake_urlopen,
    )

    reports: list[tuple[str, float | None]] = []
    path = model_download._download_fun_asr_code(
        lambda stage, ratio: reports.append((stage, ratio)),
        "歌词识别模型",
    )
    assert path == root / "model.py"
    assert model_download.fun_asr_code_bundle_present(root)
    assert reports
    assert any("组件" in stage for stage, _ratio in reports)
    assert any(isinstance(ratio, float) for _stage, ratio in reports)


def test_format_download_error_summarizes_network_failures() -> None:
    assert format_download_error(TimeoutError()) == "连接超时，请检查网络后重试"
    assert (
        format_download_error(model_download.urllib.error.URLError("timed out"))
        == "连接超时，请检查网络后重试"
    )
    assert (
        format_download_error(
            model_download.urllib.error.URLError("Connection refused")
        )
        == "无法连接下载服务器"
    )
    assert (
        format_download_error(RuntimeError("下载歌词识别模型失败：连接超时，请检查网络后重试"))
        == "下载歌词识别模型失败：连接超时，请检查网络后重试"
    )
    hub_snapshot_error = (
        "An error happened while trying to locate the files on the Hub and we "
        "cannot find the appropriate snapshot folder for the specified revision "
        "on the local disk. Please check your internet connection and try again."
    )
    assert (
        format_download_error(RuntimeError(hub_snapshot_error))
        == "无法连接模型下载服务，请检查网络或关闭本地代理后重试"
    )
    assert (
        format_download_error(OSError("Unable to connect to proxy"))
        == "本地代理不可用，请关闭代理后重试"
    )
    long_message = "x" * 200
    summarized = format_download_error(ValueError(long_message))
    assert summarized.endswith("…")
    assert len(summarized) == 178


def test_fun_asr_model_download_reports_modelscope_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import sys
    import types

    destination = tmp_path / "app-data" / "Fun-ASR" / "model"
    reports: list[tuple[str, float | None]] = []
    callback_cls_holder: list[type] = []

    def fake_ms_download(
        model_id: str,
        local_dir: str,
        progress_callbacks: list[type] | None = None,
    ) -> str:
        assert model_id == model_download.FUN_ASR_MODELSCOPE_ID
        assert progress_callbacks
        callback_cls_holder.extend(progress_callbacks)
        callback = progress_callbacks[0]("weights.bin", 100)
        callback.update(40)
        callback.update(60)
        callback.end()
        root = Path(local_dir)
        root.mkdir(parents=True, exist_ok=True)
        (root / "configuration.json").write_text("{}", encoding="utf-8")
        return str(root)

    class ProgressCallback:
        def __init__(self, filename: str, file_size: int) -> None:
            self.filename = filename
            self.file_size = file_size

        def update(self, size: int) -> None:
            return None

        def end(self) -> None:
            return None

    modelscope = types.ModuleType("modelscope")
    hub = types.ModuleType("modelscope.hub")
    snapshot_mod = types.ModuleType("modelscope.hub.snapshot_download")
    callback_mod = types.ModuleType("modelscope.hub.callback")
    snapshot_mod.snapshot_download = fake_ms_download  # type: ignore[attr-defined]
    callback_mod.ProgressCallback = ProgressCallback  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "modelscope", modelscope)
    monkeypatch.setitem(sys.modules, "modelscope.hub", hub)
    monkeypatch.setitem(sys.modules, "modelscope.hub.snapshot_download", snapshot_mod)
    monkeypatch.setitem(sys.modules, "modelscope.hub.callback", callback_mod)
    monkeypatch.setattr(
        model_download,
        "default_application_data_root",
        lambda: tmp_path / "app-data",
    )

    path = model_download._download_fun_asr_model(
        lambda stage, ratio: reports.append((stage, ratio)),
        "歌词识别模型",
    )
    assert path == destination
    assert callback_cls_holder
    assert any(isinstance(ratio, float) and ratio >= 0.1 for _stage, ratio in reports)
    assert reports[-1] == ("歌词识别模型已就绪", 1.0)


def test_stem_separation_uses_private_mirror_only_after_public_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reports: list[tuple[str, float | None]] = []
    calls: list[str] = []

    def fail_public(*_args: object, **_kwargs: object) -> object:
        calls.append("public")
        raise RuntimeError("hf unavailable")

    def fake_private(
        repository: str,
        revision: str,
        files: object,
        progress: object,
        label: str,
    ) -> Path:
        del progress, label
        calls.append("private")
        assert repository == model_download.DEMUCS_REPOSITORY
        assert revision == model_download.DEMUCS_REVISION
        root = tmp_path / "hub" / "snapshots" / revision
        root.mkdir(parents=True)
        for name in files:  # type: ignore[union-attr]
            (root / name).write_text("ok", encoding="utf-8")
        return root

    monkeypatch.setattr(model_download, "_huggingface_call", fail_public)
    monkeypatch.setattr(model_download, "_download_from_private_mirror", fake_private)
    monkeypatch.setattr(
        model_download,
        "default_application_data_root",
        lambda: tmp_path / "app-data",
    )

    path = model_download._download_stem_separation(
        lambda stage, ratio: reports.append((stage, ratio)),
        "音轨分离模型",
    )
    assert calls == ["public", "private"]
    assert path.name == model_download.DEMUCS_REVISION
    assert any("备用节点" in stage for stage, _ in reports)
    assert reports[-1] == ("音轨分离模型已就绪", 1.0)


def test_score_analysis_prefers_modelscope_before_huggingface(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reports: list[tuple[str, float | None]] = []
    calls: list[str] = []

    def fake_ms(
        model_id: str,
        *,
        local_dir: Path,
        progress: object,
        stage: str,
        ratio_span: tuple[float, float],
        ignore_patterns: object = None,
        revision: str = "master",
    ) -> Path:
        del progress, stage, ratio_span, ignore_patterns, revision
        calls.append(model_id)
        root = Path(local_dir)
        root.mkdir(parents=True, exist_ok=True)
        (root / "config.json").write_text("{}", encoding="utf-8")
        (root / "model.safetensors").write_bytes(b"weights")
        return root

    def fail_hf(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("Hugging Face fallback should not run when ModelScope succeeds")

    monkeypatch.setattr(
        model_download,
        "default_application_data_root",
        lambda: tmp_path / "app-data",
    )
    monkeypatch.setattr(model_download, "_modelscope_snapshot_download", fake_ms)
    monkeypatch.setattr(model_download, "_download_score_analysis_via_huggingface", fail_hf)

    path = model_download._download_score_analysis(
        lambda stage, ratio: reports.append((stage, ratio)),
        "谱面分析模型",
    )
    assert path == tmp_path / "app-data" / "SheetSage2" / "model"
    assert calls == [
        model_download.SHEETSAGE2_MODELSCOPE_ID,
        model_download.MERT_MODELSCOPE_ID,
    ]
    assert any(stage.startswith("正在连接魔搭节点") for stage, _ in reports)
    assert reports[-1] == ("谱面分析模型已就绪", 1.0)
    assert (tmp_path / "app-data" / "SheetSage2" / "mert" / "model.safetensors").is_file()


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
