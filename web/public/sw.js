// Service worker: lets the app shell open with no connection.
//
// - /_next/static/* files have content hashes in their names, so they never change: cache-first.
// - Pages and Next's route payloads: network-first, falling back to the cached copy offline.
// - Nothing is downloaded up front (no precache competing with the first load on a slow
//   network). The page that registered the worker sends the URLs it already loaded, which come
//   from the HTTP cache, and every later same-origin GET is cached as it passes through.
// - /api/* is never cached here. The pages keep their own last-good API data in localStorage
//   (src/lib/lastGood.ts) and label it as stale, which a transparent cache could not do.
const CACHE = "gpo-shell-v1";

self.addEventListener("install", () => self.skipWaiting());

// The first page load happened before this worker existed; cache what it used.
self.addEventListener("message", (event) => {
  if (event.data?.type !== "cache-urls") return;
  const urls = event.data.urls.filter((u) => {
    const url = new URL(u);
    return url.origin === self.location.origin && !url.pathname.startsWith("/api/");
  });
  event.waitUntil(caches.open(CACHE).then((cache) => Promise.all(urls.map((u) => cache.add(u).catch(() => {})))));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(
      caches.match(request).then((hit) => hit ?? fetch(request).then((res) => store(request, res))),
    );
    return;
  }

  event.respondWith(
    fetch(request)
      .then((res) => store(request, res))
      // Route payloads carry a cache-busting ?_rsc= parameter, so match offline copies without it.
      .catch(() => caches.match(request, { ignoreSearch: true }).then((hit) => hit ?? caches.match("/"))),
  );
});

function store(request, res) {
  if (res.ok) {
    const copy = res.clone();
    caches.open(CACHE).then((cache) => cache.put(request, copy));
  }
  return res;
}
