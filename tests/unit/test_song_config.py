# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dxband.models.song import SongConfig


def test_sample_song_config_is_valid() -> None:
    sample = Path("examples/song.sample.json")
    config = SongConfig.model_validate_json(sample.read_bytes(), strict=True)

    assert config.separation.model == "htdemucs_6s"
    assert len(config.audio.tracks) == 6


def test_legacy_four_stem_song_config_remains_readable() -> None:
    payload = json.loads(Path("examples/song.sample.json").read_text(encoding="utf-8"))
    payload["schema_version"] = 2
    payload["separation"]["model"] = "htdemucs_ft"
    payload["audio"]["tracks"].pop("guitar")
    payload["audio"]["tracks"].pop("piano")

    config = SongConfig.model_validate_json(json.dumps(payload), strict=True)

    assert config.schema_version == 2
    assert len(config.audio.tracks) == 4


def test_unknown_config_field_is_rejected() -> None:
    sample = Path("examples/song.sample.json").read_text(encoding="utf-8")
    altered = sample.replace('"schema_version": 3,', '"schema_version": 3, "unknown": true,')

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SongConfig.model_validate_json(altered, strict=True)


def test_song_config_rejects_old_stage_settings() -> None:
    payload = json.loads(Path("examples/song.sample.json").read_text(encoding="utf-8"))
    payload["playback"] = {"master_volume": 0.85}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SongConfig.model_validate_json(json.dumps(payload), strict=True)

    payload.pop("playback")
    payload["audio"]["tracks"]["vocals"]["default_muted"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SongConfig.model_validate_json(json.dumps(payload), strict=True)


def test_musical_properties_are_required() -> None:
    payload = json.loads(Path("examples/song.sample.json").read_text(encoding="utf-8"))
    payload.pop("musical")

    with pytest.raises(ValidationError, match="Field required"):
        SongConfig.model_validate(payload, strict=True)


def test_musical_properties_require_integer_bpm() -> None:
    payload = SongConfig.model_validate_json(
        Path("examples/song.sample.json").read_bytes(),
        strict=True,
    ).model_dump(mode="python")
    payload["musical"] = {"original_key": "F#m", "bpm": 71.8}

    with pytest.raises(ValidationError, match="valid integer"):
        SongConfig.model_validate(payload, strict=True)


def test_musical_properties_accept_detected_beat_grid() -> None:
    payload = SongConfig.model_validate_json(
        Path("examples/song.sample.json").read_bytes(),
        strict=True,
    ).model_dump(mode="python")
    payload["musical"] = {
        "original_key": "D",
        "bpm": 76,
        "beat_times_ms": [812, 1_601, 2_390, 3_180],
    }

    config = SongConfig.model_validate(payload, strict=True)

    assert config.musical is not None
    assert config.musical.beat_times_ms == [812, 1_601, 2_390, 3_180]


def test_musical_properties_accept_bar_boundaries() -> None:
    payload = SongConfig.model_validate_json(
        Path("examples/song.sample.json").read_bytes(),
        strict=True,
    ).model_dump(mode="python")
    payload["musical"] = {
        "original_key": "F",
        "bpm": 180,
        "beat_times_ms": [0, 333, 667, 1_000, 1_333, 1_667],
        "downbeat_times_ms": [0, 1_000],
        "beats_per_bar": 3,
    }

    config = SongConfig.model_validate(payload, strict=True)

    assert config.musical is not None
    assert config.musical.downbeat_times_ms == [0, 1_000]
    assert config.musical.beats_per_bar == 3


def test_musical_properties_reject_downbeat_outside_beat_grid() -> None:
    payload = SongConfig.model_validate_json(
        Path("examples/song.sample.json").read_bytes(),
        strict=True,
    ).model_dump(mode="python")
    payload["musical"] = {
        "original_key": "F",
        "bpm": 180,
        "beat_times_ms": [0, 333, 667, 1_000],
        "downbeat_times_ms": [0, 990],
        "beats_per_bar": 3,
    }

    with pytest.raises(ValidationError, match="every downbeat"):
        SongConfig.model_validate(payload, strict=True)


def test_musical_properties_reject_unsorted_beat_grid() -> None:
    payload = SongConfig.model_validate_json(
        Path("examples/song.sample.json").read_bytes(),
        strict=True,
    ).model_dump(mode="python")
    payload["musical"] = {
        "original_key": "D",
        "bpm": 76,
        "beat_times_ms": [812, 700],
    }

    with pytest.raises(ValidationError, match="strictly increasing"):
        SongConfig.model_validate(payload, strict=True)
