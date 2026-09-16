/* Shared "active score configuration" so edits in the Score Editor drive rankings, map and profiles. */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ScoreConfig } from "../api/types";

interface Ctx {
  config: ScoreConfig | null;
  savedId: string;
  dirty: boolean;
  /** true when consumers must post the active config (unsaved edits, or a saved non-default version) */
  custom: boolean;
  setConfig: (c: ScoreConfig) => void;
  reset: () => void;
  markSaved: (c: ScoreConfig) => void;
}

const ScoreConfigContext = createContext<Ctx | null>(null);

export function ScoreConfigProvider({ children }: { children: ReactNode }) {
  const { data: saved } = useQuery({ queryKey: ["scoreConfig", "default"], queryFn: () => api.scoreConfig("default") });
  const [config, setConfigState] = useState<ScoreConfig | null>(null);
  const [baseline, setBaseline] = useState<ScoreConfig | null>(null);

  useEffect(() => {
    if (saved && !config) {
      setConfigState(saved);
      setBaseline(saved);
    }
  }, [saved, config]);

  const value = useMemo<Ctx>(
    () => ({
      config,
      savedId: baseline?.id ?? "default",
      dirty: !!config && !!baseline && JSON.stringify(config) !== JSON.stringify(baseline),
      custom:
        !!config &&
        !!baseline &&
        (JSON.stringify(config) !== JSON.stringify(baseline) || baseline.id !== "default"),
      setConfig: setConfigState,
      reset: () => baseline && setConfigState(baseline),
      markSaved: (c) => {
        setBaseline(c);
        setConfigState(c);
      },
    }),
    [config, baseline],
  );
  return <ScoreConfigContext.Provider value={value}>{children}</ScoreConfigContext.Provider>;
}

export function useScoreConfig(): Ctx {
  const ctx = useContext(ScoreConfigContext);
  if (!ctx) throw new Error("useScoreConfig outside provider");
  return ctx;
}
