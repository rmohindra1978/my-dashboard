export function fmtMetric(value: number | null | undefined, format: string, unit?: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  switch (format) {
    case "integer":
      return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
    case "currency":
      return value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
    case "percent":
      return `${value.toFixed(1)}%`;
    case "decimal1":
      return value.toFixed(1) + (unit === "per_1000" ? " /1k" : "");
    default:
      return value.toFixed(2);
  }
}

export function fmtUsd(v: number | null | undefined, compact = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v < 0 ? "-" : "";
  const abs = Math.abs(v);
  if (compact && abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (compact && abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(0)}k`;
  return v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}%`;
}

export function fmtScore(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : v.toFixed(1);
}

export function scoreColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return "#cbd5e1";
  // red (0) -> amber (50) -> green (100)
  const stops: [number, string][] = [
    [0, "#b91c1c"],
    [25, "#ea580c"],
    [50, "#f59e0b"],
    [75, "#65a30d"],
    [100, "#15803d"],
  ];
  for (let i = 1; i < stops.length; i++) {
    if (score <= stops[i][0]) return stops[i][1];
  }
  return stops[stops.length - 1][1];
}

export const SCORE_STOPS: [number, string][] = [
  [0, "#b91c1c"],
  [25, "#ea580c"],
  [50, "#f59e0b"],
  [75, "#65a30d"],
  [100, "#15803d"],
];

export function titleize(id: string): string {
  return id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
