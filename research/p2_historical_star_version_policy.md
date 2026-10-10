# Historical star-version policy

## Why this exists

The Bank Screw star series is not guaranteed to have used one immutable publication rule since 2012.

Public contemporaneous evidence shows clear changes in terminology and precision:

### 2018: coarse, experience-based classification

Bank Screw's 2018 article "历史上的5星级投资机会" states that the four-star / five-star classification was an empirical judgment and did not have an especially strict definition.

It also describes a rough five-star condition using extremely cheap items appearing in the valuation table, such as:

- PE below 7;
- PB below 1;
- dividend yield above 5%.

Source:

- https://xueqiu.com/3079173340/109677906

### 2021: half-star publication granularity

Contemporaneous Bank Screw posts commonly used half-star states.

Examples:

- 2021-03-23: A shares moved repeatedly near the boundary between 4 stars and 3.5 stars.
- 2021-04-01: after the market rose, it returned to 3.5 stars.

Sources:

- https://xueqiu.com/3079173340/175231968/179503278
- https://xueqiu.com/3079173340/176128722

### Early 2022: explicit coarse-versus-fine transition

Existing project evidence already records:

- before 2022-05-31, integer / half-star language often acted as a coarse bucket;
- 2022-04-07 explicitly states that the market was "still 4.5-star", while a finer calculation gave 4.8;
- 2022-05-31 says the market moved out of five-star and now counts as 4.9;
- June 2022 onward, 0.1-star publication becomes consistent.

Existing analysis:

```text
research/p2_2022_granularity_sensitivity.py
research/p2_granularity_interval_model.py
```

## Important implication for the mini-program history

The current "今天几星" mini-program provides a historical chart back to 2012.

That historical chart may be useful for replicating the **current app's backcast series**.

However, it must not automatically be assumed to equal the **contemporaneously published historical star value** on every old date.

Reasons:

1. publication precision changed over time;
2. old articles describe the rating as a coarse empirical classification;
3. later app history may use a unified retrospective calculation or normalized display;
4. at least one third-party historical review reports a mismatch between a 2020 contemporaneous 3.5-star portfolio record and a later app representation around 4 stars.

The third-party mismatch is only a warning, not authoritative Target evidence:

- https://xueqiu.com/4778574435/282350872

## Required target-version fields for any 2012-2021 backfill

Any future old-history dataset should distinguish at least:

```text
date
star
source_type
source_url
publication_version
precision
is_contemporaneous
is_app_backcast
evidence_text
confidence
```

Recommended `publication_version` values:

```text
legacy_empirical_coarse
legacy_half_star
transition_coarse_plus_fine
modern_0_1_star
app_backcast_unknown_version
```

## Training policy

### Goal A: replicate the current live star calculation

Primary training/evaluation evidence should use the modern fine-grained publication regime.

Current practical boundary:

```text
2022-05-31 onward
```

Earlier coarse evidence may be used only with interval / bucket semantics.

### Goal B: replicate the current mini-program historical chart

If the mini-program 2012-2021 series can be extracted, treat it as a separate Target:

```text
app_backcast_star
```

Do not silently overwrite contemporaneous historical records.

### Goal C: study how the methodology evolved

Compare:

```text
contemporaneous_published_star
vs
current_app_backcast_star
```

on dates where both are available.

A systematic difference would itself reveal methodology/version changes.

## Current research consequence

The full reverse-engineering problem is now explicitly split into two related but distinct questions:

1. **Modern production rule:** what determines the star value published today?
2. **Historical backcast rule:** how does the current mini-program assign stars to dates before the modern 0.1-star regime?

These two formulas may not be identical.

Until proven otherwise, they must not share one unversioned Target column.
