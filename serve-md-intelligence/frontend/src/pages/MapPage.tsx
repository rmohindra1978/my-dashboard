import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import maplibregl, { type ExpressionSpecification } from "maplibre-gl";
import { api } from "../api/client";
import type { GeoLevel } from "../api/types";
import { SCORE_STOPS, fmtScore } from "../lib/format";
import { useScoreConfig } from "../lib/scoreConfig";

const BASEMAP = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const SRC = "markets";

export default function MapPage() {
  const { config, dirty } = useScoreConfig();
  const [level, setLevel] = useState<GeoLevel>("county");
  const [states, setStates] = useState<string[]>([]);
  const [minScore, setMinScore] = useState(0);
  const { data: stateList = [] } = useQuery({ queryKey: ["states"], queryFn: api.states });
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const navigate = useNavigate();
  const [ready, setReady] = useState(false);
  const [hover, setHover] = useState<Record<string, unknown> | null>(null);

  const layer = useQuery({
    queryKey: ["map", level, states, dirty ? config : "default"],
    queryFn: () => api.mapLayer(level, dirty && config ? { config, states } : { configId: "default", states }),
  });

  useEffect(() => {
    if (!container.current || map.current) return;
    const m = new maplibregl.Map({ container: container.current, style: BASEMAP, center: [-98, 38.5], zoom: 3.6, attributionControl: false });
    m.addControl(new maplibregl.NavigationControl(), "top-right");
    m.addControl(new maplibregl.AttributionControl({ compact: true }));
    m.on("load", () => setReady(true));
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
  }, []);

  const fillColor = useMemo<ExpressionSpecification>(
    () => ["case", ["==", ["typeof", ["get", "score"]], "number"], ["interpolate", ["linear"], ["get", "score"], ...SCORE_STOPS.flat()], "#cbd5e1"],
    [],
  );

  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !layer.data) return;
    const data = layer.data;
    const isPoint = data.features[0]?.geometry.type === "Point";
    const existing = m.getSource(SRC) as maplibregl.GeoJSONSource | undefined;
    if (existing) {
      existing.setData(data);
    } else {
      m.addSource(SRC, { type: "geojson", data, promoteId: "geo_id" });
    }
    for (const id of ["fill", "line", "pts"]) if (m.getLayer(id)) m.removeLayer(id);
    const filter: ExpressionSpecification = [">=", ["coalesce", ["get", "score"], -1], minScore];
    if (isPoint) {
      m.addLayer({
        id: "pts", type: "circle", source: SRC, filter,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 6, 8, 14],
          "circle-color": fillColor, "circle-stroke-color": "#fff", "circle-stroke-width": 1, "circle-opacity": 0.9,
        },
      });
    } else {
      m.addLayer({
        id: "fill", type: "fill", source: SRC, filter,
        paint: { "fill-color": fillColor, "fill-opacity": ["case", ["boolean", ["feature-state", "hover"], false], 0.95, 0.72] },
      });
      m.addLayer({ id: "line", type: "line", source: SRC, paint: { "line-color": "#ffffff", "line-width": 0.5 } });
    }
    const target = isPoint ? "pts" : "fill";
    let hovered: string | number | undefined;
    m.on("mousemove", target, (e) => {
      const f = e.features?.[0];
      if (!f) return;
      m.getCanvas().style.cursor = "pointer";
      if (hovered !== undefined) m.setFeatureState({ source: SRC, id: hovered }, { hover: false });
      hovered = f.id;
      if (hovered !== undefined) m.setFeatureState({ source: SRC, id: hovered }, { hover: true });
      setHover(f.properties as Record<string, unknown>);
    });
    m.on("mouseleave", target, () => {
      m.getCanvas().style.cursor = "";
      if (hovered !== undefined) m.setFeatureState({ source: SRC, id: hovered }, { hover: false });
      hovered = undefined;
      setHover(null);
    });
    m.on("click", target, (e) => {
      const p = e.features?.[0]?.properties;
      if (p?.geo_id) navigate(`/market/${level}/${p.geo_id}`);
    });
    if (states.length && data.features.length) {
      const b = new maplibregl.LngLatBounds();
      for (const f of data.features) {
        if (f.geometry.type === "Point") b.extend(f.geometry.coordinates as [number, number]);
        else if (f.geometry.type === "Polygon") f.geometry.coordinates[0].forEach((c) => b.extend(c as [number, number]));
        else if (f.geometry.type === "MultiPolygon") f.geometry.coordinates.forEach((poly) => poly[0].forEach((c) => b.extend(c as [number, number])));
      }
      if (!b.isEmpty()) m.fitBounds(b, { padding: 40, duration: 600 });
    }
  }, [ready, layer.data, minScore, fillColor, level, navigate, states.length]);

  return (
    <div className="space-y-3">
      <div className="card flex flex-wrap items-end gap-4">
        <div>
          <label className="label">Geography</label>
          <select className="input" value={level} onChange={(e) => setLevel(e.target.value as GeoLevel)}>
            <option value="county">Counties</option>
            <option value="zcta">ZIP codes (ZCTA)</option>
            <option value="place">Cities / places</option>
          </select>
        </div>
        <div className="min-w-48">
          <label className="label">States</label>
          <select className="input" multiple size={3} value={states} onChange={(e) => setStates(Array.from(e.target.selectedOptions).map((o) => o.value))}>
            {stateList.map((s) => (
              <option key={s.abbr} value={s.abbr}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <div className="w-56">
          <label className="label">Min score: {minScore}</label>
          <input type="range" min={0} max={100} value={minScore} className="w-full" onChange={(e) => setMinScore(Number(e.target.value))} />
        </div>
        <div className="ml-auto text-sm text-slate-500">
          {dirty && <span className="mr-2 rounded bg-amber-50 px-2 py-1 text-amber-700">using unsaved score edits</span>}
          {layer.data ? `${layer.data.features.length.toLocaleString()} features` : layer.isLoading ? "Loading…" : ""}
        </div>
      </div>
      <div className="relative">
        <div ref={container} className="h-[calc(100vh-240px)] w-full overflow-hidden rounded-lg border border-slate-200" data-testid="map" />
        <div className="absolute bottom-3 left-3 rounded bg-white/90 p-2 text-xs shadow">
          <div className="mb-1 font-semibold">SERVE MD Score</div>
          <div className="flex h-3 w-40 overflow-hidden rounded">
            {SCORE_STOPS.map(([v, c]) => (
              <div key={v} className="flex-1" style={{ background: c }} />
            ))}
          </div>
          <div className="flex justify-between text-[10px] text-slate-500">
            <span>0</span>
            <span>50</span>
            <span>100</span>
          </div>
        </div>
        {hover && (
          <div className="absolute right-3 top-3 w-64 rounded bg-white/95 p-3 text-xs shadow">
            <div className="text-sm font-semibold">
              {level === "zcta" ? `ZIP ${hover.geo_id}` : String(hover.name)}
              {hover.state_abbr ? `, ${hover.state_abbr}` : ""}
            </div>
            <div>
              Score <b>{fmtScore(hover.score as number)}</b> · Rank {String(hover.rank ?? "—")}
            </div>
            {"pop_65_plus" in hover && <div>Pop 65+: {Number(hover.pop_65_plus).toLocaleString()}</div>}
            {"ma_penetration_pct" in hover && hover.ma_penetration_pct != null && <div>MA penetration: {Number(hover.ma_penetration_pct).toFixed(1)}%</div>}
            {"pcp_per_1000_65plus" in hover && hover.pcp_per_1000_65plus != null && <div>PCPs per 1k 65+: {Number(hover.pcp_per_1000_65plus).toFixed(1)}</div>}
            <div className="mt-1 text-slate-400">Click to open profile</div>
          </div>
        )}
      </div>
    </div>
  );
}
