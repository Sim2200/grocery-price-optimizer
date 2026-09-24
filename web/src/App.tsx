import { Suspense, lazy, useCallback, useEffect, useState } from "react";
import { api, type Health } from "./api";
import UploadPage from "./pages/UploadPage";
import ReceiptsPage from "./pages/ReceiptsPage";
import PlanPage from "./pages/PlanPage";

// The charts library is large, so the Prices page is loaded only when opened.
const PricesPage = lazy(() => import("./pages/PricesPage"));
const InsightsPage = lazy(() => import("./pages/InsightsPage"));

const TABS = [
  { id: "upload", label: "Upload receipts" },
  { id: "receipts", label: "Receipts" },
  { id: "prices", label: "Prices" },
  { id: "plan", label: "Plan my trip" },
  { id: "insights", label: "Insights" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function tabFromHash(): TabId {
  const hash = window.location.hash.replace("#", "");
  return TABS.some((t) => t.id === hash) ? (hash as TabId) : "upload";
}

export default function App() {
  const [tab, setTab] = useState<TabId>(tabFromHash);
  const [health, setHealth] = useState<Health | null>(null);
  const [alertCount, setAlertCount] = useState(0);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [demoMessage, setDemoMessage] = useState<string | null>(null);
  // Bumped whenever data changes so pages refetch.
  const [dataVersion, setDataVersion] = useState(0);
  const refresh = useCallback(() => setDataVersion((v) => v + 1), []);

  useEffect(() => {
    api.health().then(setHealth).catch((e: Error) => setBackendError(e.message));
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    api
      .alerts()
      .then((a) => setAlertCount(a.length))
      .catch(() => setAlertCount(0));
  }, [dataVersion]);

  async function loadDemo() {
    if (!window.confirm("Replace all saved receipts with the bundled SYNTHETIC sample data?")) return;
    const res = await api.loadDemo(true);
    setDemoMessage(`Loaded ${res.receipts_loaded} synthetic receipts.`);
    refresh();
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>Grocery Price Optimizer</h1>
          <p className="muted">Receipts in, cheapest shopping plan out.</p>
        </div>
        <div className="header-right">
          {alertCount > 0 && (
            <a href="#prices" className="badge badge-ok" aria-label={`${alertCount} price-drop alerts`}>
              {alertCount} price {alertCount === 1 ? "drop" : "drops"} on your watchlist
            </a>
          )}
          {health && (
            <span className={`badge ${health.demo_mode ? "badge-warn" : "badge-ok"}`}>
              {health.demo_mode ? "Demo mode (no API key)" : `LLM extraction: ${health.model}`}
            </span>
          )}
          <button className="secondary" onClick={loadDemo}>
            Load synthetic demo data
          </button>
        </div>
      </header>

      {backendError && (
        <div className="alert error">
          Cannot reach the API ({backendError}). Start it with <code>make api</code>.
        </div>
      )}
      {demoMessage && (
        <div className="alert info" onClick={() => setDemoMessage(null)}>
          {demoMessage} All sample prices are synthetic, not real store prices.
        </div>
      )}

      <nav className="tabs">
        {TABS.map((t) => (
          <a key={t.id} href={`#${t.id}`} className={tab === t.id ? "tab active" : "tab"}>
            {t.label}
          </a>
        ))}
      </nav>

      <main>
        {tab === "upload" && <UploadPage onSaved={refresh} demoMode={health?.demo_mode ?? true} />}
        {tab === "receipts" && <ReceiptsPage version={dataVersion} onChanged={refresh} />}
        {tab === "prices" && (
          <Suspense fallback={<p className="muted">Loading...</p>}>
            <PricesPage version={dataVersion} onWatchlistChanged={refresh} />
          </Suspense>
        )}
        {tab === "plan" && <PlanPage version={dataVersion} />}
        {tab === "insights" && (
          <Suspense fallback={<p className="muted">Loading...</p>}>
            <InsightsPage version={dataVersion} />
          </Suspense>
        )}
      </main>
    </div>
  );
}
