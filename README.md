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

## 与 xzz-x/ETF 的关系

`xzz-x/ETF` 是独立生产项目，本仓库不修改它，也不依赖它运行文章解析。

等进入市场因子阶段时，可以**只读参考 ETF 项目已经验证的数据获取方式和质量控制逻辑**。ETF 当前生产项目已经整合宏观数据、国债收益率、指数估值、融资融券和市场成交等数据，并使用 `akshare` / `tudata` 等数据源。

原则：

1. 不直接修改 ETF 的生产代码；
2. ArticleAnalysis 使用独立文件和独立配置；
3. 如需复用数据获取逻辑，先在本项目实现 adapter，再决定是否抽象公共组件；
4. API Key / Token / Secret 不写入仓库。

## 下一步

1. 对 Google Drive 文章目录跑一次完整 ingest；
2. 检查目录命名、正文格式和日期识别率；
3. 建立 FTS 搜索库；
4. 扫描“星级 / 五星级 / 今天几星 / 指数估值数据”等语句；
5. 建立第一版可审计的历史星级 Target；
6. Target 足够后，再引入 ETF 项目中的市场因子数据进行逆向拟合。
