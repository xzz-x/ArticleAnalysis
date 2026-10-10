# 2021 backward cross-cycle findings

> Purpose: structural validation only.  
> The 2021 sample is not used to retrain the 2022-2024 price formula.

## 1. Verified contemporaneous sample

A version-aware 2021 contemporaneous sample has been recovered from Bank Screw articles in Google Drive:

```text
data/verified/star_target_2021_crosscycle_sample.csv
```

Current sample:

```text
24 dated observations
23 coarse published half-star/integer states
1 explicit 3.5-4.0 boundary
```

Observed published regimes include:

```text
3.0
3.5
4.0
```

Important publication-version evidence:

- 2021 articles commonly use 0.5-star states;
- 2021-03-23 explicitly describes repeated switching near the 4.0 / 3.5 boundary;
- 2021-09-24 says the public state is still 3.5-star while the finer position is about 3.9-star.

Therefore 2021 displayed stars must not be treated as modern fine 0.1-star point targets.

Recommended semantics:

```text
published 3.5 -> latent state approximately within [3.5, 4.0)
published 4.0 -> latent state approximately within [4.0, 4.5)
```

Explicit stated ranges retain their original ranges.

## 2. Static 2022-2024 formula backward test

The modern static price challenger is kept unchanged:

```text
latent_star =
39.95198926812065
- 4.127707783337646 * log(CSI All Share)
```

When this modern formula is projected backward to the 2021 contemporaneous sample using the correct coarse-bucket interpretation:

```text
static latent coarse-bucket MAE ≈ 0.173 star
inside correct coarse bucket ≈ 25%
max coarse-bucket miss ≈ 0.689 star
```

Thus the modern fixed intercept is not compatible with 2021.

## 3. Intercept-shift diagnostic

Keeping the same modern price slope fixed, a post-hoc uniform intercept translation was estimated only to quantify structural anchor displacement.

Full 2021 sample:

```text
best intercept shift ≈ -0.389 star
bucket MAE after shift ≈ 0.045
inside-bucket rate after shift ≈ 75%
```

Subperiods:

```text
2021 Jan-Apr:
best shift ≈ -0.48 star

2021 Sep-Nov:
best shift ≈ -0.21 star
```

These shifts are diagnostics only and must not be promoted into a predictive model.

## 4. Interpretation

The 2021 evidence strongly rejects a universal 2021-2026 formula with one fixed intercept.

At the same time, the fact that a simple intercept translation greatly restores fit suggests that the short-run price sensitivity may be more stable than the star anchor.

This is consistent with the broader mechanism hypothesis:

```text
short-run:
market price dominates star movement

long-run:
the price level corresponding to a given star regime shifts upward

publication layer:
2021 used coarse 0.5-star states
2022 transitioned toward fine 0.1-star publication
```

This agrees directionally with Bank Screw's official examples that the same 5-star regime occurred near materially higher CSI All Share levels in later years, attributed mainly to listed-company earnings growth.

## 5. Important caution

The 2021 shift is not necessarily pure economic earnings growth.

It may combine:

- long-run earnings / valuation-anchor movement;
- methodology revisions;
- publication-granularity changes;
- contemporaneous-vs-backcast version differences.

Therefore the next historical step is not to fit a larger 2021 model.

The next step is to obtain a versioned 2012-2021 series with both:

```text
contemporaneous_published_star
current_app_backcast_star
```

where overlap exists.

A systematic difference between the two would reveal retrospective recalculation by the mini-program.

## 6. Parser improvement discovered during this work

Historical articles exposed a negation edge case:

```text
A股也没有回到4星级
```

could previously be mistaken for a current 4-star observation.

The realtime parser now explicitly rejects:

```text
没有回到X星
没回到X星
未回到X星
```

with regression tests for the 2021 wording.

## 7. Current consequence

Current hierarchy of evidence:

1. price is the dominant short-run driver;
2. modern static price + 0.1 rounding is an excellent local 2026 approximation;
3. one fixed price intercept does not survive backward extension to 2021;
4. an intercept shift restores much of the 2021 fit, supporting a moving long-run anchor;
5. 2021 publication precision was materially coarser than the modern regime;
6. the unresolved problem is now long-run anchor/version evolution, not daily short-run price sensitivity.
