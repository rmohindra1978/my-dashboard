import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api/client";
import SearchBox from "./components/SearchBox";
import MarketPage from "./pages/MarketPage";
import RankingsPage from "./pages/RankingsPage";
import ScoreEditorPage from "./pages/ScoreEditorPage";
import FinancialPage from "./pages/FinancialPage";
import MapPage from "./pages/MapPage";
import HomePage from "./pages/HomePage";
import { useScoreConfig } from "./lib/scoreConfig";

const nav = [
  { to: "/", label: "Search" },
  { to: "/rankings", label: "Rankings" },
  { to: "/map", label: "Map" },
  { to: "/score", label: "Score Editor" },
  { to: "/financial", label: "Financial Model" },
];

export default function App() {
  const { data: health, isError } = useQuery({ queryKey: ["health"], queryFn: api.health, retry: false });
  const { dirty } = useScoreConfig();
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-screen-2xl items-center gap-6 px-4 py-2">
          <NavLink to="/" className="flex items-baseline gap-2">
            <span className="text-lg font-bold text-brand-700">SERVE MD</span>
            <span className="text-sm font-medium text-slate-500">Intelligence</span>
          </NavLink>
          <nav className="flex gap-1">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === "/"}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm font-medium ${isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100"}`
                }
              >
                {n.label}
                {n.to === "/score" && dirty && <span className="ml-1 text-amber-500">•</span>}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto w-96">
            <SearchBox />
          </div>
          <div className="text-xs text-slate-500" data-testid="health">
            {isError ? (
              <span className="text-red-600">API offline</span>
            ) : health ? (
              `${health.geo_units.toLocaleString()} markets · ${health.metric_rows.toLocaleString()} observations`
            ) : (
              "…"
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-screen-2xl flex-1 px-4 py-4">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/market/:level/:id" element={<MarketPage />} />
          <Route path="/rankings" element={<RankingsPage />} />
          <Route path="/map" element={<MapPage />} />
          <Route path="/score" element={<ScoreEditorPage />} />
          <Route path="/financial" element={<FinancialPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <footer className="border-t border-slate-200 py-2 text-center text-xs text-slate-400">
        Public aggregate data only (Census, CMS, HRSA, CDC). No PHI. Scores are relative percentiles, not forecasts.
      </footer>
    </div>
  );
}
