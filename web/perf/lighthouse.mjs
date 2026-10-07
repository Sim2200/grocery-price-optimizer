// Lighthouse audits of the built app, mobile emulation, N runs per page, median reported.
//
//   node perf/lighthouse.mjs --base http://localhost:8000 --runs 3 --out ../results/lighthouse_before.json
//
// Uses the locally installed Chrome (CHROME_PATH or chrome-launcher's search). Lighthouse's default
// mobile config applies: Moto G Power emulation, simulated slow 4G (150 ms RTT, 1.6 Mbps) and 4x CPU
// slowdown, so the numbers are comparable between the before and after runs on the same machine,
// not absolute field data.
import fs from "node:fs";
import path from "node:path";
import lighthouse from "lighthouse";
import * as chromeLauncher from "chrome-launcher";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, v, i, a) => (v.startsWith("--") ? [...acc, [v.slice(2), a[i + 1]]] : acc), []),
);
const base = args.base ?? "http://localhost:8000";
const runs = Number(args.runs ?? 3);
const out = args.out ?? "../results/lighthouse.json";
const pages = (args.pages ?? "/,/upload,/prices,/insights,/plan").split(",");

const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};

const chrome = await chromeLauncher.launch({ chromeFlags: ["--headless=new", "--no-sandbox"] });
const result = { base, runs, form_factor: "mobile (Lighthouse default: simulated slow 4G, 4x CPU slowdown)", pages: {} };
try {
  for (const page of pages) {
    const samples = [];
    for (let r = 0; r < runs; r++) {
      const { lhr } = await lighthouse(base + page, { port: chrome.port, output: "json", logLevel: "error" });
      const a = lhr.audits;
      const js = (a["resource-summary"]?.details?.items ?? []).find((i) => i.resourceType === "script");
      samples.push({
        performance: Math.round(lhr.categories.performance.score * 100),
        accessibility: Math.round(lhr.categories.accessibility.score * 100),
        best_practices: Math.round(lhr.categories["best-practices"].score * 100),
        seo: Math.round(lhr.categories.seo.score * 100),
        fcp_ms: a["first-contentful-paint"].numericValue,
        lcp_ms: a["largest-contentful-paint"].numericValue,
        tbt_ms: a["total-blocking-time"].numericValue,
        cls: a["cumulative-layout-shift"].numericValue,
        speed_index_ms: a["speed-index"].numericValue,
        total_bytes: a["total-byte-weight"].numericValue,
        js_transfer_bytes: js?.transferSize ?? 0,
        failing_accessibility_audits: Object.values(lhr.categories.accessibility.auditRefs)
          .map((ref) => a[ref.id])
          .filter((au) => au && au.score !== null && au.score < 1 && au.scoreDisplayMode === "binary")
          .map((au) => au.id),
      });
      process.stderr.write(`${page} run ${r + 1}: perf ${samples.at(-1).performance} a11y ${samples.at(-1).accessibility} LCP ${Math.round(samples.at(-1).lcp_ms)} ms\n`);
    }
    const keys = Object.keys(samples[0]).filter((k) => typeof samples[0][k] === "number");
    const med = Object.fromEntries(keys.map((k) => [k, Math.round(median(samples.map((s) => s[k])) * 1000) / 1000]));
    med.failing_accessibility_audits = [...new Set(samples.flatMap((s) => s.failing_accessibility_audits))];
    result.pages[page] = { median: med, samples };
  }
} finally {
  await chrome.kill();
}
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, JSON.stringify(result, null, 2) + "\n");
for (const [p, v] of Object.entries(result.pages)) {
  const m = v.median;
  console.log(`${p.padEnd(10)} perf ${m.performance}  a11y ${m.accessibility}  bp ${m.best_practices}  LCP ${Math.round(m.lcp_ms)} ms  TBT ${Math.round(m.tbt_ms)} ms  CLS ${m.cls}  JS ${Math.round(m.js_transfer_bytes / 1024)} KiB  fails: ${m.failing_accessibility_audits.join(",") || "-"}`);
}
