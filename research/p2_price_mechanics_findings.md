# P2 price mechanics findings

## Scope

This note records the current P2 checkpoint after correcting known Target extraction errors and removing the unresolved 2025-08-26 legacy exact label.

Model-selection policy remains strict:

- 2022-2024: training / expanding pre-holdout validation.
- 2025-2026: locked holdout only.
- Model class and parameters must both be selected before looking at the locked holdout.

## Target-cleaning impact

Confirmed Target fixes:

- 2026-01-14: 3.7 exact -> 3.8 exact.
- 2026-04-13: 3.9 exact -> 3.9-4.0 range.
- 2026-07-14: 4.1 exact -> 3.9-4.0 range.
- 2025-08-26: legacy 4.2 exact -> threshold-only evidence, because the surviving next-day backlink says only “大盘摸到4.2星”; the closing value remains unresolved.

After cleaning, the locked price-only model remains extremely strong.

Current price-only holdout exact MAE:

```text
0.04548 star
```

The log-price coefficient is:

```text
-4.1277
```

A 0.1-star movement in the continuous latent score therefore corresponds mechanically to roughly:

```text
2.45% index-price movement
```

This is the distance between latent-score levels, not the required single-day market move to cross a published boundary. A daily crossing can occur after a smaller move if the latent score was already close to the next threshold.

## P2 discrete-mechanism comparison

Candidate mechanism classes:

1. continuous price score;
2. 0.1-star rounding;
3. symmetric sticky threshold;
4. asymmetric hysteresis.

### Pre-holdout selection

Best expanding-validation results:

| Mechanism | Selected parameter(s) | CV exact MAE |
| --- | --- | ---: |
| continuous | none | 0.10862 |
| 0.1 rounding | offset = -0.01 | 0.10608 |
| sticky | threshold = 0.11 | 0.10165 |
| hysteresis | threshold_up = 0.07, threshold_down = 0.11 | **0.09811** |

Therefore the canonical P2 mechanism selected before the holdout is:

```text
hysteresis
```

### Locked 2025-2026 holdout

| Mechanism | Exact MAE | Exact error <= 0.1 |
| --- | ---: | ---: |
| continuous | 0.04548 | 95.67% |
| 0.1 rounding | 0.04399 | 83.72% |
| sticky | 0.03969 | 97.71% |
| hysteresis | **0.04275** | **97.20%** |

The pre-holdout-selected hysteresis mechanism improves exact MAE versus continuous price-only by about:

```text
0.00273 star
~6.0%
```

Sticky happens to perform better on the locked holdout, but it must not replace hysteresis after observing holdout performance. That would be holdout leakage.

## Interpretation

The current evidence supports the following mechanism more strongly than a multi-factor valuation model:

```text
continuous price-driven latent star
        ↓
state-dependent publication threshold
        ↓
0.1-star published state
```

The result is consistent with a sticky / hysteretic publication rule rather than simple rounding.

The pre-holdout optimum is asymmetric:

```text
latent star must rise ~0.07 above the current state before an upward star update
latent star must fall ~0.11 below the current state before a downward star update
```

This asymmetry is evidence for hysteresis, but it should not yet be interpreted as the exact historical production rule. The thresholds are empirical parameters estimated using A股全指 as the current price proxy.

## Residual-factor result remains negative

The previously selected 10-year PB percentile still fails on the locked holdout:

```text
price-only exact MAE ≈ 0.04548
price + PB exact MAE ≈ 0.10733
```

The slow-fundamental anchor is still not selected pre-holdout.

Therefore P2 should continue to prioritize threshold mechanics before adding macro or valuation factors.

## Next P2 questions

1. Test whether hysteresis thresholds are stable by star regime (3.x / 4.x / 5.x).
2. Test rolling / yearly / change-point intercepts without using holdout for selection.
3. Separate true anchor resets from publication-threshold effects.
4. Continue auditing large residual dates, but do not reinterpret strong closing exact evidence merely because a residual is large.
5. Keep 2025-2026 locked for final model comparisons.

## P2-5 online anchor adaptation

A leakage-safe online anchor test was added after the static/discrete analysis.

Rule:

- keep the pre-holdout price slope fixed;
- before predicting date t, estimate the intercept from only previously published star observations;
- after predicting t, the observed t star may enter the history for t+1;
- select the rolling window/statistic only on 2023-2024 expanding validation.

The selected rule is:

```text
10 prior published targets
mean implied anchor
```

Pre-holdout exact MAE:

```text
0.03567
```

2025-2026 evaluation:

```text
static price-only exact MAE = 0.04548
online anchor exact MAE      = 0.02841
relative improvement         = 37.5%
exact error <= 0.1 star      = 100%
```

This is substantially stronger evidence for anchor drift than any tested PB/GDP/ROE residual correction.

Important distinction: the online-anchor replica is adaptive. It uses previously published stars, which are available at prediction time, but it is not a fully exogenous formula that can be reconstructed from market price alone.

## P2-6 adaptive anchor plus publication hysteresis

A one-step adaptive publication model was then tested:

```text
current price
    +
rolling implied anchor from prior published stars
    ↓
continuous latent star
    ↓
compare with previously published star
    ↓
hysteresis threshold
    ↓
published 0.1-star state
```

The anchor rule remains 10-observation mean. Hysteresis parameters selected on 2023-2024 are:

```text
star-up threshold   = 0.07
star-down threshold = 0.06
```

Pre-holdout exact MAE for this adaptive-hysteresis rule:

```text
0.02217
```

2025-2026 evaluation:

```text
online anchor exact MAE         = 0.02841
adaptive hysteresis exact MAE   = 0.01832
improvement vs online anchor    = 35.5%
improvement vs static price     = 59.7%
exact error <= 0.1 star         = 100%
```

### Holdout-design caveat

The combined adaptive-hysteresis architecture was proposed after earlier 2025-2026 holdout results had already been inspected. Therefore 2025-2026 is no longer a pristine model-selection holdout for this newly proposed architecture, even though all numerical parameters were selected exclusively on 2023-2024.

Accordingly:

- treat the 2023-2024 expanding result as the main architecture-development evidence;
- treat the 2025-2026 combined-model result as exploratory / post-hoc confirmation;
- do not promote the combined architecture to a final confirmed replica until it is tested on genuinely unseen future dates.

## Regime-stability diagnostic

The empirical trigger gaps are not constant across star regimes or periods. Examples:

- pre-holdout 4.x: median star-down trigger gap ~0.127, star-up ~0.024;
- locked-period 4.x: star-down ~0.101, star-up ~0.062;
- pre-holdout 5.x: star-down ~0.103, star-up ~0.069;
- locked-period 5.x: star-down ~0.117, star-up ~0.017.

The 3.x regime is only well represented in the later period and also differs materially.

Therefore the earlier global 0.07 / 0.11 hysteresis estimates should not be interpreted as immutable production constants. The evidence is more consistent with a combination of:

```text
price-driven latent score
+ slowly moving anchor
+ publication-state thresholding
+ some proxy / label noise
```

This makes dynamic anchor estimation the highest-priority mechanism for the next research stage.
