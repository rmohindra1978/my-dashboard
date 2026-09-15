from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.app.models.geo import GeoLevel


class PatientAssumptions(BaseModel):
    starting_patients: int = Field(ge=0)
    new_patients_per_month: float = Field(ge=0)
    ramp_months: int = Field(ge=0)
    annual_churn_pct: float = Field(ge=0, le=100)
    panel_cap_per_provider: int = Field(gt=0)
    visits_per_patient_per_year: float = Field(ge=0)
    market_prefill: bool = True


class PayerMixAssumptions(BaseModel):
    ffs_pct: float = Field(ge=0, le=100)
    ma_pct: float = Field(ge=0, le=100)
    ma_capitated_share_pct: float = Field(ge=0, le=100)


class ReimbursementAssumptions(BaseModel):
    ffs_revenue_per_visit: float = Field(ge=0)
    ma_ffs_revenue_per_visit: float = Field(ge=0)
    capitated_pmpm: float = Field(ge=0)
    capitated_medical_cost_pct: float = Field(ge=0, le=100)
    care_management_pmpm: float = Field(ge=0)
    annual_rate_increase_pct: float
    collection_rate_pct: float = Field(ge=0, le=100)


class ProviderAssumptions(BaseModel):
    md_fte: float = Field(ge=0)
    md_salary: float = Field(ge=0)
    np_pa_fte: float = Field(ge=0)
    np_pa_salary: float = Field(ge=0)
    benefits_load_pct: float = Field(ge=0)
    hire_lead_months: int = Field(ge=0)
    add_provider_when_panel_pct: float = Field(gt=0, le=200)
    max_provider_fte: float = Field(
        default=0, ge=0, description="site capacity for auto-added providers; 0 = unlimited"
    )


class StaffingAssumptions(BaseModel):
    medical_assistants_per_provider: float = Field(ge=0)
    medical_assistant_salary: float = Field(ge=0)
    front_desk_per_provider: float = Field(ge=0)
    front_desk_salary: float = Field(ge=0)
    care_coordinators_per_provider: float = Field(ge=0)
    care_coordinator_salary: float = Field(ge=0)
    practice_manager_fte: float = Field(ge=0)
    practice_manager_salary: float = Field(ge=0)
    benefits_load_pct: float = Field(ge=0)
    annual_wage_inflation_pct: float


class FacilityAssumptions(BaseModel):
    square_feet: float = Field(ge=0)
    rent_per_sqft_per_year: float = Field(ge=0)
    cam_and_utilities_per_sqft_per_year: float = Field(ge=0)
    annual_rent_escalator_pct: float
    buildout_cost_per_sqft: float = Field(ge=0)
    equipment_and_it_capex: float = Field(ge=0)
    months_free_rent: int = Field(ge=0)


class DiagnosticsAssumptions(BaseModel):
    in_office_diagnostics_revenue_per_visit: float = Field(ge=0)
    diagnostics_cost_pct_of_revenue: float = Field(ge=0, le=100)


class MarketingAssumptions(BaseModel):
    cost_per_new_patient: float = Field(ge=0)
    fixed_marketing_per_month: float = Field(ge=0)
    launch_marketing_budget: float = Field(ge=0)


class OverheadAssumptions(BaseModel):
    variable_overhead_pct_of_revenue: float = Field(ge=0, le=100)
    fixed_gna_per_month: float = Field(ge=0)
    annual_overhead_inflation_pct: float
    emr_per_provider_per_month: float = Field(ge=0)


class GrowthAssumptions(BaseModel):
    annual_patient_growth_pct_after_year2: float
    annual_visit_intensity_change_pct: float


class CapitalAssumptions(BaseModel):
    working_capital_months: float = Field(ge=0)
    terminal_ebitda_multiple: float = Field(ge=0)
    discount_rate_pct: float
    tax_rate_pct: float = Field(ge=0, le=100)


class FinancialAssumptions(BaseModel):
    """Complete input set for the five-year clinic model. Mirrors config/financial_default.yaml."""

    id: str = "default"
    name: str = "Scenario"
    model_years: int = Field(default=5, ge=1, le=10)
    patients: PatientAssumptions
    payer_mix: PayerMixAssumptions
    reimbursement: ReimbursementAssumptions
    providers: ProviderAssumptions
    staffing: StaffingAssumptions
    facility: FacilityAssumptions
    diagnostics: DiagnosticsAssumptions
    marketing: MarketingAssumptions
    overhead: OverheadAssumptions
    growth: GrowthAssumptions
    capital: CapitalAssumptions


class MonthlyLine(BaseModel):
    month: int = Field(ge=1, description="1-based month index from opening")
    active_patients: float
    new_patients: float
    visits: float
    provider_fte: float
    revenue_ffs: float
    revenue_ma_ffs: float
    revenue_capitated_net: float
    revenue_care_management: float
    revenue_diagnostics: float
    revenue_total: float
    cost_providers: float
    cost_staff: float
    cost_facility: float
    cost_diagnostics: float
    cost_marketing: float
    cost_overhead: float
    opex_total: float
    ebitda: float
    capex: float
    cash_flow: float
    cumulative_cash: float


class AnnualSummary(BaseModel):
    year: int
    ending_patients: float
    visits: float
    revenue: float
    revenue_by_stream: dict[str, float]
    opex: float
    opex_by_category: dict[str, float]
    ebitda: float
    ebitda_margin_pct: float | None
    capex: float
    cash_flow: float
    cumulative_cash: float


class FinancialResult(BaseModel):
    assumptions: FinancialAssumptions
    annual: list[AnnualSummary]
    monthly: list[MonthlyLine] = Field(default_factory=list)
    total_revenue: float
    total_ebitda: float
    ebitda_margin_pct_final_year: float | None
    break_even_month: int | None = Field(description="first month with positive EBITDA; None if never")
    cumulative_break_even_month: int | None = Field(description="first month cumulative cash turns positive")
    peak_cash_requirement: float = Field(
        description="most negative cumulative cash position (positive number)"
    )
    initial_investment: float
    roi_pct: float | None = Field(
        description="(sum of cash flows incl. terminal value - investment) / investment"
    )
    irr_pct: float | None = Field(description="annualised IRR on monthly cash flows incl. terminal value")
    npv: float | None
    terminal_value: float
    warnings: list[str] = Field(default_factory=list)


class SensitivityRequest(BaseModel):
    assumptions: FinancialAssumptions
    variable_x: str = Field(description="dotted path, e.g. 'reimbursement.ffs_revenue_per_visit'")
    values_x: list[float]
    variable_y: str | None = None
    values_y: list[float] | None = None
    output: str = Field(
        default="irr_pct",
        description="irr_pct | roi_pct | total_ebitda | break_even_month | peak_cash_requirement",
    )


class SensitivityResponse(BaseModel):
    variable_x: str
    values_x: list[float]
    variable_y: str | None
    values_y: list[float] | None
    output: str
    grid: list[list[float | None]] = Field(description="rows = values_y (or single row), cols = values_x")


class FinancialScenario(BaseModel):
    id: str
    name: str
    geo_level: GeoLevel | None = None
    geo_id: str | None = None
    assumptions: FinancialAssumptions
    created_at: datetime | None = None
    updated_at: datetime | None = None
