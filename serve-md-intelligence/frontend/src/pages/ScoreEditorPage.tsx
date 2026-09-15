import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { MetricDef, ScoreConfig } from "../api/types";
import { useScoreConfig } from "../lib/scoreConfig";

export default function ScoreEditorPage() {
  const { config, setConfig, reset, dirty, markSaved } = useScoreConfig();
  const { data: registry } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const { data: saved = [] } = useQuery({ queryKey: ["scoreConfigs"], queryFn: api.scoreConfigs });
  const qc = useQueryClient();
  const [saveAs, setSaveAs] = useState("");
  const save = useMutation({
    mutationFn: (c: ScoreConfig) => api.saveScoreConfig(c),
    onSuccess: (c) => {
      markSaved(c);
      qc.invalidateQueries({ queryKey: ["scoreConfigs"] });
      qc.invalidateQueries({ queryKey: ["scoreConfig"] });
      qc.invalidateQueries({ queryKey: ["rank"] });
      qc.invalidateQueries({ queryKey: ["market"] });
    },
  });

  if (!config || !registry) return <p className="text-slate-500">Loading configuration…</p>;
  const totalPillar = Object.values(config.pillars).reduce((s, p) => s + p.weight, 0) || 1;
  const weightOf = (m: MetricDef) => config.metric_weights[m.id] ?? m.scoring_default;
  const dirOf = (m: MetricDef) => config.direction_overrides[m.id] ?? m.higher_is_better;

  const update = (patch: Partial<ScoreConfig>) => setConfig({ ...config, ...patch });

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-end gap-4">
        <div>
          <label className="label">Load saved config</label>
          <select
            className="input"
            value={`${config.id}@${config.version}`}
            onChange={async (e) => {
              const id = e.target.value.split("@")[0];
              const c = await api.scoreConfig(id);
              markSaved(c);
            }}
          >
            {saved.map((c) => (
              <option key={c.id} value={`${c.id}@${c.version}`}>
                {c.name} (v{c.version})
              </option>
            ))}
            {!saved.some((c) => c.id === config.id) && <option value={`${config.id}@${config.version}`}>{config.name}</option>}
          </select>
        </div>
        <div>
          <label className="label">Normalization</label>
          <select className="input" value={config.normalization} onChange={(e) => update({ normalization: e.target.value as ScoreConfig["normalization"] })}>
            <option value="percentile">Percentile rank</option>
            <option value="minmax">Min-max (2–98% winsorized)</option>
            <option value="zscore">Z-score (clipped ±3σ)</option>
          </select>
        </div>
        <div>
          <label className="label">Missing data</label>
          <select
            className="input"
            value={config.missing_metric_policy}
            onChange={(e) => update({ missing_metric_policy: e.target.value as ScoreConfig["missing_metric_policy"] })}
          >
            <option value="renormalize">Renormalize remaining weights</option>
            <option value="zero">Count as 0</option>
            <option value="exclude_market">Exclude market</option>
          </select>
        </div>
        <div className="w-32">
          <label className="label">Min coverage %</label>
          <input className="input" type="number" min={0} max={100} value={config.min_coverage_pct} onChange={(e) => update({ min_coverage_pct: Number(e.target.value) })} />
        </div>
        <div className="ml-auto flex items-end gap-2">
          {dirty && (
            <button className="btn-secondary" onClick={reset}>
              Discard edits
            </button>
          )}
          <div>
            <label className="label">Save as (id)</label>
            <input className="input w-40" placeholder={config.id} value={saveAs} onChange={(e) => setSaveAs(e.target.value)} />
          </div>
          <button
            className="btn"
            disabled={save.isPending}
            onClick={() => {
              const id = (saveAs || config.id).trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
              save.mutate({ ...config, id, name: saveAs ? saveAs : config.name });
            }}
          >
            Save new version
          </button>
        </div>
      </div>
      {save.isError && <p className="text-red-600">{String(save.error)}</p>}
      <p className="text-xs text-slate-500">
        Edits apply immediately (unsaved) to the Rankings, Map and market profiles. Saving creates a new immutable version so past
        rankings can be reproduced.
      </p>

      <div className="grid gap-4 lg:grid-cols-5">
        {Object.entries(config.pillars).map(([pid, p]) => (
          <div key={pid} className="card space-y-2">
            <div>
              <div className="flex items-baseline justify-between">
                <h2 className="font-semibold">{p.label}</h2>
                <span className="text-xs text-slate-500">{((p.weight / totalPillar) * 100).toFixed(0)}% of score</span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={p.weight}
                className="w-full"
                aria-label={`${p.label} weight`}
                onChange={(e) => update({ pillars: { ...config.pillars, [pid]: { ...p, weight: Number(e.target.value) } } })}
              />
              {p.description && <p className="text-xs text-slate-400">{p.description}</p>}
            </div>
            <div className="divide-y divide-slate-100">
              {registry.metrics
                .filter((m) => m.pillar === pid && m.higher_is_better !== null)
                .map((m) => (
                  <div key={m.id} className="py-1.5" title={m.description}>
                    <div className="flex items-center justify-between text-xs">
                      <span className={weightOf(m) === 0 ? "text-slate-400" : "text-slate-700"}>{m.label}</span>
                      <button
                        className={`rounded px-1 text-[10px] ${dirOf(m) ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}
                        title="Toggle direction: does a higher value help or hurt the market?"
                        onClick={() => update({ direction_overrides: { ...config.direction_overrides, [m.id]: !dirOf(m) } })}
                      >
                        {dirOf(m) ? "higher ↑ better" : "lower ↓ better"}
                      </button>
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="range"
                        min={0}
                        max={50}
                        step={1}
                        value={weightOf(m)}
                        className="flex-1"
                        aria-label={`${m.label} weight`}
                        onChange={(e) => update({ metric_weights: { ...config.metric_weights, [m.id]: Number(e.target.value) } })}
                      />
                      <span className="w-6 text-right text-xs tabular-nums">{weightOf(m)}</span>
                    </div>
                  </div>
                ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
