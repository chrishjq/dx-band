# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Download creation models into local default locations after an explicit request.

UI copy uses functional roles only. Upstream licenses still apply; see
MODEL_NOTICES.md and docs/model_self_setup.md.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from dxband.services.download_mirrors import (
    collect_endpoint_errors,
    huggingface_endpoints,
    model_mirror_url,
    urlopen_direct,
    urlopen_with_mirrors,
)

ProgressCallback = Callable[[str, float | None], None]

SHEETSAGE2_REPOSITORY = "m-a-p/SheetSage2"
MERT_REPOSITORY = "m-a-p/MERT-v2-FullSong"
# ModelScope hosts the same repos with mainland CDN for large weights.
SHEETSAGE2_MODELSCOPE_ID = SHEETSAGE2_REPOSITORY
MERT_MODELSCOPE_ID = MERT_REPOSITORY
MODELSCOPE_REVISION = "master"
# SheetSage2 pins this MERT revision in its config; keep HF fallback aligned.
MERT_HF_REVISION = "d8ba1c745e733b3908ce6ad16ebeb17ac7600a42"
DEMUCS_REVISION = "3c5ee475be622df764938de97e4281a7b07ffa58"
# Last-resort static paths on DX_BAND_MODEL_MIRROR (public nodes first).
_MIRROR_RELATIVE_ROOTS: dict[str, str] = {
    DEMUCS_REPOSITORY: "demucs",
    MODEL_REPOSITORY: "aligner-zh",
    EN_REPOSITORY: "aligner-en",
    YUE_REPOSITORY: "aligner-yue",
}
# Skip render/demo assets; inference only needs model code, config, and weights.
SHEETSAGE2_IGNORE_PATTERNS = (
    "render_assets/*",
    "benchmarks/*",
    "assets/*",
    "tests/*",
    "*.png",
    "*.mp3",
)
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


def mert_model_dir() -> Path:
    override = os.environ.get("DX_BAND_MERT_MODEL_DIR")
    if override:
        return Path(override).expanduser()
    return default_application_data_root() / "SheetSage2" / "mert"


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
        root = sheetsage2_model_dir()
        return (
            (root / "config.json").is_file()
            and (root / "model.safetensors").is_file()
            and _mert_ready()
        )
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


def _mert_files_present(root: Path) -> bool:
    return (root / "config.json").is_file() and (root / "model.safetensors").is_file()


def _mert_ready() -> bool:
    if _mert_files_present(mert_model_dir()):
        return True
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    cache_dir = str(huggingface_home() / "hub")
    for revision in (MERT_HF_REVISION, None):
        try:
            cached = try_to_load_from_cache(
                MERT_REPOSITORY,
                "config.json",
                cache_dir=cache_dir,
                revision=revision,
            )
        except Exception:
            continue
        if isinstance(cached, str) and Path(cached).is_file():
            return True
    return False


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


def _known_download_failure_message(text: str, *, exc_name: str = "") -> str | None:
    """Return a localized status line for known hub / proxy failures."""
    if not text:
        return None
    lowered = text.lower()
    if "proxy" in lowered or "unable to connect to proxy" in lowered:
        return "本地代理不可用，请关闭代理后重试"
    if (
        "cannot find the appropriate" in lowered and "snapshot folder" in lowered
    ) or "localentrynotfound" in exc_name.lower():
        return "无法连接模型下载服务，请检查网络或关闭本地代理后重试"
    if "max retries exceeded" in lowered:
        return "无法连接下载服务器，请检查网络后重试"
    return None


def format_download_error(exc: BaseException) -> str:
    """Turn a download exception into a short, user-visible status line."""
    text = str(exc).strip()
    known = _known_download_failure_message(text, exc_name=type(exc).__name__)
    if known is not None:
        return known
    if isinstance(exc, RuntimeError):
        if text:
            return text
    if isinstance(exc, urllib.error.HTTPError):
        return f"服务器返回 HTTP {exc.code}"
    if isinstance(exc, TimeoutError):
        return "连接超时，请检查网络后重试"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        detail = str(reason).strip() if reason is not None else str(exc).strip()
        lowered = detail.lower()
        if "timed out" in lowered or "timeout" in lowered:
            return "连接超时，请检查网络后重试"
        if "name or service not known" in lowered or "nodename nor servname" in lowered:
            return "无法解析下载地址，请检查网络或 DNS"
        if "connection refused" in lowered:
            return "无法连接下载服务器"
        if "certificate" in lowered or "ssl" in lowered:
            return "安全连接失败，请检查系统时间或网络代理"
        return detail or "网络连接失败"
    if not text:
        return "请稍后重试或检查网络"
    # Keep the first line only; hub libraries often dump multi-line stacks.
    first_line = text.splitlines()[0].strip()
    if len(first_line) > 180:
        return first_line[:177] + "…"
    return first_line


def _require_huggingface_hub() -> object:
    try:
        import huggingface_hub
    except ImportError as exc:
        raise RuntimeError("缺少下载组件，请先安装项目的 ai 依赖") from exc
    return huggingface_hub


def _prepare_huggingface_runtime() -> None:
    """Prefer mirror-friendly HTTP downloads over Xet / transfer helpers."""
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")


@contextlib.contextmanager
def _without_process_proxies() -> Iterator[None]:
    """Ignore process and system proxies so a stopped local proxy cannot hang downloads.

    Clearing HTTP(S)_PROXY alone is not enough: ``requests`` may still pick up
    proxies via ``trust_env`` / macOS system settings. Force Hugging Face Hub
    sessions to use ``trust_env=False`` for the duration of the download.
    """
    keys = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    )
    saved = {key: os.environ.pop(key, None) for key in keys}
    restore_backend: Callable[[], None] | None = None
    try:
        import requests
        from huggingface_hub.utils import (  # type: ignore[import-untyped]
            configure_http_backend,
        )
        from huggingface_hub.utils import _http as hf_http

        previous_factory = hf_http._GLOBAL_BACKEND_FACTORY

        def _direct_backend_factory() -> requests.Session:
            session = requests.Session()
            session.trust_env = False
            session.proxies = {}
            return session

        configure_http_backend(_direct_backend_factory)

        def _restore() -> None:
            configure_http_backend(previous_factory)

        restore_backend = _restore
    except Exception:
        restore_backend = None
    try:
        yield
    finally:
        if restore_backend is not None:
            try:
                restore_backend()
            except Exception:
                pass
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value


def _reset_huggingface_sessions() -> None:
    try:
        from huggingface_hub.utils import reset_sessions

        reset_sessions()
    except Exception:
        return


def _huggingface_call(operation_name: str, **kwargs: object) -> object:
    """Call a huggingface_hub download helper across China-reachable endpoints."""
    _prepare_huggingface_runtime()
    hub = _require_huggingface_hub()
    operation = getattr(hub, operation_name)
    errors: list[BaseException] = []
    with _without_process_proxies():
        for endpoint in huggingface_endpoints():
            previous = os.environ.get("HF_ENDPOINT")
            os.environ["HF_ENDPOINT"] = endpoint
            try:
                _reset_huggingface_sessions()
                try:
                    return operation(**kwargs, endpoint=endpoint)
                except TypeError as exc:
                    if "endpoint" not in str(exc):
                        raise
                    return operation(**kwargs)
            except Exception as exc:
                errors.append(exc)
            finally:
                if previous is None:
                    os.environ.pop("HF_ENDPOINT", None)
                else:
                    os.environ["HF_ENDPOINT"] = previous
    summarized = format_download_error(Exception(collect_endpoint_errors(errors)))
    raise RuntimeError(summarized) from (errors[-1] if errors else None)


def _huggingface_tqdm_class(
    progress: ProgressCallback,
    stage: str,
    ratio_span: tuple[float, float],
) -> type:
    hub = _require_huggingface_hub()
    utils = getattr(hub, "utils", None)
    tqdm_base = getattr(utils, "tqdm", None) if utils is not None else None
    if tqdm_base is None:
        from tqdm.auto import tqdm as tqdm_base  # type: ignore[import-untyped,no-redef]
    start, end = ratio_span
    # Track the most recent byte-oriented bar so large single-file downloads move.
    state = {"best_fraction": 0.0}

    class _ReportingTqdm(tqdm_base):  # type: ignore[valid-type,misc]
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self._emit()

        def update(self, n: float | None = 1) -> None:
            super().update(n)
            self._emit()

        def _emit(self) -> None:
            total = getattr(self, "total", None)
            current = getattr(self, "n", 0) or 0
            if not total:
                _report(progress, stage, None)
                return
            fraction = min(1.0, float(current) / float(total))
            # Prefer denser byte bars over coarse "files fetched" bars.
            unit = str(getattr(self, "unit", "") or "")
            if unit in {"B", "b"} or total >= 1024 * 1024:
                state["best_fraction"] = max(state["best_fraction"], fraction)
                fraction = state["best_fraction"]
            elif fraction < state["best_fraction"]:
                fraction = state["best_fraction"]
            _report(progress, stage, start + (end - start) * fraction)

    return _ReportingTqdm


@contextlib.contextmanager
def _huggingface_progress(
    progress: ProgressCallback,
    stage: str,
    ratio_span: tuple[float, float],
) -> Iterator[type]:
    """Patch hub tqdm so both file-count and byte bars report to Settings."""
    reporting = _huggingface_tqdm_class(progress, stage, ratio_span)
    patches: list[tuple[Any, str, Any]] = []
    for module_name in (
        "huggingface_hub.utils",
        "huggingface_hub.utils.tqdm",
        "huggingface_hub.file_download",
        "huggingface_hub._snapshot_download",
    ):
        try:
            module: Any = __import__(module_name, fromlist=["*"])
        except ImportError:
            continue
        if hasattr(module, "tqdm"):
            patches.append((module, "tqdm", module.tqdm))
            module.tqdm = reporting
        if hasattr(module, "hf_tqdm"):
            patches.append((module, "hf_tqdm", module.hf_tqdm))
            module.hf_tqdm = reporting
    try:
        yield reporting
    finally:
        for module, attribute, previous in patches:
            setattr(module, attribute, previous)


def _modelscope_progress_callback(
    progress: ProgressCallback,
    stage: str,
    ratio_span: tuple[float, float],
) -> type:
    try:
        from modelscope.hub.callback import (  # type: ignore[import-untyped]
            ProgressCallback as MsProgressCallback,
        )
    except ImportError as exc:
        raise RuntimeError("缺少下载组件，请先安装项目的 ai 依赖") from exc

    start, end = ratio_span
    state = {"received": 0, "known_total": 0}

    class _ReportingCallback(MsProgressCallback):  # type: ignore[misc]
        def __init__(self, filename: str, file_size: int) -> None:
            super().__init__(filename, file_size)
            if file_size > 0:
                state["known_total"] += file_size
            _report(progress, stage, start if state["known_total"] else None)

        def update(self, size: int) -> None:
            if size <= 0:
                return
            state["received"] += size
            known = state["known_total"]
            if known > 0:
                fraction = min(1.0, state["received"] / known)
                _report(progress, stage, start + (end - start) * fraction)
            else:
                _report(progress, stage, None)

        def end(self) -> None:
            known = state["known_total"]
            if known > 0:
                fraction = min(1.0, state["received"] / known)
                _report(progress, stage, start + (end - start) * fraction)

    return _ReportingCallback


def _prepare_modelscope_runtime() -> None:
    """Prefer the mainland ModelScope endpoint when unset."""
    if not os.environ.get("MODELSCOPE_ENDPOINT") and not os.environ.get(
        "MODELSCOPE_DOMAIN"
    ):
        os.environ["MODELSCOPE_ENDPOINT"] = "https://www.modelscope.cn"


def _modelscope_snapshot_download(
    model_id: str,
    *,
    local_dir: Path,
    progress: ProgressCallback,
    stage: str,
    ratio_span: tuple[float, float],
    ignore_patterns: Sequence[str] | None = None,
    revision: str = MODELSCOPE_REVISION,
) -> Path:
    try:
        from modelscope.hub.snapshot_download import (  # type: ignore[import-untyped]
            snapshot_download as ms_download,
        )
    except ImportError as exc:
        raise RuntimeError("缺少下载组件，请先安装项目的 ai 依赖") from exc
    _prepare_modelscope_runtime()
    local_dir.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, object] = {
        "model_id": model_id,
        "revision": revision,
        "local_dir": str(local_dir),
        "max_workers": 1,
        "progress_callbacks": [
            _modelscope_progress_callback(progress, stage, ratio_span)
        ],
    }
    if ignore_patterns:
        kwargs["ignore_patterns"] = list(ignore_patterns)
    with _without_process_proxies():
        return Path(str(ms_download(**kwargs)))


def _score_analysis_complete(destination: Path, mert_destination: Path) -> bool:
    return (
        (destination / "config.json").is_file()
        and (destination / "model.safetensors").is_file()
        and _mert_files_present(mert_destination)
    )


def _download_score_analysis_via_modelscope(
    progress: ProgressCallback,
    label: str,
    destination: Path,
    mert_destination: Path,
) -> None:
    stage = f"正在下载{label}"
    _report(progress, f"正在连接魔搭节点：{label}", None)
    _modelscope_snapshot_download(
        SHEETSAGE2_MODELSCOPE_ID,
        local_dir=destination,
        progress=progress,
        stage=stage,
        ratio_span=(0.0, 0.45),
        ignore_patterns=SHEETSAGE2_IGNORE_PATTERNS,
    )
    dependency_stage = f"正在下载{label}依赖组件"
    _report(progress, f"正在连接魔搭节点：{label}依赖组件", None)
    _modelscope_snapshot_download(
        MERT_MODELSCOPE_ID,
        local_dir=mert_destination,
        progress=progress,
        stage=dependency_stage,
        ratio_span=(0.45, 0.99),
    )


def _download_score_analysis_via_huggingface(
    progress: ProgressCallback,
    label: str,
    destination: Path,
    mert_destination: Path,
) -> None:
    hf_home = huggingface_home()
    hub_cache = hf_home / "hub"
    hub_cache.mkdir(parents=True, exist_ok=True)
    previous_home = os.environ.get("HF_HOME")
    previous_cache = os.environ.get("HF_HUB_CACHE")
    os.environ["HF_HOME"] = str(hf_home)
    os.environ["HF_HUB_CACHE"] = str(hub_cache)
    try:
        stage = f"正在下载{label}"
        _report(progress, f"正在连接下载节点：{label}", None)
        with _huggingface_progress(progress, stage, (0.0, 0.45)) as tqdm_class:
            _huggingface_call(
                "snapshot_download",
                repo_id=SHEETSAGE2_REPOSITORY,
                local_dir=str(destination),
                ignore_patterns=list(SHEETSAGE2_IGNORE_PATTERNS),
                max_workers=1,
                tqdm_class=tqdm_class,
                etag_timeout=60,
            )
        dependency_stage = f"正在下载{label}依赖组件"
        _report(progress, f"正在连接下载节点：{label}依赖组件", None)
        with _huggingface_progress(
            progress, dependency_stage, (0.45, 0.99)
        ) as tqdm_class:
            _huggingface_call(
                "snapshot_download",
                repo_id=MERT_REPOSITORY,
                revision=MERT_HF_REVISION,
                local_dir=str(mert_destination),
                max_workers=1,
                tqdm_class=tqdm_class,
                etag_timeout=60,
            )
    finally:
        if previous_home is None:
            os.environ.pop("HF_HOME", None)
        else:
            os.environ["HF_HOME"] = previous_home
        if previous_cache is None:
            os.environ.pop("HF_HUB_CACHE", None)
        else:
            os.environ["HF_HUB_CACHE"] = previous_cache


def _download_score_analysis(progress: ProgressCallback, label: str) -> Path:
    destination = sheetsage2_model_dir()
    mert_destination = mert_model_dir()
    destination.parent.mkdir(parents=True, exist_ok=True)
    mert_destination.parent.mkdir(parents=True, exist_ok=True)
    errors: list[BaseException] = []

    # Mainland CDN first: HF mirrors often redirect large weights overseas.
    try:
        _download_score_analysis_via_modelscope(
            progress, label, destination, mert_destination
        )
        if _score_analysis_complete(destination, mert_destination):
            _report(progress, f"{label}已就绪", 1.0)
            return destination
        errors.append(RuntimeError(f"{label}魔搭下载完成但文件不完整"))
    except Exception as exc:
        errors.append(exc)
        _report(
            progress,
            f"魔搭下载未完成，改试镜像节点：{format_download_error(exc)}",
            None,
        )

    try:
        _download_score_analysis_via_huggingface(
            progress, label, destination, mert_destination
        )
    except Exception as exc:
        errors.append(exc)
        details = "；".join(format_download_error(item) for item in errors)
        raise RuntimeError(f"下载{label}失败：{details}") from exc

    if not (destination / "config.json").is_file():
        raise RuntimeError(f"{label}下载完成但文件不完整")
    if not (destination / "model.safetensors").is_file():
        raise RuntimeError(f"{label}下载完成但权重文件缺失")
    if not _mert_files_present(mert_destination) and not _mert_ready():
        raise RuntimeError(f"{label}依赖组件下载完成但文件不完整")
    _report(progress, f"{label}已就绪", 1.0)
    return destination


def _hf_repo_cache_root(repository: str) -> Path:
    folder = f"models--{repository.replace('/', '--')}"
    return huggingface_home() / "hub" / folder


def _install_file_into_hf_cache(
    repository: str,
    revision: str,
    filename: str,
    source: Path,
) -> Path:
    """Place a downloaded file into the Hugging Face hub cache layout."""
    import shutil

    storage = _hf_repo_cache_root(repository)
    snapshots = storage / "snapshots" / revision
    refs = storage / "refs"
    snapshots.mkdir(parents=True, exist_ok=True)
    refs.mkdir(parents=True, exist_ok=True)
    destination = snapshots / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    # Copy instead of symlink so Windows clients do not need elevated rights.
    shutil.copy2(source, destination)
    (refs / "main").write_text(revision, encoding="utf-8")
    return destination


def _download_url_to_path(
    url: str,
    destination: Path,
    progress: ProgressCallback,
    stage: str,
    ratio_span: tuple[float, float],
    *,
    timeout: float = 180,
) -> None:
    start, end = ratio_span
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    _report(progress, stage, start)
    with urlopen_direct(url, timeout=timeout) as response:
        total = response.headers.get("Content-Length")
        expected = int(total) if total and total.isdigit() else None
        received = 0
        with temporary.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                received += len(chunk)
                if expected:
                    fraction = min(1.0, received / expected)
                    _report(progress, stage, start + (end - start) * fraction)
                else:
                    _report(progress, stage, None)
    temporary.replace(destination)
    _report(progress, stage, end)


def _download_from_private_mirror(
    repository: str,
    revision: str,
    files: Sequence[str],
    progress: ProgressCallback,
    label: str,
) -> Path:
    """Last-resort download from the mainland static mirror into HF cache."""
    relative_root = _MIRROR_RELATIVE_ROOTS.get(repository)
    if relative_root is None:
        raise RuntimeError(f"{label}没有可用的备用下载节点")
    stage = f"正在从备用节点下载{label}"
    _report(progress, stage, None)
    installed: list[Path] = []
    total = len(files)
    for index, filename in enumerate(files):
        mirror = model_mirror_url(relative_root, filename)
        if mirror is None:
            raise RuntimeError(f"{label}备用下载节点未启用")
        start = index / total
        end = (index + 1) / total
        temporary_dir = default_application_data_root() / "download-tmp" / relative_root
        local_file = temporary_dir / filename
        try:
            _download_url_to_path(
                mirror,
                local_file,
                progress,
                stage,
                (start, end),
            )
            installed.append(
                _install_file_into_hf_cache(repository, revision, filename, local_file)
            )
        finally:
            local_file.unlink(missing_ok=True)
    if not installed:
        raise RuntimeError(f"{label}备用下载失败")
    return installed[0].parent


def _download_stem_separation(progress: ProgressCallback, label: str) -> Path:
    paths: list[Path] = []
    total = len(DEMUCS_FILES)
    public_error: BaseException | None = None
    try:
        for index, filename in enumerate(DEMUCS_FILES):
            stage = f"正在下载{label}（{index + 1}/{total}）"
            start = index / total
            end = (index + 1) / total
            _report(progress, stage, start)
            paths.append(
                Path(
                    str(
                        _huggingface_call(
                            "hf_hub_download",
                            repo_id=DEMUCS_REPOSITORY,
                            filename=filename,
                        )
                    )
                )
            )
            _report(progress, stage, end)
        _report(progress, f"{label}已就绪", 1.0)
        return paths[0].parent
    except Exception as exc:
        public_error = exc
        _report(
            progress,
            f"公共节点下载未完成，改试备用节点：{format_download_error(exc)}",
            None,
        )
    try:
        root = _download_from_private_mirror(
            DEMUCS_REPOSITORY,
            DEMUCS_REVISION,
            DEMUCS_FILES,
            progress,
            label,
        )
    except Exception as exc:
        details = "；".join(
            format_download_error(item)
            for item in (public_error, exc)
            if item is not None
        )
        raise RuntimeError(f"下载{label}失败：{details}") from exc
    _report(progress, f"{label}已就绪", 1.0)
    return root


def _download_aligner(
    repository: str,
    revision: str,
    files: tuple[str, ...],
    progress: ProgressCallback,
    label: str,
) -> Path:
    stage = f"正在下载{label}"
    _report(progress, f"正在连接下载节点：{label}", None)
    public_error: BaseException | None = None
    try:
        with _huggingface_progress(progress, stage, (0.0, 0.99)) as tqdm_class:
            root = Path(
                str(
                    _huggingface_call(
                        "snapshot_download",
                        repo_id=repository,
                        revision=revision,
                        allow_patterns=list(files),
                        max_workers=1,
                        tqdm_class=tqdm_class,
                    )
                )
            )
        missing = [name for name in files if not (root / name).is_file()]
        if missing:
            raise RuntimeError(f"{label}下载不完整")
        _report(progress, f"{label}已就绪", 1.0)
        return root
    except Exception as exc:
        public_error = exc
        _report(
            progress,
            f"公共节点下载未完成，改试备用节点：{format_download_error(exc)}",
            None,
        )
    try:
        root = _download_from_private_mirror(
            repository, revision, files, progress, label
        )
    except Exception as exc:
        details = "；".join(
            format_download_error(item)
            for item in (public_error, exc)
            if item is not None
        )
        raise RuntimeError(f"下载{label}失败：{details}") from exc
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
        with urlopen_with_mirrors(BEAT_THIS_CHECKPOINT_URL, timeout=60) as response:
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
                    else:
                        _report(progress, f"正在下载{label}", None)
        if hasher.hexdigest() != BEAT_THIS_CHECKPOINT_SHA256:
            raise RuntimeError(f"{label}校验失败，请稍后重试")
        temporary.replace(destination)
    except urllib.error.URLError as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"下载{label}失败：{format_download_error(exc)}") from exc
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
    written: list[Path] = []
    total = len(FUN_ASR_CODE_FILES)
    # Code files are tiny; reserve about 10% of the overall lyric-model download.
    try:
        for index, relative in enumerate(FUN_ASR_CODE_FILES):
            stage = f"正在下载{label}组件（{index + 1}/{total}）"
            _report(progress, stage, index / total * 0.1)
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".partial")
            with urlopen_with_mirrors(
                FUN_ASR_CODE_BASE_URL + relative,
                timeout=60,
            ) as response:
                payload = response.read()
            if relative == "model.py" and (
                hashlib.sha256(payload).hexdigest() != MODEL_CODE_SHA256
            ):
                raise RuntimeError(f"{label}组件版本与当前程序不一致")
            temporary.write_bytes(payload)
            temporary.replace(destination)
            written.append(destination)
            _report(progress, stage, (index + 1) / total * 0.1)
    except urllib.error.URLError as exc:
        for path in written:
            path.unlink(missing_ok=True)
        raise RuntimeError(f"下载{label}组件失败：{format_download_error(exc)}") from exc
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return root / "model.py"


def _download_fun_asr_model(progress: ProgressCallback, label: str) -> Path:
    try:
        from modelscope.hub.snapshot_download import (  # type: ignore[import-untyped]
            snapshot_download as ms_download,
        )
    except ImportError as exc:
        raise RuntimeError("缺少下载组件，请先安装项目的 ai 依赖") from exc
    _prepare_modelscope_runtime()
    destination = default_application_data_root() / "Fun-ASR" / "model"
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = f"正在下载{label}"
    _report(progress, stage, 0.1)
    try:
        with _without_process_proxies():
            downloaded = Path(
                ms_download(
                    FUN_ASR_MODELSCOPE_ID,
                    local_dir=str(destination),
                    progress_callbacks=[
                        _modelscope_progress_callback(progress, stage, (0.1, 0.99))
                    ],
                )
            )
    except Exception as exc:
        raise RuntimeError(f"下载{label}失败：{format_download_error(exc)}") from exc
    if not any(
        (downloaded / name).is_file() for name in ("configuration.json", "config.yaml")
    ):
        raise RuntimeError(f"{label}下载完成但文件不完整")
    _report(progress, f"{label}已就绪", 1.0)
    return downloaded
