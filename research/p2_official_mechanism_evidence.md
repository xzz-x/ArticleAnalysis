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


## 8. Direct earnings-level tests

Two separate tests were added to distinguish the author's long-run economic explanation from the daily production rule.

### 8.1 Daily price + aggregate earnings-level model

Aggregate earnings level was approximated as:

```text
earnings_level = A股全指 close / 中证全指 000985 pe_ttm.mcw
```

The model tested:

```text
star =
a
+ b * [-log(price)]
+ c * log(earnings_level)
```

with economically oriented nonnegative coefficients.

Expanding development results:

| Fold | Price-only rounded MAE | Price + earnings rounded MAE |
| --- | ---: | ---: |
| 2022 -> 2023 | 0.00991 | **0.00755** |
| 2023 -> 2024 | 0.03915 | **0.03585** |
| Mean | 0.02453 | **0.02170** |

The earnings-level term is active in both individual folds, but its raw coefficient shrinks strongly:

```text
2022 -> 2023: ~0.41
2023 -> 2024: ~0.14
full 2022-2024 fit: 0.00
```

The contemporaneous price coefficient remains around 4.

Therefore the data do not support the pure-valuation restriction in which price and earnings level enter with approximately equal and opposite log coefficients.

### 8.2 Monthly earnings-timescale decomposition

A stronger structural test avoided fitting a new earnings coefficient.

For a fixed price sensitivity `k`:

```text
anchor_t = star_t + k * log(price_t)
```

If the slow anchor were driven primarily by aggregate earnings level in the same one-for-one way implied by a simple PE identity, then:

```text
anchor_t - k * log(earnings_level_t)
```

should be more stable than the raw anchor.

It is not.

Using the frozen price slope `k = 4.1277`:

```text
2022-06..2024:
raw monthly anchor SD          = 0.0428
earnings-adjusted anchor SD    = 0.2375

2025..2026-08:
raw monthly anchor SD          = 0.0473
earnings-adjusted anchor SD    = 0.1547
```

Using the pre-holdout within-month price slope `k = 3.6485`:

```text
2022-06..2024:
raw monthly anchor SD          = 0.0159
earnings-adjusted anchor SD    = 0.2407

2025..2026-08:
raw monthly anchor SD          = 0.0998
earnings-adjusted anchor SD    = 0.1943
```

The adjustment therefore increases, rather than reduces, anchor variation.

### Interpretation

This does **not** contradict the author's statement that long-run earnings growth raises the index level compatible with the same valuation/star state.

It means only that:

> the short/medium-horizon star anchor observed from 2022-2026 cannot be represented as a one-for-one function of the currently reconstructed `price / PE` earnings level.

The official 2013 / 2018 / 2024 examples concern multi-year structural growth. The available 2022-2026 fine-star sample is too short to identify that long-run relation cleanly.

Current working hierarchy:

1. daily star movement: overwhelmingly price-driven;
2. medium-horizon 2025-2026 drift: not explained by the reconstructed earnings level;
3. multi-year same-star point-level increase: official evidence attributes this mainly to earnings growth;
4. testing item 3 requires a longer, version-aware historical series rather than more tuning on 2022-2026.
