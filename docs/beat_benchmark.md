# 合成节拍基准

本基准让贡献者在**同一音频、同一拍点标注、同一容差**下比较节拍和小节线。音频由 `scripts/beat_benchmark.py` 合成，不使用真实歌曲或第三方录音；WAV 和预测文件在本地生成，不进入源码仓库。合成音频只能检查一组明确的回归场景，不能代表真实音乐的准确率。

| 样本 ID | 条件 | 参考值 |
| --- | --- | --- |
| `four_four` | 120 BPM、4/4、8 小节 | 32 拍、8 个小节起点 |
| `three_four` | 100 BPM、3/4、8 小节 | 24 拍、8 个小节起点 |
| `four_four_missing_kick` | 120 BPM、4/4，第 13 拍省去底鼓但保留其他节奏线索 | 32 拍、8 个小节起点 |

`reference.json` 记录每个 WAV 的 SHA-256。评分器要求预测 JSON 的 `source_sha256` 相同，并在指定容差内对参考和预测拍点做时间顺序的一对一匹配，报告 precision、recall、F1 和匹配点平均绝对误差。容差默认 70 毫秒；预测时间必须严格递增。

## 本地复现

在仓库根目录运行，先按[用户自备模型指南](model_self_setup.md)取得适用的 Beat This! checkpoint。下列输出目录应放在仓库外：

```bash
benchmark_dir=/tmp/dx-band-beat-benchmark
checkpoint=/path/to/final0.ckpt
uv run --no-sync python scripts/beat_benchmark.py generate "$benchmark_dir"
mkdir -p "$benchmark_dir/predictions"
for case in four_four three_four four_four_missing_kick; do
  uv run --no-sync python scripts/run_beat_this.py \
    "$benchmark_dir/$case.wav" "$benchmark_dir/predictions/$case.json" \
    --checkpoint "$checkpoint" --device cpu
done
uv run --no-sync python scripts/beat_benchmark.py evaluate \
  "$benchmark_dir/reference.json" "$benchmark_dir/predictions" --tolerance-ms 70
```

生成器不会覆盖已有的同名 WAV 或 `reference.json`；重跑时请使用新的空目录。评分器只读取本地 JSON，不下载模型。

## 当前参考结果

2026-11-20 在 macOS、Python 3.11.16、`beat-this` 1.1.0、CPU、`final0.ckpt` SHA-256 `8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331` 下运行：

| 样本 | 节拍 F1 | 小节起点 F1 |
| --- | ---: | ---: |
| `four_four` | 0.9697 | 0.9412 |
| `three_four` | 0.9796 | 0.2857 |
| `four_four_missing_kick` | 0.9697 | 0.9412 |

这给出一个具体的改进目标：在相同输入和 70 毫秒容差下，提高 3/4 小节起点 F1，并检查另外两个场景没有回退。提交算法改动时请附完整逐样本评分、模型/代码版本、设备和音频摘要；不要仅报告平均值。真实歌曲上的效果仍需另用有权公开的素材验证。
