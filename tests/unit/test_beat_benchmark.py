# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
import wave
from pathlib import Path

import pytest
from scripts.beat_benchmark import SAMPLE_RATE, _score, evaluate, generate


def test_generated_samples_are_reproducible_and_include_missing_pulse(tmp_path: Path) -> None:
    first = json.loads(generate(tmp_path / "first").read_text(encoding="utf-8"))
    second = json.loads(generate(tmp_path / "second").read_text(encoding="utf-8"))

    assert first == second
    assert [case["meter"] for case in first["cases"]] == [4, 3, 4]
    missing = first["cases"][2]
    assert missing["missing_kick_at_beat"] == 12
    assert missing["beats_s"][12] in missing["downbeats_s"]
    with wave.open(str(tmp_path / "first" / missing["audio_file"]), "rb") as stream:
        assert stream.getframerate() == SAMPLE_RATE
        assert stream.getnchannels() == 1
        assert stream.getsampwidth() == 2


def test_evaluation_counts_each_prediction_once_and_checks_audio_hash(tmp_path: Path) -> None:
    manifest_path = generate(tmp_path / "samples")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    predictions = tmp_path / "predictions"
    predictions.mkdir()
    for case in manifest["cases"]:
        (predictions / f"{case['id']}.json").write_text(
            json.dumps({
                "source_sha256": case["source_sha256"],
                "beats_s": case["beats_s"],
                "downbeats_s": case["downbeats_s"],
            }),
            encoding="utf-8",
        )

    report = evaluate(manifest_path, predictions, 70)
    assert all(case["beats"]["f1"] == 1 for case in report["cases"])
    assert _score([1.0, 2.0], [0.98, 1.02, 2.02], 0.07)["matched"] == 2

    first_case = manifest["cases"][0]
    path = predictions / f"{first_case['id']}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_sha256"] = "wrong sample"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="音频摘要"):
        evaluate(manifest_path, predictions, 70)
