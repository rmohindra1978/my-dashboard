import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { GeoLevel, MetricReading } from "../api/types";
import ScoreBadge from "../components/ScoreBadge";
import { fmtMetric, fmtScore, scoreColor } from "../lib/format";
import { useScoreConfig } from "../lib/scoreConfig";

function Metric({ m }: { m: MetricReading }) {
  const pct = m.percentile;
  const good = m.higher_is_better === null ? null : m.higher_is_better ? pct : pct === null || pct === undefined ? null : 100 - pct;
  return (
    <div className="flex items-center gap-3 py-1.5 text-sm" title={`${m.source_name}${m.period ? ` · ${m.period}` : ""}`}>
      <span className="flex-1 text-slate-600">{m.label}</span>
      <span className="w-24 text-right font-medium tabular-nums">{fmtMetric(m.value, m.format, m.unit)}</span>
      <span className="w-20">
        {pct !== null && pct !== undefined && (
          <div className="h-1.5 w-full rounded bg-slate-100">
            <div className="h-1.5 rounded" style={{ width: `${pct}%`, background: good === null ? "#94a3b8" : scoreColor(good) }} />
          </div>
        )}
      </span>
      <span className="w-10 text-right text-xs text-slate-400">{pct === null || pct === undefined ? "" : `p${pct.toFixed(0)}`}</span>
    </div>
  );
}

export default function MarketPage() {
  const { level = "county", id = "" } = useParams<{ level: GeoLevel; id: string }>();
  const { config, dirty } = useScoreConfig();
  const profile = useQuery({ queryKey: ["market", level, id], queryFn: () => api.market(level as GeoLevel, id) });
  const live = useQuery({
    queryKey: ["explain", level, id, config],
    queryFn: () => api.explain(level as GeoLevel, id, config ?? undefined),
    enabled: dirty && !!config,
  });

  if (profile.isLoading) return <p className="text-slate-500">Loading market…</p>;
  if (profile.isError || !profile.data) return <p className="text-red-600">Market not found.</p>;
  const p = profile.data;
  const score = dirty && live.data ? live.data : p.score;
  const peerLabel = level === "county" || level === "state" ? "all US " + level + " markets" : `${level.toUpperCase()}s in ${p.geo.state_abbr}`;

  return (
    <div className="space-y-4">
      <div className="card flex items-center gap-6">
        <ScoreBadge score={score?.score} size="lg" />
        <div className="flex-1">
          <div className="text-xs uppercase tracking-wide text-slate-400">{p.geo.geo_level}</div>
          <h1 className="text-2xl font-bold">
            {p.geo.geo_level === "zcta" ? `ZIP ${p.geo.geo_id}` : p.geo.name}
            {p.geo.state_abbr && p.geo.geo_level !== "state" ? `, ${p.geo.state_abbr}` : ""}
          </h1>
          <div className="text-sm text-slate-500">
            {p.geo.cbsa_name && <span>{p.geo.cbsa_name} · </span>}
            {p.parent_county && (
              <Link className="text-brand-600 hover:underline" to={`/market/county/${p.parent_county.geo_id}`}>
                {p.parent_county.name}, {p.parent_county.state_abbr}
              </Link>
            )}
          </div>
        </div>
        {score && (
          <div className="text-right text-sm">
            <div>
              Rank <b>{score.rank ?? "—"}</b> of {score.rank_of ?? "—"} <span className="text-slate-400">({peerLabel})</span>
            </div>
            <div className="text-slate-500">
              Data coverage {score.coverage_pct.toFixed(0)}%{score.low_confidence && <span className="ml-1 text-amber-600">· low confidence</span>}
            </div>
            <div className="text-xs text-slate-400">
              config {score.config_id} v{score.config_version}
              {dirty && <span className="text-amber-600"> (unsaved edits applied)</span>}
            </div>
          </div>
        )}
        <Link to={`/financial?level=${level}&id=${id}`} className="btn">
          Model a clinic here
        </Link>
      </div>

      {score && (
        <div className="card">
          <h2 className="mb-2 font-semibold">Pillar scores</h2>
          <div className="grid grid-cols-5 gap-3">
            {score.pillar_scores.map((ps) => (
              <div key={ps.pillar} className="rounded-md border border-slate-100 p-3 text-center">
                <div className="text-xs text-slate-500">{ps.label}</div>
                <div className="text-2xl font-bold" style={{ color: scoreColor(ps.score) }}>
                  {fmtScore(ps.score)}
                </div>
                <div className="text-[10px] text-slate-400">weight {(ps.weight * 100).toFixed(0)}% · coverage {ps.coverage_pct.toFixed(0)}%</div>
              </div>
            ))}
          </div>
          {score.contributions.length > 0 && (
            <div className="mt-4 h-56">
              <ResponsiveContainer>
                <BarChart data={[...score.contributions].sort((a, b) => b.contribution - a.contribution).slice(0, 15)} layout="vertical" margin={{ left: 120 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" tickFormatter={(v) => v.toFixed(1)} />
                  <YAxis type="category" dataKey="label" width={120} tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: number) => `${v.toFixed(2)} pts`} />
                  <Bar dataKey="contribution" fill="#1e6fd9" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {p.panels.map((panel) => (
          <div key={panel.pillar} className="card">
            <h2 className="mb-1 font-semibold">{panel.label}</h2>
            <div className="divide-y divide-slate-100">
              {panel.metrics.length === 0 && <p className="text-sm text-slate-400">No metrics available at this geography.</p>}
              {panel.metrics.map((m) => (
                <Metric key={m.metric_id} m={m} />
              ))}
            </div>
          </div>
        ))}
      </div>

      {p.related.length > 0 && (
        <div className="card">
          <h2 className="mb-2 font-semibold">ZIP codes in this county</h2>
          <div className="flex flex-wrap gap-2">
            {p.related.map((r) => (
              <Link key={r.geo_id} to={`/market/zcta/${r.geo_id}`} className="rounded border border-slate-200 px-2 py-1 text-sm hover:bg-slate-50">
                {r.geo_id}
              </Link>
            ))}
          </div>
        </div>
      )}
      <p className="text-xs text-slate-400">
        Sources: {Object.entries(p.data_vintages).map(([s, v]) => `${s} (${v})`).join(" · ") || "n/a"}. Percentiles compare against {peerLabel}.
      </p>
    </div>
  );
}
