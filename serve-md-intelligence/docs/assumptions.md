# Financial model – assumptions and mechanics

All defaults live in `config/financial_default.yaml`, are returned by `GET /api/financial/defaults`,
and are editable field-by-field in the Financial Model page. Scenarios can be saved (optionally tied
to a market). Nothing below is a forecast; these are documented starting points intended to be
tuned as SERVE MD accumulates operating data.

## Mechanics (`backend/app/engines/financial/engine.py`)

The model simulates `model_years × 12` months of a **de novo clinic**:

| block | mechanics |
|---|---|
| Patients | `starting_patients`; gross adds ramp linearly from 25 % to `new_patients_per_month` over `ramp_months`; from year 3 adds grow by `annual_patient_growth_pct_after_year2`; monthly churn = `annual_churn_pct / 12`; active panel capped at `panel_cap_per_provider × provider FTE`. Unmet demand is reported as a warning. |
| Providers | `md_fte` + `np_pa_fte` on payroll from `hire_lead_months` before opening; when panel utilisation exceeds `add_provider_when_panel_pct` an NP/PA FTE is auto-added up to `max_provider_fte` (0 = unlimited). |
| Visits | `active_patients × visits_per_patient_per_year / 12`, adjusted by `annual_visit_intensity_change_pct`. |
| Revenue | Patients split `ffs_pct` / `ma_pct`; `ma_capitated_share_pct` of MA patients are capitated. FFS visits × `ffs_revenue_per_visit`; MA non-capitated visits × `ma_ffs_revenue_per_visit`; capitated patients × `capitated_pmpm × (1 − capitated_medical_cost_pct)` (net of downstream medical cost, i.e. shared-savings view); all patients × `care_management_pmpm`; visits × `in_office_diagnostics_revenue_per_visit`. Everything × `collection_rate_pct`, escalated annually by `annual_rate_increase_pct`. |
| Provider cost | salaries × (1 + `benefits_load_pct`), wage inflation `annual_wage_inflation_pct`. |
| Staff cost | MA / front-desk / care-coordinator FTE = ratio × provider FTE, plus `practice_manager_fte`; salaries with benefits load and wage inflation. |
| Facility | `square_feet × (rent + CAM) / 12`, `months_free_rent`, `annual_rent_escalator_pct`. |
| Diagnostics cost | `diagnostics_cost_pct_of_revenue` × diagnostics revenue. |
| Marketing | `cost_per_new_patient × gross adds` + `fixed_marketing_per_month`; `launch_marketing_budget` at month 0. |
| Overhead | `variable_overhead_pct_of_revenue` × revenue + `fixed_gna_per_month` (inflated) + `emr_per_provider_per_month × provider FTE`. |
| Capex / investment | month 0: `square_feet × buildout_cost_per_sqft` + `equipment_and_it_capex` + launch marketing + pre-opening provider payroll + `working_capital_months` × first-year average opex. |
| Outputs | monthly & annual P&L, EBITDA and margin, **EBITDA break-even month** (first month EBITDA ≥ 0), **cumulative-cash break-even month**, **peak cash requirement** (most negative cumulative cash), **ROI** = (Σ cash flows + terminal value − investment) / investment, **IRR** (monthly IRR annualized, including terminal value if `terminal_ebitda_multiple` > 0), **NPV** at `discount_rate_pct`. `tax_rate_pct` is carried as an assumption for future after-tax views; returns are currently EBITDA-based (default 0). |

## Default assumptions and rationale

| assumption | default | rationale |
|---|---|---|
| Model horizon | 5 years | standard de novo underwriting period |
| New patients / month (steady state) | 65 | typical senior-focused clinic ramp with active outreach; ~780/yr gross |
| Ramp | 6 months from 25 % | grand-opening to referral-network maturity |
| Annual churn | 15 % | Medicare attrition incl. mortality, moves, plan switching |
| Panel cap / provider | 800 | senior-focused, high-touch panels are ~⅓ of a commercial PCP panel (2,000–2,500) |
| Visits / patient / year | 6.0 | Medicare seniors with chronic conditions: AWV + 4–6 problem visits |
| Payer mix | 55 % FFS / 45 % MA, 50 % of MA capitated | national MA penetration ≈ 50 % (2024–25); local mix can be pre-filled from the market's `ma_penetration_pct` |
| FFS revenue / visit | $145 | blended 99213/99214 + AWV + G2211 Medicare allowables |
| MA FFS revenue / visit | $138 | MA fee schedules typically ~95 % of Medicare |
| Capitated PMPM | $1,100 gross; 85 % medical cost | Medicare Part A/B benchmark ≈ $1,100–1,300 PMPM; MLR 85 % → net PMPM ≈ $165 |
| Care-management PMPM | $15 | blended CCM/TCM/RPM billing across the panel |
| Rate increase | 1.5 %/yr | recent PFS updates have ranged −2 % to +3 % |
| Collection rate | 96 % | Medicare bad debt is low |
| Providers | 2 MD @ $265k, 1 NP/PA @ $130k, 22 % benefits | MGMA-range primary-care compensation |
| Auto-add provider | at 95 % panel utilisation, max 4 FTE | site physically fits ~4 providers in 4,000 sq ft |
| Staffing ratios | 1.25 MA, 0.6 front desk, 0.4 care coordinator per provider; 1 practice manager | value-based senior clinics run richer MA/care-coordination ratios than commercial primary care |
| Staff salaries | MA $46k, front desk $40k, care coordinator $62k, manager $85k; 3 % wage inflation | BLS national medians, rounded |
| Facility | 4,000 sq ft, $28 rent + $8 CAM per sq ft per yr, 3 % escalator, 3 months free rent | class-B medical office in suburban markets |
| Build-out | $120 / sq ft; equipment & IT $180k | tenant-improvement and startup capex norms |
| Diagnostics | $22 revenue per visit at 45 % cost | in-office labs, EKG, spirometry |
| Marketing | $180 CAC + $6k/month fixed; $60k launch | community outreach, broker/plan partnerships |
| Overhead | 8 % of revenue variable + $18k/month fixed G&A; $650 EMR per provider per month | billing, supplies, malpractice, insurance, IT, accounting |
| Growth | +5 %/yr new-patient adds after year 2; 0 % visit-intensity change | maturing referral network |
| Capital | 3 months working capital; 8× terminal EBITDA; 12 % discount rate; 0 % tax | typical healthcare-services multiples and cost of equity; EBITDA-based returns by default |

With these defaults the base case reaches EBITDA break-even around month 31, ~25 % EBITDA margin in
year 5, peak cash need ≈ $3.6 M and a positive IRR only when terminal value is included – i.e. a
plausible but demanding de novo profile. Change any input and the outputs recompute live.

## Sensitivity

`POST /api/financial/sensitivity` runs a one- or two-way grid over any numeric assumption
(`section.field`) and returns the chosen output (IRR, ROI, NPV, EBITDA, break-even month, peak
cash…) for each cell.
