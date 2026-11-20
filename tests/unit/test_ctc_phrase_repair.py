# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import numpy as np

from dxband.creation import ctc_lyrics_aligner


def test_local_ctc_retry_targets_vocal_phrase_and_leaves_neighbors(monkeypatch) -> None:
    audio = np.zeros(24 * 16000, dtype=np.float32)
    audio[15 * 16000 : 19 * 16000] = 0.1
    scores = np.zeros((1200, 4), dtype=np.float32)
    peaks = [[1, 2, 3], [7, 16, 17, 18], [21, 22, 23]]

    def align_local(window, texts, _characters, _duration):
        assert texts == ["甲乙丙丁"]
        assert len(window) < len(scores) / 4
        return [[0.5, 1, 2, 3]]

    monkeypatch.setattr(ctc_lyrics_aligner, "_align_character_peaks", align_local)

    result = ctc_lyrics_aligner._repair_stretched_phrases(
        audio, scores, ["前一句", "甲乙丙丁", "后一句"], list("甲乙丙丁"), peaks
    )

    assert result[0] == peaks[0] and result[2] == peaks[2]
    assert 15 <= result[1][0] < result[1][-1] <= 19


def test_dominant_ctc_cluster_repairs_a_character_stranded_before_interlude(
    monkeypatch,
) -> None:
    audio = np.zeros(50 * 16000, dtype=np.float32)
    scores = np.zeros((2500, 5), dtype=np.float32)
    peaks = [[6, 7, 8], [10, 30, 31, 32, 33], [40, 41, 42]]

    def align_local(window, texts, _characters, duration):
        assert texts == ["如果要说何"]
        assert len(window) < len(scores) / 4
        assert duration < 6
        return [[0.4, 1.2, 2.0, 2.8, 3.6]]

    monkeypatch.setattr(ctc_lyrics_aligner, "_align_character_peaks", align_local)

    result = ctc_lyrics_aligner._repair_stretched_phrases(
        audio, scores, ["前一句", "如果要说何", "后一句"], list("如果要说何"), peaks
    )

    assert result[0] == peaks[0] and result[2] == peaks[2]
    assert 29 <= result[1][0] < result[1][-1] <= 34
