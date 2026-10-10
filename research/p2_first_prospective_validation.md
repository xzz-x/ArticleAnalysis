# P2 first genuine prospective validation

> Validation window: 2026-09-01 through 2026-10-09  
> Frozen-candidate cutoff: 2026-08-31  
> Number of observed A-share trading-day exact targets: 23  
> Candidate parameters were not retuned after future Target recovery.

## Data

Prospective public-star evidence:

```text
data/verified/star_target_prospective_2026_09_onward.csv
```

Verified price snapshot:

```text
data/verified/csi_all_share_prospective_2026_08_31_2026_10_09.csv
```

The price snapshot uses CSI All Share `000985.SH`, which is the post-2005 point series used by the frozen A股全指 proxy. The snapshot was first retrieved from the public Eastmoney K-line endpoint and was admitted only after the overlap date matched the pre-existing frozen series:

```text
2026-08-31 close = 5969.33
```

The public downloader remains available for future incremental updates:

```text
research/fetch_csi_all_share_prospective_prices.py
```

CI does not depend on a live market-data request for this historical prospective window; the validated 24-row price snapshot is committed under `data/verified/`.

## Frozen candidate result

Frozen candidate:

```text
p2-candidate-2026-10-10

price coefficient = -4.127707783337646
rolling anchor     = mean of prior 10 published exact implied anchors
star-up threshold = +0.07
star-down threshold = -0.06
publication step   = 0.1 star
```

True prospective result:

| Metric | Result |
| --- | ---: |
| Observed exact dates | 23 |
| MAE | **0.02174 star** |
| RMSE | 0.04663 |
| Maximum absolute error | 0.1 |
| Exact star match | **18 / 23 = 78.26%** |
| Error <= 0.1 star | **23 / 23 = 100%** |
| Persistence baseline MAE | 0.03913 |
| Persistence exact match | 60.87% |

Thus the frozen candidate materially beats simply carrying forward the previous published star.

## Change-event behavior

The 23-day window contains 9 actual star-change days.

The frozen model calls only 4 star changes.

```text
actual change days       = 9
predicted change days    = 4
correct called changes   = 4
change-direction recall  = 44.44%
called-change precision  = 100%
```

This is an important diagnostic:

> The frozen hysteresis rule is conservative. It does not create false star changes in this window, but it misses 5 real changes.

The five 0.1-star misses are:

| Date | Prediction | Actual |
| --- | ---: | ---: |
| 2026-09-04 | 4.1 | 4.2 |
| 2026-09-10 | 4.1 | 4.2 |
| 2026-09-15 | 4.2 | 4.3 |
| 2026-09-18 | 4.2 | 4.1 |
| 2026-10-08 | 4.3 | 4.4 |

There are no errors larger than 0.1 star.

The thresholds must **not** be reduced after seeing these misses. Doing so would contaminate the prospective validation.

## Comparison with model classes defined before this future window

The prospective evaluator also scores simpler mechanisms that already existed in the research code before the Sep-Oct Target recovery.

| Model | Prospective MAE | Exact match | Max error |
| --- | ---: | ---: | ---: |
| **Static price + nearest 0.1 rounding** | **0.01304** | **86.96%** | 0.1 |
| Frozen adaptive anchor + hysteresis | 0.02174 | 78.26% | 0.1 |
| Static continuous price score | 0.02206 | n/a for discrete exact match | 0.0625 |
| Online-anchor continuous score | 0.02343 | n/a for discrete exact match | 0.0654 |
| Previous-star persistence | 0.03913 | 60.87% | 0.1 |

Static price baseline:

```text
latent_star =
39.95198926812065
- 4.127707783337646 * log(A股全指)
```

The simple discrete challenger is:

```text
published_star =
round(latent_star to nearest 0.1)
```

This model class was already present in the P2 discrete-mechanics candidate set before future-star recovery, so the comparison itself is legitimate. However, it was **not** the pre-holdout-selected winner.

## What this changes

The prospective evidence supports two conclusions at the same time.

### 1. Price remains the dominant driver

All strong models are still centered on the same A股全指 log-price slope. No new PB/GDP/ROE factor is needed to explain the Sep-Oct future window.

### 2. The need for dynamic anchor + hysteresis is no longer established

Historical/post-hoc analysis made adaptive anchor + hysteresis look substantially better than static price-only.

But in the first genuinely unseen future window:

```text
static nearest-0.1 rounding MAE = 0.01304
frozen adaptive model MAE       = 0.02174
```

Therefore the current evidence does **not** justify claiming that dynamic anchor + hysteresis is the true production formula.

A simpler interpretation has regained probability:

```text
fixed/slowly stable price anchor
        +
log(A股全指)
        ↓
continuous star
        ↓
approximately nearest 0.1 publication
```

Path dependence may still exist. For example, 2026-10-09 remained at 4.4 after 2026-10-08 reached 4.4, even though the static continuous value was very close to the 4.3/4.4 midpoint. A longer untouched future sample is needed to distinguish ordinary rounding noise from true hysteresis.

## Current main uncertainty

The largest remaining mechanism question is now:

> Is the slowly moving anchor / hysteresis structure a real long-run production mechanism, or did it mainly improve fit to the previously observed 2025-2026 drift?

This cannot be answered by retuning the current 23 future observations.

The next research design should keep both of the following fixed and compare them on subsequent unseen dates:

1. frozen adaptive anchor + hysteresis candidate;
2. pre-existing static price + nearest-0.1 challenger.

No parameter should be changed based on the 2026-09-01 through 2026-10-09 errors.

## Reproducibility

Prospective evaluator:

```text
research/p2_prospective_validation.py
```

Integrity tests:

```text
tests/test_p2_frozen_candidate.py
```

The tests lock:

- original freeze date;
- slope;
- 10-observation anchor window;
- mean anchor statistic;
- +0.07 / -0.06 thresholds;
- prospective Target being strictly post-freeze;
- verified price overlap at 5969.33;
- complete price coverage for the 23 prospective Target dates.
