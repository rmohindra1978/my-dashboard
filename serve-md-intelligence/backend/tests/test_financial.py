from __future__ import annotations

import pytest

from backend.app.engines.financial import run_model, run_sensitivity
from backend.app.engines.financial.engine import irr_annual_from_monthly
from backend.app.models.financial import SensitivityRequest


def test_default_scenario_is_coherent(assumptions):
    res = run_model(assumptions)
    assert len(res.monthly) == 60 and len(res.annual) == 5
    assert res.initial_investment > 0
    assert res.annual[0].revenue < res.annual[4].revenue
    assert res.break_even_month is not None and 12 <= res.break_even_month <= 48
    assert res.peak_cash_requirement >= res.initial_investment
    assert res.annual[4].ebitda_margin_pct is not None and 10 <= res.annual[4].ebitda_margin_pct <= 45
    assert res.irr_pct is not None and res.roi_pct is not None
    for y in res.annual:
        assert abs(sum(y.revenue_by_stream.values()) - y.revenue) < 1e-6
        assert abs(sum(y.opex_by_category.values()) - y.opex) < 1e-6
        assert abs(y.revenue - y.opex - y.ebitda) < 1e-6
    assert abs(res.total_revenue - sum(y.revenue for y in res.annual)) < 1e-6


def test_monthly_identity(assumptions):
    res = run_model(assumptions)
    for m in res.monthly:
        assert (
            abs(
                m.revenue_total
                - (
                    m.revenue_ffs
                    + m.revenue_ma_ffs
                    + m.revenue_capitated_net
                    + m.revenue_care_management
                    + m.revenue_diagnostics
                )
            )
            < 1e-6
        )
        assert abs(m.ebitda - (m.revenue_total - m.opex_total)) < 1e-6
    assert (
        abs(
            res.monthly[-1].cumulative_cash - (sum(m.cash_flow for m in res.monthly) - res.initial_investment)
        )
        < 1e-4
    )


def test_higher_reimbursement_improves_returns(assumptions):
    base = run_model(assumptions, include_monthly=False)
    better = assumptions.model_copy(deep=True)
    better.reimbursement.ffs_revenue_per_visit *= 1.2
    res = run_model(better, include_monthly=False)
    assert res.total_ebitda > base.total_ebitda
    assert res.irr_pct > base.irr_pct
    assert (res.break_even_month or 999) <= (base.break_even_month or 999)


def test_panel_cap_and_auto_provider(assumptions):
    a = assumptions.model_copy(deep=True)
    a.providers.max_provider_fte = a.providers.md_fte + a.providers.np_pa_fte  # no room to add
    res = run_model(a, include_monthly=True)
    cap = a.patients.panel_cap_per_provider * (a.providers.md_fte + a.providers.np_pa_fte)
    assert max(m.active_patients for m in res.monthly) <= cap + 1e-6
    assert any("turned away" in w for w in res.warnings)


def test_no_terminal_value_lowers_irr(assumptions):
    a = assumptions.model_copy(deep=True)
    a.capital.terminal_ebitda_multiple = 0
    res = run_model(a, include_monthly=False)
    base = run_model(assumptions, include_monthly=False)
    assert res.terminal_value == 0
    assert (res.irr_pct or -999) < base.irr_pct


def test_irr_helper():
    # invest 1000, receive 100/month for 12 months -> monthly 2.92%, ~41.3% annualised
    irr = irr_annual_from_monthly([-1000] + [100] * 12)
    assert irr is not None and 40 < irr < 42
    assert irr_annual_from_monthly([-1, -1, -1]) is None


def test_sensitivity_grid(assumptions):
    req = SensitivityRequest(
        assumptions=assumptions,
        variable_x="reimbursement.ffs_revenue_per_visit",
        values_x=[120, 145, 170],
        variable_y="patients.new_patients_per_month",
        values_y=[50, 65],
        output="irr_pct",
    )
    res = run_sensitivity(req)
    assert len(res.grid) == 2 and len(res.grid[0]) == 3
    assert res.grid[1][2] > res.grid[0][0]
    with pytest.raises(KeyError):
        run_sensitivity(req.model_copy(update={"variable_x": "nope.field"}))
    with pytest.raises(ValueError):
        run_sensitivity(req.model_copy(update={"output": "bogus"}))
