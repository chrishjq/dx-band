# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Run Fun-ASR-Nano on separated vocals and retain native character times."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


def _load_local_model_code(model_code: Path) -> None:
    """Register the user-provided model without FunASR's requirements installer."""
    model_code = model_code.resolve()
    module_name = "dx_band_local_fun_asr_model"
    spec = importlib.util.spec_from_file_location(module_name, model_code)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 Fun-ASR 本地模型代码：{model_code}")
    sys.path.insert(0, str(model_code.parent))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)


def transcribe_vocals(
    vocals: Path,
    output: Path,
    model_code: Path,
    model_dir: Path,
    *,
    core_seconds: float = 18.0,
    context_seconds: float = 2.0,
    device: str = "mps",
    language: str = "粤语",
) -> dict[str, Any]:
    if not model_code.is_file():
        raise FileNotFoundError(f"Fun-ASR 模型代码不存在：{model_code}")
    if not model_dir.is_dir() or not any(
        (model_dir / name).is_file() for name in ("configuration.json", "config.yaml")
    ):
        raise FileNotFoundError(f"Fun-ASR 本地模型目录不完整：{model_dir}")
    import librosa
    import soundfile as sf
    from funasr import AutoModel

    _load_local_model_code(model_code)
    samples, sample_rate = librosa.load(str(vocals), sr=16_000, mono=True)
    duration = len(samples) / sample_rate
    model = AutoModel(
        model=str(model_dir.resolve()),
        trust_remote_code=False,
        hub="ms",
        device=device,
        disable_update=True,
    )
    chunks: list[dict[str, Any]] = []
    tokens: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "schema_version": 2,
        "model": "FunAudioLLM/Fun-ASR-Nano-2512",
        "timestamp_model": "checkpoint_native_ctc",
        "language": language,
        "method": "free_transcription_with_native_ctc_timestamps_on_separated_vocals",
        "time_basis": "ctc_audio_frames",
        "core_seconds": core_seconds,
        "context_seconds": context_seconds,
        "chunks": chunks,
        "tokens": tokens,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="song-fun-asr-") as temp_dir:
        clip_path = Path(temp_dir) / "clip.wav"
        index = 0
        while index * core_seconds < duration:
            core_start = index * core_seconds
            core_end = min(duration, core_start + core_seconds)
            audio_start = max(0.0, core_start - context_seconds)
            audio_end = min(duration, core_end + context_seconds)
            clip = samples[
                round(audio_start * sample_rate):round(audio_end * sample_rate)
            ]
            sf.write(clip_path, clip, sample_rate)
            print(f"Fun-ASR {audio_start:.1f}–{audio_end:.1f} 秒……", flush=True)
            try:
                inference = model.generate(
                    input=[str(clip_path)], cache={}, batch_size=1,
                    language=language, itn=False,
                )[0]
                timestamps = inference.get("timestamps") or []
                chunks.append({
                    "start_s": round(audio_start, 3),
                    "end_s": round(audio_end, 3),
                    "core_start_s": round(core_start, 3),
                    "core_end_s": round(core_end, 3),
                    "text": inference.get("text", ""),
                    "timestamp_count": len(timestamps),
                })
                for item in timestamps:
                    start = audio_start + float(item["start_time"])
                    end = audio_start + float(item["end_time"])
                    if not core_start <= (start + end) / 2 < core_end:
                        continue
                    tokens.append({
                        "start_s": round(start, 4),
                        "end_s": round(end, 4),
                        "token": item["token"],
                        "score": item.get("score"),
                        "chunk_index": index,
                    })
                print(f"  {inference.get('text', '')}", flush=True)
            except Exception as exc:
                chunks.append({
                    "start_s": round(audio_start, 3),
                    "end_s": round(audio_end, 3),
                    "error": str(exc),
                })
                print(f"  失败：{exc}", flush=True)
            output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            index += 1
    tokens.sort(key=lambda item: item["start_s"])
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vocals", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model-code", type=Path, required=True,
                        help="Official Fun-ASR repository's model.py")
    parser.add_argument("--model-dir", type=Path, required=True,
                        help="Local Fun-ASR-Nano-2512 model directory")
    parser.add_argument("--device", default="mps")
    parser.add_argument("--language", default="粤语")
    args = parser.parse_args()
    transcribe_vocals(
        args.vocals, args.output, args.model_code, args.model_dir,
        device=args.device, language=args.language,
    )
