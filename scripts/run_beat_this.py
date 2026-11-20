# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Run Beat This! on original audio and preserve its unmodified beat output.

The script runs in a Python source environment containing beat_this 1.1.0.
It can analyze one song for creation or a manifest for library rebuilding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_result(
    source: Path, destination: Path, predictor: object, expected_hash: str | None
) -> None:
    import numpy as np
    from beat_this.inference import Audio2Beats

    if not isinstance(predictor, Audio2Beats):
        raise TypeError("Beat This! predictor is not initialized")
    source_hash = sha256(source)
    if expected_hash is not None and source_hash != expected_hash:
        raise ValueError(f"source SHA-256 differs: {source}")
    # Decode through FFmpeg: torchaudio/soundfile do not consistently read AAC.
    with tempfile.TemporaryDirectory(prefix="beat-this-audio-") as directory:
        wav = Path(directory) / "source.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-i",
                str(source),
                "-ac",
                "1",
                "-ar",
                "22050",
                "-c:a",
                "pcm_s16le",
                str(wav),
            ],
            stdin=subprocess.DEVNULL,
            check=True,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        )
        with wave.open(str(wav), "rb") as stream:
            if stream.getnchannels() != 1 or stream.getsampwidth() != 2:
                raise ValueError("FFmpeg did not produce mono 16-bit PCM audio")
            sample_rate = stream.getframerate()
            signal = (
                np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(
                    np.float32
                )
                / 32768.0
            )
        beats, downbeats = predictor(signal, sample_rate)
    data = {
        "model": "beat_this final0",
        "source_sha256": source_hash,
        "beats_s": [float(value) for value in beats],
        "downbeats_s": [float(value) for value in downbeats],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    print(
        json.dumps(
            {
                "source": str(source),
                "output": str(destination),
                "beats": len(beats),
                "downbeats": len(downbeats),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--manifest", type=Path, help="JSON rows: source, output, expected_sha256")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--device", choices=("auto", "mps", "cuda", "cpu"), default="auto")
    args = parser.parse_args()
    if args.manifest is None and (args.source is None or args.output is None):
        parser.error("provide source/output or --manifest")
    if args.manifest is not None and (args.source is not None or args.output is not None):
        parser.error("--manifest cannot be combined with source/output")
    if not args.checkpoint.is_file():
        parser.error(f"Beat This! 模型文件不存在：{args.checkpoint}")
    import torch
    from beat_this.inference import Audio2Beats

    device = args.device
    if device == "auto":
        device = (
            "cuda"
            if torch.cuda.is_available()
            else ("mps" if torch.backends.mps.is_available() else "cpu")
        )
    predictor = Audio2Beats(checkpoint_path=str(args.checkpoint), device=device, dbn=False)
    if args.manifest is not None:
        rows = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("manifest must be a JSON array")
        for index, row in enumerate(rows, 1):
            source, output = Path(row["source"]), Path(row["output"])
            print(
                json.dumps(
                    {"stage": "start", "index": index, "source": str(source)}, ensure_ascii=False
                ),
                flush=True,
            )
            write_result(source, output, predictor, row.get("expected_sha256"))
    else:
        assert args.source is not None and args.output is not None
        write_result(args.source, args.output, predictor, None)


if __name__ == "__main__":
    sys.exit(main())
