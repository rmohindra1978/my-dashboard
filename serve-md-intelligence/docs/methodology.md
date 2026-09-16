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
- CMS Medicare enrollment (`cms_enrollment`) uses the annual-average rows (`MONTH = 'Year'`) of
  the Monthly Enrollment file, never a single month. `ma_penetration_pct` and `dual_eligible_pct`
  are computed within the same row (`MA_AND_OTH_BENES / TOT_BENES`, `DUAL_TOT_BENES / TOT_BENES`,
  in percent); `medicare_benes_growth_5yr` compares `TOT_BENES` for a year with the same county
  five years earlier (2025 vs 2020) and is only emitted where both years exist, so counties whose
  FIPS changed (e.g. Connecticut planning regions) have no growth value. Every year since 2013
  is stored so `/history/medicare_benes_total` returns the full series; the profile uses the
  latest year. `MA_AND_OTH_BENES` includes the small "other" (cost/PACE) plans, as CMS publishes it.
- CMS Geographic Variation (`cms_geo_variation`) uses the `BENE_AGE_LVL = 'All'` rows for
  Original Medicare (FFS) beneficiaries; the profile uses the latest year (2024), all years since
  2014 are stored. `readmission_rate` is scaled from the file's 0-1 fraction to percent. The
  2014-2024 release no longer publishes `BENE_AVG_RISK_SCRE`, so `avg_hcc_risk_score` stays null
  (the loader emits it automatically if CMS restores the column).
- Territories (PR, VI, GU, AS, MP), "Unknown"/"Foreign" counties (`xx999`) and national rows are
  dropped from all CMS loaders; only the 50 states + DC and their counties are loaded.

## Provider supply (`dac_clinicians`)

Primary-care supply comes from the CMS Doctors & Clinicians National Downloadable File (one row
per clinician × enrollment × group × practice address). A **PCP** is any clinician whose
`pri_spec` is INTERNAL MEDICINE, FAMILY PRACTICE, GENERAL PRACTICE, GERIATRIC MEDICINE, NURSE
PRACTITIONER or PHYSICIAN ASSISTANT (`pcp_count`); `pcp_physician_count` keeps the first four
only. NPs and PAs are counted as PCPs regardless of the setting they work in, so `pcp_count`
overstates panel-carrying primary care in specialty-heavy markets – compare it with the
physician-only count.

- **Geography.** The 5-digit practice ZIP is treated as the ZCTA (ZIP == ZCTA assumption).
  ZIPs that are not in the Census ZCTA universe (PO boxes and single-institution ZIPs such as
  44195 Cleveland Clinic or 76508 Baylor Scott & White Temple) are dropped – about 2 % of PCP
  location rows – so supply near large academic medical centres is understated until a
  ZIP→ZCTA crosswalk (HUD USPS / UDS Mapper) is added. County values are aggregated from ZCTAs
  through `geo_crosswalk` (ZCTA→county weights); when the crosswalk is empty only ZCTA rows
  are emitted.
- **Distinct clinicians.** An NPI is counted once per ZCTA and once per county however many
  addresses or groups it has there. A clinician practising in several ZCTAs / counties is
  counted in each. Split ZCTAs contribute their crosswalk weight (max weight when the clinician
  has several ZCTAs in the county), so county counts are rounded weighted sums.
- **Practice location ≠ service area.** The address is where the clinician bills from, not
  where patients live; large groups sometimes list every clinician at one administrative ZIP,
  which inflates that ZCTA and deflates neighbours. Use ZCTA counts as a proxy and prefer
  county-level ratios for site decisions.
- **Large-group share.** `large_group_pcp_share` = PCPs with `num_org_mem >= 50` (suppressed or
  missing group size counts as *not* large) divided by `pcp_count`; NULL where there are no PCPs.
  The per-1,000-seniors / per-10k-population ratios are produced by the derived-metrics step
  from `pcp_count` and ACS population, not by this loader.
- **Vintage.** The file is refreshed roughly monthly; `period` is the release month
  (`YYYY-MM`) from the CMS metastore.

## Versioning and reproducibility

Saving a configuration in the Score Editor creates a new immutable version (`id`, `version`,
`created_at`). Rankings and CSV exports carry `config_id` / `config_version`, so any past output
can be regenerated. Unsaved edits are applied live and clearly labelled.

## Known limitations

- Public data lags 1–3 years; vintages are shown on each profile.
- Cross-source denominators differ (ACS 5-year vs PEP vs CMS enrollment); ratios are computed
  within a single source wherever possible and documented in the data dictionary derivation.
- CMS suppresses small cells (`*`, typically counties with < 11 beneficiaries in a category);
  these are stored as NULL and never imputed, so a few rural counties lack utilisation metrics.
- Percentile scoring compresses real differences at the extremes; use `minmax` or `zscore` when
  absolute spread matters.
