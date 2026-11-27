# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import urllib.error

import pytest

from dxband.services import download_mirrors


def test_iter_download_urls_prefers_github_mirrors_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DX_BAND_GITHUB_MIRROR", raising=False)
    monkeypatch.setenv("DX_BAND_PREFER_MIRRORS", "1")
    url = "https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1/ffmpeg.gz"
    candidates = download_mirrors.iter_download_urls(url)
    assert candidates[-1] == url
    assert candidates[0].startswith("https://gh-proxy.com/")
    assert url in candidates[0]
    assert any(item.startswith("https://ghfast.top/") for item in candidates)


def test_iter_download_urls_prefers_gh_proxy_for_raw_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DX_BAND_GITHUB_MIRROR", raising=False)
    monkeypatch.setenv("DX_BAND_PREFER_MIRRORS", "1")
    url = "https://raw.githubusercontent.com/FunAudioLLM/Fun-ASR/main/model.py"
    candidates = download_mirrors.iter_download_urls(url)
    assert candidates[0].startswith("https://gh-proxy.com/")
    assert candidates[-1] == url


def test_iter_download_urls_can_prefer_official_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DX_BAND_PREFER_MIRRORS", "0")
    url = "https://raw.githubusercontent.com/FunAudioLLM/Fun-ASR/main/model.py"
    candidates = download_mirrors.iter_download_urls(url)
    assert candidates[0] == url
    assert any(item.startswith("https://gh-proxy.com/") for item in candidates)


def test_model_mirror_url_is_last_resort_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DX_BAND_MODEL_MIRROR", raising=False)
    assert (
        download_mirrors.model_mirror_url("demucs", "5c90dfd2.safetensors")
        == "http://106.55.161.238/dxband-models/demucs/5c90dfd2.safetensors"
    )
    monkeypatch.setenv("DX_BAND_MODEL_MIRROR", "0")
    assert download_mirrors.model_mirror_url("demucs", "x") is None


def test_huggingface_endpoints_prefer_china_mirror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.delenv("DX_BAND_HF_ENDPOINT", raising=False)
    monkeypatch.setenv("DX_BAND_PREFER_MIRRORS", "1")
    assert download_mirrors.huggingface_endpoints()[0] == "https://hf-mirror.com"


def test_urlopen_with_mirrors_falls_back_after_mirror_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DX_BAND_PREFER_MIRRORS", "1")
    monkeypatch.setattr(
        download_mirrors,
        "github_mirror_prefixes",
        lambda *_args, **_kwargs: ("https://mirror.example/",),
    )
    attempts: list[str] = []

    class _Response:
        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_urlopen(request: object, timeout: float = 0) -> _Response:
        url = request.full_url if hasattr(request, "full_url") else str(request)
        attempts.append(url)
        if "mirror.example" in url:
            raise urllib.error.URLError("mirror down")
        return _Response()

    monkeypatch.setattr(download_mirrors.urllib.request, "urlopen", fake_urlopen)
    url = "https://github.com/owner/repo/releases/download/v1/file.bin"
    with download_mirrors.urlopen_with_mirrors(url, timeout=1) as response:
        assert response is not None
    assert attempts == [
        "https://mirror.example/https://github.com/owner/repo/releases/download/v1/file.bin",
        url,
    ]
