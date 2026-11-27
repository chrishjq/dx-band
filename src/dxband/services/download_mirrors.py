# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Prefer China-reachable mirrors when downloading GitHub / Hugging Face assets.

Primary upstream URLs stay authoritative for checksums. Public mirrors are tried
first so mainland networks can complete Settings downloads; official hosts remain
as fallback. A private mainland static mirror (``DX_BAND_MODEL_MIRROR``) is only
used as a last resort for Hugging Face weights that redirect to overseas CDNs,
to avoid burning that host's bandwidth when public nodes still work.

Score-analysis weights prefer ModelScope (mainland CDN) before HF endpoints.

Override with:

- ``DX_BAND_PREFER_MIRRORS=0`` — try official URLs before mirrors
- ``DX_BAND_GITHUB_MIRROR`` — custom GitHub proxy prefix (e.g. ``https://ghfast.top/``)
- ``HF_ENDPOINT`` / ``DX_BAND_HF_ENDPOINT`` — Hugging Face API endpoint
- ``DX_BAND_MODEL_MIRROR`` — last-resort static model host (default below)
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from typing import Any

HF_OFFICIAL_ENDPOINT = "https://huggingface.co"
HF_MIRROR_ENDPOINT = "https://hf-mirror.com"

# Private mainland static copies of HF weights that public mirrors still send to
# overseas Xet/CDN. Used only after public endpoints fail.
DEFAULT_MODEL_MIRROR = "http://106.55.161.238/dxband-models"

# Public GitHub file proxies commonly used in mainland China. Availability varies;
# callers iterate until one succeeds. Prefer gh-proxy first: ghfast has been seen
# returning 502 on some release assets (e.g. ffprobe) and failing on raw content.
_GITHUB_RELEASE_MIRROR_PREFIXES: tuple[str, ...] = (
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
    "https://ghfast.top/",
)
_GITHUB_RAW_MIRROR_PREFIXES: tuple[str, ...] = (
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
    "https://ghfast.top/",
)


def prefer_mirrors() -> bool:
    return os.environ.get("DX_BAND_PREFER_MIRRORS", "1").strip() not in {
        "0",
        "false",
        "False",
        "no",
        "NO",
    }


def model_mirror_base() -> str | None:
    """Return the last-resort static model mirror base URL, or None if disabled."""
    raw = os.environ.get("DX_BAND_MODEL_MIRROR", DEFAULT_MODEL_MIRROR).strip()
    if not raw or raw in {"0", "false", "False", "no", "NO", "off", "OFF"}:
        return None
    return raw.rstrip("/")


def model_mirror_url(*parts: str) -> str | None:
    base = model_mirror_base()
    if base is None:
        return None
    path = "/".join(part.strip("/") for part in parts if part)
    return f"{base}/{path}"


def github_mirror_prefixes(url: str = "") -> tuple[str, ...]:
    custom = os.environ.get("DX_BAND_GITHUB_MIRROR", "").strip()
    if custom:
        if not custom.endswith("/"):
            custom = f"{custom}/"
    lowered = url.lower()
    defaults = (
        _GITHUB_RAW_MIRROR_PREFIXES
        if "raw.githubusercontent.com/" in lowered
        else _GITHUB_RELEASE_MIRROR_PREFIXES
    )
    if custom:
        return (custom, *tuple(prefix for prefix in defaults if prefix != custom))
    return defaults


def is_github_download_url(url: str) -> bool:
    lowered = url.lower()
    return "github.com/" in lowered or "githubusercontent.com/" in lowered


def iter_download_urls(url: str) -> tuple[str, ...]:
    """Return candidate URLs: mirrors first (by default), then the original."""
    if not is_github_download_url(url):
        return (url,)
    mirrored = tuple(f"{prefix}{url}" for prefix in github_mirror_prefixes(url))
    if prefer_mirrors():
        return (*mirrored, url)
    return (url, *mirrored)


def huggingface_endpoints() -> tuple[str, ...]:
    """Return Hugging Face endpoints to try, mirror-first unless overridden."""
    custom = (
        os.environ.get("DX_BAND_HF_ENDPOINT")
        or os.environ.get("HF_ENDPOINT")
        or ""
    ).strip().rstrip("/")
    if custom:
        others = [
            endpoint
            for endpoint in (HF_MIRROR_ENDPOINT, HF_OFFICIAL_ENDPOINT)
            if endpoint != custom
        ]
        return (custom, *others) if prefer_mirrors() else (custom,)
    if prefer_mirrors():
        return (HF_MIRROR_ENDPOINT, HF_OFFICIAL_ENDPOINT)
    return (HF_OFFICIAL_ENDPOINT, HF_MIRROR_ENDPOINT)


def urlopen_with_mirrors(
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> Any:
    """Open ``url``, trying China-friendly mirrors for GitHub hosts."""
    last_error: BaseException | None = None
    request_headers = {"User-Agent": "DX-Band", **(headers or {})}
    for candidate in iter_download_urls(url):
        request = urllib.request.Request(candidate, headers=request_headers)
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last_error = exc
            # Do not retry mirrors for client errors other than rate limits / blocks.
            if exc.code in {401, 403, 404, 410}:
                # 403/401 on a mirror can mean the proxy rejected the request; try next.
                if exc.code in {401, 403} and candidate != url:
                    continue
                raise
        except urllib.error.URLError as exc:
            last_error = exc
            continue
        except TimeoutError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise urllib.error.URLError(f"无法下载：{url}")


def urlopen_direct(
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> Any:
    """Open one absolute URL without GitHub mirror rewriting."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "DX-Band", **(headers or {})}
    )
    return urllib.request.urlopen(request, timeout=timeout)


def first_exception(errors: Sequence[BaseException]) -> BaseException:
    if not errors:
        raise RuntimeError("下载失败，请稍后重试或检查网络")
    return errors[0]


def collect_endpoint_errors(errors: Iterable[BaseException]) -> str:
    parts = [str(exc).strip() for exc in errors if str(exc).strip()]
    if not parts:
        return "请稍后重试或检查网络"
    # Prefer the last attempt detail; it is often the official host after mirrors.
    return parts[-1]
