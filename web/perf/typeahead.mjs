// Typeahead: requests per typed query and time-to-results, with the 200 ms debounce vs without.
//
//   node perf/typeahead.mjs --base http://localhost:8000 --trials 20 --out ../results/typeahead.json
//
// A real browser types a 10-character query into the Prices filter at a steady pace (one key
// every --key-delay ms, default 120 ms, roughly 50 words per minute). For each trial we count
// the /api/products/search requests the page sent and how many the page cancelled, and time
// from the last keystroke until the listbox last re-rendered (the results for the full query).
// Both timestamps are taken inside the page (keydown listener, MutationObserver on the listbox)
// so the measurement does not include the test driver's own round trips.
// "No debounce" is the same build with the delay set to 0 through the component's test hook.
// Both are measured on the local network and under DevTools' "Fast 3G" profile.
import fs from "node:fs";
import { chromium } from "@playwright/test";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, v, i, a) => (v.startsWith("--") ? [...acc, [v.slice(2), a[i + 1]]] : acc), []),
);
const base = args.base ?? "http://localhost:8000";
const trials = Number(args.trials ?? 20);
const keyDelay = Number(args["key-delay"] ?? 120);
const out = args.out ?? "../results/typeahead.json";
const QUERY = "chicken br"; // 10 characters

const FAST_3G = { offline: false, latency: 562.5, downloadThroughput: (1.6 * 1024 * 1024 / 8) * 0.9, uploadThroughput: (750 * 1024 / 8) * 0.9 };
const pct = (xs, p) => {
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.ceil((p / 100) * s.length) - 1)];
};

async function run(browser, { debounce, network }) {
  const context = await browser.newContext({ serviceWorkers: "block" });
  if (!debounce) await context.addInitScript(() => { window.__GPO_TYPEAHEAD_DEBOUNCE_MS = 0; });
  const page = await context.newPage();
  await page.goto(`${base}/prices`);
  const box = page.getByRole("combobox", { name: "Filter products or categories" });
  await box.waitFor();
  if (network) {
    const cdp = await context.newCDPSession(page);
    await cdp.send("Network.enable");
    await cdp.send("Network.emulateNetworkConditions", network);
  }
  let sent = 0, cancelled = 0;
  page.on("request", (r) => r.url().includes("/api/products/search") && sent++);
  page.on("requestfailed", (r) => r.url().includes("/api/products/search") && cancelled++);

  const samples = [];
  for (let t = 0; t < trials; t++) {
    await box.fill("");
    await page.waitForTimeout(400); // let anything from the previous trial settle
    sent = 0; cancelled = 0;
    await box.click();
    // Record the last keydown and the last change to the suggestions list, in page time.
    await page.evaluate(() => {
      window.__lastKey = 0;
      window.__lastRender = 0;
      document.addEventListener("keydown", () => { window.__lastKey = performance.now(); }, { capture: true });
      const list = document.querySelector('[role="listbox"]');
      new MutationObserver(() => { window.__lastRender = performance.now(); })
        .observe(list, { childList: true, subtree: true, characterData: true, attributes: true });
    });
    const finalResponse = page.waitForResponse((r) => r.url().includes(`q=${encodeURIComponent(QUERY)}`), { timeout: 30000 });
    await box.pressSequentially(QUERY, { delay: keyDelay });
    await finalResponse;
    await page.getByRole("option").first().waitFor();
    await page.waitForTimeout(network ? 1500 : 300); // late responses / aborts are still counted
    const ms = Math.round(await page.evaluate(() => window.__lastRender - window.__lastKey));
    samples.push({ requests_sent: sent, requests_cancelled: cancelled, time_to_results_ms: ms });
  }
  await context.close();
  const times = samples.map((s) => s.time_to_results_ms);
  const reqs = samples.map((s) => s.requests_sent);
  return {
    debounce_ms: debounce ? 200 : 0,
    network: network ? "Fast 3G (562.5 ms RTT, 1.44 Mbps down)" : "local (no throttling)",
    mean_requests_per_query: +(reqs.reduce((a, b) => a + b, 0) / reqs.length).toFixed(2),
    mean_requests_cancelled: +(samples.reduce((a, s) => a + s.requests_cancelled, 0) / samples.length).toFixed(2),
    time_to_results_p50_ms: pct(times, 50),
    time_to_results_p95_ms: pct(times, 95),
    samples,
  };
}

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL ?? "chrome" });
const result = { base, query: QUERY, query_chars: QUERY.length, key_delay_ms: keyDelay, trials, runs: [] };
try {
  for (const network of [null, FAST_3G]) {
    for (const debounce of [true, false]) {
      const r = await run(browser, { debounce, network });
      result.runs.push(r);
      console.log(`${r.network.padEnd(40)} debounce ${String(r.debounce_ms).padStart(3)} ms: ${r.mean_requests_per_query} req/query (${r.mean_requests_cancelled} cancelled), p50 ${r.time_to_results_p50_ms} ms, p95 ${r.time_to_results_p95_ms} ms`);
    }
  }
} finally {
  await browser.close();
}
fs.writeFileSync(out, JSON.stringify(result, null, 2) + "\n");
