# SERVE MD Score methodology

The SERVE MD Score is a relative, configurable 0–100 index of how attractive a market is for a
Medicare-focused, value-based primary-care clinic. It is a **ranking tool**, not a forecast.

## Pillars (default weights)

| pillar | weight | question it answers |
|---|---|---|
| Medicare demand | 30 | How many Medicare beneficiaries are there, how fast is that growing, how MA-heavy and how acute is the population? |
| Demographics & growth | 20 | How large and fast-growing is the 65+ population? |
| Competition & provider supply | 20 | Is primary care under-supplied relative to seniors? Is the market consolidated? |
| Health need | 15 | How much chronic-disease burden is there for value-based care to manage? |
| Economics & cost | 15 | Local income, poverty, labour market and occupancy-cost proxies. |

Every pillar weight, every metric weight inside a pillar, and every metric's direction
(higher-is-better vs lower-is-better) is editable in the Score Editor. Weights are relative –
they are renormalized to sum to 1 – so any positive numbers work.

## Computation

For a geography level `L` (county, ZCTA, place, state) and a score configuration `C`:

1. **Peer group.** All units of level `L` in the warehouse (optionally restricted to selected
   states). Percentiles are always computed against the peer group actually being ranked, so a
   county's score is comparable to other counties but not to a ZIP code's score.
2. **Normalize** each scored metric `m` to `n_m ∈ [0, 100]`:
   - `percentile` (default): average-rank percentile → robust to outliers and skew.
   - `minmax`: winsorized at the 2nd / 98th percentile then min–max scaled.
   - `zscore`: z-score clipped to ±3σ then mapped linearly to 0–100.
   If the metric's direction is lower-is-better, `n_m ← 100 − n_m`.
3. **Pillar score** `P_k = Σ_m w_m n_m / Σ_m w_m` over the metrics in pillar `k` that are
   present for the unit.
4. **Missing data policy** (per config):
   - `renormalize` (default): missing metrics drop out of the weighted average – the pillar is
     computed from what is available.
   - `zero`: missing metrics contribute 0.
   - `exclude_market`: units missing any weighted metric receive no score.
5. **Score** `S = Σ_k W_k P_k / Σ_k W_k` over pillars with at least one available metric.
6. **Coverage** = share of total configured metric weight that was available. Units with coverage
   below `min_coverage_pct` (default 60 %) are flagged `low_confidence` in every view.
7. **Rank** = dense rank of `S` within the peer group (1 = best).
8. **Explainability.** `/api/score/explain` returns each metric's raw value, normalized value,
   effective weight and contribution in points, which the market profile renders as a bar chart.

## Metric conventions

- Counts (beneficiaries, 65+ population) are intentionally scored *higher-is-better*: SERVE MD
  needs a large enough addressable population to fill a clinic panel. Density-style metrics
  (PCPs per 1,000 seniors) capture under-supply and are *lower-is-better*.
- Rates from CDC PLACES are age-adjusted model-based estimates; they are used to express need,
  not clinical risk.
- Informational metrics (`higher_is_better: null`, e.g. race / ethnicity shares) are shown on
  the profile but can never be weighted.
- ZCTA and place scores use the metrics available at that level (ACS, clinician file);
  county-only CMS metrics are shown from the parent county on the profile but do not enter the
  sub-county score unless a future loader allocates them via the crosswalk.

## Versioning and reproducibility

Saving a configuration in the Score Editor creates a new immutable version (`id`, `version`,
`created_at`). Rankings and CSV exports carry `config_id` / `config_version`, so any past output
can be regenerated. Unsaved edits are applied live and clearly labelled.

## Known limitations

- Public data lags 1–3 years; vintages are shown on each profile.
- Cross-source denominators differ (ACS 5-year vs PEP vs CMS enrollment); ratios are computed
  within a single source wherever possible and documented in the data dictionary derivation.
- Percentile scoring compresses real differences at the extremes; use `minmax` or `zscore` when
  absolute spread matters.
