"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useOnline } from "../lib/useOnline";
import { AppProvider, useApp } from "./AppContext";

export const TABS = [
  { id: "upload", label: "Upload receipts" },
  { id: "receipts", label: "Receipts" },
  { id: "prices", label: "Prices" },
  { id: "plan", label: "Plan my trip" },
  { id: "insights", label: "Insights" },
] as const;

function Shell({ children }: { children: ReactNode }) {
  const { health, alertCount, backendError, demoMessage, setDemoMessage, loadDemo } = useApp();
  const online = useOnline();
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const current = TABS.find((t) => pathname === `/${t.id}` || pathname.startsWith(`/${t.id}/`))?.id;

  // Links from before the port looked like /#prices. Send them to the route once.
  useEffect(() => {
    const hash = window.location.hash.replace("#", "");
    if (TABS.some((t) => t.id === hash)) router.replace(`/${hash}`);
  }, [router]);

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>Grocery Price Optimizer</h1>
          <p className="muted">Receipts in, cheapest shopping plan out.</p>
        </div>
        <div className="header-right">
          {alertCount > 0 && (
            <Link href="/prices" className="badge badge-ok">
              {alertCount} price {alertCount === 1 ? "drop" : "drops"} on your watchlist
            </Link>
          )}
          {/* Rendered before /api/health answers too, so the header keeps its height and the
              page below does not jump when the badge text arrives (Lighthouse CLS). */}
          <span
            className={`badge ${health ? (health.demo_mode ? "badge-warn" : "badge-ok") : "badge-pending"}`}
            role="status"
          >
            {health ? (health.demo_mode ? "Demo mode (no API key)" : `LLM extraction: ${health.model}`) : "Checking server..."}
          </span>
          <button className="secondary" onClick={loadDemo}>
            Load synthetic demo data
          </button>
        </div>
      </header>

      {!online && (
        <div className="alert warn offline-banner" role="status">
          You are offline. Prices and insights show the last data this browser saw; saving and
          planning need a connection.
        </div>
      )}
      {backendError && online && (
        <div className="alert error" role="alert">
          Cannot reach the API ({backendError}). Start it with <code>make api</code>.
        </div>
      )}
      {demoMessage && (
        <div className="alert info row gap spread" role="status">
          <span>{demoMessage} All sample prices are synthetic, not real store prices.</span>
          <button className="link" onClick={() => setDemoMessage(null)} aria-label="Dismiss message">
            Dismiss
          </button>
        </div>
      )}

      <nav className="tabs" aria-label="Sections">
        {TABS.map((t) => (
          <Link
            key={t.id}
            href={`/${t.id}`}
            className={current === t.id ? "tab active" : "tab"}
            aria-current={current === t.id ? "page" : undefined}
          >
            {t.label}
          </Link>
        ))}
      </nav>

      <main>{children}</main>
    </div>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <AppProvider>
      <Shell>{children}</Shell>
    </AppProvider>
  );
}
