# ArticleAnalysis

文章语料分析与投资研究实验仓库。

当前重点项目：**银行螺丝钉公众号历史文章分析与“投资星级”复刻**。

## 当前研究状态（后续工作请先读）

当前权威研究快照：

```text
research/CURRENT_RESEARCH_STATE.md
```

冻结候选与首轮真正前瞻验证：

```text
research/p2_frozen_candidate.json
research/p2_static_round_challenger.json
research/p2_first_prospective_validation.md
```

当前 P2 已完成第一段真正未见未来窗口（2026-09-01 至 2026-10-09，23 个交易日）。
价格主导假设继续得到支持，但原 frozen adaptive candidate 并未在该窗口胜过更简单的
`static price + nearest 0.1 rounding`。当前最大问题已经变成：**dynamic anchor / hysteresis
究竟是长期真实机制，还是主要解释了此前 2025–2026 的阶段性漂移**。后续从 2026-10-09
之后继续保持两套模型不调参做 head-to-head prospective validation。
较早 P0/P1 段落保留用于研究过程追踪；若数值或结论与当前快照冲突，以
`research/CURRENT_RESEARCH_STATE.md` 和冻结 spec 为准。

## 分支约定

- `main`：只保留稳定、可复用的项目基线。
- 稳定基线以 `main` 为准；研究改动从 `main` 新建短期分支并通过 PR 验证，旧 `research/screw-star-replica` 不再作为最新研究基线。
- 原始大体量文章语料不提交 Git；当前计划以 Google Drive 作为 canonical corpus storage。
- GitHub 只保存代码、配置、manifest、提取后的结构化 Target 与研究结果。

## 当前阶段

第一阶段先解决历史星级 Target：

```text
Google Drive 原始公众号语料
        ↓
本地同步 / 挂载目录
        ↓
正文解析 + SHA256 manifest
        ↓
Parquet 标准化语料
        ↓
SQLite FTS5 全文检索
        ↓
星级语句候选提取
        ↓
人工/规则复核
        ↓
star_target.csv
```

现在**不直接训练最终星级模型**。先尽可能恢复 2012–2026 年银行螺丝钉真实发布的历史星级。

## 为什么原始语料不放 GitHub

公众号文章总体量可达到数 GB，属于数据资产而不是源代码。原始文章应继续保存在 Google Drive；仓库通过 manifest 的 `relative_path + sha256` 记录所使用语料版本，保证数据血缘和可重复性。

本项目默认从 Google Drive 已同步/挂载到本机或服务器的目录读取，不提交 Google 凭据，不把本机绝对路径写入代码。

通过环境变量指定语料根目录：

```bash
export ARTICLE_ANALYSIS_CORPUS_ROOT="/path/to/screw_star_corpus"
```

## 安装

建议 Python 3.10+：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## 运行

### 1. 解析语料并建立 manifest

```bash
article-analysis --config config.example.yaml ingest
```

默认产生本地文件：

```text
.local/screw_star/articles.parquet
.local/screw_star/corpus_manifest.parquet
```

其中 `corpus_manifest.parquet` 不保存正文，只保存文章 ID、日期、标题、相对路径、文件大小、SHA256、重复文件标记等信息。

### 2. 建立全文索引

```bash
article-analysis --config config.example.yaml build-index
```

默认建立：

```text
.local/screw_star/corpus.sqlite3
```

优先使用 SQLite FTS5 `trigram` tokenizer，便于中文子串搜索；本地 SQLite 不支持时自动回退到 `unicode61`。

### 3. 搜索公众号历史文章

```bash
article-analysis --config config.example.yaml search '股债性价比'
article-analysis --config config.example.yaml search '巴菲特指标'
article-analysis --config config.example.yaml search '五星级机会'
```

### 4. 提取星级候选

```bash
article-analysis --config config.example.yaml extract-stars
```

输出：

```text
.local/screw_star/star_candidates.csv
```

字段包括：

```text
article_id
publish_date
title
star
context
pattern
confidence
relative_path
```

注意：`star_candidates.csv` 只是**候选语句**，不是最终 Target。文章里可能出现历史回顾、举例、规则解释等星级数字，因此必须继续做语义复核，并区分 realtime 与 backfilled 数据。

### 5. 构建每日 A 股 realtime Target

```bash
article-analysis --config config.example.yaml build-daily-target
```

输出：

```text
.local/screw_star/star_daily_target.csv
.local/screw_star/star_daily_review_queue.csv
```

该步骤只扫描每篇 A 股“指数估值数据”文章的开头，并按以下证据优先级选择一个值：

1. 明确的收盘语句，例如“截止到收盘，回到4.2星”；
2. 同句的“今天大盘”实时语句；
3. 开头的“还在 / 回到 / 重回”等状态语句。

它会排除“美股指数估值数据”中的全球星级、往期文章链接、图书星级和正文中的历史回顾；盘中与收盘值同时出现时优先收盘值；正文只提供 `4.9-5星` 等区间时不猜测精确值，而是写入 review queue。

2025-01-02 至 2026-08-31 的当前语料实跑结果：文本自动恢复 393 个精确 A 股 realtime Target；估值表图片又核验 3 个，合计 396 个。12 篇仍未进入精确 Target，其中 5 篇为 A 股休市，另有 7 个交易日只有区间/阈值证据。除文章开头证据外，正文中“目前 YYYY 年 M 月 D 日，市场在 X 星”的日期完全匹配语句也可补充精确值；日期不匹配的模板文本不会被采用。

图片核验单独保存在 `data/verified/star_target_image_seed.csv`。当前只接纳“正文范围 + 星形填充比例”能互相交叉确认的 2026-04-22（3.7）、2026-05-06（3.6）和 2026-08-14（4.0）；接近或超过 5 星的图形会饱和，不能安全区分 5.0 以上的小数，因此继续留在 review queue。

## 目标 Target 数据结构

后续经过验证后生成可进入 Git 的小型研究数据：

```text
date
star
source
source_url
source_type
realtime_or_backfilled
confidence
article_id
notes
```

最终 Replica 模型优先使用当时实时发布的 `realtime` 星级。

### 恢复历史 realtime Target

```bash
python research/build_historical_realtime_target.py
```

历史流水线与 2025–2026 使用同一套“当前/收盘证据优先”的原则，并额外针对早期文章做保守处理：
历史回顾、假设句、阈值描述、盘中值和明确的旧日期不会成为 exact Target；仅写“5星级”等整数
regime 而没有小数精度时，也不会强行解释为精确的 5.0。输出为
`data/derived/star_target_historical_direct.csv`、`star_target_historical_review_queue.csv`
和审计文件。

当前 Google Drive canonical corpus 中可用于这一阶段的历史年份为 **2021–2024**；
**2012–2020 语料目前缺失**，审计文件会明确记录为 corpus missing，不做插值或反推。
2022–2024 进入统一 Target 前还会经过已验证 A 股交易日集合的 calendar gate，避免春节、清明、
劳动节等假期文章中的参考星级被误当成新的日频 Target。

### 统一 2022–2026 Target

```bash
python research/build_unified_star_target.py
```

输出 `data/derived/star_target_2022_2026_unified.csv`，保证每个日期最多一条记录，
并保留 `star_low` / `star_high`、证据置信度与训练权重。2022–2024 与 2025–2026 均优先采用
可核验的公众号 direct evidence；旧年度表只填补 direct evidence/review queue 未覆盖的交易日。
区间不会被旧年度表中的单点覆盖，休市文章进入 exclusions，只有阈值描述而没有数值区间的记录
权重为零。来源冲突和合并规则记录在同目录的 audit/conflicts 文件中。

截至本轮审计，统一 Target 仍为 **1129 个日期**（2022-01-04 至 2026-08-31），其中
2022–2024 有 **472 条 historical direct exact evidence**、**62 条 direct interval/threshold**
和 **192 条 verified annual fallback**；全样本当前共有 **1126 条可训练记录**；2025-08-26 已在 P2 审计中从 legacy exact 降级为 threshold-only、训练权重为 0。历史 direct
小数证据与 legacy 年度表中已人工核验的已知冲突已清零。

### 构建 point-in-time 因子面板

```bash
python research/build_star_factor_panel.py
```

输出全历史日频 `data/features/star_factor_daily.parquet`，以及与统一 Target 对齐的
`star_model_panel_2022_2026.parquet` / `.csv`。面板同时保留 A股全指和中证全指口径，
包括巴菲特指标、股债性价比、PE/PB 本地滚动分位、盈利增长、ROE、成交和融资因子。
财报按理杏仁 `reportDate` 生效；缺少正式发布日期的 GDP 和投资者数据采用保守滞后，
且每个来源的可得日期随行保留用于未来函数审计。

### 核心三因子滚动验证

```bash
python research/core_factor_validation.py
```

脚本只用 2022–2024 数据做扩展窗口选型和拟合，锁定规格后再检验 2025–2026。
候选集覆盖两个指数、五种估值口径、两个巴菲特指标口径和 5/10/20 年 PB 分位，
并约束巴菲特指标和 PB 分位与星级负相关、股债性价比与星级正相关。输出候选排名、
留出集指标和逐日预测至 `data/derived/core_factor_validation_*`；同时与单一指数点位基线比较。

截至 2026-09-23 的验证结果：

| 项目 | 核心三因子 | 指数点位基线 |
| --- | ---: | ---: |
| 2025–2026 精确标签 MAE | 0.1625 | 0.0452 |
| 误差不超过 0.1 的比例 | 30.30% | 95.20% |
| 星级整数区间准确率 | 69.44% | 88.13% |

滚动选型从 60 个候选中选出 A股全指、`avg` 估值口径、流通市值/GDP 和 10 年 PB
分位组合。该规格在 2023–2024 选型窗口的精确标签 MAE 为 0.0847，但在完全隔离的
2025–2026 留出期，误差为点位基线的 3.60 倍；2025 和 2026 分年结果均落后，
因此不是单月异常。股债性价比系数在各训练窗口均被单调约束压至 0，当前未表现出
稳定的独立解释力。

当前结论是：核心三因子不能替代原星级规则。验证流程已检查因子方向、留出期隔离和
point-in-time 日期。

### 动态点位基线与残差验证（P1）

```bash
python research/dynamic_price_residual_analysis.py
```

P1 固定使用 A股全指，先以 2022–2024 拟合 `Star ~ log(index price)`，再把 PB 百分位、
股债性价比、巴菲特指标、盈利增长、ROE、成交/换手和融资等变量分别作为单一增量因子。
因子只能依据 2023/2024 expanding-window validation 进入模型；**2025–2026 完全锁定为 holdout**。
脚本运行时会重新读取最新统一 Target，而不是使用 factor panel 中可能过期的嵌入式标签。

最新结果：

| 项目 | 结果 |
| --- | ---: |
| Price-only 2025–2026 exact MAE | **0.0460** |
| Price-only 误差 ≤ 0.1 | **95.20%** |
| Price-only 星级整数区间准确率 | **88.38%** |
| 预留期最佳 residual 因子 | 10 年 PB 百分位 |
| Price + PB 的 holdout exact MAE | **0.1072** |
| 星级变动日方向与指数涨跌反向一致率 | **97.86%** |
| 星级变化模型 holdout MAE | **0.0333 星** |

10 年 PB 百分位在 2023–2024 预留前验证中曾将 exact MAE 从 0.1086 改善至 0.0955，
但在真正锁定的 2025–2026 holdout 中明显失效，因此**不能作为稳定残差修正项**。
真正的慢基本面候选中，表现最好的流通市值/GDP 在预留前阶段已弱于 price-only
（0.1113 vs 0.1086），所以 slow fundamental anchor 本轮不进入 holdout。

当前证据更支持：**短期星级更新主要由市场价格/点位驱动；已测试的估值、情绪和慢基本面变量
尚未证明具有稳定、跨期的增量解释力。** 年度 implied price anchor 也没有表现出简单单调漂移，
因此暂不能把盈利/GDP 写成固定的长期重定标公式。下一步应重点调查 price-change residual
最大的日期，并在获得 2012–2020 旧语料后再检验跨完整牛熊周期的 anchor drift。

当前 CI 会先重建统一 Target，再运行完整测试，并继续执行 P1、P2 离散机制、online anchor、adaptive hysteresis 和 frozen prospective evaluator；最新 P2 流水线已通过。


## 与 xzz-x/ETF 的关系

`xzz-x/ETF` 是独立生产项目，本仓库不修改它，也不依赖它运行文章解析。

等进入市场因子阶段时，可以**只读参考 ETF 项目已经验证的数据获取方式和质量控制逻辑**。ETF 当前生产项目已经整合宏观数据、国债收益率、指数估值、融资融券和市场成交等数据，并使用 `akshare` / `tudata` 等数据源。

原则：

1. 不直接修改 ETF 的生产代码；
2. ArticleAnalysis 使用独立文件和独立配置；
3. 如需复用数据获取逻辑，先在本项目实现 adapter，再决定是否抽象公共组件；
4. API Key / Token / Secret 不写入仓库。

## 下载理杏仁指数基本面

Token 仅从用户环境变量读取：

```powershell
$env:LIXINGER_TOKEN = [Environment]::GetEnvironmentVariable('LIXINGER_TOKEN', 'User')
python research/download_lixinger_index_fundamental.py
```

下载器为 A股全指 `1000002` 和中证全指 `000985` 请求 45 个原始核心字段，以及
20 个 PE/PB 长期分位校验字段。原始 JSON、请求指纹和 manifest 写入
`data/raw/lixinger/index_fundamental/`；跨窗口合并后的 Parquet 写入
`data/derived/lixinger/index_fundamental/`。两类大文件均由 `.gitignore` 排除。

首次历史下载仍优先以单个 65 字段包请求每个最长十年窗口；后续更新会先读取本地
consolidated Parquet 的最后日期，只请求**尚未存在的增量日期**，不再因为当天 `endDate`
变化而重新下载整个活跃十年窗口。65 字段请求只有在错误明确指向字段数/响应大小限制时才拆为
45 + 20 两个大包；quota、鉴权或其他参数错误会直接停止，避免额外消耗 API 调用次数。
拆包结果按日期/指数逐列保留最新非空值，防止 `drop_duplicates` 丢失另一数据包独有字段。

其余星级核心因子可通过以下命令下载：

```powershell
$env:LIXINGER_TOKEN = [Environment]::GetEnvironmentVariable('LIXINGER_TOKEN', 'User')
python research/download_lixinger_star_factors.py
```

该命令下载中国国债全期限、GDP 全字段、投资者账户、全市场融资融券，及两指数的
核心盈利/现金流/ROE 财报字段。每份请求都保留无 Token 的原始 JSON 和 manifest，
合并后的 Parquet 位于 `data/derived/lixinger/{national_debt,gdp,investor,margin,index_financials}/`。

## 下一步

1. 优先补齐 canonical corpus 中缺失的 **2012–2020** 历史文章，再用同一 realtime pipeline 恢复跨完整牛熊周期 Target；
2. 对 2025–2026 review queue 剩余交易日继续寻找正文、HTML 元数据或其他可核验证据，5 星附近的饱和图形不强行读数；
3. 2025-08-26 已完成审计并降级为 threshold-only；后续只继续审计其他大 residual 日期，不因模型残差反向修改已有明确收盘证据；
4. 当前已确认 rolling anchor 明显优于 static price-only；下一步在更长历史 Target 上检验 anchor 漂移/结构性 reset 是否跨周期稳定，并解释其经济来源；
5. 已冻结 P2 候选参数，从 2026-09-01 起等待真正未见数据做前瞻验证；在此期间不得因未来误差重新调 slope、anchor window、hysteresis threshold 或价格 proxy。
