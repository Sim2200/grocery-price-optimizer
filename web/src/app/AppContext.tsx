"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Health } from "../api";

// State that every page shares: backend health, watchlist alert count, and a
// counter that pages watch to refetch after data changes. It used to live in
// App.tsx; a context keeps the pages' props unchanged now that each page is a route.
interface AppState {
  health: Health | null;
  alertCount: number;
  backendError: string | null;
  demoMessage: string | null;
  setDemoMessage: (message: string | null) => void;
  dataVersion: number;
  refresh: () => void;
  loadDemo: () => Promise<void>;
}

const AppContext = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [alertCount, setAlertCount] = useState(0);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [demoMessage, setDemoMessage] = useState<string | null>(null);
  const [dataVersion, setDataVersion] = useState(0);
  const refresh = useCallback(() => setDataVersion((v) => v + 1), []);

  useEffect(() => {
    api.health().then(setHealth).catch((e: Error) => setBackendError(e.message));
  }, []);

  useEffect(() => {
    api
      .alerts()
      .then((a) => setAlertCount(a.length))
      .catch(() => setAlertCount(0));
  }, [dataVersion]);

  const loadDemo = useCallback(async () => {
    if (!window.confirm("Replace all saved receipts with the bundled SYNTHETIC sample data?")) return;
    const res = await api.loadDemo(true);
    setDemoMessage(`Loaded ${res.receipts_loaded} synthetic receipts.`);
    refresh();
  }, [refresh]);

  return (
    <AppContext.Provider
      value={{ health, alertCount, backendError, demoMessage, setDemoMessage, dataVersion, refresh, loadDemo }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
