# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Transcribe a mono PCM WAV with a local SheetSage2 model.

Run this from a source environment containing the model's dependencies. The
model writes events.json and companion outputs.
"""

from __future__ import annotations

import argparse
import json
import time
import wave
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path, help="16-bit mono PCM WAV excerpt")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--model", required=True, help="local SheetSage2 model directory")
    parser.add_argument("--base-model", help="local MERT parent directory")
    parser.add_argument("--device", choices=("auto", "cuda", "mps", "cpu"), default="auto")
    args = parser.parse_args()

    import numpy as np
    import torch
    from transformers import AutoModel

    started = time.monotonic()

    def report(stage: dict[str, object]) -> None:
        elapsed = round(time.monotonic() - started, 1)
        print(json.dumps({"elapsed_s": elapsed, **stage}, ensure_ascii=False), flush=True)

    with wave.open(str(args.audio), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("audio must be 16-bit mono PCM WAV")
        sample_rate = source.getframerate()
        waveform = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
        waveform = waveform.astype("float32") / 32768
    model = AutoModel.from_pretrained(
        args.model,
        trust_remote_code=True,
        torch_dtype=torch.float32,
        local_files_only=True,
        **({"base_model_path": args.base_model} if args.base_model else {}),
    ).eval()
    device = args.device
    if device == "auto":
        if torch.cuda.is_available():
            device = "cuda"
        elif torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
    model.to(device)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    model.transcribe(
        waveform,
        sampling_rate=sample_rate,
        output_dir=str(args.output_dir),
        dtype="fp32",
        preset="paper",
        progress=report,
    )
    print(args.output_dir / "events.json")


if __name__ == "__main__":
    main()
