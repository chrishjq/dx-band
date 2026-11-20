# Third-party model notices

This source project does not distribute model weights. Users obtain any required
weights from the model owners and configure local paths or caches; see
`docs/model_self_setup.md`. User-side downloading does not grant commercial-use
or redistribution rights beyond the upstream license. Read the model-specific
notes below before downloading or using each model.

## Mandarin CTC aligner `parseh/aligner-zh`

- Source: <https://huggingface.co/parseh/aligner-zh>
- Pinned revision: `920ed68179700a9380364a119744e046e04fb14d`
- Contents: quantized ONNX model, vocabulary, and preprocessing metadata.
- License: Apache-2.0 as declared by the upstream model repository.

## English CTC aligner `parseh/aligner-en`

- Source: <https://huggingface.co/parseh/aligner-en>
- Pinned revision: `c0f8960268a23db8e3705ef24d3236e419739975`
- Contents: quantized ONNX model, vocabulary, and preprocessing metadata.
- License: Apache-2.0 as declared by the upstream model repository.

## Cantonese CTC model `ctl/wav2vec2-large-xlsr-cantonese`

- Source: <https://huggingface.co/ctl/wav2vec2-large-xlsr-cantonese>
- Pinned revision: `11cb21cb68b4ed15f4c6633494ae6cc90a89bc34`
- Contents: model weights and processor metadata, used for forced alignment of supplied LRC.
- License: Apache-2.0 as declared by the upstream model repository.

## Demucs `htdemucs_6s`

- Source: <https://huggingface.co/adefossez/HTDemucs-6s>
- Contents: the six-source HTDemucs checkpoint and `htdemucs_6s.yaml`
- License note: the Demucs source code is MIT licensed, but the upstream model repository
  does not declare a license for these weights. In the upstream
  [license discussion](https://github.com/facebookresearch/demucs/issues/327), the model
  author states that pretrained weights are outside the MIT license and provided for
  scientific purposes only. Do not infer commercial-use or redistribution permission from
  the code license or from the ability to download the weights.

## SheetSage2 transcription and MERT-v2-FullSong

The transcription workflow uses the SheetSage2 adapter from
<https://huggingface.co/m-a-p/SheetSage2> and its MERT-v2-FullSong parent from
<https://huggingface.co/m-a-p/MERT-v2-FullSong>. Both model pages declare
CC BY-NC 4.0. Commercial redistribution requires a separate grant of rights
from the rights holder; retain the corresponding license and attribution.

## Beat This! beat tracking

The beat-tracking workflow reads a user-provided `final0` checkpoint from
<https://github.com/CPJKU/beat_this>. Upstream states that its code and
published model weights are MIT licensed. The application reads the beat and
downbeat output to check SheetSage2 bar boundaries.

## Fun-ASR-Nano-2512 lyric transcription

The source setup uses a user-provided local copy of
`FunAudioLLM/Fun-ASR-Nano-2512` and the Fun-ASR model code. The
[code repository](https://github.com/QwenAudio/Fun-ASR) is Apache-2.0. The
[Hugging Face model card](https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512)
lists Apache-2.0, while the separately hosted
[ModelScope model](https://modelscope.cn/models/FunAudioLLM/Fun-ASR-Nano-2512)
did not provide a license file for the checked weight artifact. Check the
license of the exact files you download; do not infer that one listing licenses
files from another host.
