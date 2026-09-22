# ArticleAnalysis

文章语料分析与投资研究实验仓库。

当前重点项目：**银行螺丝钉公众号历史文章分析与“投资星级”复刻**。

## 分支约定

- `main`：只保留稳定、可复用的项目基线。
- 当前实验分支：`research/screw-star-replica`。
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

### 统一 2022–2026 Target

```bash
python research/build_unified_star_target.py
```

输出 `data/derived/star_target_2022_2026_unified.csv`，保证每个日期最多一条记录，
并保留 `star_low` / `star_high`、证据置信度与训练权重。2025–2026 优先采用带正文证据的
新流水线结果；区间不会被旧年度表中的单点覆盖，休市文章进入 exclusions，只有阈值描述
而没有数值区间的记录权重为零。来源冲突和合并规则记录在同目录的 audit/conflicts 文件中。

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

当前结论是：核心三因子不能替代原星级规则。下一阶段应保留指数点位基线，把基本面
和市场因子用于解释其残差。验证流程已检查因子方向、留出期隔离和 point-in-time 日期，
项目自动化测试共 30 项通过。

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

下载器会优先以单个 65 字段包请求每个十年窗口，命中缓存时不会重复调用接口；
只有接口明确拒绝完整字段包时才拆为 45 + 20 两个大包。

其余星级核心因子可通过以下命令下载：

```powershell
$env:LIXINGER_TOKEN = [Environment]::GetEnvironmentVariable('LIXINGER_TOKEN', 'User')
python research/download_lixinger_star_factors.py
```

该命令下载中国国债全期限、GDP 全字段、投资者账户、全市场融资融券，及两指数的
核心盈利/现金流/ROE 财报字段。每份请求都保留无 Token 的原始 JSON 和 manifest，
合并后的 Parquet 位于 `data/derived/lixinger/{national_debt,gdp,investor,margin,index_financials}/`。

## 下一步

1. 对 review queue 中剩余 7 个交易日继续寻找正文、HTML 元数据或其他可核验来源；5 星附近的饱和图形不强行读数；
2. 将相同 pipeline 扩展到 2012–2024 历史语料；
3. 建立 FTS 搜索库并抽样审计低置信度候选；
4. 建立“指数点位基线 + 基本面残差修正”模型，检验基本面因子的增量解释力。
