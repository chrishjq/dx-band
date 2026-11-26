# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Download creation models into local default locations after an explicit request.

UI copy uses functional roles only. Upstream licenses still apply; see
MODEL_NOTICES.md and docs/model_self_setup.md.
"""

from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from dxband.creation.ctc_lyrics_aligner import (
    EN_REPOSITORY,
    EN_REVISION,
    MODEL_FILES,
    MODEL_REPOSITORY,
    MODEL_REVISION,
    YUE_FILES,
    YUE_REPOSITORY,
    YUE_REVISION,
)
from dxband.creation.demucs_runner import DEMUCS_FILES, DEMUCS_REPOSITORY
from dxband.services.application_paths import default_application_data_root

ProgressCallback = Callable[[str, float | None], None]

SHEETSAGE2_REPOSITORY = "m-a-p/SheetSage2"
MERT_REPOSITORY = "m-a-p/MERT-v2-FullSong"
BEAT_THIS_CHECKPOINT_URL = (
    "https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt"
)
BEAT_THIS_CHECKPOINT_SHA256 = (
    "8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331"
)
FUN_ASR_CODE_BASE_URL = (
    "https://raw.githubusercontent.com/FunAudioLLM/Fun-ASR/main/"
)
FUN_ASR_CODE_FILES = (
    "model.py",
    "ctc.py",
    "tools/__init__.py",
    "tools/utils.py",
)
FUN_ASR_MODELSCOPE_ID = "FunAudioLLM/Fun-ASR-Nano-2512"
MODEL_CODE_SHA256 = "223e24104889df1bd5d7f85fa7584233ad31936ea43b0c57afde37a3d9c90da5"


@dataclass(frozen=True, slots=True)
class ModelRole:
    key: str
    label: str
    detail: str


MODEL_ROLES: tuple[ModelRole, ...] = (
    ModelRole("stem_separation", "音轨分离模型", "把歌曲拆成六轨"),
    ModelRole("beat", "节拍模型", "分析拍点与小节"),
    ModelRole("score_analysis", "谱面分析模型", "分析音符与和弦"),
    ModelRole("lyric_recognition", "歌词识别模型", "从人声识别歌词文字"),
    ModelRole("lyric_align_zh", "中文歌词适配模型", "对齐国语歌词时间"),
    ModelRole("lyric_align_en", "英文歌词适配模型", "对齐英文歌词时间"),
    ModelRole("lyric_align_yue", "粤语歌词适配模型", "对齐粤语歌词时间"),
)

_ROLE_BY_KEY = {role.key: role for role in MODEL_ROLES}

_ERROR_PREFIX_TO_KEY: tuple[tuple[tuple[str, ...], str], ...] = (
    (("未配置 SheetSage2 模型目录",), "score_analysis"),
    (("未配置 Beat This! 模型文件", "Beat This! 模型文件不存在"), "beat"),
    (("缺少本机 Demucs htdemucs_6s 权重",), "stem_separation"),
    (
        ("缺少 Fun-ASR 模型代码", "缺少本机 Fun-ASR 模型", "Fun-ASR 识别失败"),
        "lyric_recognition",
    ),
    (("缺少本机zh歌词对齐模型", "缺少zh歌词对齐模型文件"), "lyric_align_zh"),
    (("缺少本机en歌词对齐模型", "缺少en歌词对齐模型文件"), "lyric_align_en"),
    (("缺少本机yue歌词对齐模型", "缺少yue歌词对齐模型文件"), "lyric_align_yue"),
)


@dataclass(frozen=True, slots=True)
class ModelRoleStatus:
    key: str
    label: str
    detail: str
    ready: bool


def model_role(key: str) -> ModelRole:
    try:
        return _ROLE_BY_KEY[key]
    except KeyError as exc:
        raise ValueError(f"未知模型角色：{key}") from exc


def missing_model_download_key(backend_message: str) -> str | None:
    """Return the downloadable role key for a known creation missing-model error."""
    for prefixes, key in _ERROR_PREFIX_TO_KEY:
        if backend_message.startswith(prefixes):
            return key
    return None


def sheetsage2_model_dir() -> Path:
    override = os.environ.get("DX_BAND_SHEETSAGE2_MODEL_DIR")
    if override:
        return Path(override).expanduser()
    return default_application_data_root() / "SheetSage2" / "model"


def beat_this_checkpoint_path() -> Path:
    override = os.environ.get("DX_BAND_BEAT_THIS_CHECKPOINT")
    if override:
        return Path(override).expanduser()
    return default_application_data_root() / "BeatThis" / "model" / "final0.ckpt"


def fun_asr_code_path() -> Path:
    override = os.environ.get("DX_BAND_FUN_ASR_MODEL_CODE")
    if override:
        return Path(override).expanduser()
    return default_application_data_root() / "Fun-ASR" / "model.py"


def fun_asr_model_dir() -> Path:
    override = os.environ.get("DX_BAND_FUN_ASR_MODEL_DIR")
    if override:
        return Path(override).expanduser()
    return default_application_data_root() / "Fun-ASR" / "model"


def huggingface_home() -> Path:
    return Path(
        os.environ.get(
            "DX_BAND_SHEETSAGE2_HF_HOME",
            str(Path.home() / ".cache" / "huggingface"),
        )
    ).expanduser()


def list_model_role_status() -> tuple[ModelRoleStatus, ...]:
    return tuple(
        ModelRoleStatus(
            key=role.key,
            label=role.label,
            detail=role.detail,
            ready=_role_is_ready(role.key),
        )
        for role in MODEL_ROLES
    )


def download_missing_model(
    key: str,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Download one role's files into the default local location."""
    role = model_role(key)
    progress = on_progress or (lambda _stage, _ratio: None)
    if key == "score_analysis":
        return _download_score_analysis(progress, role.label)
    if key == "beat":
        return _download_beat(progress, role.label)
    if key == "stem_separation":
        return _download_stem_separation(progress, role.label)
    if key == "lyric_recognition":
        return _download_lyric_recognition(progress, role.label)
    if key == "lyric_align_zh":
        return _download_aligner(
            MODEL_REPOSITORY, MODEL_REVISION, MODEL_FILES, progress, role.label
        )
    if key == "lyric_align_en":
        return _download_aligner(
            EN_REPOSITORY, EN_REVISION, MODEL_FILES, progress, role.label
        )
    return _download_aligner(
        YUE_REPOSITORY, YUE_REVISION, YUE_FILES, progress, role.label
    )


def _role_is_ready(key: str) -> bool:
    if key == "stem_separation":
        return _demucs_ready()
    if key == "beat":
        return beat_this_checkpoint_path().is_file()
    if key == "score_analysis":
        return (sheetsage2_model_dir() / "config.json").is_file() and _mert_ready()
    if key == "lyric_recognition":
        return _fun_asr_code_ready() and _fun_asr_model_ready()
    if key == "lyric_align_zh":
        return _aligner_ready(MODEL_REPOSITORY, MODEL_REVISION, MODEL_FILES)
    if key == "lyric_align_en":
        return _aligner_ready(EN_REPOSITORY, EN_REVISION, MODEL_FILES)
    if key == "lyric_align_yue":
        return _aligner_ready(YUE_REPOSITORY, YUE_REVISION, YUE_FILES)
    return False


def _demucs_ready() -> bool:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        return False
    try:
        for filename in DEMUCS_FILES:
            hf_hub_download(DEMUCS_REPOSITORY, filename, local_files_only=True)
    except Exception:
        return False
    return True


def _mert_ready() -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    try:
        cached = try_to_load_from_cache(
            MERT_REPOSITORY,
            "config.json",
            cache_dir=str(huggingface_home() / "hub"),
        )
    except Exception:
        return False
    return isinstance(cached, str) and Path(cached).is_file()


def _aligner_ready(repository: str, revision: str, files: Sequence[str]) -> bool:
    override_key = {
        MODEL_REPOSITORY: "DX_BAND_ALIGNER_ZH_MODEL_DIR",
        EN_REPOSITORY: "DX_BAND_ALIGNER_EN_MODEL_DIR",
        YUE_REPOSITORY: "DX_BAND_ALIGNER_YUE_MODEL_DIR",
    }[repository]
    override = os.environ.get(override_key)
    if override:
        root = Path(override).expanduser()
        return all((root / name).is_file() for name in files)
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        return False
    try:
        root = Path(
            snapshot_download(
                repository,
                revision=revision,
                allow_patterns=list(files),
                local_files_only=True,
            )
        )
    except Exception:
        return False
    return all((root / name).is_file() for name in files)


def fun_asr_code_bundle_present(root: Path) -> bool:
    return all((root / relative).is_file() for relative in FUN_ASR_CODE_FILES)


def _fun_asr_code_ready() -> bool:
    path = fun_asr_code_path()
    if not path.is_file() or not fun_asr_code_bundle_present(path.parent):
        return False
    if os.environ.get("DX_BAND_FUN_ASR_MODEL_CODE"):
        return True
    return hashlib.sha256(path.read_bytes()).hexdigest() == MODEL_CODE_SHA256


def _fun_asr_model_ready() -> bool:
    root = fun_asr_model_dir()
    return root.is_dir() and any(
        (root / name).is_file() for name in ("configuration.json", "config.yaml")
    )


def _report(progress: ProgressCallback, stage: str, ratio: float | None = None) -> None:
    progress(stage, ratio)


def _require_huggingface_hub() -> object:
    try:
        import huggingface_hub
    except ImportError as exc:
        raise RuntimeError("缺少下载组件，请先安装项目的 ai 依赖") from exc
    return huggingface_hub


def _download_score_analysis(progress: ProgressCallback, label: str) -> Path:
    hub = _require_huggingface_hub()
    destination = default_application_data_root() / "SheetSage2" / "model"
    destination.parent.mkdir(parents=True, exist_ok=True)
    hf_home = huggingface_home()
    hub_cache = hf_home / "hub"
    hub_cache.mkdir(parents=True, exist_ok=True)
    previous_home = os.environ.get("HF_HOME")
    previous_cache = os.environ.get("HF_HUB_CACHE")
    os.environ["HF_HOME"] = str(hf_home)
    os.environ["HF_HUB_CACHE"] = str(hub_cache)
    try:
        _report(progress, f"正在下载{label}", None)
        hub.snapshot_download(SHEETSAGE2_REPOSITORY, local_dir=str(destination))
        _report(progress, f"正在下载{label}依赖组件", None)
        hub.snapshot_download(MERT_REPOSITORY)
    finally:
        if previous_home is None:
            os.environ.pop("HF_HOME", None)
        else:
            os.environ["HF_HOME"] = previous_home
        if previous_cache is None:
            os.environ.pop("HF_HUB_CACHE", None)
        else:
            os.environ["HF_HUB_CACHE"] = previous_cache
    if not (destination / "config.json").is_file():
        raise RuntimeError(f"{label}下载完成但文件不完整")
    _report(progress, f"{label}已就绪", 1.0)
    return destination


def _download_stem_separation(progress: ProgressCallback, label: str) -> Path:
    hub = _require_huggingface_hub()
    paths: list[Path] = []
    for index, filename in enumerate(DEMUCS_FILES):
        _report(
            progress,
            f"正在下载{label}（{index + 1}/{len(DEMUCS_FILES)}）",
            index / len(DEMUCS_FILES),
        )
        paths.append(Path(hub.hf_hub_download(DEMUCS_REPOSITORY, filename)))
    _report(progress, f"{label}已就绪", 1.0)
    return paths[0].parent


def _download_aligner(
    repository: str,
    revision: str,
    files: tuple[str, ...],
    progress: ProgressCallback,
    label: str,
) -> Path:
    hub = _require_huggingface_hub()
    _report(progress, f"正在下载{label}", None)
    root = Path(
        hub.snapshot_download(
            repository,
            revision=revision,
            allow_patterns=list(files),
        )
    )
    missing = [name for name in files if not (root / name).is_file()]
    if missing:
        raise RuntimeError(f"{label}下载不完整")
    _report(progress, f"{label}已就绪", 1.0)
    return root


def _download_beat(progress: ProgressCallback, label: str) -> Path:
    destination = default_application_data_root() / "BeatThis" / "model" / "final0.ckpt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".ckpt.partial")
    _report(progress, f"正在下载{label}", 0.0)
    try:
        with urllib.request.urlopen(BEAT_THIS_CHECKPOINT_URL, timeout=60) as response:
            total = response.headers.get("Content-Length")
            expected = int(total) if total and total.isdigit() else None
            hasher = hashlib.sha256()
            received = 0
            with temporary.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    hasher.update(chunk)
                    received += len(chunk)
                    if expected:
                        _report(
                            progress,
                            f"正在下载{label}",
                            min(0.99, received / expected),
                        )
        if hasher.hexdigest() != BEAT_THIS_CHECKPOINT_SHA256:
            raise RuntimeError(f"{label}校验失败，请稍后重试")
        temporary.replace(destination)
    except urllib.error.URLError as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"下载{label}失败：{exc}") from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    _report(progress, f"{label}已就绪", 1.0)
    return destination


def _download_lyric_recognition(progress: ProgressCallback, label: str) -> Path:
    _download_fun_asr_code(progress, label)
    return _download_fun_asr_model(progress, label)


def _download_fun_asr_code(progress: ProgressCallback, label: str) -> Path:
    root = default_application_data_root() / "Fun-ASR"
    root.mkdir(parents=True, exist_ok=True)
    _report(progress, f"正在下载{label}组件", None)
    written: list[Path] = []
    try:
        for relative in FUN_ASR_CODE_FILES:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".partial")
            with urllib.request.urlopen(
                FUN_ASR_CODE_BASE_URL + relative, timeout=60
            ) as response:
                payload = response.read()
            if relative == "model.py" and (
                hashlib.sha256(payload).hexdigest() != MODEL_CODE_SHA256
            ):
                raise RuntimeError(f"{label}组件版本与当前程序不一致")
            temporary.write_bytes(payload)
            temporary.replace(destination)
            written.append(destination)
    except urllib.error.URLError as exc:
        for path in written:
            path.unlink(missing_ok=True)
        raise RuntimeError(f"下载{label}失败：{exc}") from exc
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return root / "model.py"


def _download_fun_asr_model(progress: ProgressCallback, label: str) -> Path:
    try:
        from modelscope.hub.snapshot_download import snapshot_download as ms_download
    except ImportError as exc:
        raise RuntimeError("缺少下载组件，请先安装项目的 ai 依赖") from exc
    destination = default_application_data_root() / "Fun-ASR" / "model"
    destination.parent.mkdir(parents=True, exist_ok=True)
    _report(progress, f"正在下载{label}", None)
    downloaded = Path(ms_download(FUN_ASR_MODELSCOPE_ID, local_dir=str(destination)))
    if not any(
        (downloaded / name).is_file() for name in ("configuration.json", "config.yaml")
    ):
        raise RuntimeError(f"{label}下载完成但文件不完整")
    _report(progress, f"{label}已就绪", 1.0)
    return downloaded
