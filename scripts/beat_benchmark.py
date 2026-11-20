# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Generate original beat examples and score time-aligned predictions."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import wave
from itertools import pairwise
from pathlib import Path

import numpy as np

SAMPLE_RATE = 22_050
LEAD_SECONDS = 0.5
BARS = 8
CASES = (
    ("four_four", 120, 4, None),
    ("three_four", 100, 3, None),
    ("four_four_missing_kick", 120, 4, 12),
)


def _mix(destination: np.ndarray, start_s: float, sound: np.ndarray) -> None:
    start = round(start_s * SAMPLE_RATE)
    end = min(start + len(sound), len(destination))
    destination[start:end] += sound[: end - start]


def _synthesize(bpm: int, meter: int, missing_kick: int | None, seed: int) -> np.ndarray:
    period = 60 / bpm
    beat_count = BARS * meter
    duration = LEAD_SECONDS + beat_count * period + 0.6
    signal = np.zeros(math.ceil(duration * SAMPLE_RATE), dtype=np.float32)
    random = np.random.default_rng(seed)

    # Sustained triads make the samples musical without using recorded material.
    chords = ((48, 52, 55), (43, 47, 50), (45, 48, 52), (41, 45, 48))
    for bar in range(BARS):
        length = round(meter * period * SAMPLE_RATE)
        t = np.arange(length, dtype=np.float32) / SAMPLE_RATE
        notes = chords[bar % len(chords)]
        chord = sum(
            np.sin(2 * np.pi * (440 * 2 ** ((note - 69) / 12)) * t)
            for note in notes
        )
        envelope = np.minimum(t / 0.025, 1) * np.exp(-t / (meter * period * 1.8))
        _mix(signal, LEAD_SECONDS + bar * meter * period, chord * envelope * 0.035)

    kick_t = np.arange(round(0.18 * SAMPLE_RATE), dtype=np.float32) / SAMPLE_RATE
    kick = np.sin(2 * np.pi * 62 * kick_t) * np.exp(-kick_t * 28)
    hat_t = np.arange(round(0.055 * SAMPLE_RATE), dtype=np.float32) / SAMPLE_RATE
    hat_envelope = np.exp(-hat_t * 95)
    for half_beat in range(beat_count * 2):
        time_s = LEAD_SECONDS + half_beat * period / 2
        hat = random.standard_normal(len(hat_t)).astype(np.float32) * hat_envelope
        _mix(signal, time_s, hat * 0.055)
    for beat in range(beat_count):
        if beat == missing_kick:
            continue
        time_s = LEAD_SECONDS + beat * period
        _mix(signal, time_s, kick * (0.62 if beat % meter == 0 else 0.36))
    return np.clip(signal, -0.98, 0.98)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = [output_dir / f"{name}.wav" for name, *_ in CASES]
    manifest_path = output_dir / "reference.json"
    if any(path.exists() for path in (*targets, manifest_path)):
        raise FileExistsError("基准样本已存在；请选择新的输出目录，避免覆盖已有结果")
    rows = []
    for index, (name, bpm, meter, missing_kick) in enumerate(CASES):
        signal = _synthesize(bpm, meter, missing_kick, 20261120 + index)
        path = targets[index]
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(SAMPLE_RATE)
            stream.writeframes((signal * 32767).astype("<i2").tobytes())
        period = 60 / bpm
        beats = [round(LEAD_SECONDS + beat * period, 6) for beat in range(BARS * meter)]
        rows.append({
            "id": name,
            "audio_file": path.name,
            "source_sha256": _sha256(path),
            "bpm": bpm,
            "meter": meter,
            "missing_kick_at_beat": missing_kick,
            "beats_s": beats,
            "downbeats_s": beats[::meter],
        })
    manifest_path.write_text(
        json.dumps({"schema_version": 1, "sample_rate": SAMPLE_RATE, "cases": rows}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _times(payload: dict[str, object], key: str) -> list[float]:
    value = payload.get(key)
    if not isinstance(value, list) or any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(item)
        or item < 0
        for item in value
    ):
        raise ValueError(f"{key} 必须是有限、非负的时间数组")
    times = [float(item) for item in value]
    if any(right <= left for left, right in pairwise(times)):
        raise ValueError(f"{key} 必须严格递增")
    return times


def _score(reference: list[float], predicted: list[float], tolerance_s: float) -> dict[str, object]:
    left = right = 0
    errors: list[float] = []
    while left < len(reference) and right < len(predicted):
        delta = predicted[right] - reference[left]
        if abs(delta) <= tolerance_s:
            errors.append(abs(delta) * 1000)
            left += 1
            right += 1
        elif delta < 0:
            right += 1
        else:
            left += 1
    matches = len(errors)
    precision = matches / len(predicted) if predicted else 0.0
    recall = matches / len(reference) if reference else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "reference": len(reference),
        "predicted": len(predicted),
        "matched": matches,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "matched_mae_ms": round(sum(errors) / matches, 2) if matches else None,
    }


def evaluate(manifest_path: Path, predictions_dir: Path, tolerance_ms: float) -> dict[str, object]:
    if not math.isfinite(tolerance_ms) or tolerance_ms <= 0:
        raise ValueError("时间容差必须为正数")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("不支持的参考样本版本")
    results = []
    for case in manifest["cases"]:
        predicted = json.loads(
            (predictions_dir / f"{case['id']}.json").read_text(encoding="utf-8")
        )
        if predicted.get("source_sha256") != case["source_sha256"]:
            raise ValueError(f"{case['id']} 的音频摘要与预测结果不一致")
        results.append({
            "id": case["id"],
            "beats": _score(
                _times(case, "beats_s"), _times(predicted, "beats_s"), tolerance_ms / 1000
            ),
            "downbeats": _score(
                _times(case, "downbeats_s"), _times(predicted, "downbeats_s"),
                tolerance_ms / 1000,
            ),
        })
    return {"tolerance_ms": tolerance_ms, "cases": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate_parser = commands.add_parser("generate", help="生成合成 WAV 与参考拍点")
    generate_parser.add_argument("output_dir", type=Path)
    evaluate_parser = commands.add_parser("evaluate", help="比较 Beat This! JSON 与参考拍点")
    evaluate_parser.add_argument("manifest", type=Path)
    evaluate_parser.add_argument("predictions_dir", type=Path)
    evaluate_parser.add_argument("--tolerance-ms", type=float, default=70.0)
    args = parser.parse_args()
    if args.command == "generate":
        print(generate(args.output_dir))
    else:
        report = evaluate(args.manifest, args.predictions_dir, args.tolerance_ms)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
