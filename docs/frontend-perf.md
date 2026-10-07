# Frontend performance notes

What was slow in the frontend, what changed, what the numbers say, and what the numbers do not say. Every figure is from `results/*.json`, produced by the scripts in `web/perf/` on one laptop.

## What was slow

Two things, and neither was in the React code.

**The charting library loaded before anything else.** `/prices` and `/insights` imported it at the top of the page, so a phone downloaded and parsed it before the price table or the spending total could appear. Lighthouse (mobile emulation) measured 809 KiB of JavaScript on `/prices` and 777 KiB on `/insights`, against 397-398 KiB for the pages without charts; Largest Contentful Paint was 6.1 s and 5.9 s.

**Static files went over the wire uncompressed.** FastAPI serves the Next.js export as plain files and had no compression middleware. Next.js reports the shared first-load JavaScript as 103 kB, but that is the gzip size; Lighthouse saw 398 KiB on the home page, about 4x. On a 1.4 Mbps connection that difference alone is seconds.

## What changed

- `src/grocery_optimizer/api/app.py`: `GZipMiddleware` for responses over 1 KB. This is the one backend change beyond the search endpoint, kept in its own commit.
- `web/src/views/PricesPage.tsx` loads `components/PriceCharts.tsx` with `next/dynamic`, so the charting library is fetched only after a product is selected, into a fixed-height placeholder.
- `web/src/components/SpendChart.tsx`: the three spending breakdowns on `/insights` are CSS bar lists instead of charts. They read better at 360 px and the page no longer needs the charting library at all.
- `web/src/components/Typeahead.tsx` and `GET /api/products/search`: debounced, cancellable product search with the combobox ARIA pattern, used by the prices filter, the watchlist and the list builder.
- `web/src/lib/fetchWithRetry.ts`: a timeout per attempt; GETs retry with exponential backoff and jitter, other methods never retry.
- `web/src/lib/useCachedQuery.ts` and `lastGood.ts`: the last successful prices and insights responses are kept in localStorage and shown read-only with a stale banner when the live request fails. `web/public/sw.js` caches the app shell as it is used so visited pages open offline.
- `web/src/components/Status.tsx`: skeletons, error states with retry. `components/Watchlist.tsx`: optimistic add and remove with rollback.
- `web/src/styles.css`: muted text darkened for 4.5:1 contrast, 24 px targets for text buttons and checkboxes, tables become cards under 640 px. The upload dropzone's `aria-label` was removed so its visible text is its accessible name.

## What the measurements say

Lighthouse 12, mobile emulation (simulated slow 4G, 4x CPU slowdown), 3 runs per page, median, before and after on the same machine (`results/lighthouse_before.json`, `lighthouse_after.json`):

| Page | Performance | Accessibility | LCP | JS transferred |
|---|---|---|---|---|
| / | 90 → 98 | 95 → 100 | 3547 → 2215 ms | 398 → 123 KiB |
| /upload | 93 → 99 | 95 → 100 | 3174 → 1816 ms | 397 → 122 KiB |
| /prices | 74 → 98 | 100 → 100 | 6084 → 2345 ms | 809 → 117 KiB |
| /insights | 71 → 98 | 100 → 100 | 5905 → 2205 ms | 777 → 115 KiB |
| /plan | 93 → 99 | 95 → 100 | 3156 → 1816 ms | 397 → 124 KiB |

Typeahead (`results/typeahead.json`, 10-character query typed at 120 ms per key, 20 trials): without the debounce the page sends 10 requests per query; with it, 1. The debounce costs about 200 ms after the last key: time to results p95 212 ms vs 1 ms locally, 778 ms vs 578 ms on Fast 3G, where the no-debounce run cancelled 9 of its 10 requests.

Network conditions (`results/network_conditions.json`, DevTools throttling, cold cache, median of 3): time to content on `/prices` went from 7.5 s to 3.5 s on Fast 3G and from 25.6 s to 11.0 s on Slow 3G; `/insights` is within 0.1 s of those. First feedback (a skeleton) is unchanged at about 0.7 s and 2.1 s, because it is bound by the round trips to fetch the HTML and the first script. Offline, the old build showed nothing; the new one shows cached prices in 379 ms and insights in 93 ms, with the offline and stale-data banners and no watchlist form.

## What did not help, and what is not claimed

- Next.js' own route table barely moved (103 kB shared before and after). Those numbers already assume gzip and exclude the chart chunk, so they could not show either fix. The Lighthouse transfer column is the one that reflects what a phone downloads.
- The debounce is a trade: fewer requests, slower first results by about the debounce interval. On a fast server with few users, 0 ms would feel snappier.
- All numbers are from one laptop with emulated throttling and CPU slowdown, before and after on the same machine. They are comparable with each other, not with field data.
- The service worker only caches pages that were visited while online. A page never opened cannot open offline.
- Not done: dark mode, a bundle analyzer report, image optimisation (the app has no images to optimise).

## How to reproduce

```bash
# after: this branch
make demo
.venv/bin/uvicorn --factory grocery_optimizer.api.app:create_app --port 8000 &
cd web && npm ci && npm run build > build.log
node perf/build_sizes.mjs build.log ../results/bundle_after.json
node perf/lighthouse.mjs --base http://localhost:8000 --runs 3 --out ../results/lighthouse_after.json
PW_CHANNEL=chrome node perf/typeahead.mjs --trials 20 --out ../results/typeahead.json

# before: the baseline commit in a worktree, served on :8001
git worktree add ../gpo-before 863c358
(cd ../gpo-before/web && ln -s ../../grocery-price-optimizer/web/node_modules node_modules && npm run build)
(cd ../gpo-before && PYTHONPATH=src ../grocery-price-optimizer/.venv/bin/uvicorn --factory grocery_optimizer.api.app:create_app --port 8001 &)
curl -X POST localhost:8001/api/demo/load -H 'content-type: application/json' -d '{"reset":true}'
node perf/lighthouse.mjs --base http://localhost:8001 --runs 3 --out ../results/lighthouse_before.json
PW_CHANNEL=chrome node perf/network.mjs --before http://localhost:8001 --after http://localhost:8000 --runs 3 \
    --out ../results/network_conditions.json
```

`PW_CHANNEL=chrome` uses an installed Google Chrome; omit it after `npx playwright install chromium`.
