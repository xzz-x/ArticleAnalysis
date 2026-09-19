# 理杏仁数据清单：银行螺丝钉“A股投资星级”复刻

> 浏览日期：2026-09-19  
> 状态：数据源盘点，不代表最终模型。  
> 目标：记录理杏仁中可能用于逆向复刻银行螺丝钉“A股投资星级”的可抓取数据、字段、频率、优先级与注意事项，后续统一通过 API 抓取并进入 `data/derived/` / `data/features/`。

## 1. 核心判断

理杏仁非常适合作为本项目的主要估值数据源之一。它不仅有指数日频 PE/PB/市值，还提供：

- 多种指数估值聚合方法；
- 1/3/5/10/20 年及上市以来估值统计；
- 10 年期中国国债收益率；
- GDP 与 TTM GDP；
- 指数/全市场融资融券；
- 成交额与换手率；
- 新增投资者；
- 公募基金基础信息、成立日期、份额和资产规模；
- 指数层面的财务报表与盈利指标。

这与螺丝钉公开描述的“估值 + 盈利 + 股债性价比 + 市场情绪/资金面”的框架高度对应。

---

## 2. P0：必须优先抓取的核心数据

### 2.1 A 股全市场估值：A股全指 + 中证全指

**候选指数**

1. 理杏仁 A股全指：`1000002.lxr`
2. 中证全指：`000985`

理杏仁对 A股全指的说明是“反映整个A股市场估值全貌”；2005 年以后点位直接使用中证全指。因此两个口径都应保留，不能事先假定螺丝钉采用哪一个。

**API**

`POST https://open.lixinger.com/api/cn/index/fundamental`

文档：

https://www.lixinger.com/api/open-api/html-doc/cn/index/fundamental

**重点字段**

- `pe_ttm`：PE-TTM
- `pb`：PB
- `ps_ttm`：PS-TTM
- `dyr`：股息率
- `mc`：总市值
- `mc_om`：A股市值
- `cmc`：流通市值
- `ecmc`：自由流通市值
- `cp`：收盘点位
- `ta`：成交金额
- `to_r`：换手率

**估值聚合方式全部保留用于逆向检验**

- `mcw`：总市值加权
- `ew`：等权
- `ewpvo`：正数等权
- `avg`：平均值
- `median`：中位数

**历史统计维度**

- 上市以来 `fs`
- 20 年 `y20`
- 10 年 `y10`
- 5 年 `y5`
- 3 年 `y3`
- 1 年 `y1`

后续重点抓取/构造：

- 当前估值；
- PE/PB 历史分位；
- 20% / 50% / 80% 分位对应值；
- 当前值相对历史均值/中位数偏离；
- PE/PB 的对数变化。

**理杏仁估值算法本身也值得保留**

理杏仁的指数估值计算说明明确写出：总市值加权 PE-TTM 的核心公式为

```text
PE_TTM_mcw = Σ总市值 / Σ净利润
```

理杏仁自己的口径选择是：

- 按总市值计算，而不是只按 A 股市值；
- 市值加权时不剔除亏损公司；
- 财报更新采用“及时策略”，公司新财报披露后即更新指数估值；
- 等权 PE 的基本形式是调和式 `N / Σ(1 / PE_i)`；
- 对全市场这类综合指数，负 PE 会导致普通等权值出现极端失真，因此另提供“正数等权”；
- 算术平均值会剔除负 PE 和极端值。

计算说明：
https://www.lixinger.com/wiki/stock-collection-value-calculation

这对本项目很重要：后续不能只把五种聚合方式当成同义变量。尤其应重点比较 **总市值加权 / 正数等权 / 中位数**，并检查螺丝钉的“大盘估值”是否更接近“把整个市场视作一家公司”的总市值加权口径。

**为什么优先级最高**

星级明确是“市场整体估值”。另外历史文章称“一颗星约对应大盘 20% 的估值波动”，因此需要重点测试：

```text
Star ~ a - b * log(Valuation)
```

并检验当综合估值乘以约 1.2 时，星级是否下降约 1 星。

---

### 2.2 股债性价比：A股盈利收益率 / 中国10年期国债收益率

**国债 API**

`POST https://open.lixinger.com/api/macro/national-debt`

文档：

https://www.lixinger.com/api/open-api/html-doc/macro/national-debt

重点字段：

- `tcm_y10`：中国10年期国债收益率

理杏仁本身还有“格雷厄姆指数”页面，可选择 A股全指、估值聚合方式和不同期限国债：

https://www.lixinger.com/equity/macro/graham-index/cn

**后续派生**

```text
earnings_yield = 1 / PE_TTM
equity_bond_ratio = earnings_yield / CN10Y
equity_bond_spread = earnings_yield - CN10Y
```

其中 `equity_bond_ratio` 与螺丝钉文章里对“股债性价比”的描述最接近，应作为 P0 因子。

必须同时对不同 PE 聚合方式计算，尤其：

- 总市值加权 PE；
- 中位数 PE；
- 正数等权 PE。

---

### 2.3 巴菲特指标：A股总市值 / GDP

**GDP API**

`POST https://open.lixinger.com/api/macro/gdp`

文档：

https://www.lixinger.com/api/open-api/html-doc/macro/gdp

重点字段：

- `q.gdp.ttm`：季度 GDP TTM
- `q.gdp.ttm_y2y`：GDP TTM 同比

市场市值来自指数基本面接口：

- `mc`
- `mc_om`

必须并行测试两个口径：

```text
buffett_mc = mc / GDP_TTM
buffett_a_share = mc_om / GDP_TTM
```

暂不预设哪个才是螺丝钉实际使用口径，以与历史星级拟合结果决定。

---

### 2.4 A股整体盈利与盈利增长

星级公开说明中包含“盈利”等因素，因此仅靠 PE/PB 不够。

**指数混合财报 API**

`POST https://open.lixinger.com/api/cn/index/fs/hybrid`

文档：

https://www.lixinger.com/api/open-api/html-doc/cn/index/fs/hybrid

候选核心字段：

- `ps.oi`：营业收入
- `ps.np`：净利润
- `ps.npatoshopc`：归母普通股股东净利润
- `ps.npadnrpatoshaopc`：扣非归母净利润
- `m.roe`：ROE
- `m.roe_atoshaopc`：归母普通股 ROE
- `m.fcf`：自由现金流
- `ps.fa_om`：A股融资金额

优先派生：

- 净利润 TTM；
- 净利润 TTM 同比；
- 归母净利润 TTM 同比；
- 营收 TTM 同比；
- ROE。

**关键注意事项**

财报数据必须按 `reportDate`（实际可获得日期）进入日频特征，不能按财报期末日提前填入，否则会产生严重 look-ahead bias。

---

## 3. P1：高价值的星级“修正因子”

### 3.1 成交额 / 换手率 / 市场活跃度

直接来自指数基本面：

- `ta`：成交金额
- `to_r`：换手率

后续自行构造：

- 20 / 60 / 120 / 240 日成交额均值；
- 当前成交额 / 过去一年中位数；
- 过去 1/3/5 年成交额历史分位；
- 换手率历史分位。

螺丝钉曾明确提到“成交量及百分位”，因此这一组属于高优先级修正项。

**原则：分位数优先自己用当时以前的数据重算。**

---

### 3.2 全市场融资融券

优先使用“整个A股市场”接口，而不是仅某个指数样本口径。

**API**

`POST https://open.lixinger.com/api/cn/company/market-data/margin-trading-and-securities-lending`

文档：

https://www.lixinger.com/api/open-api/html-doc/cn/company/market-data/margin-trading-and-securities-lending

重点字段：

- financingPurchaseAmount
- financingRepaymentAmount
- financingBalance
- financingSecuritiesBalance
- marginableSecuritiesMarketCap
- avgMaintenanceMarginRatio

指数融资融券接口也可作为交叉验证：

https://www.lixinger.com/api/open-api/html-doc/cn/index/margin-trading-and-securities-lending

后者额外可直接给：

- financingNetPurchaseAmount
- financingBalanceToMarketCap

派生候选：

- 融资余额 / A股流通市值；
- 融资余额 20/60/120 日变化；
- 融资净买入 5/20 日累计；
- 融资余额历史分位。

螺丝钉曾明确将“融资余额”列为定性/情绪指标，应列 P1。

---

### 3.3 新增投资者 / 开户热度

**API**

`POST https://open.lixinger.com/api/macro/investor`

文档：

https://www.lixinger.com/api/open-api/html-doc/macro/investor

重点字段：

- `nni_m`：新增自然人（月，2019-02-22 后）
- `nni_w`：新增自然人（周，2019-02-23 前）
- `ni`：自然人存量
- `nia`：A股自然人存量

对应螺丝钉公开提到的“新增开户数”。

注意：

- 2019 年前后统计频率发生变化；
- 月度数据进入日频模型时必须按真实公布时间 forward-fill，不按月末提前使用。

---

### 3.4 公募基金规模 / 新基金规模

**基金基础信息**

`POST https://open.lixinger.com/api/cn/fund`

文档：

https://www.lixinger.com/api/open-api/html-doc/cn/fund

可得到：

- 基金代码；
- 一级/二级分类；
- 成立日期；
- 是否退市等。

**基金概况**

`POST https://open.lixinger.com/api/cn/fund/profile`

可得到成立日期、申购开始日期、母/子基金等信息。

**基金份额及资产规模**

`POST https://open.lixinger.com/api/cn/fund/shares`

文档：

https://www.lixinger.com/api/open-api/html-doc/cn/fund/shares

重点字段：

- `s`：总份额
- `as`：总资产规模
- `et_shares`：场内份额
- `et_as`：场内资产规模

**基金公司资产规模**

`POST https://open.lixinger.com/api/cn/fund-company/asset-scale`

可获得权益类、混合类等历史规模。

后续可以派生：

```text
old_fund_scale
new_fund_scale_30d / 90d / 180d
new_equity_fund_count_30d / 90d
new_equity_fund_scale_share
```

这可以近似螺丝钉提到的“老基金规模 / 新基金规模”。

**重要数据清洗**

基金 A/C/E 等不同份额可能共用同一主基金，不能简单按基金代码求和，否则会重复计算。需按母基金关系、成立日期和资产披露口径去重。

---

### 3.5 股票型/权益 ETF 资金流

指数基本面 API 有：

- `fet_as_ma`
- `fet_snif_ma`

但这些更像“跟踪该指数的场内基金”口径。A股全指页面当前直接显示场内基金资产规模为 0，因此**不能把 A股全指的该字段当作整个A股 ETF 市场资金流**。

正确做法应是：

1. 从全部基金中识别股票型 ETF；
2. 汇总其份额与资产规模；
3. 用份额变化 × 净值/价格近似计算净申购；
4. 构造 1/5/20/60 日净流入。

因此列 P1/P2，不作为第一版核心公式。

---

## 4. P2：有潜力，但先不进入核心模型

### 4.1 新股发行数量

理杏仁公司基础信息 API 有：

- `ipoDate`
- listingStatus
- `issued_but_not_listed`
- `pre_disclosure`
- `issue_failure` 等状态。

API：

https://www.lixinger.com/api/open-api/html-doc/cn/company

可以按上市日期统计：

- 过去 30/60/90 天新上市股票数量；
- 年内 IPO 数；
- IPO 节奏变化。

这可以对应“新股发行数”。

### 4.2 新股破发率

目前没有在理杏仁开放 API 中发现一个现成的“全市场新股破发率”序列。

可行但成本较高的路径：

1. 用 `ipoDate` 识别新股；
2. 从 IPO 公告获取发行相关信息；
3. 取得发行价；
4. 用公司 K 线 API 获取首日/指定窗口收盘价；
5. 计算破发率。

公司公告 API 支持 `ipo` 类型：

https://www.lixinger.com/api/open-api/html-doc/cn/company/announcement

但若后续找不到结构化发行价字段，建议改用已有 ETF 项目或其他数据源，不强行从公告 NLP 解析。

---

### 4.3 限购基金占比

理杏仁基金页面确实存在“暂停大额申购/恢复大额申购”等公告，但当前没有发现开放 API 提供结构化的“当前申购限额”字段。

理论上可通过基金公告标题/正文识别：

- 暂停申购；
- 暂停大额申购；
- 恢复申购；
- 恢复大额申购。

但建立完整历史状态机成本很高，暂列 P2/P3，等核心公式解释力不足时再做。

---

### 4.4 陆股通

指数基本面可获取：

- `ha_shm`：陆股通持仓金额
- `mm_nba`：陆股通净买入金额

但从 2024-08-16 起，部分北向持仓数据披露从日频改为季度频率。因此对 2025/2026 日频星级复刻价值下降，只作为补充验证。

---

### 4.5 全市场股东人数 / 市场参与度

理杏仁 A股全指可汇总样本公司股东人数，当前为季度频率。

可构造：

- 全市场股东人数；
- QoQ 增速；
- 人均自由流通市值。

但频率低，且与新增投资者指标高度相关，暂列 P2。

---

### 4.6 A股融资 / 分红融资比

A股全指页面可聚合样本公司 IPO、定增、配股、可转债转股等融资，并与分红比较。

长期可能用于描述市场融资压力，但现有展示以年度为主，频率偏低，不适合作为每日星级核心因子。

---

### 4.7 横截面“低估股票占比”

螺丝钉常用“低估品种更多/更少”描述不同星级，因此可以后续构造市场宽度型估值因子：

- PE 低于自身历史 20% 分位的股票占比；
- PB 低于自身历史 20% 分位的股票占比；
- PE/PB 同时低估的股票占比；
- 高估股票占比。

这需要公司级日频估值 + 当时指数成分股，数据量很大，先列 P2，但它可能在解释 3.x/4.x/5.x regime 时有价值。

---

## 5. 暂不优先的理杏仁数据

以下数据理杏仁也有，但当前没有直接证据显示是螺丝钉星级公式组成部分：

- M1/M2；
- 社融；
- CPI/PPI；
- PMI；
- 汇率；
- 美债收益率；
- VIX；
- 大股东增减持；
- 龙虎榜；
- 股权质押。

这些可以作为后续稳健性/外部状态变量，但第一阶段不应塞入模型，避免把逆向复刻变成黑箱预测。

---

## 6. Point-in-time 与防未来函数规则

这是后续抓取时必须执行的约束。

### 6.1 财报

使用 `reportDate` 作为信息可用日期，而不是 `standardDate`/财报期末日。

### 6.2 GDP / 月度开户 / 基金规模

低频数据只能从真实公布后开始使用；在两次发布之间 forward-fill。

### 6.3 历史分位

理杏仁提供历史分位值，但在正式模型前必须验证其历史日期上的分位统计是否只使用当时以前的数据。

若无法确认，一律：

- 抓原始 PE/PB；
- 自己用 expanding / trailing window 计算分位；
- 不让 2025/2026 数据参与 2022/2023 的历史分位。

### 6.4 指数成分

若做横截面宽度，必须使用当时成分股或 point-in-time 股票池，不能拿 2026 成分回填历史。

---

## 7. 推荐第一批实际抓取清单

后续开始抓数据时，第一批只抓以下内容，不一次性拉所有指标。

### Batch A：核心日频

时间建议先覆盖 **2012-01-01 至当前**，便于构造 10 年以上历史估值位置。

指数：

- A股全指 `1000002`
- 中证全指 `000985`

字段：

- PE-TTM（所有聚合方式）
- PB（所有聚合方式）
- 股息率
- 总市值 / A股市值 / 流通市值
- 成交额
- 换手率
- 收盘点位

宏观：

- 中国10年国债收益率

### Batch B：核心低频

- GDP TTM
- 指数净利润 TTM / TTM同比
- 归母净利润 TTM / TTM同比
- ROE

### Batch C：情绪修正

- 全市场融资余额
- 融资净买入
- 融资余额/市场市值
- 新增自然人投资者
- 股票型基金总资产规模
- 新成立权益基金数量/规模

---

## 8. 建议的仓库落盘结构

不改 `data/verified/`。

```text
data/derived/lixinger/
    index_fundamental/
    national_debt/
    gdp/
    index_financials/
    margin/
    investor/
    fund/

data/features/
    star_core_factors.csv
    star_sentiment_factors.csv
    star_factor_panel.csv
```

API Token 只能通过环境变量读取：

```text
LIXINGER_TOKEN
```

严禁写入 GitHub。

---

## 9. 逆向拟合时的先验顺序

后续不要一开始把几十个变量一起训练。

优先顺序：

```text
Model 0:
Star ~ market valuation

Model 1:
Star ~ Buffett + Equity/Bond + PB percentile

Model 2:
Model 1 + earnings growth

Model 3:
Model 2 + turnover + margin financing

Model 4:
Model 3 + investor accounts + fund variables

P2 factors:
only when the above models leave stable, interpretable residual patterns
```

每增加一组变量，都比较：

- exact 样本 MAE；
- range 样本 interval loss；
- regime（3.x/4.x/5.x）准确率；
- 2025/2026 样本外稳定性；
- 参数方向是否符合经济逻辑；
- “约 20% 估值变化 = 1 星”的约束是否成立。

最终目标仍是复刻规则，而不是追求样本内预测精度。


---

## 10. API 调用次数最小化策略（2026-09-19核对官方文档后更新）

### 10.1 总原则

本项目的 API 设计优先级调整为：

```text
最少调用次数 > 响应体大小 > 本地存储大小
```

即：

1. 时间范围接口一律尽量取满官方允许的 10 年；
2. 有 `metricsList` 的接口，一次请求尽量把所有相关指标都塞满；
3. 不按指标拆请求；
4. 只有接口明确限制指标数时才拆；
5. 本地保留原始响应，后续衍生指标全部离线计算；
6. 对文档没有注明 `metricsList` 上限的接口，先尝试“最大字段集单次请求”；只有真实 API 返回字段数/响应体限制错误时才自动拆包重试；
7. 不使用 `limit`，避免截断历史数据；
8. 每次成功请求保存 request manifest（endpoint、时间窗、代码、metrics、hash），避免重复消耗额度。

### 10.2 推荐统一历史窗口

当前星级研究正式目标期覆盖 2012–2026，因此所有“最大10年”接口统一切成两个窗口：

```text
W1 = 2012-01-01 ~ 2021-12-31
W2 = 2022-01-01 ~ 当前日期
```

这样每个“单代码 + 10年上限”的接口只需要 2 次调用。

如果后续决定把估值背景扩展到 2005 年，则新增一个更早窗口即可，不改现有缓存。

### 10.3 指数基本面：每个指数每10年只调用1次

Endpoint:

```text
POST /api/cn/index/fundamental
```

官方限制：

- `stockCodes` 在指定 `date` 时最多可 100 个；
- **只要使用 `startDate` 做历史区间查询，就只能传 1 个指数代码**；
- 单次时间跨度最多 10 年；
- 官方文档没有注明该接口 `metricsList` 的数量上限。

因此历史抓取的最优形态：

```text
指数 1000002 × W1 = 1 call
指数 1000002 × W2 = 1 call
指数 000985  × W1 = 1 call
指数 000985  × W2 = 1 call

合计 = 4 calls
```

每次请求不再只抓 PE/PB，而是把所有可能相关的字段一起请求。

#### A. 原始市场字段全部一起取

```text
tv
ta
to_r
cp
cpc
cpa
r_cp
r_cpc
mc
mc_om
cmc
ecmc
fpa
fra
fnpa
fb
ssa
sra
snsa
sb
ha_shm
mm_nba
fet_as_ma
fet_snif_ma
launchDate
```

#### B. 四类估值的 5 种聚合方式全部一起取

```text
pe_ttm.{mcw,ew,ewpvo,avg,median}
pb.{mcw,ew,ewpvo,avg,median}
ps_ttm.{mcw,ew,ewpvo,avg,median}
dyr.{mcw,ew,ewpvo,avg,median}
```

#### C. 不做 1080 字段的历史统计笛卡尔积

前一版把

```text
4种估值 × 6个历史周期 × 5种聚合方式 × 9种统计量
```

完全展开，理论上会得到 1080 个历史统计字段。这个数字只是接口语法的组合上限，**不是推荐抓取规模**，而且大量字段互相冗余。

更合理的原则是：

1. **原始日频值一次取全**；
2. 1/3/5/10 年的分位、均值、20/50/80% 分位值等全部在本地由原始日频序列计算；
3. 仅保留少量理杏仁官方历史统计字段作为口径校验，尤其是本地历史长度不足时有价值的 `y20` / `fs` 分位；
4. 不为了“字段多”增加响应体大小和接口失败风险。

推荐指数基本面单次请求约为：

```text
20 个当前估值字段
= 4种估值 × 5种聚合方式

约25个其他原始市场字段
= 成交/换手/点位/市值/两融/陆股通/场内基金等

约20个官方长期分位校验字段（可选）
= PE、PB × y20、fs × 5种聚合方式 × cvpos

合计约 45 个核心原始字段
或约 65 个（加长期分位校验）
```

因此实际目标应是 **约45–65个字段/指数/请求**，而不是 1100 个。

如果后续发现螺丝钉实际使用某个特定理杏仁官方统计口径，再追加对应字段；不要预先抓取 `minv/maxv/maxpv/q2v/q5v/q8v/avgv` 的全部组合。

### 10.4 指数财报：单指数历史请求一次最多128个指标

Endpoint:

```text
POST /api/cn/index/fs/hybrid
```

A股全指/中证全指均属于混合市场口径研究对象，优先用 hybrid 财报接口。

官方限制：

- `startDate` 历史查询时只能传 1 个指数代码；
- 时间跨度最多 10 年；
- 单指数时 `metricsList` 最多 **128 个指标**；
- 多指数时最多 48 个指标。

因此不要尝试把 2 个指数放到同一个历史请求里，因为历史模式本来就禁止多代码，而且单指数还能拿到 128 字段上限。

对星级研究，先设计一个 **<=128 字段的最大财报包**，同时覆盖：

- 营业收入/营业总收入；
- 净利润；
- 归母净利润；
- 扣非归母净利润；
- TTM；
- TTM同比；
- 单季；
- 单季同比；
- ROE / ROA；
- 总资产；
- 总负债；
- 净资产/股东权益；
- 经营现金流；
- 自由现金流；
- 融资相关字段；
- 其他可能反映全市场盈利和财务质量的指标。

调用数：

```text
2 indices × 2 windows × 1 packed financial bundle = 4 calls
```

如果后续确实需要超过 128 个不同财务指标，再新增第二个 <=128 字段 bundle；第一阶段不要预先拆分。

### 10.5 国债：一个请求同时取大陆全部期限

Endpoint:

```text
POST /api/macro/national-debt
```

每个 10 年窗口只需要 1 call，并在同一次 `metricsList` 中取：

```text
tcm_m3
tcm_m6
tcm_y1
tcm_y2
tcm_y3
tcm_y5
tcm_y7
tcm_y10
tcm_y20
tcm_y30
```

因此 2012–当前：

```text
W1 = 1 call
W2 = 1 call
总计 = 2 calls
```

虽然星级核心只明确需要 10Y，但其他期限零额外调用，全部保存。

### 10.6 GDP：一个请求塞入大陆所有 GDP 指标

Endpoint:

```text
POST /api/macro/gdp
```

官方也是 10 年上限，且文档未注明 `metricsList` 数量上限。

因此每个窗口把大陆全部支持的 GDP 类型及其统计表达式一次获取，包括：

- GDP；
- 不变价 GDP；
- 人均 GDP；
- GNI；
- 第一/第二/第三产业 GDP；
- 三大产业对 GDP 贡献率；
- 年度累计/同比；
- 季度累计/同比；
- 单季/同比/环比/年比；
- TTM / TTM同比 / TTM环比。

2012–当前 = **2 calls**。

星级模型主要用 `q.gdp.ttm`，但既然其他 GDP 字段可以同一次拿到，就全部保留。

### 10.7 投资者：所有账户类型一次取完

Endpoint:

```text
POST /api/macro/investor
```

每个 10 年窗口同时取：

```text
ni
nia
nib
non_ni
non_nia
non_nib
nni_m
n_non_ni_m
nni_w
n_non_ni_w
```

2012–当前 = **2 calls**。

月度/周度字段会因统计制度变更在不同年份自然为空，不需要为此拆请求。

### 10.8 全市场融资融券：接口本身自动返回全部字段

Endpoint:

```text
POST /api/cn/company/market-data/margin-trading-and-securities-lending
```

该接口没有 `metricsList`，一次自动返回所有字段：

- 融资买入；
- 融资偿还；
- 融资余额；
- 融券卖出/偿还/余量/余额；
- 融资融券余额；
- 可充抵保证金证券市值；
- 担保资金；
- 担保物总价值；
- 平均维持担保比例。

当前官方页面没有像多数接口那样写明“开始和结束时间间隔不超过10年”。

因此实现顺序：

```text
第一尝试：2012-01-01 ~ current，一次调用
若服务器实际限制时间范围，再退回 W1/W2 两次调用
```

不要预先拆。

### 10.9 基金数据：暂时不要做全基金暴力扫描

基金份额接口一次只能传 1 个基金代码；而基金基础信息当前约有 3 万只基金，并且列表接口分页。

如果现在为了“新基金规模/老基金规模”直接全市场逐基金抓 10 年份额，会快速消耗大量调用额度，不符合本项目当前的 API 预算目标。

第一阶段：

1. 先充分使用指数基本面同一请求中免费附带的 `fet_as_ma` / `fet_snif_ma`；
2. 保留基金基础信息接口用于后续设计精准股票型/权益基金 universe；
3. 等核心模型残差显示基金因子确实有增量价值，再集中抓基金层数据；
4. 若抓基金，先建立唯一主基金 universe，避免 A/C/E 份额重复请求。

### 10.10 第一阶段最低调用预算

按 2012-01-01 至当前、2 个核心指数估算：

| 数据块 | 预计调用数 |
|---|---:|
| 指数基本面（2指数×2窗口） | 4 |
| 指数财报（2指数×2窗口，<=128字段/包） | 4 |
| 中国国债全部期限 | 2 |
| GDP 全字段 | 2 |
| 投资者全字段 | 2 |
| 全市场融资融券 | 1（若服务端隐含10年限制则2） |
| **合计** | **15 calls（最理想）** |

这 15 次调用已经能覆盖星级逆向研究最重要的：

- 全市场估值；
- 全部估值口径；
- 历史估值位置；
- 市值；
- 成交/换手；
- 指数融资融券；
- 北向资金；
- 指数相关场内基金数据；
- 盈利/盈利增长；
- 财务质量；
- 全期限国债；
- Buffett 指标所需 GDP；
- 投资者开户；
- 全市场融资融券状态。

### 10.11 代码层面必须实现的额度保护

后续抓取脚本必须具备：

```text
1. raw response cache
2. request fingerprint
3. skip-if-cached
4. atomic write
5. retry only on transport/server failure
6. no retry on parameter/quota error
7. FULL metrics first, split only after explicit field-limit failure
8. manifest records requested fields and date window
9. incremental update only fetches new dates
10. never refetch a completed historical window unless --force
```

这样后续日常更新只需要抓“上次最后日期之后”的增量，不会重复浪费历史额度。
