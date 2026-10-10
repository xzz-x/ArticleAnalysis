# 银行螺丝钉 A 股投资星级复刻：当前研究状态

> 更新时间：2026-10-11  
> 当前研究分支：`research/p2-price-mechanics`  
> 稳定生产基线：`main`  
> 当前 P2 PR：#3（Draft，尚未合并 main）  
> 本文件是后续研究的**首要上下文入口**。如本文件与较早 README / P0 / P1 说明存在冲突，以本文件和 `research/p2_frozen_candidate.json` 为准。

---

## 1. 项目目标

目标是逆向复刻银行螺丝钉每日公开的 **A 股投资星级**。

研究原则：

- 优先寻找可解释、稳定、可复现的规则；
- 不以黑箱拟合精度替代机制解释；
- Target 证据优先级高于模型残差；
- 不能因为模型解释不了某一天，就反过来修改有明确收盘证据的真实星级；
- 所有模型选择和参数选择必须尽量与最终验证数据隔离。

---

## 2. 当前最重要的结论

截至目前，最稳定的结论仍然是：

> **A 股投资星级的短期变化主要由 A 股市场价格驱动。**

当前没有证据支持“PE / PB / GDP / ROE / 股债性价比等多个基本面指标直接线性加权生成每日星级”。

但第一段真正未见未来数据（2026-09-01 至 2026-10-09，23 个交易日）改变了对 P2 复杂机制的判断：

- 冻结的 `adaptive anchor + hysteresis` 候选前瞻 MAE = **0.02174**；
- 23 天中 **18 天精确命中（78.26%）**；
- **23/23 天误差都不超过 0.1 星**；
- 但预先存在的更简单模型 `static price + nearest 0.1 rounding` 在同一未来窗口 MAE = **0.01304**，精确命中 **20/23（86.96%）**。

因此当前不能再写：

> dynamic anchor + hysteresis 已经是最有可能的真实生产公式。

更准确的当前结论是：

```text
核心确定项：
A股全指价格
    ↓
continuous latent star

仍待区分的发布机制：
A. static anchor + nearest 0.1 rounding
B. slowly-moving anchor + hysteresis
```

**价格主导已经比较稳；anchor 是否需要动态调整、hysteresis 是否是稳定真实机制，目前仍未定。**

详细首轮前瞻验证见：

```text
research/p2_first_prospective_validation.md
```

---

## 3. 当前最大的研究问题

### 最大问题：简单模型和复杂模型，谁能在更长的真正未来数据中持续胜出？

此前最大的瓶颈是没有真正未见未来数据。这个问题已经解决了第一步：

```text
冻结日期：2026-08-31
真正未来窗口：2026-09-01 ～ 2026-10-09
交易日 exact Target：23 个
```

这一窗口没有用于原候选参数调整。

结果出现了一个关键分歧：

| 模型 | 首轮真正 prospective MAE |
| --- | ---: |
| **Static price + nearest 0.1** | **0.01304** |
| Frozen adaptive anchor + hysteresis | 0.02174 |
| Static continuous price | 0.02206 |
| Online-anchor continuous | 0.02343 |
| Previous-star persistence | 0.03913 |

所以现在最大的研究问题已经变成：

> **2025–2026 历史阶段 adaptive 模型的明显优势，是长期真实机制，还是对当时 anchor 漂移的阶段性拟合？**

不能用这 23 天重新调参数回答这个问题。

正确方法是：

1. 保留原 frozen adaptive candidate，不改任何参数；
2. 同时保留 static price + nearest-0.1 作为简单 challenger；
3. 从 2026-10-09 之后继续收集真正未见数据；
4. 做连续 head-to-head；
5. 只有跨更长窗口、不同市场波动阶段仍稳定胜出，才提升为主要 replica 机制。

当前最重要的是**模型简化检验和持续前瞻验证**，不是继续堆新变量。

---

## 4. Target 数据当前状态

历史统一 Target 仍覆盖：

```text
2022-01-04 ～ 2026-08-31
```

另外已经建立独立的、严格 post-freeze 的未来验证集：

```text
data/verified/star_target_prospective_2026_09_onward.csv
```

当前包含：

```text
2026-09-01 ～ 2026-10-09
23 个 A 股交易日
23 个 exact closing star Target
```

对应价格证据：

```text
data/verified/csi_all_share_prospective_2026_08_31_2026_10_09.csv
```

价格口径是 `000985.SH` 中证全指点位，与冻结的 A股全指代理口径一致；重叠日：

```text
2026-08-31 close = 5969.33
```

与原冻结序列完全匹配。

重要历史 Target 修正仍然有效：

| 日期 | 原标签 | 当前处理 |
| --- | --- | --- |
| 2026-01-14 | 3.7 exact | **3.8 exact** |
| 2026-04-13 | 3.9 exact | **3.9–4.0 range** |
| 2026-07-14 | 4.1 exact | **3.9–4.0 range** |
| 2025-08-26 | legacy 4.2 exact | **threshold-only，training weight = 0** |

未来 Target 与历史训练 Target 分开保存，避免把真正 prospective evidence 悄悄回灌进训练集。

---

## 5. P1：静态 price-only 基线

固定使用：

```text
A股全指（1000002）
```

基本模型：

[
S_t = alpha + eta log(P_t)
]

当前估计：

[
eta = -4.127707783337646
]

也就是：

[
S_t approx alpha - 4.1277log(P_t)
]

含义：

- 指数上涨 → 星级下降；
- 指数下跌 → 星级上升。

当前清洗后的 2025–2026 exact MAE：

```text
0.04548 星
```

一个 0.1 星的连续潜在星级距离，对应约：

[
e^{0.1/4.1277}-1 approx 2.45%
]

即：

```text
理论连续潜在星级相差 0.1
≈ 指数价格相差 2.45%
```

注意：这不是说“单日必须涨跌 2.45% 才会改变 0.1 星”。如果当天已经靠近发布阈值，较小涨跌也可能触发星级变化。

---

## 6. 已测试但目前不支持的多因子解释

P1 曾系统测试：

- PB 长期百分位；
- PE / PB 估值变量；
- 股债性价比；
- 巴菲特指标；
- GDP；
- 盈利增长；
- ROE；
- 成交 / 换手；
- 融资数据；
- 其他市场情绪变量。

其中 10 年 PB 百分位在 2023–2024 pre-holdout validation 曾改善拟合，但在 2025–2026 明显失效：

```text
static price-only exact MAE ≈ 0.04548
price + PB exact MAE       ≈ 0.10733
```

因此目前不能把 PB 作为稳定 residual correction。

慢基本面 anchor 候选也没有在严格 pre-holdout 规则下稳定胜过 price-only。

当前结论：

> **没有证据证明需要继续堆叠 PB、GDP、ROE 等因子才能解释星级。**

---

## 7. P2：离散化 / hysteresis

单纯连续价格模型不能完全解释：

- 为什么价格每天波动，但公开星级经常不动；
- 为什么星级往往以 0.1 为单位跳变；
- 为什么向上和向下切换可能存在不同阈值。

因此测试了：

1. continuous；
2. 0.1 rounding；
3. sticky threshold；
4. asymmetric hysteresis。

仅在 2022–2024 pre-holdout 阶段选出的固定 hysteresis：

```text
star-up threshold   = 0.07
star-down threshold = 0.11
```

对应 2025–2026 exact MAE：

```text
0.04275
```

相比 static price-only 约改善 6%。

但进一步按 3.x / 4.x / 5.x 分层后，发现阈值并不是稳定常数。

例如：

```text
pre-holdout 4.x:
  star-down median trigger gap ≈ 0.127
  star-up   median trigger gap ≈ 0.024

later 4.x:
  star-down ≈ 0.101
  star-up   ≈ 0.062
```

因此不能把固定 0.07 / 0.11 当作真实生产公式。

更合理的解释是：

```text
threshold effect
+
anchor drift
+
price proxy / Target noise
```

共同作用。

---

## 8. 历史阶段的重要发现：动态 anchor

历史分析中，动态 anchor 曾带来很明显的改善。

定义 implied anchor：

[
A_i = S_i - eta log(P_i)
]

其中：

[
eta=-4.127707783337646
]

2022–2024 pre-holdout 选择出的 online rule 是：

```text
最近 10 个已发布 exact star 的 implied anchor
取 mean
```

2025–2026 历史评估：

```text
static price-only exact MAE = 0.04548
online anchor exact MAE      = 0.02841
adaptive+hysteresis          = 0.01832  (post-hoc architecture)
```

这曾提示 anchor drift 可能非常重要。

但是第一段真正 prospective data 中：

```text
static continuous      MAE = 0.02206
online-anchor continuous MAE = 0.02343
```

online anchor 并没有改善 static continuous。

因此现在应把 dynamic anchor 定义为：

> **一个具有较强历史解释力、但尚未通过跨窗口前瞻优越性验证的机制假设。**

不能再把它当作已确认事实。

---

## 9. 原冻结候选：adaptive anchor + hysteresis

原 frozen candidate 保持完全不变：

```text
research/p2_frozen_candidate.json
```

参数：

```text
price coefficient = -4.127707783337646
anchor window      = prior 10 published exact stars
anchor statistic   = mean
star-up threshold  = +0.07
star-down threshold= -0.06
publication step   = 0.1
freeze cutoff      = 2026-08-31
```

它的第一段真正前瞻结果：

```text
n = 23
MAE = 0.02174
RMSE = 0.04663
exact match = 78.26%
within 0.1 star = 100%
max error = 0.1
```

真实星级变化日有 9 天，模型只预测变化 4 天：

```text
change recall     = 44.44%
change precision  = 100%
```

说明冻结 hysteresis **偏保守**：

- 没有错误触发不存在的变化；
- 但漏掉 5 次真实 0.1 星变化。

漏掉日期：

```text
2026-09-04  predicted 4.1, actual 4.2
2026-09-10  predicted 4.1, actual 4.2
2026-09-15  predicted 4.2, actual 4.3
2026-09-18  predicted 4.2, actual 4.1
2026-10-08  predicted 4.3, actual 4.4
```

**禁止根据这些错误把 0.07 / 0.06 调小。**

---

## 10. 第一段真正前瞻模型比较

同一 23 日窗口：

| 模型 | MAE | Exact match | Max error |
| --- | ---: | ---: | ---: |
| **Static price + nearest 0.1 rounding** | **0.01304** | **86.96%** | 0.1 |
| Frozen adaptive + hysteresis | 0.02174 | 78.26% | 0.1 |
| Static continuous | 0.02206 | — | 0.0625 |
| Online-anchor continuous | 0.02343 | — | 0.0654 |
| Previous-star persistence | 0.03913 | 60.87% | 0.1 |

static continuous 公式仍然是：

[
S_t^*=39.95198926812065-4.127707783337646log(P_t)
]

简单 challenger：

[
S_t=operatorname{round}_{0.1}(S_t^*)
]

这个 model class 在未来数据恢复之前已经存在于 P2 discrete candidate set 中，所以可以合法作为 prospective comparator。

需要同时看到两边证据：

- 在较长的 2025–2026 已观察历史阶段，static nearest-0.1 的 MAE 约 **0.03766**，比 adaptive post-hoc 的 0.01832 差；
- 但在真正未来的 23 天里，static nearest-0.1 **反而最好**。

因此暂时没有资格选出最终生产公式。

---

## 11. 当前研究判断

现在最可靠的机制层级是：

### 高置信度

```text
A股全指价格
    ↓
星级主要反向变化
```

### 中等置信度

```text
存在一个近似线性的 log-price → latent-star 映射
系数约 -4.1277
```

### 尚未确认

```text
anchor 是否持续动态漂移
是否必须使用最近10个星级校准
是否存在稳定 hysteresis
上下行阈值是否固定
```

第一段未来数据明显提高了“**简单 static anchor + 0.1 rounding**”的可信度。

但 23 天仍然太短，不能否定长期 anchor drift。

---

## 12. 下一阶段实验设计

后续不再用 2026-09-01～2026-10-09 调任何旧候选参数。

从 **2026-10-09 之后的新交易日**开始，至少并行跟踪：

### Model A：原 frozen adaptive candidate

```text
10-star rolling anchor
+
price latent score
+
+0.07 / -0.06 hysteresis
```

参数永不回调。

### Model B：simple static-round challenger

```text
latent =
39.95198926812065
-4.127707783337646 * log(price)

prediction =
nearest 0.1 star
```

不增加参数。

主要比较：

- MAE；
- exact match；
- ≤0.1 rate；
- change-day recall / precision；
- 连续不同市场阶段的稳定性。

只有未来样本继续扩展后，才能决定 Model A 还是 Model B 更接近真实规则。

---

## 13. 仍需补的长期证据

### A. 继续前瞻采集

优先级最高。

每新增公开星级：

1. 保存原始公开证据；
2. 保存同日 000985.SH 收盘点位；
3. 不改模型；
4. 直接追加 prospective evaluation。

### B. 补 2012–2020 历史语料

用于判断：

- static intercept 是否跨周期稳定；
- anchor 是否只在某些牛熊阶段 reset；
- hysteresis 是否是长期规律。

### C. 解释 anchor

只有当长周期证据重新确认 anchor drift 后，再研究：

```text
earnings / GDP
PE/PB regime
index composition
interest rates
manual recalibration
```

目前不应重新堆多因子。

---

## 14. 当前文件导航

后续新会话优先阅读：

```text
research/CURRENT_RESEARCH_STATE.md
research/p2_first_prospective_validation.md
research/p2_frozen_candidate.json
research/p2_price_mechanics_findings.md
```

未来验证数据：

```text
data/verified/star_target_prospective_2026_09_onward.csv
data/verified/csi_all_share_prospective_2026_08_31_2026_10_09.csv
```

核心脚本：

```text
research/p2_prospective_validation.py
research/fetch_csi_all_share_prospective_prices.py
research/p2_adaptive_hysteresis_analysis.py
research/p2_online_anchor_analysis.py
research/p2_discrete_price_mechanics.py
research/dynamic_price_residual_analysis.py
```

冻结完整性测试：

```text
tests/test_p2_frozen_candidate.py
```

当前分支：

```text
research/p2-price-mechanics
```

PR：

```text
#3 P2: clean targets and model adaptive price mechanics
```

---

## 15. 一句话研究状态

> **短期星级由价格主导已经较稳；第一段未来验证更偏向 static price + 0.1 rounding，而官方长期证据又明确表明同星级点位会随盈利增长上移。当前最关键的下一步，是保持未来模型不调参，同时取得并版本化 2012–2021 小程序 backcast 星级，与 contemporaneous 历史发布值重叠校准，识别长期 anchor 和方法版本演化。**

---

## 16. 官方披露机制与盈利水平的新结论

2026 年银行螺丝钉公开课程明确说明：星级综合考虑整体估值、盈利增长、成交量和市场情绪；同样 5 星时，中证全指约从 2013 年 2700 点、2018 年 3400 点上移到 2024 年 4800 点，并明确把这种长期点位抬升主要归因于上市公司盈利增长。

因此，一个固定 intercept 的 price-only 公式不可能是 2012–2026 全历史的永久生产公式。

但目前 source-aligned 实证同时表明：

- 按作者公布锚点校准后的中证全指股债性价比口径可信，但没有稳定击败 price-only；
- PE / PB / 巴菲特指标 / 股债性价比直接组成每日星级模型，也没有稳定胜过 price-only；
- aggregate earnings level = A股全指点位 / 中证全指 PE 的日频增量作用很小且不稳定；
- earnings-level raw coefficient 从约 0.41 降到 0.14，在完整 2022–2024 拟合中收缩为 0；
- 用 earnings level 校正月度 implied anchor 后，anchor 波动反而显著放大。

所以当前必须按时间尺度区分：

```text
短期（日频）：价格绝对主导。
中期（2022–2026）：当前 price/PE 构造的盈利水平不能解释 anchor 漂移。
长期（跨多年）：官方明确认为盈利增长会抬高同星级对应的指数点位；
这一点需要更长、版本化的历史星级才能真正检验。
```

相关分析：

```text
research/p2_official_mechanism_evidence.md
research/p2_earnings_level_anchor_model.py
research/p2_earnings_timescale_decomposition.py
```

---

## 17. 历史星级版本政策

现有 contemporaneous 证据显示发布精度和方法存在明显版本变化：

```text
2018：4/5 星仍被明确描述为经验性的粗分类。
2021：公开文章大量使用 3.5 / 4.0 半星级。
2022-04-07：明确同时出现“粗算 4.5、细算 4.8”。
2022-05-31：出现“现在算 4.9”的 0.1 星过渡标记。
2022-06 以后：0.1 星发布逐渐稳定。
```

因此以后即使从「今天几星」小程序取得 2012–2021 完整历史，也必须区分：

```text
contemporaneous_published_star
vs
current_app_backcast_star
```

不能把小程序回溯值直接覆盖当年真实发布值。

相关文件：

```text
research/p2_historical_star_version_policy.md
data/verified/star_historical_version_anchors.csv
```

当前最大的长期机制问题进一步收敛为：如何取得并版本化 2012–2021 小程序 backcast 星级，并与同期公开文章 contemporaneous 星级做重叠校准，以判断小程序是否使用了回溯重算公式。

---

## 18. 2021 跨周期验证的新结论

已从现有 Google Drive contemporaneous 公众号语料中恢复一批 2021 历史星级：

```text
data/verified/star_target_2021_crosscycle_sample.csv
```

当前样本：

```text
24 个日期
23 个 0.5 星粗粒度公开状态
1 个 3.5-4.0 明确边界
```

2021 的发布体系和现代 0.1 星体系不同。同期文章明确显示：

- 3.5 / 4.0 半星级是公开状态；
- 2021-03-23 讨论 3.5 与 4.0 边界反复切换；
- 2021-09-24 同时写“还是3.5星级”和“约在3.9星级的水平”。

因此 2021 的 3.5 应理解为 coarse bucket，而不是现代意义上的精确 3.5 点：

```text
3.5-star publication ≈ latent [3.5, 4.0)
4.0-star publication ≈ latent [4.0, 4.5)
```

用完全不重训的现代 static price formula 向后投射：

```text
latent =
39.95198926812065
-4.127707783337646 * log(CSI All Share)
```

按正确 coarse-bucket 语义评价：

```text
2021 coarse-bucket MAE ≈ 0.173 star
直接落入正确 bucket ≈ 25%
最大 bucket miss ≈ 0.689 star
```

因此：

> **2022-2024 的 fixed-intercept static formula 不是跨 2021-2026 的永久公式。**

但如果保持 price slope 完全不变，只做一个 post-hoc intercept translation 来量化 anchor 位移：

```text
full 2021 best shift ≈ -0.389 star
bucket MAE after shift ≈ 0.045
inside-bucket rate ≈ 75%
```

而且 2021 内部也有变化：

```text
Jan-Apr best shift ≈ -0.48
Sep-Nov best shift ≈ -0.21
```

这进一步支持：

```text
短期：price slope 相对稳定
长期：anchor / 同星级对应点位会移动
发布层：历史粒度与现代粒度不同
```

这与官方长期例子“同为5星，中证全指点位从 2013/2018 到 2024 持续上移，主要归因于上市公司盈利增长”的方向一致，但目前不能把 2021 intercept shift 全部解释为盈利增长，因为其中还可能包含方法版本变化和 coarse publication effect。

这轮历史工作还发现并修复了一个 Target parser bug：

```text
没有回到4星级
没回到4星级
```

此前可能被误识别为当前 4 星；现在已加入 negation filter 和 regression tests。

详细记录：

```text
research/p2_2021_crosscycle_findings.md
research/p2_2021_crosscycle_validation.py
```

### 当前最重要的机制问题进一步收敛

现在已经不应继续争论“static 还是 dynamic 哪个日频拟合更漂亮”。

更准确的问题是：

> **短期价格敏感度似乎相对稳定，但长期 anchor 如何随盈利、估值体系和方法版本共同演化？**

下一阶段长期研究的最高优先级仍是：

1. 获取并版本化 2012-2021 小程序 backcast 星级；
2. 与 contemporaneous published star 做重叠校准；
3. 判断小程序历史序列是否经过统一回溯重算；
4. 在版本化历史 Target 上再研究长期 anchor 与盈利水平的关系。



---

## 19. P3：「今天几星」小程序入口与历史 backcast 时间线

已从银行螺丝钉公众号原始归档 HTML 中恢复「今天几星」小程序唯一标识：

```text
nickname = 今天几星
appid    = wx132d40a0c36674a6
path     = pages/discovery/index
```

同一 AppID / path 在 2023-05-24、2023-07-17、2024-04-24、2024-07-20、2024-08-27、2024-09-03 等归档文章中重复出现。

更重要的是，历史功能存在明确的版本演化：

```text
2023-05-24
小程序首发。
当时描述的是交易日 09:30 / 12:00 / 14:30 / 16:00 固定时点星级播报；
文章同时说明后续功能会继续开发。

2023-07-17
官方明确写“上线了一个新功能：历史星级查询”。
首页顶部进入“查看历史星级”。
当时 UI 可查询 2014 年至当时的星级和中证全指点位。
同时明确写：2014 年以前的数据后台也有，等待优化后更新。

2024-07-20
最新星级已升级为每分钟更新；历史星级仍作为独立功能保留。

2026
公开使用说明已描述为可查询 2012 年以来任意交易日。
```

因此现在可以确认：

> **小程序历史星级是 2023 年以后逐步上线、补齐和展示的 retrospective dataset。**

这进一步强化现有版本治理原则：

```text
contemporaneous_published_star
!=
current_app_backcast_star
```

即使取得 2012-2021 全量小程序历史，也不能直接覆盖当年真实发布 Target。

### API 调研现状

公开索引中暂未找到：

- AppID 对应的可下载 wxapkg；
- 已反编译源码；
- request 合法域名白名单；
- 明文历史星级 API。

仅凭 AppID 和入口 path 还无法可靠枚举生产接口。

下一步最有价值的技术动作是：

1. 在正常用户会话中打开历史星级图；
2. 导出该操作产生的 HAR / 网络请求记录；
3. 从运行时请求中识别历史序列 endpoint；
4. 再判断 endpoint 是否支持日期区间或整段历史批量请求。

已新增：

```text
research/p3_today_star_miniprogram_findings.md
research/extract_today_star_har.py
tests/test_today_star_har_extractor.py
```

HAR 工具只做候选筛选，并主动隐藏 cookie / authorization / token 等敏感字段，不涉及 Model A / Model B 的任何参数修改。

### 公共历史源的备选路线

如果短期内仍拿不到运行时接口，继续用 contemporaneous 公开源扩展跨周期锚点。

目前可直接确认的例子包括：

```text
2018-12-19
银行螺丝钉雪球文章：
“目前市场处于4星级”
并明确说明当时四/五星属于经验判断、没有特别严格的说法。

2020-09-24
银行螺丝钉雪球文章：
市场距离4星级不到2%。
这是 threshold evidence，不应擅自转换成 exact star。

2020-07-14
雪球基金转述银行螺丝钉：
“A股市场接近3星级”。
这是二手 contemporaneous 证据，只适合作为候选锚点，不进入 exact Target。
```

因此长期 Target 恢复继续遵守：

```text
direct closing exact
>
direct closing range / bucket
>
direct threshold statement
>
secondary contemporaneous quote
>
retrospective statement
>
current-app backcast
```

任何 threshold / secondary evidence 均不因模型 residual 大小而被升级为 exact。
