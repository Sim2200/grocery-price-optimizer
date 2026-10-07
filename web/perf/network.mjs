// Page behaviour on slow and absent networks, before vs after the frontend changes.
//
//   node perf/network.mjs --before http://localhost:8001 --after http://localhost:8000 --runs 3 \
//        --out ../results/network_conditions.json
//
// "before" is the baseline commit's build served by its own backend (no compression), "after"
// is the current build. Throttling uses DevTools' presets through CDP:
//   Fast 3G: 562.5 ms RTT, 1.44 Mbps down, 675 kbps up
//   Slow 3G: 2000 ms RTT, 360 kbps down, 360 kbps up
// Every throttled run starts from a cold browser context (no HTTP cache, no service worker).
// Measured from the start of navigation:
//   first_feedback_ms  first moment <main> shows anything (a skeleton or loading text counts)
//   content_ms         the real content is on screen (price table rows / the spending total)
//   js_kb              JavaScript transferred by the time the content is shown
// Offline: visit /prices and /insights online first, then drop the connection and reload each.
import fs from "node:fs";
import { chromium } from "@playwright/test";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, v, i, a) => (v.startsWith("--") ? [...acc, [v.slice(2), a[i + 1]]] : acc), []),
);
const targets = { before: args.before ?? "http://localhost:8001", after: args.after ?? "http://localhost:8000" };
const runs = Number(args.runs ?? 3);
const out = args.out ?? "../results/network_conditions.json";

const PROFILES = {
  "Fast 3G": { offline: false, latency: 562.5, downloadThroughput: (1.6 * 1024 * 1024 / 8) * 0.9, uploadThroughput: (750 * 1024 / 8) * 0.9 },
  "Slow 3G": { offline: false, latency: 2000, downloadThroughput: (500 * 1024 / 8) * 0.8, uploadThroughput: (500 * 1024 / 8) * 0.8 },
};
const PAGES = { "/prices": "table tbody tr", "/insights": ".big" };
const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};

async function throttledLoad(browser, base, path, profile) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  await cdp.send("Network.emulateNetworkConditions", profile);
  const t0 = Date.now();
  page.goto(base + path).catch(() => {});
  await page.waitForFunction(() => {
    const main = document.querySelector("main");
    return !!main && (main.textContent?.trim().length ?? 0) + main.querySelectorAll(".skeleton").length > 0;
  }, null, { timeout: 180000, polling: 50 });
  const firstFeedback = Date.now() - t0;
  await page.waitForSelector(PAGES[path], { timeout: 180000 });
  const content = Date.now() - t0;
  const jsBytes = await page.evaluate(() =>
    performance.getEntriesByType("resource").filter((e) => e.initiatorType === "script")
      .reduce((a, e) => a + e.transferSize, 0));
  await context.close();
  return { first_feedback_ms: firstFeedback, content_ms: content, js_kb: Math.round(jsBytes / 1024) };
}

async function offline(browser, base) {
  const context = await browser.newContext();
  const page = await context.newPage();
  for (const path of Object.keys(PAGES)) {
    await page.goto(base + path);
    await page.waitForSelector(PAGES[path], { timeout: 30000 });
  }
  await page.waitForTimeout(3000); // let the service worker (after build) finish caching
  await context.setOffline(true);
  const result = {};
  for (const path of Object.keys(PAGES)) {
    const t0 = Date.now();
    let rendered = false;
    try {
      await page.goto(base + path, { timeout: 15000 });
      await page.waitForSelector(PAGES[path], { timeout: 10000 });
      rendered = true;
    } catch {
      // the browser's own "no internet" page, or the app without data
    }
    const text = await page.locator("body").innerText().catch(() => "");
    result[path] = {
      content_rendered: rendered,
      content_ms: rendered ? Date.now() - t0 : null,
      offline_banner: /You are offline/.test(text),
      stale_data_banner: /Showing saved data from/.test(text),
      // Read-only while offline: the watchlist form is hidden on the prices page.
      watchlist_form_hidden: path === "/prices" ? rendered && (await page.getByRole("button", { name: "Watch" }).count()) === 0 : null,
    };
  }
  await context.close();
  return result;
}

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL ?? "chrome" });
const result = { runs, profiles: Object.fromEntries(Object.entries(PROFILES).map(([k, v]) => [k, { rtt_ms: v.latency, down_kbps: Math.round(v.downloadThroughput * 8 / 1024) }])), throttled: {}, offline: {} };
try {
  for (const [name, base] of Object.entries(targets)) {
    result.throttled[name] = {};
    for (const [profileName, profile] of Object.entries(PROFILES)) {
      result.throttled[name][profileName] = {};
      for (const path of Object.keys(PAGES)) {
        const samples = [];
        for (let r = 0; r < runs; r++) samples.push(await throttledLoad(browser, base, path, profile));
        const med = Object.fromEntries(Object.keys(samples[0]).map((k) => [k, median(samples.map((s) => s[k]))]));
        result.throttled[name][profileName][path] = { median: med, samples };
        console.log(`${name.padEnd(7)} ${profileName} ${path.padEnd(10)} first feedback ${med.first_feedback_ms} ms, content ${med.content_ms} ms, JS ${med.js_kb} KiB`);
      }
    }
    result.offline[name] = await offline(browser, base);
    console.log(`${name.padEnd(7)} offline`, JSON.stringify(result.offline[name]));
  }
} finally {
  await browser.close();
}
fs.writeFileSync(out, JSON.stringify(result, null, 2) + "\n");
