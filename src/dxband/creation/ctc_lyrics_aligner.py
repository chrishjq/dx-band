# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Forced alignment of known lyrics against the separated vocal track."""

import json
import os
from itertools import pairwise
from pathlib import Path

import numpy as np
from opencc import OpenCC

from dxband.lyrics.instrumental_markers import instrumental_marker_label
from dxband.lyrics.metadata import is_lyric_metadata
from dxband.lyrics.word_timing_edit import retime_edited_text
from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming

MODEL_REPOSITORY = "parseh/aligner-zh"
MODEL_REVISION = "920ed68179700a9380364a119744e046e04fb14d"
MODEL_FILES = ("model.int8.onnx", "vocab.json", "preprocessor_config.json", "meta.json")
EN_REPOSITORY = "parseh/aligner-en"
EN_REVISION = "c0f8960268a23db8e3705ef24d3236e419739975"
YUE_REPOSITORY = "ctl/wav2vec2-large-xlsr-cantonese"
YUE_REVISION = "11cb21cb68b4ed15f4c6633494ae6cc90a89bc34"
YUE_FILES = (
    "pytorch_model.bin", "config.json", "vocab.json", "preprocessor_config.json",
    "tokenizer_config.json", "special_tokens_map.json",
)
# The Cantonese model omits this common sung interjection. Align it against a
# close vocal equivalent while retaining the original character in the lyrics.
YUE_ALIGNMENT_SUBSTITUTIONS = {"呵": "喔"}


def _alignment_character(
    char: str, language: str, vocabulary: dict[str, int], convert: OpenCC
) -> str | None:
    if not char.strip():
        return None
    normalized = str(convert.convert(char)).lower()
    if len(normalized) == 1 and normalized in vocabulary:
        return normalized
    if language == "yue":
        substitute = YUE_ALIGNMENT_SUBSTITUTIONS.get(char)
        if substitute in vocabulary:
            return substitute
    return None


def _align_character_peaks(
    scores: np.ndarray,
    texts: list[str],
    unique_chars: list[str],
    duration: float,
) -> list[list[float]]:
    """Use the same ctc-segmentation aligner on every release platform."""
    try:
        from ctc_segmentation import (
            CtcSegmentationParameters,
            ctc_segmentation,
            prepare_text,
        )
    except ImportError as exc:
        raise RuntimeError(
            "ctc-segmentation 未安装，无法执行统一的歌词逐字对齐"
        ) from exc

    config = CtcSegmentationParameters(
        char_list=["<pad>", *unique_chars],
        blank=0,
        index_duration=duration / len(scores),
        min_window_size=max(8_000, len(scores) + 1_000),
    )
    ground_truth, starts = prepare_text(config, texts)
    timings, _confidence, _states = ctc_segmentation(config, scores, ground_truth)
    return [
        [float(timings[starts[index] + 1 + char_index]) for char_index in range(len(text))]
        for index, text in enumerate(texts)
    ]


def _repair_stretched_phrases(
    audio: np.ndarray,
    scores: np.ndarray,
    texts: list[str],
    unique_chars: list[str],
    peaks: list[list[float]],
) -> list[list[float]]:
    """Retry an implausibly stretched line within its supported vocal phrase."""
    frame_samples = 640
    frame_seconds = frame_samples / 16_000
    frames = audio[: len(audio) // frame_samples * frame_samples].reshape(-1, frame_samples)
    energy = np.sqrt(np.mean(frames * frames, axis=1))
    score_seconds = len(audio) / (16_000 * len(scores))
    repaired = list(peaks)
    for index, times in enumerate(peaks):
        if not any(right - left >= 2.4 for left, right in pairwise(times)):
            continue
        left_limit = repaired[index - 1][-1] + 0.2 if index else 0.0
        right_limit = peaks[index + 1][0] - 0.2 if index + 1 < len(peaks) else len(audio) / 16_000
        # A single false character peak can sit in the preceding phrase while
        # the clear majority of the line is tightly grouped after an
        # instrumental break. Accompaniment leakage may make the energy track
        # look continuous, so use the dominant CTC peak cluster as independent
        # evidence and retry the complete line inside that local window.
        split_at = np.flatnonzero(np.diff(times) >= 2.4) + 1
        clusters = sorted(
            np.split(np.asarray(times), split_at), key=len, reverse=True
        )
        dominant = clusters[0]
        second_size = len(clusters[1]) if len(clusters) > 1 else 0
        if (
            len(dominant) > second_size
            and len(dominant) * 3 >= len(times) * 2
            and len(dominant) >= 3
        ):
            start = max(left_limit, float(dominant[0]) - 0.9)
            end = min(right_limit, float(dominant[-1]) + 0.9)
            first = max(0, round(start / score_seconds))
            last = min(len(scores), round(end / score_seconds))
            if last - first > 2 * len(times):
                local_peaks = _align_character_peaks(
                    scores[first:last], [texts[index]], unique_chars,
                    (last - first) * score_seconds,
                )[0]
                proposed = [time + first * score_seconds for time in local_peaks]
                if (
                    all(left < right for left, right in pairwise(proposed))
                    and proposed[0] >= start - 0.1
                    and proposed[-1] <= end + 0.1
                    and proposed[-1] - proposed[0] <= (times[-1] - times[0]) * 0.75
                ):
                    repaired[index] = proposed
                    continue
        left = max(0, round(left_limit / frame_seconds))
        right = min(len(energy), round(right_limit / frame_seconds))
        if right <= left:
            continue
        local = energy[left:right]
        active = np.flatnonzero(local >= max(0.002, float(local.max()) * 0.035)) + left
        if not len(active):
            continue
        phrases = np.split(active, np.flatnonzero(np.diff(active) > 15) + 1)
        candidates = [
            (group[0] * frame_seconds, (group[-1] + 1) * frame_seconds)
            for group in phrases
            if len(group) >= 4
        ]
        for start, end in candidates:
            if not (
                sum(start - 0.22 <= time <= end + 0.22 for time in times) * 2 > len(times)
                and (times[0] < start - 2.4 or times[-1] > end + 2.4)
            ):
                continue
            first = max(0, round(max(left_limit, start - 0.28) / score_seconds))
            last = min(len(scores), round(min(right_limit, end + 0.28) / score_seconds))
            if last - first <= 2 * len(times):
                continue
            local_peaks = _align_character_peaks(
                scores[first:last], [texts[index]], unique_chars, (last - first) * score_seconds
            )[0]
            proposed = [time + first * score_seconds for time in local_peaks]
            if (
                all(left < right for left, right in pairwise(proposed))
                and proposed[-1] - proposed[0] <= (times[-1] - times[0]) * 0.75
                and sum(start - 0.16 <= time <= end + 0.16 for time in proposed) * 5
                >= len(proposed) * 4
            ):
                repaired[index] = proposed
                break
    return repaired


class LrcCtcAligner:
    def __init__(self, model_root: Path | None = None, language: str = "zh") -> None:
        self.model_root = model_root
        self.language = language

    def align_document(self, reference: LyricsDocument, vocals_path: Path) -> LyricsDocument:
        import librosa
        import onnxruntime as ort
        from scipy.special import logsumexp

        model_root = self._model_root()
        vocabulary = json.loads((model_root / "vocab.json").read_text(encoding="utf-8"))
        convert = OpenCC("s2t" if self.language == "yue" else "t2s")
        kept: list[LyricLine] = []
        texts: list[str] = []
        display_chars: list[list[str | None]] = []
        for line in reference.lines:
            if (
                self._is_credit(line.text, reference.title, line.start_ms)
                or instrumental_marker_label(line)
            ):
                continue
            alignment_chars: list[str] = []
            visible_chars: list[str | None] = []
            for char in line.text:
                if self.language == "en" and char.isspace():
                    if alignment_chars and alignment_chars[-1] != "|":
                        alignment_chars.append("|")
                        visible_chars.append(None)
                    continue
                normalized = _alignment_character(char, self.language, vocabulary, convert)
                if normalized is not None:
                    alignment_chars.append(normalized)
                    visible_chars.append(char)
            while alignment_chars and alignment_chars[-1] == "|":
                alignment_chars.pop()
                visible_chars.pop()
            text = "".join(alignment_chars)
            if not text:
                raise ValueError(f"歌词“{line.text}”没有{self.language}对齐模型支持的字符")
            kept.append(line)
            texts.append(text)
            display_chars.append(visible_chars)
        if not kept:
            raise ValueError("LRC 没有可演唱的歌词行")

        audio, _ = librosa.load(str(vocals_path), sr=16_000, mono=True)
        if len(audio) < 16_000:
            raise ValueError("人声轨太短，无法对齐歌词")
        unique_chars = list(dict.fromkeys("".join(texts)))
        blank_id = self._blank_id(vocabulary)
        selected_ids = [blank_id, *(vocabulary[char] for char in unique_chars)]
        chunks = []
        if self.language == "yue":
            import torch
            from transformers import AutoModelForCTC, AutoProcessor

            processor = AutoProcessor.from_pretrained(
                str(model_root), local_files_only=True
            )  # type: ignore[no-untyped-call]
            model = AutoModelForCTC.from_pretrained(
                str(model_root), local_files_only=True
            ).eval()
            with torch.inference_mode():
                for offset in range(0, len(audio), 15 * 16_000):
                    chunk = audio[offset : offset + 15 * 16_000]
                    features = processor(chunk, sampling_rate=16_000, return_tensors="pt")
                    logits = model(**features).logits[0].cpu().numpy()
                    chunks.append(
                        logits[:, selected_ids] - logsumexp(logits, axis=1, keepdims=True)
                    )
        else:
            options = ort.SessionOptions()
            options.intra_op_num_threads = min(os.cpu_count() or 1, 4)
            session = ort.InferenceSession(
                str(model_root / "model.int8.onnx"), options,
                providers=["CPUExecutionProvider"],
            )
            for offset in range(0, len(audio), 15 * 16_000):
                chunk = audio[offset : offset + 15 * 16_000]
                chunk = (chunk - chunk.mean()) / max(float(chunk.std()), 1e-8)
                logits = session.run(None, {"input_values": chunk[None].astype("float32")})[0][0]
                chunks.append(
                    logits[:, selected_ids] - logsumexp(logits, axis=1, keepdims=True)
                )
        scores = np.concatenate(chunks).astype("float32")
        duration = len(audio) / 16_000
        peaks = _align_character_peaks(scores, texts, unique_chars, duration)
        peaks = _repair_stretched_phrases(audio, scores, texts, unique_chars, peaks)
        max_ms = len(audio) * 1000 // 16_000
        starts_ms = [max(0, round((times[0] - 0.35) * 1000)) for times in peaks]
        ends_ms = [min(max_ms, round((times[-1] + 0.60) * 1000)) for times in peaks]
        for index in range(len(peaks) - 1):
            if ends_ms[index] > starts_ms[index + 1]:
                boundary = round((peaks[index][-1] + peaks[index + 1][0]) * 500)
                ends_ms[index] = boundary
                starts_ms[index + 1] = boundary

        lines: list[LyricLine] = []
        for index, (line, _text, times, visible) in enumerate(
            zip(kept, texts, peaks, display_chars, strict=True)
        ):
            begin, end = starts_ms[index], ends_ms[index]
            if begin >= end:
                raise ValueError(f"歌词“{line.text}”的对齐时间无效，请检查 LRC 顺序")
            boundaries = [
                begin,
                *(round((left + right) * 500) for left, right in pairwise(times)),
                end,
            ]
            boundaries = [max(begin, min(end, value)) for value in boundaries]
            if any(right <= left for left, right in pairwise(boundaries)):
                raise ValueError(f"歌词“{line.text}”的逐字时间异常，请人工检查 LRC")
            words = [
                WordTiming(
                    text=display,
                    start_ms=boundaries[position],
                    end_ms=boundaries[position + 1],
                )
                for position, display in enumerate(visible)
                if display is not None
            ]
            provisional = LyricLine(
                id=f"line-{index + 1:04d}", start_ms=begin, end_ms=end,
                text="".join(word.text for word in words), words=words,
            )
            completed_words = retime_edited_text(provisional, line.text)
            if not completed_words:
                raise ValueError(f"歌词“{line.text}”无法补齐逐字时间")
            lines.append(
                LyricLine(id=provisional.id, start_ms=begin, end_ms=end,
                          text=line.text, words=completed_words)
            )
        return LyricsDocument(
            schema_version=1, title=reference.title, language=self.language,
            timing_mode="word", lines=lines
        )

    @staticmethod
    def _is_credit(text: str, title: str, start_ms: int | None = None) -> bool:
        return is_lyric_metadata(text, title, start_ms)

    @staticmethod
    def _blank_id(vocabulary: dict[str, int]) -> int:
        if "<pad>" in vocabulary:
            return vocabulary["<pad>"]
        if "[PAD]" in vocabulary:
            return vocabulary["[PAD]"]
        return max(vocabulary.values())

    def _model_root(self) -> Path:
        root: Path | None
        if self.model_root is not None:
            root = self.model_root
        else:
            override = os.environ.get(f"DX_BAND_ALIGNER_{self.language.upper()}_MODEL_DIR")
            root = Path(override).expanduser() if override else None
            if root is None:
                from huggingface_hub import snapshot_download

                repository, revision = {
                    "zh": (MODEL_REPOSITORY, MODEL_REVISION),
                    "en": (EN_REPOSITORY, EN_REVISION),
                    "yue": (YUE_REPOSITORY, YUE_REVISION),
                }[self.language]
                try:
                    root = Path(snapshot_download(
                        repository, revision=revision,
                        allow_patterns=list(MODEL_FILES if self.language != "yue" else YUE_FILES),
                        local_files_only=True,
                    ))
                except Exception as exc:
                    raise RuntimeError(
                        f"缺少本机{self.language}歌词对齐模型；"
                        f"请先从 https://huggingface.co/{repository} 自行下载对应版本"
                    ) from exc
        required = MODEL_FILES if self.language != "yue" else YUE_FILES
        if not all((root / filename).is_file() for filename in required):
            raise RuntimeError(f"缺少{self.language}歌词对齐模型文件：{root}")
        return root
