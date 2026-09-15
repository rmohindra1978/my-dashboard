"""Five-year clinic financial model.

A monthly simulation (model_years * 12 steps) driven entirely by `FinancialAssumptions`.
Month 0 carries the initial investment (build-out, equipment, launch marketing, pre-opening payroll and
working capital). Returns (ROI, IRR, NPV) are computed on monthly cash flows plus an optional terminal value.
All methodology is documented in docs/financial-model.md.
"""

from __future__ import annotations

import copy
import math

import numpy as np

from backend.app.models.financial import (
    AnnualSummary,
    FinancialAssumptions,
    FinancialResult,
    MonthlyLine,
    SensitivityRequest,
    SensitivityResponse,
)


def _pct(x: float) -> float:
    return x / 100.0


def _grow(base: float, annual_pct: float, year_idx: int) -> float:
    return base * (1.0 + _pct(annual_pct)) ** year_idx


def _provider_cost_per_month(a: FinancialAssumptions, md_fte: float, np_fte: float, year_idx: int) -> float:
    p = a.providers
    annual = (md_fte * p.md_salary + np_fte * p.np_pa_salary) * (1 + _pct(p.benefits_load_pct))
    return _grow(annual, a.staffing.annual_wage_inflation_pct, year_idx) / 12.0


def _staff_cost_per_month(a: FinancialAssumptions, provider_fte: float, year_idx: int) -> float:
    s = a.staffing
    annual = (
        s.medical_assistants_per_provider * provider_fte * s.medical_assistant_salary
        + s.front_desk_per_provider * provider_fte * s.front_desk_salary
        + s.care_coordinators_per_provider * provider_fte * s.care_coordinator_salary
        + s.practice_manager_fte * s.practice_manager_salary
    ) * (1 + _pct(s.benefits_load_pct))
    return _grow(annual, s.annual_wage_inflation_pct, year_idx) / 12.0


def _facility_cost_per_month(a: FinancialAssumptions, month: int, year_idx: int) -> float:
    f = a.facility
    if month <= f.months_free_rent:
        return f.square_feet * f.cam_and_utilities_per_sqft_per_year / 12.0
    annual = f.square_feet * (f.rent_per_sqft_per_year + f.cam_and_utilities_per_sqft_per_year)
    return _grow(annual, f.annual_rent_escalator_pct, year_idx) / 12.0


def initial_investment(a: FinancialAssumptions) -> tuple[float, dict[str, float]]:
    """Month-0 outlay. Working capital = N months of steady-state fixed opex at opening staffing."""
    f, m, p = a.facility, a.marketing, a.providers
    provider_fte = p.md_fte + p.np_pa_fte
    monthly_fixed = (
        _provider_cost_per_month(a, p.md_fte, p.np_pa_fte, 0)
        + _staff_cost_per_month(a, provider_fte, 0)
        + a.facility.square_feet * (f.rent_per_sqft_per_year + f.cam_and_utilities_per_sqft_per_year) / 12.0
        + a.overhead.fixed_gna_per_month
        + a.overhead.emr_per_provider_per_month * provider_fte
        + m.fixed_marketing_per_month
    )
    parts = {
        "buildout": f.square_feet * f.buildout_cost_per_sqft,
        "equipment_and_it": f.equipment_and_it_capex,
        "launch_marketing": m.launch_marketing_budget,
        "pre_opening_payroll": (
            _provider_cost_per_month(a, p.md_fte, p.np_pa_fte, 0) + _staff_cost_per_month(a, provider_fte, 0)
        )
        * p.hire_lead_months,
        "working_capital": monthly_fixed * a.capital.working_capital_months,
    }
    return sum(parts.values()), parts


def irr_annual_from_monthly(cash_flows: list[float]) -> float | None:
    """Annualised IRR of a monthly cash-flow series (index 0 = month 0). None if no sign change / no root."""
    cfs = np.asarray(cash_flows, dtype=float)
    if not (np.any(cfs > 0) and np.any(cfs < 0)):
        return None

    def npv(rate: float) -> float:
        t = np.arange(len(cfs))
        return float(np.sum(cfs / (1.0 + rate) ** t))

    lo, hi = -0.99, 1.0  # monthly rate bounds
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    monthly = (lo + hi) / 2.0
    annual = (1.0 + monthly) ** 12 - 1.0
    return None if not math.isfinite(annual) else annual * 100.0


def run_model(a: FinancialAssumptions, include_monthly: bool = True) -> FinancialResult:
    n_months = a.model_years * 12
    warnings: list[str] = []
    if abs(a.payer_mix.ffs_pct + a.payer_mix.ma_pct - 100) > 0.01:
        warnings.append("payer mix does not sum to 100%; shares were normalised")
    mix_total = (a.payer_mix.ffs_pct + a.payer_mix.ma_pct) or 100.0
    ffs_share, ma_share = a.payer_mix.ffs_pct / mix_total, a.payer_mix.ma_pct / mix_total
    cap_share = _pct(a.payer_mix.ma_capitated_share_pct)

    invest, _parts = initial_investment(a)
    md_fte, np_fte = a.providers.md_fte, a.providers.np_pa_fte
    active = float(a.patients.starting_patients)
    cumulative = -invest
    monthly: list[MonthlyLine] = []
    cash_flows = [-invest]
    lost_to_capacity = 0.0

    for month in range(1, n_months + 1):
        year_idx = (month - 1) // 12
        # --- demand
        base_adds = a.patients.new_patients_per_month
        if year_idx >= 2:
            base_adds = _grow(base_adds, a.growth.annual_patient_growth_pct_after_year2, year_idx - 1)
        if a.patients.ramp_months > 0 and month <= a.patients.ramp_months:
            base_adds *= 0.25 + 0.75 * (month / a.patients.ramp_months)
        churned = active * _pct(a.patients.annual_churn_pct) / 12.0
        active = max(0.0, active - churned)

        # --- capacity / auto-add provider
        provider_fte = md_fte + np_fte
        cap = provider_fte * a.patients.panel_cap_per_provider
        room = a.providers.max_provider_fte <= 0 or provider_fte + 1.0 <= a.providers.max_provider_fte
        if room and cap > 0 and (active + base_adds) > cap * _pct(a.providers.add_provider_when_panel_pct):
            np_fte += 1.0
            provider_fte = md_fte + np_fte
            cap = provider_fte * a.patients.panel_cap_per_provider
        new = min(base_adds, max(0.0, cap - active)) if cap > 0 else base_adds
        lost_to_capacity += base_adds - new
        active += new

        # --- volumes & revenue
        rate = (1 + _pct(a.reimbursement.annual_rate_increase_pct)) ** year_idx
        visits_pp = (
            a.patients.visits_per_patient_per_year
            * (1 + _pct(a.growth.annual_visit_intensity_change_pct)) ** year_idx
        )
        visits = active * visits_pp / 12.0
        collect = _pct(a.reimbursement.collection_rate_pct)
        ffs_patients = active * ffs_share
        ma_patients = active * ma_share
        cap_patients = ma_patients * cap_share
        ma_ffs_patients = ma_patients - cap_patients
        visits_ffs = visits * (ffs_patients / active) if active else 0.0
        visits_ma_ffs = visits * (ma_ffs_patients / active) if active else 0.0
        rev_ffs = visits_ffs * a.reimbursement.ffs_revenue_per_visit * rate * collect
        rev_ma_ffs = visits_ma_ffs * a.reimbursement.ma_ffs_revenue_per_visit * rate * collect
        rev_cap = (
            cap_patients
            * a.reimbursement.capitated_pmpm
            * rate
            * (1 - _pct(a.reimbursement.capitated_medical_cost_pct))
        )
        rev_cm = active * a.reimbursement.care_management_pmpm * rate * collect
        rev_diag = visits * a.diagnostics.in_office_diagnostics_revenue_per_visit * rate * collect
        revenue = rev_ffs + rev_ma_ffs + rev_cap + rev_cm + rev_diag

        # --- costs
        c_prov = _provider_cost_per_month(a, md_fte, np_fte, year_idx)
        c_staff = _staff_cost_per_month(a, provider_fte, year_idx)
        c_fac = _facility_cost_per_month(a, month, year_idx)
        c_diag = rev_diag * _pct(a.diagnostics.diagnostics_cost_pct_of_revenue)
        c_mkt = new * a.marketing.cost_per_new_patient + a.marketing.fixed_marketing_per_month
        c_ovh = (
            revenue * _pct(a.overhead.variable_overhead_pct_of_revenue)
            + _grow(a.overhead.fixed_gna_per_month, a.overhead.annual_overhead_inflation_pct, year_idx)
            + a.overhead.emr_per_provider_per_month * provider_fte
        )
        opex = c_prov + c_staff + c_fac + c_diag + c_mkt + c_ovh
        ebitda = revenue - opex
        capex = 0.0
        cash = ebitda - capex
        cumulative += cash
        cash_flows.append(cash)
        monthly.append(
            MonthlyLine(
                month=month,
                active_patients=active,
                new_patients=new,
                visits=visits,
                provider_fte=provider_fte,
                revenue_ffs=rev_ffs,
                revenue_ma_ffs=rev_ma_ffs,
                revenue_capitated_net=rev_cap,
                revenue_care_management=rev_cm,
                revenue_diagnostics=rev_diag,
                revenue_total=revenue,
                cost_providers=c_prov,
                cost_staff=c_staff,
                cost_facility=c_fac,
                cost_diagnostics=c_diag,
                cost_marketing=c_mkt,
                cost_overhead=c_ovh,
                opex_total=opex,
                ebitda=ebitda,
                capex=capex,
                cash_flow=cash,
                cumulative_cash=cumulative,
            )
        )

    if lost_to_capacity > 0:
        warnings.append(
            f"{lost_to_capacity:,.0f} prospective patients turned away by panel capacity; add providers"
        )

    annual: list[AnnualSummary] = []
    for y in range(a.model_years):
        lines = monthly[y * 12 : (y + 1) * 12]
        rev = sum(line.revenue_total for line in lines)
        opx = sum(line.opex_total for line in lines)
        annual.append(
            AnnualSummary(
                year=y + 1,
                ending_patients=lines[-1].active_patients,
                visits=sum(line.visits for line in lines),
                revenue=rev,
                revenue_by_stream={
                    "ffs": sum(line.revenue_ffs for line in lines),
                    "ma_ffs": sum(line.revenue_ma_ffs for line in lines),
                    "capitated_net": sum(line.revenue_capitated_net for line in lines),
                    "care_management": sum(line.revenue_care_management for line in lines),
                    "diagnostics": sum(line.revenue_diagnostics for line in lines),
                },
                opex=opx,
                opex_by_category={
                    "providers": sum(line.cost_providers for line in lines),
                    "staff": sum(line.cost_staff for line in lines),
                    "facility": sum(line.cost_facility for line in lines),
                    "diagnostics": sum(line.cost_diagnostics for line in lines),
                    "marketing": sum(line.cost_marketing for line in lines),
                    "overhead": sum(line.cost_overhead for line in lines),
                },
                ebitda=rev - opx,
                ebitda_margin_pct=((rev - opx) / rev * 100.0) if rev else None,
                capex=sum(line.capex for line in lines),
                cash_flow=sum(line.cash_flow for line in lines),
                cumulative_cash=lines[-1].cumulative_cash,
            )
        )

    final_ebitda = annual[-1].ebitda
    terminal = max(0.0, final_ebitda) * a.capital.terminal_ebitda_multiple
    cash_flows[-1] += terminal
    total_cf = sum(cash_flows[1:])
    roi = ((total_cf - invest) / invest * 100.0) if invest > 0 else None
    irr = irr_annual_from_monthly(cash_flows)
    r_m = (1 + _pct(a.capital.discount_rate_pct)) ** (1 / 12) - 1
    npv = float(sum(cf / (1 + r_m) ** t for t, cf in enumerate(cash_flows)))
    be = next((line.month for line in monthly if line.ebitda > 0), None)
    cum_be = next((line.month for line in monthly if line.cumulative_cash > 0), None)
    peak = max(0.0, -min([-invest] + [line.cumulative_cash for line in monthly]))

    return FinancialResult(
        assumptions=a,
        annual=annual,
        monthly=monthly if include_monthly else [],
        total_revenue=sum(x.revenue for x in annual),
        total_ebitda=sum(x.ebitda for x in annual),
        ebitda_margin_pct_final_year=annual[-1].ebitda_margin_pct,
        break_even_month=be,
        cumulative_break_even_month=cum_be,
        peak_cash_requirement=peak,
        initial_investment=invest,
        roi_pct=roi,
        irr_pct=irr,
        npv=npv,
        terminal_value=terminal,
        warnings=warnings,
    )


def _set_path(obj: FinancialAssumptions, dotted: str, value: float) -> FinancialAssumptions:
    data = obj.model_dump()
    node = data
    parts = dotted.split(".")
    for p in parts[:-1]:
        node = node[p]
    if parts[-1] not in node:
        raise KeyError(dotted)
    node[parts[-1]] = value
    return FinancialAssumptions(**data)


SENSITIVITY_OUTPUTS = {
    "irr_pct": lambda r: r.irr_pct,
    "roi_pct": lambda r: r.roi_pct,
    "npv": lambda r: r.npv,
    "total_ebitda": lambda r: r.total_ebitda,
    "total_revenue": lambda r: r.total_revenue,
    "break_even_month": lambda r: r.break_even_month,
    "cumulative_break_even_month": lambda r: r.cumulative_break_even_month,
    "peak_cash_requirement": lambda r: r.peak_cash_requirement,
    "ebitda_margin_pct_final_year": lambda r: r.ebitda_margin_pct_final_year,
}


def run_sensitivity(req: SensitivityRequest) -> SensitivityResponse:
    if req.output not in SENSITIVITY_OUTPUTS:
        raise ValueError(
            f"unsupported sensitivity output '{req.output}'; choose one of {sorted(SENSITIVITY_OUTPUTS)}"
        )
    pick = SENSITIVITY_OUTPUTS[req.output]
    ys = req.values_y if (req.variable_y and req.values_y) else [None]
    grid: list[list[float | None]] = []
    for y in ys:
        row: list[float | None] = []
        for x in req.values_x:
            a = _set_path(copy.deepcopy(req.assumptions), req.variable_x, x)
            if req.variable_y and y is not None:
                a = _set_path(a, req.variable_y, y)
            res = run_model(a, include_monthly=False)
            val = pick(res)
            row.append(None if val is None else float(val))
        grid.append(row)
    return SensitivityResponse(
        variable_x=req.variable_x,
        values_x=req.values_x,
        variable_y=req.variable_y,
        values_y=req.values_y if req.variable_y else None,
        output=req.output,
        grid=grid,
    )
