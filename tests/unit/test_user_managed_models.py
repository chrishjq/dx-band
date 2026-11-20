# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

import pytest

from dxband.constants import TRACK_FILENAMES
from dxband.creation import ctc_lyrics_aligner, demucs_runner
from dxband.creation.beat_this_runner import BeatThisRunner
from dxband.creation.cancellation import CancellationToken
from dxband.creation.fun_asr_runner import FunAsrRunner


def test_demucs_requires_local_weights_before_starting_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import huggingface_hub

    monkeypatch.setattr(demucs_runner.importlib.metadata, "version", lambda _name: "4.1.0")
    monkeypatch.setattr(
        huggingface_hub, "hf_hub_download",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    monkeypatch.setattr(
        demucs_runner.DemucsRunner, "_run_process",
        lambda *_args: pytest.fail("Demucs started before local weights were checked"),
    )

    with pytest.raises(demucs_runner.DemucsError, match="自行下载"):
        demucs_runner.DemucsRunner().run(
            tmp_path / "song.wav", tmp_path, "cpu", CancellationToken(), lambda _line: None,
        )


def test_ctc_aligner_uses_only_local_model_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    import huggingface_hub

    monkeypatch.delenv("DX_BAND_ALIGNER_ZH_MODEL_DIR", raising=False)

    def no_snapshot(_repository: str, **kwargs: object) -> Path:
        assert kwargs["local_files_only"] is True
        raise FileNotFoundError()

    monkeypatch.setattr(huggingface_hub, "snapshot_download", no_snapshot)

    with pytest.raises(RuntimeError, match="自行下载"):
        ctc_lyrics_aligner.LrcCtcAligner(language="zh")._model_root()


def test_demucs_uses_huggingface_only_after_local_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import huggingface_hub

    checked: list[str] = []
    commands: list[list[str]] = []
    track_dir = tmp_path / "htdemucs_6s" / "song"
    track_dir.mkdir(parents=True)
    for filename in TRACK_FILENAMES.values():
        (track_dir / filename).touch()

    def local_file(_repository: str, filename: str, *, local_files_only: bool) -> str:
        assert local_files_only
        checked.append(filename)
        return str(tmp_path / filename)

    monkeypatch.setattr(demucs_runner.importlib.metadata, "version", lambda _name: "4.1.0")
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", local_file)
    monkeypatch.setattr(
        demucs_runner.DemucsRunner, "_run_process",
        lambda _self, command, *_args: commands.append(command),
    )
    result = demucs_runner.DemucsRunner().run(
        tmp_path / "song.wav", tmp_path, "cpu", CancellationToken(), lambda _line: None,
    )

    assert set(checked) == set(demucs_runner.DEMUCS_FILES)
    assert commands[0][commands[0].index("-n") + 1] == "hf://htdemucs_6s"
    assert result.output_dir == track_dir


def test_fun_asr_requires_user_model_directory(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="DX_BAND_FUN_ASR_MODEL_DIR"):
        FunAsrRunner(model_dir=tmp_path / "missing").check_ready()


def test_beat_this_requires_local_checkpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("DX_BAND_BEAT_THIS_CHECKPOINT", raising=False)
    runner = BeatThisRunner(python=tmp_path / "python")
    with pytest.raises(RuntimeError, match="自行下载"):
        runner.check_ready()
