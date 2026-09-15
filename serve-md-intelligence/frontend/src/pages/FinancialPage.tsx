import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { AssumptionSection, FinancialAssumptions, FinancialResult, GeoLevel } from "../api/types";
import { fmtPct, fmtUsd, titleize } from "../lib/format";

const SECTIONS: { key: AssumptionSection; label: string }[] = [
  { key: "patients", label: "Patients & visits" },
  { key: "payer_mix", label: "Payer mix" },
  { key: "reimbursement", label: "Reimbursement" },
  { key: "providers", label: "Providers & compensation" },
  { key: "staffing", label: "Staffing" },
  { key: "facility", label: "Facility & rent" },
  { key: "diagnostics", label: "Diagnostics" },
  { key: "marketing", label: "Marketing" },
  { key: "overhead", label: "Overhead" },
  { key: "growth", label: "Growth" },
  { key: "capital", label: "Capital & returns" },
];

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function FinancialPage() {
  const [params] = useSearchParams();
  const level = params.get("level") as GeoLevel | null;
  const geoId = params.get("id");
  const qc = useQueryClient();
  const defaults = useQuery({ queryKey: ["financialDefaults"], queryFn: api.financialDefaults });
  const market = useQuery({ queryKey: ["market", level, geoId], queryFn: () => api.market(level!, geoId!), enabled: !!level && !!geoId });
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
  const [a, setA] = useState<FinancialAssumptions | null>(null);
  const [open, setOpen] = useState<AssumptionSection>("patients");
  const [scenarioName, setScenarioName] = useState("");

  useEffect(() => {
    if (defaults.data && !a) setA(defaults.data);
  }, [defaults.data, a]);

  const debounced = useDebounced(a, 250);
  const result = useQuery({
    queryKey: ["financialRun", debounced],
    queryFn: () => api.runFinancial(debounced!),
    enabled: !!debounced,
    placeholderData: (prev) => prev,
  });
  const save = useMutation({
    mutationFn: () =>
      api.saveScenario({
        id: scenarioName.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-"),
        name: scenarioName.trim(),
        geo_level: level,
        geo_id: geoId,
        assumptions: { ...a!, id: scenarioName.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-"), name: scenarioName.trim() },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scenarios"] }),
  });
  const del = useMutation({ mutationFn: (id: string) => api.deleteScenario(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["scenarios"] }) });

  const marketHint = useMemo(() => {
    const panels = market.data?.panels ?? [];
    const find = (id: string) => panels.flatMap((p) => p.metrics).find((m) => m.metric_id === id)?.value ?? null;
    return { benes: find("medicare_benes_total"), pop65: find("pop_65_plus"), pcp: find("pcp_per_1000_65plus"), ma: find("ma_penetration_pct") };
  }, [market.data]);

  if (!a) return <p className="text-slate-500">Loading assumptions…</p>;
  const r = result.data;
  const setField = (section: AssumptionSection, key: string, value: number | boolean) =>
    setA({ ...a, [section]: { ...a[section], [key]: value } });

  return (
    <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
      {/* ---------------------------------------------------------------- assumptions */}
      <div className="space-y-3">
        <div className="card">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Assumptions</h2>
            <button className="btn-secondary text-xs" onClick={() => setA(defaults.data!)}>
              Reset defaults
            </button>
          </div>
          {market.data && (
            <div className="mt-2 rounded bg-brand-50 p-2 text-xs text-brand-900">
              Modeling for{" "}
              <Link className="font-semibold underline" to={`/market/${level}/${geoId}`}>
                {market.data.geo.geo_level === "zcta" ? `ZIP ${market.data.geo.geo_id}` : market.data.geo.name}, {market.data.geo.state_abbr}
              </Link>
              <div className="mt-1 grid grid-cols-2 gap-x-3 text-[11px]">
                <span>Medicare benes: {marketHint.benes?.toLocaleString() ?? "—"}</span>
                <span>Pop 65+: {marketHint.pop65?.toLocaleString() ?? "—"}</span>
                <span>MA penetration: {fmtPct(marketHint.ma)}</span>
                <span>PCPs /1k 65+: {marketHint.pcp?.toFixed(1) ?? "—"}</span>
              </div>
              {marketHint.ma !== null && a.payer_mix.ma_pct !== Math.round(marketHint.ma) && (
                <button
                  className="mt-1 text-[11px] underline"
                  onClick={() => setA({ ...a, payer_mix: { ...a.payer_mix, ma_pct: Math.round(marketHint.ma!), ffs_pct: 100 - Math.round(marketHint.ma!) } })}
                >
                  Apply market MA penetration ({Math.round(marketHint.ma)}%) to payer mix
                </button>
              )}
            </div>
          )}
          <div className="mt-2">
            <label className="label">Model years</label>
            <input className="input w-24" type="number" min={1} max={10} value={a.model_years} onChange={(e) => setA({ ...a, model_years: Number(e.target.value) })} />
          </div>
        </div>
        {SECTIONS.map((s) => (
          <div key={s.key} className="card p-0">
            <button className="flex w-full items-center justify-between px-4 py-2 text-left text-sm font-semibold" onClick={() => setOpen(open === s.key ? ("" as AssumptionSection) : s.key)}>
              {s.label}
              <span className="text-slate-400">{open === s.key ? "−" : "+"}</span>
            </button>
            {open === s.key && (
              <div className="grid grid-cols-2 gap-2 border-t border-slate-100 px-4 py-3">
                {Object.entries(a[s.key]).map(([k, v]) => (
                  <label key={k} className="text-xs">
                    <span className="block truncate text-slate-500" title={k}>
                      {titleize(k)}
                    </span>
                    {typeof v === "boolean" ? (
                      <input type="checkbox" checked={v} onChange={(e) => setField(s.key, k, e.target.checked)} />
                    ) : (
                      <input className="input" type="number" step="any" value={v} onChange={(e) => setField(s.key, k, Number(e.target.value))} />
                    )}
                  </label>
                ))}
              </div>
            )}
          </div>
        ))}
        <div className="card space-y-2">
          <h3 className="text-sm font-semibold">Scenarios</h3>
          <div className="flex gap-1">
            <input className="input" placeholder="Scenario name" value={scenarioName} onChange={(e) => setScenarioName(e.target.value)} />
            <button className="btn" disabled={!scenarioName.trim() || save.isPending} onClick={() => save.mutate()}>
              Save
            </button>
          </div>
          <ul className="divide-y divide-slate-100 text-sm">
            {scenarios.data?.map((s) => (
              <li key={s.id} className="flex items-center justify-between py-1">
                <button className="text-left hover:text-brand-600" onClick={() => setA(s.assumptions)}>
                  {s.name}
                  {s.geo_id && <span className="ml-1 text-xs text-slate-400">({s.geo_level} {s.geo_id})</span>}
                </button>
                <button className="text-xs text-slate-400 hover:text-red-600" onClick={() => del.mutate(s.id)}>
                  delete
                </button>
              </li>
            ))}
            {scenarios.data?.length === 0 && <li className="py-1 text-xs text-slate-400">No saved scenarios yet.</li>}
          </ul>
        </div>
      </div>

      {/* ---------------------------------------------------------------- outputs */}
      <div className="space-y-4">
        {result.isError && <p className="text-red-600">{String(result.error)}</p>}
        {r && <Outputs r={r} />}
      </div>
    </div>
  );
}

function Kpi({ label, value, sub, warn }: { label: string; value: string; sub?: string; warn?: boolean }) {
  return (
    <div className="rounded-md border border-slate-100 p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`text-xl font-bold ${warn ? "text-red-600" : "text-slate-800"}`}>{value}</div>
      {sub && <div className="text-[11px] text-slate-400">{sub}</div>}
    </div>
  );
}

function Outputs({ r }: { r: FinancialResult }) {
  const last = r.annual[r.annual.length - 1];
  const monthly = r.monthly.map((m) => ({ ...m, month: m.month }));
  const streams = Object.keys(last.revenue_by_stream);
  const cats = Object.keys(last.opex_by_category);
  const palette = ["#1e6fd9", "#15803d", "#f59e0b", "#7c3aed", "#0891b2", "#b91c1c"];
  return (
    <>
      <div className="card">
        <div className="grid grid-cols-4 gap-3 xl:grid-cols-8">
          <Kpi label={`Year ${last.year} revenue`} value={fmtUsd(last.revenue)} sub={`${fmtUsd(r.total_revenue)} cumulative`} />
          <Kpi label={`Year ${last.year} EBITDA`} value={fmtUsd(last.ebitda)} sub={`${fmtUsd(r.total_ebitda)} cumulative`} warn={last.ebitda < 0} />
          <Kpi label="EBITDA margin (final yr)" value={fmtPct(r.ebitda_margin_pct_final_year)} warn={(r.ebitda_margin_pct_final_year ?? 0) < 0} />
          <Kpi label="EBITDA break-even" value={r.break_even_month ? `Month ${r.break_even_month}` : "Not reached"} warn={!r.break_even_month} />
          <Kpi label="Peak cash requirement" value={fmtUsd(r.peak_cash_requirement)} sub={`incl. ${fmtUsd(r.initial_investment)} initial`} />
          <Kpi label="Cash payback" value={r.cumulative_break_even_month ? `Month ${r.cumulative_break_even_month}` : "Not reached"} />
          <Kpi label="ROI" value={fmtPct(r.roi_pct, 0)} sub="incl. terminal value" warn={(r.roi_pct ?? 0) < 0} />
          <Kpi label="IRR" value={fmtPct(r.irr_pct)} sub={`NPV ${fmtUsd(r.npv)}`} warn={(r.irr_pct ?? 0) < 0} />
        </div>
        {r.warnings.length > 0 && (
          <ul className="mt-3 space-y-1 text-xs text-amber-700">
            {r.warnings.map((w, i) => (
              <li key={i}>⚠ {w}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <div className="card h-72">
          <h3 className="text-sm font-semibold">Monthly revenue vs. EBITDA</h3>
          <ResponsiveContainer height="90%">
            <LineChart data={monthly}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" tick={{ fontSize: 10 }} />
              <YAxis tickFormatter={(v) => fmtUsd(v)} tick={{ fontSize: 10 }} width={60} />
              <Tooltip formatter={(v: number) => fmtUsd(v, false)} labelFormatter={(l) => `Month ${l}`} />
              <Legend />
              <Line type="monotone" dataKey="revenue_total" name="Revenue" stroke="#1e6fd9" dot={false} />
              <Line type="monotone" dataKey="ebitda" name="EBITDA" stroke="#15803d" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="card h-72">
          <h3 className="text-sm font-semibold">Cumulative cash (J-curve)</h3>
          <ResponsiveContainer height="90%">
            <AreaChart data={monthly}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" tick={{ fontSize: 10 }} />
              <YAxis tickFormatter={(v) => fmtUsd(v)} tick={{ fontSize: 10 }} width={60} />
              <Tooltip formatter={(v: number) => fmtUsd(v, false)} labelFormatter={(l) => `Month ${l}`} />
              <Area type="monotone" dataKey="cumulative_cash" name="Cumulative cash" stroke="#7c3aed" fill="#ede9fe" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="card h-72">
          <h3 className="text-sm font-semibold">Active patients & provider FTE</h3>
          <ResponsiveContainer height="90%">
            <LineChart data={monthly}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="l" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 10 }} />
              <Tooltip labelFormatter={(l) => `Month ${l}`} />
              <Legend />
              <Line yAxisId="l" type="monotone" dataKey="active_patients" name="Active patients" stroke="#1e6fd9" dot={false} />
              <Line yAxisId="r" type="stepAfter" dataKey="provider_fte" name="Provider FTE" stroke="#f59e0b" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="card h-72">
          <h3 className="text-sm font-semibold">Annual revenue by stream</h3>
          <ResponsiveContainer height="90%">
            <BarChart data={r.annual.map((y) => ({ year: `Y${y.year}`, ...y.revenue_by_stream }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="year" />
              <YAxis tickFormatter={(v) => fmtUsd(v)} tick={{ fontSize: 10 }} width={60} />
              <Tooltip formatter={(v: number) => fmtUsd(v, false)} />
              <Legend />
              {streams.map((s, i) => (
                <Bar key={s} dataKey={s} stackId="rev" name={titleize(s)} fill={palette[i % palette.length]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2 text-left">Line</th>
              {r.annual.map((y) => (
                <th key={y.year} className="px-3 py-2 text-right">
                  Year {y.year}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 tabular-nums">
            <Row label="Ending patients" vals={r.annual.map((y) => y.ending_patients.toLocaleString("en-US", { maximumFractionDigits: 0 }))} />
            <Row label="Visits" vals={r.annual.map((y) => y.visits.toLocaleString("en-US", { maximumFractionDigits: 0 }))} />
            {streams.map((s) => (
              <Row key={s} label={`  ${titleize(s)}`} vals={r.annual.map((y) => fmtUsd(y.revenue_by_stream[s], false))} muted />
            ))}
            <Row label="Total revenue" vals={r.annual.map((y) => fmtUsd(y.revenue, false))} bold />
            {cats.map((c) => (
              <Row key={c} label={`  ${titleize(c)}`} vals={r.annual.map((y) => fmtUsd(-y.opex_by_category[c], false))} muted />
            ))}
            <Row label="Total operating expenses" vals={r.annual.map((y) => fmtUsd(-y.opex, false))} bold />
            <Row label="EBITDA" vals={r.annual.map((y) => fmtUsd(y.ebitda, false))} bold highlight />
            <Row label="EBITDA margin" vals={r.annual.map((y) => fmtPct(y.ebitda_margin_pct))} />
            <Row label="Capex" vals={r.annual.map((y) => fmtUsd(-y.capex, false))} />
            <Row label="Cash flow" vals={r.annual.map((y) => fmtUsd(y.cash_flow, false))} />
            <Row label="Cumulative cash" vals={r.annual.map((y) => fmtUsd(y.cumulative_cash, false))} bold />
          </tbody>
        </table>
      </div>
    </>
  );
}

function Row({ label, vals, bold, muted, highlight }: { label: string; vals: string[]; bold?: boolean; muted?: boolean; highlight?: boolean }) {
  return (
    <tr className={`${highlight ? "bg-brand-50" : ""} ${bold ? "font-semibold" : ""} ${muted ? "text-slate-500" : ""}`}>
      <td className="whitespace-pre px-3 py-1.5">{label}</td>
      {vals.map((v, i) => (
        <td key={i} className="px-3 py-1.5 text-right">
          {v}
        </td>
      ))}
    </tr>
  );
}
