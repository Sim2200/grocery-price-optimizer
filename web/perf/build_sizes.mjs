// Parses the route table that `next build` prints and writes per-route sizes as JSON.
//   npm run build | tee build.log ; node perf/build_sizes.mjs build.log ../results/bundle_before.json
// "First Load JS" is what Next.js reports for each route: the route's own chunk plus the shared
// chunks, gzip-compressed sizes.
import fs from "node:fs";
const [, , logPath, outPath] = process.argv;
const text = fs.readFileSync(logPath, "utf8");
const toKb = (n, unit) => (unit === "B" ? Number(n) / 1000 : unit === "MB" ? Number(n) * 1000 : Number(n));
const routes = {};
for (const line of text.split("\n")) {
  const m = line.match(/[┌├└]\s+[○ƒ●λ]?\s*(\/\S*)\s+([\d.]+)\s*(B|kB|MB)\s+([\d.]+)\s*(B|kB|MB)/);
  if (m) routes[m[1]] = { route_kb: toKb(m[2], m[3]), first_load_js_kb: toKb(m[4], m[5]) };
}
const shared = text.match(/First Load JS shared by all\s+([\d.]+)\s*(kB|MB)/);
const out = { source: "next build route table (gzip sizes as reported by Next.js)", shared_first_load_kb: shared ? toKb(shared[1], shared[2]) : null, routes };
fs.writeFileSync(outPath, JSON.stringify(out, null, 2) + "\n");
console.log(JSON.stringify(out));
