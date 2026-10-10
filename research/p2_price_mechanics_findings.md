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
