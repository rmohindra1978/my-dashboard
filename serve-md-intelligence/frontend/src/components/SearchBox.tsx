import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export default function SearchBox({ autoFocus = false, large = false }: { autoFocus?: boolean; large?: boolean }) {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 200);
    return () => clearTimeout(t);
  }, [q]);

  const { data: results = [] } = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.search(debounced),
    enabled: debounced.length >= 2,
  });

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const go = (i: number) => {
    const r = results[i];
    if (!r) return;
    setOpen(false);
    setQ("");
    navigate(`/market/${r.geo_level}/${r.geo_id}`);
  };

  return (
    <div ref={box} className="relative">
      <input
        autoFocus={autoFocus}
        className={`input ${large ? "py-3 text-lg" : ""}`}
        placeholder="Search a city, ZIP code or county…  e.g. Phoenix, 85004, Maricopa County AZ"
        value={q}
        aria-label="Search markets"
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, results.length - 1));
          else if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
          else if (e.key === "Enter") go(active);
          else if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && debounced.length >= 2 && (
        <ul className="absolute z-20 mt-1 max-h-80 w-full overflow-auto rounded-md border border-slate-200 bg-white shadow-lg" role="listbox">
          {results.length === 0 && <li className="px-3 py-2 text-sm text-slate-500">No matches</li>}
          {results.map((r, i) => (
            <li
              key={`${r.geo_level}-${r.geo_id}`}
              role="option"
              aria-selected={i === active}
              className={`flex cursor-pointer items-center justify-between px-3 py-2 text-sm ${i === active ? "bg-brand-50" : "hover:bg-slate-50"}`}
              onMouseEnter={() => setActive(i)}
              onMouseDown={() => go(i)}
            >
              <span>{r.display}</span>
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-500">{r.geo_level}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
