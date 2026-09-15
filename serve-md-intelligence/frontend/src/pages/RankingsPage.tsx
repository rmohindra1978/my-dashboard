import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, downloadRankingCsv } from "../api/client";
import type { GeoLevel, MetricFilter, RankingRequest } from "../api/types";
import { fmtMetric, fmtScore, scoreColor } from "../lib/format";
import { useScoreConfig } from "../lib/scoreConfig";

const TABLE_COLS: { id: string; label: string; format: string }[] = [
  { id: "pop_65_plus", label: "Pop 65+", format: "integer" },
  { id: "pct_65_plus", label: "% 65+", format: "percent" },
  { id: "medicare_benes_total", label: "Medicare benes", format: "integer" },
  { id: "ma_penetration_pct", label: "MA %", format: "percent" },
  { id: "pcp_per_1000_65plus", label: "PCPs /1k 65+", format: "decimal1" },
  { id: "median_household_income", label: "HH income", format: "currency" },
];

export default function RankingsPage() {
  const { config, dirty } = useScoreConfig();
  const [level, setLevel] = useState<GeoLevel>("county");
  const [states, setStates] = useState<string[]>([]);
  const [filters, setFilters] = useState<MetricFilter[]>([]);
  const [sortBy, setSortBy] = useState("score");
  const [desc, setDesc] = useState(true);
  const [page, setPage] = useState(0);
  const pageSize = 50;
  const { data: stateList = [] } = useQuery({ queryKey: ["states"], queryFn: api.states });
  const { data: registry } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });

  const req = useMemo<RankingRequest>(
    () => ({
      geo_level: level,
      config_id: dirty ? null : "default",
      config: dirty ? config : null,
      states: states.length ? states : null,
      filters,
      limit: pageSize,
      offset: page * pageSize,
      include_contributions: false,
      sort_by: sortBy,
      descending: desc,
    }),
    [level, states, filters, sortBy, desc, page, dirty, config],
  );
  const { data, isFetching, error } = useQuery({ queryKey: ["rank", req], queryFn: () => api.rank(req), placeholderData: (prev) => prev });

  const pillars = config ? Object.entries(config.pillars) : [];
  const toggleSort = (col: string) => {
    if (sortBy === col) setDesc(!desc);
    else {
      setSortBy(col);
      setDesc(true);
    }
    setPage(0);
  };
  const th = (col: string, label: string, right = true) => (
    <th key={col} className={`cursor-pointer whitespace-nowrap px-2 py-2 ${right ? "text-right" : "text-left"} hover:text-brand-600`} onClick={() => toggleSort(col)}>
      {label}
      {sortBy === col && <span className="ml-1 text-brand-600">{desc ? "▼" : "▲"}</span>}
    </th>
  );

  return (
    <div className="space-y-3">
      <div className="card flex flex-wrap items-end gap-4">
        <div>
          <label className="label">Geography</label>
          <select
            className="input"
            value={level}
            onChange={(e) => {
              setLevel(e.target.value as GeoLevel);
              setPage(0);
            }}
          >
            <option value="county">Counties</option>
            <option value="zcta">ZIP codes (ZCTA)</option>
            <option value="place">Cities / places</option>
            <option value="state">States</option>
          </select>
        </div>
        <div className="min-w-48">
          <label className="label">States</label>
          <select
            className="input"
            multiple
            size={3}
            value={states}
            onChange={(e) => {
              setStates(Array.from(e.target.selectedOptions).map((o) => o.value));
              setPage(0);
            }}
          >
            {stateList.map((s) => (
              <option key={s.abbr} value={s.abbr}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <FilterEditor filters={filters} onChange={(f) => { setFilters(f); setPage(0); }} metrics={registry?.metrics.map((m) => ({ id: m.id, label: m.label })) ?? []} />
        <div className="ml-auto flex items-center gap-2 text-sm text-slate-500">
          {dirty && <span className="rounded bg-amber-50 px-2 py-1 text-amber-700">using unsaved score edits</span>}
          {data && (
            <span>
              {data.total.toLocaleString()} markets · {data.computed_in_ms.toFixed(0)} ms
            </span>
          )}
          <button className="btn-secondary" onClick={() => downloadRankingCsv(req)} disabled={!data}>
            Export CSV
          </button>
        </div>
      </div>

      {error && <p className="text-red-600">{String(error)}</p>}
      <div className={`card overflow-x-auto p-0 ${isFetching ? "opacity-70" : ""}`}>
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-2 py-2 text-right">#</th>
              <th className="px-2 py-2 text-left">Market</th>
              {th("score", "Score")}
              {pillars.map(([id, p]) => th(id, p.label))}
              {TABLE_COLS.map((c) => th(c.id, c.label))}
              <th className="px-2 py-2 text-right">Coverage</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data?.rows.map((r) => (
              <tr key={r.geo_id} className="hover:bg-slate-50">
                <td className="px-2 py-1.5 text-right text-slate-400">{r.rank}</td>
                <td className="px-2 py-1.5">
                  <Link to={`/market/${level}/${r.geo_id}`} className="font-medium hover:text-brand-600">
                    {level === "zcta" ? `ZIP ${r.geo_id}` : r.name}
                    {r.state_abbr && level !== "state" ? `, ${r.state_abbr}` : ""}
                  </Link>
                  {r.low_confidence && <span className="ml-1 text-xs text-amber-600" title="Low data coverage">!</span>}
                </td>
                <td className="px-2 py-1.5 text-right">
                  <span className="rounded px-1.5 py-0.5 text-xs font-semibold text-white" style={{ background: scoreColor(r.score) }}>
                    {fmtScore(r.score)}
                  </span>
                </td>
                {r.pillar_scores.map((p) => (
                  <td key={p.pillar} className="px-2 py-1.5 text-right tabular-nums" style={{ color: scoreColor(p.score) }}>
                    {fmtScore(p.score)}
                  </td>
                ))}
                {TABLE_COLS.map((c) => (
                  <td key={c.id} className="px-2 py-1.5 text-right tabular-nums text-slate-600">
                    {fmtMetric(r.metrics[c.id], c.format)}
                  </td>
                ))}
                <td className="px-2 py-1.5 text-right text-slate-400">{r.coverage_pct.toFixed(0)}%</td>
              </tr>
            ))}
            {data && data.rows.length === 0 && (
              <tr>
                <td colSpan={20} className="px-2 py-6 text-center text-slate-400">
                  No markets match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {data && data.total > pageSize && (
        <div className="flex items-center justify-center gap-3 text-sm">
          <button className="btn-secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>
            ← Prev
          </button>
          <span>
            Page {page + 1} of {Math.ceil(data.total / pageSize)}
          </span>
          <button className="btn-secondary" disabled={(page + 1) * pageSize >= data.total} onClick={() => setPage(page + 1)}>
            Next →
          </button>
        </div>
      )}
    </div>
  );
}

function FilterEditor({
  filters,
  onChange,
  metrics,
}: {
  filters: MetricFilter[];
  onChange: (f: MetricFilter[]) => void;
  metrics: { id: string; label: string }[];
}) {
  const [metric, setMetric] = useState("pop_65_plus");
  const [op, setOp] = useState<MetricFilter["op"]>("gte");
  const [value, setValue] = useState("");
  return (
    <div>
      <label className="label">Filters</label>
      <div className="flex items-center gap-1">
        <select className="input w-44" value={metric} onChange={(e) => setMetric(e.target.value)}>
          {metrics.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
        <select className="input w-16" value={op} onChange={(e) => setOp(e.target.value as MetricFilter["op"])}>
          <option value="gte">≥</option>
          <option value="lte">≤</option>
        </select>
        <input className="input w-28" type="number" value={value} onChange={(e) => setValue(e.target.value)} placeholder="value" />
        <button
          className="btn-secondary"
          disabled={value === ""}
          onClick={() => {
            onChange([...filters, { metric_id: metric, op, value: Number(value) }]);
            setValue("");
          }}
        >
          Add
        </button>
      </div>
      {filters.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {filters.map((f, i) => (
            <span key={i} className="flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-xs">
              {metrics.find((m) => m.id === f.metric_id)?.label ?? f.metric_id} {f.op === "gte" ? "≥" : "≤"} {f.value}
              <button className="text-slate-400 hover:text-red-600" onClick={() => onChange(filters.filter((_, j) => j !== i))}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
