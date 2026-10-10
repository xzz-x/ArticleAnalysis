# 银行螺丝钉 A 股投资星级复刻：当前研究状态

> 更新时间：2026-10-10  
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

截至目前，证据**不支持**“星级主要由 PE / PB / GDP / ROE / 股债性价比等多因子线性加权直接计算”。

目前最有解释力的机制是：

```text
市场价格
   ↓
price-driven continuous latent star
   +
slowly-moving anchor
   ↓
continuous latent star
   ↓
state-dependent publication threshold / hysteresis
   ↓
公开的 0.1 星离散星级
```

可以概括为：

> **星级主体由 A 股市场价格驱动，但价格到星级的映射基准会缓慢漂移；公开星级还存在一定状态黏滞 / 发布阈值，因此并不是连续理论星级变化一点就立刻调整 0.1 星。**

当前研究重点已经从“继续找更多基本面因子”转向：

1. 动态 anchor 的真实机制；
2. 发布星级的状态阈值；
3. 在真正未见未来数据上的前瞻验证。

---

## 3. 当前最大的研究问题

### 最大问题：缺乏真正独立、从未参与模型开发的未来验证期

2022–2024 最初用于训练和 expanding pre-holdout validation。

2025–2026 原本作为 locked holdout，但在研究过程中，我们已经观察过这一时期的模型表现，并据此继续提出了：

- online rolling anchor；
- adaptive anchor + hysteresis。

因此：

> **2025–2026 已不能再作为“组合架构选择”的 pristine holdout。**

虽然当前组合模型的全部数值参数仍然只在 2022–2024 上选择，但模型架构本身是在看过部分 2025–2026 结果后提出的。

所以目前真正缺少的是：

```text
完全冻结模型
    ↓
获得 2026-09-01 以后新数据
    ↓
不调任何参数
    ↓
直接前瞻预测
    ↓
检验真实泛化能力
```

这已经是当前研究最关键的瓶颈。

---

## 4. Target 数据当前状态

统一 Target 当前覆盖：

```text
2022-01-04 ～ 2026-08-31
```

当前已确认的重要 Target 修正：

| 日期 | 原标签 | 当前处理 |
| --- | --- | --- |
| 2026-01-14 | 3.7 exact | **3.8 exact**，最终下午收盘覆盖中午值 |
| 2026-04-13 | 3.9 exact | **3.9–4.0 range** |
| 2026-07-14 | 4.1 exact | **3.9–4.0 range**，最终收盘区间覆盖上午 4.1 |
| 2025-08-26 | legacy 4.2 exact | **threshold-only，training weight = 0** |

2025-08-26 的现存直接证据只能说明：

> “大盘摸到 4.2 星”

不能证明当天**收盘就是 4.2 星**，因此不再作为 exact training label。

当前训练逻辑：

- exact：可训练；
- range：按区间误差训练 / 评价；
- threshold-only：不可作为精确训练 Target；
- market closed：排除；
- 明确收盘证据 > 收盘区间 > current/opening > intraday。

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

## 8. 当前最关键发现：动态 anchor

定义某个已发布星级对应的 implied anchor：

[
A_i = S_i - eta log(P_i)
]

因为：

[
eta=-4.127707783337646
]

所以也可写成：

[
A_i=S_i+4.127707783337646log(P_i)
]

在每天预测之前，只使用**此前已经发布的星级**估计当前 anchor。

pre-holdout 自动选择出的规则：

```text
最近 10 个已发布 exact star 的 implied anchor
取 mean
```

即：

[
A_t =
rac{1}{10}
sum_{i=t-10}^{t-1}
left(
S_i-etalog P_i
ight)
]

然后当天连续潜在星级：

[
S_t^*=A_t+etalog P_t
]

即：

[
oxed{
S_t^*=A_t-4.127707783337646log P_t
}
]

online anchor 模型结果：

```text
2023–2024 pre-holdout exact MAE ≈ 0.03567

2025–2026:
static price-only exact MAE = 0.04548
online anchor exact MAE      = 0.02841
relative improvement         = 37.5%
exact error <= 0.1 star      = 100%
```

这是目前比 PB / GDP / ROE 等多因子调整强得多的证据。

---

## 9. 当前最佳候选：adaptive anchor + hysteresis

目前最强的候选结构：

```text
当前 A股全指价格
      +
最近 10 个已发布星级反推的 rolling anchor
      ↓
continuous latent star
      ↓
与上一已发布星级比较
      ↓
hysteresis
      ↓
公开 0.1 星级
```

冻结参数：

```text
price coefficient = -4.127707783337646

anchor:
  window = previous 10 published exact stars
  statistic = mean

publication threshold:
  star-up   = +0.07
  star-down = -0.06

publication step:
  0.1 star
```

完整计算逻辑：

### 第一步：rolling anchor

[
A_t =
rac{1}{10}
sum_{i=t-10}^{t-1}
left(
S_i+4.127707783337646log P_i
ight)
]

### 第二步：连续理论星级

[
S_t^*=A_t-4.127707783337646log P_t
]

### 第三步：发布规则

设上一已发布星级为 (S_{t-1})。

如果：

[
S_t^*-S_{t-1}ge0.07
]

则：

[
S_t=operatorname{round}_{0.1}(S_t^*)
]

如果：

[
S_t^*-S_{t-1}le-0.06
]

则：

[
S_t=operatorname{round}_{0.1}(S_t^*)
]

否则：

[
S_t=S_{t-1}
]

---

## 10. 当前候选表现

| 模型 | exact MAE |
| --- | ---: |
| Static price-only | 0.04548 |
| Fixed hysteresis | 0.04275 |
| Online rolling anchor | 0.02841 |
| **Adaptive anchor + hysteresis** | **0.01832** |

adaptive anchor + hysteresis：

```text
2022–2024 architecture-development / pre-holdout exact MAE ≈ 0.02217
2025–2026 exploratory/post-hoc exact MAE              ≈ 0.01832
```

相比 static price-only：

```text
约下降 59.7%
```

相比 online-anchor-only：

```text
约进一步下降 35.5%
```

### 重要限制

**0.01832 不能当作最终严格 out-of-sample 成绩。**

因为 adaptive anchor + hysteresis 这个组合架构是在已经观察部分 2025–2026 结果之后提出的。

所以当前候选只能称为：

```text
frozen prospective candidate
```

而不是：

```text
confirmed final replica
```

---

## 11. 已冻结的前瞻候选

机器可读定义：

```text
research/p2_frozen_candidate.json
```

前瞻 evaluator：

```text
research/p2_prospective_validation.py
```

冻结边界：

```text
Target cutoff      = 2026-08-31
Prospective start  = 2026-09-01
Last observed star = 4.1
```

从冻结开始，前瞻验证阶段**禁止**：

- 重新拟合 (eta)；
- 修改 10 个星级窗口；
- mean 改 median；
- 调整 +0.07 / -0.06；
- 因未来误差不好而切换价格 proxy；
- 删除难预测日期；
- 看完未来误差后再回头改模型。

当前 evaluator 状态：

```text
prospectiveRows   = 0
observedExactRows = 0
exactMae          = null

status =
awaiting_genuinely_unseen_price_and_target_data
```

现有 Google Drive corpus 尚未检索到可靠的 2026-09 / 2026-10 新 A 股指数估值文章，因此目前没有污染这个未来验证窗口。

---

## 12. 当前最大未知：真实 anchor 到底是什么

rolling 10-star mean 在预测上表现很好，但它只是**复刻方法**，不一定就是银行螺丝钉真实内部公式。

真实 anchor 可能来自：

- 全市场盈利长期增长；
- 指数成分股变化；
- PE / PB 估值中枢长期变化；
- 盈利 / GDP；
- 人工定期重新标定；
- 某种长期估值分位；
- 多种慢变量共同作用。

所以需要区分两个目标：

### A. 复刻目标

只要：

```text
past published stars + current price
```

就能高精度预测下一星级。

当前已经取得明显进展。

### B. 机制解释目标

要进一步回答：

> 银行螺丝钉自己为什么会调整这个 anchor？

这个问题目前还没有解决。

---

## 13. 下一步工作的优先级

### P2-A：真正前瞻验证

一旦获得 2026-09-01 之后：

- A 股全指价格；
- 新公开星级；

直接运行冻结 evaluator。

**不得重新调参。**

这是最高优先级。

### P2-B：补旧历史语料

如果能够恢复 2012–2020 公众号历史文章，则可覆盖：

- 2015 牛市；
- 2016–2018；
- 2019–2021；
- 多轮完整牛熊周期。

这样才能真正检验：

- anchor 是否长期漂移；
- anchor 是否存在结构性 reset；
- 10-star rolling mean 是否只是近几年特例；
- hysteresis 是否跨周期稳定。

### P2-C：解释 anchor

只有在更长历史中确认动态 anchor 稳定存在后，再研究：

```text
anchor_t
~
earnings
GDP
PB/PE regime
index composition
rate environment
manual reset
```

不要提前重新堆多因子。

### P2-D：继续 Target 审计

原则：

> 先判断 residual 是不是标签问题，再判断是不是机制问题。

明确收盘 exact 不能因为模型误差大就被改写。

---

## 14. 当前项目文件导航

后续新会话优先阅读：

```text
research/CURRENT_RESEARCH_STATE.md
research/p2_frozen_candidate.json
research/p2_price_mechanics_findings.md
```

核心脚本：

```text
research/dynamic_price_residual_analysis.py
research/p2_discrete_price_mechanics.py
research/p2_online_anchor_analysis.py
research/p2_adaptive_hysteresis_analysis.py
research/p2_prospective_validation.py
```

Target：

```text
data/derived/star_target_2022_2026_unified.csv
data/derived/star_target_2022_2026_audit.json
```

当前研究分支：

```text
research/p2-price-mechanics
```

PR：

```text
#3 P2: clean targets and model adaptive price mechanics
```

在真正前瞻验证完成之前：

> **不要把 P2 候选合并成“已确认最终公式”的结论。**

---

## 15. 一句话研究状态

> **当前最有希望的复刻公式是“价格驱动的连续潜在星级 + 最近已发布星级反推的动态 anchor + hysteresis 发布规则”；历史拟合已经非常接近，但最大的剩余问题是缺少完全未参与模型开发的 2026-09-01 以后未来数据进行严格前瞻验证。**
