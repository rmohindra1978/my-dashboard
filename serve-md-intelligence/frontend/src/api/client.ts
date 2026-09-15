import type {
  FinancialAssumptions,
  FinancialResult,
  FinancialScenario,
  GeoLevel,
  MarketProfile,
  MarketScore,
  MetricRegistry,
  RankingRequest,
  RankingResponse,
  ScoreConfig,
  SearchResult,
  StateInfo,
} from "./types";

const BASE = import.meta.env.VITE_API_URL ?? "";
const TOKEN_KEY = "servemd.token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}
export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(init.headers as Record<string, string>) };
  const token = getToken();
  if (token) headers["X-Access-Token"] = token;
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => request<{ status: string; geo_units: number; metric_rows: number; sources_loaded: Record<string, string> }>("/api/health"),
  metrics: () => request<MetricRegistry>("/api/meta/metrics"),
  states: () => request<StateInfo[]>("/api/meta/states"),
  search: (q: string) => request<SearchResult[]>(`/api/search?q=${encodeURIComponent(q)}`),
  market: (level: GeoLevel, id: string, configId = "default") =>
    request<MarketProfile>(`/api/markets/${level}/${id}?config_id=${encodeURIComponent(configId)}`),
  scoreConfigs: () => request<ScoreConfig[]>("/api/score/configs"),
  scoreConfig: (id: string) => request<ScoreConfig>(`/api/score/configs/${id}`),
  saveScoreConfig: (cfg: ScoreConfig) => request<ScoreConfig>("/api/score/configs", { method: "POST", body: JSON.stringify(cfg) }),
  explain: (level: GeoLevel, id: string, config?: ScoreConfig, configId?: string) =>
    request<MarketScore>("/api/score/explain", {
      method: "POST",
      body: JSON.stringify({ geo_level: level, geo_id: id, config: config ?? null, config_id: configId ?? null }),
    }),
  rank: (req: RankingRequest) => request<RankingResponse>("/api/rank", { method: "POST", body: JSON.stringify(req) }),
  rankCsvUrl: () => `${BASE}/api/rank/export.csv`,
  mapLayer: (level: GeoLevel, opts: { config?: ScoreConfig; configId?: string; states?: string[] }) =>
    request<GeoJSON.FeatureCollection>(`/api/map/${level}`, {
      method: "POST",
      body: JSON.stringify({ config: opts.config ?? null, config_id: opts.configId ?? null, states: opts.states?.length ? opts.states : null }),
    }),
  financialDefaults: () => request<FinancialAssumptions>("/api/financial/defaults"),
  runFinancial: (a: FinancialAssumptions) => request<FinancialResult>("/api/financial/run", { method: "POST", body: JSON.stringify(a) }),
  scenarios: () => request<FinancialScenario[]>("/api/financial/scenarios"),
  saveScenario: (s: FinancialScenario) =>
    request<FinancialScenario>(`/api/financial/scenarios/${encodeURIComponent(s.id)}`, { method: "PUT", body: JSON.stringify(s) }),
  deleteScenario: (id: string) => request<void>(`/api/financial/scenarios/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

export async function downloadRankingCsv(req: RankingRequest) {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["X-Access-Token"] = token;
  const res = await fetch(api.rankCsvUrl(), { method: "POST", headers, body: JSON.stringify(req) });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `servemd_rankings_${req.geo_level}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
