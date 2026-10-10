# Official mechanism evidence for the Bank Screw star rating

> Purpose: external mechanism evidence only.  
> This file must not be used as a source of exact daily training labels unless a dated closing-star statement is independently verified.

## 1. Official factor disclosure

Bank Screw public course material states that the star rating considers market-wide valuation, earnings growth, trading activity and market sentiment.

More detailed 2026 course material lists the main quantitative signals as:

1. Buffett indicator: total listed-company market value / GDP;
2. equity-bond relative value: CSI All Share earnings yield versus the 10-year government-bond yield;
3. PB historical percentile.

The qualitative / sentiment side includes items such as:

- margin financing balance;
- trading amount and its percentile;
- IPO count and IPO break rate;
- existing-fund scale;
- new-fund scale;
- new-account openings;
- share of funds under purchase restrictions;
- market news / sentiment.

Public source examples:

- https://finance.sina.com.cn/wm/2026-04-14/doc-inhunttw4018046.shtml
- https://finance.sina.com.cn/money/fund/jjgsgd/2026-07-17/doc-iniiefhn4037476.shtml
- https://finance.sina.com.cn/money/fund/jjgsgd/2026-07-27/doc-inikfnpm0718829.shtml
- https://finance.sina.com.cn/wm/2026-05-07/doc-inhxahra7674165.shtml

## 2. Official same-star / different-index-level examples

Bank Screw repeatedly gives the following approximate CSI All Share examples for roughly the same 5-star state:

```text
2012-2014: ~2700-2800
2018:      ~3400
2024:      ~4800
```

The author explicitly explains that the higher index level at the same valuation/star state comes from listed-company earnings growth.

Public source examples:

- https://finance.sina.com.cn/wm/2026-05-05/doc-inhwwmhz9597183.shtml
- https://jingxuan.douyin.com/m/video/7679318182158486810
- https://jingxuan.douyin.com/m/video/7674874256487943450
- https://finance.sina.com.cn/money/fund/jjgsgd/2026-07-27/doc-inikfnpm0718829.shtml

## 3. Implication for reverse engineering

This evidence rules out a universal 2012-2026 formula of the form:

```text
star = constant_intercept + beta * log(index_price)
```

with one fixed intercept.

Using the currently frozen price slope `-4.127707783337646`, the approximate 5-star examples imply materially different intercepts:

```text
2013 at index 2700 -> implied intercept ~37.61
2018 at index 3400 -> implied intercept ~38.56
2024 at index 4800 -> implied intercept ~39.99
```

The implied shift from the 2013 example to the 2024 example is about **2.37 star-equivalent intercept units**.

These examples are approximate and must never be inserted into the daily Target as exact labels. Their value is structural:

> a static price formula may be a strong local approximation, but some long-run anchor must move.

## 4. Stronger long-run hypothesis

The official explanation suggests the long-run mechanism is closer to:

```text
market price
÷
market earnings level
        ↓
market valuation
        +
relative valuation / sentiment adjustments
        ↓
star rating
```

or in log form:

```text
star_t
≈
a
+ b * log(price_t)
+ c * log(earnings_level_t)
+ other valuation/sentiment adjustments
```

Because the frozen price coefficient is negative, a rising earnings level can mechanically raise the price level compatible with the same star rating.

This is conceptually different from the previously tested short-run `rolling star-implied anchor`:

- rolling star anchor is a replication device;
- aggregate earnings level would be an exogenous economic explanation for why the anchor moves.

## 5. Current data gap

The current P1 feature set contains useful proxies for several disclosed factors:

```text
buffett_mc_to_gdp
buffett_mc_om_to_gdp
equity_bond_ratio_avg
pb_avg_pct_10y_local
fin_q_ps_np_ttm_y2y
ta_pct_252
to_r_pct_252
market_financing_balance_change_20
market_financing_balance_change_60
investor_nni_w
investor_nni_m
```

However, the current candidate list explicitly exposes an **earnings-growth proxy** rather than a clean aggregate **market earnings level** series.

That matters because the official long-run explanation is about the *level* of earnings moving the index level compatible with a given valuation, not merely today's year-on-year growth rate.

Therefore the next data-acquisition priority is:

> obtain a consistent CSI All Share / total-A-share aggregate earnings-level series, preferably directly or reconstructable from index market value and PE / earnings yield.

This should be done before interpreting the rolling 10-star anchor as the true economic mechanism.

## 6. Historical-version caveat

There is also evidence that historical star definitions may not have been perfectly stable across product eras.

A third-party historical review cites a 2020-06-23 Bank Screw portfolio record describing A shares as 3.5 stars while a later app history representation is reported as 4 stars.

Source:

- https://xueqiu.com/4778574435/282350872

This is not strong enough to overwrite historical Targets. It is a warning that:

- today's app history may include retrospective normalization;
- historical portfolio-era terminology may differ from the current star series;
- future 2012-2021 backfill must preserve source/version metadata instead of assuming one immutable historical label definition.

## 7. Research consequence

Current hierarchy of evidence:

1. **Strong:** price is the dominant short-run driver.
2. **Strong:** one fixed price intercept cannot explain the full 2012-2026 history.
3. **Officially supported:** earnings growth/level and multiple valuation/sentiment signals matter to the star framework.
4. **Unresolved:** exact weights and update frequency.
5. **Unresolved:** whether the current app historical series is fully contemporaneous or partly normalized retrospectively.

The next mechanism work should therefore focus on explaining the long-run anchor with exogenous earnings / valuation data, while the frozen prospective models continue unchanged.
