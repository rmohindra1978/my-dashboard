import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import SearchBox from "../components/SearchBox";
import { fmtScore, scoreColor } from "../lib/format";

export default function HomePage() {
  const { data } = useQuery({
    queryKey: ["rank", "home"],
    queryFn: () =>
      api.rank({ geo_level: "county", config_id: "default", filters: [], limit: 10, offset: 0, include_contributions: false, sort_by: "score", descending: true }),
  });
  return (
    <div className="mx-auto max-w-4xl space-y-8 py-8">
      <div className="text-center">
        <h1 className="text-3xl font-bold text-slate-800">Where should SERVE MD open next?</h1>
        <p className="mt-2 text-slate-500">
          Search any US city, ZIP code or county for Medicare demand, demographics, competition, provider supply and economics.
        </p>
      </div>
      <SearchBox autoFocus large />
      <div className="card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">Top counties by SERVE MD Score</h2>
          <Link to="/rankings" className="text-sm text-brand-600 hover:underline">
            Full rankings →
          </Link>
        </div>
        <ol className="divide-y divide-slate-100">
          {data?.rows.map((r) => (
            <li key={r.geo_id} className="flex items-center gap-3 py-2 text-sm">
              <span className="w-6 text-right text-slate-400">{r.rank}</span>
              <Link to={`/market/county/${r.geo_id}`} className="flex-1 font-medium text-slate-800 hover:text-brand-600">
                {r.name}, {r.state_abbr}
              </Link>
              <span className="rounded px-2 py-0.5 text-xs font-semibold text-white" style={{ background: scoreColor(r.score) }}>
                {fmtScore(r.score)}
              </span>
            </li>
          ))}
          {!data && <li className="py-2 text-sm text-slate-400">Loading…</li>}
        </ol>
      </div>
    </div>
  );
}
