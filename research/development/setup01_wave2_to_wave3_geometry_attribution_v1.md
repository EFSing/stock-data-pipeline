# SETUP_01 Wave3 Fib Geometry Attribution v1

> Research-only descriptive analysis. It does not select a threshold or
> change SETUP_01 Decision, RR, Target, Wave, Swing, Fib, Entry, Stop,
> or T→T+1 semantics.

- 全部 SETUP_01 CONFIRMED：745
- 既有正式 T1 <5%：198
- Wave3 Fib 本身 <5%：81
- 其中 SMALL_WAVE_FIB：18
- 其中 BOTH_NEAR：63

## 几何恒等式

R = HIGH1 - LOW0；r = (HIGH1 - LOW2) / R；
e = planned_entry - HIGH1。

fib_1_272_remaining_absolute = (1.272 - r) × R - e，
并逐事件与 LOW2 + 1.272 × R - planned_entry 核对。

- 恒等式最大绝对残差：0.000000000000
- 恒等式通过：True

## 分组描述统计

| group | N | r median | Wave1 gain median | Wave1 range / ATR14 median | e / R median | Fib headroom / R median | Fib1.272 remaining upside median |
|---|---:|---:|---:|---:|---:|---:|---:|
| 全部 CONFIRMED | 745 | 0.6418 | 15.89% | 4.0214 | 18.87% | 0.3707 | 4.50% |
| T1 <5% | 198 | 0.7038 | 15.68% | 4.2982 | 4.76% | 0.5304 | 6.76% |
| Wave3 Fib <5%（81） | 81 | 0.8864 | 8.96% | 3.3288 | 7.02% | 0.3228 | 3.16% |
| SMALL_WAVE_FIB | 18 | 0.8928 | 9.80% | 3.4320 | 4.47% | 0.3321 | 3.49% |
| BOTH_NEAR | 63 | 0.8857 | 8.71% | 3.2672 | 8.21% | 0.3186 | 3.13% |
| NEAR_SWING_ONLY | 117 | 0.5778 | 22.39% | 5.0892 | 3.59% | 0.6520 | 10.86% |

## 81 个 Wave3 Fib-near 的几何分解

| 项目 | 均值 | 占 1.272 normalized extension budget |
|---|---:|---:|
| Wave2 retracement term r | 0.8454 | 66.46% |
| confirmation extension term e/R | 7.95% | 6.25% |
| remaining Fib headroom 1.272-r-e/R | 0.3471 | 27.29% |

- r >= 0.786：81 可计算事件中 55 个（67.90%）。
- BOTH_NEAR：63 / 81（77.78%）。

## 描述性结论（不转化为生产规则）

1. **Deep Wave2 retracement 是相对 Fib headroom 的主要压缩项。** 81 个事件的 r median 为 0.8864，全部 CONFIRMED 为 0.6418；按既有 0.786 Fib 区域作描述性统计，67.90% 落在该区域。
2. **Wave1 scale 是绝对价格空间的第二个明显因素。** Fib-near 组的 Wave1 gain median 为 8.96%，全部 CONFIRMED 为 15.89%；Wave1 range / ATR14 median 为 3.3288，全部 CONFIRMED 为 4.0214。
3. **Confirmation extension 不是这 81 个事件的主要独立来源。** Fib-near 组 e/R median 为 7.02%，全部 CONFIRMED 为 18.87%；它会进一步减少 headroom，但本组并未表现出相对全部事件更大的 confirmation extension。
4. **组合机制明显存在。** 81 个 Fib-near 中 BOTH_NEAR 占 77.78% （63/81），所以不能把上一轮的 81 个直接写成“Wave1 too small”。更准确的描述是：深回撤压缩 normalized Fib headroom，较小 Wave1 scale 压缩绝对空间，并且多数事件同时有近端 confirmed swing high。
5. **全体低 T1 的 nearest-first 主导因素仍是已确认历史阻力。** 既有 198 个 T1 <5% 事件中，NEAR_SWING_ONLY=117、BOTH_NEAR=63、SMALL_WAVE_FIB=18；本轮没有因此改变 confirmed swing high 的正式候选边界。

以上是描述统计与几何分解，不是阈值选择、不是收益归因，也不是新的 production gate。
