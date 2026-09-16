// Mirrors backend/app/models/*. Keep in sync when contracts change.
export type GeoLevel = "state" | "county" | "zcta" | "place";

export interface GeoUnit {
  geo_level: GeoLevel;
  geo_id: string;
  name: string;
  state_fips?: string | null;
  state_abbr?: string | null;
  lat?: number | null;
  lon?: number | null;
  land_area_sqmi?: number | null;
  cbsa_code?: string | null;
  cbsa_name?: string | null;
}

export interface SearchResult {
  geo_level: GeoLevel;
  geo_id: string;
  name: string;
  state_abbr?: string | null;
  display: string;
  match_score: number;
}

export interface SourceDef {
  id: string;
  name: string;
  publisher: string;
  url: string;
  vintage: string;
  geo_levels: GeoLevel[];
  notes?: string | null;
}

export interface MetricDef {
  id: string;
  label: string;
  description: string;
  pillar: string;
  unit: string;
  format: string;
  higher_is_better: boolean | null;
  geo_levels: GeoLevel[];
  source: string;
  derivation: string;
  scoring_default: number;
}

export interface MetricRegistry {
  sources: Record<string, SourceDef>;
  metrics: MetricDef[];
}

export interface MetricReading {
  metric_id: string;
  label: string;
  value: number | null;
  unit: string;
  format: string;
  period?: string | null;
  source_id: string;
  source_name: string;
  higher_is_better: boolean | null;
  percentile?: number | null;
}

export interface PillarPanel {
  pillar: string;
  label: string;
  metrics: MetricReading[];
}

export interface PillarConfig {
  label: string;
  weight: number;
  description?: string | null;
}

export interface ScoreConfig {
  id: string;
  name: string;
  description?: string | null;
  version: number;
  normalization: "percentile" | "minmax" | "zscore";
  missing_metric_policy: "renormalize" | "zero" | "exclude_market";
  min_coverage_pct: number;
  pillars: Record<string, PillarConfig>;
  metric_weights: Record<string, number>;
  direction_overrides: Record<string, boolean>;
  created_at?: string | null;
}

export interface MetricContribution {
  metric_id: string;
  label: string;
  pillar: string;
  raw_value: number | null;
  normalized: number | null;
  weight: number;
  contribution: number;
}

export interface PillarScore {
  pillar: string;
  label: string;
  score: number | null;
  weight: number;
  coverage_pct: number;
}

export interface MarketScore {
  geo_level: GeoLevel;
  geo_id: string;
  name: string;
  state_abbr?: string | null;
  score: number | null;
  rank?: number | null;
  rank_of?: number | null;
  coverage_pct: number;
  low_confidence: boolean;
  pillar_scores: PillarScore[];
  contributions: MetricContribution[];
  config_id: string;
  config_version: number;
}

export interface MarketProfile {
  geo: GeoUnit;
  panels: PillarPanel[];
  score?: MarketScore | null;
  parent_county?: GeoUnit | null;
  related: GeoUnit[];
  data_vintages: Record<string, string>;
}

export interface MetricFilter {
  metric_id: string;
  op: "gte" | "lte" | "eq" | "between";
  value?: number | null;
  low?: number | null;
  high?: number | null;
}

export interface RankingRequest {
  geo_level: GeoLevel;
  config_id?: string | null;
  config?: ScoreConfig | null;
  states?: string[] | null;
  filters: MetricFilter[];
  limit: number;
  offset: number;
  include_contributions: boolean;
  sort_by: string;
  descending: boolean;
}

export interface RankingRow extends MarketScore {
  metrics: Record<string, number | null>;
}

export interface RankingResponse {
  total: number;
  geo_level: GeoLevel;
  config_id: string;
  config_version: number;
  rows: RankingRow[];
  computed_in_ms: number;
}

// Financial model --------------------------------------------------------------------------
export interface FinancialAssumptions {
  id: string;
  name: string;
  model_years: number;
  patients: Record<string, number | boolean>;
  payer_mix: Record<string, number>;
  reimbursement: Record<string, number>;
  providers: Record<string, number>;
  staffing: Record<string, number>;
  facility: Record<string, number>;
  diagnostics: Record<string, number>;
  marketing: Record<string, number>;
  overhead: Record<string, number>;
  growth: Record<string, number>;
  capital: Record<string, number>;
}

export type AssumptionSection = Exclude<keyof FinancialAssumptions, "id" | "name" | "model_years">;

export interface MonthlyLine {
  month: number;
  active_patients: number;
  new_patients: number;
  visits: number;
  provider_fte: number;
  revenue_total: number;
  opex_total: number;
  ebitda: number;
  cash_flow: number;
  cumulative_cash: number;
  [k: string]: number;
}

export interface AnnualSummary {
  year: number;
  ending_patients: number;
  visits: number;
  revenue: number;
  revenue_by_stream: Record<string, number>;
  opex: number;
  opex_by_category: Record<string, number>;
  ebitda: number;
  ebitda_margin_pct: number | null;
  capex: number;
  cash_flow: number;
  cumulative_cash: number;
}

export interface FinancialResult {
  assumptions: FinancialAssumptions;
  annual: AnnualSummary[];
  monthly: MonthlyLine[];
  total_revenue: number;
  total_ebitda: number;
  ebitda_margin_pct_final_year: number | null;
  break_even_month: number | null;
  cumulative_break_even_month: number | null;
  peak_cash_requirement: number;
  initial_investment: number;
  roi_pct: number | null;
  irr_pct: number | null;
  npv: number | null;
  terminal_value: number;
  warnings: string[];
}

export interface FinancialScenario {
  id: string;
  name: string;
  geo_level?: GeoLevel | null;
  geo_id?: string | null;
  assumptions: FinancialAssumptions;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface StateInfo {
  fips: string;
  name: string;
  abbr: string;
}
