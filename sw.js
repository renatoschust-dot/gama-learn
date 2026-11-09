const CACHE = "gama-learn-v3";
const SHELL = [
  "/", "/index.html", "/app.js", "/style.css",
  "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"
];
const API_CACHE = [
  "/api/version", "/api/graph", "/api/health", "/api/digest",
  "/api/review", "/api/learned", "/api/powers", "/api/sources",
  "/api/lesson", "/api/study", "/api/auth"
];
const API_PREFETCH = [
  "/api/graph", "/api/version", "/api/health", "/api/digest",
  "/api/review?agent=opencode", "/api/learned?agent=opencode", "/api/auth"
];

self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    await c.addAll(SHELL);
    for (const p of API_PREFETCH) {
      try {
        const r = await fetch(p);
        if (r.ok) await c.put(p, r);
      } catch (_) {}
    }
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  if (url.pathname.startsWith("/api/")) {
    if (!API_CACHE.includes(url.pathname)) return;
    e.respondWith(
      fetch(req).then((res) => {
        if (res.ok) caches.open(CACHE).then((c) => c.put(req, res.clone()));
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }

  e.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok) caches.open(CACHE).then((c) => c.put(req, res.clone()));
      return res;
    }).catch(() => caches.match("/")))
  );
});