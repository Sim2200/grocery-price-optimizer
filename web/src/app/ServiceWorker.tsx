"use client";

import { useEffect } from "react";

/** Registers public/sw.js in production builds (the dev server would cache stale code), then
 *  hands it the files this page already loaded so the page also opens offline next time. */
export default function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker
      .register("/sw.js")
      .then(() => navigator.serviceWorker.ready)
      .then((reg) => {
        const loaded = performance.getEntriesByType("resource").map((e) => e.name);
        reg.active?.postMessage({ type: "cache-urls", urls: [location.href, ...loaded] });
      })
      .catch(() => {
        // Not fatal: the app works online without it.
      });
  }, []);
  return null;
}
