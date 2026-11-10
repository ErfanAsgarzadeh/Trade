"use strict";
// Cache only public offline presentation assets. Authenticated pages and API responses
// always use the network: never leave private balances/licenses on a shared device.
const CACHE = "trade-offline-v4";
const OFFLINE = "/portal-assets/offline.html";
const PUBLIC_ASSETS = [
  OFFLINE,
  "/portal-assets/titanium.css",
  "/portal-assets/appearance.js",
];
self.addEventListener("install", (event) =>
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PUBLIC_ASSETS)),
  ),
);
self.addEventListener("activate", (event) =>
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith("trade-offline-") && key !== CACHE)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  ),
);
self.addEventListener("fetch", (event) => {
  if (
    event.request.method !== "GET" ||
    new URL(event.request.url).origin !== self.location.origin
  )
    return;
  if (PUBLIC_ASSETS.includes(new URL(event.request.url).pathname)) {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(event.request)),
    );
    return;
  }
  if (event.request.mode === "navigate")
    event.respondWith(
      fetch(event.request).catch(() =>
        caches.open(CACHE).then((cache) => cache.match(OFFLINE)),
      ),
    );
});
